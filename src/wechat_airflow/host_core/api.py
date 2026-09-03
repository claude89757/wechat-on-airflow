from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .database import ensure_schema, ping, transaction
from .domain import (
    PRIORITY_TERMS,
    STANDARD_TERMS,
    VENUES,
    decrypt_invite_code,
    encrypt_invite_code,
    generate_invite_code,
    hash_invite_code,
    hash_verification_code,
    jsonable_datetime,
    mask_email,
    normalize_email,
    random_token,
    random_verification_code,
    resolve_term,
    subscription_dedupe_key,
    utc_now,
    validate_subscription,
    weekday_mask,
    weekdays_from_mask,
)
from .service import increment_subscription_generations, runtime_heartbeat
from .settings import HostCoreSettings, load_settings, load_tencent_email_settings

LOGGER = logging.getLogger("zacks.host_core.api")
API_PREFIX = "/zacks-api/api"
RECEIPT_DAYS = 180
CHALLENGE_MINUTES = 10
COFFEE_CLAIM_DELAY_SECONDS = 5
COFFEE_SESSION_MINUTES = 10

app = FastAPI(
    title="Zacks Airflow-host API",
    version="0.7.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _settings() -> HostCoreSettings:
    return load_settings()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("x-zacks-client-ip")
        or request.headers.get("cf-connecting-ip")
        or (request.client.host if request.client else "unknown")
    )[:128]


def _client_ip_hash(request: Request, settings: HostCoreSettings) -> str:
    return hashlib.sha256(f"{_client_ip(request)}:{settings.verification_pepper}".encode()).hexdigest()


def _edge_authorized(request: Request, settings: HostCoreSettings) -> bool:
    supplied = request.headers.get("x-zacks-edge-token", "")
    return bool(supplied) and hashlib.sha256(supplied.encode()).digest() == hashlib.sha256(
        settings.edge_token.encode()
    ).digest()


def _internal_authorized(request: Request, settings: HostCoreSettings) -> bool:
    authorization = request.headers.get("authorization", "")
    return authorization.startswith("Bearer ") and hashlib.sha256(
        authorization[7:].strip().encode()
    ).digest() == hashlib.sha256(settings.edge_token.encode()).digest()


@app.middleware("http")
async def protect_origin(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.url.path in {f"{API_PREFIX}/healthz", f"{API_PREFIX}/readyz"}:
        return await call_next(request)
    settings = _settings()
    if request.url.path.startswith(f"{API_PREFIX}/internal/"):
        allowed = _internal_authorized(request, settings)
    else:
        allowed = _edge_authorized(request, settings)
    if not allowed:
        return JSONResponse({"error": "未授权"}, status_code=401)
    return await call_next(request)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.on_event("startup")
def startup() -> None:
    ensure_schema()
    settings = _settings()
    runtime_heartbeat("zacks-api", settings.deployment_commit, {"version": "0.7.0"})


def _identity(request: Request, *, required: bool = False) -> dict[str, Any] | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        if required:
            raise HTTPException(status_code=401, detail="请先验证邮箱")
        return None
    token = authorization[7:].strip()
    if not token:
        if required:
            raise HTTPException(status_code=401, detail="请先验证邮箱")
        return None
    now = utc_now()
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT email, masked_email
                FROM zacks.verified_receipts
                WHERE token_hash = :token_hash
                  AND revoked_at IS NULL
                  AND expires_at > :now
                """
            ),
            {"token_hash": _hash_token(token), "now": now},
        ).mappings().first()
        if not row:
            if required:
                raise HTTPException(status_code=401, detail="邮箱凭证已失效，请重新验证")
            return None
        connection.execute(
            text(
                """
                UPDATE zacks.verified_receipts
                SET last_used_at = :now
                WHERE token_hash = :token_hash
                """
            ),
            {"now": now, "token_hash": _hash_token(token)},
        )
        connection.execute(
            text(
                """
                UPDATE zacks.user_profiles
                SET last_active_at = :now, updated_at = :now
                WHERE email = :email
                """
            ),
            {"now": now, "email": row["email"]},
        )
    return {"email": row["email"], "maskedEmail": row["masked_email"]}


def _tier(connection, email: str) -> str:  # type: ignore[no-untyped-def]
    value = connection.execute(
        text(
            """
            SELECT tier
            FROM zacks.user_delivery_tiers
            WHERE email = :email AND revoked_at IS NULL
            """
        ),
        {"email": email},
    ).scalar_one_or_none()
    return "priority" if value == "priority" else "standard"


def _is_admin(connection, email: str) -> bool:  # type: ignore[no-untyped-def]
    return bool(
        connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM zacks.user_roles
                    WHERE email = :email AND role = 'admin' AND revoked_at IS NULL
                )
                """
            ),
            {"email": email},
        ).scalar_one()
    )


