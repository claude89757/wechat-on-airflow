from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts/host_core_production.py").read_text(encoding="utf-8")


def test_compose_exec_places_user_option_before_service() -> None:
    helper = SCRIPT.split("def compose_exec", 1)[1].split("def running_services", 1)[0]
    assert 'command = COMPOSE + ["exec", "-T"]' in helper
    assert 'command += ["--user", str(user)]' in helper
    assert "command += [service] + list(arguments)" in helper
    assert helper.index('command += ["--user", str(user)]') < helper.index(
        "command += [service] + list(arguments)"
    )
    assert "completed = run(command, check=check, capture=capture)" in helper


def test_d1_snapshot_is_reowned_before_application_import() -> None:
    migration = SCRIPT.split("def migrate_sql", 1)[1].split("def enable_dual", 1)[0]
    uid_lookup = 'runtime_uid = compose_exec("zacks-api", "id", "-u", capture=True)'
    ownership = 'f"{runtime_uid}:0"'
    importer = '"/opt/airflow/project/scripts/import_d1_sql_export.py"'
    assert uid_lookup in migration
    assert ownership in migration
    assert 'user="0:0"' in migration
    assert migration.index(uid_lookup) < migration.index('compose("cp"')
    assert migration.index(ownership) < migration.index(importer)


def test_d1_snapshot_cleanup_is_root_and_cannot_mask_import_error() -> None:
    migration = SCRIPT.split("def migrate_sql", 1)[1].split("def enable_dual", 1)[0]
    cleanup = migration.split("finally:", 1)[1]
    assert '"rm"' in cleanup
    assert 'user="0:0"' in cleanup
    assert "check=False" in cleanup
