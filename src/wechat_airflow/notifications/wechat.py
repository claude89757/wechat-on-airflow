#!/usr/bin/env python3

import hashlib
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import requests

from wechat_airflow.notifications.booking_links import (
    BOOKING_LINK_LAST_SENT_VAR,
    BookingLinkPlan,
    plan_booking_link,
    restore_sent,
)

JsonDict = dict[str, Any]

WECHAT_SEND_API_URL_VAR = "WECHAT_SEND_API_URL"
WECHAT_SEND_DEVICE_NAME_VAR = "WECHAT_SEND_DEVICE_NAME"
WECHAT_SEND_TIMEOUT_SECONDS_VAR = "WECHAT_SEND_TIMEOUT_SECONDS"
WECHAT_SEND_RETRY_COUNT_VAR = "WECHAT_SEND_RETRY_COUNT"
WECHAT_SEND_RETRY_DELAY_SECONDS_VAR = "WECHAT_SEND_RETRY_DELAY_SECONDS"
WECHAT_SEND_FALLBACK_OUTBOX_VAR = "WECHAT_SEND_FALLBACK_OUTBOX"
WECHAT_SEND_FALLBACK_MAX_ITEMS_VAR = "WECHAT_SEND_FALLBACK_MAX_ITEMS"
MIN_SEND_TIMEOUT_SECONDS = 210
DEFAULT_RETRY_COUNT = 4
DEVICE_BUSY_ERROR = "device_busy"
DEVICE_BUSY_RETRY_LIMIT = 4
DEVICE_BUSY_RETRY_DELAY_SECONDS = 15.0