def _require_admin(request: Request) -> dict[str, Any]:
    identity = _identity(request, required=True)
    assert identity is not None
    with transaction() as connection:
        if not _is_admin(connection, identity["email"]):
            raise HTTPException(status_code=403, detail="仅管理员可以执行此操作")
    return identity


@app.get(f"{API_PREFIX}/healthz")
def healthz() -> dict[str, Any]:
    settings = _settings()
    database = ping()
    return {
        "ok": True,
        "service": "zacks-tennis-alerts",
        "runtime": "airflow-host",
        "version": "0.7.0",
        "deploymentCommit": settings.deployment_commit,
        "database": {
            "schemaReady": bool(database.get("schema_ready")),
            "serverVersion": int(database.get("server_version_num") or 0),
        },
        "deliveryOwner": settings.delivery_owner,
        "observationMode": settings.observation_mode,
        "capabilities": {
            "priorityWeatherBypass": True,
            "cloudflareIndependentDelivery": True,
        },
    }


@app.get(f"{API_PREFIX}/readyz")
def readyz() -> dict[str, Any]:
    settings = _settings()
    database = ping()
    email_ready = True
    email_error = None
    if settings.host_owns_delivery:
        try:
            load_tencent_email_settings()
        except RuntimeError as exc:
            email_ready = False
            email_error = str(exc)
    ready = bool(database.get("schema_ready")) and email_ready
    return {
        "ok": ready,
        "databaseReady": bool(database.get("schema_ready")),
        "emailReady": email_ready,
        "emailError": email_error,
        "deliveryOwner": settings.delivery_owner,
    }


