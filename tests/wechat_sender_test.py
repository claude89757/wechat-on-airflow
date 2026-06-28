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
