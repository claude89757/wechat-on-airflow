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
            operator = None
            operator = operator_factory(
                appium_server_url=appium_server_url,
                device_name=device_name,
                force_app_launch=True,
            )
            time.sleep(restart_wait_seconds)
            if not operator.is_at_main_page():
                operator.return_to_chats()
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
