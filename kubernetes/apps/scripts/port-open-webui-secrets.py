#!/usr/bin/env python3
"""Seal the active Docker Open WebUI runtime environment for Kubernetes."""

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def source_environment(host: str, container: str) -> dict[str, str]:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "docker", "inspect", container],
        check=True,
        capture_output=True,
    )
    container_data = json.loads(result.stdout)[0]
    return dict(item.split("=", 1) for item in container_data["Config"].get("Env", []) if "=" in item)


def source_file(host: str, container: str, path: str) -> str:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "docker", "cp", f"{container}:{path}", "-"],
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        if len(members) != 1:
            raise RuntimeError(f"expected one file in Docker copy of {path}")
        extracted = archive.extractfile(members[0])
        if extracted is None:
            raise RuntimeError(f"could not read Docker file {path}")
        return extracted.read().decode().strip()


def seal(namespace: str, name: str, values: dict[str, str]) -> bytes:
    command = [
        "kubectl",
        "create",
        "secret",
        "generic",
        name,
        "--namespace",
        namespace,
        "--dry-run=client",
        "--output=json",
    ]
    command.extend(f"--from-literal={key}={value}" for key, value in values.items())
    plain_secret = subprocess.run(command, check=True, capture_output=True).stdout
    return subprocess.run(
        [
            "kubeseal",
            "--format=yaml",
            "--controller-name=sealed-secrets",
            "--controller-namespace=kube-system",
        ],
        input=plain_secret,
        check=True,
        capture_output=True,
    ).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.1.167")
    parser.add_argument("--container", default="open-webui")
    parser.add_argument("--output", type=Path, default=Path("kubernetes/apps/secrets/open-webui-runtime-env.sealed.yaml"))
    args = parser.parse_args()

    values = source_environment(args.host, args.container)
    if not values:
        raise RuntimeError("source container has no environment values")
    if not values.get("WEBUI_SECRET_KEY"):
        values["WEBUI_SECRET_KEY"] = source_file(args.host, args.container, "/app/backend/.webui_secret_key")
    if not values["WEBUI_SECRET_KEY"]:
        raise RuntimeError("source Open WebUI secret key is empty")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(seal("open-webui", "runtime-env", values))
    print(args.output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
