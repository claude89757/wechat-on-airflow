from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from sqlalchemy import text

from wechat_airflow.notifications.booking_links import (
    BOOKING_LINK_COOLDOWN,
    attach_footer,
    program_for_venue,
)

from .control import delivery_guard, runtime_state
from .database import ensure_schema, get_engine, transaction
from .service import active_subscription_for_venue, runtime_heartbeat
from .settings import _first_value, load_settings
from .wechat_queue import current_message

LOGGER = logging.getLogger(__name__)
# One host consumer across all devices; the sender independently serializes each device.
CONSUMER_LOCK = 728190316
MAX_ATTEMPTS = 3
SENDER_ERRORS = {
    "device_busy",
    "device_not_ready",
    "service_misconfigured",
    "ledger_unavailable",
    "wechat_not_ready",
    "contact_not_found",
    "appium_timeout",
    "send_failed",
    "submission_unknown",
    "idempotency_conflict",
    "invalid_request",
    "device_not_allowed",
}


def sender_readiness() -> dict[str, Any]:
    endpoint = _first_value("WECHAT_SEND_API_URL") or ""
    device = _first_value("WECHAT_SEND_DEVICE_NAME") or ""
    if not endpoint or not device:
        return {"ok": False, "reason": "sender_configuration_missing"}
    parsed = urlsplit(endpoint)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "/readyz", "", ""))
    try:
        response = requests.get(origin, timeout=20)
        body = response.json()
        return {
            "ok": response.status_code == 200 and body.get("ok") is True,
            "appiumReady": body.get("appium_ready") is True,
            "deviceReady": body.get("device_ready") is True,
            "deploymentCommit": body.get("deploymentCommit"),
            "durableIdempotency": body.get("durableIdempotency") is True,
            "cloudflareProxyObserved": bool(response.headers.get("cf-ray")),
        }
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}


