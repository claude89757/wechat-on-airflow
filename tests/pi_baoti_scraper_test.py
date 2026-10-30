#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "pi_host" / "dsh_ydmap" / "server.py"


class FakeDriver:
    def __init__(self) -> None:
        self.visited: list[str] = []
        self.clicked: list[str] = []

    def get(self, url: str) -> None:
        self.visited.append(url)

    def execute_script(self, script: str, argument: str) -> bool:
        self.clicked.append(argument)
        return True


def install_selenium_stubs() -> None:
    selenium = types.ModuleType("selenium")
    webdriver = types.ModuleType("selenium.webdriver")
    chrome = types.ModuleType("selenium.webdriver.chrome")
    options = types.ModuleType("selenium.webdriver.chrome.options")
    service = types.ModuleType("selenium.webdriver.chrome.service")
    options.Options = type("Options", (), {})
    service.Service = type("Service", (), {})
    webdriver.Chrome = type("Chrome", (), {})
    chrome.options = options
    chrome.service = service
    sys.modules.setdefault("selenium", selenium)
    sys.modules.setdefault("selenium.webdriver", webdriver)
    sys.modules.setdefault("selenium.webdriver.chrome", chrome)
    sys.modules.setdefault("selenium.webdriver.chrome.options", options)
    sys.modules.setdefault("selenium.webdriver.chrome.service", service)


def load_server() -> types.ModuleType:
    install_selenium_stubs()
    spec = importlib.util.spec_from_file_location("pi_dsh_ydmap_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server()


def snapshot(courts: dict[str, list[list[str]]], signature: str) -> dict[str, object]:
    return {
        "captcha": False,
        "ready": True,
        "signature": signature,
        "courts": courts,
        "courtNames": list(courts),
    }


class PiBaotiScraperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original = {
            "cleanup": server._cleanup_stale_browser,
            "start": server._start_chromium,
            "devtools": server._wait_devtools,
            "attach": server._attach,
            "stop": server._stop,
            "wait": server._wait_for_schedule,
            "sleep": server.time.sleep,
        }
        server.time.sleep = lambda seconds: None

    def tearDown(self) -> None:
        server._cleanup_stale_browser = self.original["cleanup"]
        server._start_chromium = self.original["start"]
        server._wait_devtools = self.original["devtools"]
        server._attach = self.original["attach"]
        server._stop = self.original["stop"]
        server._wait_for_schedule = self.original["wait"]
        server.time.sleep = self.original["sleep"]

    def _install_driver(self, driver: FakeDriver, payloads: list[dict[str, object]]) -> None:
        queue = list(payloads)

        def fake_wait(
            _driver: FakeDriver,
            timeout: int = 45,
            previous_signature: str | None = None,
        ) -> dict[str, object]:
            if not queue:
                raise AssertionError("unexpected extra schedule wait")
            return queue.pop(0)

        server._cleanup_stale_browser = lambda: None
        server._start_chromium = lambda url: ("proc", url)
        server._wait_devtools = lambda timeout=40: None
        server._attach = lambda: driver
        server._stop = lambda proc, driver_obj: None
        server._wait_for_schedule = fake_wait

    def test_baoti_merges_three_groups_and_prefixes_indoor_courts(self) -> None:
        driver = FakeDriver()
        today = date.today()
        second = today + timedelta(days=1)
        payloads = [
            snapshot({"室外场1号": [["18:00", "19:00"]]}, "a1"),
            snapshot({"室外场1号": [["20:00", "21:00"]]}, "a2"),
            snapshot({"A号场": [["19:00", "20:00"]]}, "b1"),
            snapshot({"A号场": [["21:00", "22:00"]]}, "b2"),
            snapshot({"风雨场1号": [["18:30", "19:30"]]}, "c1"),
            snapshot({}, "c2"),
        ]
        self._install_driver(driver, payloads)

        result = server.scrape_available_slots("baoti", 2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["venue"], "baoti")
        self.assertEqual(result["venue_name"], "宝安网球中心")
        days = {item["date"]: item["courts"] for item in result["days"]}
        self.assertEqual(
            days[today.isoformat()],
            {
                "室外场1号": [["18:00", "19:00"]],
                "室内A号场": [["19:00", "20:00"]],
                "风雨场1号": [["18:30", "19:30"]],
            },
        )
        self.assertEqual(
            days[second.isoformat()],
            {"室外场1号": [["20:00", "21:00"]], "室内A号场": [["21:00", "22:00"]]},
        )
        self.assertEqual(driver.visited, [group[2] for group in server.VENUE_GROUPS["baoti"][1:]])
        self.assertEqual(driver.clicked, [second.strftime("%m-%d")] * 3)

    def test_dsh_keeps_single_group_without_prefixing(self) -> None:
        driver = FakeDriver()
        payloads = [
            snapshot({"1号风雨场": [["18:00", "19:00"]]}, "d1"),
            snapshot({"1号风雨场": [["20:00", "21:00"]]}, "d2"),
        ]
        self._install_driver(driver, payloads)

        result = server.scrape_available_slots("dsh", 2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["venue"], "dsh")
        self.assertEqual(driver.visited, [])
        courts = [item["courts"] for item in result["days"]]
        self.assertEqual(courts[0], {"1号风雨场": [["18:00", "19:00"]]})
        self.assertEqual(courts[1], {"1号风雨场": [["20:00", "21:00"]]})

    def test_unknown_venue_fails_without_starting_a_browser(self) -> None:
        def fail_start(url: str) -> object:
            raise AssertionError("browser must not start for an unknown venue")

        server._start_chromium = fail_start
        result = server.scrape_available_slots("nope", 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_venue:nope")
        self.assertEqual(result["days"], [])

    def test_captcha_mid_group_reports_captcha_with_partial_days(self) -> None:
        driver = FakeDriver()
        today = date.today()
        payloads = [
            snapshot({"室外场1号": [["18:00", "19:00"]]}, "x1"),
            {"captcha": True, "ready": False, "courts": {}, "signature": ""},
        ]
        self._install_driver(driver, payloads)

        result = server.scrape_available_slots("baoti", 2)

        self.assertFalse(result["ok"])
        self.assertTrue(result["captcha"])
        self.assertEqual(result["error"], "captcha")
        self.assertEqual(
            [item["date"] for item in result["days"]],
            [today.isoformat()],
        )


if __name__ == "__main__":
    unittest.main()
