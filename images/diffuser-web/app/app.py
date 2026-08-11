#!/usr/bin/env python3
"""Small FLUX text-to-image web service."""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, stream_with_context
from werkzeug.datastructures import FileStorage
from PIL import Image


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("FLUX_OUTPUT_DIR", str(APP_DIR / "outputs")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path(os.getenv("HF_HUB_CACHE", str(APP_DIR / "hf-cache" / "hub")))

os.environ.setdefault("HF_HUB_CACHE", str(CACHE_DIR))

MODEL_ID = os.getenv("MODEL_ID", os.getenv("FLUX_MODEL_ID", "kpsss34/FHDR_Uncensored"))
OPENAI_IMAGE_MODEL_ID = os.getenv("FLUX_OPENAI_MODEL_ID", "flux-image").strip() or "flux-image"
OPENAI_MAX_IMAGES = int(os.getenv("FLUX_OPENAI_MAX_IMAGES", "1"))
SUPPORTED_MODES = {"text", "image"}
PIPELINE_KIND = os.getenv("FLUX_PIPELINE", "auto").strip().lower()
TEXT_ENCODER_ID = os.getenv("FLUX_TEXT_ENCODER_ID", "").strip()
TEXT_ENCODER_SUBFOLDER = os.getenv("FLUX_TEXT_ENCODER_SUBFOLDER", "").strip()
TEXT_ENCODER_GGUF_FILE = os.getenv("FLUX_TEXT_ENCODER_GGUF_FILE", "").strip()
TEXT_ENCODER_TOKENIZER_ID = os.getenv("FLUX_TEXT_ENCODER_TOKENIZER_ID", "").strip()
TEXT_ENCODER_TOKENIZER_SUBFOLDER = os.getenv("FLUX_TEXT_ENCODER_TOKENIZER_SUBFOLDER", "").strip()
TEXT_ENCODER_OUT_LAYERS = tuple(
    int(layer.strip())
    for layer in os.getenv("FLUX_TEXT_ENCODER_OUT_LAYERS", "9,18,27").split(",")
    if layer.strip()
)
LORA_ID = os.getenv("FLUX_LORA_ID", "").strip()
LORA_WEIGHT = os.getenv("FLUX_LORA_WEIGHT", "").strip()
LORA_ADAPTER = os.getenv("FLUX_LORA_ADAPTER", "v1")
DEFAULT_PORT = int(os.getenv("PORT", os.getenv("FLUX_WEB_PORT", "8189")))
DEFAULT_HOST = os.getenv("HOST", os.getenv("FLUX_WEB_HOST", "0.0.0.0"))

DEFAULT_WIDTH = int(os.getenv("FLUX_DEFAULT_WIDTH", "1024"))
DEFAULT_HEIGHT = int(os.getenv("FLUX_DEFAULT_HEIGHT", "1024"))
DEFAULT_STEPS = int(os.getenv("FLUX_DEFAULT_STEPS", "40"))
DEFAULT_GUIDANCE = float(os.getenv("FLUX_DEFAULT_GUIDANCE", "4"))
DEFAULT_MAX_SEQUENCE_LENGTH = int(os.getenv("FLUX_MAX_SEQUENCE_LENGTH", "512"))
MAX_DIMENSION = int(os.getenv("FLUX_MAX_DIMENSION", "1536"))
MAX_STEPS = int(os.getenv("FLUX_MAX_STEPS", "80"))
QUANTIZATION = os.getenv("FLUX_QUANTIZATION", "bnb-4bit").lower()
TORCH_NUM_THREADS = int(os.getenv("FLUX_TORCH_NUM_THREADS", "0") or "0")
TORCH_INTEROP_THREADS = int(os.getenv("FLUX_TORCH_INTEROP_THREADS", "0") or "0")
CPU_OFFLOAD = os.getenv("FLUX_CPU_OFFLOAD", "1").lower() not in {"0", "false", "no", "off"}
ENABLE_XFORMERS = os.getenv("FLUX_ENABLE_XFORMERS", "1").lower() not in {"0", "false", "no", "off"}
VAE_TILING = os.getenv("FLUX_VAE_TILING", "0").lower() not in {"0", "false", "no", "off"}
VAE_SLICING = os.getenv("FLUX_VAE_SLICING", "0").lower() not in {"0", "false", "no", "off"}
TEXT_ENCODER_DEVICE = os.getenv("FLUX_TEXT_ENCODER_DEVICE", "").strip()
IMAGE_MODEL_DEVICE = os.getenv(
    "FLUX_IMAGE_MODEL_DEVICE",
    os.getenv("FLUX_TRANSFORMER_DEVICE", ""),
).strip()


app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))
app.config["TEMPLATES_AUTO_RELOAD"] = True

