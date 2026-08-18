import json
import os
import subprocess
import time
from pathlib import Path
from threading import Lock
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from wechat_sender import (
    InvalidSendRequestError,
    WeChatSenderError,
    cleanup_appium_device,
    send_text_messages,
)

IDEMPOTENCY_TTL_SECONDS = 600
IDEMPOTENCY_CACHE_LIMIT = 256

APP_NAME = "wechat-sender-agent"
DEFAULT_APPIUM_URL = "http://127.0.0.1:6002"
DEVICE_LOCK_WAIT_SECONDS = 70

app = FastAPI(title=APP_NAME)
device_lock = Lock()
_warm_operator = None
_warm_appium_url = ""
_recent_sends: dict[str, tuple[float, dict]] = {}


class SendRequest(BaseModel):
    receiver: str = Field(min_length=1)
    messages: list[str] = Field(min_length=1)
    device_name: str = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)

    @field_validator("receiver", "device_name")
    @classmethod
    def non_blank_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("messages")
    @classmethod
    def non_blank_messages(cls, value: list[str]) -> list[str]:
        if any(not isinstance(message, str) or not message.strip() for message in value):
            raise ValueError("messages must contain only non-empty strings")
        return value


def _json_error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": error, "message": message},
    )


def _runtime_setting(environment_name: str, credential_name: str, default: str = "") -> str:
    environment_value = os.getenv(environment_name, "").strip()
    if environment_value:
        return environment_value
    credential_directory = os.getenv("CREDENTIALS_DIRECTORY", "").strip()
    if not credential_directory:
        return default
    try:
        value = (Path(credential_directory) / credential_name).read_text(encoding="utf-8")
    except OSError:
        return default
    return value.strip() or default


def _allowed_device_name() -> str:
    return _runtime_setting("WECHAT_ALLOWED_DEVICE_NAME", "wechat_allowed_device_name")


def _appium_url() -> str:
    return _runtime_setting("WECHAT_APPIUM_URL", "wechat_appium_url", DEFAULT_APPIUM_URL)


def _run_adb(
    device_name: str,
    *arguments: str,
    timeout: int = 8,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", device_name, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _device_readiness(device_name: str) -> tuple[bool, str | None]:
    try:
        state = _run_adb(device_name, "get-state")
        if state.returncode != 0 or state.stdout.strip() != "device":
            return False, "adb_device_offline"

        boot = _run_adb(device_name, "shell", "getprop", "sys.boot_completed")
        if boot.returncode != 0 or boot.stdout.strip() != "1":
            return False, "android_not_booted"

        wechat = _run_adb(device_name, "shell", "pm", "path", "com.tencent.mm")
        if wechat.returncode != 0 or not wechat.stdout.strip().startswith("package:"):
            return False, "wechat_not_installed"
    except (OSError, subprocess.TimeoutExpired):
        return False, "adb_unavailable"
    return True, None


def reset_runtime_state() -> None:
    global _warm_operator, _warm_appium_url
    _discard_warm_operator()
    _recent_sends.clear()


def _discard_warm_operator() -> None:
    global _warm_operator, _warm_appium_url
    operator = _warm_operator
    _warm_operator = None
    _warm_appium_url = ""
    if operator is None:
        return
    try:
        operator.close()
    except Exception:
        return


def _cached_send(idempotency_key: str | None) -> dict | None:
    if not idempotency_key:
        return None
    cached = _recent_sends.get(idempotency_key)
    if cached is None:
        return None
    cached_at, payload = cached
    if time.monotonic() - cached_at > IDEMPOTENCY_TTL_SECONDS:
        _recent_sends.pop(idempotency_key, None)
        return None
    return payload


def _remember_send(idempotency_key: str | None, payload: dict) -> None:
    if not idempotency_key:
        return
    _recent_sends[idempotency_key] = (time.monotonic(), payload)
    extra = len(_recent_sends) - IDEMPOTENCY_CACHE_LIMIT
    if extra <= 0:
        return
    oldest = sorted(_recent_sends.items(), key=lambda item: item[1][0])[:extra]
    for key, _value in oldest:
        _recent_sends.pop(key, None)


def _usable_warm_operator(device_name: str, appium_url: str):
    operator = _warm_operator
    if operator is None:
        return None
    if _warm_appium_url != appium_url or getattr(operator, "device_name", None) != device_name:
        _discard_warm_operator()
        return None
    return operator


@app.exception_handler(RequestValidationError)
def validation_exception_handler(_request, _exc):
    return _json_error(400, "invalid_request", "request payload is invalid")


@app.get("/healthz")
def healthz():
    configured = bool(_allowed_device_name() and _appium_url())
    return {"ok": configured, "service": APP_NAME, "configured": configured}


@app.get("/readyz")
def readyz():
    if not _allowed_device_name() or not _appium_url():
        return _json_error(503, "service_misconfigured", "sender is not configured")

    try:
        with urlopen(f"{_appium_url().rstrip('/')}/status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            value = payload.get("value") if isinstance(payload, dict) else None
            ready = (
                response.status == 200 and isinstance(value, dict) and value.get("ready") is True
            )
    except Exception as exc:
        return _json_error(
            503,
            "appium_unavailable",
            f"Appium readiness check failed: {type(exc).__name__}",
        )

    if not ready:
        return _json_error(503, "appium_not_ready", "Appium is not ready")

    device_ready, reason = _device_readiness(_allowed_device_name())
    if not device_ready:
        return _json_error(
            503,
            "device_not_ready",
            f"Android device readiness check failed: {reason}",
        )
    return {
        "ok": True,
        "service": APP_NAME,
        "appium_ready": True,
        "device_ready": True,
    }


@app.post("/v1/wechat/send")
def send_wechat(request: SendRequest):
    global _warm_operator, _warm_appium_url
    allowed_device_name = _allowed_device_name()
    if not allowed_device_name:
        return _json_error(
            503,
            "service_misconfigured",
            "allowed device is not configured",
        )
    if request.device_name != allowed_device_name:
        return _json_error(403, "device_not_allowed", "requested device is not allowed")

    cached = _cached_send(request.idempotency_key)
    if cached is not None:
        return cached

    acquired = device_lock.acquire(timeout=DEVICE_LOCK_WAIT_SECONDS)
    if not acquired:
        return _json_error(409, "device_busy", "device queue wait timed out")

    try:
        cached = _cached_send(request.idempotency_key)
        if cached is not None:
            return cached

        appium_url = _appium_url()
        existing_operator = _usable_warm_operator(request.device_name, appium_url)
        try:
            result = send_text_messages(
                appium_server_url=appium_url,
                device_name=request.device_name,
                receiver=request.receiver,
                messages=request.messages,
                existing_operator=existing_operator,
                close_operator=False,
                preflight_cleanup=None if existing_operator else cleanup_appium_device,
                startup_wait_seconds=0 if existing_operator else 1.0,
            )
        except Exception:
            _discard_warm_operator()
            raise

        _warm_operator = result.operator
        _warm_appium_url = appium_url
        payload = {
            "success": result.success,
            "device_name": result.device_name,
            "receiver": result.receiver,
            "sent_count": result.sent_count,
            "navigation_path": result.navigation_path,
            "session_reused": result.session_reused,
        }
        _remember_send(request.idempotency_key, payload)
        return payload
    except InvalidSendRequestError as exc:
        return _json_error(400, exc.error_code, str(exc))
    except WeChatSenderError as exc:
        status_code = 504 if exc.error_code == "appium_timeout" else 500
        return _json_error(status_code, exc.error_code, str(exc))
    finally:
        device_lock.release()