@app.get(f"{API_PREFIX}/bootstrap")
def bootstrap(request: Request) -> dict[str, Any]:
    settings = _settings()
    identity = _identity(request)
    now = utc_now()
    shanghai_now = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    day_start_local = shanghai_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = day_start_local.astimezone(UTC)

    with transaction() as connection:
        active_subscriptions = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM zacks.subscriptions s
                    LEFT JOIN zacks.user_delivery_tiers tiers ON tiers.email = s.email
                    WHERE s.active = true
                      AND s.active_until > :now
                      AND (
                        s.auto_renew = false
                        OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
                      )
                    """
                ),
                {"now": now},
            ).scalar_one()
        )
        reminders_today = int(
            connection.execute(
                text(
                    """
                    SELECT count(DISTINCT message_id)
                    FROM zacks.notification_outbox
                    WHERE submitted_at >= :day_start
                    """
                ),
                {"day_start": day_start},
            ).scalar_one()
        )
        venue_rows = connection.execute(
            text(
                """
                SELECT
                    status.venue_id,
                    status.venue_name,
                    status.healthy,
                    status.last_inspection_at,
                    status.last_notification_at,
                    count(DISTINCT subscriptions.email) FILTER (
                        WHERE subscriptions.active = true
                          AND subscriptions.active_until > :now
                          AND (
                            subscriptions.auto_renew = false
                            OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
                          )
                    ) AS subscriber_count
                FROM zacks.venue_status status
                LEFT JOIN zacks.subscription_venues selected
                    ON selected.venue_id = status.venue_id
                LEFT JOIN zacks.subscriptions subscriptions
                    ON subscriptions.id = selected.subscription_id
                LEFT JOIN zacks.user_delivery_tiers tiers
                    ON tiers.email = subscriptions.email
                GROUP BY status.venue_id, status.venue_name, status.healthy,
                         status.last_inspection_at, status.last_notification_at
                ORDER BY subscriber_count DESC, status.venue_name, status.venue_id
                """
            ),
            {"now": now},
        ).mappings().all()

        subscription_rows: list[dict[str, Any]] = []
        submitted_today = delivered_today = failed_today = 0
        identity_tier = "standard"
        admin = False
        if identity:
            email = identity["email"]
            identity_tier = _tier(connection, email)
            admin = _is_admin(connection, email)
            subscription_rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT id, venue_ids, start_time, end_time, weekday_mask,
                               duration_days, term_code, auto_renew, active_until,
                               active, created_at
                        FROM zacks.subscriptions
                        WHERE email = :email AND active = true AND active_until > :now
                        ORDER BY created_at DESC
                        """
                    ),
                    {"email": email, "now": now},
                ).mappings()
            ]
            counts = connection.execute(
                text(
                    """
                    SELECT
                        count(DISTINCT message_id) FILTER (
                            WHERE submitted_at >= :day_start
                        ) AS submitted,
                        count(DISTINCT message_id) FILTER (
                            WHERE status = 'delivered' AND delivered_at >= :day_start
                        ) AS delivered,
                        count(DISTINCT message_id) FILTER (
                            WHERE status = 'failed' AND failed_at >= :day_start
                        ) AS failed
                    FROM zacks.notification_outbox
                    WHERE email = :email
                    """
                ),
                {"email": email, "day_start": day_start},
            ).mappings().one()
            submitted_today = int(counts["submitted"] or 0)
            delivered_today = int(counts["delivered"] or 0)
            failed_today = int(counts["failed"] or 0)

    daily_limit = (
        settings.priority_daily_email_limit
        if identity_tier == "priority"
        else settings.standard_daily_email_limit
    )
    subscription_limit = (
        settings.priority_active_subscription_limit
        if identity_tier == "priority"
        else settings.standard_active_subscription_limit
    )
    venues = [
        {
            "id": row["venue_id"],
            "name": row["venue_name"],
            "healthy": bool(row["healthy"]),
            "subscriberCount": int(row["subscriber_count"] or 0),
            "lastInspectionAt": jsonable_datetime(row["last_inspection_at"]),
            "lastNotificationAt": jsonable_datetime(row["last_notification_at"]),
        }
        for row in venue_rows
    ]
    subscriptions = [
        {
            "id": row["id"],
            "venueIds": row["venue_ids"] if isinstance(row["venue_ids"], list) else json.loads(row["venue_ids"]),
            "startTime": row["start_time"],
            "endTime": row["end_time"],
            "weekdays": weekdays_from_mask(row["weekday_mask"]),
            "durationDays": int(row["duration_days"]),
            "termCode": row["term_code"],
            "autoRenew": bool(row["auto_renew"]),
            "eligible": not bool(row["auto_renew"]) or identity_tier == "priority",
            "activeUntil": jsonable_datetime(row["active_until"]),
            "active": bool(row["active"]),
            "createdAt": jsonable_datetime(row["created_at"]),
        }
        for row in subscription_rows
    ]
    return {
        "generatedAt": now.isoformat(),
        "dataStatus": {
            "stale": False,
            "source": "live",
            "reason": None,
            "retryAt": None,
        },
        "weatherEmailGate": {
            "suppressed": False,
            "precipitationMm": None,
            "thresholdMm": settings.weather_threshold_mm,
        },
        "metrics": {
            "activeSubscriptions": active_subscriptions,
            "remindersToday": reminders_today,
            "healthyVenues": sum(1 for venue in venues if venue["healthy"]),
            "totalVenues": len(venues),
        },
        "deliveryTiers": {
            "standard": settings.standard_daily_email_limit,
            "priority": settings.priority_daily_email_limit,
        },
        "subscriptionTerms": {
            "standard": list(STANDARD_TERMS),
            "priority": list(PRIORITY_TERMS),
        },
        "subscriptionLimits": {
            "standard": settings.standard_active_subscription_limit,
            "priority": settings.priority_active_subscription_limit,
        },
        "venues": venues,
        "identity": {
            "verified": bool(identity),
            "maskedEmail": identity["maskedEmail"] if identity else None,
            "remindersToday": submitted_today,
            "submittedToday": submitted_today,
            "deliveredToday": delivered_today,
            "failedToday": failed_today,
            "tier": identity_tier,
            "isAdmin": admin,
            "dailyLimit": daily_limit,
            "remainingToday": max(0, daily_limit - submitted_today),
            "activeSubscriptionLimit": subscription_limit,
            "activeSubscriptionCount": len(subscriptions),
            "remainingSubscriptions": max(0, subscription_limit - len(subscriptions)),
        },
        "subscriptions": subscriptions,
    }