pipeline: Any | None = None
pipeline_lock = threading.Lock()
generation_lock = threading.Lock()
load_error: str | None = None


def _torch_dtype(torch: Any) -> Any:
    dtype_name = os.getenv("FLUX_TORCH_DTYPE", "bfloat16").lower()
    if dtype_name in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if dtype_name in {"fp16", "float16", "half"}:
        return torch.float16
    if dtype_name in {"fp32", "float32"}:
        return torch.float32
    raise ValueError("FLUX_TORCH_DTYPE must be one of bfloat16, float16, or float32")


def _configure_torch_runtime(torch: Any) -> None:
    if TORCH_NUM_THREADS > 0:
        torch.set_num_threads(TORCH_NUM_THREADS)
    if TORCH_INTEROP_THREADS > 0:
        try:
            torch.set_num_interop_threads(TORCH_INTEROP_THREADS)
        except RuntimeError as exc:
            app.logger.info("Could not set PyTorch interop threads: %s", exc)


def _bnb_config(config_cls: Any, torch: Any, dtype: Any) -> Any:
    if QUANTIZATION in {"bnb-4bit", "4bit", "nf4"}:
        return config_cls(
            load_in_4bit=True,
            bnb_4bit_quant_type=os.getenv("FLUX_BNB_4BIT_QUANT_TYPE", "nf4"),
            bnb_4bit_compute_dtype=dtype,
            bnb_4bit_use_double_quant=os.getenv("FLUX_BNB_DOUBLE_QUANT", "1").lower()
            not in {"0", "false", "no", "off"},
        )
    if QUANTIZATION in {"bnb-8bit", "8bit", "int8"}:
        return config_cls(load_in_8bit=True)
    if QUANTIZATION in {"none", "off", "false", "0"}:
        return None
    raise ValueError("FLUX_QUANTIZATION must be one of bnb-4bit, bnb-8bit, or none")


def _selected_pipeline_kind() -> str:
    if PIPELINE_KIND in {"flux2", "flux2-klein", "flux2_klein"}:
        return "flux2-klein"
    if PIPELINE_KIND in {"flux1", "flux", "flux1-dev", "flux1_dev"}:
        return "flux1"
    if PIPELINE_KIND != "auto":
        raise ValueError("FLUX_PIPELINE must be one of auto, flux1, or flux2-klein")

    normalized_model = MODEL_ID.lower().replace("_", "-")
    if "flux.2-klein" in normalized_model or "flux2-klein" in normalized_model:
        return "flux2-klein"
    return "flux1"


def _device_requires_cuda(device: str) -> bool:
    normalized = device.strip().lower()
    return normalized == "cuda" or normalized.startswith("cuda:")


def _cuda_is_required() -> bool:
    if _selected_pipeline_kind() == "flux2-klein" and _flux2_split_devices_enabled():
        return _device_requires_cuda(_flux2_text_encoder_device()) or _device_requires_cuda(_flux2_image_model_device())
    return True


def _split_hf_reference(reference: str) -> tuple[str, str]:
    if ":" in reference and not reference.startswith("/") and "/" in reference.split(":", 1)[0]:
        repo_id, tag = reference.rsplit(":", 1)
        if repo_id and tag:
            return repo_id, tag
    return reference, ""


def _token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN") or None


def _resolve_gguf_file(repo_id: str, tag: str) -> str:
    if TEXT_ENCODER_GGUF_FILE:
        return TEXT_ENCODER_GGUF_FILE
    if not tag:
        return ""
    if tag.lower().endswith(".gguf"):
        return tag

    try:
        from huggingface_hub import list_repo_files

        normalized_tag = tag.lower().replace("_", "").replace("-", "")
        candidates = []
        for filename in list_repo_files(repo_id, token=_token()):
            normalized_filename = Path(filename).name.lower().replace("_", "").replace("-", "")
            if filename.lower().endswith(".gguf") and normalized_tag in normalized_filename:
                candidates.append(filename)
        if candidates:
            return sorted(candidates, key=len)[0]
    except Exception as exc:
        app.logger.info("Could not resolve GGUF tag %s from %s: %s", tag, repo_id, exc)

    raise ValueError(
        f"Could not resolve GGUF tag '{tag}' for {repo_id}. Set FLUX_TEXT_ENCODER_GGUF_FILE explicitly."
    )


