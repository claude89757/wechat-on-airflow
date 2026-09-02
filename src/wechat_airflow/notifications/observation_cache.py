from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

OBSERVATION_CACHE_ENABLED_ENV = "WEBAPP_OBSERVATION_LOCAL_DEDUPE_ENABLED"
OBSERVATION_CACHE_PATH_ENV = "WEBAPP_OBSERVATION_STATE_PATH"
OBSERVATION_HEARTBEAT_SECONDS_ENV = "WEBAPP_OBSERVATION_HEARTBEAT_SECONDS"
OBSERVATION_FAILURE_RETRY_SECONDS_ENV = "WEBAPP_OBSERVATION_FAILURE_RETRY_SECONDS"
DEFAULT_OBSERVATION_CACHE_PATH = Path("/opt/airflow/logs/webapp-observation-state.json")
DEFAULT_OBSERVATION_HEARTBEAT_SECONDS = 480.0
DEFAULT_OBSERVATION_FAILURE_RETRY_SECONDS = 120.0
_STATE_VERSION = 2

ObservationAction = Literal["forward", "skip_success", "skip_retry"]


class CacheEntry(TypedDict):
    fingerprint: str
    last_attempt_at: float
    last_success_at: float
    gate: dict[str, Any] | None


class VenueHeartbeat(TypedDict):
    last_attempt_at: float
    last_success_at: float


class CacheState(TypedDict):
    version: int
    entries: dict[str, CacheEntry]
    venues: dict[str, VenueHeartbeat]


@dataclass(frozen=True)
class ObservationDeliveryDecision:
    action: ObservationAction
    key: str
    fingerprint: str
    gate: dict[str, Any] | None
    enabled: bool
    venue_id: str = ""


