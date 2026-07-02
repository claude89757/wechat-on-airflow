#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from typing import Iterable, Optional

import requests


WECHAT_SEND_API_URL_VAR = "WECHAT_SEND_API_URL"
WECHAT_SEND_DEVICE_NAME_VAR = "WECHAT_SEND_DEVICE_NAME"
WECHAT_SEND_TIMEOUT_SECONDS_VAR = "WECHAT_SEND_TIMEOUT_SECONDS"
WECHAT_SEND_RETRY_COUNT_VAR = "WECHAT_SEND_RETRY_COUNT"
WECHAT_SEND_RETRY_DELAY_SECONDS_VAR = "WECHAT_SEND_RETRY_DELAY_SECONDS"


class WeChatSendApiError(Exception):
    """Raised when the remote WeChat sender API rejects or fails a send."""


def _get_variable(key: str, default_var=None, deserialize_json: bool = False):
    from airflow.models import Variable

    return Variable.get(key, default_var=default_var, deserialize_json=deserialize_json)


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


def _normalize_chatrooms(chatrooms) -> list[str]:
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


def _request_once(api_url: str, payload: dict, timeout_seconds: int) -> dict:
    try:
        response = requests.post(api_url, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise WeChatSendApiError(f"wechat send api request failed: {exc}") from exc

    response_text = response.text

    try:
        result = response.json()
    except ValueError as exc:
        raise WeChatSendApiError(
            f"wechat send api returned non-json response: status={response.status_code}, body={response_text[:200]}"
        ) from exc

    if response.status_code >= 400 or not result.get("success"):
        error = result.get("error") or f"http_{response.status_code}"
        message = result.get("message") or response_text[:200]
        raise WeChatSendApiError(f"wechat send api failed: {error}: {message}")

    return result


def send_wechat_text(receiver: str, messages: Iterable[str], device_name: Optional[str] = None) -> dict:
    api_url = str(_get_variable(WECHAT_SEND_API_URL_VAR, default_var="")).strip()
    if not api_url:
        raise WeChatSendApiError(f"Airflow Variable {WECHAT_SEND_API_URL_VAR} is required")

    resolved_device_name = (device_name or _get_variable(WECHAT_SEND_DEVICE_NAME_VAR, default_var="")).strip()
    if not resolved_device_name:
        raise WeChatSendApiError(
            f"device_name is required or Airflow Variable {WECHAT_SEND_DEVICE_NAME_VAR} must be set"
        )

    normalized_receiver = str(receiver).strip()
    if not normalized_receiver:
        raise WeChatSendApiError("receiver is required")

    payload = {
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

    last_error = None
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


def send_wechat_text_to_chatrooms(chatrooms, message: str, device_name: Optional[str] = None) -> list[dict]:
    results = []
    chatroom_list = _normalize_chatrooms(chatrooms)
    print(f"[WECHAT_SEND_API] target_chatrooms={chatroom_list}")

    for chatroom in chatroom_list:
        results.append(send_wechat_text(chatroom, [message], device_name=device_name))
    return results


def send_wechat_text_to_chatrooms_var(
    chatrooms_var: str,
    message: str,
    device_name: Optional[str] = None,
) -> list[dict]:
    chatrooms = _get_variable(chatrooms_var, default_var="")
    return send_wechat_text_to_chatrooms(chatrooms, message, device_name=device_name)
