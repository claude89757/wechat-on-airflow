# WeChat Cloudflare Send Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a synchronous remote WeChat text-send service with Cloudflare as the public API gateway and a FastAPI sender-agent on `47.115.144.127`.

**Architecture:** Cloudflare Worker validates public requests and forwards them to a token-protected sender-agent. The sender-agent runs beside Appium, serializes access to device `971bd67c0107`, and uses an Airflow-free Appium text sender to control WeChat. The first version has no queue or persistent job store.

**Tech Stack:** Python 3, FastAPI, Uvicorn, Appium Python Client, Selenium, unittest, TypeScript, Cloudflare Workers, Wrangler, Vitest.

---

## File Structure

- Create `wechat_sender/__init__.py`: public Python API for the extracted sender module.
- Create `wechat_sender/appium_text_sender.py`: Airflow-free Appium text sender with structured results and exceptions.
- Create `sender_agent/__init__.py`: package marker for the agent service.
- Create `sender_agent/app.py`: FastAPI app exposing `POST /v1/wechat/send`.
- Create `cloudflare/wechat-worker/package.json`: Worker project scripts and dev dependencies.
- Create `cloudflare/wechat-worker/tsconfig.json`: TypeScript configuration.
- Create `cloudflare/wechat-worker/wrangler.jsonc`: Worker deployment configuration and required secrets declaration.
- Create `cloudflare/wechat-worker/src/index.ts`: Cloudflare Worker gateway.
- Create `cloudflare/wechat-worker/test/index.test.ts`: Worker unit tests.
- Create `tests/wechat_sender_test.py`: unit tests for the Appium-free sender wrapper using fake operators.
- Create `tests/sender_agent_test.py`: FastAPI agent tests using `TestClient`.
- Create `docs/wechat-cloudflare-send-service.md`: runtime setup, environment variables, and smoke test commands.

The repository `.gitignore` ignores files named `test_*.py`; new Python tests use `*_test.py` names so they are tracked without changing ignore rules.

---

### Task 1: Extract Airflow-Free Appium Text Sender

**Files:**
- Create: `wechat_sender/__init__.py`
- Create: `wechat_sender/appium_text_sender.py`
- Test: `tests/wechat_sender_test.py`

- [ ] **Step 1: Write the failing sender tests**

Create `tests/wechat_sender_test.py`:

