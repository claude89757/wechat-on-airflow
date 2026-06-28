import os
from threading import Lock

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


APP_NAME = "wechat-sender-agent"
DEFAULT_APPIUM_URL = "http://127.0.0.1:6002"
DEFAULT_DEVICE_NAME = "971bd67c0107"

app = FastAPI(title=APP_NAME)
device_lock = Lock()


class SendRequest(BaseModel):
    receiver: str = Field(min_length=1)
    messages: list[str] = Field(min_length=1)
    device_name: str = Field(min_length=1)

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


def _allowed_device_name() -> str:
    return os.getenv("WECHAT_ALLOWED_DEVICE_NAME", DEFAULT_DEVICE_NAME)


def _appium_url() -> str:
    return os.getenv("WECHAT_APPIUM_URL", DEFAULT_APPIUM_URL)


@app.exception_handler(RequestValidationError)
def validation_exception_handler(_request, _exc):
    return _json_error(400, "invalid_request", "request payload is invalid")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": APP_NAME}


@app.post("/v1/wechat/send")
def send_wechat(request: SendRequest):
    allowed_device_name = _allowed_device_name()
    if request.device_name != allowed_device_name:
        return _json_error(403, "device_not_allowed", "requested device is not allowed")

    acquired = device_lock.acquire(blocking=False)
    if not acquired:
        return _json_error(409, "device_busy", "device is already sending a message")

    try:
        result = send_text_messages(
            appium_server_url=_appium_url(),
            device_name=request.device_name,
            receiver=request.receiver,
            messages=request.messages,
            preflight_cleanup=cleanup_appium_device,
        )
        return {
            "success": result.success,
            "device_name": result.device_name,
            "receiver": result.receiver,
            "sent_count": result.sent_count,
        }
    except InvalidSendRequestError as exc:
        return _json_error(400, exc.error_code, str(exc))
    except WeChatSenderError as exc:
        status_code = 504 if exc.error_code == "appium_timeout" else 500
        return _json_error(status_code, exc.error_code, str(exc))
    finally:
        device_lock.release()
