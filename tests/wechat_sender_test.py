import unittest

from wechat_sender.appium_text_sender import (
    DeviceNotReadyError,
    InvalidSendRequestError,
    SendFailedError,
    SendResult,
    _recent_chat_xpaths,
    _run_stale_retry,
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
