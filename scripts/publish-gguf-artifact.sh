#!/usr/bin/env bash
# Push one already-downloaded model file as an OCI artifact.
# Usage: OCI_PASSWORD=... scripts/publish-gguf-artifact.sh <repository:tag> <file>
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s <repository:tag> <file>\n' "$0" >&2
  exit 2
fi

: "${OCI_PASSWORD:?Set OCI_PASSWORD from the oci-registry-client Secret.}"

reference=$1
source_file=$2
base_name=$(basename "$source_file")
source_dir=$(dirname "$source_file")

if [[ ! -f "$source_file" ]]; then
  printf 'model file does not exist: %s\n' "$source_file" >&2
  exit 2
fi

printf '%s' "$OCI_PASSWORD" | podman run --rm --interactive \
  --dns 192.168.1.2 \
  --volume "${source_dir}:/input:ro" \
  ghcr.io/oras-project/oras:v1.3.0 \
  push \
  --username registry \
  --password-stdin \
  --artifact-type application/vnd.cisien.ai.model.v1 \
  --disable-path-validation \
  "$reference" \
  "/input/${base_name}:application/vnd.cisien.ai.gguf.v1"
