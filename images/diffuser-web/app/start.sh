#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

echo "=== FLUX Web UI Startup Script ==="
echo

# Check if the project venv is available.
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Error: project venv not found at $VENV_PYTHON"
    echo "Create it with: uv venv --python 3.12 .venv"
    exit 1
fi

# Check CUDA availability
echo "Checking CUDA availability..."
"$VENV_PYTHON" -c "import sys, torch; print(f'Python: {sys.executable}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA device count: {torch.cuda.device_count()}' if torch.cuda.is_available() else '')"

echo
PORT="${PORT:-8189}"
HOST="${HOST:-0.0.0.0}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$PWD/hf-cache/hub}"
export HF_HUB_CACHE
mkdir -p "$HF_HUB_CACHE"

echo "Starting FLUX Web UI..."
echo "Access the UI at: http://localhost:${PORT}"
echo "Hugging Face hub cache: ${HF_HUB_CACHE}"
echo "Press Ctrl+C to stop the server"
echo

# Start the application with the project-local venv even if another venv is active.
exec env HOST="${HOST}" PORT="${PORT}" HF_HUB_CACHE="${HF_HUB_CACHE}" "$VENV_PYTHON" app.py
