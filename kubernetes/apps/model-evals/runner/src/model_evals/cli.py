"""Command-line entry points for offline candidate validation and run records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .candidate import Candidate
from .manifest import render_candidate
from .results import RunResult, write_run_metadata


def _candidate(path: str) -> Candidate:
    return Candidate.from_dict(json.loads(Path(path).read_text()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model-evals")
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser("render")
    render.add_argument("candidate")
    render.add_argument("benchmark")
    render.add_argument("benchmark_revision")
    render.add_argument("seed", type=int)

    create = commands.add_parser("create-run")
    create.add_argument("candidate")
    create.add_argument("benchmark")
    create.add_argument("benchmark_revision")
    create.add_argument("seed", type=int)
    create.add_argument("result_root")

    args = parser.parse_args(argv)
    candidate = _candidate(args.candidate)
    run_id = candidate.run_id(args.benchmark, args.benchmark_revision, args.seed)
    if args.command == "render":
        print(render_candidate(candidate, run_id), end="")
        return 0

    result = RunResult.create(candidate, args.benchmark, args.benchmark_revision, args.seed)
    path = write_run_metadata(Path(args.result_root) / result.run_id, result)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