@app.post(f"{API_PREFIX}/email/send-code")
def send_verification_code(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    settings = _settings()
    email = normalize_email(payload.get("email"))
    now = utc_now()
    since = now - timedelta(hours=1)
    ip_hash = _client_ip_hash(request, settings)
    challenge_id = str(uuid.uuid4())
    code = random_verification_code()
    expires_at = now + timedelta(minutes=CHALLENGE_MINUTES)
    with transaction() as connection:
        email_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM zacks.verification_challenges
                    WHERE email = :email AND created_at >= :since
                    """
                ),
                {"email": email, "since": since},
            ).scalar_one()
        )
        ip_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM zacks.verification_challenges
                    WHERE ip_hash = :ip_hash AND created_at >= :since
                    """
                ),
                {"ip_hash": ip_hash, "since": since},
            ).scalar_one()
        )
        if email_count >= 3 or ip_count >= 20:
            raise HTTPException(status_code=429, detail="验证码发送过于频繁，请稍后再试")
        connection.execute(
            text(
                """
                INSERT INTO zacks.verification_challenges(
                    id, email, code_hash, ip_hash, expires_at, attempts, created_at
                )
                VALUES (
                    :id, :email, :code_hash, :ip_hash, :expires_at, 0, :created_at
                )
                """
            ),
            {
                "id": challenge_id,
                "email": email,
                "code_hash": hash_verification_code(challenge_id, code, settings.verification_pepper),
                "ip_hash": ip_hash,
                "expires_at": expires_at,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.system_email_outbox(
                    id, dedupe_key, email, email_type, subject, body, status,
                    attempt_count, next_attempt_at, created_at, updated_at
                )
                VALUES (
                    :id, :dedupe_key, :email, 'verification', :subject, :body,
                    'pending', 0, :now, :now, :now
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "dedupe_key": f"verification:{challenge_id}",
                "email": email,
                "subject": "Zacks 网球提醒验证码",
                "body": f"你的验证码是 {code}，{CHALLENGE_MINUTES} 分钟内有效。",
                "now": now,
            },
        )
    return {"challengeId": challenge_id, "expiresAt": expires_at.isoformat()}


@app.post(f"{API_PREFIX}/email/verify")
def verify_email(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    settings = _settings()
    challenge_id = str(payload.get("challengeId") or "").strip()
    code = str(payload.get("code") or "").strip()
    if not challenge_id or not code:
        raise ValueError("请输入验证码")
    now = utc_now()
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT email, code_hash, attempts
                FROM zacks.verification_challenges
                WHERE id = :id
                  AND consumed_at IS NULL
                  AND expires_at > :now
                FOR UPDATE
                """
            ),
            {"id": challenge_id, "now": now},
        ).mappings().first()
        if not row or int(row["attempts"] or 0) >= 5:
            raise HTTPException(status_code=400, detail="验证码无效或已过期")
        expected = hash_verification_code(challenge_id, code, settings.verification_pepper)
        if not __import__("hmac").compare_digest(expected, str(row["code_hash"])):
            connection.execute(
                text(
                    """
                    UPDATE zacks.verification_challenges
                    SET attempts = attempts + 1 WHERE id = :id
                    """
                ),
                {"id": challenge_id},
            )
            raise HTTPException(status_code=400, detail="验证码错误")
        email = str(row["email"])
        token = random_token()
        masked = mask_email(email)
        expires_at = now + timedelta(days=RECEIPT_DAYS)
        connection.execute(
            text(
                """
                UPDATE zacks.verification_challenges
                SET consumed_at = :now WHERE id = :id
                """
            ),
            {"now": now, "id": challenge_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.verified_receipts(
                    token_hash, email, masked_email, expires_at, last_used_at, created_at
                )
                VALUES (
                    :token_hash, :email, :masked_email, :expires_at, :now, :now
                )
                """
            ),
            {
                "token_hash": _hash_token(token),
                "email": email,
                "masked_email": masked,
                "expires_at": expires_at,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_profiles(
                    email, masked_email, first_verified_at, last_verified_at,
                    last_login_at, last_active_at, created_at, updated_at
                )
                VALUES (
                    :email, :masked_email, :now, :now, :now, :now, :now, :now
                )
                ON CONFLICT (email) DO UPDATE SET
                    masked_email = EXCLUDED.masked_email,
                    last_verified_at = EXCLUDED.last_verified_at,
                    last_login_at = EXCLUDED.last_login_at,
                    last_active_at = EXCLUDED.last_active_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {"email": email, "masked_email": masked, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_delivery_tiers(
                    email, tier, created_at, updated_at
                )
                VALUES (:email, 'standard', :now, :now)
                ON CONFLICT (email) DO NOTHING
                """
            ),
            {"email": email, "now": now},
        )
    return {
        "token": token,
        "email": email,
        "maskedEmail": masked,
        "verifiedAt": now.isoformat(),
        "expiresAt": expires_at.isoformat(),
    }


@app.post(f"{API_PREFIX}/subscriptions")
def create_subscription(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> JSONResponse:
    identity = _identity(request, required=True)
    assert identity is not None
    settings = _settings()
    now = utc_now()
    with transaction() as connection:
        tier = _tier(connection, identity["email"])
        candidate = validate_subscription(payload, priority=tier == "priority")
        limit = (
            settings.priority_active_subscription_limit
            if tier == "priority"
            else settings.standard_active_subscription_limit
        )
        active_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM zacks.subscriptions
                    WHERE email = :email AND active = true AND active_until > :now
                    """
                ),
                {"email": identity["email"], "now": now},
            ).scalar_one()
        )
        if active_count >= limit:
            raise HTTPException(status_code=409, detail="已达到有效订阅数量上限")
        mask = weekday_mask(candidate.weekdays)
        dedupe_key = subscription_dedupe_key(
            identity["email"],
            candidate.venue_ids,
            candidate.start_time,
            candidate.end_time,
            mask,
        )
        existing = connection.execute(
            text(
                """
                SELECT id FROM zacks.subscriptions
                WHERE email = :email AND dedupe_key = :dedupe_key
                  AND active = true AND active_until > :now
                """
            ),
            {"email": identity["email"], "dedupe_key": dedupe_key, "now": now},
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="相同订阅已经存在")
        term = resolve_term(candidate.term_code, now)
        subscription_id = str(uuid.uuid4())
        connection.execute(
            text(
                """
                INSERT INTO zacks.subscriptions(
                    id, email, venue_ids, start_time, end_time, weekday_mask,
                    duration_days, term_code, auto_renew, dedupe_key,
                    active_until, active, created_at, updated_at
                )
                VALUES (
                    :id, :email, CAST(:venue_ids AS jsonb), :start_time, :end_time,
                    :weekday_mask, :duration_days, :term_code, :auto_renew,
                    :dedupe_key, :active_until, true, :now, :now
                )
                """
            ),
            {
                "id": subscription_id,
                "email": identity["email"],
                "venue_ids": json.dumps(candidate.venue_ids),
                "start_time": candidate.start_time,
                "end_time": candidate.end_time,
                "weekday_mask": mask,
                "duration_days": term.duration_days,
                "term_code": term.term_code,
                "auto_renew": term.auto_renew,
                "dedupe_key": dedupe_key,
                "active_until": term.active_until,
                "now": now,
            },
        )
        for venue_id in candidate.venue_ids:
            connection.execute(
                text(
                    """
                    INSERT INTO zacks.subscription_venues(subscription_id, venue_id)
                    VALUES (:subscription_id, :venue_id)
                    """
                ),
                {"subscription_id": subscription_id, "venue_id": venue_id},
            )
        increment_subscription_generations(connection, list(candidate.venue_ids))
    return JSONResponse(
        {
            "id": subscription_id,
            "venueIds": list(candidate.venue_ids),
            "startTime": candidate.start_time,
            "endTime": candidate.end_time,
            "weekdays": list(candidate.weekdays),
            "durationDays": term.duration_days,
            "termCode": term.term_code,
            "autoRenew": term.auto_renew,
            "eligible": True,
            "activeUntil": term.active_until.isoformat(),
            "active": True,
            "createdAt": now.isoformat(),
        },
        status_code=201,
    )