```python
import unittest

from wechat_sender.appium_text_sender import (
    InvalidSendRequestError,
    SendFailedError,
    SendResult,
    send_text_messages,
)


class FakeOperator:
    created = []

    def __init__(self, appium_server_url, device_name, force_app_launch=False):
        self.appium_server_url = appium_server_url
        self.device_name = device_name
        self.force_app_launch = force_app_launch
        self.closed = False
        self.sent = []
        self.at_main_page = not force_app_launch
        FakeOperator.created.append(self)

    def is_at_main_page(self):
        return self.at_main_page

    def send_message(self, receiver, messages):
        self.sent.append((receiver, list(messages)))

    def close(self):
        self.closed = True


class RestartingFakeOperator(FakeOperator):
    def __init__(self, appium_server_url, device_name, force_app_launch=False):
        super().__init__(appium_server_url, device_name, force_app_launch)
        self.at_main_page = force_app_launch


class FailingOperator(FakeOperator):
    def send_message(self, receiver, messages):
        raise RuntimeError("send button missing")


class WeChatSenderTest(unittest.TestCase):
    def setUp(self):
        FakeOperator.created = []

    def test_send_text_messages_returns_structured_result(self):
        result = send_text_messages(
            appium_server_url="http://47.115.144.127:6002",
            device_name="971bd67c0107",
            receiver="文件传输助手",
            messages=["hello", "world"],
            operator_factory=FakeOperator,
            startup_wait_seconds=0,
            restart_wait_seconds=0,
        )

        self.assertEqual(
            result,
            SendResult(
                success=True,
                device_name="971bd67c0107",
                receiver="文件传输助手",
                sent_count=2,
            ),
        )
        self.assertEqual(FakeOperator.created[0].sent, [("文件传输助手", ["hello", "world"])])
        self.assertTrue(FakeOperator.created[0].closed)

    def test_restarts_wechat_when_initial_session_is_not_at_main_page(self):
        result = send_text_messages(
            appium_server_url="http://47.115.144.127:6002",
            device_name="971bd67c0107",
            receiver="文件传输助手",
            messages=["hello"],
            operator_factory=RestartingFakeOperator,
            startup_wait_seconds=0,
            restart_wait_seconds=0,
        )

        self.assertTrue(result.success)
        self.assertEqual(len(FakeOperator.created), 2)
        self.assertFalse(FakeOperator.created[0].force_app_launch)
        self.assertTrue(FakeOperator.created[0].closed)
        self.assertTrue(FakeOperator.created[1].force_app_launch)
        self.assertEqual(FakeOperator.created[1].sent, [("文件传输助手", ["hello"])])

    def test_invalid_messages_raise_invalid_request(self):
        with self.assertRaises(InvalidSendRequestError) as error:
            send_text_messages(
                appium_server_url="http://47.115.144.127:6002",
                device_name="971bd67c0107",
                receiver="文件传输助手",
                messages=[""],
                operator_factory=FakeOperator,
                startup_wait_seconds=0,
                restart_wait_seconds=0,
            )

        self.assertEqual(error.exception.error_code, "invalid_request")

    def test_underlying_send_failure_is_raised(self):
        with self.assertRaises(SendFailedError) as error:
            send_text_messages(
                appium_server_url="http://47.115.144.127:6002",
                device_name="971bd67c0107",
                receiver="文件传输助手",
                messages=["hello"],
                operator_factory=FailingOperator,
                startup_wait_seconds=0,
                restart_wait_seconds=0,
            )

        self.assertEqual(error.exception.error_code, "send_failed")
        self.assertIn("send button missing", str(error.exception))
        self.assertTrue(FakeOperator.created[0].closed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the sender tests to verify they fail**

Run:

```bash
python -m unittest discover -s tests -p '*_test.py' -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wechat_sender'`.

- [ ] **Step 3: Implement the Airflow-free sender module**

Create `wechat_sender/__init__.py`:

```python
from .appium_text_sender import (
    AppiumTimeoutError,
    ContactNotFoundError,
    DeviceNotReadyError,
    InvalidSendRequestError,
    SendFailedError,
    SendResult,
    TextWeChatOperator,
    WeChatSenderError,
    send_text_messages,
)

__all__ = [
    "AppiumTimeoutError",
    "ContactNotFoundError",
    "DeviceNotReadyError",
    "InvalidSendRequestError",
    "SendFailedError",
    "SendResult",
    "TextWeChatOperator",
    "WeChatSenderError",
    "send_text_messages",
]
```

Create `wechat_sender/appium_text_sender.py`:

