#!/usr/bin/env python3
"""Offline Pi service regressions; no provider or notification requests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "pi_host" / "dsh_ydmap" / "server.py"
TODAY = date(2026, 11, 1)
TOMORROW = TODAY + timedelta(days=1)


def install_selenium_stubs() -> None:
    modules = {
        name: types.ModuleType(name)
        for name in (
            "selenium",
            "selenium.webdriver",
            "selenium.webdriver.chrome",
            "selenium.webdriver.chrome.options",
            "selenium.webdriver.chrome.service",
        )
    }
    modules["selenium.webdriver.chrome.options"].Options = type("Options", (), {})
    modules["selenium.webdriver.chrome.service"].Service = type("Service", (), {})
    modules["selenium.webdriver"].Chrome = type("Chrome", (), {})
    for name, module in modules.items():
        sys.modules.setdefault(name, module)


def load_server() -> types.ModuleType:
    install_selenium_stubs()
    spec = importlib.util.spec_from_file_location("pi_dsh_ydmap_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load_server()


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        # Shanghai has crossed midnight while a UTC host has not.
        instant = datetime(2026, 10, 31, 18, tzinfo=UTC)
        return instant.astimezone(tz)


class AccessDiagnosticsTest(unittest.TestCase):
    def test_initial_resource_and_execution_errors_export_only_categories(self):
        driver = Mock(spec=["execute_script", "execute"])
        driver.execute_script.return_value = {"vueRootPresent": 0, "scriptReferences": 3}
        entries = [
            {
                "message": json.dumps(
                    {
                        "message": {
                            "method": "Network.responseReceived",
                            "params": {
                                "type": kind,
                                "response": {
                                    "url": "https://private.test/" + path,
                                    "mimeType": "text/html",
                                    "status": status,
                                },
                            },
                        }
                    }
                )
            }
            for kind, path, status in (
                ("Document", "start", 503),
                ("Script", "main.js", 403),
                ("Image", "favicon.ico", 404),
            )
        ]
        driver.execute.side_effect = [
            {"value": entries},
            {
                "value": [
                    {
                        "message": "TypeError SyntaxError MIME type; status of 403; net::ERR_CERT_INVALID; private-token"
                    }
                ]
            },
        ]
        result = server._access_diagnostics(driver)
        self.assertEqual(result["httpErrors"], 3)
        self.assertEqual(result["documentHttpErrors"], 1)
        self.assertEqual(result["faviconHttpErrors"], 1)
        for key in (
            "scriptHtmlResponses",
            "scriptHttpErrors",
            "typeErrors",
            "syntaxErrors",
            "mimeTypeErrors",
            "consoleHttp403Errors",
            "consoleTlsErrors",
        ):
            self.assertEqual(result[key], 1)
        self.assertNotIn("private", json.dumps(result))

    def test_empty_logs_and_unavailable_logging_remain_distinct(self):
        driver = Mock(spec=["execute_script", "execute"])
        driver.execute_script.return_value = {}
        driver.execute.return_value = {"value": []}
        result = server._access_diagnostics(driver)
        self.assertEqual(result, {"performanceLogEntries": 0, "browserLogEntries": 0})
        driver.execute.side_effect = RuntimeError("never-export")
        self.assertEqual(
            server._access_diagnostics(driver),
            {
                "performanceLogUnavailable": 1,
                "browserLogUnavailable": 1,
            },
        )

    def test_passive_logs_distinguish_html_api_and_resource_failures_without_secrets(self):
        driver = Mock(spec=["execute_script", "execute"])
        driver.execute_script.return_value = {
            "maskRoots": 1,
            "legacyHandles": 1,
            "semanticHandles": 0,
            "frames": 0,
            "private": "never-export",
            "maskChildren": True,
        }

        def event(method, **params):
            return {"message": json.dumps({"message": {"method": method, "params": params}})}

        logs = [
            [
                event(
                    "Network.requestWillBeSent",
                    requestId="private-id",
                    request={
                        "url": "https://bawtt.ydmap.cn/api/getVenueOrderList?token=never-export"
                    },
                ),
                event(
                    "Network.responseReceived",
                    response={
                        "url": "https://bawtt.ydmap.cn/api/getVenueOrderList?token=never-export",
                        "status": 200,
                        "mimeType": "text/html",
                        "headers": {"secret": "never-export"},
                    },
                ),
                event(
                    "Network.loadingFailed",
                    requestId="private-id",
                    type="XHR",
                    errorText="net::ERR_CERT_AUTHORITY_INVALID",
                ),
                event(
                    "Network.loadingFailed", type="Script", errorText="net::ERR_NAME_NOT_RESOLVED"
                ),
                event("Network.loadingFailed", type="Script", blockedReason="csp"),
                event(
                    "Network.responseReceived",
                    response={
                        "url": "https://bawtt.ydmap.cn/api/getSportVenueConfig?token=never-export",
                        "status": 200,
                        "mimeType": "text/html",
                    },
                ),
            ],
            [
                {"message": "Content Security Policy never-export"},
                {"message": "ReferenceError never-export"},
            ],
        ]
        driver.execute.side_effect = [{"value": events} for events in logs]
        result = server._access_diagnostics(driver)
        self.assertEqual(driver.execute.call_args_list[0].args, ("getLog", {"type": "performance"}))
        self.assertEqual(driver.execute.call_args_list[1].args, ("getLog", {"type": "browser"}))
        self.assertEqual(result["performanceLogEntries"], 6)
        self.assertEqual(result["configHtmlResponses"], 1)
        self.assertEqual(result["browserLogEntries"], 2)
        self.assertEqual(result["orderHtmlResponses"], 1)
        self.assertEqual(result["lastOrderStatus"], 200)
        self.assertEqual(result["orderFailures"], 1)
        self.assertEqual(result["scriptFailures"], 2)
        for key in (
            "tlsFailures",
            "dnsFailures",
            "blockedFailures",
            "cspErrors",
            "referenceErrors",
        ):
            self.assertEqual(result[key], 1)
        self.assertEqual(result["legacyHandles"], 1)
        self.assertNotIn("maskChildren", result)
        self.assertNotIn("never-export", json.dumps(result))
        self.assertTrue(all(type(value) is int for value in result.values()))


class Clock:
    value = 100.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeElement:
    def __init__(self, driver: FakeDriver, target: str) -> None:
        self.driver = driver
        self.target = target

    def click(self) -> None:
        self.driver.clicked.append(self.target)


class FakeDriver:
    def __init__(self) -> None:
        self.visited: list[str] = []
        self.clicked: list[str] = []

    def get(self, url: str) -> None:
        self.visited.append(url)

    def set_page_load_timeout(self, seconds: float) -> None:
        pass

    def execute_script(self, script: str, argument: str) -> FakeElement:
        if script != server.FIND_DATE_JS:
            raise AssertionError("unexpected browser script")
        return FakeElement(self, argument)


def snapshot(
    booking_date: date = TODAY,
    generation: int = 1,
    *,
    venue: str = "baoti",
    key: str = "outdoor",
    available: bool = True,
) -> dict[str, object]:
    if venue == "dsh":
        product_id, product_name, court_name = "100000", "网球场", "1号风雨场"
        host, sales_id = "wxsports.ydmap.cn", "100220"
    else:
        product_id, product_name, court_name = {
            "outdoor": ("111317", "室外网球场", "室外场1号"),
            "indoor": ("103224", "室内网球场", "A号场"),
            "windrain": ("111319", "风雨网球场", "风雨场1号"),
        }[key]
        host, sales_id = "bawtt.ydmap.cn", "104036"
    return {
        "captcha": False,
        "accessError": None,
        "ready": True,
        "signature": "same-availability",
        "courts": {court_name: [["18:00", "19:00"]]} if available else {},
        "courtNames": [court_name],
        "cellCount": 12,
        "pageHost": host,
        "selectedDate": booking_date.isoformat(),
        "queryDate": booking_date.isoformat(),
        "selectedProduct": product_id,
        "sourceProduct": product_id,
        "selectedSalesId": sales_id,
        "sourceSalesId": sales_id,
        "productName": product_name,
        "productNameField": "itemName",
        "productInCatalog": True,
        "availableDates": [(TODAY + timedelta(days=offset)).isoformat() for offset in range(7)],
        "loadingCounter": 0,
        "loadGeneration": generation,
        "dataVersion": {"platforms": generation * 2 - 1, "orders": generation * 2},
    }


OUTDOOR_IDENTITY = {
    "host": "bawtt.ydmap.cn",
    "sales_id": "104036",
    "sales_item_id": "111317",
    "label": "室外",
}


class PiBaotiScraperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.driver = FakeDriver()
        self.browser_starts: list[tuple[str, Path, float]] = []
        self.browser_events: list[str] = []

        def start(url, *, profile):
            self.browser_events.append("start")
            self.browser_starts.append((url, profile, self.clock.value))
            return object()

        contexts = [
            patch.object(server, "datetime", FixedDatetime),
            patch.object(server.time, "monotonic", self.clock.monotonic),
            patch.object(server.time, "sleep", self.clock.sleep),
            patch.object(server, "_cleanup_stale_browser"),
            patch.object(server, "_start_chromium", side_effect=start),
            patch.object(server, "_wait_devtools"),
            patch.object(server, "_attach", return_value=self.driver),
            patch.object(
                server, "_stop", side_effect=lambda *_: self.browser_events.append("stop")
            ),
        ]
        for context in contexts:
            context.start()
            self.addCleanup(context.stop)

    def install_payloads(self, payloads: list[dict[str, object]]) -> None:
        queue = list(payloads)
        last = queue[-1]

        def extract(_driver, **kwargs):
            nonlocal last
            if queue:
                last = queue.pop(0)
            return dict(last)

        context = patch.object(server, "_extract_day", side_effect=extract)
        self.extract = context.start()
        self.addCleanup(context.stop)

    def test_initial_page_warmup_precedes_attach_without_reloading(self) -> None:
        self.install_payloads([{"captcha": True, "ready": False}])
        attached_at = []
        server._attach.side_effect = (
            lambda **kwargs: attached_at.append(self.clock.value) or self.driver
        )
        result = server.scrape_available_slots("baoti", 2)
        self.assertEqual(attached_at, [104.0])
        self.assertEqual(result["error"], "captcha")
        self.assertEqual(self.driver.visited, [])

    def test_first_product_probe_requires_source_evidence_and_keeps_normal_order(self) -> None:
        for evidence, product in ((False, "111317"), (True, "111319")):
            with (
                self.subTest(evidence=evidence),
                patch.dict(server.os.environ, {"YDMAP_DIAGNOSTIC_FIRST_PRODUCT": "windrain"}),
            ):
                self.install_payloads([{"captcha": True, "ready": False}])
                result = server.scrape_available_slots("baoti", 2, source_evidence=evidence)
                self.assertTrue(server._start_chromium.call_args.args[0].endswith("=" + product))
                self.assertEqual(
                    server._start_chromium.call_args.kwargs["profile"].name,
                    "baoti-outdoor" if not evidence else "baoti-windrain",
                )
                self.assertEqual(result["diagnostics"]["requestedProduct"], product)
                self.assertEqual(result["diagnostics"]["failurePhase"], "initial_schedule")
                self.assertEqual(result["days"], [])
        self.assertEqual(
            [group[0] for group in server.VENUE_GROUPS["baoti"]], ["outdoor", "indoor", "windrain"]
        )

    def test_browser_environment_reports_versions_without_private_capabilities(self) -> None:
        driver = types.SimpleNamespace(
            capabilities={
                "browserVersion": "137.0.7151.119",
                "chrome": {
                    "chromedriverVersion": "138.0.1.2 (private-build)",
                    "userDataDir": "private-profile",
                },
                "secret": "private-cookie",
            }
        )
        report = server._browser_environment(driver)
        self.assertFalse(report["userAgentOverrideEnabled"])
        self.assertFalse(report["driverMajorMatchesBrowser"])
        self.assertEqual(report["driverVersion"], "138.0.1.2")
        self.assertFalse(report["profileResetBeforeScrape"])
        self.assertNotIn("private", str(report))
        driver.capabilities["browserVersion"] = "private-token"
        self.assertEqual(server._browser_environment(driver), {})

    def group_payloads(self, *, venue="baoti", key="outdoor", available=True):
        return [
            snapshot(TODAY, 1, venue=venue, key=key, available=available),
            snapshot(TOMORROW, 2, venue=venue, key=key, available=available),
            snapshot(TODAY, 3, venue=venue, key=key, available=available),
        ]

    def test_browser_exception_retains_only_bounded_phase_and_sentinel(self) -> None:
        exception_type = type("JavascriptException", (Exception,), {})
        with patch.object(
            server,
            "_extract_day",
            side_effect=exception_type("bookability_predicate_invalid private-cookie-value"),
        ):
            result = server.scrape_available_slots("baoti", 2)
        self.assertEqual(result["error"], "bookability_predicate_invalid")
        self.assertEqual(result["days"], [])
        self.assertEqual(
            result["diagnostics"],
            {"failurePhase": "initial_schedule", "requestedProduct": "111317"},
        )
        self.assertNotIn("private-cookie-value", str(result))

    def test_driver_deadline_aborts_hung_command_without_repeating_source_request(self) -> None:
        service = object()
        self.driver._ydmap_service = service
        timer = Mock()
        error = type("ReadTimeoutError", (Exception,), {})

        def hung(*args, **kwargs):
            timer_factory.call_args.args[1]()
            raise error("private-wire-message")

        with (
            patch.object(server.threading, "Timer", return_value=timer) as timer_factory,
            patch.object(server, "_extract_day", side_effect=hung) as extract,
            patch.object(server, "_stop_driver_service") as stop_service,
            patch.object(server, "_access_diagnostics", return_value={"browserLogUnavailable": 1}),
        ):
            result = server.scrape_available_slots("baoti", 2)
        self.assertEqual(timer_factory.call_args.args[0], 180)
        timer.start.assert_called_once()
        timer.cancel.assert_called_once()
        stop_service.assert_called_once_with(service)
        extract.assert_called_once()
        self.assertEqual(result["error"], "ReadTimeoutError")
        self.assertEqual(result["days"], [])
        self.assertEqual(result["diagnostics"]["accessDiagnostics"], {"browserLogUnavailable": 1})
        self.assertEqual(self.browser_events, ["start", "stop"])
        self.assertNotIn("private-wire-message", str(result))

    def wait_for_tomorrow(self):
        return server._wait_for_schedule(
            self.driver,
            timeout=2,
            expected_date=TOMORROW.isoformat(),
            previous=snapshot(),
            **OUTDOOR_IDENTITY,
        )

    def test_initial_schedule_timeout_keeps_passive_diagnostics_without_challenge(self):
        self.install_payloads([{"ready": False, "captcha": False}])
        with patch.object(server, "_access_diagnostics", return_value={"typeErrors": 1}) as probe:
            result = self.wait_for_tomorrow()
        probe.assert_called_once_with(self.driver)
        self.assertEqual(result["error"], "schedule_not_ready")
        self.assertEqual(result["accessDiagnostics"], {"typeErrors": 1})

    def test_baoti_complete_verified_groups_and_shanghai_dates(self) -> None:
        self.install_payloads(
            sum((self.group_payloads(key=key) for key in ("outdoor", "indoor", "windrain")), [])
        )
        result = server.scrape_available_slots("baoti", 2)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["venue"], "baoti")
        self.assertEqual(
            [day["date"] for day in result["days"]], [TODAY.isoformat(), TOMORROW.isoformat()]
        )
        for day in result["days"]:
            self.assertEqual(set(day["courts"]), {"室外场1号", "室内A号场", "风雨场1号"})
            self.assertEqual(len(day["groups"]), 3)
            for group in day["groups"]:
                self.assertEqual(group["source_date"], day["date"])
                self.assertEqual(group["selected_date"], day["date"])
                self.assertTrue(set(group["court_names"]).issubset(day["court_names"]))
        self.assertEqual(self.driver.clicked, ["11-02", "11-01"] * 3)
        self.assertEqual(self.driver.visited, [])
        self.assertEqual(
            [url.rsplit("=", 1)[-1] for url, _, _ in self.browser_starts],
            ["111317", "103224", "111319"],
        )
        self.assertEqual(
            [profile.name for _, profile, _ in self.browser_starts],
            ["baoti-outdoor", "baoti-indoor", "baoti-windrain"],
        )
        self.assertGreaterEqual(self.browser_starts[1][2] - self.browser_starts[0][2], 30)
        self.assertGreaterEqual(self.browser_starts[2][2] - self.browser_starts[1][2], 30)
        self.assertEqual(server._attach.call_count, 3)
        self.assertEqual(server._stop.call_count, 3)
        self.assertEqual(self.browser_events, ["start", "stop"] * 3)

    def test_dsh_preserves_names_and_single_group(self) -> None:
        self.install_payloads(self.group_payloads(venue="dsh"))
        result = server.scrape_available_slots("dsh", 2)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.driver.visited, [])
        self.assertEqual(self.clock.value, 104)  # Only its existing initial warm-up.
        for day in result["days"]:
            self.assertEqual(day["courts"], {"1号风雨场": [["18:00", "19:00"]]})
            self.assertEqual([group["key"] for group in day["groups"]], [""])

    def test_empty_availability_is_valid_when_all_courts_are_loaded(self) -> None:
        self.install_payloads(
            sum(
                (
                    self.group_payloads(key=key, available=False)
                    for key in ("outdoor", "indoor", "windrain")
                ),
                [],
            )
        )
        result = server.scrape_available_slots("baoti", 2)
        self.assertTrue(result["ok"], result)
        for day in result["days"]:
            self.assertEqual(day["courts"], {})
            self.assertEqual(len(day["court_names"]), 3)

    def test_unknown_venue_does_not_start_browser(self) -> None:
        result = server.scrape_available_slots("nope", 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_venue:nope")
        server._start_chromium.assert_not_called()

    def test_mid_group_challenge_discards_all_partial_days(self) -> None:
        self.install_payloads(self.group_payloads() + [{"captcha": True, "ready": False}])
        result = server.scrape_available_slots("baoti", 2)
        self.assertFalse(result["ok"])
        self.assertTrue(result["captcha"])
        self.assertEqual(result["error"], "captcha")
        self.assertEqual(result["days"], [])
        self.assertEqual(self.driver.visited, [])
        self.assertEqual(len(self.browser_starts), 2)
        self.assertEqual(server._stop.call_count, 2)

    def test_product_switch_requires_both_new_source_arrays_even_after_remount(self) -> None:
        previous = snapshot(TODAY, 3)
        current = snapshot(TODAY, 1, key="indoor")
        identity = {**OUTDOOR_IDENTITY, "sales_item_id": "103224", "label": "室内"}
        self.assertIsNone(server._snapshot_issue(current, previous=previous, **identity))
        for stale_key in ("platforms", "orders"):
            stale = {**current, "dataVersion": dict(current["dataVersion"])}
            stale["dataVersion"][stale_key] = previous["dataVersion"][stale_key]
            self.assertEqual(
                server._snapshot_issue(stale, previous=previous, **identity), "source_not_refreshed"
            )

    def test_next_product_browser_failure_discards_partial_data(self) -> None:
        self.install_payloads(self.group_payloads())
        original = server._start_chromium.side_effect

        def start(url, *, profile):
            if url.endswith("=103224"):
                raise TimeoutError("private-detail")
            return original(url, profile=profile)

        server._start_chromium.side_effect = start
        result = server.scrape_available_slots("baoti", 2)
        self.assertEqual(result["error"], "TimeoutError")
        self.assertEqual(result["days"], [])
        self.assertEqual(result["diagnostics"]["requestedProduct"], "103224")
        self.assertEqual(self.driver.visited, [])
        self.assertEqual(server._stop.call_count, 1)
        self.assertEqual(server._start_chromium.call_count, 2)
        self.assertNotIn("private-detail", str(result))

    def test_mid_group_date_failure_discards_all_partial_days(self) -> None:
        initial = snapshot(key="indoor")
        stale = {**snapshot(TOMORROW, 1, key="indoor"), "signature": "different"}
        self.install_payloads(self.group_payloads() + [initial, stale])
        result = server.scrape_available_slots("baoti", 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "source_not_refreshed")
        self.assertEqual(result["days"], [])

    def test_wrong_venue_product_or_group_cannot_be_relabelled(self) -> None:
        cases = [
            ("pageHost", "wxsports.ydmap.cn", "venue_host_mismatch"),
            ("sourceSalesId", "100220", "venue_id_mismatch"),
            ("sourceProduct", "100000", "product_id_mismatch"),
            ("productName", "室内网球场", "product_name_mismatch"),
            ("productInCatalog", False, "product_name_unverified"),
            ("courtNames", ["室内A号场", "室外场1号"], "court_group_mismatch"),
        ]
        for key, value, error in cases:
            with self.subTest(key=key):
                self.assertEqual(
                    server._snapshot_issue({**snapshot(), key: value}, **OUTDOOR_IDENTITY), error
                )

    def test_unavailable_calendar_date_fails_without_selecting_another_day(self) -> None:
        self.install_payloads([{**snapshot(), "availableDates": [TODAY.isoformat()]}])
        result = server.scrape_available_slots("baoti", 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "requested_date_unavailable")
        self.assertEqual(self.driver.clicked, [])

    def test_one_day_request_observes_refresh_before_emitting_today(self) -> None:
        self.install_payloads(self.group_payloads(venue="dsh"))
        result = server.scrape_available_slots("dsh", 1)
        self.assertTrue(result["ok"], result)
        self.assertEqual([day["date"] for day in result["days"]], [TODAY.isoformat()])
        self.assertEqual(self.driver.clicked, ["11-02", "11-01"])

    def test_stale_date_with_changed_availability_is_not_accepted(self) -> None:
        self.install_payloads([{**snapshot(TODAY, 2), "signature": "changed"}])
        result = self.wait_for_tomorrow()
        self.assertFalse(result["ready"])
        self.assertEqual(result["error"], "date_not_selected")

    def test_selected_date_without_refreshed_source_arrays_is_not_accepted(self) -> None:
        self.install_payloads([{**snapshot(TOMORROW, 2), "dataVersion": snapshot()["dataVersion"]}])
        result = self.wait_for_tomorrow()
        self.assertFalse(result["ready"])
        self.assertEqual(result["error"], "source_not_refreshed")

    def test_identical_availability_with_fresh_source_date_is_accepted(self) -> None:
        self.install_payloads([snapshot(TOMORROW, 2)])
        result = self.wait_for_tomorrow()
        self.assertTrue(result["ready"])
        self.assertEqual(self.extract.call_count, 1)

    def test_only_one_refreshed_array_or_incomplete_load_is_not_accepted(self) -> None:
        cases = [
            ("dataVersion", {"platforms": 3, "orders": 2}, "source_not_refreshed"),
            ("dataVersion", {"platforms": 1, "orders": 4}, "source_not_refreshed"),
            ("loadGeneration", 1, "source_not_refreshed"),
            ("loadingCounter", 1, "schedule_loading"),
            ("queryDate", TODAY.isoformat(), "date_identity_mismatch"),
        ]
        for key, value, error in cases:
            with self.subTest(key=key, value=value):
                result = server._snapshot_issue(
                    {**snapshot(TOMORROW, 2), key: value},
                    expected_date=TOMORROW.isoformat(),
                    previous=snapshot(),
                    **OUTDOOR_IDENTITY,
                )
                self.assertEqual(result, error)

    def test_access_restriction_is_terminal_without_retries(self) -> None:
        for error in ("captcha", "rate_limited", "login_required"):
            with self.subTest(error=error):
                self.install_payloads([{**snapshot(), "accessError": error}])
                result = server._wait_for_schedule(self.driver, timeout=25, **OUTDOOR_IDENTITY)
                self.assertFalse(result["ready"])
                self.assertEqual(result["error"], error)
                self.assertEqual(self.extract.call_count, 1)

    def test_total_deadline_caps_wait(self) -> None:
        self.install_payloads([{}])
        result = server._wait_for_schedule(
            self.driver, timeout=45, deadline=self.clock.value + 2, **OUTDOOR_IDENTITY
        )
        self.assertFalse(result["ready"])
        self.assertEqual(self.clock.value, 102.0)

    def test_health_identifies_exact_server_source_release_and_busy_state(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/healthz"
        responses = []
        handler._send_json = lambda status, body: responses.append((status, body))
        with patch.dict(server.os.environ, {"YDMAP_DEPLOYMENT_COMMIT": "a" * 40}):
            server.SCRAPE_LOCK.acquire()
            try:
                handler.do_GET()
            finally:
                server.SCRAPE_LOCK.release()
        status, body = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["protocolVersion"], 2)
        self.assertEqual(body["deploymentCommit"], "a" * 40)
        self.assertEqual(body["sourceSha256"], hashlib.sha256(SERVER_PATH.read_bytes()).hexdigest())
        self.assertEqual(body["venues"], ["baoti", "dsh"])
        self.assertTrue(body["busy"])

    def test_optional_evidence_is_collected_only_after_validated_date_refresh(self) -> None:
        diagnostic = {
            "schema_version": 1,
            "bookability_verified": False,
            "source_cell_count": 12,
            "matched_cell_count": 0,
            "unmatched_cell_count": 12,
            "coverage_complete": False,
            "component_scan_truncated": False,
            "source_truncated": False,
            "components": [],
            "methods": [],
            "samples": [],
        }
        self.install_payloads(
            [
                snapshot(venue="dsh"),
                snapshot(TOMORROW, 2, venue="dsh"),
                {**snapshot(TOMORROW, 2, venue="dsh"), "sourceEvidence": diagnostic},
                snapshot(TODAY, 3, venue="dsh"),
                {**snapshot(TODAY, 3, venue="dsh"), "sourceEvidence": diagnostic},
            ]
        )
        result = server.scrape_available_slots("dsh", 2, source_evidence=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            [call.kwargs for call in self.extract.call_args_list],
            [{}, {}, {"source_evidence": True}, {}, {"source_evidence": True}],
        )
        for day in result["days"]:
            self.assertFalse(day["groups"][0]["source_evidence"]["bookability_verified"])

    def test_evidence_capture_revalidates_identity_and_discards_failure(self) -> None:
        for failed in (
            {"captcha": True, "ready": False},
            {**snapshot(TODAY, 2, venue="dsh"), "sourceEvidence": {"private": "never-export"}},
        ):
            with self.subTest(failed=failed):
                self.install_payloads(
                    [snapshot(venue="dsh"), snapshot(TOMORROW, 2, venue="dsh"), failed]
                )
                result = server.scrape_available_slots("dsh", 2, source_evidence=True)
                self.assertFalse(result["ok"])
                self.assertEqual(result["days"], [])
                self.assertNotIn("source_evidence", str(result))
                self.assertNotIn("never-export", str(result))

    def test_http_evidence_requires_exact_explicit_flag(self) -> None:
        for suffix, expected in (
            ("", False),
            ("&evidence=true", False),
            ("&evidence=source-v1", True),
            ("&evidence=source-v1&evidence=other", False),
        ):
            with self.subTest(suffix=suffix):
                handler = server.Handler.__new__(server.Handler)
                handler.path = "/inspect?venue=baoti&days=2" + suffix
                handler._send_json = lambda *args: None
                with patch.object(
                    server, "scrape_available_slots", return_value={"ok": True}
                ) as scrape:
                    handler.do_GET()
                    scrape.assert_called_once_with(
                        "baoti", 2, source_evidence=expected, verification_once=False
                    )

    def test_verification_requires_all_gates_and_consumes_one_authorization(self) -> None:
        with (
            patch.object(server, "VERIFICATION_AVAILABLE", True),
            patch.object(server, "_scrape_available_slots", return_value={"ok": False}) as inner,
        ):
            for venue, evidence, requested in (
                ("baoti", True, False),
                ("baoti", False, True),
                ("dsh", True, True),
            ):
                server.scrape_available_slots(
                    venue, 2, source_evidence=evidence, verification_once=requested
                )
                self.assertIsNone(inner.call_args.kwargs["verification"])
                self.assertTrue(server.VERIFICATION_AVAILABLE)
            result = server.scrape_available_slots(
                "baoti", 2, source_evidence=True, verification_once=True
            )
            self.assertFalse(result["diagnostics"]["verificationAttempted"])
            self.assertEqual(result["diagnostics"]["verificationOutcome"], "not_needed")
            self.assertFalse(server.VERIFICATION_AVAILABLE)
            server.scrape_available_slots("baoti", 2, source_evidence=True, verification_once=True)
            self.assertIsNone(inner.call_args.kwargs["verification"])

    def test_normal_verification_is_one_native_drag_and_no_retry(self) -> None:
        handle = object()
        driver = Mock()
        driver.execute_script.return_value = {"status": "ready", "handle": handle, "distance": 200}
        chain = Mock()
        chain.click_and_hold.return_value = chain
        chain.move_by_offset.return_value = chain
        chain.release.return_value = chain
        actions = Mock(return_value=chain)
        module = types.ModuleType("selenium.webdriver.common.action_chains")
        module.ActionChains = actions
        state = {"attempted": False, "outcome": "not_needed"}
        with patch.dict(sys.modules, {module.__name__: module}):
            self.assertTrue(server._normal_verification_once(driver, state))
        actions.assert_called_once_with(driver, duration=1000)
        chain.click_and_hold.assert_called_once_with(handle)
        chain.move_by_offset.assert_called_once_with(200, 0)
        chain.release.assert_called_once_with()
        chain.perform.assert_called_once_with()
        self.assertEqual(state, {"attempted": True, "outcome": "not_passed", "control": "ready"})
        driver.execute_script.return_value = None
        self.assertFalse(server._normal_verification_once(driver, state))
        self.assertEqual(state["outcome"], "unsupported_control")

    def test_failed_verification_keeps_atomic_failure_and_audit(self) -> None:
        self.install_payloads([{"captcha": True, "ready": False}])

        def gesture(driver, state):
            state.update(attempted=True, outcome="not_passed")
            return True

        with (
            patch.object(server, "VERIFICATION_AVAILABLE", True),
            patch.object(server, "_normal_verification_once", side_effect=gesture) as action,
        ):
            result = server.scrape_available_slots(
                "baoti", 2, source_evidence=True, verification_once=True
            )
        action.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["days"], [])
        self.assertTrue(result["captcha"])
        self.assertTrue(result["diagnostics"]["verificationAttempted"])
        self.assertEqual(result["diagnostics"]["verificationOutcome"], "not_passed")

    def test_late_date_challenge_consumes_the_same_single_authorization(self) -> None:
        self.install_payloads([snapshot(), {"captcha": True, "ready": False}])

        def gesture(driver, state):
            state.update(attempted=True, outcome="not_passed")
            return True

        with (
            patch.object(server, "VERIFICATION_AVAILABLE", True),
            patch.object(server, "_normal_verification_once", side_effect=gesture) as action,
        ):
            result = server.scrape_available_slots(
                "baoti", 2, source_evidence=True, verification_once=True
            )
        action.assert_called_once()
        self.assertEqual(result["days"], [])
        self.assertEqual(result["error"], "captcha")
        self.assertEqual(result["diagnostics"]["failurePhase"], "refreshed_schedule")
        self.assertEqual(result["diagnostics"]["requestedProduct"], "111317")
        self.assertTrue(result["diagnostics"]["verificationAttempted"])

    def test_verification_recovery_requires_valid_source_and_never_repeats(self) -> None:
        self.install_payloads([{"captcha": True}, snapshot(TOMORROW, 2)])
        state = {"attempted": False, "outcome": "not_needed"}

        def gesture(driver, state):
            state.update(attempted=True, outcome="not_passed")
            return True

        with patch.object(server, "_normal_verification_once", side_effect=gesture) as action:
            result = server._wait_for_schedule(
                self.driver,
                timeout=10,
                expected_date=TOMORROW.isoformat(),
                previous=snapshot(),
                verification=state,
                **OUTDOOR_IDENTITY,
            )
            self.assertTrue(result["ready"])
            self.assertEqual(state["outcome"], "passed")
            with patch.object(server, "_extract_day", return_value={"captcha": True}):
                failed = server._wait_for_schedule(
                    self.driver,
                    timeout=10,
                    verification=state,
                    **OUTDOOR_IDENTITY,
                )
            self.assertFalse(failed["ready"])
            action.assert_called_once()

    def test_ordinary_watcher_results_never_include_source_evidence(self) -> None:
        self.install_payloads(self.group_payloads(venue="dsh"))
        result = server.scrape_available_slots("dsh", 2)
        self.assertTrue(result["ok"])
        self.assertNotIn("source_evidence", str(result))
        self.assertTrue(all(not call.kwargs for call in self.extract.call_args_list))

    def test_busy_inspect_is_serialized_before_starting_a_second_browser(self) -> None:
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/inspect?venue=baoti&days=2"
        responses = []
        handler._send_json = lambda status, body: responses.append((status, body))
        server.SCRAPE_LOCK.acquire()
        try:
            handler.do_GET()
        finally:
            server.SCRAPE_LOCK.release()
        self.assertEqual(responses[0][0], 429)
        self.assertEqual(responses[0][1]["error"], "busy")
        server._start_chromium.assert_not_called()


class PiDriverLifecycleTest(unittest.TestCase):
    def test_native_browser_launch_uses_fixed_profile_and_no_user_agent_override(self) -> None:
        profile = Path("/tmp/service-profile/baoti-outdoor")
        with patch.object(server.subprocess, "Popen") as popen:
            server._start_chromium(server._baoti_group_url("111317"), profile=profile)
        command = popen.call_args.args[0]
        self.assertIn("--user-data-dir=" + str(profile), command)
        self.assertFalse(any(argument.startswith("--user-agent=") for argument in command))

    def test_source_sanitizer_removes_nested_private_literals_and_comments(self) -> None:
        code = """function textFun(e) {
          const a = `private-template ${/}/.test(e) ? `nested-private ${e}` : "private-string"}`;
          const b = "https://private.example/?token=private-token";
          const c = /private-regexp/g; /* private-comment */
          return e.className === "noOpen" ? "已预订" : "免费";
        }"""
        source, redacted, incomplete = server._sanitize_function_source(code)
        self.assertTrue(redacted)
        self.assertFalse(incomplete)
        self.assertNotIn("private", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("`", source)
        self.assertIn('"noOpen"', source)
        self.assertIn('"已预订"', source)

    def test_unterminated_literal_is_redacted_and_marked_incomplete(self) -> None:
        source, redacted, incomplete = server._sanitize_function_source(
            'function textFun(){return "private-unfinished'
        )
        self.assertTrue(redacted)
        self.assertTrue(incomplete)
        self.assertNotIn("private", source)

    def test_connection_timeout_is_set_before_creating_session(self) -> None:
        connection = Mock()
        remote_module = types.ModuleType("selenium.webdriver.remote.remote_connection")
        remote_module.RemoteConnection = Mock(return_value=connection)
        config_module = types.ModuleType("selenium.webdriver.remote.client_config")
        config_module.ClientConfig = Mock(
            side_effect=lambda **kwargs: types.SimpleNamespace(**kwargs)
        )
        service = Mock(service_url="http://127.0.0.1:12345")
        driver = Mock()
        timer = Mock()

        def attach_remote(*, command_executor, options):
            self.assertIs(command_executor, connection)
            config = remote_module.RemoteConnection.call_args.kwargs["client_config"]
            self.assertEqual(config.timeout, 30)
            self.assertGreater(config.timeout, 20)
            self.assertFalse(config.keep_alive)
            self.assertEqual(config.remote_server_addr, service.service_url)
            self.assertEqual(options.debugger_address, f"127.0.0.1:{server.DEBUG_PORT}")
            return driver

        with (
            patch.dict(
                sys.modules,
                {remote_module.__name__: remote_module, config_module.__name__: config_module},
            ),
            patch.object(server, "Options", return_value=Mock()),
            patch.object(server, "Service", return_value=service),
            patch.object(server.threading, "Timer", return_value=timer) as timer_factory,
            patch.object(server.webdriver, "Remote", side_effect=attach_remote, create=True),
        ):
            self.assertIs(server._attach(timeout=17), driver)
        timer_factory.assert_called_once_with(17, server._stop_driver_service, args=(service,))
        timer.start.assert_called_once()
        timer.cancel.assert_called_once()
        service.start.assert_called_once()
        self.assertIs(driver._ydmap_service, service)
        self.assertEqual(driver._ydmap_client_config.timeout, 30)
        connection.set_timeout.assert_not_called()
        driver.set_page_load_timeout.assert_called_once_with(20)
        driver.set_script_timeout.assert_called_once_with(8)

    def test_cleanup_keeps_short_wire_timeout_inside_reserved_budget(self) -> None:
        driver, proc = Mock(), Mock(pid=12345)
        driver._ydmap_client_config = types.SimpleNamespace(timeout=30)
        driver._ydmap_service = types.SimpleNamespace(process=None)

        def quit_driver():
            self.assertEqual(driver._ydmap_client_config.timeout, 5)

        driver.quit.side_effect = quit_driver
        with patch.object(server.os, "killpg"):
            server._stop(proc, driver)
        driver.quit.assert_called_once()
        proc.wait.assert_called_once_with(timeout=8)

    def test_unresponsive_driver_process_is_killed_with_bounded_wait(self) -> None:
        process = Mock()
        process.wait.side_effect = TimeoutError()
        service = Mock(process=process)
        server._stop_driver_service(service)
        process.wait.assert_called_once_with(timeout=2)
        process.kill.assert_called_once()
        self.assertIsNone(service.process)

    def test_cleanup_rejects_shared_or_outside_tmp_profile(self) -> None:
        for path in ("/tmp", "/", "/home"):
            with (
                self.subTest(path=path),
                patch.object(server, "PROFILE", Path(path)),
                patch.object(server.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "dedicated directory"):
                    server._cleanup_stale_browser()
                run.assert_not_called()

    def test_cleanup_preserves_dedicated_session_and_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="pi-ydmap-test-") as directory:
            profile = Path(directory) / "profile"
            profile.mkdir(mode=0o755)
            marker = profile / "Cookies"
            marker.write_bytes(b"offline-test-session")
            with (
                patch.object(server, "PROFILE", profile),
                patch.object(server.subprocess, "run"),
                patch.object(server.time, "sleep"),
            ):
                server._cleanup_stale_browser()
                server._cleanup_stale_browser()
            self.assertEqual(marker.read_bytes(), b"offline-test-session")
            self.assertEqual(profile.stat().st_mode & 0o777, 0o700)

    def test_product_profile_cannot_escape_service_directory(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="pi-ydmap-test-") as directory:
            base = Path(directory) / "service"
            other = Path(directory) / "other"
            other.mkdir(mode=0o755)
            with (
                patch.object(server, "PROFILE", base),
                patch.object(server.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "dedicated directory"):
                    server._cleanup_stale_browser(other)
                run.assert_not_called()
            self.assertEqual(other.stat().st_mode & 0o777, 0o755)

    def test_product_profile_rejects_cross_product_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="pi-ydmap-test-") as directory:
            base = Path(directory)
            target = base / "baoti-indoor"
            target.mkdir(mode=0o755)
            link = base / "baoti-outdoor"
            link.symlink_to(target)
            with (
                patch.object(server, "PROFILE", base),
                patch.object(server.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "dedicated directory"):
                    server._cleanup_stale_browser(link)
                run.assert_not_called()
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_cleanup_rejects_profile_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="pi-ydmap-test-") as directory:
            target = Path(directory) / "target"
            target.mkdir(mode=0o755)
            link = Path(directory) / "profile"
            link.symlink_to(target)
            with (
                patch.object(server, "PROFILE", link),
                patch.object(server.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "dedicated directory"):
                    server._cleanup_stale_browser()
                run.assert_not_called()
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