def _claim(worker_id: str) -> dict[str, Any] | None:
    with transaction() as connection:
        connection.execute(
            text("""
            UPDATE zacks.wechat_outbox SET status = 'submission_unknown', updated_at = now(),
                last_error = 'dispatch interrupted; investigate before replay'
            WHERE status = 'dispatching' AND lease_until < now()
        """)
        )
        connection.execute(
            text("""
            UPDATE zacks.wechat_outbox SET status = 'expired', updated_at = now()
            WHERE status IN ('pending','retry','processing') AND expires_at <= now()
        """)
        )
        row = (
            connection.execute(
                text("""
            SELECT * FROM zacks.wechat_outbox
            WHERE status IN ('pending','retry','processing') AND next_attempt_at <= now()
                AND expires_at > now() AND (lease_until IS NULL OR lease_until < now())
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
        """)
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        connection.execute(
            text("""
            UPDATE zacks.wechat_outbox SET status = 'processing', lease_owner = :worker,
                lease_until = now() + interval '300 seconds', attempt_count = attempt_count + 1,
                updated_at = now() WHERE id = :id
        """),
            {"worker": worker_id, "id": row["id"]},
        )
        return {**dict(row), "attempt_count": int(row["attempt_count"]) + 1}


def _finish(row: dict[str, Any], worker: str, status: str, reason: str | None = None) -> None:
    if status in {"failed", "submission_unknown"}:
        LOGGER.error(
            "WeChat delivery requires attention venue=%s status=%s reason=%s",
            row["venue_id"],
            status,
            reason,
        )
    with transaction() as connection:
        connection.execute(
            text("""
            UPDATE zacks.wechat_outbox SET status = :status, last_error = :reason,
                sent_at = CASE WHEN :status = 'sent' THEN now() ELSE sent_at END,
                next_attempt_at = now() + interval '15 seconds',
                lease_owner = NULL, lease_until = NULL, updated_at = now()
            WHERE id = :id AND lease_owner = :worker
        """),
            {"status": status, "reason": reason, "id": row["id"], "worker": worker},
        )
        if status == "sent" and row.get("program_id"):
            connection.execute(
                text("""
                INSERT INTO zacks.booking_link_cooldowns(receiver_hash, program_id, sent_at)
                VALUES (:receiver, :program, now()) ON CONFLICT(receiver_hash, program_id)
                DO UPDATE SET sent_at = EXCLUDED.sent_at
            """),
                {
                    "receiver": hashlib.sha256(row["receiver"].encode()).hexdigest(),
                    "program": row["program_id"],
                },
            )


def _prepare(row: dict[str, Any], worker: str) -> bool:
    if not active_subscription_for_venue(str(row["venue_id"])):
        _finish(row, worker, "cancelled", "no_active_subscription")
        return False
    with transaction() as connection:
        slots = [
            dict(slot)
            for slot in connection.execute(
                text("""
            SELECT s.* FROM zacks.observed_slots s WHERE s.event_key = ANY(:keys)
            AND (s.booking_date + CAST(s.start_time AS time)) AT TIME ZONE 'Asia/Shanghai' > now()
            AND EXISTS (SELECT 1 FROM zacks.current_availability c
                WHERE c.event_key = s.event_key AND c.last_seen_at > now() - interval '15 minutes')
            """),
                {"keys": row["event_keys"]},
            ).mappings()
        ]
        message, keys, _rejected = current_message(row["message"], slots)
        valid = bool(keys)
        if valid:
            if message != row["message"]:
                row["outbound_message"] = None
                row["message"] = message
            row["event_keys"] = keys
            outbound = row.get("outbound_message") or row["message"]
            program = program_for_venue(str(row["venue_id"]))
            program_id = row.get("program_id")
            if program and not row.get("outbound_message"):
                last = connection.execute(
                    text("""
                    SELECT sent_at FROM zacks.booking_link_cooldowns
                    WHERE receiver_hash = :receiver AND program_id = :program
                """),
                    {
                        "receiver": hashlib.sha256(row["receiver"].encode()).hexdigest(),
                        "program": program.program_id,
                    },
                ).scalar_one_or_none()
                from .domain import utc_now

                if last is None or utc_now() - last >= BOOKING_LINK_COOLDOWN:
                    outbound = attach_footer(outbound, program.link)
                    program_id = program.program_id
            row["outbound_message"] = outbound
            row["program_id"] = program_id
            connection.execute(
                text("""
                UPDATE zacks.wechat_outbox SET status = 'dispatching', outbound_message = :message,
                    message = :source_message, event_keys = CAST(:keys AS jsonb), program_id = :program, updated_at = now()
                WHERE id = :id AND lease_owner = :worker AND status = 'processing'
            """),
                {
                    "message": outbound,
                    "source_message": row["message"],
                    "keys": json.dumps(keys),
                    "program": program_id,
                    "id": row["id"],
                    "worker": worker,
                },
            )
    if not valid:
        _finish(row, worker, "expired", "availability_changed")
    return valid


def _retry(row: dict[str, Any], worker: str, reason: str) -> None:
    _finish(row, worker, "retry" if row["attempt_count"] < MAX_ATTEMPTS else "failed", reason)


def deliver(row: dict[str, Any], worker: str) -> None:
    # Pause/cancel takes the exclusive lock; it waits for this bounded call to finish.
    with delivery_guard() as enabled:
        if not enabled:
            _finish(row, worker, "retry", "delivery_paused")
            return
        readiness = sender_readiness()
        if (
            not readiness["ok"]
            or not readiness.get("durableIdempotency")
            or readiness.get("deploymentCommit") != os.environ.get("DEPLOYMENT_COMMIT")
        ):
            _retry(row, worker, "sender_not_ready")
            return
        if not _prepare(row, worker):
            return
        endpoint = _first_value("WECHAT_SEND_API_URL") or ""
        try:
            response = requests.post(
                endpoint,
                json={
                    "receiver": row["receiver"],
                    "device_name": row["device_name"],
                    "messages": [row["outbound_message"]],
                    # Retries with an unchanged payload keep the same identity.
                    # A known-unsent digest pruned before retry gets its own payload identity.
                    "idempotency_key": hashlib.sha256(
                        (row["id"] + "\0" + row["outbound_message"]).encode()
                    ).hexdigest(),
                },
                timeout=210,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("sender_response_invalid")
            error = str(payload.get("error") or "sender_result_unknown")
            if error not in SENDER_ERRORS:
                error = "sender_result_unknown"
            if response.status_code == 200 and payload.get("success") is True:
                _finish(row, worker, "sent")
            elif error in {
                "device_busy",
                "device_not_ready",
                "service_misconfigured",
                "ledger_unavailable",
            } or (
                payload.get("safe_to_retry") is True
                and payload.get("submission_state") == "not_submitted"
                and payload.get("sent_count") == 0
                and error in SENDER_ERRORS
            ):
                _retry(row, worker, error)
            elif payload.get("error") in {"invalid_request", "device_not_allowed"}:
                _finish(row, worker, "failed", str(payload.get("error")))
            else:
                # Unknown/partial UI send is NOT retried automatically.
                _finish(row, worker, "submission_unknown", error)
        except requests.ConnectTimeout:
            _retry(row, worker, "connection_timeout_before_submission")
        except Exception as exc:
            _finish(row, worker, "submission_unknown", type(exc).__name__)


def reconcile_unknown() -> None:
    """A ledger-confirmed send may clear uncertainty; all other states stay quarantined."""
    endpoint = _first_value("WECHAT_SEND_API_URL") or ""
    if not endpoint:
        return
    parsed = urlsplit(endpoint)
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, "/v1/wechat/status", "", ""))
    with transaction() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                text("""
            SELECT * FROM zacks.wechat_outbox WHERE status='submission_unknown'
            AND created_at > now() - interval '1 day' AND next_attempt_at <= now()
            ORDER BY next_attempt_at LIMIT 5 FOR UPDATE SKIP LOCKED
        """)
            ).mappings()
        ]
        for row in rows:
            connection.execute(
                text("""
                UPDATE zacks.wechat_outbox SET next_attempt_at=now()+interval '5 minutes'
                WHERE id=:id AND status='submission_unknown'
            """),
                {"id": row["id"]},
            )
    for row in rows:
        if not row.get("outbound_message"):
            continue
        canonical = json.dumps(
            {
                "device": row["device_name"],
                "receiver": row["receiver"],
                "messages": [row["outbound_message"]],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        derived_key = hashlib.sha256(
            (row["id"] + "\0" + row["outbound_message"]).encode()
        ).hexdigest()
        # Old rows used the queue ID directly. Either lookup must match the full payload.
        for key in (derived_key, row["id"]):
            try:
                response = requests.post(
                    endpoint, json={"idempotency_key": key, "payload_hash": payload_hash}, timeout=5
                )
                response.raise_for_status()
                evidence = response.json()
                if (
                    not isinstance(evidence, dict)
                    or evidence.get("confirmed") is not True
                    or evidence.get("sent_count") != 1
                ):
                    continue
                stamp = datetime.fromisoformat(str(evidence["updated_at"]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=UTC)
                with transaction() as connection:
                    connection.execute(
                        text("""
                        UPDATE zacks.wechat_outbox SET status='sent', sent_at=:sent,
                        last_error=NULL, lease_owner=NULL, lease_until=NULL, updated_at=now()
                        WHERE id=:id AND status='submission_unknown'
                    """),
                        {"id": row["id"], "sent": stamp},
                    )
                    if row.get("program_id"):
                        connection.execute(
                            text("""
                            INSERT INTO zacks.booking_link_cooldowns(receiver_hash,program_id,sent_at)
                            VALUES(:receiver,:program,:sent) ON CONFLICT(receiver_hash,program_id)
                            DO UPDATE SET sent_at=GREATEST(zacks.booking_link_cooldowns.sent_at,EXCLUDED.sent_at)
                        """),
                            {
                                "receiver": hashlib.sha256(row["receiver"].encode()).hexdigest(),
                                "program": row["program_id"],
                                "sent": stamp,
                            },
                        )
                break
            except Exception as exc:
                LOGGER.warning("Sender reconciliation unavailable: %s", type(exc).__name__)
                break


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ensure_schema()
    worker = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    with get_engine().connect() as lock:
        if not lock.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": CONSUMER_LOCK}
        ).scalar_one():
            raise RuntimeError("Another WeChat consumer already owns the device queue")
        backend_pid = lock.execute(text("SELECT pg_backend_pid()")).scalar_one()
        lock.commit()
        next_reconcile = 0.0
        while True:
            # Losing the dedicated lock connection is fatal: never auto-reconnect
            # and continue sending without the session-level device fence.
            if lock.invalidated or lock.closed:
                raise RuntimeError("WeChat ownership connection lost")
            if lock.execute(text("SELECT pg_backend_pid()")).scalar_one() != backend_pid:
                raise RuntimeError("WeChat ownership connection changed")
            lock.commit()
            try:
                settings = load_settings()
                runtime_heartbeat(
                    "zacks-wechat-worker",
                    settings.deployment_commit,
                    {"mode": settings.delivery_owner},
                )
                row = (
                    _claim(worker)
                    if settings.host_owns_delivery and runtime_state()["wechat_enabled"]
                    else None
                )
                if row:
                    deliver(row, worker)
                elif time.monotonic() >= next_reconcile:
                    reconcile_unknown()
                    next_reconcile = time.monotonic() + 60
                else:
                    time.sleep(5)
            except KeyboardInterrupt:
                return
            except Exception as exc:
                LOGGER.error("WeChat cycle failed: %s", type(exc).__name__)
                time.sleep(10)


if __name__ == "__main__":
    main()