```python
import random
import time
from dataclasses import dataclass
from typing import Callable, Iterable


class WeChatSenderError(Exception):
    error_code = "send_failed"


class InvalidSendRequestError(WeChatSenderError):
    error_code = "invalid_request"


class DeviceNotReadyError(WeChatSenderError):
    error_code = "wechat_not_ready"


class ContactNotFoundError(WeChatSenderError):
    error_code = "contact_not_found"


class AppiumTimeoutError(WeChatSenderError):
    error_code = "appium_timeout"


class SendFailedError(WeChatSenderError):
    error_code = "send_failed"


@dataclass(frozen=True)
class SendResult:
    success: bool
    device_name: str
    receiver: str
    sent_count: int


class TextWeChatOperator:
    def __init__(
        self,
        appium_server_url: str,
        device_name: str,
        force_app_launch: bool = False,
    ):
        from appium.options.android import UiAutomator2Options
        from appium.webdriver.webdriver import WebDriver as AppiumWebDriver

        capabilities = {
            "platformName": "Android",
            "automationName": "uiautomator2",
            "udid": device_name,
            "appPackage": "com.tencent.mm",
            "appActivity": ".ui.LauncherUI",
            "noReset": True,
            "fullReset": False,
            "forceAppLaunch": force_app_launch,
            "autoGrantPermissions": True,
            "newCommandTimeout": 60,
            "resetKeyboard": True,
            "adbExecTimeout": 60000,
        }
        self.device_name = device_name
        self.driver = AppiumWebDriver(
            command_executor=appium_server_url,
            options=UiAutomator2Options().load_capabilities(capabilities),
        )

    def send_message(self, receiver: str, messages: list[str]) -> None:
        from appium.webdriver.common.appiumby import AppiumBy
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if not messages:
            raise InvalidSendRequestError("messages must contain at least one item")

        if not self.is_contact_in_recent_chats(receiver):
            try:
                search_btn = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "搜索"))
                )
                search_btn.click()
                search_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (AppiumBy.XPATH, "//android.widget.EditText[@text='搜索']")
                    )
                )
                search_input.send_keys(receiver)
                contact = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (AppiumBy.XPATH, f"//android.widget.TextView[@text='{receiver}']")
                    )
                )
                contact.click()
            except TimeoutException as exc:
                raise ContactNotFoundError(f"receiver not found: {receiver}") from exc

        for index, message in enumerate(messages):
            try:
                message_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.EditText"))
                )
                message_input.send_keys(message)
                send_btn = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[@text='发送']",
                )
                send_btn.click()
                if index < len(messages) - 1:
                    time.sleep(random.uniform(0.3, 3))
            except TimeoutException as exc:
                raise AppiumTimeoutError("timed out waiting for WeChat input") from exc
            except Exception as exc:
                raise SendFailedError(str(exc)) from exc

        self.return_to_chats()

    def is_contact_in_recent_chats(self, receiver: str) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        if not self.is_at_main_page():
            self.return_to_chats()
            time.sleep(1)

        for attempt in range(5):
            contact_elements = self.driver.find_elements(
                by=AppiumBy.XPATH,
                value=f"//android.view.View[@text='{receiver}']",
            )
            if len(contact_elements) > 1:
                raise ContactNotFoundError(f"multiple recent chats named {receiver}")
            if contact_elements:
                contact_elements[0].click()
                time.sleep(1)
                return True
            if attempt < 4:
                self.scroll_down()
                time.sleep(0.5)
        return False

    def scroll_down(self, start: float = 0.8, end: float = 0.2) -> None:
        screen_size = self.driver.get_window_size()
        start_x = screen_size["width"] * 0.5
        start_y = screen_size["height"] * start
        end_y = screen_size["height"] * end
        self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
        time.sleep(0.5)

    def return_to_chats(self) -> None:
        from appium.webdriver.common.appiumby import AppiumBy

        for _ in range(5):
            try:
                back_btn = self.driver.find_element(
                    by=AppiumBy.ID,
                    value="com.tencent.mm:id/g",
                )
                back_btn.click()
                time.sleep(0.5)
                if self.is_at_main_page():
                    return
            except Exception:
                break

        self.driver.press_keycode(4)
        time.sleep(0.5)
        if not self.is_at_main_page():
            raise DeviceNotReadyError("unable to return to WeChat main page")

    def is_at_main_page(self) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        required_xpaths = [
            "//android.widget.TextView[@text='微信']",
            "//android.widget.TextView[@text='通讯录']",
            "//android.widget.TextView[@text='发现']",
            "//android.widget.TextView[@text='我']",
        ]
        try:
            for xpath in required_xpaths:
                self.driver.find_element(AppiumBy.XPATH, xpath)
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self.driver:
            self.driver.quit()


def _validate_send_request(
    appium_server_url: str,
    device_name: str,
    receiver: str,
    messages: Iterable[str],
) -> list[str]:
    if not isinstance(appium_server_url, str) or not appium_server_url.strip():
        raise InvalidSendRequestError("appium_server_url is required")
    if not isinstance(device_name, str) or not device_name.strip():
        raise InvalidSendRequestError("device_name is required")
    if not isinstance(receiver, str) or not receiver.strip():
        raise InvalidSendRequestError("receiver is required")
    if isinstance(messages, str):
        raise InvalidSendRequestError("messages must be a list of strings")

    normalized = []
    for message in messages:
        if not isinstance(message, str) or not message.strip():
            raise InvalidSendRequestError("messages must be non-empty strings")
        normalized.append(message)
    if not normalized:
        raise InvalidSendRequestError("messages must contain at least one item")
    return normalized


def send_text_messages(
    appium_server_url: str,
    device_name: str,
    receiver: str,
    messages: Iterable[str],
    operator_factory: Callable[..., TextWeChatOperator] = TextWeChatOperator,
    startup_wait_seconds: float = 1.0,
    restart_wait_seconds: float = 3.0,
) -> SendResult:
    normalized_messages = _validate_send_request(
        appium_server_url=appium_server_url,
        device_name=device_name,
        receiver=receiver,
        messages=messages,
    )

    operator = None
    try:
        operator = operator_factory(
            appium_server_url=appium_server_url,
            device_name=device_name,
            force_app_launch=False,
        )
        time.sleep(startup_wait_seconds)
        if not operator.is_at_main_page():
            operator.close()
            operator = operator_factory(
                appium_server_url=appium_server_url,
                device_name=device_name,
                force_app_launch=True,
            )
            time.sleep(restart_wait_seconds)
            if not operator.is_at_main_page():
                raise DeviceNotReadyError("WeChat main page is not available")

        operator.send_message(receiver=receiver, messages=normalized_messages)
        return SendResult(
            success=True,
            device_name=device_name,
            receiver=receiver,
            sent_count=len(normalized_messages),
        )
    except WeChatSenderError:
        raise
    except Exception as exc:
        raise SendFailedError(str(exc)) from exc
    finally:
        if operator:
            operator.close()
```

