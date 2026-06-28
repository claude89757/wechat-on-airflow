import json
import random
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional
from urllib.request import Request, urlopen


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


def _appium_url(appium_server_url: str, path: str) -> str:
    return f"{appium_server_url.rstrip('/')}{path}"


def _http_json_request(method: str, url: str) -> dict[str, Any]:
    request = Request(url, method=method)
    with urlopen(request, timeout=10) as response:
        body = response.read()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _run_cleanup_command(command: list[str], timeout: int) -> None:
    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def _session_matches_device(session: dict[str, Any], device_name: str) -> bool:
    capabilities = session.get("capabilities") or {}
    candidates = {
        capabilities.get("udid"),
        capabilities.get("deviceName"),
        capabilities.get("appium:udid"),
        capabilities.get("appium:deviceName"),
    }
    return device_name in candidates


def _is_stale_object_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "StaleObjectException" in message
        or "StaleElementReferenceException" in message
        or "stale element reference" in message.lower()
    )


def _run_stale_retry(
    operation: Callable[[], Any],
    attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
    wait_seconds: float = 0.5,
) -> Any:
    tries = max(attempts, 1)
    for attempt in range(tries):
        try:
            return operation()
        except Exception as exc:
            if not _is_stale_object_error(exc) or attempt == tries - 1:
                raise
            sleeper(wait_seconds)
    raise RuntimeError("unreachable")


def cleanup_appium_device(
    appium_server_url: str,
    device_name: str,
    http_request: Callable[[str, str], dict[str, Any]] = _http_json_request,
    command_runner: Callable[[list[str], int], None] = _run_cleanup_command,
    sleeper: Callable[[float], None] = time.sleep,
    max_attempts: int = 5,
    poll_seconds: float = 1.0,
) -> None:
    last_error = None
    session_url = _appium_url(appium_server_url, "/sessions")
    attempts = max(max_attempts, 1)

    for attempt in range(attempts):
        try:
            sessions = http_request("GET", session_url)
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                sleeper(poll_seconds)
                continue
            raise DeviceNotReadyError("unable to read Appium sessions before send") from exc

        matching_sessions = [
            session
            for session in sessions.get("value", [])
            if _session_matches_device(session, device_name)
        ]
        if not matching_sessions:
            break

        for session in matching_sessions:
            session_id = session.get("id")
            if not session_id:
                continue
            try:
                http_request("DELETE", _appium_url(appium_server_url, f"/session/{session_id}"))
            except Exception as exc:
                last_error = exc

        if attempt < attempts - 1:
            sleeper(poll_seconds)
    else:
        raise DeviceNotReadyError(
            f"unable to clear existing Appium sessions for device {device_name}"
        ) from last_error

    for package_name in (
        "io.appium.uiautomator2.server",
        "io.appium.uiautomator2.server.test",
    ):
        try:
            command_runner(
                [
                    "adb",
                    "-s",
                    device_name,
                    "shell",
                    "am",
                    "force-stop",
                    package_name,
                ],
                10,
            )
        except Exception:
            pass

    try:
        command_runner(["adb", "-s", device_name, "forward", "--remove", "tcp:8200"], 10)
    except Exception:
        pass

    sleeper(poll_seconds)


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
                def click_search_button() -> None:
                    search_btn = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "搜索"))
                    )
                    search_btn.click()

                _run_stale_retry(click_search_button)
                search_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(
                        (AppiumBy.XPATH, "//android.widget.EditText[@text='搜索']")
                    )
                )
                search_input.send_keys(receiver)
                def click_search_result() -> None:
                    contact = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(
                            (AppiumBy.XPATH, f"//android.widget.TextView[@text='{receiver}']")
                        )
                    )
                    contact.click()

                _run_stale_retry(click_search_result)
            except TimeoutException as exc:
                raise ContactNotFoundError(f"receiver not found: {receiver}") from exc

        for index, message in enumerate(messages):
            try:
                def send_current_message() -> None:
                    message_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(
                            (AppiumBy.XPATH, "//android.widget.EditText")
                        )
                    )
                    message_input.send_keys(message)
                    send_btn = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(
                            (AppiumBy.XPATH, "//android.widget.Button[@text='发送']")
                        )
                    )
                    send_btn.click()

                _run_stale_retry(send_current_message)
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
            def click_recent_chat_if_visible() -> bool:
                contact_elements = self.driver.find_elements(
                    by=AppiumBy.XPATH,
                    value=f"//android.view.View[@text='{receiver}']",
                )
                if len(contact_elements) > 1:
                    raise ContactNotFoundError(f"multiple recent chats named {receiver}")
                if not contact_elements:
                    return False
                contact_elements[0].click()
                return True

            if _run_stale_retry(click_recent_chat_if_visible):
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
    close_wait_seconds: float = 1.0,
    restart_wait_seconds: float = 3.0,
    preflight_cleanup: Optional[Callable[[str, str], None]] = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> SendResult:
    normalized_messages = _validate_send_request(
        appium_server_url=appium_server_url,
        device_name=device_name,
        receiver=receiver,
        messages=messages,
    )
    normalized_receiver = receiver.strip()

    operator = None
    try:
        if preflight_cleanup:
            preflight_cleanup(appium_server_url, device_name)
        operator = operator_factory(
            appium_server_url=appium_server_url,
            device_name=device_name,
            force_app_launch=False,
        )
        sleeper(startup_wait_seconds)
        if not operator.is_at_main_page():
            operator.close()
            operator = None
            sleeper(close_wait_seconds)
            operator = operator_factory(
                appium_server_url=appium_server_url,
                device_name=device_name,
                force_app_launch=True,
            )
            sleeper(restart_wait_seconds)
            if not operator.is_at_main_page():
                operator.return_to_chats()
            if not operator.is_at_main_page():
                raise DeviceNotReadyError("WeChat main page is not available")

        operator.send_message(receiver=normalized_receiver, messages=normalized_messages)
        return SendResult(
            success=True,
            device_name=device_name,
            receiver=normalized_receiver,
            sent_count=len(normalized_messages),
        )
    except WeChatSenderError:
        raise
    except Exception as exc:
        raise SendFailedError(str(exc)) from exc
    finally:
        if operator:
            operator.close()