def _load_flux2_external_text_encoder(torch: Any, dtype: Any) -> dict[str, Any]:
    if not TEXT_ENCODER_ID:
        return {}

    from transformers import AutoTokenizer, Qwen3ForCausalLM

    repo_id, tag = _split_hf_reference(TEXT_ENCODER_ID)
    gguf_file = _resolve_gguf_file(repo_id, tag)
    tokenizer_repo = TEXT_ENCODER_TOKENIZER_ID or repo_id
    tokenizer_subfolder = TEXT_ENCODER_TOKENIZER_SUBFOLDER or TEXT_ENCODER_SUBFOLDER

    tokenizer_kwargs: dict[str, Any] = {}
    if tokenizer_subfolder:
        tokenizer_kwargs["subfolder"] = tokenizer_subfolder
    elif gguf_file:
        tokenizer_kwargs["gguf_file"] = gguf_file

    model_kwargs: dict[str, Any] = {"torch_dtype": dtype}
    if gguf_file:
        model_kwargs["gguf_file"] = gguf_file
    elif TEXT_ENCODER_SUBFOLDER:
        model_kwargs["subfolder"] = TEXT_ENCODER_SUBFOLDER

    app.logger.info("Loading FLUX.2 text encoder from %s%s", repo_id, f" ({gguf_file})" if gguf_file else "")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_repo, token=_token(), **tokenizer_kwargs)
    text_encoder = Qwen3ForCausalLM.from_pretrained(repo_id, token=_token(), **model_kwargs)
    return {"tokenizer": tokenizer, "text_encoder": text_encoder}


def _flux2_split_devices_enabled() -> bool:
    return _selected_pipeline_kind() == "flux2-klein" and bool(TEXT_ENCODER_DEVICE or IMAGE_MODEL_DEVICE)


def _flux2_text_encoder_device() -> str:
    return TEXT_ENCODER_DEVICE or IMAGE_MODEL_DEVICE or "cuda:0"


def _flux2_image_model_device() -> str:
    return IMAGE_MODEL_DEVICE or TEXT_ENCODER_DEVICE or "cuda:1"


def _module_device(module: Any) -> str | None:
    if module is None:
        return None
    device = getattr(module, "device", None)
    if device is not None:
        return str(device)
    try:
        return str(next(module.parameters()).device)
    except Exception:
        return None


def _pipeline_component_devices(pipe: Any | None) -> dict[str, str | None]:
    if pipe is None:
        return {}
    return {
        "text_encoder": _module_device(getattr(pipe, "text_encoder", None)),
        "transformer": _module_device(getattr(pipe, "transformer", None)),
        "vae": _module_device(getattr(pipe, "vae", None)),
        "execution": str(getattr(pipe, "_execution_device", None)),
    }


def _xformers_supported_for_pipeline(pipe: Any) -> bool:
    if not ENABLE_XFORMERS:
        return False

    transformer_device = _module_device(getattr(pipe, "transformer", None))
    if transformer_device is not None:
        return _device_requires_cuda(transformer_device)

    execution_device = getattr(pipe, "_execution_device", None)
    if execution_device is not None:
        return _device_requires_cuda(str(execution_device))

    return _device_requires_cuda(str(getattr(pipe, "device", "")))


def _place_flux2_pipeline(pipe: Any) -> Any:
    text_encoder_device = _flux2_text_encoder_device()
    image_model_device = _flux2_image_model_device()

    app.logger.info(
        "Placing FLUX.2 components: text_encoder=%s transformer=%s vae=%s",
        text_encoder_device,
        image_model_device,
        image_model_device,
    )
    if CPU_OFFLOAD:
        app.logger.info("Ignoring FLUX_CPU_OFFLOAD because explicit FLUX.2 device placement is configured")

    pipe.text_encoder.to(text_encoder_device)
    pipe.transformer.to(image_model_device)
    pipe.vae.to(image_model_device)
    return pipe


