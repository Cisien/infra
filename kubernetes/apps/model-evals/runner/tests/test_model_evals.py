import json
import tempfile
import unittest
from pathlib import Path

from model_evals.candidate import Candidate, ValidationError
from model_evals.cli import main
from model_evals.manifest import render_candidate, render_evaluator_job
from model_evals.results import RunResult, write_run_metadata
from model_evals.swebench import collect_run_status, write_run_status


class CandidateTests(unittest.TestCase):
    def candidate_data(self):
        return {
            "candidate_id": "example-vllm",
            "model": {
                "source": "example/model",
                "revision": "0123456789abcdef",
                "chat_template_revision": "0123456789abcdef",
            },
            "runtime": {
                "engine": "vllm",
                "image": "example/runtime@sha256:" + "a" * 64,
                "version": "1.0.0",
            },
            "serving": {"max_model_len": 32768, "max_num_seqs": 1},
            "hardware_profile": "nvidia-gb10-single-gpu",
            "scheduling": {
                "node_selector": {"ai.cisien.com/accelerator": "gb10"},
                "gpu_resource": "nvidia.com/gpu.shared",
                "gpu_count": 1,
                "tolerations": [
                    {
                        "key": "ai.cisien.com/gpu",
                        "operator": "Equal",
                        "value": "true",
                        "effect": "NoSchedule",
                    }
                ],
            },
            "model_cache_claim": "example-model-cache",
        }

    def test_candidate_requires_digest_pinned_image(self):
        data = self.candidate_data()
        data["runtime"]["image"] = "example/runtime:latest"

        with self.assertRaises(ValidationError):
            Candidate.from_dict(data)

    def test_candidate_run_id_is_stable(self):
        candidate = Candidate.from_dict(self.candidate_data())

        self.assertEqual(
            candidate.run_id("mmlu-pro", "2026-08-01", 7),
            candidate.run_id("mmlu-pro", "2026-08-01", 7),
        )

    def test_renderer_keeps_service_cluster_internal(self):
        candidate = Candidate.from_dict(self.candidate_data())
        rendered = render_candidate(candidate, "mmlu-pro-2026-08-01")

        self.assertIn("kind: Deployment", rendered)
        self.assertIn("kind: Service", rendered)
        self.assertIn("type: ClusterIP", rendered)
        self.assertNotIn("LoadBalancer", rendered)
        self.assertNotIn("HTTPRoute", rendered)
        self.assertIn("automountServiceAccountToken: false", rendered)
        self.assertIn("claimName: example-model-cache", rendered)
        self.assertIn("effect: 'NoSchedule'", rendered)

    def test_run_metadata_is_immutable(self):
        candidate = Candidate.from_dict(self.candidate_data())
        result = RunResult.create(candidate, "mmlu-pro", "2026-08-01", 7)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_run_metadata(path, result)
            write_run_metadata(path, result)
            metadata = json.loads((path / "run.json").read_text())

        self.assertEqual(metadata["run_id"], result.run_id)

    def test_evaluator_job_uses_only_internal_candidate_service(self):
        candidate = Candidate.from_dict(self.candidate_data())

        rendered = render_evaluator_job(
            candidate,
            "mmlu-pro",
            "2026-08-01",
            7,
            "example/runner@sha256:" + "b" * 64,
            "evaluation-results",
        )

        self.assertIn("kind: Job", rendered)
        self.assertIn("backoffLimit: 0", rendered)
        self.assertIn("model-evals.cisien.com/role: 'evaluator'", rendered)
        self.assertIn("base_url=http://eval-", rendered)
        self.assertIn("claimName: evaluation-results", rendered)
        self.assertNotIn("LoadBalancer", rendered)

    def test_create_run_command_writes_result_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidate.json"
            candidate_path.write_text(json.dumps(self.candidate_data()))
            result_root = Path(directory) / "results"

            exit_code = main(
                ["create-run", str(candidate_path), "mmlu-pro", "2026-08-01", "7", str(result_root)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(list(result_root.glob("*/run.json"))), 1)

    def test_swebench_status_counts_predictions_and_marks_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "preds.json").write_text(
                json.dumps(
                    {
                        "example__one": {"model_patch": "diff --git a/a b/a"},
                        "example__two": {"model_patch": ""},
                    }
                )
            )
            for instance_id in ("example__one", "example__two"):
                instance = output / instance_id
                instance.mkdir()
                (instance / f"{instance_id}.traj.json").write_text(
                    json.dumps({"instance_id": instance_id, "info": {"exit_status": "Submitted"}})
                )
            (output / "run-status.json").write_text(json.dumps({"state": "complete", "exit_code": 0}))

            status = collect_run_status(output, total_instances=500)

        self.assertEqual(status["completed_instances"], 2)
        self.assertEqual(status["remaining_instances"], 498)
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["exit_code"], 0)

    def test_swebench_status_marks_completed_run_incomplete_when_trajectory_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            instance = output / "example__one"
            instance.mkdir()
            (output / "preds.json").write_text(
                json.dumps({"example__one": {"model_patch": ""}})
            )
            (instance / "example__one.traj.json").write_text(
                json.dumps({"instance_id": "example__one", "info": {"exception_str": "Connection error"}})
            )
            (output / "run-status.json").write_text(json.dumps({"state": "complete", "exit_code": 0}))

            status = collect_run_status(output, total_instances=1)

        self.assertEqual(status["failed_instances"], 1)
        self.assertEqual(status["state"], "incomplete")

    def test_swebench_status_marks_prediction_without_trajectory_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "preds.json").write_text(
                json.dumps({"example__one": {"model_patch": ""}})
            )
            (output / "run-status.json").write_text(json.dumps({"state": "complete", "exit_code": 0}))

            status = collect_run_status(output, total_instances=1)

        self.assertEqual(status["failed_instances"], 1)
        self.assertEqual(status["state"], "incomplete")

    def test_swebench_status_writer_records_terminal_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_run_status(output, "failed", exit_code=7)

            status = collect_run_status(output)

        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["exit_code"], 7)

    def test_swebench_status_preserves_recorded_process_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_run_status(output, "running", agent_pid=123, port_forward_pid=456)

            status = collect_run_status(output)

        self.assertEqual(status["agent_pid"], 123)
        self.assertEqual(status["port_forward_pid"], 456)


if __name__ == "__main__":
    unittest.main()