def _configured_seconds(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    try:
        value = float(raw)
    except ValueError:
        return fallback
    return min(max(value, 1.0), 3_600.0)


def _explicitly_enabled() -> bool | None:
    value = os.environ.get(OBSERVATION_CACHE_ENABLED_ENV)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def observation_cache_path() -> Path:
    configured = os.environ.get(OBSERVATION_CACHE_PATH_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_OBSERVATION_CACHE_PATH


def observation_cache_enabled() -> bool:
    explicit = _explicitly_enabled()
    if explicit is False:
        return False
    path = observation_cache_path()
    if explicit is True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
    return path.parent.is_dir() and os.access(path.parent, os.W_OK)


def _string_field(candidate: Mapping[str, object], snake_case: str, camel_case: str) -> str:
    return str(candidate.get(snake_case) or candidate.get(camel_case) or "").strip()


def _canonical_slots(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    slots: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        candidate = {str(key): item_value for key, item_value in item.items()}
        slot = {
            "date": str(candidate.get("date") or "").strip(),
            "court_name": _string_field(candidate, "court_name", "courtName"),
            "start_time": _string_field(candidate, "start_time", "startTime"),
            "end_time": _string_field(candidate, "end_time", "endTime"),
        }
        key = "|".join(slot.values())
        slots[key] = slot
    return [slots[key] for key in sorted(slots)]


def observation_identity(payload: Mapping[str, object]) -> tuple[str, str]:
    venue_id = _string_field(payload, "venue_id", "venueId")
    scope = _string_field(payload, "observation_scope", "observationScope") or "default"
    canonical = {
        "venue_id": venue_id,
        "venue_name": _string_field(payload, "venue_name", "venueName"),
        "observation_scope": scope,
        "healthy": payload.get("healthy") is True,
        "error": str(payload.get("error") or "")[:300] or None,
        "slots": _canonical_slots(payload.get("slots")),
    }
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{venue_id}:{scope}", hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _entry_gate(entry: object) -> dict[str, Any] | None:
    if not isinstance(entry, Mapping):
        return None
    gate = entry.get("gate")
    if not isinstance(gate, Mapping):
        return None
    return {str(key): value for key, value in gate.items()}


def _empty_state() -> CacheState:
    return {"version": _STATE_VERSION, "entries": {}, "venues": {}}


def _read_state(path: Path) -> CacheState:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(value, dict):
        return _empty_state()

    raw_entries = value.get("entries")
    entries: dict[str, CacheEntry] = {}
    if isinstance(raw_entries, dict):
        for key, raw_entry in raw_entries.items():
            if not isinstance(raw_entry, Mapping):
                continue
            try:
                entries[str(key)] = {
                    "fingerprint": str(raw_entry.get("fingerprint") or ""),
                    "last_attempt_at": float(raw_entry.get("last_attempt_at") or 0),
                    "last_success_at": float(raw_entry.get("last_success_at") or 0),
                    "gate": _entry_gate(raw_entry),
                }
            except (TypeError, ValueError):
                continue

    raw_venues = value.get("venues")
    venues: dict[str, VenueHeartbeat] = {}
    if isinstance(raw_venues, dict):
        for venue_id, raw_heartbeat in raw_venues.items():
            if not isinstance(raw_heartbeat, Mapping):
                continue
            try:
                venues[str(venue_id)] = {
                    "last_attempt_at": float(raw_heartbeat.get("last_attempt_at") or 0),
                    "last_success_at": float(raw_heartbeat.get("last_success_at") or 0),
                }
            except (TypeError, ValueError):
                continue
    return {"version": _STATE_VERSION, "entries": entries, "venues": venues}


def _write_state(path: Path, state: CacheState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


@contextlib.contextmanager
def _locked_state(path: Path) -> Iterator[CacheState]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield _read_state(path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _latest_gate(state: CacheState, venue_id: str) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    prefix = f"{venue_id}:"
    for key, entry in state["entries"].items():
        if not key.startswith(prefix):
            continue
        gate = _entry_gate(entry)
        if gate is not None:
            candidates.append((entry["last_success_at"], gate))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _reserve_venue_attempt(state: CacheState, venue_id: str, current_time: float) -> None:
    heartbeat = state["venues"].setdefault(
        venue_id,
        {"last_attempt_at": 0.0, "last_success_at": 0.0},
    )
    heartbeat["last_attempt_at"] = current_time


def decide_observation_delivery(
    payload: Mapping[str, object],
    *,
    now: float | None = None,
) -> ObservationDeliveryDecision:
    current_time = time.time() if now is None else now
    venue_id = _string_field(payload, "venue_id", "venueId")
    has_available_slots = bool(_canonical_slots(payload.get("slots")))
    key, fingerprint = observation_identity(payload)
    if not observation_cache_enabled():
        return ObservationDeliveryDecision(
            "forward",
            key,
            fingerprint,
            None,
            False,
            venue_id,
        )

    path = observation_cache_path()
    try:
        with _locked_state(path) as state:
            entry = state["entries"].get(key)
            gate = _latest_gate(state, venue_id)
            if entry is None or entry["fingerprint"] != fingerprint:
                _reserve_venue_attempt(state, venue_id, current_time)
                _write_state(path, state)
                return ObservationDeliveryDecision(
                    "forward",
                    key,
                    fingerprint,
                    gate,
                    True,
                    venue_id,
                )

            heartbeat = state["venues"].setdefault(
                venue_id,
                {"last_attempt_at": 0.0, "last_success_at": 0.0},
            )
            heartbeat_seconds = _configured_seconds(
                OBSERVATION_HEARTBEAT_SECONDS_ENV,
                DEFAULT_OBSERVATION_HEARTBEAT_SECONDS,
            )
            retry_seconds = _configured_seconds(
                OBSERVATION_FAILURE_RETRY_SECONDS_ENV,
                DEFAULT_OBSERVATION_FAILURE_RETRY_SECONDS,
            )
            retry_pending = heartbeat["last_attempt_at"] > heartbeat["last_success_at"]
            if retry_pending and current_time - heartbeat["last_attempt_at"] < retry_seconds:
                action: ObservationAction = "skip_retry"
            elif has_available_slots:
                action = "forward"
                _reserve_venue_attempt(state, venue_id, current_time)
                _write_state(path, state)
            elif (
                entry["last_success_at"] > 0
                and heartbeat["last_success_at"] > 0
                and current_time - heartbeat["last_success_at"] < heartbeat_seconds
            ):
                action = "skip_success"
            else:
                action = "forward"
                _reserve_venue_attempt(state, venue_id, current_time)
                _write_state(path, state)
            return ObservationDeliveryDecision(
                action,
                key,
                fingerprint,
                gate,
                True,
                venue_id,
            )
    except OSError:
        return ObservationDeliveryDecision(
            "forward",
            key,
            fingerprint,
            None,
            False,
            venue_id,
        )


def record_observation_result(
    decision: ObservationDeliveryDecision,
    *,
    success: bool,
    gate: Mapping[str, object] | None,
    now: float | None = None,
) -> None:
    if not decision.enabled:
        return
    current_time = time.time() if now is None else now
    venue_id = decision.venue_id or decision.key.partition(":")[0]
    path = observation_cache_path()
    try:
        with _locked_state(path) as state:
            entries = state["entries"]
            current = entries.get(decision.key)
            previous_gate = _entry_gate(current) or _latest_gate(state, venue_id)
            previous_fingerprint = current["fingerprint"] if current is not None else ""
            previous_success = current["last_success_at"] if current is not None else 0.0
            normalized_gate = (
                {str(key): value for key, value in gate.items()}
                if gate is not None
                else previous_gate
            )
            entries[decision.key] = {
                "fingerprint": decision.fingerprint,
                "last_attempt_at": current_time,
                "last_success_at": (
                    current_time
                    if success
                    else previous_success
                    if previous_fingerprint == decision.fingerprint
                    else 0.0
                ),
                "gate": normalized_gate,
            }
            venue = state["venues"].setdefault(
                venue_id,
                {"last_attempt_at": 0.0, "last_success_at": 0.0},
            )
            venue["last_attempt_at"] = current_time
            if success:
                venue["last_success_at"] = current_time
            _write_state(path, state)
    except OSError:
        return


def cached_gate_for_venue(venue_id: str) -> dict[str, Any] | None:
    if not observation_cache_enabled():
        return None
    path = observation_cache_path()
    try:
        with _locked_state(path) as state:
            return _latest_gate(state, venue_id)
    except OSError:
        return None
