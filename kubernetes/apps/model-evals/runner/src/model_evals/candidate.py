"""Candidate validation and reproducible run identity."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


class ValidationError(ValueError):
    """Raised when a candidate cannot produce a reproducible evaluation."""


def _required(mapping: dict[str, Any], name: str) -> Any:
    value = mapping.get(name)
    if value in (None, ""):
        raise ValidationError(f"missing required field: {name}")
    return value


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    model_source: str
    model_revision: str
    chat_template_revision: str
    runtime_engine: str
    runtime_image: str
    runtime_version: str
    max_model_len: int
    max_num_seqs: int
    hardware_profile: str
    node_selector: dict[str, str]
    gpu_resource: str
    gpu_count: int
    tolerations: tuple[dict[str, str], ...]
    model_cache_claim: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candidate":
        model = _required(data, "model")
        runtime = _required(data, "runtime")
        serving = _required(data, "serving")
        scheduling = _required(data, "scheduling")
        if not isinstance(model, dict) or not isinstance(runtime, dict):
            raise ValidationError("model and runtime must be mappings")
        image = str(_required(runtime, "image"))
        if "@sha256:" not in image:
            raise ValidationError("runtime.image must be pinned by sha256 digest")
        engine = str(_required(runtime, "engine"))
        if engine not in {"vllm", "llama-cpp"}:
            raise ValidationError("runtime.engine must be vllm or llama-cpp")
        max_model_len = int(_required(serving, "max_model_len"))
        max_num_seqs = int(_required(serving, "max_num_seqs"))
        gpu_count = int(_required(scheduling, "gpu_count"))
        node_selector = _required(scheduling, "node_selector")
        tolerations = _required(scheduling, "tolerations")
        if max_model_len < 1 or max_num_seqs < 1 or gpu_count < 1:
            raise ValidationError("serving and GPU values must be positive")
        if not isinstance(node_selector, dict) or not node_selector:
            raise ValidationError("scheduling.node_selector must be a non-empty mapping")
        if not isinstance(tolerations, list) or not tolerations or not all(
            isinstance(item, dict) for item in tolerations
        ):
            raise ValidationError("scheduling.tolerations must be a non-empty list of mappings")
        return cls(
            candidate_id=str(_required(data, "candidate_id")),
            model_source=str(_required(model, "source")),
            model_revision=str(_required(model, "revision")),
            chat_template_revision=str(_required(model, "chat_template_revision")),
            runtime_engine=engine,
            runtime_image=image,
            runtime_version=str(_required(runtime, "version")),
            max_model_len=max_model_len,
            max_num_seqs=max_num_seqs,
            hardware_profile=str(_required(data, "hardware_profile")),
            node_selector={str(key): str(value) for key, value in node_selector.items()},
            gpu_resource=str(_required(scheduling, "gpu_resource")),
            gpu_count=gpu_count,
            tolerations=tuple(
                {str(key): str(value) for key, value in item.items()} for item in tolerations
            ),
            model_cache_claim=str(_required(data, "model_cache_claim")),
        )

    def run_id(self, benchmark: str, benchmark_revision: str, seed: int) -> str:
        payload = {
            "candidate": self.as_dict(),
            "benchmark": benchmark,
            "benchmark_revision": benchmark_revision,
            "seed": seed,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model": {
                "source": self.model_source,
                "revision": self.model_revision,
                "chat_template_revision": self.chat_template_revision,
            },
            "runtime": {
                "engine": self.runtime_engine,
                "image": self.runtime_image,
                "version": self.runtime_version,
            },
            "serving": {
                "max_model_len": self.max_model_len,
                "max_num_seqs": self.max_num_seqs,
            },
            "hardware_profile": self.hardware_profile,
            "scheduling": {
                "node_selector": self.node_selector,
                "gpu_resource": self.gpu_resource,
                "gpu_count": self.gpu_count,
                "tolerations": list(self.tolerations),
            },
            "model_cache_claim": self.model_cache_claim,
        }
