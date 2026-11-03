from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_core_routine", ROOT / "scripts/host_core_production.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("mismatch", [None, "tunnel", "observation", "gate"])
def test_existing_configuration_is_verified_without_changes(mismatch):
    values = [MODULE.LOCAL_OBSERVATION_URL, "enforce"]
    if mismatch == "observation":
        values[0] = "unexpected"
    if mismatch == "gate":
        values[1] = "unexpected"
    with (
        patch.object(
            MODULE,
            "run",
            return_value=SimpleNamespace(
                stdout='{"changed":'
                + ("true" if mismatch == "tunnel" else "false")
                + ',"applied":false}'
            ),
        ) as run,
        patch.object(MODULE, "variable_get", side_effect=values),
        patch.object(MODULE, "variable_set", side_effect=AssertionError("must not mutate")),
    ):
        if mismatch:
            with pytest.raises(RuntimeError, match="explicit repair required"):
                MODULE.verify_existing_configuration()
        else:
            MODULE.verify_existing_configuration()
    args = run.call_args.args[0]
    assert "--apply" not in args and "--restart" not in args


def test_routine_routing_preserves_configuration_and_caches():
    with (
        patch.object(MODULE, "assert_target"),
        patch.object(MODULE, "already_activated", return_value=True),
        patch.object(MODULE, "verify_existing_configuration") as verify,
        patch.object(MODULE, "variable_set", side_effect=AssertionError("no config write")),
        patch.object(MODULE, "compose_exec", side_effect=AssertionError("no cache deletion")),
        patch.object(MODULE, "_wait_for_local_health") as health,
        patch.object(MODULE, "_wait_for_local_ready") as ready,
    ):
        result = MODULE.prepare_routing("a" * 40)
    verify.assert_called_once_with()
    health.assert_called_once_with("a" * 40)
    ready.assert_called_once_with()
    assert result["existingConfigurationPreserved"] and result["cachesPreserved"]


def test_runtime_configuration_gate_precedes_backup_fence_and_service_changes():
    source = (
        (ROOT / "scripts/host_core_production.py")
        .read_text()
        .split("def prepare_runtime(", 1)[1]
        .split("def sync_secrets", 1)[0]
    )
    assert source.index("verify_existing_configuration()") < source.index("backup_dir =")
    assert source.index("verify_existing_configuration()") < source.index(
        "set_delivery_enabled(False"
    )
    assert "if not routine_upgrade:" in source
    assert source.index("if not routine_upgrade:") < source.index('"--apply"')


@pytest.mark.parametrize(
    "missing",
    [
        None,
        "everActivated",
        "migrationComplete",
        "deliveryEnabled",
        "wechatEnabled",
        "deploymentCommit",
    ],
)
def test_routine_preflight_uses_live_checkpoint_and_fails_closed(tmp_path, missing):
    checkpoint = {
        "everActivated": True,
        "migrationComplete": True,
        "deliveryEnabled": True,
        "wechatEnabled": True,
        "deploymentCommit": "b" * 40,
    }
    if missing:
        checkpoint.pop(missing)
    (tmp_path / "zacks_edge_token").write_text("existing-identity-value")
    with (
        patch.dict(os.environ, {"AIRFLOW_SECRET_DIR": str(tmp_path)}),
        patch.object(MODULE, "preflight", return_value={}),
        patch.object(MODULE, "host_python", return_value=json.dumps(checkpoint)) as probe,
        patch.object(MODULE, "variable_get", return_value="existing-identity-value"),
        patch.object(MODULE, "verify_existing_configuration") as configuration,
        patch.object(MODULE, "local_health") as health,
        patch.object(MODULE, "local_ready"),
        patch.object(MODULE, "compose", side_effect=AssertionError("must not change services")),
        patch.object(
            MODULE, "one_shot", side_effect=AssertionError("must not build/run candidate")
        ),
    ):
        if missing:
            with pytest.raises(RuntimeError, match="routine upgrade"):
                MODULE.routine_preflight("a" * 40)
            configuration.assert_not_called()
        else:
            result = MODULE.routine_preflight("a" * 40)
            assert result["currentDeploymentCommit"] == "b" * 40
            health.assert_called_once_with("b" * 40)
    script = probe.call_args.args[0]
    assert "read_checkpoint(os.environ['DEPLOYMENT_COMMIT'])" in script
    assert "a" * 40 not in script


