#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "probe_pi_ydmap_isolated.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "pi-isolated-ydmap-probe.yml").read_text(
    encoding="utf-8"
)


class IsolatedPiYdmapProbeTest(unittest.TestCase):
    def test_probe_stays_off_dashah_runtime(self) -> None:
        self.assertIn("https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317", SCRIPT)
        self.assertIn("ISOLATED_DEBUG_PORT = 9335", SCRIPT)
        self.assertIn("/tmp/bawtt_ydmap_probe_profile", SCRIPT)
        self.assertNotIn("/tmp/dsh_ydmap_profile", SCRIPT)
        self.assertNotIn("systemctl restart", SCRIPT)
        self.assertNotIn("systemctl stop", SCRIPT)
        self.assertNotIn("systemctl disable", SCRIPT)
        self.assertNotIn("pkill -f remote-debugging-port=9224", SCRIPT)
        self.assertIn("remote-debugging-port={ISOLATED_DEBUG_PORT}", SCRIPT)
        self.assertIn("http://127.0.0.1:8788/healthz", SCRIPT)
        self.assertIn("dsh-ydmap-scraper", SCRIPT)
        self.assertNotIn('BOOKING_URL = "https://wxsports.ydmap.cn', SCRIPT)

    def test_workflow_is_manual_and_isolated(self) -> None:
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertIn("inputs.confirm", WORKFLOW)
        self.assertIn("group: pi-isolated-ydmap-probe", WORKFLOW)
        self.assertNotIn("production-airflow-v2", WORKFLOW)
        self.assertIn("scripts/probe_pi_ydmap_isolated.py", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