- [ ] **Step 4: Run the sender tests to verify they pass**

Run:

```bash
python -m unittest discover -s tests -p '*_test.py' -v
```

Expected: PASS for `tests.wechat_sender_test`.

- [ ] **Step 5: Commit the sender extraction**

Run:

```bash
git add wechat_sender tests/wechat_sender_test.py
git commit -m "feat: extract appium wechat text sender"
```

---

### Task 2: Implement The Sender-Agent HTTP Service

**Files:**
- Create: `sender_agent/__init__.py`
- Create: `sender_agent/app.py`
- Test: `tests/sender_agent_test.py`

- [ ] **Step 1: Write failing FastAPI agent tests**

Create `tests/sender_agent_test.py`:

```python
import os
import unittest
from unittest.mock import patch

os.environ["WECHAT_AGENT_TOKEN"] = "agent-secret"

from fastapi.testclient import TestClient

from sender_agent.app import app
from wechat_sender import SendFailedError, SendResult


class SenderAgentTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer agent-secret"}

    @patch("sender_agent.app.send_text_messages")
    def test_send_success(self, mock_send):
        mock_send.return_value = SendResult(
            success=True,
            device_name="971bd67c0107",
            receiver="文件传输助手",
            sent_count=1,
        )

        response = self.client.post(
            "/v1/wechat/send",
            headers=self.headers,
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "device_name": "971bd67c0107",
                "receiver": "文件传输助手",
                "sent_count": 1,
            },
        )
        mock_send.assert_called_once()

    def test_rejects_missing_token(self):
        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "unauthorized")

    def test_rejects_wrong_device(self):
        response = self.client.post(
            "/v1/wechat/send",
            headers=self.headers,
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "other-device",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "device_not_allowed")

    def test_rejects_invalid_messages(self):
        response = self.client.post(
            "/v1/wechat/send",
            headers=self.headers,
            json={
                "receiver": "文件传输助手",
                "messages": [],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_request")

    @patch("sender_agent.app.device_lock")
    def test_returns_device_busy_when_lock_is_held(self, mock_lock):
        mock_lock.acquire.return_value = False

        response = self.client.post(
            "/v1/wechat/send",
            headers=self.headers,
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "device_busy")

    @patch("sender_agent.app.send_text_messages")
    def test_maps_sender_failure(self, mock_send):
        mock_send.side_effect = SendFailedError("send button missing")

        response = self.client.post(
            "/v1/wechat/send",
            headers=self.headers,
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "send_failed")
        self.assertIn("send button missing", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the agent tests to verify they fail**

Run:

```bash
python -m unittest tests/sender_agent_test.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sender_agent'`.

