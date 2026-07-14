#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable

EMAIL_SEND_FALLBACK_OUTBOX_VAR = "EMAIL_SEND_FALLBACK_OUTBOX"
EMAIL_SEND_FALLBACK_MAX_ITEMS_VAR = "EMAIL_SEND_FALLBACK_MAX_ITEMS"
EMAIL_TEMPLATE_ID = 33340
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def send_template_email(**kwargs):
    from tennis_dags.utils.tencent_ses import send_template_email as send

    return send(**kwargs)


def _get_variable(key: str, default_var=None, deserialize_json: bool = False):
    from airflow.models import Variable

    return Variable.get(key, default_var=default_var, deserialize_json=deserialize_json)


def _set_variable(key: str, value, serialize_json: bool = False):
    from airflow.models import Variable

    Variable.set(key, value, serialize_json=serialize_json)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_int_variable(key: str, default: int) -> int:
    value = _get_variable(key, default_var=str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_recipients(value, recipients_var: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Airflow Variable {recipients_var} must be a JSON list")

    recipients = []
    seen = set()
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


def _normalize_notifications(notifications: Iterable[dict]) -> list[dict]:
    normalized = []
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


def _record_failed_batch(
    source: str,
    notifications: list[dict],
    recipients_var: str,
    error: str,
) -> dict:
    now = _utc_now()
    canonical_payload = json.dumps(notifications, ensure_ascii=False, sort_keys=True)
    failure_id = hashlib.sha256(
        f"{source}\0{recipients_var}\0{canonical_payload}".encode("utf-8")
    ).hexdigest()
    outbox = _get_variable(
        EMAIL_SEND_FALLBACK_OUTBOX_VAR,
        default_var=[],
        deserialize_json=True,
    )
    if not isinstance(outbox, list):
        outbox = []

    entry = {
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
    notifications: list[dict],
    recipients_var: str,
    error: str,
) -> bool:
    try:
        _record_failed_batch(source, notifications, recipients_var, error)
        return True
    except Exception as fallback_exc:
        print(
            f"[VENUE_EMAIL] fallback persistence failed source={source}, "
            f"error={fallback_exc}"
        )
        return False


def send_venue_email_batch(
    source: str,
    notifications: Iterable[dict],
    *,
    recipients_var: str,
) -> dict:
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

    free_time_lines = [
        f"{item['court_name']} {item['date']} {item['start_time']}-{item['end_time']}"
        for item in normalized_notifications
    ]
    print(
        f"[VENUE_EMAIL] sending source={normalized_source}, "
        f"config_var={normalized_recipients_var}, "
        f"notification_count={len(normalized_notifications)}, "
        f"recipient_count={len(recipients)}"
    )

    try:
        result = send_template_email(
            subject=f"【{normalized_source}】发现{len(normalized_notifications)}个可订时段",
            template_id=EMAIL_TEMPLATE_ID,
            template_data={
                "COURT_NAME": normalized_source,
                "FREE_TIME": "；".join(free_time_lines),
            },
            recipients=recipients,
            from_email="Zacks <tennis@zacks.com.cn>",
            reply_to="tennis@zacks.com.cn",
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
