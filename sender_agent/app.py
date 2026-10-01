import hashlib
import json
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Timer
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from sender_agent import ledger
from sender_agent.device_lease import DeviceLease
from wechat_sender import (
    InvalidSendRequestError,
    WeChatSenderError,
    cleanup_appium_device,
    send_text_messages,
)
from wechat_sender.appium_text_sender import SendProgress

APP_NAME = "wechat-sender-agent"
DEFAULT_APPIUM_URL = "http://127.0.0.1:6002"
DEVICE_LOCK_WAIT_SECONDS = 150


@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        reset_runtime_state()


app = FastAPI(title=APP_NAME, lifespan=lifespan)
device_lock = Lock()
_warm_operator = None
_warm_appium_url = ""
_device_lease = None
_warm_idle_timer = None
_warm_generation = 0


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


def _busy_before_submission(message: str) -> JSONResponse:
    # Only use before ledger.claim or any UI submission for this request.
    return JSONResponse(
        status_code=409,
        content={
            "success": False,
            "error": "device_busy",
            "message": message,
            "submission_state": "not_submitted",
            "safe_to_retry": True,
            "sent_count": 0,
        },
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
    with device_lock:
        _discard_warm_operator()


def _discard_warm_operator() -> None:
    global _warm_operator, _warm_appium_url, _device_lease
    _cancel_warm_idle_timer()
    operator = _warm_operator
    _warm_operator = None
    _warm_appium_url = ""
    try:
        if operator is not None:
            operator.close()
    except Exception:
        pass
    finally:
        if _device_lease is not None:
            _device_lease.release()
            _device_lease = None


def _cancel_warm_idle_timer() -> None:
    global _warm_idle_timer, _warm_generation
    _warm_generation += 1
    timer, _warm_idle_timer = _warm_idle_timer, None
    if timer is not None:
        timer.cancel()


def _expire_warm_operator(generation: int) -> None:
    # Never close an operator in the middle of a send. A new request cancels
    # the timer under this same mutex, and its finally block rearms it.
    with device_lock:
        if generation == _warm_generation:
            _discard_warm_operator()


def _arm_warm_idle_timer() -> None:
    global _warm_idle_timer
    _cancel_warm_idle_timer()
    if _warm_operator is None:
        return
    try:
        seconds = min(max(float(os.getenv("WECHAT_WARM_IDLE_SECONDS", "5")), 0.1), 30)
    except ValueError:
        seconds = 5.0
    timer = Timer(seconds, _expire_warm_operator, args=(_warm_generation,))
    timer.daemon = True
    _warm_idle_timer = timer
    timer.start()


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
    return {
        "ok": configured,
        "service": APP_NAME,
        "configured": configured,
        "deploymentCommit": os.environ.get("DEPLOYMENT_COMMIT", "unknown"),
        "durableIdempotency": ledger.ready(),
    }


@app.get("/readyz")
def readyz():
    if not _allowed_device_name() or not _appium_url():
        return _json_error(503, "service_misconfigured", "sender is not configured")
    lock_directory = os.getenv("WECHAT_DEVICE_LOCK_DIR", "/run/wechat-device")
    if not os.access(lock_directory, os.W_OK | os.X_OK):
        return _json_error(503, "device_lock_unavailable", "shared phone lock is not writable")

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
    if not ledger.ready():
        return _json_error(503, "ledger_unavailable", "durable sender ledger is unavailable")
    return {
        "ok": True,
        "deploymentCommit": os.environ.get("DEPLOYMENT_COMMIT", "unknown"),
        "durableIdempotency": True,
        "service": APP_NAME,
        "appium_ready": True,
        "device_ready": True,
    }


class StatusRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=256)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


@app.post("/v1/wechat/status")
def send_status(request: StatusRequest):
    """Read ledger evidence only. Missing/unknown is never permission to resend."""
    if not device_lock.acquire(blocking=False):
        return _json_error(409, "device_busy", "sender currently processing")
    try:
        return ledger.lookup(request.idempotency_key, request.payload_hash)
    except Exception:
        return _json_error(503, "ledger_unavailable", "durable sender ledger is unavailable")
    finally:
        device_lock.release()


@app.post("/v1/wechat/send")
def send_wechat(request: SendRequest):
    global _warm_operator, _warm_appium_url, _device_lease
    allowed_device_name = _allowed_device_name()
    if not allowed_device_name:
        return _json_error(
            503,
            "service_misconfigured",
            "allowed device is not configured",
        )
    if request.device_name != allowed_device_name:
        return _json_error(403, "device_not_allowed", "requested device is not allowed")

    acquired = device_lock.acquire(timeout=DEVICE_LOCK_WAIT_SECONDS)
    if not acquired:
        return _busy_before_submission("device queue wait timed out")

    _cancel_warm_idle_timer()
    try:
        canonical = json.dumps(
            {
                "device": request.device_name,
                "receiver": request.receiver,
                "messages": request.messages,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        key = request.idempotency_key or payload_hash
        appium_url = _appium_url()
        existing_operator = _usable_warm_operator(request.device_name, appium_url)
        # Every create/reset/cleanup and retained warm session owns the same
        # kernel lock as the reader. Busy is rejected before claiming the job.
        if _device_lease is None:
            lease = DeviceLease(request.device_name)
            if not lease.acquire(timeout=5):
                return _busy_before_submission("phone is owned by another worker")
            _device_lease = lease
        try:
            phase, cached = ledger.claim(key, payload_hash, preparing=True)
        except Exception:
            return _json_error(503, "ledger_unavailable", "durable sender ledger is unavailable")
        if phase == "sent":
            return cached
        if phase == "conflict":
            return _json_error(
                409, "idempotency_conflict", "idempotency key has a different payload"
            )
        if phase != "claimed":
            return _json_error(
                409, "submission_unknown", "previous UI outcome requires reconciliation"
            )

        progress = SendProgress(before_submit=lambda: ledger.mark_submitting(key))
        try:
            result = send_text_messages(
                appium_server_url=appium_url,
                device_name=request.device_name,
                receiver=request.receiver,
                messages=request.messages,
                existing_operator=existing_operator,
                close_operator=False,
                progress=progress,
                preflight_cleanup=None if existing_operator else cleanup_appium_device,
                startup_wait_seconds=0 if existing_operator else 1.0,
            )
        except Exception as exc:
            _discard_warm_operator()
            code = exc.error_code if isinstance(exc, WeChatSenderError) else "send_failed"
            outcome = "submission_unknown" if progress.submission_started else "not_submitted"
            payload = {
                "success": False,
                "error": code,
                "message": "sender outcome requires reconciliation"
                if progress.submission_started
                else "sender failed before submission",
                "submission_state": outcome,
                "safe_to_retry": not progress.submission_started,
                "sent_count": progress.confirmed_count,
            }
            ledger.finish(key, outcome, payload)
            return JSONResponse(
                status_code=504 if code == "appium_timeout" else 500, content=payload
            )

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
        ledger.finish(key, "sent" if result.success else "submission_unknown", payload)
        return payload
    except InvalidSendRequestError as exc:
        return _json_error(400, exc.error_code, str(exc))
    except WeChatSenderError as exc:
        status_code = 504 if exc.error_code == "appium_timeout" else 500
        return _json_error(status_code, exc.error_code, str(exc))
    except Exception:
        return _json_error(500, "submission_unknown", "send result requires reconciliation")
    finally:
        if _warm_operator is None:
            _discard_warm_operator()
        else:
            _arm_warm_idle_timer()
        device_lock.release()
