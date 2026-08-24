# DSpark speculative-token sweep plan

## Goal

Select the `num_speculative_tokens` value that improves single-request coding-token generation speed without an unacceptable latency, cache, or stability cost.

This plan does not apply a Kubernetes manifest or start a Job.

## Benchmark workload

Use `speculative_decode_benchmark.py`.

The workload asks the model to return only a unified diff that implements and tests a Python duration parser. It requires correct handling for `ms`, `s`, `m`, and `h`, and invalid-input coverage. The prompt is coding-focused and has a fixed text body.

Each request uses a unique `cache_salt`. This prevents prefix-cache reuse from changing decode measurements. The benchmark requests exactly 512 generated tokens with temperature `0`.

For each configuration:

1. Wait for the Deployment to report `updatedReplicas=1` and `availableReplicas=1`. Do not use a label-only Pod readiness wait after a Deployment patch: it can match the old, terminating ReplicaSet Pod.
2. Run one unrecorded warmup request.
3. Run five serial measured requests.
4. Save the JSON output with the image digest, model revision, and candidate value.
5. Record the Prometheus counter deltas over the measured window.

Run only one client request at a time. Do not mix this test with the long-prefix cache benchmark. That is a separate prefill/cache experiment.

## Candidate order

Test these candidates in this order:

| Order | `num_speculative_tokens` | Purpose |
|---:|---:|---|
| 1 | `0` | Control: remove `--speculative-config`; retain all other runtime settings. |
| 2 | `1` | Minimal DSpark look-ahead. |
| 3 | `2` | Small look-ahead. |
| 4 | `3` | Moderate look-ahead. |
| 5 | `5` | Larger look-ahead. |
| 6 | `7` | Current production setting. |
| 7 | `9` | High look-ahead; stop if it causes memory, latency, or stability regressions. |

For every candidate, change only the speculative configuration. Keep the pinned image, target model, draft model, model name, context length, sequence limit, cache setting, GPU allocation, and prompt unchanged.

## Later benchmark command

Use this command only when the GPU and cluster are available for this test:

```sh
python3 speculative_decode_benchmark.py \
  --api-base http://nvidia-gb10-qwen38.ai.svc.cluster.local:8080 \
  --model competent-robot \
  --candidate <candidate> \
  --image-reference <pinned-image-digest> \
  --generation-tokens 512 \
  --warmup-runs 1 \
  --repetitions 5 \
  --output /tmp/dspark-speculative-<candidate>.json
```

## Measurements

The benchmark JSON supplies these per-request values and summaries:

- generation tokens per second: min, median, mean, p95, and max;
- generation duration: min, median, mean, p95, and max;
- time to first token: min, median, mean, p95, and max.

Also capture these Prometheus series before and after each five-request sample window, filtered to `namespace="ai", service="nvidia-gb10-qwen38"`:

- `vllm:spec_decode_num_draft_tokens_total`;
- `vllm:spec_decode_num_accepted_tokens_total`;
- `vllm:prefix_cache_hits_total` and `vllm:prefix_cache_queries_total`;
- `vllm:kv_cache_usage_perc`;
- `vllm:num_preemptions_total`;
- TTFT and inter-token latency histograms.

Calculate the draft acceptance ratio as accepted draft tokens divided by drafted tokens. It is diagnostic data, not the selection metric by itself.

## Selection rule

Choose the smallest candidate that has the highest median generation-token rate, provided that it meets all of these gates relative to candidate `0`:

1. No Pod restart, inference error, request timeout, or scheduler preemption.
2. p95 TTFT does not increase by more than 10%.
3. p95 generation-token rate does not regress.
4. KV-cache usage remains below the level that causes preemption or reduced required concurrency.
5. The accepted/drafted ratio is non-zero and is stable across measured requests.

If two candidates are within 3% median generation-token speed, choose the smaller value. It uses fewer draft/KV resources and has less risk at concurrent load.

## Follow-up validation

After selecting a single-request winner, run a separate small concurrency test at the normal `--max-num-seqs` limit. Use the same coding workload and compare the winner with candidate `0`. Keep prefix caching enabled but retain unique cache salts. Do not promote a candidate based only on serial speed if it reduces concurrent throughput or causes preemption.
