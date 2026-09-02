#!/usr/bin/env python3

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import requests

from wechat_airflow.notifications.observation_cache import (
    cached_gate_for_venue,
    decide_observation_delivery,
    record_observation_result,
)

WEBAPP_OBSERVATION_API_URL_VAR = "WEBAPP_OBSERVATION_API_URL"
WEBAPP_OBSERVATION_API_TOKEN_VAR = "WEBAPP_OBSERVATION_API_TOKEN"
WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR = "WEBAPP_OBSERVATION_TIMEOUT_SECONDS"
WEBAPP_WECHAT_GATE_CACHE_VAR = "WEBAPP_WECHAT_SUBSCRIPTION_GATES"
WEBAPP_WECHAT_GATE_MODE_VAR = "WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_GATE_MODE = "enforce"


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


def _current_observation_scope() -> str | None:
    """Return a stable Airflow task scope without coupling callers to task IDs."""
    try:
        from airflow.sdk import get_current_context

        context = get_current_context()
    except Exception:
        return None

    task_instance = context.get("task_instance") or context.get("ti")
    task = context.get("task")
    task_id = str(
        getattr(task_instance, "task_id", "") or getattr(task, "task_id", "") or ""
    ).strip()
    if not task_id:
        return None
    map_index = getattr(task_instance, "map_index", -1)
    if isinstance(map_index, int) and map_index >= 0:
        return f"{task_id}:{map_index}"
    return task_id