@app.delete(f"{API_PREFIX}/subscriptions/{{subscription_id}}")
def cancel_subscription(subscription_id: str, request: Request) -> dict[str, Any]:
    identity = _identity(request, required=True)
    assert identity is not None
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT venue_ids FROM zacks.subscriptions
                WHERE id = :id AND email = :email AND active = true
                FOR UPDATE
                """
            ),
            {"id": subscription_id, "email": identity["email"]},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="订阅不存在")
        venue_ids = row["venue_ids"] if isinstance(row["venue_ids"], list) else json.loads(row["venue_ids"])
        connection.execute(
            text(
                """
                UPDATE zacks.subscriptions
                SET active = false, updated_at = now()
                WHERE id = :id AND email = :email
                """
            ),
            {"id": subscription_id, "email": identity["email"]},
        )
        increment_subscription_generations(connection, list(venue_ids))
    return {"success": True}


@app.post(f"{API_PREFIX}/priority/redeem")
def redeem_priority(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    identity = _identity(request, required=True)
    assert identity is not None
    settings = _settings()
    now = utc_now()
    code_hash = hash_invite_code(payload.get("code"), settings.invite_pepper)
    ip_hash = _client_ip_hash(request, settings)
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT id FROM zacks.priority_invite_codes
                WHERE code_hash = :code_hash
                  AND active = true
                  AND redeemed_at IS NULL
                  AND deleted_at IS NULL
                  AND expires_at > :now
                FOR UPDATE
                """
            ),
            {"code_hash": code_hash, "now": now},
        ).mappings().first()
        success = bool(row)
        connection.execute(
            text(
                """
                INSERT INTO zacks.priority_invite_attempts(
                    id, email, ip_hash, success, created_at
                ) VALUES (:id, :email, :ip_hash, :success, :created_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "email": identity["email"],
                "ip_hash": ip_hash,
                "success": success,
                "created_at": now,
            },
        )
        if not row:
            raise HTTPException(status_code=400, detail="邀请码无效、已过期或已被使用")
        connection.execute(
            text(
                """
                UPDATE zacks.priority_invite_codes
                SET redeemed_by = :email, redeemed_at = :now, updated_at = :now
                WHERE id = :id
                """
            ),
            {"email": identity["email"], "now": now, "id": row["id"]},
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_delivery_tiers(
                    email, tier, source_invite_id, created_at, updated_at, revoked_at
                )
                VALUES (:email, 'priority', :invite_id, :now, :now, NULL)
                ON CONFLICT (email) DO UPDATE SET
                    tier = 'priority', source_invite_id = EXCLUDED.source_invite_id,
                    updated_at = EXCLUDED.updated_at, revoked_at = NULL
                """
            ),
            {"email": identity["email"], "invite_id": row["id"], "now": now},
        )
    return {
        "success": True,
        "tier": "priority",
        "dailyLimit": settings.priority_daily_email_limit,
    }


