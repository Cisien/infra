"""Immutable local result records for evaluator Jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from .candidate import Candidate


@dataclass(frozen=True)
class RunResult:
    run_id: str
    candidate_id: str
    benchmark: str
    benchmark_revision: str
    seed: int
    status: str
    created_at: str

    @classmethod
    def create(
        cls, candidate: Candidate, benchmark: str, benchmark_revision: str, seed: int
    ) -> "RunResult":
        return cls(
            run_id=candidate.run_id(benchmark, benchmark_revision, seed),
            candidate_id=candidate.candidate_id,
            benchmark=benchmark,
            benchmark_revision=benchmark_revision,
            seed=seed,
            status="created",
            created_at=datetime.now(UTC).isoformat(),
        )


def write_run_metadata(result_dir: Path, result: RunResult) -> Path:
    result_dir.mkdir(parents=True, exist_ok=True)
    destination = result_dir / "run.json"
    content = json.dumps(asdict(result), indent=2, sort_keys=True) + "\n"
    if destination.exists():
        existing = destination.read_text()
        if existing != content:
            raise FileExistsError(f"refusing to overwrite immutable run record: {destination}")
        return destination
    destination.write_text(content)
    return destination
