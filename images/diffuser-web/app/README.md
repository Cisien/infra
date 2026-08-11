# FLUX Web UI

A small HTTP web interface for running `kpsss34/FHDR_Uncensored` with Diffusers
`FluxPipeline`.

The app starts a Flask server on port `8189` by default and exposes:

- `GET /` - browser interface
- `GET /health` - model and CUDA status
- `POST /api/load` - preload the model
- `POST /api/generate` - generate one image
- `POST /api/generate-stream` - generate one image with step progress events

## Setup

```bash
cd ~/src/diffuser-web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
hf auth login
```

The model may require Hugging Face auth, so the account used by `hf auth login`
must have accepted any required model terms.

## Run

```bash
./start.sh
```

Then open:

```text
http://localhost:8189
```

The app redirects Hugging Face model downloads to `./hf-cache/hub` by default.
That keeps downloads writable even if the global Hugging Face hub cache has bad
ownership. Your auth token still comes from the normal Hugging Face login.

Override bind settings with environment variables:

```bash
HOST=0.0.0.0 PORT=8189 ./start.sh
```

For the RTX 3090 CUDA setup on the remote host, install with `uv`:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv --torch-backend cu128 -r requirements.txt
```

## Generation Defaults

- Width: `1024`
- Height: `1024`
- Steps: `40`
- Guidance scale: `4`
- Max sequence length: `512`
- Torch dtype: `bfloat16`
- Quantization: `bnb-4bit`

You can override model settings with:

```bash
MODEL_ID=kpsss34/FHDR_Uncensored ./start.sh
MODEL_ID=black-forest-labs/FLUX.1-dev ./start.sh
```

LoRA loading is optional. To enable it:

```bash
FLUX_LORA_ID=lustlyai/Flux_Lustly.ai_Uncensored_nsfw_v1 \
FLUX_LORA_WEIGHT=flux_lustly-ai_v1.safetensors \
./start.sh
```

Quantization is enabled by default to fit FLUX on 24 GB GPUs:

```bash
FLUX_QUANTIZATION=bnb-4bit ./start.sh
```

Other options:

```bash
FLUX_QUANTIZATION=bnb-8bit ./start.sh
FLUX_QUANTIZATION=none ./start.sh
```

The quantized path loads the FLUX transformer and T5 text encoder with
bitsandbytes before constructing the pipeline, then uses Diffusers model CPU
offload by default. Disable offload only if you have enough VRAM:

```bash
FLUX_CPU_OFFLOAD=0 ./start.sh
```

The browser UI uses `/api/generate-stream`, which streams Server-Sent Event
messages for load status, per-step progress, completion, and errors. The
non-streaming `/api/generate` endpoint remains available for simple API clients.