def _flux2_prompt_embeds_for_image_device(pipe: Any, torch: Any, prompt: str, max_sequence_length: int) -> Any:
    text_encoder_device = _flux2_text_encoder_device()
    image_model_device = _flux2_image_model_device()
    text_prompt_embeds = pipe._get_qwen3_prompt_embeds(
        text_encoder=pipe.text_encoder,
        tokenizer=pipe.tokenizer,
        prompt=prompt,
        dtype=pipe.transformer.dtype,
        device=torch.device(text_encoder_device),
        max_sequence_length=max_sequence_length,
        hidden_states_layers=TEXT_ENCODER_OUT_LAYERS,
    )
    prompt_embeds = text_prompt_embeds.to(device=torch.device(image_model_device), dtype=pipe.transformer.dtype)
    del text_prompt_embeds
    if text_encoder_device != image_model_device and text_encoder_device.startswith("cuda"):
        torch.cuda.empty_cache()
    return prompt_embeds


def _place_pipeline(pipe: Any) -> Any:
    if _flux2_split_devices_enabled():
        return _place_flux2_pipeline(pipe)

    if CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    return pipe


def _load_flux2_pipeline(torch: Any, dtype: Any) -> Any:
    from diffusers import Flux2KleinPipeline

    load_kwargs = {"torch_dtype": dtype}
    load_kwargs.update(_load_flux2_external_text_encoder(torch, dtype))
    pipe = Flux2KleinPipeline.from_pretrained(MODEL_ID, token=_token(), **load_kwargs)
    return _place_pipeline(pipe)


def _load_flux1_pipeline(torch: Any, dtype: Any) -> Any:
    from diffusers import (
        BitsAndBytesConfig as DiffusersBitsAndBytesConfig,
        FluxPipeline,
        FluxTransformer2DModel,
    )
    from transformers import BitsAndBytesConfig as TransformersBitsAndBytesConfig
    from transformers import T5EncoderModel

    quantization_config = _bnb_config(DiffusersBitsAndBytesConfig, torch, dtype)
    text_encoder_quantization_config = _bnb_config(TransformersBitsAndBytesConfig, torch, dtype)

    if quantization_config is None:
        return _place_pipeline(FluxPipeline.from_pretrained(MODEL_ID, token=_token(), torch_dtype=dtype))

    app.logger.info("Loading FLUX.1 with %s quantization", QUANTIZATION)
    transformer = FluxTransformer2DModel.from_pretrained(
        MODEL_ID,
        subfolder="transformer",
        quantization_config=quantization_config,
        torch_dtype=dtype,
        token=_token(),
    )
    text_encoder_2 = T5EncoderModel.from_pretrained(
        MODEL_ID,
        subfolder="text_encoder_2",
        quantization_config=text_encoder_quantization_config,
        torch_dtype=dtype,
        token=_token(),
    )
    pipe = FluxPipeline.from_pretrained(
        MODEL_ID,
        transformer=transformer,
        text_encoder_2=text_encoder_2,
        torch_dtype=dtype,
        token=_token(),
    )
    return _place_pipeline(pipe)


def _load_pipeline() -> Any:
    global load_error, pipeline

    if pipeline is not None:
        return pipeline

    with pipeline_lock:
        if pipeline is not None:
            return pipeline

        try:
            import torch

            _configure_torch_runtime(torch)
            if _cuda_is_required() and not torch.cuda.is_available():
                raise RuntimeError("CUDA is not available. Install a CUDA build of PyTorch and run on a CUDA GPU.")

            dtype = _torch_dtype(torch)
            selected_pipeline = _selected_pipeline_kind()
            app.logger.info("Loading %s model %s", selected_pipeline, MODEL_ID)
            if selected_pipeline == "flux2-klein":
                pipe = _load_flux2_pipeline(torch, dtype)
            else:
                pipe = _load_flux1_pipeline(torch, dtype)

            if LORA_ID:
                lora_kwargs = {"adapter_name": LORA_ADAPTER}
                if LORA_WEIGHT:
                    lora_kwargs["weight_name"] = LORA_WEIGHT
                pipe.load_lora_weights(LORA_ID, **lora_kwargs)
                pipe.set_adapters([LORA_ADAPTER], adapter_weights=[1])

            if hasattr(pipe, "enable_xformers_memory_efficient_attention") and _xformers_supported_for_pipeline(pipe):
                try:
                    pipe.enable_xformers_memory_efficient_attention()
                except Exception as exc:
                    app.logger.info("xformers attention was not enabled: %s", exc)
            elif hasattr(pipe, "enable_xformers_memory_efficient_attention"):
                app.logger.info("xformers attention skipped for non-CUDA image model placement")

            if VAE_TILING and hasattr(pipe.vae, "enable_tiling"):
                pipe.vae.enable_tiling()
                app.logger.info("VAE tiling enabled")
            if VAE_SLICING and hasattr(pipe.vae, "enable_slicing"):
                pipe.vae.enable_slicing()
                app.logger.info("VAE slicing enabled")

            pipeline = pipe
            load_error = None
            return pipeline
        except Exception as exc:
            load_error = str(exc)
            raise


