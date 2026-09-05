from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_TRUE_VALUES: Final = {"1", "true", "yes", "on"}
_FALSE_VALUES: Final = {"0", "false", "no", "off"}
_SECRET_ROOT = Path(os.environ.get("ZACKS_SECRET_DIR", "/run/secrets"))


def _variable(name: str) -> str | None:
    """Configuration only. Durable delivery ownership lives in PostgreSQL."""
    try:
        from airflow.models.variable import Variable as OrmVariable

        value = OrmVariable.get(name, default_var=None)
    except Exception:
        return None
    if value is None:
        return None
    return str(value).strip() or None


def _first_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
        value = _variable(name)
        if value:
            return value
    return None


def _secret_file(name: str) -> str | None:
    candidates = [
        _SECRET_ROOT / name,
        Path("/etc/wechat-on-airflow/secrets") / name,
    ]
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _secret_or_value(filename: str, *names: str) -> str | None:
    return _secret_file(filename) or _first_value(*names)


def _bool_value(name: str, default: bool) -> bool:
    raw = _first_value(name)
    if raw is None:
        return default
    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _positive_int(name: str, default: int) -> int:
    raw = _first_value(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value > 0 else default


def _derived_secret(label: str) -> str:
    material = (
        _secret_file("zacks_host_master_key")
        or _secret_file("airflow_fernet_key")
        or _first_value("AIRFLOW__CORE__FERNET_KEY")
    )
    if not material:
        raise RuntimeError("host secret material is unavailable")
    digest = hashlib.sha256(f"{label}\0{material}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


@dataclass(frozen=True)
class HostCoreSettings:
    deployment_commit: str
    observation_mode: str
    delivery_owner: str
    wechat_gate_source: str
    edge_token: str
    verification_pepper: str
    invite_pepper: str
    standard_daily_email_limit: int
    priority_daily_email_limit: int
    standard_active_subscription_limit: int
    priority_active_subscription_limit: int
    notification_daily_send_limit: int
    weather_gate_enabled: bool
    weather_threshold_mm: float
    weather_latitude: float
    weather_longitude: float
    redis_url: str | None

    @property
    def host_owns_delivery(self) -> bool:
        return self.delivery_owner == "airflow_host"

    @property
    def host_observation_enabled(self) -> bool:
        return self.observation_mode in {"dual", "host"}

    @property
    def legacy_observation_enabled(self) -> bool:
        return self.observation_mode in {"dual", "cloudflare"}


@dataclass(frozen=True)
class TencentEmailSettings:
    secret_id: str
    secret_key: str
    region: str
    from_address: str
    reply_to: str
    template_id: int


def load_settings() -> HostCoreSettings:
    from .control import runtime_state

    state = runtime_state()
    observation_mode = "host"
    delivery_owner = "airflow_host" if state["delivery_enabled"] else "paused"
    gate_source = "host"

    edge_token = _secret_or_value(
        "zacks_edge_token",
        "ZACKS_EDGE_TOKEN",
        "WEBAPP_OBSERVATION_API_TOKEN",
    )
    if not edge_token:
        raise RuntimeError("Zacks edge token is unavailable")

    threshold_raw = _first_value("WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM") or "25"
    latitude_raw = _first_value("WEATHER_EMAIL_GATE_LATITUDE") or "22.5431"
    longitude_raw = _first_value("WEATHER_EMAIL_GATE_LONGITUDE") or "114.0579"
    try:
        threshold = float(threshold_raw)
    except ValueError:
        threshold = 25.0
    try:
        latitude = float(latitude_raw)
    except ValueError:
        latitude = 22.5431
    try:
        longitude = float(longitude_raw)
    except ValueError:
        longitude = 114.0579

    return HostCoreSettings(
        deployment_commit=os.environ.get("DEPLOYMENT_COMMIT", "unknown"),
        observation_mode=observation_mode,
        delivery_owner=delivery_owner,
        wechat_gate_source=gate_source,
        edge_token=edge_token,
        verification_pepper=(
            _secret_or_value("zacks_verification_pepper", "ZACKS_VERIFICATION_PEPPER")
            or _derived_secret("zacks-verification-v1")
        ),
        invite_pepper=(
            _secret_or_value("zacks_invite_pepper", "ZACKS_INVITE_PEPPER")
            or _derived_secret("zacks-invite-v1")
        ),
        standard_daily_email_limit=_positive_int("STANDARD_DAILY_EMAIL_LIMIT", 10),
        priority_daily_email_limit=_positive_int("PRIORITY_DAILY_EMAIL_LIMIT", 100),
        standard_active_subscription_limit=_positive_int("STANDARD_ACTIVE_SUBSCRIPTION_LIMIT", 5),
        priority_active_subscription_limit=_positive_int("PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT", 20),
        notification_daily_send_limit=_positive_int("NOTIFICATION_DAILY_SEND_LIMIT", 1000),
        weather_gate_enabled=_bool_value("WEATHER_EMAIL_GATE_ENABLED", True),
        weather_threshold_mm=max(threshold, 0.1),
        weather_latitude=min(max(latitude, -90.0), 90.0),
        weather_longitude=min(max(longitude, -180.0), 180.0),
        redis_url=_first_value("ZACKS_REDIS_URL"),
    )


def load_tencent_email_settings() -> TencentEmailSettings:
    secret_id = _secret_or_value(
        "tencent_secret_id",
        "TENCENT_SECRET_ID",
        "TENCENTCLOUD_SECRET_ID",
        "TENCENT_CLOUD_SECRET_ID",
    )
    secret_key = _secret_or_value(
        "tencent_secret_key",
        "TENCENT_SECRET_KEY",
        "TENCENTCLOUD_SECRET_KEY",
        "TENCENT_CLOUD_SECRET_KEY",
    )
    region = _secret_or_value("tencent_region", "TENCENT_REGION") or "ap-guangzhou"
    from_address = _secret_or_value(
        "email_from_address",
        "EMAIL_FROM_ADDRESS",
        "TENCENT_EMAIL_FROM_ADDRESS",
    )
    reply_to = _secret_or_value(
        "email_reply_to",
        "EMAIL_REPLY_TO",
        "TENCENT_EMAIL_REPLY_TO",
    )
    template_raw = _secret_or_value(
        "email_template_id",
        "EMAIL_TEMPLATE_ID",
        "TENCENT_EMAIL_TEMPLATE_ID",
    )
    missing = [
        name
        for name, value in {
            "secret_id": secret_id,
            "secret_key": secret_key,
            "from_address": from_address,
            "reply_to": reply_to,
            "template_id": template_raw,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Tencent SES host credentials are incomplete: " + ",".join(missing))
    try:
        template_id = int(str(template_raw))
    except ValueError as exc:
        raise RuntimeError("Tencent SES template ID is invalid") from exc
    if template_id <= 0:
        raise RuntimeError("Tencent SES template ID is invalid")
    return TencentEmailSettings(
        secret_id=str(secret_id),
        secret_key=str(secret_key),
        region=str(region),
        from_address=str(from_address),
        reply_to=str(reply_to),
        template_id=template_id,
    )
