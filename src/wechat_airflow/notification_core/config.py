from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit


def _airflow_variable(name: str, default: str = "") -> str:
    """Read an Airflow Variable without making the module require Airflow in tests."""
    try:
        from airflow.sdk import Variable

        value = Variable.get(name, default=default)
    except Exception:
        return default
    return str(value or default).strip()


def _value(name: str, *, variable: str | None = None, default: str = "") -> str:
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    return _airflow_variable(variable or name, default)


def _positive_int(name: str, *, variable: str | None = None, default: int) -> int:
    raw = _value(name, variable=variable, default=str(default))
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(name: str, *, variable: str | None = None, default: float) -> float:
    raw = _value(name, variable=variable, default=str(default))
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _boolean(name: str, *, variable: str | None = None, default: bool) -> bool:
    raw = _value(name, variable=variable, default="true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _secret_file(name: str) -> str:
    secret_dir = Path(os.environ.get("AIRFLOW_SECRET_DIR", "/run/secrets"))
    candidate = secret_dir / name
    try:
        return candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _database_url() -> str:
    explicit = os.environ.get("ZACKS_CORE_DATABASE_URL", "").strip()
    if explicit:
        return explicit

    username = os.environ.get("AIRFLOW_DATABASE_USERNAME", "airflow").strip() or "airflow"
    database = os.environ.get("AIRFLOW_DATABASE_NAME", "airflow").strip() or "airflow"
    host = os.environ.get("ZACKS_CORE_DATABASE_HOST", "postgresql").strip() or "postgresql"
    port = os.environ.get("ZACKS_CORE_DATABASE_PORT", "5432").strip() or "5432"
    password = os.environ.get("AIRFLOW_DATABASE_PASSWORD", "").strip()
    if not password:
        password = _secret_file("airflow_database_password")
    if not password:
        raise RuntimeError("notification core database password is not configured")
    return (
        "postgresql+psycopg2://"
        f"{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )


def _snapshot_url() -> str:
    explicit = _value("ZACKS_SUBSCRIPTION_SNAPSHOT_URL")
    if explicit:
        return explicit

    observation_url = _airflow_variable("WEBAPP_OBSERVATION_API_URL", "")
    if not observation_url:
        return ""
    parts = urlsplit(observation_url)
    return urlunsplit((parts.scheme, parts.netloc, "/api/internal/subscription-snapshot", "", ""))


@dataclass(frozen=True)
class NotificationCoreSettings:
    database_url: str
    schema: str
    ingest_token: str
    redis_url: str
    subscription_snapshot_url: str
    subscription_snapshot_token: str
    subscription_sync_seconds: int
    worker_idle_seconds: float
    api_host: str
    api_port: int
    tencent_secret_id: str
    tencent_secret_key: str
    tencent_region: str
    email_from_address: str
    email_reply_to: str
    email_template_id: int
    global_daily_email_limit: int
    standard_daily_email_limit: int
    priority_daily_email_limit: int
    weather_gate_enabled: bool
    weather_precipitation_threshold_mm: float
    weather_latitude: float
    weather_longitude: float

    @property
    def email_delivery_configured(self) -> bool:
        return all(
            (
                self.tencent_secret_id,
                self.tencent_secret_key,
                self.tencent_region,
                self.email_from_address,
                self.email_reply_to,
                self.email_template_id > 0,
            )
        )


def load_settings() -> NotificationCoreSettings:
    schema = os.environ.get("ZACKS_CORE_SCHEMA", "zacks_core").strip() or "zacks_core"
    if not schema.replace("_", "").isalnum():
        raise RuntimeError("ZACKS_CORE_SCHEMA must contain only letters, digits, and underscores")

    ingest_token = _value(
        "ZACKS_CORE_INGEST_TOKEN",
        variable="WEBAPP_OBSERVATION_API_TOKEN",
    )
    return NotificationCoreSettings(
        database_url=_database_url(),
        schema=schema,
        ingest_token=ingest_token,
        redis_url=os.environ.get("ZACKS_CORE_REDIS_URL", "redis://redis:6379/1").strip(),
        subscription_snapshot_url=_snapshot_url(),
        subscription_snapshot_token=_value(
            "ZACKS_SUBSCRIPTION_SNAPSHOT_TOKEN",
            variable="WEBAPP_OBSERVATION_API_TOKEN",
        ),
        subscription_sync_seconds=_positive_int(
            "ZACKS_SUBSCRIPTION_SYNC_SECONDS", default=300
        ),
        worker_idle_seconds=_positive_float("ZACKS_CORE_WORKER_IDLE_SECONDS", default=2.0),
        api_host=os.environ.get("ZACKS_CORE_API_HOST", "0.0.0.0").strip() or "0.0.0.0",
        api_port=_positive_int("ZACKS_CORE_API_PORT", default=8091),
        tencent_secret_id=_value("TENCENT_SECRET_ID"),
        tencent_secret_key=_value("TENCENT_SECRET_KEY"),
        tencent_region=_value("TENCENT_REGION", default="ap-guangzhou"),
        email_from_address=_value("EMAIL_FROM_ADDRESS"),
        email_reply_to=_value("EMAIL_REPLY_TO"),
        email_template_id=_positive_int("EMAIL_TEMPLATE_ID", default=0),
        global_daily_email_limit=_positive_int(
            "NOTIFICATION_DAILY_SEND_LIMIT", default=1000
        ),
        standard_daily_email_limit=_positive_int(
            "STANDARD_DAILY_EMAIL_LIMIT", default=10
        ),
        priority_daily_email_limit=_positive_int(
            "PRIORITY_DAILY_EMAIL_LIMIT", default=100
        ),
        weather_gate_enabled=_boolean("WEATHER_EMAIL_GATE_ENABLED", default=True),
        weather_precipitation_threshold_mm=_positive_float(
            "WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM", default=25.0
        ),
        weather_latitude=float(_value("WEATHER_EMAIL_GATE_LATITUDE", default="22.5431")),
        weather_longitude=float(_value("WEATHER_EMAIL_GATE_LONGITUDE", default="114.0579")),
    )