- [ ] **Step 3: Implement the FastAPI sender-agent**

Create `sender_agent/__init__.py`:

```python
"""HTTP sender-agent for the Cloudflare WeChat send service."""
```

Create `sender_agent/app.py`:

```python
import os
from threading import Lock

from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from wechat_sender import WeChatSenderError, send_text_messages


APP_NAME = "wechat-sender-agent"
DEFAULT_APPIUM_URL = "http://47.115.144.127:6002"
DEFAULT_DEVICE_NAME = "971bd67c0107"

app = FastAPI(title=APP_NAME)
device_lock = Lock()


class SendRequest(BaseModel):
    receiver: str = Field(min_length=1)
    messages: list[str] = Field(min_length=1)
    device_name: str = Field(min_length=1)


def _json_error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": error, "message": message},
    )


def _agent_token() -> str:
    return os.getenv("WECHAT_AGENT_TOKEN", "")


def _allowed_device_name() -> str:
    return os.getenv("WECHAT_ALLOWED_DEVICE_NAME", DEFAULT_DEVICE_NAME)


def _appium_url() -> str:
    return os.getenv("WECHAT_APPIUM_URL", DEFAULT_APPIUM_URL)


def _is_authorized(authorization: str | None) -> bool:
    token = _agent_token()
    return bool(token) and authorization == f"Bearer {token}"


@app.exception_handler(RequestValidationError)
def validation_exception_handler(_request, _exc):
    return _json_error(400, "invalid_request", "request payload is invalid")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": APP_NAME}


@app.post("/v1/wechat/send")
def send_wechat(request: SendRequest, authorization: str | None = Header(default=None)):
    if not _is_authorized(authorization):
        return _json_error(401, "unauthorized", "missing or invalid bearer token")

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
        )
        return {
            "success": result.success,
            "device_name": result.device_name,
            "receiver": result.receiver,
            "sent_count": result.sent_count,
        }
    except WeChatSenderError as exc:
        status_code = 504 if exc.error_code == "appium_timeout" else 500
        return _json_error(status_code, exc.error_code, str(exc))
    finally:
        device_lock.release()
```

- [ ] **Step 4: Run the agent tests to verify they pass**

Run:

```bash
python -m unittest tests/sender_agent_test.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the sender-agent**

Run:

```bash
git add sender_agent tests/sender_agent_test.py
git commit -m "feat: add wechat sender agent"
```

---

### Task 3: Implement The Cloudflare Worker Gateway

**Files:**
- Create: `cloudflare/wechat-worker/package.json`
- Create: `cloudflare/wechat-worker/tsconfig.json`
- Create: `cloudflare/wechat-worker/wrangler.jsonc`
- Create: `cloudflare/wechat-worker/src/index.ts`
- Create: `cloudflare/wechat-worker/test/index.test.ts`

- [ ] **Step 1: Add the Worker project files and failing tests**

Create `cloudflare/wechat-worker/package.json`:

```json
{
  "name": "wechat-cloudflare-worker",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "typecheck": "tsc --noEmit",
    "dev": "wrangler dev",
    "deploy": "wrangler deploy"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20260620.0",
    "typescript": "^5.5.4",
    "vitest": "^2.1.9",
    "wrangler": "^4.20.0"
  }
}
```

Create `cloudflare/wechat-worker/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "Bundler",
    "strict": true,
    "types": ["@cloudflare/workers-types", "vitest/globals"],
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts", "test/**/*.ts"]
}
```

Create `cloudflare/wechat-worker/wrangler.jsonc`:

```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "wechat-send-gateway",
  "main": "src/index.ts",
  "compatibility_date": "2026-06-28",
  "vars": {
    "ALLOWED_DEVICE_NAME": "971bd67c0107",
    "SENDER_AGENT_URL": "http://47.115.144.127:7001"
  },
  "observability": {
    "enabled": true
  }
}
```

Create `cloudflare/wechat-worker/test/index.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import worker, { Env } from "../src/index";

