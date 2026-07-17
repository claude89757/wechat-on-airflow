#!/usr/bin/env python3

import hashlib
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import requests

JsonDict = dict[str, Any]

WECHAT_SEND_API_URL_VAR = "WECHAT_SEND_API_URL"
WECHAT_SEND_DEVICE_NAME_VAR = "WECHAT_SEND_DEVICE_NAME"
WECHAT_SEND_TIMEOUT_SECONDS_VAR = "WECHAT_SEND_TIMEOUT_SECONDS"
WECHAT_SEND_RETRY_COUNT_VAR = "WECHAT_SEND_RETRY_COUNT"
WECHAT_SEND_RETRY_DELAY_SECONDS_VAR = "WECHAT_SEND_RETRY_DELAY_SECONDS"
WECHAT_SEND_FALLBACK_OUTBOX_VAR = "WECHAT_SEND_FALLBACK_OUTBOX"
WECHAT_SEND_FALLBACK_MAX_ITEMS_VAR = "WECHAT_SEND_FALLBACK_MAX_ITEMS"


class WeChatSendApiError(Exception):
    """Raised when the remote WeChat sender API rejects or fails a send."""


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
    value = _get_variable(key, default_var=str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_float_variable(key: str, default: float) -> float:
    value = _get_variable(key, default_var=str(default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        raise WeChatSendApiError(f"wechat send api failed: {error}: {message}")

    return result


def send_wechat_text(
    receiver: str, messages: Iterable[str], device_name: str | None = None
) -> JsonDict:
    api_url = str(_get_variable(WECHAT_SEND_API_URL_VAR, default_var="")).strip()
    if not api_url:
        raise WeChatSendApiError(f"Airflow Variable {WECHAT_SEND_API_URL_VAR} is required")

    resolved_device_name = str(
        device_name or _get_variable(WECHAT_SEND_DEVICE_NAME_VAR, default_var="")
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

    timeout_seconds = _get_int_variable(WECHAT_SEND_TIMEOUT_SECONDS_VAR, 120)
    retry_count = max(_get_int_variable(WECHAT_SEND_RETRY_COUNT_VAR, 3), 1)
    retry_delay_seconds = max(_get_float_variable(WECHAT_SEND_RETRY_DELAY_SECONDS_VAR, 5.0), 0)

    print(
        f"[WECHAT_SEND_API] sending receiver={normalized_receiver}, "
        f"message_count={len(payload['messages'])}, config_var={WECHAT_SEND_API_URL_VAR}"
    )

    last_error: WeChatSendApiError | None = None
    for attempt in range(1, retry_count + 1):
        try:
            result = _request_once(api_url, payload, timeout_seconds)
            print(
                f"[WECHAT_SEND_API] sent receiver={normalized_receiver}, "
                f"sent_count={result.get('sent_count')}"
            )
            return result
        except WeChatSendApiError as exc:
            last_error = exc
            if attempt >= retry_count:
                break
            print(f"[WECHAT_SEND_API] attempt {attempt}/{retry_count} failed: {exc}; retrying")
            time.sleep(retry_delay_seconds)

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
        default_var=[],
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


def send_wechat_text_to_chatrooms_best_effort(
    chatrooms: object,
    message: str,
    device_name: str | None = None,
    source: str = "unknown",
) -> list[JsonDict]:
    """Send each chat independently and persist failures without raising."""
    results: list[JsonDict] = []
    chatroom_list = _normalize_chatrooms(chatrooms)
    normalized_source = str(source).strip() or "unknown"
    print(f"[WECHAT_SEND_FALLBACK] target_chatrooms={chatroom_list}, source={normalized_source}")

    for chatroom in chatroom_list:
        try:
            result = send_wechat_text(chatroom, [message], device_name=device_name)
            results.append({"success": True, "receiver": chatroom, "result": result})
        except Exception as exc:
            print(
                f"[WECHAT_SEND_FALLBACK] send failed receiver={chatroom}, "
                f"source={normalized_source}, error={exc}"
            )
            try:
                _record_failed_send(chatroom, message, normalized_source, exc)
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
    chatrooms = _get_variable(chatrooms_var, default_var="")
    return send_wechat_text_to_chatrooms(chatrooms, message, device_name=device_name)
