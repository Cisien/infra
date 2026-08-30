"""Render internal-only candidate server resources."""

from __future__ import annotations

from .candidate import Candidate


def _mapping(values: dict[str, str], indent: int) -> str:
    prefix = " " * indent
    return "\n".join(f"{prefix}{key}: {value!r}" for key, value in values.items())


def _tolerations(values: tuple[dict[str, str], ...], indent: int) -> str:
    prefix = " " * indent
    lines: list[str] = []
    for value in values:
        for index, (key, item) in enumerate(value.items()):
            marker = "- " if index == 0 else "  "
            lines.append(f"{prefix}{marker}{key}: {item!r}")
    return "\n".join(lines)


def render_candidate(candidate: Candidate, run_id: str) -> str:
    name = f"eval-{run_id}"
    labels = {
        "app.kubernetes.io/name": name,
        "model-evals.cisien.com/run-id": run_id,
        "model-evals.cisien.com/candidate-id": candidate.candidate_id,
        "model-evals.cisien.com/role": "candidate",
    }
    rendered_root_labels = _mapping(labels, 4)
    rendered_pod_labels = _mapping(labels, 8)
    selector = _mapping(candidate.node_selector, 8)
    tolerations = _tolerations(candidate.tolerations, 8)
    args = [
        candidate.model_source,
        "--served-model-name" if candidate.runtime_engine == "vllm" else "--alias",
        candidate.candidate_id,
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--max-model-len" if candidate.runtime_engine == "vllm" else "--ctx-size",
        str(candidate.max_model_len),
    ]
    if candidate.runtime_engine == "vllm":
        args.extend(["--max-num-seqs", str(candidate.max_num_seqs)])
    argument_lines = "\n".join(f"            - {value!r}" for value in args)
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: model-evals
  labels:
{rendered_root_labels}
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: {name}
  template:
    metadata:
      labels:
{rendered_pod_labels}
    spec:
      automountServiceAccountToken: false
      serviceAccountName: candidate-server
      nodeSelector:
{selector}
      tolerations:
{tolerations}
      containers:
        - name: inference
          image: {candidate.runtime_image!r}
          args:
{argument_lines}
          ports:
            - name: http
              containerPort: 8080
          resources:
            requests:
              {candidate.gpu_resource}: {candidate.gpu_count}
            limits:
              {candidate.gpu_resource}: {candidate.gpu_count}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
          readinessProbe:
            httpGet:
              path: /health
              port: http
          livenessProbe:
            httpGet:
              path: /health
              port: http
          volumeMounts:
            - name: model-cache
              mountPath: /models
              readOnly: true
      volumes:
        - name: model-cache
          persistentVolumeClaim:
            claimName: {candidate.model_cache_claim}
---
apiVersion: v1
kind: Service
metadata:
  name: {name}
  namespace: model-evals
  labels:
{rendered_root_labels}
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: {name}
  ports:
    - name: http
      port: 8080
      targetPort: http
"""


def render_evaluator_job(
    candidate: Candidate,
    benchmark: str,
    benchmark_revision: str,
    seed: int,
    runner_image: str,
    results_claim: str,
) -> str:
    """Render one bounded lm-eval Job for a ClusterIP candidate Service."""
    if "@sha256:" not in runner_image:
        raise ValueError("runner_image must be pinned by sha256 digest")
    run_id = candidate.run_id(benchmark, benchmark_revision, seed)
    service_name = f"eval-{run_id}"
    return f"""apiVersion: batch/v1
kind: Job
metadata:
  name: evaluate-{run_id}
  namespace: model-evals
  labels:
    model-evals.cisien.com/run-id: {run_id!r}
    model-evals.cisien.com/role: 'evaluator'
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 7200
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        model-evals.cisien.com/run-id: {run_id!r}
        model-evals.cisien.com/role: 'evaluator'
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      serviceAccountName: evaluator
      containers:
        - name: lm-eval
          image: {runner_image!r}
          command: ["lm_eval"]
          args:
            - --model
            - local-completions
            - --model_args
            - model={candidate.candidate_id},base_url=http://{service_name}.model-evals.svc.cluster.local:8080/v1,num_concurrent=1
            - --tasks
            - {benchmark!r}
            - --seed
            - {str(seed)!r}
            - --output_path
            - /results/{run_id}/{benchmark_revision}
          resources:
            requests:
              cpu: '4'
              memory: 16Gi
            limits:
              cpu: '4'
              memory: 16Gi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
          volumeMounts:
            - name: results
              mountPath: /results
      volumes:
        - name: results
          persistentVolumeClaim:
            claimName: {results_claim}
"""
