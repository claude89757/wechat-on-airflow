import unittest
from types import ModuleType
from unittest.mock import patch

from wechat_sender.appium_text_sender import (
    VISUAL_INPUT_CLEAR_KEYSTROKES,
    VISUAL_MAIN_NAVIGATION_TOP_RATIO,
    VISUAL_OCR_THRESHOLD,
    VISUAL_SEND_BUTTON_REGION,
    DeviceNotReadyError,
    InvalidSendRequestError,
    OcrLine,
    SendFailedError,
    SendResult,
    TextWeChatOperator,
    _green_button_bounds,
    _normalize_visual_text,
    _parse_tesseract_tsv,
    _recent_chat_xpaths,
    _run_stale_retry,
    _threshold_ocr_image,
    _visual_text_match_score,
    _xpath_literal,
    cleanup_appium_device,
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

    def is_target_chat_open(self, _receiver):
        return False

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


class RecoveringRestartOperator(FakeOperator):
    def __init__(self, appium_server_url, device_name, force_app_launch=False):
        super().__init__(appium_server_url, device_name, force_app_launch)
        self.at_main_page = False
        self.return_to_chats_calls = 0

    def return_to_chats(self):
        self.return_to_chats_calls += 1
        self.at_main_page = True


class VisualOnlyDriver:
    current_package = "com.tencent.mm"
    current_activity = ".ui.LauncherUI"

    def __init__(self):
        self.scripts = []
        self.swipes = []

    def find_elements(self, **_kwargs):
        return []

    def get_window_size(self):
        return {"width": 1080, "height": 2340}

    def execute_script(self, name, arguments):
        self.scripts.append((name, arguments))
        self.current_activity = ".ui.chatting.ChattingUI"

    def swipe(self, *arguments):
        self.swipes.append(arguments)


class WeChatSenderTest(unittest.TestCase):
    def setUp(self):
        FakeOperator.created = []

    def test_send_text_messages_returns_structured_result(self):
        result = send_text_messages(
            appium_server_url="http://appium.test:6002",
            device_name="test-device",
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
                device_name="test-device",
                receiver="文件传输助手",
                sent_count=2,
            ),
        )
        self.assertEqual(FakeOperator.created[0].sent, [("文件传输助手", ["hello", "world"])])
        self.assertTrue(FakeOperator.created[0].closed)

    def test_normalizes_receiver_whitespace_before_sending(self):
        result = send_text_messages(
            appium_server_url="http://appium.test:6002",
            device_name="test-device",
            receiver="  Zacks_大沙河限定免费  ",
            messages=["hello"],
            operator_factory=FakeOperator,
            startup_wait_seconds=0,
            restart_wait_seconds=0,
        )

        self.assertEqual(result.receiver, "Zacks_大沙河限定免费")
        self.assertEqual(FakeOperator.created[0].sent, [("Zacks_大沙河限定免费", ["hello"])])

    def test_cleans_appium_state_before_creating_session(self):
        events = []

        class RecordingOperator(FakeOperator):
            def __init__(self, appium_server_url, device_name, force_app_launch=False):
                events.append(("operator", force_app_launch))
                super().__init__(appium_server_url, device_name, force_app_launch)

        def cleanup(appium_server_url, device_name):
            events.append(("cleanup", appium_server_url, device_name))

        result = send_text_messages(
            appium_server_url="http://127.0.0.1:6002",
            device_name="test-device",
            receiver="文件传输助手",
            messages=["hello"],
            operator_factory=RecordingOperator,
            startup_wait_seconds=0,
            restart_wait_seconds=0,
            preflight_cleanup=cleanup,
        )

        self.assertTrue(result.success)
        self.assertEqual(events[0], ("cleanup", "http://127.0.0.1:6002", "test-device"))
        self.assertEqual(events[1], ("operator", False))

    def test_cleanup_deletes_device_sessions_and_stops_uiautomator2(self):
        http_calls = []
        command_calls = []
        get_count = 0

        def http_request(method, url):
            nonlocal get_count
            http_calls.append((method, url))
            if method == "GET":
                get_count += 1
                if get_count > 1:
                    return {"value": []}
                return {
                    "value": [
                        {
                            "id": "matching-session",
                            "capabilities": {"udid": "test-device"},
                        },
                        {
                            "id": "other-session",
                            "capabilities": {"udid": "other-device"},
                        },
                    ]
                }
            return {"value": None}

        def command_runner(command, timeout):
            command_calls.append((command, timeout))

        cleanup_appium_device(
            appium_server_url="http://127.0.0.1:6002",
            device_name="test-device",
            http_request=http_request,
            command_runner=command_runner,
            sleeper=lambda _seconds: None,
        )

        self.assertIn(("GET", "http://127.0.0.1:6002/sessions"), http_calls)
        self.assertIn(
            ("DELETE", "http://127.0.0.1:6002/session/matching-session"),
            http_calls,
        )
        self.assertNotIn(
            ("DELETE", "http://127.0.0.1:6002/session/other-session"),
            http_calls,
        )
        self.assertIn(
            (
                [
                    "adb",
                    "-s",
                    "test-device",
                    "shell",
                    "am",
                    "force-stop",
                    "io.appium.uiautomator2.server",
                ],
                10,
            ),
            command_calls,
        )
        self.assertIn(
            (
                [
                    "adb",
                    "-s",
                    "test-device",
                    "shell",
                    "input",
                    "keyevent",
                    "BACK",
                ],
                10,
            ),
            command_calls,
        )
        self.assertIn(
            (
                [
                    "adb",
                    "-s",
                    "test-device",
                    "shell",
                    "am",
                    "force-stop",
                    "io.appium.uiautomator2.server.test",
                ],
                10,
            ),
            command_calls,
        )

    def test_cleanup_retries_when_sessions_endpoint_is_temporarily_busy(self):
        http_calls = []

        def http_request(method, url):
            http_calls.append((method, url))
            if len(http_calls) == 1:
                raise TimeoutError("appium is busy")
            return {"value": []}

        cleanup_appium_device(
            appium_server_url="http://127.0.0.1:6002",
            device_name="test-device",
            http_request=http_request,
            command_runner=lambda _command, _timeout: None,
            sleeper=lambda _seconds: None,
        )

        self.assertEqual(
            http_calls,
            [
                ("GET", "http://127.0.0.1:6002/sessions"),
                ("GET", "http://127.0.0.1:6002/sessions"),
            ],
        )

    def test_cleanup_raises_when_existing_session_cannot_be_cleared(self):
        def http_request(method, _url):
            if method == "GET":
                return {
                    "value": [
                        {
                            "id": "stuck-session",
                            "capabilities": {"udid": "test-device"},
                        }
                    ]
                }
            return {"value": None}

        with self.assertRaises(DeviceNotReadyError):
            cleanup_appium_device(
                appium_server_url="http://127.0.0.1:6002",
                device_name="test-device",
                http_request=http_request,
                command_runner=lambda _command, _timeout: None,
                sleeper=lambda _seconds: None,
                max_attempts=2,
            )

    def test_retries_stale_object_errors(self):
        attempts = []
        sleeps = []

        def operation():
            attempts.append("called")
            if len(attempts) == 1:
                raise RuntimeError("androidx.test.uiautomator.StaleObjectException")
            return "ok"

        result = _run_stale_retry(
            operation,
            attempts=3,
            sleeper=lambda seconds: sleeps.append(seconds),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [0.5])

    def test_does_not_retry_non_stale_errors(self):
        attempts = []

        def operation():
            attempts.append("called")
            raise RuntimeError("send button missing")

        with self.assertRaises(RuntimeError):
            _run_stale_retry(
                operation,
                attempts=3,
                sleeper=lambda _seconds: None,
            )

        self.assertEqual(len(attempts), 1)

    def test_recent_chat_xpaths_include_text_view_locator(self):
        xpaths = _recent_chat_xpaths("Zacks_大沙河限定免费")

        self.assertIn(
            "//android.widget.TextView[@text='Zacks_大沙河限定免费']",
            xpaths,
        )
        self.assertIn(
            "//android.view.View[@text='Zacks_大沙河限定免费']",
            xpaths,
        )

    def test_xpath_literal_handles_single_quotes(self):
        self.assertEqual(_xpath_literal("Bob's Group"), '"Bob\'s Group"')

    def test_visual_text_normalization_ignores_ocr_punctuation(self):
        self.assertEqual(
            _normalize_visual_text("_Zacks-大沙河限定免费"),
            _normalize_visual_text("Zacks_大沙河限定免费"),
        )

    def test_visual_ocr_threshold_keeps_wechat_green_text_dark(self):
        class Image:
            def __init__(self, pixels):
                self.pixels = pixels

            def point(self, transform):
                return Image([transform(pixel) for pixel in self.pixels])

        image = Image([117, VISUAL_OCR_THRESHOLD - 1, 245])

        self.assertEqual(_threshold_ocr_image(image).pixels, [0, 0, 255])

    def test_visual_text_match_accepts_long_truncated_chat_name(self):
        self.assertGreater(
            _visual_text_match_score(
                "Zacks网球场预定小助手_2",
                "Zacks网球场预定小助手_2群",
            ),
            0,
        )

    def test_visual_text_match_rejects_short_ambiguous_prefix(self):
        self.assertEqual(
            _visual_text_match_score(
                "Zacks网球场",
                "Zacks网球场预定小助手_2群",
            ),
            0,
        )

    def test_visual_text_match_rejects_similar_group_suffix(self):
        self.assertEqual(
            _visual_text_match_score(
                "Zacks网球场预定小助手_1群",
                "Zacks网球场预定小助手_2群",
            ),
            0,
        )

    def test_visual_text_match_rejects_missing_numbered_group_suffix(self):
        self.assertEqual(
            _visual_text_match_score(
                "Zacks网球场预定小助手",
                "Zacks网球场预定小助手_2群",
            ),
            0,
        )

    def test_recent_chat_match_allows_number_hidden_by_display_truncation(self):
        self.assertGreater(
            _visual_text_match_score(
                "Zacks网球场预定小助手_",
                "Zacks网球场预定小助手_2群",
                allow_truncated_numeric_suffix=True,
            ),
            0.9,
        )
        self.assertEqual(
            _visual_text_match_score(
                "Zacks网球场预定小助手_1群",
                "Zacks网球场预定小助手_2群",
                allow_truncated_numeric_suffix=True,
            ),
            0,
        )

    def test_visual_text_match_accepts_chinese_ocr_error_with_same_group_number(self):
        self.assertGreaterEqual(
            _visual_text_match_score(
                "Zacks网球场预订小助于_2群",
                "Zacks网球场预定小助手_2群",
            ),
            0.72,
        )

    def test_parses_tesseract_lines_back_to_screen_coordinates(self):
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop"
            "\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t10\t20\t50\t10\t90\tZacks\n"
            "5\t1\t1\t1\t1\t2\t60\t20\t100\t10\t90\t大沙河限定免费\n"
        )

        lines = _parse_tesseract_tsv(
            tsv,
            origin_x=100,
            origin_y=200,
            scale=0.5,
        )

        self.assertEqual(
            lines,
            [
                OcrLine(
                    text="Zacks大沙河限定免费",
                    left=120,
                    top=240,
                    right=420,
                    bottom=260,
                )
            ],
        )

    def test_finds_large_green_visual_send_button(self):
        width = 100
        pixels = [(245, 245, 245)] * (width * 50)
        for y in range(10, 40):
            for x in range(20, 80):
                pixels[y * width + x] = (7, 193, 96)

        button = _green_button_bounds(
            pixels,
            width=width,
            origin_x=800,
            origin_y=1000,
        )

        self.assertEqual(
            button,
            OcrLine(
                text="visual-send-button",
                left=820,
                top=1010,
                right=880,
                bottom=1040,
            ),
        )

    @patch("wechat_sender.appium_text_sender.subprocess.run")
    def test_visual_input_clear_uses_batched_adb_key_events(self, mock_run):
        mock_run.return_value.returncode = 0
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.device_name = "test-device"
        regions = []
        operator._find_visual_green_button = lambda *, region: regions.append(region)

        operator._clear_visual_input()

        self.assertEqual(mock_run.call_count, 2)
        delete_command = mock_run.call_args_list[1].args[0]
        self.assertEqual(
            delete_command[:7], ["adb", "-s", "test-device", "shell", "input", "keyevent", "67"]
        )
        self.assertEqual(delete_command.count("67"), VISUAL_INPUT_CLEAR_KEYSTROKES)
        self.assertEqual(regions, [VISUAL_SEND_BUTTON_REGION])
        self.assertEqual(VISUAL_SEND_BUTTON_REGION, (0.78, 0.57, 1.0, 0.66))

    @patch("wechat_sender.appium_text_sender.time.sleep")
    def test_visual_send_checks_only_the_bottom_input_row(self, _mock_sleep):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.set_clipboard_text = lambda _value: None
        operator.driver.press_keycode = lambda _value: None
        operator.current_receiver = "target-chat"
        operator._is_verified_chat_open = lambda _receiver: True
        operator._tap_ratio = lambda *_args: None
        operator._clear_visual_input = lambda: None
        regions = []
        buttons = iter(
            [
                OcrLine("visual-send-button", 850, 1350, 1050, 1450),
                None,
            ]
        )
        operator._find_visual_green_button = lambda *, region: (
            regions.append(region) or next(buttons)
        )
        operator._find_visual_line = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("green send button should be used")
        )

        operator._send_visual_messages(["hello"])

        self.assertEqual(
            regions,
            [VISUAL_SEND_BUTTON_REGION, VISUAL_SEND_BUTTON_REGION],
        )

    def test_visual_only_device_opens_visible_chat_without_scrolling(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.current_receiver = None
        operator.is_at_main_page = lambda: True
        operator._click_accessible_text = lambda _value: False
        operator._has_accessible_wechat_controls = lambda: False
        operator._find_accessible_text_candidates = lambda *_args, **_kwargs: []
        operator._wait_for_chat = lambda _receiver, timeout: bool(timeout)
        operator._find_visual_lines = lambda *_args, **_kwargs: [
            OcrLine(
                text="Zacks_大沙河限定免费",
                left=200,
                top=600,
                right=700,
                bottom=680,
            )
        ]

        opened = operator.is_contact_in_recent_chats("Zacks_大沙河限定免费")

        self.assertTrue(opened)
        self.assertEqual(operator.driver.swipes, [])
        self.assertEqual(
            operator.driver.scripts,
            [("mobile: clickGesture", {"x": 450, "y": 640})],
        )

    def test_partial_accessibility_still_checks_visible_chat_without_scrolling(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.current_receiver = None
        operator.is_at_main_page = lambda: True
        operator._click_accessible_text = lambda _value: False
        operator._has_accessible_wechat_controls = lambda: True
        operator._find_accessible_text_candidates = lambda *_args, **_kwargs: []
        operator._wait_for_chat = lambda _receiver, timeout: bool(timeout)
        operator._find_visual_lines = lambda *_args, **_kwargs: [
            OcrLine(
                text="Zacks网球场预定小助手_2",
                left=200,
                top=600,
                right=780,
                bottom=680,
            )
        ]

        opened = operator.is_contact_in_recent_chats("Zacks网球场预定小助手_2群")

        self.assertTrue(opened)
        self.assertEqual(operator.driver.swipes, [])

    def test_accessible_partial_chat_name_is_checked_before_ocr(self):
        class Element:
            text = "Zacks网球场预订小助于_2群"
            rect = {"x": 100, "y": 400, "width": 700, "height": 80}

            def get_attribute(self, _name):
                return ""

            def click(self):
                return None

        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.current_receiver = None
        operator.is_at_main_page = lambda: True
        operator._click_accessible_text = lambda _value: False
        operator._find_accessible_text_candidates = lambda *_args, **_kwargs: [Element()]
        operator._wait_for_chat = lambda _receiver, timeout: bool(timeout)
        operator._find_visual_line = lambda *_args, **_kwargs: None

        opened = operator.is_contact_in_recent_chats("Zacks网球场预定小助手_2群")

        self.assertTrue(opened)
        self.assertEqual(operator.driver.swipes, [])

    def test_non_chat_wechat_page_is_not_accepted_as_target_chat(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".plugin.profile.ui.ContactInfoUI"
        operator._has_accessible_title = lambda _receiver: True
        operator._find_visual_line = lambda *_args, **_kwargs: OcrLine(
            text="Zacks网球场预定小助手_2群",
            left=200,
            top=60,
            right=800,
            bottom=120,
        )

        self.assertFalse(operator._is_visual_chat_page("Zacks网球场预定小助手_2群"))

    def test_chat_activity_requires_matching_title(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.chatting.ChattingUI"
        operator._has_accessible_title = lambda _receiver: False
        operator._find_visual_line = lambda *_args, **_kwargs: None

        self.assertFalse(operator._is_visual_chat_page("Zacks网球场预定小助手_2群"))

    def test_launcher_activity_accepts_verified_chat_title(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.LauncherUI"
        operator._is_visual_main_page = lambda: False
        operator._has_accessible_title = lambda _receiver: True

        self.assertTrue(operator._is_visual_chat_page("Zacks网球场预定小助手_2群"))

    def test_launcher_main_page_is_not_accepted_as_chat(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.LauncherUI"
        operator._is_visual_main_page = lambda: True
        operator._has_accessible_title = lambda _receiver: True

        self.assertFalse(operator._is_visual_chat_page("Zacks网球场预定小助手_2群"))

    def test_visual_main_page_ignores_chat_content_above_bottom_navigation(self):
        class NavigationRegion:
            def __init__(self, green_pixels):
                self.green_pixels = green_pixels

            def getdata(self):
                return [(0, 180, 80)] * self.green_pixels + [(240, 240, 240)]

        class Screenshot:
            size = (1080, 2340)

            def __init__(self):
                self.crop_bounds = None

            def convert(self, _mode):
                return self

            def crop(self, bounds):
                self.crop_bounds = bounds
                green_pixels = 150 if bounds[1] < 2164 else 0
                return NavigationRegion(green_pixels)

        screenshot = Screenshot()
        image_module = ModuleType("PIL.Image")
        image_module.open = lambda _value: screenshot
        pil_module = ModuleType("PIL")
        pil_module.Image = image_module

        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.get_screenshot_as_png = lambda: b"png"

        with patch.dict("sys.modules", {"PIL": pil_module, "PIL.Image": image_module}):
            self.assertFalse(operator._is_visual_main_page())

        self.assertEqual(VISUAL_MAIN_NAVIGATION_TOP_RATIO, 0.925)
        self.assertEqual(
            screenshot.crop_bounds,
            (0, 2164, 292, 2340),
        )

    def test_send_reuses_an_already_open_verified_target_chat(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.current_receiver = None
        operator.is_target_chat_open = lambda _receiver: True
        operator.is_contact_in_recent_chats = lambda _receiver: (_ for _ in ()).throw(
            AssertionError("recent chats must not be opened")
        )
        operator._search_and_open_chat = lambda _receiver: (_ for _ in ()).throw(
            AssertionError("search must not be opened")
        )
        operator._is_verified_chat_open = lambda receiver: (operator.current_receiver == receiver)
        operator._has_accessible_message_input = lambda: False
        sent = []
        operator._send_visual_messages = lambda messages: sent.extend(messages)
        operator.return_to_chats = lambda: None

        operator.send_message("target-chat", ["hello"])

        self.assertEqual(sent, ["hello"])

    def test_verified_chat_does_not_repeat_unstable_title_ocr(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.chatting.ChattingUI"
        operator.current_receiver = "Zacks网球场预定小助手_2群"
        operator._is_visual_chat_page = lambda _receiver: (_ for _ in ()).throw(
            AssertionError("strict title OCR must not repeat after verification")
        )

        self.assertTrue(operator._is_verified_chat_open("Zacks网球场预定小助手_2群"))

    def test_return_to_chats_clears_verified_launcher_chat(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.LauncherUI"
        operator.current_receiver = "Zacks网球场预定小助手_2群"
        operator.is_at_main_page = lambda: True

        appiumby_module = ModuleType("appium.webdriver.common.appiumby")

        class StubAppiumBy:
            ID = "id"

        appiumby_module.AppiumBy = StubAppiumBy
        with patch.dict(
            "sys.modules",
            {
                "appium": ModuleType("appium"),
                "appium.webdriver": ModuleType("appium.webdriver"),
                "appium.webdriver.common": ModuleType("appium.webdriver.common"),
                "appium.webdriver.common.appiumby": appiumby_module,
            },
        ):
            operator.return_to_chats()

        self.assertIsNone(operator.current_receiver)
        self.assertFalse(operator._is_verified_chat_open("Zacks网球场预定小助手_2群"))

    def test_search_tries_next_visual_result_after_wrong_entry(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.FTSMainUI"
        operator.driver.set_clipboard_text = lambda _value: None
        operator.driver.press_keycode = lambda _value: None
        operator._wait_for_search_page = lambda timeout: bool(timeout)
        operator._click_accessible_text = lambda _receiver: False
        candidates = [
            OcrLine("Zacks网球场预定小助手_2群", 100, 300, 800, 360),
            OcrLine("Zacks网球场预定小助手_2群", 100, 500, 800, 560),
        ]
        operator._find_visual_lines = lambda *_args, **_kwargs: candidates
        opened = iter([False, True])
        operator._wait_for_chat = lambda _receiver, timeout: next(opened) and bool(timeout)
        returns = []
        operator._return_to_search_results = lambda: returns.append("back")

        appiumby_module = ModuleType("appium.webdriver.common.appiumby")

        class StubAppiumBy:
            ACCESSIBILITY_ID = "accessibility id"
            XPATH = "xpath"

        appiumby_module.AppiumBy = StubAppiumBy
        with patch.dict(
            "sys.modules",
            {
                "appium": ModuleType("appium"),
                "appium.webdriver": ModuleType("appium.webdriver"),
                "appium.webdriver.common": ModuleType("appium.webdriver.common"),
                "appium.webdriver.common.appiumby": appiumby_module,
            },
        ):
            operator._search_and_open_chat("Zacks网球场预定小助手_2群")

        self.assertEqual(returns, ["back"])
        self.assertEqual(operator.current_receiver, "Zacks网球场预定小助手_2群")
        self.assertEqual(len(operator.driver.scripts), 3)

    def test_search_tries_next_accessible_result_after_wrong_entry(self):
        class Element:
            def __init__(self, top):
                self.rect = {"x": 100, "y": top, "width": 700, "height": 80}

        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.FTSMainUI"
        operator.driver.set_clipboard_text = lambda _value: None
        operator.driver.press_keycode = lambda _value: None
        operator._wait_for_search_page = lambda timeout: bool(timeout)
        operator._find_accessible_text_candidates = lambda *_args, **_kwargs: [
            Element(300),
            Element(500),
        ]
        operator._find_visual_lines = lambda *_args, **_kwargs: []
        opened = iter([False, True])
        operator._wait_for_chat = lambda _receiver, timeout: next(opened) and bool(timeout)
        returns = []
        operator._return_to_search_results = lambda: returns.append("back")

        appiumby_module = ModuleType("appium.webdriver.common.appiumby")

        class StubAppiumBy:
            XPATH = "xpath"

        appiumby_module.AppiumBy = StubAppiumBy
        with patch.dict(
            "sys.modules",
            {
                "appium": ModuleType("appium"),
                "appium.webdriver": ModuleType("appium.webdriver"),
                "appium.webdriver.common": ModuleType("appium.webdriver.common"),
                "appium.webdriver.common.appiumby": appiumby_module,
            },
        ):
            operator._search_and_open_chat("Zacks_大沙河限定免费")

        self.assertEqual(returns, ["back"])
        self.assertEqual(operator.current_receiver, "Zacks_大沙河限定免费")
        self.assertEqual(
            operator.driver.scripts[-2:],
            [
                ("mobile: clickGesture", {"x": 450, "y": 340}),
                ("mobile: clickGesture", {"x": 450, "y": 540}),
            ],
        )

    def test_search_button_is_accepted_when_click_leaves_main_page(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator._wait_for_search_page = lambda timeout: False
        operator.is_at_main_page = lambda: False

        class SearchButton:
            rect = {"x": 800, "y": 80, "width": 100, "height": 100}

            def click(self):
                return None

        operator.driver.find_elements = lambda **_kwargs: [SearchButton()]
        appiumby_module = ModuleType("appium.webdriver.common.appiumby")

        class StubAppiumBy:
            ACCESSIBILITY_ID = "accessibility id"

        appiumby_module.AppiumBy = StubAppiumBy
        with patch.dict(
            "sys.modules",
            {
                "appium": ModuleType("appium"),
                "appium.webdriver": ModuleType("appium.webdriver"),
                "appium.webdriver.common": ModuleType("appium.webdriver.common"),
                "appium.webdriver.common.appiumby": appiumby_module,
            },
        ):
            self.assertTrue(operator._open_search_from_main_page())

    def test_launcher_search_page_is_detected_from_top_input(self):
        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.current_activity = ".ui.LauncherUI"
        operator._activity_ends_with = lambda suffix: suffix == "LauncherUI"
        operator._has_accessible_search_input = lambda: True

        self.assertTrue(operator._is_accessible_search_page())

    def test_chat_input_is_not_treated_as_search_input(self):
        class Input:
            rect = {"x": 0, "y": 2000, "width": 900, "height": 100}

        operator = TextWeChatOperator.__new__(TextWeChatOperator)
        operator.driver = VisualOnlyDriver()
        operator.driver.find_elements = lambda **_kwargs: [Input()]

        appiumby_module = ModuleType("appium.webdriver.common.appiumby")

        class StubAppiumBy:
            XPATH = "xpath"

        appiumby_module.AppiumBy = StubAppiumBy
        with patch.dict(
            "sys.modules",
            {
                "appium": ModuleType("appium"),
                "appium.webdriver": ModuleType("appium.webdriver"),
                "appium.webdriver.common": ModuleType("appium.webdriver.common"),
                "appium.webdriver.common.appiumby": appiumby_module,
            },
        ):
            self.assertFalse(operator._has_accessible_search_input())

    def test_restarts_wechat_when_initial_session_is_not_at_main_page(self):
        result = send_text_messages(
            appium_server_url="http://appium.test:6002",
            device_name="test-device",
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

    def test_waits_after_closing_before_restart(self):
        events = []

        class RecordingRestartOperator(FakeOperator):
            def __init__(self, appium_server_url, device_name, force_app_launch=False):
                events.append(("operator", force_app_launch))
                super().__init__(appium_server_url, device_name, force_app_launch)
                self.at_main_page = force_app_launch

            def close(self):
                events.append(("close", self.force_app_launch))
                super().close()

        def sleeper(seconds):
            events.append(("sleep", seconds))

        result = send_text_messages(
            appium_server_url="http://appium.test:6002",
            device_name="test-device",
            receiver="文件传输助手",
            messages=["hello"],
            operator_factory=RecordingRestartOperator,
            startup_wait_seconds=0,
            close_wait_seconds=1,
            restart_wait_seconds=0,
            sleeper=sleeper,
        )

        self.assertTrue(result.success)
        self.assertEqual(
            events[:4],
            [
                ("operator", False),
                ("sleep", 0),
                ("close", False),
                ("sleep", 1),
            ],
        )
        self.assertEqual(events[4], ("operator", True))

    def test_attempts_to_return_to_chats_after_restart_before_failing(self):
        result = send_text_messages(
            appium_server_url="http://appium.test:6002",
            device_name="test-device",
            receiver="文件传输助手",
            messages=["hello"],
            operator_factory=RecoveringRestartOperator,
            startup_wait_seconds=0,
            restart_wait_seconds=0,
        )

        self.assertTrue(result.success)
        self.assertEqual(len(FakeOperator.created), 2)
        self.assertEqual(FakeOperator.created[1].return_to_chats_calls, 1)
        self.assertEqual(FakeOperator.created[1].sent, [("文件传输助手", ["hello"])])

    def test_invalid_messages_raise_invalid_request(self):
        with self.assertRaises(InvalidSendRequestError) as error:
            send_text_messages(
                appium_server_url="http://appium.test:6002",
                device_name="test-device",
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
                appium_server_url="http://appium.test:6002",
                device_name="test-device",
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
