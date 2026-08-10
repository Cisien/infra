#!/usr/bin/env python3
"""Create SealedSecrets from the active Wavelog Portainer service settings."""

import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

MIGRATIONS = (
    (
        "wavelog_wavelog-db",
        "wavelog",
        "db-env",
        (
            "MARIADB_RANDOM_ROOT_PASSWORD",
            "MARIADB_DATABASE",
            "MARIADB_USER",
            "MARIADB_PASSWORD",
        ),
    ),
    ("wavelog_wavelog-main", "wavelog", "app-env", ("CI_ENV",)),
)


def get_services(url: str, api_key: str) -> list[dict]:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/endpoints/1/docker/services",
        headers={"X-API-Key": api_key},
    )
    with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=30) as response:
        return json.load(response)


def environment(service: dict) -> dict[str, str]:
    values = service["Spec"]["TaskTemplate"]["ContainerSpec"].get("Env", [])
    return dict(value.split("=", 1) for value in values if "=" in value)


def seal(namespace: str, name: str, values: dict[str, str]) -> str:
    create = [
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
    create.extend(f"--from-literal={key}={value}" for key, value in values.items())
    plain_secret = subprocess.run(create, check=True, capture_output=True).stdout
    sealed = subprocess.run(
        [
            "kubeseal",
            "--format=yaml",
            "--controller-name=sealed-secrets",
            "--controller-namespace=kube-system",
        ],
        input=plain_secret,
        check=True,
        capture_output=True,
    )
    return sealed.stdout.decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("PORTAINER_URL"))
    parser.add_argument("--api-key", default=os.environ.get("PORTAINER_API_KEY"))
    parser.add_argument("--output-dir", type=Path, default=Path("kubernetes/apps/secrets"))
    args = parser.parse_args()
    if not args.url or not args.api_key:
        parser.error("set PORTAINER_URL and PORTAINER_API_KEY, or pass --url and --api-key")

    services = {service["Spec"]["Name"]: service for service in get_services(args.url, args.api_key)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for source, namespace, target, keys in MIGRATIONS:
        if source not in services:
            raise RuntimeError(f"Portainer service not found: {source}")
        source_values = environment(services[source])
        missing = [key for key in keys if not source_values.get(key)]
        if missing:
            raise RuntimeError(f"{source} has missing environment values: {', '.join(missing)}")
        output = args.output_dir / f"{namespace}-{target}.sealed.yaml"
        output.write_text(seal(namespace, target, {key: source_values[key] for key in keys}))
        print(output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
