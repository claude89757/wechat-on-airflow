from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import requests

from wechat_airflow.notification_core.config import NotificationCoreSettings

ENDPOINT = "ses.tencentcloudapi.com"
SERVICE = "ses"
VERSION = "2020-10-02"


class TencentSesError(RuntimeError):
    def __init__(self, message: str, *, code: str = "unknown", definitive: bool) -> None:
        super().__init__(message)
        self.code = code
        self.definitive = definitive


@dataclass(frozen=True)
class TencentSendResult:
    message_id: str
    request_id: str | None


@dataclass(frozen=True)
class TencentDeliveryStatus:
    state: str
    provider_status: str
    delivered_at: datetime | None
    error: str | None


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _authorization(
    settings: NotificationCoreSettings,
    *,
    action: str,
    payload: str,
    timestamp: int,
) -> dict[str, str]:
    date_text = datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    content_type = "application/json"
    canonical_headers = f"content-type:{content_type}\nhost:{ENDPOINT}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join(
        ("POST", "/", "", canonical_headers, signed_headers, _sha256_hex(payload))
    )
    credential_scope = f"{date_text}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        (
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            _sha256_hex(canonical_request),
        )
    )
    secret_date = _hmac(f"TC3{settings.tencent_secret_key}".encode(), date_text)
    secret_service = _hmac(secret_date, SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={settings.tencent_secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": ENDPOINT,
        "X-TC-Action": action,
        "X-TC-Region": settings.tencent_region,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": VERSION,
    }


def _call(
    settings: NotificationCoreSettings,
    action: str,
    payload_value: Mapping[str, object],
    *,
    timeout_seconds: float = 15.0,
) -> Mapping[str, Any]:
    payload = json.dumps(payload_value, ensure_ascii=False, separators=(",", ":"))
    timestamp = int(time.time())
    try:
        response = requests.post(
            f"https://{ENDPOINT}",
            headers=_authorization(
                settings,
                action=action,
                payload=payload,
                timestamp=timestamp,
            ),
            data=payload.encode("utf-8"),
            timeout=(5.0, timeout_seconds),
        )
    except requests.RequestException as exc:
        # A network timeout may happen after the provider accepted the request.
        # The caller must not blindly replay it.
        raise TencentSesError(
            f"Tencent SES request result is uncertain: {type(exc).__name__}",
            code="network_uncertain",
            definitive=False,
        ) from exc

    try:
        root = response.json()
    except ValueError as exc:
        raise TencentSesError(
            f"Tencent SES returned non-JSON HTTP {response.status_code}",
            code=f"HTTP_{response.status_code}",
            definitive=response.status_code < 500,
        ) from exc
    provider = root.get("Response") if isinstance(root, Mapping) else None
    provider = provider if isinstance(provider, Mapping) else {}
    error = provider.get("Error")
    if isinstance(error, Mapping):
        code = str(error.get("Code") or "provider_error")
        message = str(error.get("Message") or "Tencent SES rejected the request")
        definitive = not (
            code.startswith("InternalError")
            or code.startswith("RequestLimitExceeded")
            or code.startswith("ResourceUnavailable")
        )
        raise TencentSesError(
            f"{code}: {message}"[:500],
            code=code,
            definitive=definitive,
        )
    if response.status_code >= 400 or not provider:
        raise TencentSesError(
            f"Tencent SES HTTP {response.status_code}",
            code=f"HTTP_{response.status_code}",
            definitive=response.status_code < 500,
        )
    return provider


def send_template_email(
    settings: NotificationCoreSettings,
    recipient: str,
    subject: str,
    body: str,
) -> TencentSendResult:
    if not settings.email_delivery_configured:
        raise TencentSesError(
            "Tencent SES settings are incomplete",
            code="not_configured",
            definitive=True,
        )
    response = _call(
        settings,
        "SendEmail",
        {
            "FromEmailAddress": settings.email_from_address,
            "Destination": [recipient],
            "Subject": subject,
            "Template": {
                "TemplateID": settings.email_template_id,
                "TemplateData": json.dumps(
                    {"COURT_NAME": "网球空场提醒", "FREE_TIME": body},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
            "ReplyToAddresses": settings.email_reply_to,
            "TriggerType": 1,
        },
    )
    message_id = str(response.get("MessageId") or "").strip()
    if not message_id:
        raise TencentSesError(
            "Tencent SES accepted the request without a MessageId",
            code="missing_message_id",
            definitive=False,
        )
    request_id = str(response.get("RequestId") or "").strip() or None
    return TencentSendResult(message_id=message_id, request_id=request_id)


def _request_dates(message_id: str, submitted_at: datetime) -> list[str]:
    values: list[str] = []
    marker = "-date-"
    if marker in message_id:
        suffix = message_id.split(marker, 1)[1]
        if len(suffix) >= 8 and suffix[:8].isdigit():
            values.append(f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}")
    shanghai = submitted_at.astimezone(UTC) + timedelta(hours=8)
    for offset in (0, -1, 1):
        value = (shanghai + timedelta(days=offset)).date().isoformat()
        if value not in values:
            values.append(value)
    return values


def delivery_status(
    settings: NotificationCoreSettings,
    *,
    message_id: str,
    recipient: str,
    submitted_at: datetime,
) -> TencentDeliveryStatus:
    match: Mapping[str, Any] | None = None
    for request_date in _request_dates(message_id, submitted_at):
        response = _call(
            settings,
            "GetSendEmailStatus",
            {
                "RequestDate": request_date,
                "Offset": 0,
                "Limit": 100,
                "MessageId": message_id,
            },
        )
        values = response.get("EmailStatusList")
        if isinstance(values, list):
            match = next(
                (
                    item
                    for item in values
                    if isinstance(item, Mapping)
                    and str(item.get("MessageId") or "") == message_id
                ),
                None,
            )
        if match:
            break
    if not match:
        return TencentDeliveryStatus(
            state="submitted",
            provider_status="accepted",
            delivered_at=None,
            error=None,
        )

    deliver_status = str(match.get("DeliverStatus") or "").strip()
    send_status = str(match.get("SendStatus") or "").strip()
    provider_status = f"send={send_status or 'unknown'};deliver={deliver_status or 'unknown'}"
    message = str(match.get("DeliverMessage") or "").strip() or None
    # Tencent SES uses 1 for successful delivery and non-zero failure values in
    # the status API. Keep unknown values pending rather than inventing success.
    if deliver_status == "1":
        raw_time = match.get("DeliverTime")
        delivered_at: datetime | None = None
        try:
            numeric = int(str(raw_time))
            if numeric > 0:
                delivered_at = datetime.fromtimestamp(
                    numeric / 1000 if numeric > 10_000_000_000 else numeric,
                    UTC,
                )
        except (TypeError, ValueError, OSError):
            delivered_at = None
        return TencentDeliveryStatus(
            state="delivered",
            provider_status=provider_status,
            delivered_at=delivered_at,
            error=None,
        )
    if deliver_status and deliver_status not in {"0", "null", "None"}:
        return TencentDeliveryStatus(
            state="failed",
            provider_status=provider_status,
            delivered_at=None,
            error=message or "Tencent SES reported delivery failure",
        )
    return TencentDeliveryStatus(
        state="submitted",
        provider_status=provider_status,
        delivered_at=None,
        error=message,
    )
