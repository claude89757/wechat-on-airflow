#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path("/etc/cloudflared/config.yml")
DEFAULT_HOSTNAME = "airflow.claude89757.cc"
DEFAULT_SERVICE = "http://127.0.0.1:8090"
PATH_PATTERN = "^/zacks-api/.*"


def desired_rule(hostname: str, service: str) -> dict[str, str]:
    return {"hostname": hostname, "path": PATH_PATTERN, "service": service}


def normalize_document(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("cloudflared configuration must be a mapping")
    document = {str(key): item for key, item in value.items()}
    ingress = document.get("ingress")
    if not isinstance(ingress, list) or not ingress:
        raise RuntimeError("cloudflared configuration has no ingress rules")
    if not all(isinstance(rule, dict) for rule in ingress):
        raise RuntimeError("cloudflared ingress contains an invalid rule")
    return document


def with_zacks_rule(
    document: dict[str, Any],
    *,
    hostname: str,
    service: str,
) -> tuple[dict[str, Any], bool]:
    rule = desired_rule(hostname, service)
    ingress = [dict(item) for item in document["ingress"]]
    existing_indexes = [
        index
        for index, item in enumerate(ingress)
        if item.get("hostname") == hostname and item.get("path") == PATH_PATTERN
    ]
    changed = False
    if existing_indexes:
        first = existing_indexes[0]
        if ingress[first] != rule:
            ingress[first] = rule
            changed = True
        for index in reversed(existing_indexes[1:]):
            ingress.pop(index)
            changed = True
    else:
        insertion = len(ingress)
        for index, item in enumerate(ingress):
            if item.get("hostname") == hostname and not item.get("path"):
                insertion = index
                break
            if str(item.get("service") or "").startswith("http_status:"):
                insertion = index
                break
        ingress.insert(insertion, rule)
        changed = True
    updated = dict(document)
    updated["ingress"] = ingress
    return updated, changed


def _dump(path: Path, document: dict[str, Any], mode: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(document, handle, sort_keys=False, allow_unicode=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, mode)


def validate(path: Path) -> None:
    subprocess.run(
        ["cloudflared", "--config", str(path), "tunnel", "ingress", "validate"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def write_atomic(path: Path, document: dict[str, Any]) -> None:
    metadata = path.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _dump(temporary, document, stat.S_IMODE(metadata.st_mode))
        try:
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
        except PermissionError:
            pass
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_candidate(config: Path, document: dict[str, Any]) -> None:
    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{config.name}.candidate.", suffix=".yml", dir=config.parent
    )
    os.close(descriptor)
    candidate = Path(candidate_name)
    try:
        _dump(candidate, document, 0o600)
        validate(candidate)
    finally:
        candidate.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add the host-owned Zacks API path to the existing Cloudflare Tunnel"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--hostname", default=DEFAULT_HOSTNAME)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart", action="store_true")
    arguments = parser.parse_args()

    if not arguments.config.is_file():
        raise RuntimeError(f"cloudflared configuration not found: {arguments.config}")
    document = normalize_document(yaml.safe_load(arguments.config.read_text(encoding="utf-8")))
    updated, changed = with_zacks_rule(
        document,
        hostname=arguments.hostname,
        service=arguments.service,
    )
    validate_candidate(arguments.config, updated)
    result: dict[str, Any] = {
        "config": str(arguments.config),
        "hostname": arguments.hostname,
        "path": PATH_PATTERN,
        "service": arguments.service,
        "changed": changed,
        "applied": False,
    }
    if not arguments.apply:
        print(json.dumps(result, sort_keys=True))
        return 0

    backup = arguments.config.with_suffix(arguments.config.suffix + ".pre-zacks-host-core")
    if changed:
        if not backup.exists():
            shutil.copy2(arguments.config, backup)
        write_atomic(arguments.config, updated)
    try:
        validate(arguments.config)
        if arguments.restart:
            subprocess.run(["systemctl", "restart", "cloudflared.service"], check=True)
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "cloudflared.service"],
                check=True,
            )
    except Exception:
        if changed and backup.exists():
            shutil.copy2(backup, arguments.config)
            if arguments.restart:
                subprocess.run(["systemctl", "restart", "cloudflared.service"], check=False)
        raise
    result["applied"] = True
    result["backup"] = str(backup)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
