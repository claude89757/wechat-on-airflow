#!/usr/bin/env python3

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

JsonDict = dict[str, Any]
Notification = dict[str, str]

EMAIL_SEND_FALLBACK_OUTBOX_VAR = "EMAIL_SEND_FALLBACK_OUTBOX"
EMAIL_SEND_FALLBACK_MAX_ITEMS_VAR = "EMAIL_SEND_FALLBACK_MAX_ITEMS"
EMAIL_TEMPLATE_ID_VAR = "VENUE_EMAIL_TEMPLATE_ID"
EMAIL_FROM_ADDRESS_VAR = "VENUE_EMAIL_FROM_ADDRESS"
EMAIL_REPLY_TO_VAR = "VENUE_EMAIL_REPLY_TO"
DEFAULT_EMAIL_TEMPLATE_ID = 33340
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")


def send_template_email(**kwargs: Any) -> JsonDict:
    from wechat_airflow.clients.tencent_ses import send_template_email as send

    return cast(JsonDict, send(**kwargs))


def _get_variable(
    key: str,
    default_var: Any = None,
    deserialize_json: bool = False,
) -> Any:
    from airflow.sdk import Variable

    return Variable.get(key, default_var=default_var, deserialize_json=deserialize_json)


def _set_variable(key: str, value: Any, serialize_json: bool = False) -> None:
    from airflow.sdk import Variable

    Variable.set(key, value, serialize_json=serialize_json)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> date:
    return datetime.now().date()