function env(overrides: Partial<Env> = {}): Env {
  return {
    PUBLIC_API_TOKEN: "public-secret",
    SENDER_AGENT_TOKEN: "agent-secret",
    SENDER_AGENT_URL: "http://47.115.144.127:7001",
    ALLOWED_DEVICE_NAME: "971bd67c0107",
    ...overrides,
  };
}

describe("wechat send worker", () => {
  it("rejects missing public token", async () => {
    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "971bd67c0107",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ success: false, error: "unauthorized" });
  });

  it("rejects wrong public token", async () => {
    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        headers: { Authorization: "Bearer wrong-secret" },
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "971bd67c0107",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ success: false, error: "unauthorized" });
  });

  it("rejects invalid messages", async () => {
    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        headers: { Authorization: "Bearer public-secret" },
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: [],
          device_name: "971bd67c0107",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ success: false, error: "invalid_request" });
  });

  it("rejects wrong device", async () => {
    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        headers: { Authorization: "Bearer public-secret" },
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "other-device",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ success: false, error: "device_not_allowed" });
  });

  it("forwards valid requests to sender-agent", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          success: true,
          device_name: "971bd67c0107",
          receiver: "文件传输助手",
          sent_count: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const response = await worker.fetch(
      new Request("https://worker.example/v1/wechat/send", {
        method: "POST",
        headers: { Authorization: "Bearer public-secret" },
        body: JSON.stringify({
          receiver: "文件传输助手",
          messages: ["hello"],
          device_name: "971bd67c0107",
        }),
      }),
      env(),
      {} as ExecutionContext,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ success: true, sent_count: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://47.115.144.127:7001/v1/wechat/send",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer agent-secret",
          "Content-Type": "application/json",
        }),
      }),
    );

    fetchMock.mockRestore();
  });
});
```

- [ ] **Step 2: Install Worker dependencies and verify tests fail**

Run:

```bash
cd cloudflare/wechat-worker
npm install
npm test
```

Expected: FAIL with `Cannot find module '../src/index'`.

- [ ] **Step 3: Implement the Worker gateway**

Create `cloudflare/wechat-worker/src/index.ts`:

```ts
export interface Env {
  PUBLIC_API_TOKEN: string;
  SENDER_AGENT_TOKEN: string;
  SENDER_AGENT_URL: string;
  ALLOWED_DEVICE_NAME: string;
}