def _positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _positive_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _dimension(value: Any, default: int) -> int:
    parsed = _positive_int(value, default, 128, MAX_DIMENSION)
    divisor = 16 if _selected_pipeline_kind() == "flux2-klein" else 8
    return max(128, (parsed // divisor) * divisor)


def _seed(value: Any) -> int:
    if value in (None, ""):
        return secrets.randbits(32)
    return _positive_int(value, 0, 0, 2**32 - 1)


def _image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _load_image_from_bytes(data: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise ValueError("Input image must be a valid image file.") from exc


def _load_image_upload(upload: FileStorage | None) -> Image.Image | None:
    if upload is None or not upload.filename:
        return None
    return _load_image_from_bytes(upload.read())


def _load_base64_image(value: Any) -> Image.Image | None:
    if value in (None, ""):
        return None
    raw = str(value)
    if "," in raw and raw.split(",", 1)[0].startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return _load_image_from_bytes(base64.b64decode(raw, validate=True))
    except Exception as exc:
        raise ValueError("image must be base64-encoded image data.") from exc


def _request_payload() -> tuple[dict[str, Any], Image.Image | None]:
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        return request.form.to_dict(), _load_image_upload(request.files.get("image"))
    data = request.get_json(silent=True) or {}
    return data, _load_base64_image(data.get("image"))


def _generation_params(data: dict[str, Any]) -> dict[str, Any]:
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("Prompt is required.")

    mode = str(data.get("mode") or "text").strip().lower()
    if mode in {"txt2img", "text-to-image"}:
        mode = "text"
    if mode in {"img2img", "image-to-image", "reference"}:
        mode = "image"
    if mode not in SUPPORTED_MODES:
        raise ValueError("mode must be either text or image.")
    if mode == "image" and _selected_pipeline_kind() != "flux2-klein":
        raise ValueError("Image mode is only supported by the FLUX.2 Klein pipeline.")

    return {
        "mode": mode,
        "prompt": prompt,
        "width": _dimension(data.get("width"), DEFAULT_WIDTH),
        "height": _dimension(data.get("height"), DEFAULT_HEIGHT),
        "steps": _positive_int(data.get("num_inference_steps"), DEFAULT_STEPS, 1, MAX_STEPS),
        "guidance": _positive_float(data.get("guidance_scale"), DEFAULT_GUIDANCE, 0.0, 20.0),
        "max_sequence_length": _positive_int(
            data.get("max_sequence_length"),
            DEFAULT_MAX_SEQUENCE_LENGTH,
            64,
            512,
        ),
        "seed": _seed(data.get("seed")),
    }


def _openai_error(message: str, status: int = 400, param: str | None = None, code: str | None = None) -> Any:
    payload: dict[str, Any] = {
        "error": {
            "message": message,
            "type": "invalid_request_error",
            "param": param,
            "code": code,
        }
    }
    return jsonify(payload), status


def _openai_generation_params(data: dict[str, Any]) -> dict[str, Any]:
    converted = dict(data)
    size = str(converted.get("size", "")).strip().lower()
    if size and size != "auto":
        try:
            width_raw, height_raw = size.split("x", 1)
            converted["width"] = int(width_raw)
            converted["height"] = int(height_raw)
        except ValueError as exc:
            raise ValueError("size must be formatted as WIDTHxHEIGHT or set to auto.") from exc

    if "num_inference_steps" not in converted:
        if "steps" in converted:
            converted["num_inference_steps"] = converted["steps"]
        elif "step" in converted:
            converted["num_inference_steps"] = converted["step"]

    return _generation_params(converted)


def _result_payload(image: Image.Image, started_at: float, params: dict[str, Any]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(exist_ok=True)
    filename = f"{int(time.time())}-{params['seed']}.png"
    image.save(OUTPUT_DIR / filename)

    return {
        "ok": True,
        "image": _image_to_base64(image),
        "image_url": f"/outputs/{filename}",
        "filename": filename,
        "seed": params["seed"],
        "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        "parameters": {
            "mode": params["mode"],
            "width": params["width"],
            "height": params["height"],
            "num_inference_steps": params["steps"],
            "guidance_scale": params["guidance"],
            "max_sequence_length": params["max_sequence_length"],
            "input_image": params.get("input_image"),
        },
    }


def _generate_image(
    params: dict[str, Any],
    progress_callback: Any | None = None,
    status_callback: Any | None = None,
    input_image: Image.Image | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    pipe = _load_pipeline()

    import torch

    if params["mode"] == "image":
        if input_image is None:
            raise ValueError("Image mode requires an input image.")
        params["input_image"] = {"width": input_image.width, "height": input_image.height}

    generator = torch.Generator("cpu").manual_seed(params["seed"])
    call_kwargs = {
        "prompt": params["prompt"],
        "guidance_scale": params["guidance"],
        "height": params["height"],
        "width": params["width"],
        "num_inference_steps": params["steps"],
        "max_sequence_length": params["max_sequence_length"],
        "generator": generator,
    }
    if params["mode"] == "image":
        call_kwargs["image"] = input_image
    if _selected_pipeline_kind() == "flux2-klein":
        call_kwargs["text_encoder_out_layers"] = TEXT_ENCODER_OUT_LAYERS
        if _flux2_split_devices_enabled():
            prompt_started_at = time.perf_counter()
            call_kwargs["prompt"] = None
            call_kwargs["prompt_embeds"] = _flux2_prompt_embeds_for_image_device(
                pipe,
                torch,
                params["prompt"],
                params["max_sequence_length"],
            )
            app.logger.info("Prompt encoding finished in %.2fs", time.perf_counter() - prompt_started_at)
            config = getattr(pipe, "config", {})
            is_distilled = bool(
                config.get("is_distilled", False) if hasattr(config, "get") else getattr(config, "is_distilled", False)
            )
            if params["guidance"] > 1 and not is_distilled:
                call_kwargs["negative_prompt_embeds"] = _flux2_prompt_embeds_for_image_device(
                    pipe,
                    torch,
                    "",
                    params["max_sequence_length"],
                )
    if progress_callback is not None:
        call_kwargs["callback_on_step_end"] = progress_callback
        call_kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]

    app.logger.info(
        "Starting %s generation at %sx%s for %s steps",
        params["mode"],
        params["width"],
        params["height"],
        params["steps"],
    )
    pipeline_started_at = time.perf_counter()
    with torch.inference_mode():
        result = pipe(**call_kwargs)
    app.logger.info("Pipeline call finished in %.2fs", time.perf_counter() - pipeline_started_at)

    if status_callback is not None:
        status_callback("Saving image")

    save_started_at = time.perf_counter()
    payload = _result_payload(result.images[0], started_at, params)
    app.logger.info("Image save/payload finished in %.2fs", time.perf_counter() - save_started_at)
    return payload


def _stream_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/")
def index() -> str:
    return render_template(
        "index.html",
        defaults={
            "width": DEFAULT_WIDTH,
            "height": DEFAULT_HEIGHT,
            "steps": DEFAULT_STEPS,
            "guidance": DEFAULT_GUIDANCE,
            "max_sequence_length": DEFAULT_MAX_SEQUENCE_LENGTH,
            "max_dimension": MAX_DIMENSION,
            "dimension_step": 16 if _selected_pipeline_kind() == "flux2-klein" else 8,
            "max_steps": MAX_STEPS,
            "model": MODEL_ID,
            "lora": LORA_ID or None,
            "port": DEFAULT_PORT,
        },
    )


@app.get("/health")
def health() -> Any:
    gpu_info: dict[str, Any] = {"cuda_available": False}
    try:
        import torch

        if torch.cuda.is_available():
            gpu_info = {
                "cuda_available": True,
                "device_count": torch.cuda.device_count(),
                "devices": [
                    {
                        "id": index,
                        "name": torch.cuda.get_device_name(index),
                        "memory_allocated": torch.cuda.memory_allocated(index),
                        "memory_reserved": torch.cuda.memory_reserved(index),
                    }
                    for index in range(torch.cuda.device_count())
                ],
            }
    except Exception as exc:
        gpu_info = {"cuda_available": False, "error": str(exc)}

    return jsonify(
        {
            "ok": True,
            "model_loaded": pipeline is not None,
            "generation_busy": generation_lock.locked(),
            "load_error": load_error,
            "model": MODEL_ID,
            "pipeline": _selected_pipeline_kind(),
            "text_encoder": TEXT_ENCODER_ID or None,
            "text_encoder_gguf_file": TEXT_ENCODER_GGUF_FILE or None,
            "text_encoder_out_layers": TEXT_ENCODER_OUT_LAYERS,
            "lora": LORA_ID,
            "lora_weight": LORA_WEIGHT,
            "adapter": LORA_ADAPTER,
            "quantization": QUANTIZATION,
            "torch_dtype": os.getenv("FLUX_TORCH_DTYPE", "bfloat16").lower(),
            "torch_threads": {
                "num_threads": TORCH_NUM_THREADS or None,
                "interop_threads": TORCH_INTEROP_THREADS or None,
            },
            "cpu_offload": CPU_OFFLOAD,
            "xformers": ENABLE_XFORMERS,
            "device_placement": {
                "split_devices": _flux2_split_devices_enabled(),
                "text_encoder_device": TEXT_ENCODER_DEVICE or None,
                "image_model_device": IMAGE_MODEL_DEVICE or None,
                "components": _pipeline_component_devices(pipeline),
            },
            "python": sys.executable,
            "gpu": gpu_info,
        }
    )


@app.get("/v1/models")
def openai_models() -> Any:
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": OPENAI_IMAGE_MODEL_ID,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                    "root": MODEL_ID,
            "metadata": {
                "modalities": {
                    "input": ["text", "image"],
                    "output": ["image"],
                },
                "backend": "diffusers",
                "modes": ["text", "image"],
                "max_dimension": MAX_DIMENSION,
                "max_images": OPENAI_MAX_IMAGES,
            },
                }
            ],
        }
    )