class WeChatSendApiError(Exception):
    """Raised when the remote WeChat sender API rejects or fails a send."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


def _get_variable(
    key: str,
    default: Any = None,
    deserialize_json: bool = False,
) -> Any:
    from airflow.sdk import Variable

    return Variable.get(key, default=default, deserialize_json=deserialize_json)


def _set_variable(key: str, value: Any, serialize_json: bool = False) -> None:
    from airflow.sdk import Variable

    Variable.set(key, value, serialize_json=serialize_json)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_messages(messages: Iterable[str]) -> list[str]:
    if isinstance(messages, str):
        messages = [messages]

    normalized = []
    for message in messages:
        if not isinstance(message, str) or not message.strip():
            continue
        normalized.append(message)

    if not normalized:
        raise WeChatSendApiError("messages must contain at least one non-empty string")
    return normalized


def _normalize_chatrooms(chatrooms: object) -> list[str]:
    if isinstance(chatrooms, str):
        candidates = chatrooms.splitlines()
    elif isinstance(chatrooms, list):
        candidates = chatrooms
    else:
        candidates = []
    return [str(chatroom).strip() for chatroom in candidates if str(chatroom).strip()]


def _get_int_variable(key: str, default: int) -> int:
    value = _get_variable(key, default=str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_float_variable(key: str, default: float) -> float:
    value = _get_variable(key, default=str(default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_device_busy_error(error: WeChatSendApiError) -> bool:
    return error.error_code == DEVICE_BUSY_ERROR or DEVICE_BUSY_ERROR in str(error)


def _request_once(api_url: str, payload: JsonDict, timeout_seconds: int) -> JsonDict:
    try:
        response = requests.post(api_url, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise WeChatSendApiError(f"wechat send api request failed: {exc}") from exc

    response_text = response.text

    try:
        raw_result = response.json()
    except ValueError as exc:
        raise WeChatSendApiError(
            f"wechat send api returned non-json response: status={response.status_code}, body={response_text[:200]}"
        ) from exc

    if not isinstance(raw_result, dict):
        raise WeChatSendApiError(
            f"wechat send api returned invalid JSON shape: status={response.status_code}"
        )
    result = cast(JsonDict, raw_result)

    if response.status_code >= 400 or not result.get("success"):
        error = result.get("error") or f"http_{response.status_code}"
        message = result.get("message") or response_text[:200]
        raise WeChatSendApiError(
            f"wechat send api failed: {error}: {message}",
            error_code=str(error),
        )

    return result


def send_wechat_text(
    receiver: str, messages: Iterable[str], device_name: str | None = None
) -> JsonDict:
    api_url = str(_get_variable(WECHAT_SEND_API_URL_VAR, default="")).strip()
    if not api_url:
        raise WeChatSendApiError(f"Airflow Variable {WECHAT_SEND_API_URL_VAR} is required")

    resolved_device_name = str(
        device_name or _get_variable(WECHAT_SEND_DEVICE_NAME_VAR, default="")
    ).strip()
    if not resolved_device_name:
        raise WeChatSendApiError(
            f"device_name is required or Airflow Variable {WECHAT_SEND_DEVICE_NAME_VAR} must be set"
        )

    normalized_receiver = str(receiver).strip()
    if not normalized_receiver:
        raise WeChatSendApiError("receiver is required")

    payload: JsonDict = {
        "receiver": normalized_receiver,
        "messages": _normalize_messages(messages),
        "device_name": resolved_device_name,
    }
    payload["idempotency_key"] = hashlib.sha256(
        "\0".join([normalized_receiver, resolved_device_name, *payload["messages"]]).encode()
    ).hexdigest()

    timeout_seconds = max(
        _get_int_variable(WECHAT_SEND_TIMEOUT_SECONDS_VAR, MIN_SEND_TIMEOUT_SECONDS),
        MIN_SEND_TIMEOUT_SECONDS,
    )
    retry_count = max(_get_int_variable(WECHAT_SEND_RETRY_COUNT_VAR, DEFAULT_RETRY_COUNT), 1)
    retry_delay_seconds = max(_get_float_variable(WECHAT_SEND_RETRY_DELAY_SECONDS_VAR, 5.0), 0)

    print(
        f"[WECHAT_SEND_API] sending receiver={normalized_receiver}, "
        f"message_count={len(payload['messages'])}, config_var={WECHAT_SEND_API_URL_VAR}"
    )

    last_error: WeChatSendApiError | None = None
    busy_attempts = 0
    other_attempts = 0
    while True:
        try:
            result = _request_once(api_url, payload, timeout_seconds)
            print(
                f"[WECHAT_SEND_API] sent receiver={normalized_receiver}, "
                f"sent_count={result.get('sent_count')}"
            )
            return result
        except WeChatSendApiError as exc:
            last_error = exc
            if _is_device_busy_error(exc):
                busy_attempts += 1
                if busy_attempts >= DEVICE_BUSY_RETRY_LIMIT:
                    break
                delay_seconds = DEVICE_BUSY_RETRY_DELAY_SECONDS
                print(
                    f"[WECHAT_SEND_API] device busy attempt {busy_attempts}/"
                    f"{DEVICE_BUSY_RETRY_LIMIT} failed: {exc}; waiting {delay_seconds}s"
                )
            else:
                other_attempts += 1
                if other_attempts >= retry_count:
                    break
                delay_seconds = retry_delay_seconds
                print(
                    f"[WECHAT_SEND_API] attempt {other_attempts}/{retry_count} failed: "
                    f"{exc}; retrying"
                )
            time.sleep(delay_seconds)

    raise last_error or WeChatSendApiError("wechat send api failed")


def send_wechat_text_to_chatrooms(
    chatrooms: object,
    message: str,
    device_name: str | None = None,
) -> list[JsonDict]:
    results: list[JsonDict] = []
    chatroom_list = _normalize_chatrooms(chatrooms)
    print(f"[WECHAT_SEND_API] target_chatrooms={chatroom_list}")

    for chatroom in chatroom_list:
        results.append(send_wechat_text(chatroom, [message], device_name=device_name))
    return results


def _record_failed_send(
    receiver: str,
    message: str,
    source: str,
    error: Exception,
) -> JsonDict:
    now = _utc_now()
    failure_id = hashlib.sha256(f"{source}\0{receiver}\0{message}".encode()).hexdigest()
    outbox = _get_variable(
        WECHAT_SEND_FALLBACK_OUTBOX_VAR,
        default=[],
        deserialize_json=True,
    )
    if not isinstance(outbox, list):
        outbox = []

    entry: JsonDict = {
        "id": failure_id,
        "source": source,
        "receiver": receiver,
        "message": message,
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

    max_items = max(_get_int_variable(WECHAT_SEND_FALLBACK_MAX_ITEMS_VAR, 200), 1)
    _set_variable(
        WECHAT_SEND_FALLBACK_OUTBOX_VAR,
        outbox[-max_items:],
        serialize_json=True,
    )
    return entry


def _load_booking_link_cache() -> object:
    cache = _get_variable(BOOKING_LINK_LAST_SENT_VAR, default={}, deserialize_json=True)
    if isinstance(cache, dict):
        return cache
    return {}


def _save_booking_link_cache(cache: object) -> None:
    _set_variable(BOOKING_LINK_LAST_SENT_VAR, cache, serialize_json=True)


def _plan_outbound_booking_link(
    chatroom: str,
    message: str,
    booking_venue_id: str | None,
) -> BookingLinkPlan:
    try:
        return plan_booking_link(
            message,
            receiver=chatroom,
            venue_id=booking_venue_id,
            cache=_load_booking_link_cache(),
            now=datetime.now(),
        )
    except Exception as exc:
        print(f"[WECHAT_BOOKING_LINK] plan failed: {exc}")
        return BookingLinkPlan(
            message=message,
            cache=None,
            program_id=None,
            previous_timestamp=None,
        )


def _commit_booking_link_plan(plan: BookingLinkPlan) -> None:
    if plan.cache is None:
        return
    try:
        _save_booking_link_cache(plan.cache)
    except Exception as exc:
        print(f"[WECHAT_BOOKING_LINK] claim failed: {exc}")


def _release_booking_link_plan(chatroom: str, plan: BookingLinkPlan) -> None:
    if plan.cache is None or plan.program_id is None:
        return
    try:
        restored = restore_sent(
            _load_booking_link_cache(),
            chatroom,
            plan.program_id,
            plan.previous_timestamp,
        )
        _save_booking_link_cache(restored)
    except Exception as exc:
        print(f"[WECHAT_BOOKING_LINK] release failed: {exc}")


def send_wechat_text_to_chatrooms_best_effort(
    chatrooms: object,
    message: str,
    device_name: str | None = None,
    source: str = "unknown",
    booking_venue_id: str | None = None,
) -> list[JsonDict]:
    """Send each chat independently and persist failures without raising."""
    results: list[JsonDict] = []
    chatroom_list = _normalize_chatrooms(chatrooms)
    normalized_source = str(source).strip() or "unknown"
    print(f"[WECHAT_SEND_FALLBACK] target_chatrooms={chatroom_list}, source={normalized_source}")

    for chatroom in chatroom_list:
        plan = _plan_outbound_booking_link(chatroom, message, booking_venue_id)
        outbound = plan.message
        _commit_booking_link_plan(plan)
        try:
            result = send_wechat_text(chatroom, [outbound], device_name=device_name)
            results.append({"success": True, "receiver": chatroom, "result": result})
        except Exception as exc:
            _release_booking_link_plan(chatroom, plan)
            print(
                f"[WECHAT_SEND_FALLBACK] send failed receiver={chatroom}, "
                f"source={normalized_source}, error={exc}"
            )
            try:
                _record_failed_send(chatroom, outbound, normalized_source, exc)
            except Exception as fallback_exc:
                print(
                    f"[WECHAT_SEND_FALLBACK] persistence failed receiver={chatroom}, "
                    f"source={normalized_source}, error={fallback_exc}"
                )
            results.append({"success": False, "receiver": chatroom, "error": str(exc)})

    return results


def send_wechat_text_to_chatrooms_var(
    chatrooms_var: str,
    message: str,
    device_name: str | None = None,
) -> list[JsonDict]:
    chatrooms = _get_variable(chatrooms_var, default="")
    return send_wechat_text_to_chatrooms(chatrooms, message, device_name=device_name)
