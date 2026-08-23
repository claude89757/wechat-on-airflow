from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import probe_wechat_delivery  # noqa: E402


class WeChatDirectContactProbeContractTest(unittest.TestCase):
    def test_direct_selector_is_bounded_and_accepts_tt(self):
        pattern = probe_wechat_delivery.TARGET_MEMBERSHIP_PATTERN

        self.assertIsNotNone(pattern.fullmatch("direct:Tt"))
        self.assertIsNotNone(pattern.fullmatch("direct:测试 联系人"))
        self.assertIsNone(pattern.fullmatch("direct:"))
        self.assertIsNone(pattern.fullmatch("direct: Tt"))
        self.assertIsNone(pattern.fullmatch("direct:Tt "))
        self.assertIsNone(pattern.fullmatch("direct:A:B"))
        self.assertIsNone(pattern.fullmatch("direct:" + "a" * 65))

    def test_direct_probe_sends_one_hard_coded_message_without_reading_group_targets(self):
        script = probe_wechat_delivery.remote_script()

        self.assertIn('if selector.startswith("direct:"):', script)
        self.assertIn('"target_set": "direct"', script)
        self.assertIn('"message_kind": (', script)
        self.assertIn('"direct_delivery_acceptance"', script)
        self.assertIn('{"target_selector": "direct"}', script)
        self.assertIn('{"target_selector": selector or None}', script)
        self.assertIn("【系统验收】微信发送链路测试", script)
        self.assertNotIn("Variable.set", script)
        self.assertNotIn("WECHAT_SEND_FALLBACK_OUTBOX", script)

        result_block = script.split("print(\n    json.dumps(", 1)[-1]
        self.assertNotIn('"receiver": direct_receiver', result_block)
        self.assertNotIn('"message": message', result_block)


if __name__ == "__main__":
    unittest.main()