@app.post("/v1/images/generations")
def openai_image_generations() -> Any:
    data = request.get_json(silent=True) or {}
    requested_model = str(data.get("model") or OPENAI_IMAGE_MODEL_ID).strip()
    if requested_model not in {OPENAI_IMAGE_MODEL_ID, MODEL_ID}:
        return _openai_error(f"Model '{requested_model}' is not available.", 404, "model", "model_not_found")

    response_format = str(data.get("response_format") or "b64_json").strip()
    if response_format not in {"b64_json", "url"}:
        return _openai_error("response_format must be either 'b64_json' or 'url'.", 400, "response_format")

    max_images = max(1, OPENAI_MAX_IMAGES)
    try:
        image_count = int(data.get("n") or 1)
    except (TypeError, ValueError):
        return _openai_error(f"n must be between 1 and {max_images}.", 400, "n")
    if image_count < 1 or image_count > max_images:
        return _openai_error(f"n must be between 1 and {max_images}.", 400, "n")

    try:
        params = _openai_generation_params(data)
    except ValueError as exc:
        return _openai_error(str(exc), 400)

    if not generation_lock.acquire(blocking=False):
        return _openai_error("A generation is already running.", 429)

    try:
        created = int(time.time())
        generated: list[dict[str, Any]] = []
        for index in range(image_count):
            item_params = dict(params)
            if data.get("seed") not in (None, ""):
                item_params["seed"] = (params["seed"] + index) % (2**32)
            payload = _generate_image(item_params)
            if response_format == "url":
                generated.append({"url": request.url_root.rstrip("/") + payload["image_url"]})
            else:
                generated.append({"b64_json": payload["image"]})
        return jsonify({"created": created, "data": generated})
    except Exception as exc:
        app.logger.exception("OpenAI-compatible image generation failed")
        return _openai_error(str(exc), 500, code="generation_failed")
    finally:
        generation_lock.release()


