#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PACKAGE_VERSION = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)


class ContractError(RuntimeError):
    pass


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
    args = parser.parse_args()

    notes = validate(args.root.resolve(), args.version)
    if args.notes_output:
        args.notes_output.write_text(notes, encoding="utf-8")
    print(f"release contract valid for {args.version}")


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        raise SystemExit(f"release-contract: {exc}") from exc
