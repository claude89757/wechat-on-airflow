import csv
import difflib
import io
import json
import random
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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


@dataclass(frozen=True)
class OcrLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int


VISUAL_INPUT_CLEAR_KEYSTROKES = 1024
VISUAL_MAIN_NAVIGATION_TOP_RATIO = 0.90
VISUAL_SEND_BUTTON_REGION = (0.78, 0.57, 1.0, 0.66)


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


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = ', "\'", '.join(f"'{part}'" for part in value.split("'"))
    return f"concat({parts})"


def _recent_chat_xpaths(receiver: str) -> list[str]:
    receiver_literal = _xpath_literal(receiver)
    return [
        f"//android.widget.TextView[@text={receiver_literal}]",
        f"//android.view.View[@text={receiver_literal}]",
        f"//*[contains(@content-desc, {receiver_literal})]",
    ]


def _normalize_visual_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _visual_text_match_score(
    candidate: str,
    expected: str,
    *,
    allow_truncated_numeric_suffix: bool = False,
) -> float:
    normalized_candidate = _normalize_visual_text(candidate)
    normalized_expected = _normalize_visual_text(expected)
    if not normalized_candidate or not normalized_expected:
        return 0.0
    if normalized_candidate == normalized_expected:
        return 1.0
    if normalized_expected in normalized_candidate:
        return 0.99

    candidate_digits = re.findall(r"\d+", normalized_candidate)
    expected_digits = re.findall(r"\d+", normalized_expected)
    if expected_digits and candidate_digits != expected_digits:
        if (
            allow_truncated_numeric_suffix
            and not candidate_digits
            and len(normalized_candidate) >= max(8, round(len(normalized_expected) * 0.6))
            and normalized_expected.startswith(normalized_candidate)
        ):
            return 0.9 + 0.08 * len(normalized_candidate) / len(normalized_expected)
        return 0.0

    if len(normalized_candidate) >= max(
        8, len(normalized_expected) - 2
    ) and normalized_expected.startswith(normalized_candidate):
        return 0.9 + 0.08 * len(normalized_candidate) / len(normalized_expected)

    if len(normalized_candidate) < max(8, round(len(normalized_expected) * 0.6)):
        return 0.0
    similarity = difflib.SequenceMatcher(
        None,
        normalized_candidate,
        normalized_expected,
    ).ratio()
    if similarity >= 0.72:
        return similarity
    return 0.0


def _parse_tesseract_tsv(
    value: str,
    *,
    origin_x: int,
    origin_y: int,
    scale: float,
) -> list[OcrLine]:
    grouped_rows: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(value), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
        grouped_rows.setdefault(key, []).append(row)

    lines = []
    for rows in grouped_rows.values():
        try:
            left = min(int(row["left"]) for row in rows)
            top = min(int(row["top"]) for row in rows)
            right = max(int(row["left"]) + int(row["width"]) for row in rows)
            bottom = max(int(row["top"]) + int(row["height"]) for row in rows)
        except (KeyError, TypeError, ValueError):
            continue
        lines.append(
            OcrLine(
                text="".join(row["text"].strip() for row in rows),
                left=round(origin_x + left / scale),
                top=round(origin_y + top / scale),
                right=round(origin_x + right / scale),
                bottom=round(origin_y + bottom / scale),
            )
        )
    return lines


