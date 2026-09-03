from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .settings import TencentEmailSettings

ENDPOINT = "ses.tencentcloudapi.com"
SERVICE = "ses"
VERSION = "2020-10-02"


class TencentSesError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.provider_message = message


@dataclass(frozen=True)
class SendResult:
    message_id: str | None
    request_id: str | None


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


def _call(
    settings: TencentEmailSettings,
    action: str,
    payload_value: dict[str, Any],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    timestamp = int(time.time())
    request_date = datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    payload = json.dumps(payload_value, ensure_ascii=False, separators=(",", ":"))
    content_type = "application/json"
    canonical_headers = f"content-type:{content_type}\nhost:{ENDPOINT}\n"
    signed_headers = "content-type;host"
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, _sha256_hex(payload)]
    )
    credential_scope = f"{request_date}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            _sha256_hex(canonical_request),
        ]
    )
    secret_date = _hmac(f"TC3{settings.secret_key}".encode(), request_date)
    secret_service = _hmac(secret_date, SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = ", ".join(
        [
            f"TC3-HMAC-SHA256 Credential={settings.secret_id}/{credential_scope}",
            f"SignedHeaders={signed_headers}",
            f"Signature={signature}",
        ]
    )
    response = requests.post(
        f"https://{ENDPOINT}",
        headers={
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": ENDPOINT,
            "X-TC-Action": action,
            "X-TC-Region": settings.region,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": VERSION,
        },
        data=payload.encode(),
        timeout=timeout,
    )
    try:
        document = response.json()
    except ValueError as exc:
        raise TencentSesError(
            f"HTTP_{response.status_code}", "腾讯云邮件接口返回非 JSON 数据"
        ) from exc
    provider = document.get("Response") if isinstance(document, dict) else None
    if not isinstance(provider, dict):
        raise TencentSesError(f"HTTP_{response.status_code}", "腾讯云邮件接口响应无效")
    error = provider.get("Error")
    if response.status_code >= 400 or isinstance(error, dict):
        code = str(error.get("Code") if isinstance(error, dict) else f"HTTP_{response.status_code}")
        message = str(error.get("Message") if isinstance(error, dict) else "腾讯云邮件接口调用失败")
        raise TencentSesError(code, message)
    return provider


def send_template_email(
    settings: TencentEmailSettings,
    recipient: str,
    subject: str,
    body: str,
    *,
    category: str,
) -> SendResult:
    response = _call(
        settings,
        "SendEmail",
        {
            "FromEmailAddress": settings.from_address,
            "Destination": [recipient],
            "Subject": subject,
            "Template": {
                "TemplateID": settings.template_id,
                "TemplateData": json.dumps(
                    {"COURT_NAME": category, "FREE_TIME": body},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
            "ReplyToAddresses": settings.reply_to,
            "TriggerType": 1,
        },
    )
    return SendResult(
        message_id=str(response.get("MessageId")) if response.get("MessageId") else None,
        request_id=str(response.get("RequestId")) if response.get("RequestId") else None,
    )


def _status_dates(message_id: str, now: datetime | None = None) -> list[str]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    dates: list[str] = []
    match = __import__("re").search(r"(?:^|-)date-(\d{4})(\d{2})(\d{2})\d{6}(?:-|$)", message_id)
    if match:
        dates.append(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")
    shanghai = current + timedelta(hours=8)
    for offset in (0, -1, -2):
        candidate = (shanghai + timedelta(days=offset)).date().isoformat()
        if candidate not in dates:
            dates.append(candidate)
    return dates


def get_email_status(
    settings: TencentEmailSettings,
    message_id: str,
    recipient: str | None = None,
) -> dict[str, Any] | None:
    for request_date in _status_dates(message_id):
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
        rows = response.get("EmailStatusList")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("MessageId") == message_id:
                    return row
    if recipient:
        for request_date in _status_dates(message_id):
            response = _call(
                settings,
                "GetSendEmailStatus",
                {
                    "RequestDate": request_date,
                    "Offset": 0,
                    "Limit": 100,
                    "ToEmailAddress": recipient,
                },
            )
            rows = response.get("EmailStatusList")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and row.get("MessageId") == message_id:
                        return row
    return None


def normalize_status(value: dict[str, Any] | None) -> tuple[str, str | None, datetime | None]:
    if not value:
        return "pending", None, None
    deliver_status = str(value.get("DeliverStatus") or "").strip().lower()
    send_status = str(value.get("SendStatus") or "").strip().lower()
    message = str(value.get("DeliverMessage") or "").strip()[:500] or None
    delivered_at: datetime | None = None
    raw_time = value.get("DeliverTime")
    if raw_time:
        try:
            numeric = int(str(raw_time))
            if numeric > 10_000_000_000:
                numeric //= 1_000
            delivered_at = datetime.fromtimestamp(numeric, UTC)
        except (TypeError, ValueError, OSError):
            delivered_at = None
    if deliver_status in {"1", "success", "delivered"}:
        return "delivered", message, delivered_at or datetime.now(UTC)
    if deliver_status in {"2", "3", "failed", "bounce", "rejected"}:
        return "failed", message or "provider delivery failed", delivered_at
    if send_status in {"2", "3", "failed", "rejected"}:
        return "failed", message or "provider send failed", delivered_at
    return "pending", message, delivered_at
