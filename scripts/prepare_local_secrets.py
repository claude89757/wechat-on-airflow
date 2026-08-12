#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

import yaml
from _ops import REPO_ROOT, OpsError


def secret_contract() -> tuple[Path, int, int, tuple[str, ...]]:
    runtime = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    target = runtime["target"]
    directory = REPO_ROOT / str(target["local_secret_directory"])
    directory_mode = int(str(target["local_secret_directory_mode"]), 8)
    file_mode = int(str(target["local_secret_file_mode"]), 8)
    filenames = tuple(str(value) for value in target["runtime_secrets"].values())
    return directory, directory_mode, file_mode, filenames


def create_secret(path: Path, mode: int) -> bool:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        if not path.is_file():
            raise OpsError(f"local secret path is not a file: {path}") from None
        path.chmod(mode)
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_urlsafe(48))
        handle.write("\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create ignored, development-only runtime secret files."
    )
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()

    default_directory, directory_mode, file_mode, filenames = secret_contract()
    directory = (args.directory or default_directory).resolve()
    directory.mkdir(mode=directory_mode, parents=True, exist_ok=True)
    directory.chmod(directory_mode)
    created = sum(create_secret(directory / filename, file_mode) for filename in filenames)
    print(f"local runtime secrets ready: files={len(filenames)} created={created}")


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"prepare-local-secrets: {exc}")
        raise SystemExit(1) from exc