def _green_button_bounds(
    pixels: Iterable[tuple[int, int, int]],
    *,
    width: int,
    origin_x: int,
    origin_y: int,
    min_pixels: int = 500,
) -> OcrLine | None:
    points = [
        (index % width, index // width)
        for index, (red, green, blue) in enumerate(pixels)
        if green >= 130 and green >= red + 50 and green >= blue + 30
    ]
    if len(points) < min_pixels:
        return None

    left = min(x for x, _y in points)
    top = min(y for _x, y in points)
    right = max(x for x, _y in points) + 1
    bottom = max(y for _x, y in points) + 1
    if right - left < 48 or bottom - top < 24:
        return None
    return OcrLine(
        text="visual-send-button",
        left=origin_x + left,
        top=origin_y + top,
        right=origin_x + right,
        bottom=origin_y + bottom,
    )


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

    for adb_command in (
        ["shell", "input", "keyevent", "WAKEUP"],
        ["shell", "wm", "dismiss-keyguard"],
        ["shell", "cmd", "statusbar", "collapse"],
        ["shell", "input", "keyevent", "BACK"],
    ):
        try:
            command_runner(["adb", "-s", device_name, *adb_command], 10)
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
            "newCommandTimeout": 120,
            "adbExecTimeout": 120000,
            "uiautomator2ServerInstallTimeout": 120000,
            "uiautomator2ServerLaunchTimeout": 120000,
        }
        self.device_name = device_name
        self.current_receiver: str | None = None
        self.driver = AppiumWebDriver(
            command_executor=appium_server_url,
            options=UiAutomator2Options().load_capabilities(capabilities),
        )

    def send_message(self, receiver: str, messages: list[str]) -> None:
        if not messages:
            raise InvalidSendRequestError("messages must contain at least one item")
        self.current_receiver = None

        if not self.is_contact_in_recent_chats(receiver):
            self._search_and_open_chat(receiver)

        if not self._is_verified_chat_open(receiver):
            raise ContactNotFoundError(f"target chat was not verified: {receiver}")

        if self._has_accessible_message_input():
            self._send_accessible_messages(messages)
        else:
            self._send_visual_messages(messages)

        self.return_to_chats()

    def is_contact_in_recent_chats(self, receiver: str) -> bool:
        if not self.is_at_main_page():
            self.return_to_chats()
            time.sleep(1)

        if self._click_accessible_text(receiver):
            if self._wait_for_chat(receiver, timeout=6):
                self.current_receiver = receiver
                return True
            self.return_to_chats()

        for element in self._find_accessible_text_candidates(
            receiver,
            top_ratio=0.10,
            bottom_ratio=0.90,
            allow_truncated_numeric_suffix=True,
        ):
            try:
                _run_stale_retry(element.click)
            except Exception:
                continue
            if self._wait_for_chat(receiver, timeout=6):
                self.current_receiver = receiver
                return True
            self.return_to_chats()

        lines = self._find_visual_lines(
            receiver,
            region=(0.15, 0.10, 0.93, 0.90),
            scale=1.25,
            page_segmentation_mode=11,
            allow_truncated_numeric_suffix=True,
        )
        for line in lines:
            self._tap_ocr_line(line)
            if self._wait_for_chat(receiver, timeout=6):
                self.current_receiver = receiver
                return True
            self.return_to_chats()
        return False

    def _click_accessible_text(self, value: str) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        def click_matching_element() -> bool:
            for xpath in _recent_chat_xpaths(value):
                for element in self.driver.find_elements(by=AppiumBy.XPATH, value=xpath):
                    try:
                        element.click()
                        return True
                    except Exception:
                        continue
            return False

        return bool(_run_stale_retry(click_matching_element))

    def _has_accessible_wechat_controls(self) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            return bool(
                self.driver.find_elements(
                    by=AppiumBy.XPATH,
                    value="//*[@package='com.tencent.mm' and @clickable='true']",
                )
            )
        except Exception:
            return False

    def _has_accessible_message_input(self) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            return bool(
                self.driver.find_elements(
                    by=AppiumBy.XPATH,
                    value="//android.widget.EditText",
                )
            )
        except Exception:
            return False

    @staticmethod
    def _accessible_element_text(element: Any) -> str:
        values = []
        try:
            values.append(str(element.text or ""))
        except Exception:
            pass
        for attribute in ("text", "contentDescription", "content-desc"):
            try:
                values.append(str(element.get_attribute(attribute) or ""))
            except Exception:
                continue
        return " ".join(value for value in values if value)

    def _find_accessible_text_candidates(
        self,
        receiver: str,
        *,
        top_ratio: float,
        bottom_ratio: float,
        minimum_score: float = 0.72,
        allow_truncated_numeric_suffix: bool = False,
    ) -> list[Any]:
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            screen_height = self.driver.get_window_size()["height"]
            elements = self.driver.find_elements(
                by=AppiumBy.XPATH,
                value="//*[@text!='' or @content-desc!='']",
            )
        except Exception:
            return []

        candidates = []
        for element in elements:
            try:
                rect = element.rect
                center_y = rect["y"] + rect["height"] / 2
            except Exception:
                continue
            if not screen_height * top_ratio <= center_y <= screen_height * bottom_ratio:
                continue
            score = _visual_text_match_score(
                self._accessible_element_text(element),
                receiver,
                allow_truncated_numeric_suffix=allow_truncated_numeric_suffix,
            )
            if score >= minimum_score:
                candidates.append((score, center_y, rect["x"], element))
        return [
            element
            for _score, _center_y, _left, element in sorted(
                candidates,
                key=lambda item: (item[1], item[2], -item[0]),
            )
        ]

    def _search_and_open_chat(self, receiver: str) -> None:
        from appium.webdriver.common.appiumby import AppiumBy

        self.current_receiver = None
        if not self._open_search_from_main_page():
            self._tap_ratio(0.83, 0.07)

        if not self._wait_for_search_page(timeout=5) and self.is_at_main_page():
            raise AppiumTimeoutError("WeChat search page did not open")

        search_inputs = self.driver.find_elements(
            by=AppiumBy.XPATH,
            value="//android.widget.EditText[@text='搜索']",
        )
        if search_inputs:
            search_inputs[0].send_keys(receiver)
        else:
            self.driver.set_clipboard_text(receiver)
            self.driver.press_keycode(279)
        time.sleep(1)

        if self._click_accessible_text(receiver):
            if self._wait_for_chat(receiver, timeout=6):
                self.current_receiver = receiver
                return
            self._return_to_search_results()

        matching_lines = self._find_visual_lines(
            receiver,
            region=(0.08, 0.12, 0.94, 0.70),
            scale=1.25,
            page_segmentation_mode=11,
        )
        for line in matching_lines:
            self._tap_ocr_line(line)
            if self._wait_for_chat(receiver, timeout=6):
                self.current_receiver = receiver
                return
            self._return_to_search_results()

        raise ContactNotFoundError(f"receiver did not open: {receiver}")

    def _open_search_from_main_page(self) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            screen = self.driver.get_window_size()
            search_buttons = self.driver.find_elements(
                by=AppiumBy.ACCESSIBILITY_ID,
                value="搜索",
            )
        except Exception:
            return False

        for button in search_buttons:
            try:
                rect = button.rect
                center_x = rect["x"] + rect["width"] / 2
                center_y = rect["y"] + rect["height"] / 2
                if center_x < screen["width"] * 0.55 or center_y > screen["height"] * 0.18:
                    continue
                _run_stale_retry(button.click)
            except Exception:
                continue
            if self._wait_for_search_page(timeout=2) or not self.is_at_main_page():
                return True
        return False

    def _return_to_search_results(self) -> None:
        self.current_receiver = None
        self.driver.press_keycode(4)
        if not self._wait_for_search_page(timeout=5):
            raise ContactNotFoundError("unable to return to WeChat search results")

    def _send_accessible_messages(self, messages: list[str]) -> None:
        from appium.webdriver.common.appiumby import AppiumBy
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        for index, message in enumerate(messages):
            try:

                def send_current_message(current_message: str = message) -> None:
                    message_input = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located(
                            (AppiumBy.XPATH, "//android.widget.EditText")
                        )
                    )
                    message_input.send_keys(current_message)
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

    def _send_visual_messages(self, messages: list[str]) -> None:
        if not self.current_receiver or not self._is_verified_chat_open(self.current_receiver):
            raise DeviceNotReadyError("WeChat chat page is not active")

        self._tap_ratio(0.25, 0.955)
        time.sleep(1)
        for index, message in enumerate(messages):
            try:
                self._clear_visual_input()
                self.driver.set_clipboard_text(message)
                self.driver.press_keycode(279)
                time.sleep(0.5)
                send_line = self._find_visual_green_button(region=VISUAL_SEND_BUTTON_REGION)
                if send_line is None:
                    send_line = self._find_visual_line(
                        "发送",
                        region=VISUAL_SEND_BUTTON_REGION,
                        scale=0.8,
                        page_segmentation_mode=11,
                    )
                if send_line is None:
                    raise AppiumTimeoutError("visual send button was not found")
                self._tap_ocr_line(send_line)
                time.sleep(0.8)
                if self.driver.current_package != "com.tencent.mm":
                    raise SendFailedError("WeChat left the chat page during send")
                if self._find_visual_green_button(region=VISUAL_SEND_BUTTON_REGION) is not None:
                    raise SendFailedError("visual send button remained active after tap")
                if index < len(messages) - 1:
                    time.sleep(random.uniform(0.3, 3))
            except WeChatSenderError:
                raise
            except Exception as exc:
                raise SendFailedError(str(exc)) from exc
        self.driver.set_clipboard_text("")

    def _clear_visual_input(self) -> None:
        commands = (
            ["shell", "input", "keyevent", "123"],
            [
                "shell",
                "input",
                "keyevent",
                *(["67"] * VISUAL_INPUT_CLEAR_KEYSTROKES),
            ],
        )
        for arguments in commands:
            try:
                result = subprocess.run(
                    ["adb", "-s", self.device_name, *arguments],
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DeviceNotReadyError("unable to clear visual message input") from exc
            if result.returncode != 0:
                raise DeviceNotReadyError("unable to clear visual message input")

        if self._find_visual_green_button(region=VISUAL_SEND_BUTTON_REGION) is not None:
            raise SendFailedError("visual message input still contains a draft")

    def _find_visual_green_button(
        self,
        *,
        region: tuple[float, float, float, float],
    ) -> OcrLine | None:
        try:
            from PIL import Image
        except ImportError as exc:
            raise DeviceNotReadyError("Pillow is required for visual WeChat automation") from exc

        image = Image.open(io.BytesIO(self.driver.get_screenshot_as_png())).convert("RGB")
        width, height = image.size
        left = round(width * region[0])
        top = round(height * region[1])
        right = round(width * region[2])
        bottom = round(height * region[3])
        cropped = image.crop((left, top, right, bottom))
        return _green_button_bounds(
            cropped.getdata(),
            width=cropped.width,
            origin_x=left,
            origin_y=top,
        )

    def _ocr_lines(
        self,
        *,
        region: tuple[float, float, float, float],
        scale: float,
        page_segmentation_mode: int,
    ) -> list[OcrLine]:
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise DeviceNotReadyError("Pillow is required for visual WeChat automation") from exc

        image = Image.open(io.BytesIO(self.driver.get_screenshot_as_png()))
        width, height = image.size
        left = round(width * region[0])
        top = round(height * region[1])
        right = round(width * region[2])
        bottom = round(height * region[3])
        cropped = ImageOps.grayscale(image.crop((left, top, right, bottom)))
        cropped = cropped.resize(
            (round(cropped.width * scale), round(cropped.height * scale)),
            Image.Resampling.LANCZOS,
        )

        temporary_path: Path | None = None
        result: subprocess.CompletedProcess[str] | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary_file:
                temporary_path = Path(temporary_file.name)
            cropped.save(temporary_path)
            result = subprocess.run(
                [
                    "tesseract",
                    str(temporary_path),
                    "stdout",
                    "-l",
                    "chi_sim+eng",
                    "--psm",
                    str(page_segmentation_mode),
                    "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DeviceNotReadyError("tesseract is required for visual WeChat automation") from exc
        except subprocess.TimeoutExpired as exc:
            raise AppiumTimeoutError("visual text recognition timed out") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        if result is None or result.returncode != 0:
            raise DeviceNotReadyError("visual text recognition failed")
        return _parse_tesseract_tsv(
            result.stdout,
            origin_x=left,
            origin_y=top,
            scale=scale,
        )

    def _find_visual_line(
        self,
        value: str,
        *,
        region: tuple[float, float, float, float],
        scale: float,
        page_segmentation_mode: int,
        minimum_score: float = 0.72,
    ) -> OcrLine | None:
        lines = self._find_visual_lines(
            value,
            region=region,
            scale=scale,
            page_segmentation_mode=page_segmentation_mode,
            minimum_score=minimum_score,
        )
        return lines[0] if lines else None

    def _find_visual_lines(
        self,
        value: str,
        *,
        region: tuple[float, float, float, float],
        scale: float,
        page_segmentation_mode: int,
        minimum_score: float = 0.72,
        allow_truncated_numeric_suffix: bool = False,
    ) -> list[OcrLine]:
        scored_lines = [
            (
                _visual_text_match_score(
                    line.text,
                    value,
                    allow_truncated_numeric_suffix=allow_truncated_numeric_suffix,
                ),
                line,
            )
            for line in self._ocr_lines(
                region=region,
                scale=scale,
                page_segmentation_mode=page_segmentation_mode,
            )
        ]
        return [
            line
            for score, line in sorted(
                (item for item in scored_lines if item[0] >= minimum_score),
                key=lambda item: (item[1].top, item[1].left, -item[0]),
            )
        ]

    def _tap_ocr_line(self, line: OcrLine) -> None:
        self.driver.execute_script(
            "mobile: clickGesture",
            {
                "x": round((line.left + line.right) / 2),
                "y": round((line.top + line.bottom) / 2),
            },
        )

    def _tap_ratio(self, x_ratio: float, y_ratio: float) -> None:
        screen_size = self.driver.get_window_size()
        self.driver.execute_script(
            "mobile: clickGesture",
            {
                "x": round(screen_size["width"] * x_ratio),
                "y": round(screen_size["height"] * y_ratio),
            },
        )

    def _activity_ends_with(self, suffix: str) -> bool:
        try:
            return self.driver.current_package == "com.tencent.mm" and str(
                self.driver.current_activity
            ).endswith(suffix)
        except Exception:
            return False

    def _wait_for_activity(self, suffix: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._activity_ends_with(suffix):
                return True
            time.sleep(0.25)
        return self._activity_ends_with(suffix)

    def _has_accessible_search_input(self) -> bool:
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            screen_height = self.driver.get_window_size()["height"]
            inputs = self.driver.find_elements(
                by=AppiumBy.XPATH,
                value="//android.widget.EditText",
            )
            return any(
                element.rect["y"] + element.rect["height"] / 2 <= screen_height * 0.18
                for element in inputs
            )
        except Exception:
            return False

    def _is_accessible_search_page(self) -> bool:
        return self._activity_ends_with("FTSMainUI") or self._has_accessible_search_input()

    def _wait_for_search_page(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._is_accessible_search_page():
                return True
            time.sleep(0.25)
        if self._is_accessible_search_page():
            return True
        return any(
            self._find_visual_line(
                text,
                region=(0.0, 0.0, 1.0, 0.18),
                scale=1.5,
                page_segmentation_mode=11,
                minimum_score=0.86,
            )
            is not None
            for text in ("搜索", "取消")
        )

    def _is_visual_chat_page(self, receiver: str) -> bool:
        is_chatting_activity = self._activity_ends_with("ChattingUI")
        is_launcher_activity = self._activity_ends_with("LauncherUI")
        if not (is_chatting_activity or is_launcher_activity):
            return False
        if is_launcher_activity and self._is_visual_main_page():
            return False
        if self._has_accessible_title(receiver):
            return True
        return (
            self._find_visual_line(
                receiver,
                region=(0.08, 0.01, 0.92, 0.16),
                scale=1.5,
                page_segmentation_mode=11,
                minimum_score=0.86,
            )
            is not None
        )

    def _has_accessible_title(self, receiver: str) -> bool:
        return bool(
            self._find_accessible_text_candidates(
                receiver,
                top_ratio=0.0,
                bottom_ratio=0.18,
                minimum_score=0.86,
            )
        )

    def _wait_for_chat(self, receiver: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._is_visual_chat_page(receiver):
                return True
            time.sleep(0.25)
        return self._is_visual_chat_page(receiver)

    def _is_verified_chat_open(self, receiver: str) -> bool:
        if self.current_receiver != receiver:
            return False
        return self._activity_ends_with("ChattingUI") or self._activity_ends_with("LauncherUI")

    def _is_visual_main_page(self) -> bool:
        if self.driver.current_package != "com.tencent.mm":
            return False
        try:
            from PIL import Image
        except ImportError as exc:
            raise DeviceNotReadyError("Pillow is required for visual WeChat automation") from exc

        image = Image.open(io.BytesIO(self.driver.get_screenshot_as_png())).convert("RGB")
        width, height = image.size
        navigation = image.crop(
            (
                0,
                round(height * VISUAL_MAIN_NAVIGATION_TOP_RATIO),
                round(width * 0.27),
                height,
            )
        )
        green_pixels = sum(
            1
            for red, green, blue in navigation.getdata()
            if green >= 110 and green >= red + 40 and green >= blue + 30
        )
        return green_pixels >= 150

    def scroll_down(self, start: float = 0.8, end: float = 0.2) -> None:
        screen_size = self.driver.get_window_size()
        start_x = screen_size["width"] * 0.5
        start_y = screen_size["height"] * start
        end_y = screen_size["height"] * end
        self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
        time.sleep(0.5)

    def return_to_chats(self) -> None:
        from appium.webdriver.common.appiumby import AppiumBy

        self.current_receiver = None
        for _ in range(6):
            if self.is_at_main_page():
                return
            try:
                back_btn = self.driver.find_element(
                    by=AppiumBy.ID,
                    value="com.tencent.mm:id/g",
                )
                back_btn.click()
            except Exception:
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
            return self._is_visual_main_page()

    def close(self) -> None:
        if self.driver:
            try:
                self.driver.set_clipboard_text("")
            except Exception:
                pass
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
    preflight_cleanup: Callable[[str, str], None] | None = None,
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
