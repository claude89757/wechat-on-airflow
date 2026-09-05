from __future__ import annotations

import hashlib
import logging
import os
import socket
import time
import uuid
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

LOGGER = logging.getLogger(__name__)
# One host consumer across all devices; the sender independently serializes each device.
CONSUMER_LOCK = 728190316


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
        keys = row["event_keys"]
        count = connection.execute(
            text("""
            SELECT count(*) FROM zacks.observed_slots s WHERE s.event_key = ANY(:keys)
            AND (s.booking_date + CAST(s.start_time AS time)) AT TIME ZONE 'Asia/Shanghai' > now()
            AND EXISTS (SELECT 1 FROM zacks.current_availability c
                WHERE c.event_key = s.event_key AND c.last_seen_at > now() - interval '15 minutes')
        """),
            {"keys": keys},
        ).scalar_one()
        if count != len(keys):
            valid = False
        else:
            valid = True
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
                    program_id = :program, updated_at = now()
                WHERE id = :id AND lease_owner = :worker AND status = 'processing'
            """),
                {"message": outbound, "program": program_id, "id": row["id"], "worker": worker},
            )
    if not valid:
        _finish(row, worker, "expired", "availability_changed")
    return valid


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
            _finish(row, worker, "retry", "sender_not_ready")
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
                    "idempotency_key": row["id"],
                },
                timeout=210,
            )
            payload = response.json()
            if response.status_code == 200 and payload.get("success") is True:
                _finish(row, worker, "sent")
            elif payload.get("error") in {
                "device_busy",
                "device_not_ready",
                "service_misconfigured",
            }:
                _finish(row, worker, "retry", str(payload.get("error")))
            elif payload.get("error") in {"invalid_request", "device_not_allowed"}:
                _finish(row, worker, "failed", str(payload.get("error")))
            else:
                # Unknown/partial UI send is NOT retried automatically.
                _finish(row, worker, "submission_unknown", "sender_result_unknown")
        except requests.ConnectTimeout:
            _finish(row, worker, "retry", "connection_timeout_before_submission")
        except Exception as exc:
            _finish(row, worker, "submission_unknown", type(exc).__name__)


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
                else:
                    time.sleep(5)
            except KeyboardInterrupt:
                return
            except Exception as exc:
                LOGGER.error("WeChat cycle failed: %s", type(exc).__name__)
                time.sleep(10)


if __name__ == "__main__":
    main()