@app.post(f"{API_PREFIX}/coffee/session")
def coffee_session(request: Request) -> dict[str, Any]:
    identity = _identity(request, required=True)
    assert identity is not None
    settings = _settings()
    now = utc_now()
    ip_hash = _client_ip_hash(request, settings)
    session_id = str(uuid.uuid4())
    claim_token = random_token(24)
    claimable_at = now + timedelta(seconds=COFFEE_CLAIM_DELAY_SECONDS)
    expires_at = now + timedelta(minutes=COFFEE_SESSION_MINUTES)
    with transaction() as connection:
        claimed = bool(
            connection.execute(
                text("SELECT 1 FROM zacks.coffee_invite_claims WHERE email = :email"),
                {"email": identity["email"]},
            ).scalar_one_or_none()
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.coffee_invite_sessions(
                    id, email, ip_hash, shown_at, claimable_at, expires_at, created_at
                ) VALUES (
                    :id, :email, :ip_hash, :shown_at, :claimable_at, :expires_at, :created_at
                )
                """
            ),
            {
                "id": f"{session_id}:{_hash_token(claim_token)}",
                "email": identity["email"],
                "ip_hash": ip_hash,
                "shown_at": now,
                "claimable_at": claimable_at,
                "expires_at": expires_at,
                "created_at": now,
            },
        )
    return {
        "claimToken": f"{session_id}.{claim_token}",
        "availableAt": claimable_at.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "alreadyClaimed": claimed,
    }


@app.post(f"{API_PREFIX}/coffee/invite")
def coffee_invite(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    identity = _identity(request, required=True)
    assert identity is not None
    settings = _settings()
    raw_token = str(payload.get("claimToken") or "")
    session_id, separator, secret = raw_token.partition(".")
    if not separator:
        raise HTTPException(status_code=400, detail="彩蛋会话无效")
    now = utc_now()
    session_key = f"{session_id}:{_hash_token(secret)}"
    with transaction() as connection:
        existing = connection.execute(
            text(
                """
                SELECT invites.encrypted_code, invites.expires_at, claims.claimed_at
                FROM zacks.coffee_invite_claims claims
                JOIN zacks.priority_invite_codes invites ON invites.id = claims.invite_id
                WHERE claims.email = :email
                """
            ),
            {"email": identity["email"]},
        ).mappings().first()
        if existing:
            code = decrypt_invite_code(existing["encrypted_code"], settings.invite_pepper)
            if not code:
                raise HTTPException(status_code=503, detail="彩蛋邀请码暂时无法读取")
            return {
                "code": code,
                "expiresAt": jsonable_datetime(existing["expires_at"]),
                "claimedAt": jsonable_datetime(existing["claimed_at"]),
                "reused": True,
                "status": "available",
            }
        session = connection.execute(
            text(
                """
                SELECT id, ip_hash, claimable_at, expires_at, consumed_at
                FROM zacks.coffee_invite_sessions
                WHERE id = :id AND email = :email
                FOR UPDATE
                """
            ),
            {"id": session_key, "email": identity["email"]},
        ).mappings().first()
        if not session or session["consumed_at"] or session["expires_at"] <= now:
            raise HTTPException(status_code=400, detail="彩蛋会话无效或已过期")
        if session["claimable_at"] > now:
            raise HTTPException(status_code=425, detail="请稍候再领取")
        code = generate_invite_code()
        invite_id = str(uuid.uuid4())
        expires_at = now + timedelta(days=30)
        connection.execute(
            text(
                """
                INSERT INTO zacks.priority_invite_codes(
                    id, code_hash, encrypted_code, code_hint, expires_at, active,
                    note, created_at, updated_at
                ) VALUES (
                    :id, :code_hash, :encrypted_code, :code_hint, :expires_at,
                    true, 'coffee-support', :now, :now
                )
                """
            ),
            {
                "id": invite_id,
                "code_hash": hash_invite_code(code, settings.invite_pepper),
                "encrypted_code": encrypt_invite_code(code, settings.invite_pepper),
                "code_hint": "-".join(code.split("-")[:3]),
                "expires_at": expires_at,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.coffee_invite_claims(
                    email, session_id, invite_id, ip_hash, claimed_at
                ) VALUES (:email, :session_id, :invite_id, :ip_hash, :claimed_at)
                """
            ),
            {
                "email": identity["email"],
                "session_id": session_key,
                "invite_id": invite_id,
                "ip_hash": session["ip_hash"],
                "claimed_at": now,
            },
        )
        connection.execute(
            text("UPDATE zacks.coffee_invite_sessions SET consumed_at = :now WHERE id = :id"),
            {"now": now, "id": session_key},
        )
    return {
        "code": code,
        "expiresAt": expires_at.isoformat(),
        "claimedAt": now.isoformat(),
        "reused": False,
        "status": "available",
    }


