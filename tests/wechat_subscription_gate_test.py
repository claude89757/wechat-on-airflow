from datetime import UTC, datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

from wechat_airflow.notifications import webapp, wechat


class WeChatSubscriptionGateTest(TestCase):
    def test_enforce_allows_fresh_active_gate(self):
        now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
        result = {
            "wechat_gate": {
                "allowed": True,
                "evaluated_at": (now - timedelta(minutes=1)).isoformat(),
                "valid_until": (now + timedelta(minutes=9)).isoformat(),
                "revision": 123,
            }
        }
        with patch.object(webapp, "_get_variable", return_value="enforce"):
            self.assertTrue(webapp.wechat_delivery_allowed("tops", result, now=now))

    def test_enforce_fails_closed_when_gate_is_missing(self):
        with (
            patch.object(webapp, "_get_variable") as get_variable,
            patch.object(webapp, "_cached_gate", return_value=None),
        ):
            get_variable.side_effect = lambda key, default=None, deserialize_json=False: (
                "enforce" if key == webapp.WEBAPP_WECHAT_GATE_MODE_VAR else default
            )
            self.assertFalse(webapp.wechat_delivery_allowed("tops"))

    def test_suppressed_delivery_releases_watcher_dedupe_and_never_calls_sender(self):
        stored: list[tuple[str, object, bool]] = []

        def get_variable(key, default=None, deserialize_json=False):
            if key == "TOPS科技园网球场":
                return ["old", "new-a", "new-b"]
            return default

        def set_variable(key, value, serialize_json=False):
            stored.append((key, value, serialize_json))

        with (
            patch.object(wechat, "wechat_delivery_allowed", return_value=False),
            patch.object(wechat, "_get_variable", side_effect=get_variable),
            patch.object(wechat, "_set_variable", side_effect=set_variable),
            patch.object(wechat, "send_wechat_text") as sender,
        ):
            result = wechat.send_wechat_text_to_chatrooms_best_effort(
                ["room"],
                "new-a\nnew-b",
                source="TOPS科技园网球场巡检",
                booking_venue_id="tops",
            )

        sender.assert_not_called()
        self.assertTrue(result[0]["suppressed"])
        self.assertTrue(result[0]["dedupe_released"])
        self.assertEqual(stored, [("TOPS科技园网球场", ["old"], True)])

    def test_dedupe_cache_registry_covers_all_web_venues(self):
        expected = {
            "szw", "gba", "dsh_free", "dsh", "sysh", "tops", "fsb", "jdwx",
            "ppba", "tyzx", "fsb_shenyun", "fsb_shekou", "fsb_xinan",
            "fsb_zhengzhong", "fsb_atuoshan", "fsb_zonglvquan", "fsb_guanhu",
            "fsb_bantian", "fsb_shahe", "fsb_baoshui", "fsb_nanyou", "fsb_xinqiao",
            "fsb_yifangcheng", "fsb_qilin", "fsb_maozhouhe", "fft_qianhai",
        }
        self.assertEqual(set(wechat.VENUE_DEDUPE_CACHE_KEYS), expected)
