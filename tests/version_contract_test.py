from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PACKAGE_VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)


def test_named_release_version_is_consistent_across_package_and_changelog():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = project["project"]["version"]
    package_source = (ROOT / "src/wechat_airflow/__init__.py").read_text(encoding="utf-8")
    package_match = PACKAGE_VERSION_PATTERN.search(package_source)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert SEMVER_PATTERN.fullmatch(project_version)
    assert package_match is not None
    assert package_match.group(1) == project_version
    assert f"## [{project_version}] - " in changelog