@app.get(f"{API_PREFIX}/community/users")
def community_users(request: Request) -> dict[str, Any]:
    _identity(request, required=True)
    with transaction() as connection:
        rows = connection.execute(
            text(
                """
                SELECT p.email, p.last_active_at,
                       CASE WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
                            THEN 'priority' ELSE 'standard' END AS tier,
                       count(DISTINCT subscriptions.id) FILTER (
                           WHERE subscriptions.active = true
                             AND subscriptions.active_until > now()
                       ) AS active_subscriptions,
                       count(DISTINCT outbox.message_id) FILTER (
                           WHERE outbox.status = 'delivered'
                       ) AS delivered_total
                FROM zacks.user_profiles p
                LEFT JOIN zacks.user_delivery_tiers tiers ON tiers.email = p.email
                LEFT JOIN zacks.subscriptions subscriptions ON subscriptions.email = p.email
                LEFT JOIN zacks.notification_outbox outbox ON outbox.email = p.email
                GROUP BY p.email, p.last_active_at, tiers.tier, tiers.revoked_at
                ORDER BY p.last_active_at DESC
                LIMIT 100
                """
            )
        ).mappings().all()
    now = utc_now()
    users = []
    for row in rows:
        age = now - row["last_active_at"]
        activity = "今天" if age < timedelta(days=1) else "本周" if age < timedelta(days=7) else "较早"
        delivered = int(row["delivered_total"] or 0)
        volume = "0" if delivered == 0 else "1-9" if delivered < 10 else "10-99" if delivered < 100 else "100+"
        users.append(
            {
                "email": mask_email(row["email"]),
                "tier": row["tier"],
                "activity": activity,
                "activeSubscriptions": int(row["active_subscriptions"] or 0),
                "deliveredVolume": volume,
            }
        )
    return {"generatedAt": now.isoformat(), "users": users}


@app.get(f"{API_PREFIX}/admin/users")
def admin_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    with transaction() as connection:
        rows = connection.execute(
            text(
                """
                SELECT p.*,
                       CASE WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
                            THEN 'priority' ELSE 'standard' END AS tier,
                       EXISTS (
                           SELECT 1 FROM zacks.user_roles roles
                           WHERE roles.email = p.email AND roles.role = 'admin'
                             AND roles.revoked_at IS NULL
                       ) AS is_admin,
                       count(DISTINCT subscriptions.id) FILTER (
                           WHERE subscriptions.active = true
                             AND subscriptions.active_until > now()
                       ) AS active_subscriptions,
                       count(DISTINCT outbox.message_id) FILTER (
                           WHERE outbox.status = 'delivered'
                       ) AS delivered_all_time
                FROM zacks.user_profiles p
                LEFT JOIN zacks.user_delivery_tiers tiers ON tiers.email = p.email
                LEFT JOIN zacks.subscriptions subscriptions ON subscriptions.email = p.email
                LEFT JOIN zacks.notification_outbox outbox ON outbox.email = p.email
                GROUP BY p.email, tiers.tier, tiers.revoked_at
                ORDER BY p.last_active_at DESC
                LIMIT 250
                """
            )
        ).mappings().all()
    return {
        "generatedAt": utc_now().isoformat(),
        "users": [
            {
                "email": row["email"],
                "maskedEmail": row["masked_email"],
                "tier": row["tier"],
                "isAdmin": bool(row["is_admin"]),
                "firstVerifiedAt": jsonable_datetime(row["first_verified_at"]),
                "lastVerifiedAt": jsonable_datetime(row["last_verified_at"]),
                "lastLoginAt": jsonable_datetime(row["last_login_at"]),
                "lastActiveAt": jsonable_datetime(row["last_active_at"]),
                "activeSubscriptions": int(row["active_subscriptions"] or 0),
                "submittedToday": 0,
                "deliveredToday": 0,
                "failedToday": 0,
                "deliveredAllTime": int(row["delivered_all_time"] or 0),
            }
            for row in rows
        ],
    }