@app.post("/v1/images/edits")
def openai_image_edits() -> Any:
    data = request.form.to_dict()
    requested_model = str(data.get("model") or OPENAI_IMAGE_MODEL_ID).strip()
    if requested_model not in {OPENAI_IMAGE_MODEL_ID, MODEL_ID}:
        return _openai_error(f"Model '{requested_model}' is not available.", 404, "model", "model_not_found")
    if request.files.get("mask") is not None:
        return _openai_error("Masked inpainting is not supported by this loaded FLUX.2 Klein pipeline.", 501, "mask")

    response_format = str(data.get("response_format") or "b64_json").strip()
    if response_format not in {"b64_json", "url"}:
        return _openai_error("response_format must be either 'b64_json' or 'url'.", 400, "response_format")

    max_images = max(1, OPENAI_MAX_IMAGES)
    try:
        image_count = int(data.get("n") or 1)
    except (TypeError, ValueError):
        return _openai_error(f"n must be between 1 and {max_images}.", 400, "n")
    if image_count < 1 or image_count > max_images:
        return _openai_error(f"n must be between 1 and {max_images}.", 400, "n")

    try:
        input_image = _load_image_upload(request.files.get("image"))
        if input_image is None:
            return _openai_error("image is required.", 400, "image")
        converted = dict(data)
        converted["mode"] = "image"
        params = _openai_generation_params(converted)
    except ValueError as exc:
        return _openai_error(str(exc), 400)

    if not generation_lock.acquire(blocking=False):
        return _openai_error("A generation is already running.", 429)

    try:
        created = int(time.time())
        generated: list[dict[str, Any]] = []
        for index in range(image_count):
            item_params = dict(params)
            if data.get("seed") not in (None, ""):
                item_params["seed"] = (params["seed"] + index) % (2**32)
            payload = _generate_image(item_params, input_image=input_image)
            if response_format == "url":
                generated.append({"url": request.url_root.rstrip("/") + payload["image_url"]})
            else:
                generated.append({"b64_json": payload["image"]})
        return jsonify({"created": created, "data": generated})
    except Exception as exc:
        app.logger.exception("OpenAI-compatible image edit failed")
        return _openai_error(str(exc), 500, code="generation_failed")
    finally:
        generation_lock.release()


