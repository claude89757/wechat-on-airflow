from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from wechat_airflow.notification_core.config import load_settings
from wechat_airflow.notification_core.database import database_health, ensure_schema
from wechat_airflow.notification_core.repository import ingest_observation, service_metrics
from wechat_airflow.notification_core.subscription_sync import synchronize_from_cloudflare

LOGGER = logging.getLogger("zacks.notification_core.api")
app = FastAPI(
    title="Zacks Notification Core",
    version="0.7.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _authorized(authorization: str | None) -> bool:
    settings = load_settings()
    expected = settings.ingest_token
    if not expected or not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:].strip()
    return bool(token) and hmac.compare_digest(token, expected)


def _require_authorization(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _wake_worker() -> None:
    settings = load_settings()
    if not settings.redis_url:
        return
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )
        client.lpush("zacks:notification-core:wakeup", "1")
        client.ltrim("zacks:notification-core:wakeup", 0, 20)
        client.expire("zacks:notification-core:wakeup", 300)
    except Exception as exc:
        # Redis is deliberately optional. PostgreSQL polling remains authoritative.
        LOGGER.warning("notification worker wake-up unavailable: %s", type(exc).__name__)


@app.on_event("startup")
def startup() -> None:
    ensure_schema(load_settings())


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "service": "zacks-notification-core",
        "version": "0.7.0",
        **database_health(load_settings()),
    }


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    health = database_health(load_settings())
    snapshot = health.get("subscriptionSnapshot") if isinstance(health, dict) else None
    ready = bool(
        health.get("ok")
        and isinstance(snapshot, dict)
        and snapshot.get("ready") is True
    )
    if not ready:
        raise HTTPException(status_code=503, detail="subscription snapshot not ready")
    return {"ok": True, "service": "zacks-notification-core", "version": "0.7.0"}


@app.post("/api/internal/observations")
async def observations(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _require_authorization(authorization)
    try:
        payload = await request.json()
        result = ingest_observation(payload, load_settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("observation ingest failed")
        raise HTTPException(status_code=503, detail=type(exc).__name__) from exc
    if int(result.get("matchedNotifications") or 0) > 0:
        _wake_worker()
    return result


@app.post("/api/internal/subscription-sync")
def subscription_sync(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _require_authorization(authorization)
    try:
        return {"success": True, **synchronize_from_cloudflare(load_settings())}
    except Exception as exc:
        LOGGER.exception("subscription snapshot sync failed")
        raise HTTPException(status_code=503, detail=type(exc).__name__) from exc


@app.get("/api/internal/status")
def status(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _require_authorization(authorization)
    return {"success": True, **service_metrics(load_settings())}


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "wechat_airflow.notification_core.api:app",
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
