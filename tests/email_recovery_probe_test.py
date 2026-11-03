"""Recovery guards plus real SQL checks on CI's disposable PostgreSQL only."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from wechat_airflow.host_core import database
from wechat_airflow.host_core.migration import EXPORT_TABLES

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "email_recovery_probe", ROOT / "scripts/email_recovery_probe.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

COMMIT = "b" * 40
BEFORE = datetime(2026, 11, 1, 2, 30, tzinfo=UTC)


class Result:
    def __init__(self, value=None):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        return self.value

    def one_or_none(self):
        return self.value


class TransactionEngine:
    def __init__(self):
        self.state = {
            "deployment_commit": COMMIT,
            "delivery_enabled": False,
            "wechat_enabled": False,
            "activated_at": BEFORE - timedelta(days=30),
            "updated_at": BEFORE,
            "phase": "paused",
            "acceptance_started_at": None,
        }
        self.statements = []

    @contextmanager
    def begin(self):
        original = copy.deepcopy(self.state)
        try:
            yield self
        except Exception:
            self.state = original
            raise

    def execute(self, statement, values=None):
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("SELECT deployment_commit"):
            return Result(copy.deepcopy(self.state))
        if "UPDATE zacks.runtime_control" in sql:
            assert values is not None
            if (
                self.state["deployment_commit"] != values["commit"]
                or self.state["updated_at"] != values["previous_timestamp"]
                or self.state["delivery_enabled"] != values["previous_enabled"]
                or self.state["wechat_enabled"]
            ):
                return Result(None)
            self.state.update(
                delivery_enabled=values["enabled"],
                phase=values["phase"],
                updated_at=self.state["updated_at"] + timedelta(seconds=1),
            )
            return Result(copy.deepcopy(self.state))
        return Result()


@pytest.fixture
def guarded_engine(monkeypatch):
    engine = TransactionEngine()
    monkeypatch.setenv("DEPLOYMENT_COMMIT", COMMIT)
    monkeypatch.setattr(probe, "get_engine", lambda: engine)
    monkeypatch.setattr(probe, "require_schema", lambda connection: None)
    monkeypatch.setattr(probe, "migration_complete", lambda connection: True)
    monkeypatch.setattr(probe, "load_tencent_email_settings", lambda: None)
    return engine


def test_enable_then_owned_pause_preserves_runtime_wechat_and_acceptance(guarded_engine):
    before = copy.deepcopy(guarded_engine.state)
    enabled = probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert enabled["state"]["deliveryEnabled"] is True
    assert enabled["updatedAt"] != BEFORE.isoformat()
    assert guarded_engine.state["activated_at"] == before["activated_at"]
    assert guarded_engine.state["acceptance_started_at"] is None
    assert guarded_engine.state["wechat_enabled"] is False
    assert guarded_engine.state["deployment_commit"] == COMMIT
    assert "pg_advisory_xact_lock" in guarded_engine.statements[2]
    paused = probe.mutate(COMMIT, "pause", enabled["updatedAt"])
    assert paused["state"]["deliveryEnabled"] is False
    assert guarded_engine.state["acceptance_started_at"] is None
    updates = [sql for sql in guarded_engine.statements if sql.lstrip().startswith("UPDATE")]
    assert len(updates) == 2
    assert all("UPDATE zacks.runtime_control" in sql for sql in updates)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("deployment_commit", "c" * 40, "control_runtime_mismatch"),
        ("wechat_enabled", True, "wechat_must_remain_disabled"),
        ("updated_at", BEFORE + timedelta(seconds=1), "control_state_changed"),
        ("delivery_enabled", True, "unexpected_delivery_state"),
        ("activated_at", None, "verified_activation_checkpoint_required"),
    ],
)
def test_changed_or_unverified_control_state_never_enables(guarded_engine, field, value, reason):
    guarded_engine.state[field] = value
    before = copy.deepcopy(guarded_engine.state)
    with pytest.raises(probe.RecoveryRefused, match=reason):
        probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert guarded_engine.state == before
    assert not any(sql.lstrip().startswith("UPDATE") for sql in guarded_engine.statements)


def test_missing_schema_or_migration_does_not_mutate(guarded_engine, monkeypatch):
    def missing_schema(connection):
        raise probe.RecoveryRefused("schema_fingerprint_mismatch")

    monkeypatch.setattr(probe, "require_schema", missing_schema)
    with pytest.raises(probe.RecoveryRefused, match="schema_fingerprint_mismatch"):
        probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert not any(sql.lstrip().startswith("UPDATE") for sql in guarded_engine.statements)
    monkeypatch.setattr(probe, "require_schema", lambda connection: None)
    monkeypatch.setattr(probe, "migration_complete", lambda connection: False)
    with pytest.raises(probe.RecoveryRefused, match="verified_activation_checkpoint_required"):
        probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert not any(sql.lstrip().startswith("UPDATE") for sql in guarded_engine.statements)


def test_failed_enable_cannot_be_replayed_and_old_rollback_cannot_pause_new_state(guarded_engine):
    enabled = probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    with pytest.raises(probe.RecoveryRefused, match="control_state_changed"):
        probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    guarded_engine.state["updated_at"] += timedelta(seconds=2)
    with pytest.raises(probe.RecoveryRefused, match="control_state_changed"):
        probe.mutate(COMMIT, "pause", enabled["updatedAt"])
    assert guarded_engine.state["delivery_enabled"] is True


def test_container_identity_and_aware_timestamp_required(guarded_engine, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_COMMIT", "c" * 40)
    with pytest.raises(probe.RecoveryRefused, match="container_runtime_mismatch"):
        probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert guarded_engine.statements == []
    with pytest.raises(probe.RecoveryRefused, match="timezone_required"):
        probe.parse_timestamp("2026-11-01T02:30:00")


def test_heartbeat_output_drops_unapproved_details():
    result = probe.heartbeat_summary(
        {
            "deployment_commit": COMMIT,
            "healthy": True,
            "updated_at": BEFORE,
            "details": {
                "mode": "shadow",
                "owner": False,
                "subscriber": 0,
                "reconciled": "private-value",
                "secret": "private-value",
            },
        }
    )
    assert result["mode"] == "shadow"
    assert result["owner"] is False
    assert "private-value" not in json.dumps(result)


def test_cli_failure_never_prints_database_error_or_secret(monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError("postgresql://private-password@private-host/private-db")

    monkeypatch.setattr(probe, "snapshot", fail)
    monkeypatch.setattr(sys, "argv", ["probe", COMMIT, "snapshot"])
    with pytest.raises(SystemExit):
        probe.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"ok": False, "errorType": "RuntimeError"}
    assert "private-" not in captured.out + captured.err


@pytest.fixture
def real_engine(monkeypatch):
    url = os.environ.get("ZACKS_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("isolated PostgreSQL test URL not supplied")
    parsed = make_url(url)
    if parsed.database != "zacks_test" or parsed.host not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("Refusing destructive recovery fixture outside isolated zacks_test")
    monkeypatch.setenv("ZACKS_DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_COMMIT", COMMIT)
    monkeypatch.setattr(probe, "load_tencent_email_settings", lambda: None)
    database.reset_engine_for_test()
    engine = database.get_engine()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == "zacks_test"
        connection.execute(text("DROP SCHEMA IF EXISTS zacks CASCADE"))
    database.ensure_schema(engine)
    proof = {
        "providerIdentityPreserved": True,
        **{
            name: {"sourceCount": 0, "matchedCount": 0, "keysSha256": "a" * 64}
            for name in EXPORT_TABLES
        },
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE zacks.runtime_control SET deployment_commit=:commit, delivery_enabled=false, "
                "wechat_enabled=false, activated_at=:before, updated_at=:before, phase='paused'"
            ),
            {"commit": COMMIT, "before": BEFORE},
        )
        connection.execute(
            text(
                "INSERT INTO zacks.migration_state(source,source_revision,imported_at,details) "
                "VALUES('cloudflare-d1','test',:before,CAST(:details AS jsonb))"
            ),
            {"before": BEFORE, "details": json.dumps({"reconciliation": proof})},
        )
    yield engine
    database.reset_engine_for_test()


def test_real_postgres_fence_cas_and_no_release_acceptance_change(real_engine):
    enabled = probe.mutate(COMMIT, "enable", BEFORE.isoformat())
    assert enabled["state"]["deliveryEnabled"] is True
    with pytest.raises(probe.RecoveryRefused, match="control_state_changed"):
        probe.mutate(COMMIT, "pause", BEFORE.isoformat())
    with real_engine.connect() as connection:
        state = connection.execute(text("SELECT * FROM zacks.runtime_control")).mappings().one()
        assert state["wechat_enabled"] is False
        assert state["acceptance_started_at"] is None
        assert state["activated_at"] == BEFORE
    paused = probe.mutate(COMMIT, "pause", enabled["updatedAt"])
    assert paused["state"]["deliveryEnabled"] is False


def test_real_snapshot_counts_only_new_provider_receipts_and_never_updates_rows(real_engine):
    with real_engine.begin() as connection:
        for row_id, submitted, delivered in (
            ("old", BEFORE - timedelta(minutes=1), BEFORE + timedelta(minutes=1)),
            ("new", BEFORE + timedelta(seconds=1), BEFORE + timedelta(minutes=1)),
        ):
            connection.execute(
                text(
                    "INSERT INTO zacks.notification_outbox "
                    "(id,subscription_id,event_key,venue_id,email,subject,body,status,next_attempt_at,"
                    "created_at,updated_at,submitted_at,delivered_at,message_id) VALUES "
                    "(:id,:id,:id,'szw','private@example.test','private-subject','private-body',"
                    "'delivered',:start,:start,:end,:start,:end,:id)"
                ),
                {"id": row_id, "start": submitted, "end": delivered},
            )
    result = probe.snapshot(COMMIT, BEFORE.isoformat())
    assert result["naturalEmail"]["submitted"] == 1
    assert result["naturalEmail"]["delivered"] == 1
    assert result["outboxes"]["notification_outbox"]["statuses"]["delivered"] == 2
    assert "private" not in json.dumps(result)
    assert result["state"]["deliveryEnabled"] is False
    assert result["state"]["updatedAt"] == BEFORE.isoformat()
