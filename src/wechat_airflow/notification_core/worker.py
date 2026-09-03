from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import UTC, datetime

from sqlalchemy import text

from wechat_airflow.notification_core.config import NotificationCoreSettings, load_settings
from wechat_airflow.notification_core.database import engine, ensure_schema
from wechat_airflow.notification_core.repository import (
    EmailDigestClaim,
    claim_email_digest,
    finish_daily_reservation,
    mark_claim_retry,
    mark_claim_submitted,
    mark_claim_suppressed,
    mark_provider_status,
    recover_expired_processing,
    reserve_daily_delivery,
    service_metrics,
    submitted_messages_due,
)
from wechat_airflow.notification_core.subscription_sync import synchronize_from_cloudflare
from wechat_airflow.notification_core.tencent_ses import (
    TencentSesError,
    delivery_status,
    send_template_email,
)
from wechat_airflow.notification_core.weather import evaluate_weather

LOGGER = logging.getLogger("zacks.notification_core.worker")
_STOP = False


def _delivery_mode() -> str:
    value = os.environ.get("ZACKS_CORE_DELIVERY_MODE", "shadow").strip().lower()
    return value if value in {"shadow", "active"} else "shadow"


def _stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _wait(settings: NotificationCoreSettings) -> None:
    if settings.redis_url:
        try:
            import redis

            client = redis.Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=0.5,
                socket_timeout=max(1.0, settings.worker_idle_seconds + 1),
                decode_responses=True,
            )
            client.blpop(
                "zacks:notification-core:wakeup",
                timeout=max(1, int(settings.worker_idle_seconds)),
            )
            return
        except Exception as exc:
            LOGGER.debug("Redis wake-up unavailable: %s", type(exc).__name__)
    time.sleep(settings.worker_idle_seconds)


def _send_one(settings: NotificationCoreSettings) -> bool:
    claim = claim_email_digest(settings)
    if claim is None:
        return False

    weather = evaluate_weather(settings)
    if claim.tier == "standard" and not weather.send_email:
        mark_claim_suppressed(
            claim,
            (
                "weather_suppressed:"
                f"precipitation={weather.precipitation_mm}:"
                f"threshold={weather.threshold_mm}"
            ),
            settings,
        )
        return True

    reserved, reason = reserve_daily_delivery(claim, settings)
    if not reserved:
        mark_claim_suppressed(claim, reason, settings)
        return True

    try:
        result = send_template_email(settings, claim.email, claim.subject, claim.body)
        mark_claim_submitted(
            claim,
            message_id=result.message_id,
            request_id=result.request_id,
            settings=settings,
        )
        finish_daily_reservation(claim, submitted=True, settings=settings)
        LOGGER.info(
            json.dumps(
                {
                    "event": "notification_digest_submitted",
                    "tier": claim.tier,
                    "itemCount": len(claim.row_ids),
                },
                ensure_ascii=False,
            )
        )
    except TencentSesError as exc:
        mark_claim_retry(
            claim,
            f"{exc.code}: {str(exc)[:400]}",
            definitive=exc.definitive,
            settings=settings,
        )
        finish_daily_reservation(claim, submitted=False, settings=settings)
        LOGGER.warning(
            "notification digest failed code=%s definitive=%s",
            exc.code,
            exc.definitive,
        )
    except Exception as exc:
        # An unexpected exception around the network call is treated as
        # uncertain to avoid blind duplicate delivery.
        mark_claim_retry(
            claim,
            f"unexpected:{type(exc).__name__}",
            definitive=False,
            settings=settings,
        )
        finish_daily_reservation(claim, submitted=False, settings=settings)
        LOGGER.exception("notification digest result is uncertain")
    return True


def _reconcile(settings: NotificationCoreSettings) -> int:
    checked = 0
    for message in submitted_messages_due(settings, limit=10):
        try:
            result = delivery_status(
                settings,
                message_id=message.message_id,
                recipient=message.email,
                submitted_at=message.submitted_at,
            )
            mark_provider_status(
                message,
                status=result.state,
                provider_status=result.provider_status,
                delivered_at=result.delivered_at,
                error=result.error,
                settings=settings,
            )
            checked += 1
        except TencentSesError as exc:
            LOGGER.warning("delivery reconciliation unavailable code=%s", exc.code)
            break
        except Exception:
            LOGGER.exception("delivery reconciliation failed")
            break
    return checked


def _run_with_lock(settings: NotificationCoreSettings) -> int:
    connection = engine(settings).connect()
    lock_name = "zacks-notification-core-email-worker"
    acquired = bool(
        connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": lock_name}
        ).scalar_one()
    )
    if not acquired:
        LOGGER.error("another notification-core worker already owns the singleton lock")
        connection.close()
        return 2

    last_sync = 0.0
    last_reconcile = 0.0
    last_lease_recovery = 0.0
    try:
        while not _STOP:
            now = time.monotonic()
            if now - last_sync >= settings.subscription_sync_seconds:
                try:
                    summary = synchronize_from_cloudflare(settings)
                    LOGGER.info(
                        json.dumps(
                            {"event": "subscription_snapshot_synced", **summary},
                            ensure_ascii=False,
                        )
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "subscription snapshot sync failed; local snapshot retained: %s",
                        type(exc).__name__,
                    )
                last_sync = now

            if _delivery_mode() == "active":
                if now - last_lease_recovery >= 60:
                    recovered = recover_expired_processing(settings)
                    if recovered:
                        LOGGER.error("marked %s expired email leases uncertain", recovered)
                    last_lease_recovery = now
                worked = _send_one(settings)
                if now - last_reconcile >= 300:
                    _reconcile(settings)
                    last_reconcile = now
                if worked:
                    continue
            _wait(settings)
    finally:
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name}
            )
        finally:
            connection.close()
    return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = load_settings()
    ensure_schema(settings)
    health = service_metrics(settings)
    LOGGER.info(
        json.dumps(
            {
                "event": "notification_core_started",
                "version": "0.7.0",
                "deliveryMode": _delivery_mode(),
                "snapshotReady": health["subscriptionSnapshot"]["ready"],
                "startedAt": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    return _run_with_lock(settings)


if __name__ == "__main__":
    raise SystemExit(main())