interface SendPayload {
  receiver: string;
  messages: string[];
  device_name: string;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(status: number, error: string, message: string): Response {
  return jsonResponse({ success: false, error, message }, status);
}

function isAuthorized(request: Request, env: Env): boolean {
  const expected = `Bearer ${env.PUBLIC_API_TOKEN}`;
  return Boolean(env.PUBLIC_API_TOKEN) && request.headers.get("Authorization") === expected;
}

function normalizeAgentUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

function validatePayload(value: unknown, allowedDeviceName: string): SendPayload | Response {
  if (value === null || typeof value !== "object") {
    return apiError(400, "invalid_request", "request body must be an object");
  }

  const payload = value as Record<string, unknown>;
  if (typeof payload.receiver !== "string" || payload.receiver.trim() === "") {
    return apiError(400, "invalid_request", "receiver is required");
  }
  if (!Array.isArray(payload.messages) || payload.messages.length === 0) {
    return apiError(400, "invalid_request", "messages must be a non-empty array");
  }
  if (payload.messages.some((message) => typeof message !== "string" || message.trim() === "")) {
    return apiError(400, "invalid_request", "messages must contain only non-empty strings");
  }
  if (payload.device_name !== allowedDeviceName) {
    return apiError(403, "device_not_allowed", "requested device is not allowed");
  }

  return {
    receiver: payload.receiver,
    messages: payload.messages as string[],
    device_name: payload.device_name as string,
  };
}

async function readJson(request: Request): Promise<unknown | Response> {
  try {
    return await request.json();
  } catch {
    return apiError(400, "invalid_request", "request body must be valid JSON");
  }
}

async function forwardToAgent(payload: SendPayload, env: Env): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60_000);
  try {
    const response = await fetch(`${normalizeAgentUrl(env.SENDER_AGENT_URL)}/v1/wechat/send`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.SENDER_AGENT_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "sender-agent unavailable";
    return apiError(502, "upstream_unavailable", message);
  } finally {
    clearTimeout(timeout);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/healthz") {
      return jsonResponse({ ok: true, service: "wechat-send-gateway" });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/wechat/send") {
      return apiError(404, "not_found", "endpoint not found");
    }
    if (!isAuthorized(request, env)) {
      return apiError(401, "unauthorized", "missing or invalid bearer token");
    }

    const json = await readJson(request);
    if (json instanceof Response) {
      return json;
    }

    const payload = validatePayload(json, env.ALLOWED_DEVICE_NAME);
    if (payload instanceof Response) {
      return payload;
    }

    return forwardToAgent(payload, env);
  },
};
```

- [ ] **Step 4: Run Worker tests and typecheck**

Run:

```bash
cd cloudflare/wechat-worker
npm test
npm run typecheck
```

Expected: PASS.

- [ ] **Step 5: Configure Worker secrets locally for deployment**

Run:

```bash
cd cloudflare/wechat-worker
npx wrangler secret put PUBLIC_API_TOKEN
npx wrangler secret put SENDER_AGENT_TOKEN
```

Expected: Wrangler confirms both secrets are uploaded. Do not commit secret values.

- [ ] **Step 6: Commit the Worker gateway**

Run:

```bash
git add cloudflare/wechat-worker
git commit -m "feat: add cloudflare wechat send gateway"
```

---

### Task 4: Add Runtime Documentation And Smoke Test

**Files:**
- Create: `docs/wechat-cloudflare-send-service.md`

- [ ] **Step 1: Write the runtime documentation**

Create `docs/wechat-cloudflare-send-service.md`:

```markdown
# WeChat Cloudflare Send Service

## Architecture

```text
Caller
  -> Cloudflare Worker /v1/wechat/send
  -> sender-agent on 47.115.144.127
  -> Appium http://47.115.144.127:6002
  -> Android device 971bd67c0107
  -> WeChat Zacks
```

## Sender-Agent Environment

Set these variables on `47.115.144.127`:

```bash
test -n "${WECHAT_AGENT_TOKEN:?set WECHAT_AGENT_TOKEN before starting sender-agent}"
export WECHAT_ALLOWED_DEVICE_NAME="971bd67c0107"
export WECHAT_APPIUM_URL="http://47.115.144.127:6002"
```

Start the service as one process so the in-process device lock is valid:

```bash
uvicorn sender_agent.app:app --host 0.0.0.0 --port 7001 --workers 1
```

## Local Sender-Agent Smoke Test

Run from a machine that can reach `47.115.144.127:7001`:

```bash
curl -sS -X POST "http://47.115.144.127:7001/v1/wechat/send" \
  -H "Authorization: Bearer ${WECHAT_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "文件传输助手",
    "messages": ["sender-agent smoke test"],
    "device_name": "971bd67c0107"
  }'
```

Expected response:

```json
{
  "success": true,
  "device_name": "971bd67c0107",
  "receiver": "文件传输助手",
  "sent_count": 1
}
```

