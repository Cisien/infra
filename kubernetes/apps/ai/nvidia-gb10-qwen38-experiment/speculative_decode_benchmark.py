#!/usr/bin/env python3
"""Measure cold-cache code-generation speed for vLLM speculative decoding."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import uuid
from pathlib import Path

import benchmark


def coding_prompt() -> str:
    return """You are working in a Python codebase. Return only a unified diff.

File: src/durations.py

Current code:
```python
def parse_duration(value: str) -> int:
    number, unit = value.split()
    return int(number)
```

Task:
- Implement parse_duration for positive integer durations with units ms, s, m, and h.
- Return milliseconds.
- Reject malformed values, zero, negative values, and unsupported units with ValueError.
- Preserve the existing function name and type signature.
- Add focused unittest coverage in tests/test_durations.py.

Do not explain the patch. Emit only the diff.
"""


def prose_prompt() -> str:
    return """Write a concise incident summary in plain text for an internal engineering update.

At 09:14 UTC, a production API began returning elevated 503 errors after a cache-node restart. The on-call engineer drained traffic from the unhealthy node at 09:21 UTC. Error rate returned to normal at 09:24 UTC. The investigation found that the node started before its cache volume mounted. The team will add a mount readiness check and test the restart procedure this week.

Include: impact, timeline, root cause, mitigation, and follow-up actions. Use complete sentences and neutral technical language. Do not use markdown.
"""


def workload_prompt(workload: str) -> str:
    if workload == "coding":
        return coding_prompt()
    if workload == "prose":
        return prose_prompt()
    raise ValueError(f"unsupported workload: {workload}")


def cold_coding_payload(
    model: str, generation_tokens: int, repetition: int, workload: str = "coding"
) -> dict:
    return benchmark.completion_payload(
        model=model,
        prompt=workload_prompt(workload),
        generation_tokens=generation_tokens,
        cache_salt=f"spec-decode-{workload}-{repetition}-{uuid.uuid4().hex}",
    )


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile of an empty list")
    if not 0 < percentile_value <= 1:
        raise ValueError("percentile must be in the range (0, 1]")
    return sorted(values)[math.ceil(len(values) * percentile_value) - 1]


def summarize_generation_cases(cases: list[dict]) -> dict:
    if not cases:
        raise ValueError("at least one benchmark case is required")

    def summary(name: str) -> dict:
        values = [case[name] for case in cases]
        return {
            "min": min(values),
            "median": statistics.median(values),
            "mean": statistics.fmean(values),
            "p95": percentile(values, 0.95),
            "max": max(values),
        }

    return {
        "samples": len(cases),
        "generation_tokens_per_second": summary("generation_tokens_per_second"),
        "generation_seconds": summary("generation_seconds"),
        "time_to_first_token_seconds": summary("time_to_first_token_seconds"),
    }


def run_case(
    api_base: str,
    model: str,
    generation_tokens: int,
    repetition: int,
    timeout: int,
    workload: str,
) -> dict:
    payload = cold_coding_payload(model, generation_tokens, repetition, workload)
    prompt_tokens = benchmark.tokenize(api_base, model, payload["prompt"], timeout)
    result = benchmark.complete(
        api_base, payload, prompt_tokens, generation_tokens, timeout
    )
    result.pop("completion_text")
    result.update(
        {
            "repetition": repetition,
            "workload": workload,
            "cache_salt": payload["cache_salt"],
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--model-revision", default="main")
    parser.add_argument("--workload", choices=("coding", "prose"), default="coding")
    parser.add_argument("--generation-tokens", type=int, default=512)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    if args.generation_tokens < 1:
        parser.error("--generation-tokens must be positive")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.warmup_runs < 0:
        parser.error("--warmup-runs cannot be negative")

    api_base = args.api_base.rstrip("/")
    for repetition in range(1, args.warmup_runs + 1):
        run_case(api_base, args.model, args.generation_tokens, -repetition, args.timeout, args.workload)

    cases = []
    for repetition in range(1, args.repetitions + 1):
        case = run_case(
            api_base, args.model, args.generation_tokens, repetition, args.timeout, args.workload
        )
        print(json.dumps(case), flush=True)
        cases.append(case)

    output = {
        "workload": args.workload,
        "cache_policy": "unique cache_salt for every warmup and measured request",
        "candidate": args.candidate,
        "image_reference": args.image_reference,
        "model_revision": args.model_revision,
        "generation_tokens": args.generation_tokens,
        "warmup_runs": args.warmup_runs,
        "cases": cases,
        "summary": summarize_generation_cases(cases),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["summary"]), flush=True)


if __name__ == "__main__":
    main()
