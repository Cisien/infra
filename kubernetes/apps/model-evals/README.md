# Model evaluation runner

This directory defines an isolated, internal-only Kubernetes boundary for public-model evaluations. It compares a pinned candidate system: model revision, runtime image digest, serving limits, hardware profile, and a pinned benchmark revision.

## Safety properties

- `model-evals` has baseline Pod Security Admission labels.
- NetworkPolicy denies all traffic by default. Evaluators can reach only candidate Services on TCP 8080 and cluster DNS. Candidate Pods accept only evaluator and monitoring ingress.
- Candidate render output creates only a `Deployment` and `ClusterIP` `Service`. It does not create a Gateway, HTTPRoute, Ingress, LoadBalancer Service, LiteLLM model, or DNS object.
- The example candidate is a ConfigMap only. It starts no inference workload and uses no GPU.
- `storage.example.yaml` is not deployed. Select a real retained StorageClass through live cluster discovery before enabling result storage.

## Initial benchmark revisions

The runner records these values but does not bundle benchmark adapters yet:

- MMLU-Pro: `TIGER-Lab/MMLU-Pro` repository revision selected at run creation.
- GPQA Diamond: `idavidrein/gpqa` repository revision selected at run creation.
- LiveCodeBench: release date and repository revision selected at run creation.

SWE-bench Verified uses the separately pinned `mini-SWE-agent==2.4.6` adapter and rootless local Podman task sandboxes. It is intentionally launched outside the base Kustomization because the per-instance benchmark images are Docker-compatible x86_64 containers. The agent calls the authenticated internal LiteLLM Gateway directly; it does not use a `kubectl port-forward`. The launch and status commands are:

```bash
scripts/model-evals-swebench-run
scripts/model-evals-swebench-status
scripts/model-evals-swebench-status --watch 30
```

The launcher records `run-status.json` in its result directory. The status command reports durable prediction progress, active agent PIDs, and active Podman task sandboxes. A completed agent phase still requires the official SWE-bench harness to score generated patches.

The launcher reads the LiteLLM key from `LITELLM_API_KEY` when it is set, or otherwise from the local `~/litellm-key.txt` file. It does not write or print the key.

## Local checks

```bash
PYTHONPATH=kubernetes/apps/model-evals/runner/src \
  python -m unittest discover -s kubernetes/apps/model-evals/runner/tests -v
kubectl kustomize kubernetes/apps/model-evals
```

## Render a candidate Deployment

Candidate files use JSON syntax, which is valid YAML, so the standard-library runner can validate them without adding a YAML parser dependency.

```bash
scripts/model-evals-render \
  kubernetes/apps/model-evals/example-candidate.json \
  mmlu-pro 2026-08-01 7 > /tmp/candidate.yaml
```

Review the rendered YAML before any apply. The runner does not apply Kubernetes resources.

## Create an immutable run record

```bash
scripts/model-evals-submit \
  kubernetes/apps/model-evals/example-candidate.json \
  mmlu-pro 2026-08-01 7 /tmp/model-eval-results
scripts/model-evals-status /tmp/model-eval-results/<run-id>
scripts/model-evals-report /tmp/model-eval-results
```