## Cloudflare Worker Environment

Set Worker secrets:

```bash
cd cloudflare/wechat-worker
npx wrangler secret put PUBLIC_API_TOKEN
npx wrangler secret put SENDER_AGENT_TOKEN
```

`SENDER_AGENT_URL` defaults to `http://47.115.144.127:7001` in `wrangler.jsonc`.

## Worker Smoke Test

```bash
curl -sS -X POST "${WECHAT_WORKER_URL:?set WECHAT_WORKER_URL}/v1/wechat/send" \
  -H "Authorization: Bearer ${PUBLIC_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "文件传输助手",
    "messages": ["cloudflare worker smoke test"],
    "device_name": "971bd67c0107"
  }'
```

Expected response has `success: true` and `sent_count: 1`.

## Operational Notes

- Do not expose Appium `6002` as the public API.
- Expose only sender-agent `7001`.
- Keep sender-agent at one process unless an external lock is introduced.
- `409 device_busy` means another request is currently controlling the phone.
- `502 upstream_unavailable` means Cloudflare cannot reach sender-agent.
```

- [ ] **Step 2: Verify documentation has no unresolved markers**

Run:

```bash
python - <<'PY'
from pathlib import Path

markers = ["TB" + "D", "TO" + "DO", "FIX" + "ME", "place" + "holder", "\u5f85\u5b9a", "\u672a\u5b9a"]
text = Path("docs/wechat-cloudflare-send-service.md").read_text()
matches = [marker for marker in markers if marker in text]
if matches:
    raise SystemExit(f"unresolved markers found: {matches}")
PY
```

Expected: command exits successfully with no output.

- [ ] **Step 3: Commit the documentation**

Run:

```bash
git add docs/wechat-cloudflare-send-service.md
git commit -m "docs: add wechat send service runbook"
```

---

### Task 5: Final Verification

**Files:**
- Verify all files created in Tasks 1-4.

- [ ] **Step 1: Run Python unit tests**

Run:

```bash
python -m unittest discover -s tests -p '*_test.py' -v
```

Expected: PASS for `wechat_sender_test.py` and `sender_agent_test.py`.

- [ ] **Step 2: Run Worker unit tests and typecheck**

Run:

```bash
cd cloudflare/wechat-worker
npm test
npm run typecheck
```

Expected: PASS for Vitest and TypeScript.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short
```

Expected: no unstaged or untracked implementation files.

- [ ] **Step 4: Manual live smoke test on `47.115.144.127`**

Run on `47.115.144.127`:

```bash
test -n "${WECHAT_AGENT_TOKEN:?set WECHAT_AGENT_TOKEN before starting sender-agent}"
export WECHAT_ALLOWED_DEVICE_NAME="971bd67c0107"
export WECHAT_APPIUM_URL="http://47.115.144.127:6002"
uvicorn sender_agent.app:app --host 0.0.0.0 --port 7001 --workers 1
```

From another shell:

```bash
curl -sS -X POST "http://47.115.144.127:7001/v1/wechat/send" \
  -H "Authorization: Bearer ${WECHAT_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "文件传输助手",
    "messages": ["live smoke test"],
    "device_name": "971bd67c0107"
  }'
```

Expected: response contains `"success": true`, and WeChat account `Zacks` sends `live smoke test` to `文件传输助手`.

---

## Self-Review Notes

- Spec coverage: The plan covers Airflow-free Appium extraction, synchronous sender-agent API, single-process device locking, Cloudflare Worker validation/forwarding, deployment target `47.115.144.127`, and smoke testing against device `971bd67c0107`.
- Unresolved marker scan: The plan avoids fake secret values and fake Worker host strings in run commands; secrets are read from environment variables or Wrangler prompts.
- Type and contract consistency: Python `SendResult`, sender-agent JSON responses, and Worker response forwarding all preserve `success`, `device_name`, `receiver`, and `sent_count`; validation failures map to `invalid_request`.
