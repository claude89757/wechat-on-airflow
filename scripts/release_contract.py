#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import tomllib
from datetime import datetime
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PACKAGE_VERSION = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
COMMIT = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$")


class ContractError(RuntimeError):
    pass


def validate_recovery(
    *,
    version: str,
    target_commit: str,
    scope: str,
    include_sender: bool,
    runtime_commit: str,
    control_updated_at: str,
    delivery_enabled: bool,
    wechat_enabled: bool,
) -> None:
    """Accept only the recorded email-active, WeChat-paused recovery baseline."""
    if not any((runtime_commit, control_updated_at, delivery_enabled, wechat_enabled)):
        return
    if not COMMIT.fullmatch(target_commit) or not COMMIT.fullmatch(runtime_commit):
        raise ContractError("recovery requires exact target and existing runtime commits")
    if target_commit == runtime_commit:
        raise ContractError("recovery must align a new reviewed release commit")
    if version == "0.7.0" or scope != "all" or not include_sender:
        raise ContractError("recovery requires a full release and explicit Sender deployment")
    if not delivery_enabled or wechat_enabled:
        raise ContractError("recovery requires active email and paused WeChat")
    if not UTC_TIMESTAMP.fullmatch(control_updated_at):
        raise ContractError("recovery requires the exact UTC control timestamp")
    try:
        datetime.fromisoformat(control_updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid recovery control timestamp") from exc


def release_notes(root: Path, version: str) -> str:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = f"## [{version}] - "
    start = changelog.find(heading)
    if start < 0:
        raise ContractError("changelog release section is missing")
    next_heading = changelog.find("\n## [", start + len(heading))
    return changelog[start : next_heading if next_heading >= 0 else None].strip() + "\n"


def validate(root: Path, version: str) -> str:
    if not SEMVER.fullmatch(version):
        raise ContractError("version must use MAJOR.MINOR.PATCH without a v prefix")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_source = (root / "src/wechat_airflow/__init__.py").read_text(encoding="utf-8")
    package_match = PACKAGE_VERSION.search(package_source)
    if project["project"]["version"] != version:
        raise ContractError("pyproject version does not match requested release")
    if package_match is None or package_match.group(1) != version:
        raise ContractError("runtime package version does not match requested release")
    return release_notes(root, version)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate semantic version and changelog release contract."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--notes-output", type=Path)
    parser.add_argument("--target-commit", default="")
    parser.add_argument("--scope", default="auto")
    parser.add_argument("--include-sender", action="store_true")
    parser.add_argument("--recovery-runtime-commit", default="")
    parser.add_argument("--recovery-control-updated-at", default="")
    parser.add_argument("--recovery-delivery-enabled", action="store_true")
    parser.add_argument("--recovery-wechat-enabled", action="store_true")
    args = parser.parse_args()

    notes = validate(args.root.resolve(), args.version)
    validate_recovery(
        version=args.version,
        target_commit=args.target_commit,
        scope=args.scope,
        include_sender=args.include_sender,
        runtime_commit=args.recovery_runtime_commit,
        control_updated_at=args.recovery_control_updated_at,
        delivery_enabled=args.recovery_delivery_enabled,
        wechat_enabled=args.recovery_wechat_enabled,
    )
    if args.notes_output:
        args.notes_output.write_text(notes, encoding="utf-8")
    print(f"release contract valid for {args.version}")


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        raise SystemExit(f"release-contract: {exc}") from exc
