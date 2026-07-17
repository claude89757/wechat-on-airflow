import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from wechat_airflow.notifications import email as venue_email


class VenueEmailTest(unittest.TestCase):
    def setUp(self):
        self.variables = {
            "SZW_EMAIL_LIST": [
                "a@example.com",
                "b@example.com",
            ],
            "SYSH_EMAIL_LIST": [
                "a@example.com",
                "b@example.com",
            ],
            venue_email.EMAIL_TEMPLATE_ID_VAR: "54297",
            venue_email.EMAIL_FROM_ADDRESS_VAR: "Sender <sender@example.com>",
            venue_email.EMAIL_REPLY_TO_VAR: "reply@example.com",
            venue_email.EMAIL_SEND_FALLBACK_OUTBOX_VAR: [],
            venue_email.EMAIL_SEND_FALLBACK_MAX_ITEMS_VAR: "200",
        }

    def get_variable(self, key, default_var=None, deserialize_json=False):
        return self.variables.get(key, default_var)

    def set_variable(self, key, value, serialize_json=False):
        self.variables[key] = value

    def test_batch_sends_all_new_slots_in_one_email(self):
        notifications = [
            {
                "date": "07-15",
                "court_name": "深圳湾1号场",
                "start_time": "18:00",
                "end_time": "19:00",
            },
            {
                "date": "07-16",
                "court_name": "深圳湾2号场",
                "start_time": "20:00",
                "end_time": "21:00",
            },
        ]

        with (
            patch(
                "wechat_airflow.notifications.email._get_variable", side_effect=self.get_variable
            ),
            patch(
                "wechat_airflow.notifications.email._set_variable", side_effect=self.set_variable
            ),
            patch("wechat_airflow.notifications.email._today", return_value=date(2026, 7, 16)),
            patch(
                "wechat_airflow.notifications.email.send_template_email",
                return_value={"success": True, "message_id": "message-1"},
            ) as mock_send,
        ):
            result = venue_email.send_venue_email_batch(
                "深圳湾网球场巡检",
                notifications,
                recipients_var="SZW_EMAIL_LIST",
            )

        self.assertTrue(result["success"])
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs["recipients"], ["a@example.com", "b@example.com"])
        self.assertEqual(call_kwargs["subject"], "深圳湾1号场 07-15 星期三 18:00-19:00")
        self.assertEqual(call_kwargs["template_id"], 54297)
        self.assertEqual(call_kwargs["from_email"], "Sender <sender@example.com>")
        self.assertEqual(call_kwargs["reply_to"], "reply@example.com")
        self.assertEqual(
            call_kwargs["template_data"],
            {
                "FREE_TIME": (
                    "深圳湾1号场 07-15 星期三 18:00-19:00\n深圳湾2号场 07-16 星期四 20:00-21:00"
                )
            },
        )
        self.assertNotIn("发现", call_kwargs["subject"])
        self.assertEqual(self.variables[venue_email.EMAIL_SEND_FALLBACK_OUTBOX_VAR], [])

    def test_weekday_uses_nearest_year_across_new_year(self):
        notification = {
            "date": "01-01",
            "court_name": "测试场",
            "start_time": "09:00",
            "end_time": "10:00",
        }

        with patch("wechat_airflow.notifications.email._today", return_value=date(2026, 12, 31)):
            line = venue_email._format_notification(notification)

        self.assertEqual(line, "测试场 01-01 星期五 09:00-10:00")

    def test_approved_template_can_be_activated_without_redeploy(self):
        self.variables[venue_email.EMAIL_TEMPLATE_ID_VAR] = "33340"
        notifications = [
            {
                "date": "07-16",
                "court_name": "深圳湾1号场",
                "start_time": "18:00",
                "end_time": "19:00",
            }
        ]

        with (
            patch(
                "wechat_airflow.notifications.email._get_variable", side_effect=self.get_variable
            ),
            patch(
                "wechat_airflow.notifications.email._set_variable", side_effect=self.set_variable
            ),
            patch("wechat_airflow.notifications.email._today", return_value=date(2026, 7, 16)),
            patch(
                "wechat_airflow.notifications.email.send_template_email",
                return_value={"success": True},
            ) as mock_send,
        ):
            venue_email.send_venue_email_batch(
                "深圳湾网球场",
                notifications,
                recipients_var="SZW_EMAIL_LIST",
            )

        self.assertEqual(mock_send.call_args.kwargs["template_id"], 33340)
        self.assertEqual(
            mock_send.call_args.kwargs["template_data"]["COURT_NAME"],
            "深圳湾网球场",
        )

    def test_failed_send_is_recorded_without_raising(self):
        notifications = [
            {
                "date": "07-15",
                "court_name": "上越沙河1号场",
                "start_time": "18:00",
                "end_time": "19:00",
            }
        ]

        with (
            patch(
                "wechat_airflow.notifications.email._get_variable", side_effect=self.get_variable
            ),
            patch(
                "wechat_airflow.notifications.email._set_variable", side_effect=self.set_variable
            ),
            patch(
                "wechat_airflow.notifications.email._utc_now",
                return_value="2026-07-14T16:00:00+00:00",
            ),
            patch(
                "wechat_airflow.notifications.email.send_template_email",
                return_value={"success": False, "error": "FailedOperation.FrequencyLimit"},
            ),
        ):
            result = venue_email.send_venue_email_batch(
                "上越沙河网球场巡检",
                notifications,
                recipients_var="SYSH_EMAIL_LIST",
            )

        self.assertFalse(result["success"])
        fallback = self.variables[venue_email.EMAIL_SEND_FALLBACK_OUTBOX_VAR]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["source"], "上越沙河网球场巡检")
        self.assertEqual(fallback[0]["recipients_var"], "SYSH_EMAIL_LIST")
        self.assertEqual(fallback[0]["notification_count"], 1)
        self.assertEqual(fallback[0]["attempt_count"], 1)

    def test_missing_venue_recipient_variable_uses_fallback(self):
        notifications = [
            {
                "date": "07-15",
                "court_name": "TOPS1号场",
                "start_time": "18:00",
                "end_time": "19:00",
            }
        ]

        with (
            patch(
                "wechat_airflow.notifications.email._get_variable", side_effect=self.get_variable
            ),
            patch(
                "wechat_airflow.notifications.email._set_variable", side_effect=self.set_variable
            ),
            patch(
                "wechat_airflow.notifications.email._utc_now",
                return_value="2026-07-14T16:00:00+00:00",
            ),
            patch("wechat_airflow.notifications.email.send_template_email") as mock_send,
        ):
            result = venue_email.send_venue_email_batch(
                "TOPS科技园网球场巡检",
                notifications,
                recipients_var="TOPS_EMAIL_LIST",
            )

        self.assertFalse(result["success"])
        self.assertIn("TOPS_EMAIL_LIST", result["error"])
        mock_send.assert_not_called()
        self.assertEqual(len(self.variables[venue_email.EMAIL_SEND_FALLBACK_OUTBOX_VAR]), 1)

    def test_all_active_venue_watchers_use_independent_recipient_variables(self):
        root_dir = Path(__file__).resolve().parents[1]
        watcher_dir = root_dir / "src" / "wechat_airflow" / "venues"
        watcher_variables = {
            "szw_watcher.py": "SZW_EMAIL_LIST",
            "jdwx_watcher.py": "JDWX_EMAIL_LIST",
            "sysh_watcher.py": "SYSH_EMAIL_LIST",
            "tops_watcher.py": "TOPS_EMAIL_LIST",
            "tyzx_watcher.py": "TYZX_EMAIL_LIST",
        }

        for filename, variable_name in watcher_variables.items():
            source = (watcher_dir / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("send_venue_email_batch", source)
                self.assertIn(f'recipients_var="{variable_name}"', source)
                self.assertNotIn("SZ_TENNIS_EMAIL_LIST", source)


if __name__ == "__main__":
    unittest.main()
