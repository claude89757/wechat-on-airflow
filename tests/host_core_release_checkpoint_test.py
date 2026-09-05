from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from wechat_airflow.host_core.migration import EXPORT_TABLES
from wechat_airflow.host_core.release_checkpoint import migration_reconciled

ROOT = Path(__file__).resolve().parents[1]


def proof():
    return {
        "reconciliation": {
            **{table: {"sourceCount": 2, "matchedCount": 2, "keysSha256": "a" * 64} for table in EXPORT_TABLES},
            "providerIdentityPreserved": True,
        }
    }


def test_migration_checkpoint_requires_all_identities_and_provider_proof():
    assert migration_reconciled(proof()) is True
    for table in EXPORT_TABLES:
        value = copy.deepcopy(proof())
        del value["reconciliation"][table]
        assert migration_reconciled(value) is False
    value = proof()
    value["reconciliation"]["providerIdentityPreserved"] = False
    assert migration_reconciled(value) is False


@pytest.mark.parametrize("count", [None, True, -1, "2", 3])
def test_migration_checkpoint_rejects_invalid_or_unmatched_counts(count):
    value = proof()
    value["reconciliation"]["subscriptions"]["sourceCount"] = count
    assert migration_reconciled(value) is False


@pytest.mark.parametrize("value", [None, {}, {"reconciliation": []}])
def test_migration_checkpoint_rejects_missing_or_malformed_proof(value):
    assert migration_reconciled(value) is False


@pytest.mark.parametrize("complete,edge_active,success", [(True, True, True), (False, True, False)])
def test_release_resume_never_reimports_after_completed_migration(tmp_path, complete, edge_active, success):
    if not shutil.which("jq"):
        pytest.skip("jq is required for the release shell contract")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "calls"
    scripts = {
        "ssh": (
            '#!/bin/sh\necho "ssh $*" >> "$CALL_LOG"\n'
            'case "$*" in\n'
            '*release_checkpoint*) printf "%s\\n" "$CHECKPOINT" ;;\n'
            '*prepare-runtime*) echo \'{"previouslyActivated":false,"success":true}\' ;;\n'
            '*) echo \'{"success":true}\' ;;\nesac\n'
        ),
        "curl": '#!/bin/sh\nprintf "%s\\n" "$EDGE_RESPONSE"\n',
        "node": '#!/bin/sh\necho "node $*" >> "$CALL_LOG"\ncat >/dev/null\n',
        "npx": '#!/bin/sh\necho "npx $*" >> "$CALL_LOG"\n',
        "python": '#!/bin/sh\necho "python health" >> "$CALL_LOG"\n',
        "sleep": '#!/bin/sh\necho "sleep $*" >> "$CALL_LOG"\n',
    }
    for name, content in scripts.items():
        path = binaries / name
        path.write_text(content)
        path.chmod(0o755)
    environment = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        TARGET_COMMIT="a" * 40,
        OPERATION="full-cutover",
        AIRFLOW_SSH_HOST="test-only-host",
        AIRFLOW_SSH_PORT="22",
        AIRFLOW_SSH_USER="test-only-user",
        AIRFLOW_REPOSITORY_PATH="/test-only-repository",
        CALL_LOG=str(log),
        CHECKPOINT=json.dumps({"migrationComplete": complete, "everActivated": False}),
        EDGE_RESPONSE=json.dumps({"cutover": edge_active}),
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/host_core_release.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = log.read_text()
    assert (result.returncode == 0) is success
    for forbidden in ("d1 export", "migrate-sql", "sync-secrets", "node - maintenance", "sleep 300"):
        assert forbidden not in calls
    if success:
        assert "resume_verified_migration" in result.stdout
        assert "prepare-routing" in calls
        assert "node - production" in calls
        assert " cutover " in calls
    else:
        assert "refusing D1 re-import" in result.stderr
        assert "pause-host-delivery" in calls