@app.post("/api/load")
def load_model() -> Any:
    try:
        _load_pipeline()
        return jsonify({"ok": True, "model_loaded": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/generate")
def generate() -> Any:
    data, input_image = _request_payload()
    try:
        params = _generation_params(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not generation_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "A generation is already running."}), 429

    try:
        return jsonify(_generate_image(params, input_image=input_image))
    except Exception as exc:
        app.logger.exception("Generation failed")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        generation_lock.release()


@app.post("/api/generate-stream")
def generate_stream() -> Any:
    data, input_image = _request_payload()
    try:
        params = _generation_params(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if generation_lock.locked():
        return jsonify({"ok": False, "error": "A generation is already running."}), 429

    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def worker() -> None:
        if not generation_lock.acquire(blocking=False):
            messages.put({"type": "error", "message": "A generation is already running."})
            messages.put(None)
            return

        try:
            if pipeline is None:
                messages.put({"type": "status", "message": "Loading model"})
            else:
                messages.put({"type": "status", "message": "Model already loaded"})
            _load_pipeline()

            def on_step_end(_pipe: Any, step: int, _timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
                current = step + 1
                total = params["steps"]
                messages.put(
                    {
                        "type": "progress",
                        "step": current,
                        "total_steps": total,
                        "percentage": round((current / total) * 90),
                        "phase": "denoising",
                    }
                )
                if current == total:
                    app.logger.info("Denoising finished after %s steps", total)
                    messages.put({"type": "status", "message": "Decoding image"})
                return callback_kwargs

            messages.put({"type": "status", "message": "Generating image"})
            payload = _generate_image(
                params,
                progress_callback=on_step_end,
                status_callback=lambda message: messages.put({"type": "status", "message": message}),
                input_image=input_image,
            )
            payload["type"] = "complete"
            messages.put(payload)
        except Exception as exc:
            app.logger.exception("Streaming generation failed")
            messages.put({"type": "error", "message": str(exc)})
        finally:
            generation_lock.release()
            messages.put(None)

    threading.Thread(target=worker, daemon=True).start()

    @stream_with_context
    def events() -> Any:
        yield _stream_event({"type": "status", "message": "Queued generation"})
        while True:
            message = messages.get()
            if message is None:
                break
            yield _stream_event(message)

    return Response(events(), mimetype="text/event-stream")


@app.get("/outputs/<path:filename>")
def outputs(filename: str) -> Any:
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving FLUX web UI at http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"Hugging Face hub cache: {os.environ['HF_HUB_CACHE']}")
    print(f"Quantization: {QUANTIZATION}")
    print(f"CPU offload: {CPU_OFFLOAD}")
    print(f"Text encoder device: {TEXT_ENCODER_DEVICE or 'default'}")
    print(f"Image model device: {IMAGE_MODEL_DEVICE or 'default'}")
    print(f"Python: {sys.executable}")
    print(f"Model: {MODEL_ID}")
    print(f"LoRA:  {LORA_ID or 'none'}{f' ({LORA_WEIGHT})' if LORA_WEIGHT else ''}")
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False, threaded=True)