def _get_int_variable(key: str, default: int) -> int:
    value = _get_variable(key, default_var=str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_email_template_id() -> int:
    template_id = _get_int_variable(EMAIL_TEMPLATE_ID_VAR, DEFAULT_EMAIL_TEMPLATE_ID)
    if template_id <= 0:
        raise ValueError(f"Airflow Variable {EMAIL_TEMPLATE_ID_VAR} must be a positive integer")
    return template_id


def _get_required_string_variable(key: str) -> str:
    value = str(_get_variable(key, default_var="")).strip()
    if not value:
        raise ValueError(f"Airflow Variable {key} is required")
    return value


def _normalize_recipients(value: object, recipients_var: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Airflow Variable {recipients_var} must be a JSON list")

    recipients: list[str] = []
    seen: set[str] = set()
    invalid_count = 0
    for item in value:
        recipient = str(item).strip()
        normalized = recipient.lower()
        if not recipient:
            continue
        if not EMAIL_PATTERN.match(recipient):
            invalid_count += 1
            continue
        if normalized not in seen:
            recipients.append(recipient)
            seen.add(normalized)

    if invalid_count:
        raise ValueError(
            f"Airflow Variable {recipients_var} contains {invalid_count} invalid email entries"
        )
    if not recipients:
        raise ValueError(f"Airflow Variable {recipients_var} must contain recipients")
    return recipients


def _normalize_notifications(notifications: Iterable[object]) -> list[Notification]:
    normalized: list[Notification] = []
    for notification in notifications or []:
        if not isinstance(notification, dict):
            continue
        item = {
            "date": str(notification.get("date") or "").strip(),
            "court_name": str(notification.get("court_name") or "").strip(),
            "start_time": str(notification.get("start_time") or "").strip(),
            "end_time": str(notification.get("end_time") or "").strip(),
        }
        if all(item.values()):
            normalized.append(item)
    return normalized


def _parse_notification_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        pass

    reference_date = _today()
    candidates = []
    for year in (reference_date.year - 1, reference_date.year, reference_date.year + 1):
        try:
            candidates.append(datetime.strptime(f"{year}-{value}", "%Y-%m-%d").date())
        except ValueError:
            continue
    if not candidates:
        raise ValueError(f"invalid notification date: {value}")
    return min(candidates, key=lambda candidate: abs((candidate - reference_date).days))


def _format_notification(notification: Notification) -> str:
    notification_date = _parse_notification_date(notification["date"])
    weekday = WEEKDAY_NAMES[notification_date.weekday()]
    display_date = notification_date.strftime("%m-%d")
    return (
        f"{notification['court_name']} {display_date} 星期{weekday} "
        f"{notification['start_time']}-{notification['end_time']}"
    )


def _record_failed_batch(
    source: str,
    notifications: list[Notification],
    recipients_var: str,
    error: str,
) -> JsonDict:
    now = _utc_now()
    canonical_payload = json.dumps(notifications, ensure_ascii=False, sort_keys=True)
    failure_id = hashlib.sha256(
        f"{source}\0{recipients_var}\0{canonical_payload}".encode()
    ).hexdigest()
    outbox = _get_variable(
        EMAIL_SEND_FALLBACK_OUTBOX_VAR,
        default_var=[],
        deserialize_json=True,
    )
    if not isinstance(outbox, list):
        outbox = []

    entry: JsonDict = {
        "id": failure_id,
        "source": source,
        "recipients_var": recipients_var,
        "notifications": notifications,
        "notification_count": len(notifications),
        "error": str(error)[:1000],
        "first_failed_at": now,
        "last_failed_at": now,
        "attempt_count": 1,
    }
    for index, existing in enumerate(outbox):
        if isinstance(existing, dict) and existing.get("id") == failure_id:
            entry["first_failed_at"] = existing.get("first_failed_at") or now
            entry["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            outbox[index] = entry
            break
    else:
        outbox.append(entry)

    max_items = max(_get_int_variable(EMAIL_SEND_FALLBACK_MAX_ITEMS_VAR, 200), 1)
    _set_variable(
        EMAIL_SEND_FALLBACK_OUTBOX_VAR,
        outbox[-max_items:],
        serialize_json=True,
    )
    return entry


def _record_failure_safely(
    source: str,
    notifications: list[Notification],
    recipients_var: str,
    error: str,
) -> bool:
    try:
        _record_failed_batch(source, notifications, recipients_var, error)
        return True
    except Exception as fallback_exc:
        print(f"[VENUE_EMAIL] fallback persistence failed source={source}, error={fallback_exc}")
        return False


def send_venue_email_batch(
    source: str,
    notifications: Iterable[object],
    *,
    recipients_var: str,
) -> JsonDict:
    """Send one email for all newly detected slots without raising to the DAG."""
    normalized_source = str(source).strip() or "unknown"
    normalized_recipients_var = str(recipients_var).strip()
    normalized_notifications = _normalize_notifications(notifications)
    if not normalized_notifications:
        return {"success": True, "skipped": True, "notification_count": 0}

    if not normalized_recipients_var:
        error = "recipients_var must be provided for each venue"
        recorded = _record_failure_safely(
            normalized_source,
            normalized_notifications,
            normalized_recipients_var,
            error,
        )
        return {
            "success": False,
            "error": error,
            "fallback_recorded": recorded,
            "notification_count": len(normalized_notifications),
        }

    try:
        recipients = _normalize_recipients(
            _get_variable(
                normalized_recipients_var,
                default_var=[],
                deserialize_json=True,
            ),
            normalized_recipients_var,
        )
    except Exception as exc:
        error = str(exc)
        recorded = _record_failure_safely(
            normalized_source,
            normalized_notifications,
            normalized_recipients_var,
            error,
        )
        print(
            f"[VENUE_EMAIL] configuration failed source={normalized_source}, "
            f"config_var={normalized_recipients_var}, error={error}"
        )
        return {
            "success": False,
            "error": error,
            "fallback_recorded": recorded,
            "notification_count": len(normalized_notifications),
        }

    try:
        notification_lines = [_format_notification(item) for item in normalized_notifications]
    except Exception as exc:
        error = str(exc)
        recorded = _record_failure_safely(
            normalized_source,
            normalized_notifications,
            normalized_recipients_var,
            error,
        )
        print(f"[VENUE_EMAIL] formatting failed source={normalized_source}, error={error}")
        return {
            "success": False,
            "error": error,
            "fallback_recorded": recorded,
            "notification_count": len(normalized_notifications),
        }

    print(
        f"[VENUE_EMAIL] sending source={normalized_source}, "
        f"config_var={normalized_recipients_var}, "
        f"notification_count={len(normalized_notifications)}, "
        f"recipient_count={len(recipients)}"
    )

    result: JsonDict
    try:
        template_id = _get_email_template_id()
        template_data: dict[str, object] = {
            "FREE_TIME": "\n".join(notification_lines),
        }
        if template_id == DEFAULT_EMAIL_TEMPLATE_ID:
            template_data["COURT_NAME"] = normalized_source

        result = send_template_email(
            subject=notification_lines[0],
            template_id=template_id,
            template_data=template_data,
            recipients=recipients,
            from_email=_get_required_string_variable(EMAIL_FROM_ADDRESS_VAR),
            reply_to=_get_required_string_variable(EMAIL_REPLY_TO_VAR),
            trigger_type=1,
        )
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    if result.get("success"):
        print(
            f"[VENUE_EMAIL] sent source={normalized_source}, "
            f"notification_count={len(normalized_notifications)}"
        )
        return result

    error = str(result.get("error") or "email send failed")
    recorded = _record_failure_safely(
        normalized_source,
        normalized_notifications,
        normalized_recipients_var,
        error,
    )
    print(f"[VENUE_EMAIL] send failed source={normalized_source}, error={error}")
    return {
        **result,
        "success": False,
        "fallback_recorded": recorded,
        "notification_count": len(normalized_notifications),
    }
