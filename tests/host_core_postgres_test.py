"""Real PostgreSQL contracts. The destructive fixture accepts ONLY zacks_test.

No production credentials or external requests are permitted. CI supplies a
throwaway PostgreSQL service; local execution requires ZACKS_TEST_DATABASE_URL.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from wechat_airflow.host_core import api, control, database, migration, service, weather, worker
from wechat_airflow.host_core.domain import hash_verification_code, utc_now
from wechat_airflow.host_core.settings import load_settings

URL = os.environ.get("ZACKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="isolated PostgreSQL test URL not supplied")
PREFIX = "/zacks-api/api"
EDGE = {"X-Zacks-Edge-Token": "test-edge-token"}


def sql(statement, params=None):
    with database.transaction() as c:
        result = c.execute(text(statement), params or {})
        return [dict(r) for r in result.mappings()] if result.returns_rows else []


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    url = make_url(URL)
    if url.database != "zacks_test" or url.host not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("Refusing destructive integration fixture outside isolated zacks_test")
    monkeypatch.setenv("ZACKS_DATABASE_URL", URL)
    for name, value in {
        "ZACKS_EDGE_TOKEN": "test-edge-token",
        "ZACKS_VERIFICATION_PEPPER": "test-verification-pepper",
        "ZACKS_INVITE_PEPPER": "test-invite-pepper",
        "DEPLOYMENT_COMMIT": "a" * 40,
        "WEATHER_EMAIL_GATE_ENABLED": "false",
        "TENCENT_SECRET_ID": "test-only-id",
        "TENCENT_SECRET_KEY": "test-only-secret",
        "EMAIL_FROM_ADDRESS": "test@example.test",
        "EMAIL_REPLY_TO": "test@example.test",
        "EMAIL_TEMPLATE_ID": "1",
    }.items():
        monkeypatch.setenv(name, value)
    database.reset_engine_for_test()
    engine = create_engine(URL)
    with engine.begin() as c:
        assert c.execute(text("SELECT current_database()")).scalar_one() == "zacks_test"
        c.execute(text("DROP SCHEMA IF EXISTS zacks CASCADE"))
    engine.dispose()
    database.ensure_schema()
    weather.reset_weather_cache_for_test()

    def forbidden(*args, **kwargs):
        raise AssertionError("external network is forbidden in PostgreSQL tests")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    yield
    database.reset_engine_for_test()


def client():
    return TestClient(api.app, headers=EDGE, raise_server_exceptions=True)


def identity(email="player@example.test"):
    token = uuid.uuid4().hex
    now = utc_now()
    sql(
        """INSERT INTO zacks.verified_receipts(token_hash, email, masked_email,
        expires_at,last_used_at,created_at) VALUES(:token,:email,'p***@example.test',
        :expires,:now,:now)""",
        {
            "token": hashlib.sha256(token.encode()).hexdigest(),
            "email": email,
            "expires": now + timedelta(days=1),
            "now": now,
        },
    )
    return {**EDGE, "Authorization": f"Bearer {token}"}


def subscription(c, headers, *, start="18:00", end="21:00", venues=None):
    response = c.post(
        PREFIX + "/subscriptions",
        headers=headers,
        json={
            "venueIds": venues or ["tops"],
            "startTime": start,
            "endTime": end,
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "termCode": "7d",
        },
    )
    return response


def observation(*, scope="day-1", healthy=True, slots=None, seen=None):
    day = (utc_now().astimezone(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat()
    return {
        "venue_id": "tops",
        "venue_name": "TOPS科技园网球场",
        "observation_scope": scope,
        "healthy": healthy,
        "checked_at": (seen or utc_now()).isoformat(),
        "slots": slots
        if slots is not None
        else [{"date": day, "court_name": "1号场", "start_time": "18:00", "end_time": "19:00"}],
    }


def make_pending(c, headers):
    sub = subscription(c, headers)
    assert sub.status_code == 201, sub.text
    result = service.ingest_observation(observation())
    assert result["matchedNotifications"] == 1
    sql("UPDATE zacks.notification_outbox SET next_attempt_at = now() - interval '1 second'")
    return sub.json()["id"]


def enable_for_test():
    # Tests seed an already-accepted control state; never reach a real provider.
    sql(
        "UPDATE zacks.runtime_control SET delivery_enabled=true, activated_at=now(), phase='active'"
    )


def claim():
    target = worker._next_subscriber_target()
    assert target
    return worker._claim_subscriber_group(
        "test-worker",
        load_settings(),
        target,
        weather.WeatherDecision(True, target["booking_date"], 0, 25, "test"),
    )


def test_wrong_code_attempts_commit_and_lock_out():
    code, challenge = "123456", "challenge"
    sql(
        """INSERT INTO zacks.verification_challenges(id,email,code_hash,ip_hash,expires_at,
        attempts,created_at) VALUES(:id,'test@example.test',:hash,'ip',now()+interval '10 minutes',0,now())""",
        {
            "id": challenge,
            "hash": hash_verification_code(challenge, code, "test-verification-pepper"),
        },
    )
    with client() as c:
        for _ in range(6):
            r = c.post(PREFIX + "/email/verify", json={"challengeId": challenge, "code": "999999"})
            assert r.status_code == 400
        assert sql("SELECT attempts FROM zacks.verification_challenges")[0]["attempts"] == 5
        assert (
            c.post(
                PREFIX + "/email/verify", json={"challengeId": challenge, "code": code}
            ).status_code
            == 400
        )


def test_verification_consumes_once_and_queues_expiring_code(monkeypatch):
    monkeypatch.setattr(api, "random_verification_code", lambda: "123456")
    with client() as c:
        r = c.post(PREFIX + "/email/send-code", json={"email": "test@example.test"})
        assert r.status_code == 200, r.text
        row = sql("SELECT expires_at,body FROM zacks.system_email_outbox")[0]
        assert row["expires_at"] > utc_now()
        payload = {"challengeId": r.json()["challengeId"], "code": "123456"}
        assert c.post(PREFIX + "/email/verify", json=payload).status_code == 200
        assert c.post(PREFIX + "/email/verify", json=payload).status_code == 400


def test_expired_subscription_can_be_recreated():
    with client() as c:
        h = identity()
        r = subscription(c, h)
        assert r.status_code == 201, r.text
        sql("UPDATE zacks.subscriptions SET active_until=now()-interval '1 second'")
        again = subscription(c, h)
        assert again.status_code == 201, again.text
    rows = sql("SELECT active,count(*) n FROM zacks.subscriptions GROUP BY active")
    assert {r["active"]: r["n"] for r in rows} == {True: 1, False: 1}


def test_concurrent_create_enforces_per_user_limit():
    h = identity()

    def create(i):
        with client() as c:
            return subscription(c, h, start=f"{i + 8:02d}:00", end=f"{i + 9:02d}:00").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(create, range(8)))
    assert statuses.count(201) == 5, statuses
    assert statuses.count(409) == 3, statuses


def test_concurrent_duplicate_is_one_subscription_no_500():
    h = identity()

    def create(_):
        with client() as c:
            return subscription(c, h).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(create, range(6)))
    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 5, statuses


def test_cancel_retracts_pending_reminder():
    with client() as c:
        h = identity()
        sub = make_pending(c, h)
        assert c.delete(PREFIX + "/subscriptions/" + sub, headers=h).status_code == 200
        assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "cancelled"
        assert worker._next_subscriber_target() is None


def test_concurrent_observation_dedupes_and_new_subscription_generation_matches():
    with client() as c:
        h = identity()
        assert subscription(c, h).status_code == 201
        payload = observation()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(service.ingest_observation, [payload] * 12))
        assert sum(r["matchedNotifications"] for r in results) == 1
        h2 = identity("second@example.test")
        assert subscription(c, h2).status_code == 201
        assert service.ingest_observation(observation())["matchedNotifications"] == 1
        assert sql("SELECT count(*) n FROM zacks.notification_outbox")[0]["n"] == 2


def test_empty_poll_invalidates_current_and_old_poll_cannot_resurrect():
    first = observation()
    service.ingest_observation(first)
    assert sql("SELECT count(*) n FROM zacks.current_availability")[0]["n"] == 1
    service.ingest_observation(observation(slots=[], seen=utc_now() + timedelta(seconds=1)))
    assert service.ingest_observation(first)["ignored"] == "older_observation"
    assert sql("SELECT count(*) n FROM zacks.current_availability")[0]["n"] == 0


def test_fake_email_submission_records_attempt_and_message_id(monkeypatch):
    calls = []

    def send(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(message_id="test-provider-1", request_id="test-request")

    monkeypatch.setattr(worker, "send_template_email", send)
    with client() as c:
        make_pending(c, identity())
        enable_for_test()
        rows = claim()
        worker._complete_subscriber(rows, "test-worker")
    out = sql("SELECT status,message_id FROM zacks.notification_outbox")[0]
    assert out == {"status": "submitted", "message_id": "test-provider-1"}
    assert sql("SELECT phase FROM zacks.delivery_attempts")[0]["phase"] == "submitted"
    assert calls == [1]
    assert worker._next_subscriber_target() is None


@pytest.mark.parametrize(
    "error,expected",
    [(requests.ConnectTimeout, "retry"), (requests.ReadTimeout, "submission_unknown")],
)
def test_transport_failure_distinguishes_unknown_submission(monkeypatch, error, expected):
    def fail(*args, **kwargs):
        raise error("simulated")

    monkeypatch.setattr(worker, "send_template_email", fail)
    with client() as c:
        make_pending(c, identity())
        enable_for_test()
        worker._complete_subscriber(claim(), "test-worker")
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == expected


def test_interrupted_dispatch_never_requeued_as_unsent():
    with client() as c:
        make_pending(c, identity())
        rows = claim()
        assert rows
    sql(
        "UPDATE zacks.notification_outbox SET status='dispatching',lease_until=now()-interval '1 second'"
    )
    worker._release_expired_leases()
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "submission_unknown"
    assert sql("SELECT status FROM zacks.email_delivery_claims")[0]["status"] == "unknown"
    assert worker._next_subscriber_target() is None


def test_availability_changed_after_claim_is_not_sent(monkeypatch):
    monkeypatch.setattr(
        worker, "send_template_email", lambda *a, **kw: pytest.fail("stale notification sent")
    )
    with client() as c:
        make_pending(c, identity())
        enable_for_test()
        rows = claim()
        service.ingest_observation(observation(slots=[]))
        worker._complete_subscriber(rows, "test-worker")
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "expired"


def test_verification_outbox_expires_before_retry(monkeypatch):
    monkeypatch.setattr(api, "random_verification_code", lambda: "123456")
    with client() as c:
        assert (
            c.post(PREFIX + "/email/send-code", json={"email": "code@example.test"}).status_code
            == 200
        )
    sql("UPDATE zacks.system_email_outbox SET expires_at=now()-interval '1 second'")
    worker._expire_unusable()
    assert worker._claim_system("test-worker") is None
    assert sql("SELECT status FROM zacks.system_email_outbox")[0]["status"] == "expired"


def test_migration_batches_reconciles_and_rejects_after_activation():
    now = utc_now().isoformat()
    snapshot = {k: [] for k in migration.EXPORT_TABLES}
    snapshot["user_profiles"] = [
        {
            "email": "migrate@example.test",
            "masked_email": "m***@example.test",
            "created_at": now,
            "updated_at": now,
        }
    ]
    counts = migration.import_snapshot(snapshot, source_revision="test-export-sha")
    assert counts["user_profiles"] == 1
    detail = sql("SELECT details FROM zacks.migration_state")[0]["details"]
    assert detail["reconciliation"]["user_profiles"]["matchedCount"] == 1
    control.set_delivery_enabled(True, "a" * 40)
    control.set_delivery_enabled(False, "a" * 40)
    with pytest.raises(RuntimeError, match="forbidden"):
        migration.import_snapshot(snapshot, source_revision="other-export")


def test_missing_ses_settings_returns_503(monkeypatch):
    def missing():
        raise RuntimeError("missing settings")

    monkeypatch.setattr(api, "load_tencent_email_settings", missing)
    with client() as c:
        r = c.get(PREFIX + "/readyz")
        assert r.status_code == 503, r.text
        assert r.json()["ok"] is False


def test_wechat_queue_is_durable_idempotent_and_has_expiry():
    from wechat_airflow.host_core.wechat_queue import enqueue

    with client() as c:
        assert subscription(c, identity()).status_code == 201
        payload = observation()
        service.ingest_observation(payload)
    day = payload["slots"][0]["date"]
    message = f"【1号场】星期日({day[5:]})空场: 18:00-19:00"
    request = {
        "venue_id": "tops",
        "receivers": ["test-only-group"],
        "device_name": "test-only-device",
        "message": message,
        "source": "test",
    }
    first = enqueue(request)
    second = enqueue(request)
    assert first["ids"] == second["ids"]
    rows = sql("SELECT status,expires_at FROM zacks.wechat_outbox")
    assert len(rows) == 1
    assert rows[0]["expires_at"] <= utc_now() + timedelta(minutes=5)


def test_wechat_changed_availability_is_expired_without_external_send():
    from wechat_airflow.host_core import wechat_queue, wechat_worker

    with client() as c:
        assert subscription(c, identity()).status_code == 201
        payload = observation()
        service.ingest_observation(payload)
    day = payload["slots"][0]["date"]
    wechat_queue.enqueue(
        {
            "venue_id": "tops",
            "receivers": ["test-only-group"],
            "device_name": "test-only-device",
            "message": f"【1号场】星期日({day[5:]})空场: 18:00-19:00",
            "source": "test",
        }
    )
    row = wechat_worker._claim("test-worker")
    assert row
    service.ingest_observation(observation(slots=[]))
    assert wechat_worker._prepare(row, "test-worker") is False
    assert sql("SELECT status FROM zacks.wechat_outbox")[0]["status"] == "expired"


def test_api_probe_uses_real_database_but_rolls_back_every_test_write():
    from wechat_airflow.host_core.api_probe import run_probe

    result = run_probe()
    assert result["complete"] and result["ok"], result
    assert len(result["checks"]) == 13
    assert result["externalTestSends"] == 0
    assert sql("SELECT count(*) AS n FROM zacks.subscriptions")[0]["n"] == 0
    assert sql("SELECT count(*) AS n FROM zacks.system_email_outbox")[0]["n"] == 0


def test_invalid_migration_proof_cannot_activate_delivery():
    import json

    sql(
        "INSERT INTO zacks.migration_state(source,source_revision,imported_at,details) VALUES('cloudflare-d1','test',now(),CAST(:proof AS jsonb))",
        {
            "proof": json.dumps(
                {
                    "reconciliation": {
                        **{
                            k: {"sourceCount": 1, "matchedCount": 0, "keysSha256": "f" * 64}
                            for k in migration.EXPORT_TABLES
                        },
                        "providerIdentityPreserved": True,
                    }
                }
            )
        },
    )
    with pytest.raises(RuntimeError, match="verified migration"):
        control.set_delivery_enabled(True, "a" * 40)
    assert not control.runtime_state()["delivery_enabled"]


def test_migration_invite_cipher_and_hash_are_preserved():
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from wechat_airflow.host_core.domain import decrypt_invite_code, hash_invite_code

    pepper = "test-invite-pepper"
    from wechat_airflow.host_core.domain import generate_invite_code

    plain = generate_invite_code()
    iv = b"0123456789ab"
    key = hashlib.sha256(f"zacks-invite-encryption:{pepper}".encode()).digest()

    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    row = {
        "id": "migrated-invite",
        "code_hash": hash_invite_code(plain, pepper),
        "encrypted_code": encode(AESGCM(key).encrypt(iv, plain.encode(), None)),
        "encryption_iv": encode(iv),
        "active": 1,
        "expires_at": (utc_now() + timedelta(days=30)).isoformat(),
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
    }
    snapshot = {k: [] for k in migration.EXPORT_TABLES}
    snapshot["priority_invite_codes"] = [row]
    migration.import_snapshot(snapshot, source_revision="cipher-test")
    saved = sql("SELECT * FROM zacks.priority_invite_codes")[0]
    assert saved["code_hash"] == row["code_hash"]
    assert decrypt_invite_code(saved["encrypted_code"], pepper) == plain
    with client() as c:
        headers = identity()
        result = c.post(PREFIX + "/priority/redeem", headers=headers, json={"code": plain})
        assert result.status_code == 200, result.text
        assert result.json()["tier"] == "priority"


def test_coffee_claim_is_serialized_across_sessions():
    with client() as c:
        headers = identity()
        sessions = [c.post(PREFIX + "/coffee/session", headers=headers).json() for _ in range(3)]
        sql("UPDATE zacks.coffee_invite_sessions SET claimable_at=now()-interval '1 second'")
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(
                pool.map(
                    lambda x: c.post(
                        PREFIX + "/coffee/invite",
                        headers=headers,
                        json={"claimToken": x["claimToken"]},
                    ),
                    sessions,
                )
            )
        assert all(x.status_code == 200 for x in responses), [x.text for x in responses]
        assert len({x.json()["code"] for x in responses}) == 1
    assert sql("SELECT count(*) AS n FROM zacks.coffee_invite_claims")[0]["n"] == 1


def test_provider_ack_then_database_failure_is_not_blindly_retried(monkeypatch):
    from contextlib import contextmanager

    calls = []
    monkeypatch.setattr(
        worker,
        "send_template_email",
        lambda *a, **k: (
            calls.append(1) or SimpleNamespace(message_id="provider-ack", request_id="request")
        ),
    )
    with client() as c:
        make_pending(c, identity())
        enable_for_test()
        rows = claim()
    original = worker.transaction
    entered = 0

    @contextmanager
    def unreliable(*args, **kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            raise RuntimeError("simulated DB outage after provider ACK")
        with original(*args, **kwargs) as connection:
            yield connection

    with monkeypatch.context() as patcher:
        patcher.setattr(worker, "transaction", unreliable)
        with pytest.raises(RuntimeError):
            worker._complete_subscriber(rows, "test-worker")
    assert calls == [1]
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "dispatching"
    sql("UPDATE zacks.notification_outbox SET lease_until=now()-interval '1 second'")
    worker._release_expired_leases()
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "submission_unknown"
    assert worker._next_subscriber_target() is None
    assert calls == [1]


def test_business_acceptance_requires_real_cycles_and_delivery(monkeypatch):
    import json
    from pathlib import Path

    import yaml

    from wechat_airflow.host_core import health
    from wechat_airflow.host_core.api_probe import run_probe

    migration.import_snapshot({k: [] for k in migration.EXPORT_TABLES}, source_revision="a" * 40)
    proof = run_probe()
    assert proof["ok"]
    sql(
        "UPDATE zacks.runtime_control SET delivery_enabled=true,wechat_enabled=true,deployment_commit=:sha,acceptance_started_at=now()-interval '60 seconds',api_acceptance=CAST(:probe AS jsonb)",
        {"sha": "a" * 40, "probe": json.dumps(proof)},
    )
    sql("UPDATE zacks.venue_status SET healthy=true,last_inspection_at=now()")
    sql(
        "INSERT INTO zacks.observation_state(observation_key,venue_id,fingerprint,healthy,last_seen_at,updated_at) VALUES ('tops:day','tops','fingerprint',true,now(),now())"
    )
    # These mock Airflow metadata tables are ONLY in the guarded disposable test DB.
    sql("CREATE TABLE IF NOT EXISTS dag(dag_id text PRIMARY KEY,is_paused boolean)")
    sql(
        "CREATE TABLE IF NOT EXISTS dag_run(dag_id text,run_type text,state text,start_date timestamptz,end_date timestamptz)"
    )
    sql("DELETE FROM dag")
    sql("DELETE FROM dag_run")
    manifest = yaml.safe_load(
        (Path(__file__).parents[1] / "config/active-components.yaml").read_text()
    )
    for entry in manifest["active_dags"]:
        sql("INSERT INTO dag VALUES(:id,false)", {"id": entry["dag_id"]})
        for _ in range(3):
            sql(
                "INSERT INTO dag_run VALUES(:id,'scheduled','success',now()-interval '20 seconds',now()-interval '1 second')",
                {"id": entry["dag_id"]},
            )
    for component in health.COMPONENT_MAX_AGE:
        service.runtime_heartbeat(component, "a" * 40, {})
    monkeypatch.setattr(
        health,
        "sender_readiness",
        lambda: {
            "ok": True,
            "deploymentCommit": "a" * 40,
            "durableIdempotency": True,
            "cloudflareProxyObserved": False,
        },
    )
    report = health.business_report("a" * 40, require_delivery=False)
    assert report["complete"] and report["ok"], report["failedChecks"]
    report = health.business_report("a" * 40, require_delivery=True)
    assert not report["ok"]
    assert set(report["failedChecks"]) == {
        "naturalEmailProviderDelivered",
        "naturalWeChatDelivered",
    }
    sql(
        "UPDATE dag_run SET state='failed' WHERE dag_id=:id",
        {"id": manifest["active_dags"][2]["dag_id"]},
    )
    report = health.business_report("a" * 40)
    assert not report["checks"]["allNaturalDagCycles"]
