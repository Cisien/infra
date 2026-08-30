"""Status helpers for locally isolated SWE-bench runs."""

import json
from pathlib import Path
from typing import Any


def write_run_status(output_dir: Path, state: str, exit_code: int | None = None, **details: Any) -> None:
    """Persist the current run state without leaving a partial JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "exit_code": exit_code, **details}
    temporary_path = output_dir / ".run-status.json.tmp"
    temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary_path.replace(output_dir / "run-status.json")


def collect_run_status(output_dir: Path, total_instances: int = 500) -> dict[str, Any]:
    """Return progress from the prediction and durable run-status files."""
    predictions_path = output_dir / "preds.json"
    predictions: dict[str, Any] = {}
    if predictions_path.exists():
        predictions = json.loads(predictions_path.read_text())

    status_path = output_dir / "run-status.json"
    run_status: dict[str, Any] = {}
    if status_path.exists():
        run_status = json.loads(status_path.read_text())

    trajectory_ids = set()
    failed_ids = set()
    for trajectory_path in output_dir.glob("*/*.traj.json"):
        trajectory = json.loads(trajectory_path.read_text())
        instance_id = trajectory.get("instance_id", trajectory_path.parent.name)
        trajectory_ids.add(instance_id)
        if trajectory.get("info", {}).get("exception_str"):
            failed_ids.add(instance_id)

    failed_ids.update(set(predictions) - trajectory_ids)
    failed = len(failed_ids)

    state = run_status.get("state", "unknown")
    if state == "complete" and failed:
        state = "incomplete"

    completed = len(predictions)
    submitted = sum(bool(prediction.get("model_patch")) for prediction in predictions.values())
    return {
        "state": state,
        "exit_code": run_status.get("exit_code"),
        "completed_instances": completed,
        "failed_instances": failed,
        "remaining_instances": max(total_instances - completed, 0),
        "submitted_patches": submitted,
        "total_instances": total_instances,
        "agent_pid": run_status.get("agent_pid"),
        "port_forward_pid": run_status.get("port_forward_pid"),
    }