def flatten_court_slots(
    booking_date: str,
    court_data: Mapping[str, Iterable[Iterable[object]]],
) -> list[dict[str, str]]:
    """Convert a venue adapter's court mapping into the web subscription contract."""
    slots: list[dict[str, str]] = []
    for court_name, free_slots in (court_data or {}).items():
        normalized_court_name = str(court_name).strip()
        if not normalized_court_name:
            continue
        for slot in free_slots or []:
            values = list(slot)
            if len(values) < 2:
                continue
            start_time = str(values[0]).strip()
            end_time = str(values[1]).strip()
            if end_time == "24:00":
                end_time = "23:59"
            if len(start_time) != 5 or len(end_time) != 5:
                continue
            slots.append(
                {
                    "date": booking_date,
                    "court_name": normalized_court_name,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
    return slots


def _normalize_gate(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    evaluated_at = str(value.get("evaluatedAt") or value.get("evaluated_at") or "").strip()
    valid_until = str(value.get("validUntil") or value.get("valid_until") or "").strip()
    try:
        evaluated_ts = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        valid_until_ts = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except ValueError:
        return None
    if evaluated_ts.tzinfo is None or valid_until_ts.tzinfo is None:
        return None
    return {
        "allowed": value.get("allowed") is True,
        "evaluated_at": evaluated_ts.astimezone(UTC).isoformat(),
        "valid_until": valid_until_ts.astimezone(UTC).isoformat(),
        "revision": int(value.get("revision") or 0),
    }


def _cache_gate(venue_id: str, gate: dict[str, Any]) -> None:
    try:
        cached = _get_variable(WEBAPP_WECHAT_GATE_CACHE_VAR, default={}, deserialize_json=True)
        if not isinstance(cached, dict):
            cached = {}
        if _normalize_gate(cached.get(str(venue_id))) == gate:
            return
        cached[str(venue_id)] = gate
        _set_variable(WEBAPP_WECHAT_GATE_CACHE_VAR, cached, serialize_json=True)
    except Exception as exc:
        print(f"[WEBAPP_WECHAT_GATE] cache write failed venue={venue_id}, error={str(exc)[:200]}")


def _cached_gate(venue_id: str) -> dict[str, Any] | None:
    local_gate = _normalize_gate(cached_gate_for_venue(venue_id))
    if local_gate is not None:
        return local_gate
    try:
        cached = _get_variable(WEBAPP_WECHAT_GATE_CACHE_VAR, default={}, deserialize_json=True)
    except Exception:
        return None
    if not isinstance(cached, dict):
        return None
    return _normalize_gate(cached.get(str(venue_id)))


def wechat_delivery_allowed(
    venue_id: str,
    observation_result: Mapping[str, object] | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the venue's WeChat alert may be delivered.

    `off` preserves the legacy behavior. `shadow` logs the decision but does not
    suppress. `enforce` is the production default: a fresh Web-owned subscription
    gate is required, while a short Cloudflare outage may reuse the last gate until
    its `valid_until` timestamp. Missing/stale state fails closed.
    """
    mode = (
        str(_get_variable(WEBAPP_WECHAT_GATE_MODE_VAR, default=DEFAULT_GATE_MODE)).strip().lower()
    )
    if mode not in {"off", "shadow", "enforce"}:
        mode = DEFAULT_GATE_MODE
    if mode == "off":
        return True

    gate = None
    if observation_result:
        gate = _normalize_gate(
            observation_result.get("wechat_gate") or observation_result.get("wechatGate")
        )
    if gate is None:
        gate = _cached_gate(venue_id)

    current = (now or datetime.now(UTC)).astimezone(UTC)
    fresh = False
    allowed = False
    if gate:
        try:
            valid_until = datetime.fromisoformat(str(gate["valid_until"]).replace("Z", "+00:00"))
            fresh = valid_until >= current
            allowed = fresh and bool(gate.get("allowed"))
        except (KeyError, ValueError, TypeError):
            fresh = False
            allowed = False

    decision = "allow" if allowed else "suppress"
    print(
        f"[WEBAPP_WECHAT_GATE] venue={venue_id}, mode={mode}, decision={decision}, "
        f"fresh={fresh}, revision={gate.get('revision') if gate else None}"
    )
    if mode == "shadow":
        return True
    return allowed


def publish_venue_observation(
    venue_id: str,
    venue_name: str,
    slots: Iterable[Mapping[str, object]],
    *,
    healthy: bool,
    error: str | None = None,
    checked_at: datetime | None = None,
    observation_scope: str | None = None,
) -> dict[str, Any]:
    """Publish venue state without failing the calling DAG."""
    api_url = str(_get_variable(WEBAPP_OBSERVATION_API_URL_VAR, default="")).strip()
    api_token = str(_get_variable(WEBAPP_OBSERVATION_API_TOKEN_VAR, default="")).strip()
    if not api_url or not api_token:
        print("[WEBAPP] observation publishing skipped: configuration is incomplete")
        return {"success": True, "skipped": True, "configured": False}

    try:
        timeout = float(
            _get_variable(
                WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR,
                default=str(DEFAULT_TIMEOUT_SECONDS),
            )
        )
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = min(max(timeout, 0.5), 15.0)

    normalized_slots = []
    for slot in slots:
        normalized_slots.append(
            {
                "date": str(slot.get("date") or "").strip(),
                "court_name": str(slot.get("court_name") or "").strip(),
                "start_time": str(slot.get("start_time") or "").strip(),
                "end_time": str(slot.get("end_time") or "").strip(),
            }
        )

    normalized_scope = (
        str(observation_scope or _current_observation_scope() or "default").strip()[:120]
        or "default"
    )
    payload: dict[str, object] = {
        "venue_id": venue_id,
        "venue_name": venue_name,
        "observation_scope": normalized_scope,
        "healthy": bool(healthy),
        "checked_at": (checked_at or datetime.now(UTC)).isoformat(),
        "error": str(error or "")[:300] or None,
        "slots": normalized_slots[:200],
    }
    slot_count = len(normalized_slots[:200])
    delivery = decide_observation_delivery(payload)
    cached_gate = _normalize_gate(delivery.gate)
    if delivery.action == "skip_success":
        print(
            f"[WEBAPP] observation locally deduplicated venue={venue_id}, "
            f"scope={normalized_scope}, healthy={healthy}, slots={slot_count}"
        )
        return {
            "success": True,
            "slot_count": slot_count,
            "observation_scope": normalized_scope,
            "local_deduplicated": True,
            "wechat_gate": cached_gate,
        }
    if delivery.action == "skip_retry":
        print(
            f"[WEBAPP] observation retry throttled venue={venue_id}, "
            f"scope={normalized_scope}, healthy={healthy}, slots={slot_count}"
        )
        return {
            "success": False,
            "deferred": True,
            "error": "recent Web publication failure; local retry is throttled",
            "slot_count": slot_count,
            "observation_scope": normalized_scope,
            "wechat_gate": cached_gate,
        }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}
        gate = _normalize_gate(
            response_payload.get("wechatGate") if isinstance(response_payload, dict) else None
        )
        record_observation_result(delivery, success=True, gate=gate)
        if gate is not None:
            _cache_gate(venue_id, gate)
        print(
            f"[WEBAPP] observation published venue={venue_id}, "
            f"scope={normalized_scope}, healthy={healthy}, slots={slot_count}, "
            f"wechat_gate={gate.get('allowed') if gate else None}"
        )
        return {
            "success": True,
            "slot_count": slot_count,
            "observation_scope": normalized_scope,
            "local_deduplicated": False,
            "wechat_gate": gate,
        }
    except Exception as exc:
        record_observation_result(delivery, success=False, gate=cached_gate)
        print(f"[WEBAPP] observation publishing failed venue={venue_id}, error={str(exc)[:300]}")
        return {
            "success": False,
            "error": str(exc)[:300],
            "slot_count": slot_count,
            "observation_scope": normalized_scope,
            "wechat_gate": cached_gate or _cached_gate(venue_id),
        }
