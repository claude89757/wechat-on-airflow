import hashlib
import unittest
from unittest.mock import call, patch

from wechat_airflow.notifications import wechat as wechat_send_api


class FakeResponse:
    status_code = 200
    text = '{"success": true}'

    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {"success": True, "sent_count": 1}
        self.status_code = status_code
        self.text = str(self._payload)

    def json(self):
        return self._payload


class WeChatSendApiTest(unittest.TestCase):
    def variable_getter(self, key, default=None, deserialize_json=False):
        values = {
            "WECHAT_SEND_API_URL": "http://sender.example/v1/wechat/send",
            "WECHAT_SEND_DEVICE_NAME": "device-from-variable",
            "WECHAT_SEND_TIMEOUT_SECONDS": "400",
            "WECHAT_SEND_RETRY_COUNT": "1",
            "WECHAT_SEND_RETRY_DELAY_SECONDS": "0",
        }
        return values.get(key, default)

    def idempotency_key(self, receiver, messages, device_name="device-from-variable"):
        return hashlib.sha256("\0".join([receiver, device_name, *messages]).encode()).hexdigest()

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_uses_airflow_variable_endpoint(self, mock_post):
        mock_post.return_value = FakeResponse({"success": True, "sent_count": 2})

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            result = wechat_send_api.send_wechat_text(" 文件传输助手 ", ["hello", "world"])

        self.assertEqual(result["sent_count"], 2)
        mock_post.assert_called_once_with(
            "http://sender.example/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello", "world"],
                "device_name": "device-from-variable",
                "idempotency_key": self.idempotency_key(
                    "文件传输助手",
                    ["hello", "world"],
                ),
            },
            timeout=400,
        )

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_allows_explicit_device_name(self, mock_post):
        mock_post.return_value = FakeResponse()

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            wechat_send_api.send_wechat_text("Zacks", ["hello"], device_name="explicit-device")

        self.assertEqual(mock_post.call_args.kwargs["json"]["device_name"], "explicit-device")
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["idempotency_key"],
            self.idempotency_key("Zacks", ["hello"], "explicit-device"),
        )

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_raises_on_api_failure(self, mock_post):
        mock_post.return_value = FakeResponse(
            {"success": False, "error": "send_failed", "message": "send button missing"},
            status_code=500,
        )

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("send_failed", str(error.exception))
        mock_post.assert_called_once()

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_wraps_request_errors(self, mock_post):
        mock_post.side_effect = wechat_send_api.requests.Timeout("timeout")

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("request failed", str(error.exception))

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_timeout_floors_below_the_device_queue_wait(self, mock_post):
        mock_post.return_value = FakeResponse()

        def getter(key, default=None, deserialize_json=False):
            values = {
                "WECHAT_SEND_API_URL": "http://sender.example/v1/wechat/send",
                "WECHAT_SEND_DEVICE_NAME": "device-from-variable",
                "WECHAT_SEND_TIMEOUT_SECONDS": "30",
                "WECHAT_SEND_RETRY_COUNT": "1",
                "WECHAT_SEND_RETRY_DELAY_SECONDS": "0",
            }
            return values.get(key, default)

        with patch("wechat_airflow.notifications.wechat._get_variable", side_effect=getter):
            wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(
            mock_post.call_args.kwargs["timeout"],
            wechat_send_api.MIN_SEND_TIMEOUT_SECONDS,
        )

    @patch("wechat_airflow.notifications.wechat.time.sleep")
    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_device_busy_waits_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            FakeResponse(
                {"success": False, "error": "device_busy", "message": "busy"},
                status_code=409,
            ),
            FakeResponse({"success": True, "sent_count": 1}),
        ]

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            result = wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(wechat_send_api.DEVICE_BUSY_RETRY_DELAY_SECONDS)

    @patch("wechat_airflow.notifications.wechat.time.sleep")
    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_device_busy_retries_before_raising(self, mock_post, mock_sleep):
        mock_post.return_value = FakeResponse(
            {"success": False, "error": "device_busy", "message": "busy"},
            status_code=409,
        )

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(error.exception.error_code, "device_busy")
        self.assertEqual(mock_post.call_count, wechat_send_api.DEVICE_BUSY_RETRY_LIMIT)
        self.assertEqual(
            mock_sleep.call_args_list,
            [call(wechat_send_api.DEVICE_BUSY_RETRY_DELAY_SECONDS)]
            * (wechat_send_api.DEVICE_BUSY_RETRY_LIMIT - 1),
        )

    @patch("wechat_airflow.notifications.wechat.send_wechat_text")
    def test_send_wechat_text_to_chatrooms_normalizes_lines(self, mock_send):
        wechat_send_api.send_wechat_text_to_chatrooms(" A \n\n B ", "hello")

        self.assertEqual(
            [call.args for call in mock_send.call_args_list],
            [("A", ["hello"]), ("B", ["hello"])],
        )

    def test_best_effort_send_continues_after_failure_and_records_fallback(self):
        variables = {
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default=None, deserialize_json=False):
            return variables.get(key, default)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        with (
            patch("wechat_airflow.notifications.wechat._get_variable", side_effect=get_variable),
            patch("wechat_airflow.notifications.wechat._set_variable", side_effect=set_variable),
            patch(
                "wechat_airflow.notifications.wechat.send_wechat_text",
                side_effect=[
                    wechat_send_api.WeChatSendApiError("sender unavailable"),
                    {"success": True, "sent_count": 1},
                ],
            ) as mock_send,
            patch(
                "wechat_airflow.notifications.wechat._utc_now",
                return_value="2026-07-14T15:00:00+00:00",
            ),
        ):
            results = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A", "B"],
                "hello",
                source="test-dag",
            )

        self.assertEqual(
            mock_send.call_args_list,
            [call("A", ["hello"], device_name=None), call("B", ["hello"], device_name=None)],
        )
        self.assertEqual([result["success"] for result in results], [False, True])
        self.assertEqual(len(variables["WECHAT_SEND_FALLBACK_OUTBOX"]), 1)
        self.assertEqual(variables["WECHAT_SEND_FALLBACK_OUTBOX"][0]["receiver"], "A")
        self.assertEqual(variables["WECHAT_SEND_FALLBACK_OUTBOX"][0]["source"], "test-dag")

    def test_best_effort_send_merges_duplicate_fallback_entries(self):
        variables = {
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default=None, deserialize_json=False):
            return variables.get(key, default)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        with (
            patch("wechat_airflow.notifications.wechat._get_variable", side_effect=get_variable),
            patch("wechat_airflow.notifications.wechat._set_variable", side_effect=set_variable),
            patch(
                "wechat_airflow.notifications.wechat.send_wechat_text",
                side_effect=wechat_send_api.WeChatSendApiError("sender unavailable"),
            ),
            patch(
                "wechat_airflow.notifications.wechat._utc_now",
                side_effect=["2026-07-14T15:00:00+00:00", "2026-07-14T15:01:00+00:00"],
            ),
        ):
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A"], "hello", source="test-dag"
            )
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A"], "hello", source="test-dag"
            )

        fallback = variables["WECHAT_SEND_FALLBACK_OUTBOX"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["attempt_count"], 2)
        self.assertEqual(fallback[0]["first_failed_at"], "2026-07-14T15:00:00+00:00")
        self.assertEqual(fallback[0]["last_failed_at"], "2026-07-14T15:01:00+00:00")

    @patch(
        "wechat_airflow.notifications.wechat._record_failed_send",
        side_effect=RuntimeError("variable unavailable"),
    )
    @patch(
        "wechat_airflow.notifications.wechat.send_wechat_text",
        side_effect=wechat_send_api.WeChatSendApiError("sender unavailable"),
    )
    def test_best_effort_send_swallows_fallback_persistence_failure(self, mock_send, mock_record):
        results = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
            ["A"],
            "hello",
            source="test-dag",
        )

        self.assertEqual(results[0]["success"], False)
        mock_send.assert_called_once_with("A", ["hello"], device_name=None)
        mock_record.assert_called_once()

    def test_best_effort_attaches_booking_link_once_then_shares_cooldown(self):
        variables = {
            "WECHAT_BOOKING_LINK_LAST_SENT": {},
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default=None, deserialize_json=False):
            return variables.get(key, default)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        class Evening(wechat_send_api.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 18, 18, 5, tzinfo=tz)

        with (
            patch("wechat_airflow.notifications.wechat.datetime", Evening),
            patch("wechat_airflow.notifications.wechat._get_variable", side_effect=get_variable),
            patch("wechat_airflow.notifications.wechat._set_variable", side_effect=set_variable),
            patch("wechat_airflow.notifications.wechat.wechat_delivery_allowed", return_value=True),
            patch(
                "wechat_airflow.notifications.wechat.send_wechat_text",
                return_value={"success": True, "sent_count": 1},
            ) as mock_send,
        ):
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["Zacks_A"],
                "【深圳湾1号场】星期二(08-18)空场: 18:00-19:00",
                source="深圳湾网球场巡检",
                booking_venue_id="szw",
            )
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["Zacks_A"],
                "【大湾区网球场1号场】星期二(08-18)空场: 18:00-19:00",
                source="大湾区网球场巡检",
                booking_venue_id="gba",
            )

        first_message = mock_send.call_args_list[0].args[1][0]
        second_message = mock_send.call_args_list[1].args[1][0]
        self.assertTrue(first_message.endswith("#小程序://未来荟/XL8wsbG5boBuZSl"))
        self.assertNotIn("#小程序://", second_message)

    def test_best_effort_releases_booking_link_claim_after_send_failure(self):
        variables = {
            "WECHAT_BOOKING_LINK_LAST_SENT": {},
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default=None, deserialize_json=False):
            return variables.get(key, default)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        class Evening(wechat_send_api.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 18, 18, 5, tzinfo=tz)

        with (
            patch("wechat_airflow.notifications.wechat.datetime", Evening),
            patch("wechat_airflow.notifications.wechat._get_variable", side_effect=get_variable),
            patch("wechat_airflow.notifications.wechat._set_variable", side_effect=set_variable),
            patch("wechat_airflow.notifications.wechat.wechat_delivery_allowed", return_value=True),
            patch(
                "wechat_airflow.notifications.wechat._utc_now",
                return_value="2026-08-18T10:05:00+00:00",
            ),
            patch(
                "wechat_airflow.notifications.wechat.send_wechat_text",
                side_effect=[
                    wechat_send_api.WeChatSendApiError("sender unavailable"),
                    {"success": True, "sent_count": 1},
                ],
            ) as mock_send,
        ):
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["Zacks_A"],
                "slot-a",
                source="深圳湾网球场巡检",
                booking_venue_id="szw",
            )
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["Zacks_A"],
                "slot-b",
                source="大湾区网球场巡检",
                booking_venue_id="gba",
            )

        self.assertTrue(
            mock_send.call_args_list[1].args[1][0].endswith("#小程序://未来荟/XL8wsbG5boBuZSl")
        )


if __name__ == "__main__":
    unittest.main()