def test_routine_routing_cannot_fall_back_to_initial_migration():
    with (
        patch.object(MODULE, "assert_target"),
        patch.object(MODULE, "already_activated", return_value=False),
        patch.object(MODULE, "variable_set", side_effect=AssertionError("no mutation")),
        patch.object(MODULE, "compose_exec", side_effect=AssertionError("no cache deletion")),
        pytest.raises(RuntimeError, match="cannot initialize routing"),
    ):
        MODULE.prepare_routing("a" * 40, routine_only=True)


@pytest.mark.parametrize("failure", ["preflight", "prepare_guard", "after_fence"])
def test_routine_failure_pauses_only_after_mutation_marker(tmp_path, failure):
    source = (ROOT / "scripts/host_core_release.sh").read_text()
    control = source[source.index("changed=false\n") :]
    log = tmp_path / "prepare.log"
    control = control.replace("/tmp/host-core-prepare.log", str(log))
    calls = tmp_path / "calls"
    setup = r"""set -Eeuo pipefail
OPERATION=routine-upgrade
remote() {
  printf '%s\n' "$*" >> "$CALLS"
  if [[ "$1" == routine-preflight && "$FAILURE" == preflight ]]; then return 7; fi
  if [[ "$1" == prepare-runtime ]]; then
    if [[ "$FAILURE" == after_fence ]]; then
      echo '{"event": "host_runtime_mutation_started"}'
    fi
    return 8
  fi
}
"""
    result = subprocess.run(
        ["bash", "-c", setup + control],
        env={**os.environ, "CALLS": str(calls), "FAILURE": failure},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    operations = calls.read_text().splitlines()
    assert ("pause-host-delivery" in operations) is (failure == "after_fence")
    if failure == "preflight":
        assert operations == ["routine-preflight"]
    assert not any(
        "sync-secrets" in item or "migrate" in item or "prepare-routing" in item
        for item in operations
    )


def test_routine_ship_mode_is_fixed_and_blocks_first_migration():
    ship = (ROOT / ".github/workflows/production-ship.yml").read_text()
    shell = (ROOT / "scripts/host_core_release.sh").read_text()
    assert "inputs.version == '0.7.0' && 'full-cutover' || 'routine-upgrade'" in ship
    assert shell.index("remote routine-preflight") < shell.index(
        'remote prepare-runtime "${routine_args[@]}"'
    )
    assert shell.index("Routine upgrade cannot enter first-migration operations") < shell.index(
        "deploy_edge maintenance", shell.index('case "$OPERATION"')
    )
    source = (ROOT / "scripts/host_core_production.py").read_text()
    assert 'print(json.dumps({"event": "host_runtime_mutation_started"}), flush=True)' in source


def test_source_restore_requires_unchanged_live_baseline_not_same_component_sha():
    import yaml

    jobs = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())["jobs"]
    steps = jobs["operate"]["steps"]
    prepare = next(step for step in steps if step.get("id") == "prepare_remote")
    restore = next(
        step
        for step in steps
        if step.get("name") == "Restore source after rejected routine preflight"
    )
    assert "routine-upgrade" in restore["if"] and "failure()" in restore["if"]
    assert 'echo "live_commit=$live_commit"' in prepare["run"]
    assert "LIVE_COMMIT" in restore["env"]
    assert 'python - "$live"' in restore["run"]
    assert 'state.get("delivery_enabled") is True' in restore["run"]
    assert 'state.get("wechat_enabled") is True' in restore["run"]
    assert restore["run"].index('python - "$live"') < restore["run"].index(
        'git checkout --quiet --detach "$previous"'
    )
    for step in (prepare, restore):
        checked = subprocess.run(
            ["bash", "-n"], input=step["run"], capture_output=True, text=True, check=False
        )
        assert checked.returncode == 0, checked.stderr