@app.api_route(f"{API_PREFIX}/admin/invites", methods=["GET", "POST"])
def admin_invites(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse | dict[str, Any]:
    _require_admin(request)
    settings = _settings()
    if request.method == "POST":
        candidate = payload or {}
        count = min(max(int(candidate.get("count") or 1), 1), 20)
        days = min(max(int(candidate.get("expiresInDays") or 90), 1), 365)
        note = str(candidate.get("note") or "")[:120] or None
        now = utc_now()
        invites = []
        with transaction() as connection:
            for _ in range(count):
                code = generate_invite_code()
                invite_id = str(uuid.uuid4())
                expires_at = now + timedelta(days=days)
                connection.execute(
                    text(
                        """
                        INSERT INTO zacks.priority_invite_codes(
                            id, code_hash, encrypted_code, code_hint, expires_at,
                            active, note, created_at, updated_at
                        ) VALUES (
                            :id, :code_hash, :encrypted_code, :code_hint, :expires_at,
                            true, :note, :now, :now
                        )
                        """
                    ),
                    {
                        "id": invite_id,
                        "code_hash": hash_invite_code(code, settings.invite_pepper),
                        "encrypted_code": encrypt_invite_code(code, settings.invite_pepper),
                        "code_hint": "-".join(code.split("-")[:3]),
                        "expires_at": expires_at,
                        "note": note,
                        "now": now,
                    },
                )
                invites.append(
                    {
                        "id": invite_id,
                        "code": code,
                        "codeHint": "-".join(code.split("-")[:3]),
                        "recoverable": True,
                        "active": True,
                        "status": "available",
                        "note": note,
                        "createdAt": now.isoformat(),
                        "expiresAt": expires_at.isoformat(),
                        "redeemedBy": None,
                        "redeemedAt": None,
                    }
                )
        return JSONResponse({"invites": invites}, status_code=201)

    with transaction() as connection:
        rows = connection.execute(
            text(
                """
                SELECT * FROM zacks.priority_invite_codes
                ORDER BY created_at DESC LIMIT 250
                """
            )
        ).mappings().all()
    now = utc_now()
    invites = []
    for row in rows:
        code = decrypt_invite_code(row["encrypted_code"], settings.invite_pepper)
        status = (
            "deleted" if row["deleted_at"] else
            "redeemed" if row["redeemed_at"] else
            "expired" if row["expires_at"] <= now else
            "available" if row["active"] else "disabled"
        )
        invites.append(
            {
                "id": row["id"],
                "code": code,
                "codeHint": row["code_hint"],
                "recoverable": bool(code),
                "active": bool(row["active"]),
                "status": status,
                "note": row["note"],
                "createdAt": jsonable_datetime(row["created_at"]),
                "expiresAt": jsonable_datetime(row["expires_at"]),
                "redeemedBy": row["redeemed_by"],
                "redeemedAt": jsonable_datetime(row["redeemed_at"]),
            }
        )
    return {"generatedAt": now.isoformat(), "invites": invites}


@app.patch(f"{API_PREFIX}/admin/invites/{{invite_id}}")
def update_invite(
    invite_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_admin(request)
    now = utc_now()
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT active, note, expires_at, redeemed_at, deleted_at
                FROM zacks.priority_invite_codes WHERE id = :id FOR UPDATE
                """
            ),
            {"id": invite_id},
        ).mappings().first()
        if not row or row["deleted_at"]:
            raise HTTPException(status_code=404, detail="邀请码不存在")
        if row["redeemed_at"]:
            raise HTTPException(status_code=409, detail="已兑换的邀请码不能修改")
        active = bool(payload.get("active")) if "active" in payload else bool(row["active"])
        note = str(payload.get("note"))[:120] if "note" in payload else row["note"]
        expires_at = (
            now + timedelta(days=min(max(int(payload["expiresInDays"]), 1), 365))
            if "expiresInDays" in payload
            else row["expires_at"]
        )
        connection.execute(
            text(
                """
                UPDATE zacks.priority_invite_codes
                SET active = :active, note = :note, expires_at = :expires_at,
                    updated_at = :now
                WHERE id = :id
                """
            ),
            {
                "active": active,
                "note": note,
                "expires_at": expires_at,
                "now": now,
                "id": invite_id,
            },
        )
    return {"success": True}


@app.delete(f"{API_PREFIX}/admin/invites/{{invite_id}}")
def delete_invite(invite_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    with transaction() as connection:
        result = connection.execute(
            text(
                """
                UPDATE zacks.priority_invite_codes
                SET active = false, deleted_at = now(), updated_at = now()
                WHERE id = :id AND redeemed_at IS NULL AND deleted_at IS NULL
                """
            ),
            {"id": invite_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="邀请码不存在或不能删除")
    return {"success": True}


@app.post(f"{API_PREFIX}/internal/observations")
def internal_observation(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .service import ingest_observation

    return ingest_observation(payload)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "wechat_airflow.host_core.api:app",
        host=os.environ.get("ZACKS_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("ZACKS_API_PORT", "8090")),
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.environ.get("ZACKS_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
