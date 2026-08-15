#!/usr/bin/env bash
set -euo pipefail

server_dir="${SERVER_DIR:-/data/server}"
port="${PALWORLD_PORT:-8211}"
query_port="${PALWORLD_QUERY_PORT:-27015}"
players="${PALWORLD_PLAYERS:-16}"

mkdir -p "${server_dir}"

if [[ "${UPDATE_ON_START:-true}" == "true" || ! -x "${server_dir}/PalServer.sh" ]]; then
  until "${STEAMCMDDIR}/steamcmd.sh" \
    +force_install_dir "${server_dir}" \
    +login anonymous \
    +app_update 2394010 validate \
    +quit; do
    printf '%s\n' 'SteamCMD installation failed; retrying in 30 seconds.' >&2
    sleep 30
  done
fi

exec "${server_dir}/PalServer.sh" \
  -port="${port}" \
  -queryport="${query_port}" \
  -players="${players}" \
  -useperfthreads \
  -NoAsyncLoadingThread \
  -EpicApp=PalServer
