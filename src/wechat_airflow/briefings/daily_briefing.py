from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, cast

from wechat_airflow.briefings.config import (
    DAILY_BRIEFING_ENABLED_VAR,
    DAILY_BRIEFING_LOOKBACK_HOURS_VAR,
    DAILY_BRIEFING_MAX_ITEMS_VAR,
    DAILY_BRIEFING_MODEL_VAR,
    DAILY_BRIEFING_OPENAI_API_KEY_VAR,
    DAILY_BRIEFING_OPENAI_API_URL_VAR,
    DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS_VAR,
    DAILY_BRIEFING_STATE_VAR,
    DAILY_BRIEFING_TOPICS_VAR,
    DAILY_BRIEFING_WECHAT_RECEIVER_VAR,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RESPONSES_API_URL,
    DEFAULT_TOPICS,
)
from wechat_airflow.briefings.content import (
    build_briefing_prompt,
    format_briefing_message,
    now_local,
    split_wechat_messages,
)
from wechat_airflow.briefings.models import (
    BriefingSource,
    DailyBriefingApiError,
    DailyBriefingConfigError,
    DailyBriefingError,
    JsonDict,
)
from wechat_airflow.briefings.openai_client import (
    generate_briefing,
    parse_responses_api_result,
    source_from_mapping,
)
from wechat_airflow.notifications.wechat import send_wechat_text

__all__ = [
    "BriefingSource",
    "DailyBriefingApiError",
    "DailyBriefingConfigError",
    "DailyBriefingError",
    "build_briefing_prompt",
    "format_briefing_message",
    "generate_briefing",
    "parse_responses_api_result",
    "run_daily_briefing",
    "split_wechat_messages",
]


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


def _is_enabled(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalized_topics(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_TOPICS)
    topics = [str(item).strip() for item in value if str(item).strip()]
    return topics or list(DEFAULT_TOPICS)


def _load_state() -> JsonDict:
    value = _get_variable(DAILY_BRIEFING_STATE_VAR, default={}, deserialize_json=True)
    if not isinstance(value, dict):
        return {}
    return cast(JsonDict, value)


def _save_state(value: JsonDict) -> None:
    _set_variable(DAILY_BRIEFING_STATE_VAR, value, serialize_json=True)


def _state_draft(state: JsonDict, local_date: str) -> tuple[str, list[BriefingSource]] | None:
    if state.get("date") != local_date:
        return None
    body = state.get("message")
    raw_sources = state.get("sources")
    if not isinstance(body, str) or not body.strip() or not isinstance(raw_sources, list):
        return None
    sources = [
        source
        for raw_source in raw_sources
        for source in [source_from_mapping(raw_source)]
        if source is not None
    ]
    return body, sources


def _source_payload(sources: list[BriefingSource]) -> list[JsonDict]:
    return [{"title": source.title, "url": source.url} for source in sources]


def run_daily_briefing(now: datetime | None = None) -> JsonDict:
    if not _is_enabled(_get_variable(DAILY_BRIEFING_ENABLED_VAR, default="false")):
        print("[DAILY_BRIEFING] disabled")
        return {"success": True, "skipped": True, "reason": "disabled"}

    local_now = now_local(now)
    local_date = local_now.date().isoformat()
    state = _load_state()
    if state.get("sent_date") == local_date:
        print(f"[DAILY_BRIEFING] already sent local_date={local_date}")
        return {"success": True, "skipped": True, "reason": "already_sent"}

    api_key = str(_get_variable(DAILY_BRIEFING_OPENAI_API_KEY_VAR, default="")).strip()
    receiver = str(_get_variable(DAILY_BRIEFING_WECHAT_RECEIVER_VAR, default="")).strip()
    if not api_key:
        raise DailyBriefingConfigError(
            f"Airflow Variable {DAILY_BRIEFING_OPENAI_API_KEY_VAR} is required when enabled"
        )
    if not receiver:
        raise DailyBriefingConfigError(
            f"Airflow Variable {DAILY_BRIEFING_WECHAT_RECEIVER_VAR} is required when enabled"
        )

    api_url = str(
        _get_variable(DAILY_BRIEFING_OPENAI_API_URL_VAR, default=DEFAULT_RESPONSES_API_URL)
    ).strip()
    model = str(_get_variable(DAILY_BRIEFING_MODEL_VAR, default=DEFAULT_MODEL)).strip()
    lookback_hours = _positive_int(
        _get_variable(
            DAILY_BRIEFING_LOOKBACK_HOURS_VAR,
            default=str(DEFAULT_LOOKBACK_HOURS),
        ),
        DEFAULT_LOOKBACK_HOURS,
    )
    timeout_seconds = _positive_int(
        _get_variable(
            DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS_VAR,
            default=str(DEFAULT_REQUEST_TIMEOUT_SECONDS),
        ),
        DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    max_items = min(
        _positive_int(
            _get_variable(DAILY_BRIEFING_MAX_ITEMS_VAR, default=str(DEFAULT_MAX_ITEMS)),
            DEFAULT_MAX_ITEMS,
        ),
        12,
    )
    topics = _normalized_topics(
        _get_variable(DAILY_BRIEFING_TOPICS_VAR, default=DEFAULT_TOPICS, deserialize_json=True)
    )

    draft = _state_draft(state, local_date)
    if draft is None:
        prompt = build_briefing_prompt(
            now=local_now,
            topics=topics,
            lookback_hours=lookback_hours,
            max_items=max_items,
        )
        body, sources = generate_briefing(
            api_key=api_key,
            api_url=api_url,
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
        message = format_briefing_message(
            local_date=local_date,
            body=body,
            sources=sources,
        )
        state = {
            "date": local_date,
            "status": "generated",
            "message": message,
            "sources": _source_payload(sources),
            "generated_at": local_now.isoformat(),
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        }
        _save_state(state)
    else:
        message, sources = draft
        print(f"[DAILY_BRIEFING] reusing cached draft local_date={local_date}")

    messages = split_wechat_messages(message)
    try:
        result = send_wechat_text(receiver, messages)
    except Exception as exc:
        failed_state = dict(state)
        failed_state.update(
            {
                "date": local_date,
                "status": "delivery_failed",
                "last_error": str(exc)[:1000],
                "last_attempt_at": now_local().isoformat(),
            }
        )
        _save_state(failed_state)
        raise

    sent_state = dict(state)
    sent_state.update(
        {
            "date": local_date,
            "status": "sent",
            "sent_date": local_date,
            "sent_at": now_local().isoformat(),
            "message_count": len(messages),
        }
    )
    sent_state.pop("last_error", None)
    _save_state(sent_state)
    print(
        f"[DAILY_BRIEFING] sent local_date={local_date}, "
        f"message_count={len(messages)}, source_count={len(sources)}"
    )
    return {
        "success": True,
        "skipped": False,
        "local_date": local_date,
        "message_count": len(messages),
        "source_count": len(sources),
        "delivery": result,
    }
