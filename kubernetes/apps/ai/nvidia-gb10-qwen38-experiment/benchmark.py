#!/usr/bin/env python3
"""Measure uncached prompt and generation performance through a vLLM API."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict, timeout: int):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urlopen(request, timeout=timeout)


def tokenize(api_base: str, model: str, prompt: str, timeout: int) -> int:
    with post_json(
        f"{api_base}/tokenize",
        {"model": model, "prompt": prompt, "add_special_tokens": False},
        timeout,
    ) as response:
        return len(json.load(response)["tokens"])


def completion_payload(
    model: str,
    prompt: str,
    generation_tokens: int,
    cache_salt: str | None,
) -> dict:
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": generation_tokens,
        "min_tokens": generation_tokens,
        "ignore_eos": True,
        "stream": True,
        "stream_options": {"include_usage": True},
        "return_token_ids": True,
    }
    if cache_salt is not None:
        payload["cache_salt"] = cache_salt
    return payload


def next_turn_prompt(previous_prompt: str, completion: str, turn: int) -> str:
    return f"{previous_prompt}{completion}\nUser: Continue turn {turn}.\nAssistant:"


def cache_benefit_verified(ttfts: list[float], max_ratio: float) -> bool:
    if len(ttfts) < 2:
        raise ValueError("multi-turn cache verification requires at least two turns")
    return all(ttft / ttfts[0] <= max_ratio for ttft in ttfts[1:])


def sized_prompt(api_base: str, model: str, target_tokens: int, timeout: int) -> tuple[str, str]:
    nonce = uuid.uuid4().hex
    prompt = f" benchmark-{target_tokens}-{nonce}"
    seed_tokens = tokenize(api_base, model, prompt, timeout)
    prompt += " token" * (target_tokens - seed_tokens)
    tokenized_prompt_tokens = tokenize(api_base, model, prompt, timeout)
    if tokenized_prompt_tokens != target_tokens:
        raise RuntimeError(
            f"prompt tokenization changed: expected {target_tokens}, got "
            f"{tokenized_prompt_tokens}"
        )
    return prompt, nonce


def complete(
    api_base: str,
    payload: dict,
    prompt_tokens: int,
    generation_tokens: int,
    timeout: int,
) -> dict:
    started = time.monotonic()
    first_token_at = None
    last_token_at = None
    usage = None
    event_count = 0
    streamed_completion_tokens = 0
    completion_parts = []
    with post_json(f"{api_base}/v1/completions", payload, timeout) as response:
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            if data == "[DONE]":
                break
            event = json.loads(data)
            event_count += 1
            now = time.monotonic()
            choices = event.get("choices", [])
            for choice in choices:
                text = choice.get("text", "")
                if text:
                    completion_parts.append(text)
            if any(choice.get("text") for choice in choices):
                if first_token_at is None:
                    first_token_at = now
                last_token_at = now
            streamed_completion_tokens += sum(
                len(choice.get("token_ids", [])) for choice in choices
            )
            if event.get("usage") is not None:
                usage = event["usage"]
                break
            if streamed_completion_tokens >= generation_tokens:
                break

    finished = time.monotonic()
    if first_token_at is None or last_token_at is None:
        raise RuntimeError("stream response did not contain generated tokens")

    completion_tokens = (
        usage["completion_tokens"] if usage is not None else streamed_completion_tokens
    )
    generation_seconds = max(last_token_at - first_token_at, 0.001)
    return {
        "prompt_tokens": usage["prompt_tokens"] if usage is not None else prompt_tokens,
        "completion_tokens": completion_tokens,
        "time_to_first_token_seconds": first_token_at - started,
        "generation_seconds": generation_seconds,
        "generation_tokens_per_second": completion_tokens / generation_seconds,
        "total_seconds": finished - started,
        "event_count": event_count,
        "completion_text": "".join(completion_parts),
    }


def benchmark_case(
    api_base: str,
    model: str,
    target_tokens: int,
    generation_tokens: int,
    timeout: int,
) -> dict:
    prompt, nonce = sized_prompt(api_base, model, target_tokens, timeout)
    request_id = str(uuid.uuid4())
    payload = completion_payload(
        model, prompt, generation_tokens, f"qwen38-performance-cold-{request_id}"
    )
    result = complete(api_base, payload, target_tokens, generation_tokens, timeout)
    result.update({
        "target_prompt_tokens": target_tokens,
        "prompt_nonce": nonce,
        "cache_salt": payload["cache_salt"],
    })
    return result


def benchmark_multi_turn_case(
    api_base: str,
    model: str,
    target_tokens: int,
    generation_tokens: int,
    turns: int,
    max_follow_up_ttft_ratio: float,
    timeout: int,
) -> dict:
    prompt, nonce = sized_prompt(api_base, model, target_tokens, timeout)
    turn_results = []
    for turn in range(1, turns + 1):
        prompt_tokens = tokenize(api_base, model, prompt, timeout)
        result = complete(
            api_base,
            completion_payload(model, prompt, generation_tokens, cache_salt=None),
            prompt_tokens,
            generation_tokens,
            timeout,
        )
        completion = result.pop("completion_text")
        result["turn"] = turn
        turn_results.append(result)
        prompt = next_turn_prompt(prompt, completion, turn + 1)

    ttfts = [result["time_to_first_token_seconds"] for result in turn_results]
    follow_up_ratios = [ttft / ttfts[0] for ttft in ttfts[1:]]
    return {
        "target_initial_prompt_tokens": target_tokens,
        "turns": turn_results,
        "prompt_nonce": nonce,
        "cache_salt": None,
        "max_follow_up_ttft_ratio": max_follow_up_ttft_ratio,
        "follow_up_ttft_ratios": follow_up_ratios,
        "cache_benefit_verified": cache_benefit_verified(
            ttfts, max_follow_up_ttft_ratio
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", required=True)
    parser.add_argument("--generation-tokens", type=int, default=128)
    parser.add_argument(
        "--multi-turns",
        type=int,
        default=1,
        help="Run this many turns with a shared prefix and vLLM prefix caching.",
    )
    parser.add_argument(
        "--max-follow-up-ttft-ratio",
        type=float,
        default=0.5,
        help="Fail multi-turn verification if a follow-up TTFT exceeds this ratio of turn 1.",
    )
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    if args.multi_turns < 1:
        parser.error("--multi-turns must be at least 1")
    if args.multi_turns > 1 and args.max_follow_up_ttft_ratio <= 0:
        parser.error("--max-follow-up-ttft-ratio must be positive")

    results = []
    cache_verification_failed = False
    for size in args.sizes:
        if args.multi_turns == 1:
            result = benchmark_case(
                args.api_base.rstrip("/"),
                args.model,
                size,
                args.generation_tokens,
                args.timeout,
            )
            result.pop("completion_text")
        else:
            result = benchmark_multi_turn_case(
                args.api_base.rstrip("/"),
                args.model,
                size,
                args.generation_tokens,
                args.multi_turns,
                args.max_follow_up_ttft_ratio,
                args.timeout,
            )
            cache_verification_failed |= not result["cache_benefit_verified"]
        print(json.dumps(result), flush=True)
        results.append(result)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    if cache_verification_failed:
        raise RuntimeError(
            "follow-up turn TTFT was on the scale of a cache miss; inspect output"
        )


if __name__ == "__main__":
    main()
