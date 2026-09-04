from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_manual_ci_uses_first_parent_and_validates_sender_without_deploying() -> None:
    workflow = read(".github/workflows/ci.yml")

    assert 'EVENT_NAME: ${{ github.event_name }}' in workflow
    assert 'if [[ "$EVENT_NAME" == "workflow_dispatch" ]]' in workflow
    assert 'git rev-parse "${TARGET_COMMIT}^"' in workflow
    assert "--include-sender" in workflow
    assert "It is not a production deployment approval" in workflow


def test_host_entry_scripts_remain_runnable_on_the_production_python_36_host() -> None:
    for path in (
        "scripts/host_core_production.py",
        "scripts/configure_zacks_tunnel.py",
    ):
        source = read(path)
        ast.parse(source, filename=path, feature_version=(3, 6))
        assert "from __future__ import annotations" not in source
        assert "capture_output=" not in source
        assert "text=True" not in source
        assert "missing_ok=" not in source


def test_all_production_host_core_callers_use_python3() -> None:
    for path in (
        ".github/workflows/production-host-core.yml",
        ".github/workflows/production-host-core-v070.yml",
        ".github/workflows/production-ship.yml",
    ):
        workflow = read(path)
        assert "python scripts/host_core_production.py" not in workflow
        assert "python3 scripts/host_core_production.py" in workflow


def test_sql_snapshot_is_checksum_verified_on_runner_host_and_container() -> None:
    workflow = read(".github/workflows/production-host-core.yml")
    host_script = read("scripts/host_core_production.py")
    importer = read("scripts/import_d1_sql_export.py")

    assert "sha256sum" in workflow
    assert "--snapshot-sha256" in workflow
    assert "snapshot_sha256.lower()" in host_script
    assert "--expected-sha256" in host_script
    assert "D1 SQL export checksum mismatch" in importer
    assert "REQUIRED_TABLES" in importer
