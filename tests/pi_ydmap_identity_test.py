#!/usr/bin/env python3
"""Execute the production extraction JS against offline source/UI fixtures.

The fixture models fields recorded by the public-script diagnostics in PR223;
synthetic rows are not evidence that a current provider deployment supports them.
Live acceptance must validate the same fields before replacing the Pi service.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

_fixture_spec = importlib.util.spec_from_file_location(
    "pi_ydmap_scraper_fixtures", Path(__file__).with_name("pi_baoti_scraper_test.py")
)
assert _fixture_spec is not None and _fixture_spec.loader is not None
_fixtures = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixtures)
OUTDOOR_IDENTITY = _fixtures.OUTDOOR_IDENTITY
server = _fixtures.server

NODE = shutil.which("node")
if NODE is None and Path("/opt/node-v22/bin/node").is_file():
    NODE = "/opt/node-v22/bin/node"

HARNESS = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const today = Date.parse('2026-11-01T00:00:00+08:00');
const tomorrow = today + 86400000;
const product = {salesItemId: 111317, itemName: '室外网球场'};
if (input.noName) delete product.itemName;
const parent = {
  curDate: today, salesId: 104036, salesItemId: 111317,
  serverData: {
    itemDataList: [product],
    dateDataList: [{day: today}, {day: tomorrow}],
  },
};
function cell(cls, extra = {}) {
  return {
    startTimeText: '18:00', endTimeText: '19:00', className: cls,
    platformInfo: {venueName: '室外场1号', onlineBooking: 1}, priceBean: {price: 0}, ...extra,
  };
}
const rows = input.cells || [cell('')];
const table = {
  $options: {name: 'ScheduleTable'}, $children: [], $parent: parent,
  params: {dateTime: today, salesId: 104036, salesItem: product},
  tableLoadingCounter: 0, tableLoadingFlag: 1,
  serverData: {sportPlatformList: [{venueName: '室外场1号'}], orderInfoList: []},
  rows: [rows],
  isTicket: false,
  // Source rule recorded in the successful October browser inspection.
  isAvailableStatic(col) {
    if (input.invalidPredicate) return 'true';
    return !(col.expired || col.priceBean == null || col.orderNoBook ||
      col.platformInfo.onlineBooking !== 1 || input.notOpen || col.className ||
      col.freeRange || col.rowspan > 1 || col.colspan > 1);
  },
};
if (input.noPredicate) delete table.isAvailableStatic;
let functionCalls = 0;
if (input.renderer) {
  const definitions = {
    isAvailableStatic: table.isAvailableStatic,
    textFun: function textFun(col) {
      functionCalls++;
      // private-comment-token
      const ignored = 'https://private.example/?token=private-token';
      return col.className === 'noOpen' ? '已预订' : '免费';
    },
    isNoBook: function isNoBook(col) { functionCalls++; return !!col.orderNoBook; },
    closeMsg: function closeMsg() { functionCalls++; return '不可预约'; },
    sellerMessage: function sellerMessage(col) { functionCalls++; return col.orderInfo?.sellerMessage; },
    isTicketDisabled: function isTicketDisabled(col) { functionCalls++; return !!col.expired; },
    unrelatedSecretMethod: function unrelatedSecretMethod() { return 'unrelated-private'; },
  };
  for (let i = 0; i < (input.rendererCount || 1); i++) {
    const methods = {...definitions};
    if (input.largeMethods) {
      for (const key of Object.keys(methods)) {
        methods[key] = new Function('col', 'return ' + Array(700).fill('"已预订"').join('+') + '+' + i + ';');
      }
    }
    const renderer = {
      $options: {name: input.componentName || 'CanvasRow', methods,
        computed: {classObj: {get: function classObj() {functionCalls++; return {noOpen: true};}}}},
      $children: [], _isMounted: true, _isDestroyed: false,
      $el: {isConnected: !input.detached},
      row: input.cloned ? rows.map(col => ({...col})) : input.partial ? rows.slice(0, 1) : rows,
    };
    Object.defineProperty(renderer, 'classObj', {get() { throw new Error('computed getter invoked'); }});
    table.$children.push(renderer);
  }
}
if (input.noSource) delete table.serverData;
const root = {$options: {name: 'App'}, $children: [
  {$options: {name: 'Slider'}, $children: []}, table,
]};
const visibleBox = {width: 200, height: 100, left: 10, top: 10, right: 210, bottom: 110};
function mask(hidden) {
  return {getBoundingClientRect: () => visibleBox,
    style: {display: hidden ? 'none' : 'block'}, parentElement: null};
}
globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;
globalThis.getComputedStyle = el => ({
  display: 'block', visibility: 'visible', opacity: '1', contentVisibility: 'visible', ...el.style,
});
globalThis.window = {};
globalThis.location = {hostname: 'bawtt.ydmap.cn'};
globalThis.document = {
  readyState: 'complete',
  body: {innerText: input.body || ''},
  querySelector: selector => selector === '#app' ? {__vue__: root} : null,
  querySelectorAll: selector => selector === '.waf-nc-mask' && input.mask ? [mask(input.mask === 'hidden')] : [],
};
const extract = new Function(input.script);
const results = [extract(input.evidence === true)];
if (input.changeDate) {
  parent.curDate = tomorrow;
  table.params.dateTime = tomorrow;
  table.tableLoadingFlag = 2;
  results.push(extract(input.evidence === true));
  table.serverData.sportPlatformList = [{venueName: '室外场1号'}];
  table.serverData.orderInfoList = [];
  results.push(extract(input.evidence === true));
}
for (const result of results) result.fixtureFunctionCalls = functionCalls;
process.stdout.write(JSON.stringify(results));
"""


@unittest.skipUnless(NODE, "Node is optional on Pi; Python protocol/date tests still run")
class PiYdmapIdentityTest(unittest.TestCase):
    def extract(self, **fixture):
        result = subprocess.run(
            [NODE, "-e", HARNESS],
            input=json.dumps({"script": server.EXTRACT_DAY_JS, **fixture}),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        return json.loads(result.stdout)

    def evidence(self, *, budget=None, label="室外", **fixture):
        raw = self.extract(evidence=True, renderer=True, **fixture)[0]
        self.assertEqual(raw["fixtureFunctionCalls"], 0)
        return server._source_evidence(
            raw["sourceEvidence"],
            label,
            budget
            if budget is not None
            else {"remaining": server.SOURCE_TOTAL_BYTES, "seen": set()},
        )

    def test_source_evidence_is_opt_in_and_never_invokes_renderer_functions(self) -> None:
        ordinary = self.extract(renderer=True)[0]
        self.assertNotIn("sourceEvidence", ordinary)
        self.assertEqual(ordinary["fixtureFunctionCalls"], 0)
        evidence = self.evidence()
        self.assertFalse(evidence["bookability_verified"])
        self.assertTrue(evidence["coverage_complete"])
        self.assertEqual(evidence["matched_cell_count"], 1)
        self.assertEqual({item["name"] for item in evidence["methods"]}, set(server.SOURCE_METHODS))
        self.assertEqual(len(evidence["samples"]), 1)
        serialized = json.dumps(evidence, ensure_ascii=False)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("private-comment", serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("unrelatedSecretMethod", serialized)
        self.assertIn("已预订", serialized)
        self.assertIn("noOpen", serialized)

    def test_unmounted_or_cloned_row_bindings_are_not_complete_coverage(self) -> None:
        for mode in ("detached", "cloned"):
            with self.subTest(mode=mode):
                evidence = self.evidence(**{mode: True})
                self.assertFalse(evidence["coverage_complete"])
                self.assertEqual(evidence["unmatched_cell_count"], 1)
                self.assertFalse(evidence["bookability_verified"])

    def test_methods_components_and_utf8_source_have_hard_bounds(self) -> None:
        evidence = self.evidence(rendererCount=25, largeMethods=True)
        self.assertEqual(len(evidence["components"]), 16)
        self.assertLessEqual(len(evidence["methods"]), 24)
        self.assertTrue(evidence["component_scan_truncated"])
        self.assertTrue(evidence["source_truncated"])
        self.assertFalse(evidence["coverage_complete"])
        self.assertLessEqual(sum(item["emitted_bytes"] for item in evidence["methods"]), 24576)
        for item in evidence["methods"]:
            self.assertLessEqual(len(item["source"].encode("utf-8")), 4096)

    def test_repeated_sources_share_hashes_without_repeating_source_bytes(self) -> None:
        budget = {"remaining": 24576, "seen": set()}
        first = self.evidence(budget=budget)
        second = self.evidence(budget=budget)
        self.assertTrue(all(item["reused"] and item["source"] == "" for item in second["methods"]))
        self.assertEqual(
            [item["sha256"] for item in first["methods"]],
            [item["sha256"] for item in second["methods"]],
        )

    def test_samples_retain_only_public_known_fields_and_two_categories(self) -> None:
        cells = [
            {
                "startTimeText": "18:00",
                "endTimeText": "19:00",
                "className": "",
                "platformInfo": {"venueName": "A号场", "onlineBooking": "private-auth-token"},
                "priceBean": {"price": 100, "private": "private-price-data"},
            },
            {
                "startTimeText": "19:00",
                "endTimeText": "20:00",
                "className": "col-completed private-class",
                "platformInfo": {"venueName": "A号场", "onlineBooking": 1},
                "orderInfo": {"orderNo": "private-order", "sellerMessage": "private-name"},
            },
        ]
        evidence = self.evidence(cells=cells, partial=True, label="室内")
        # Both rows are unavailable; the bounded sampler emits one per category.
        self.assertEqual(len(evidence["samples"]), 1)
        self.assertEqual(evidence["matched_cell_count"], 1)
        self.assertFalse(evidence["coverage_complete"])
        sample = evidence["samples"][0]
        self.assertEqual(sample["court"], "室内A号场")
        self.assertIsNone(sample["online_booking"])
        self.assertTrue(sample["online_booking_redacted"])
        self.assertTrue(sample["has_price"])
        completed = self.evidence(cells=cells[1:])
        self.assertEqual(completed["samples"][0]["known_classes"], ["col-completed"])
        self.assertNotIn("private-", json.dumps(evidence))

    def test_challenge_does_not_collect_optional_function_source(self) -> None:
        for body in ("Access Verification", "请先登录", "您访问的频次过快，请休息一会儿!"):
            with self.subTest(body=body):
                payload = self.extract(evidence=True, renderer=True, body=body)[0]
                self.assertNotIn("sourceEvidence", payload)
                self.assertEqual(payload["fixtureFunctionCalls"], 0)

    def test_chinese_and_english_verification_are_terminal(self) -> None:
        for text in (
            "Access Verification",
            "slide to verify",
            "访问验证",
            "安全验证",
            "请滑动验证",
            "人机验证",
        ):
            with self.subTest(text=text):
                data = self.extract(body=text)[0]
                self.assertTrue(data["captcha"])
                self.assertEqual(data["accessError"], "captcha")

    def test_visible_waf_mask_is_a_challenge_even_without_text(self) -> None:
        data = self.extract(mask="visible")[0]
        self.assertTrue(data["captcha"])
        self.assertTrue(data["challengeMaskVisible"])
        self.assertFalse(data["challengeText"])
        self.assertTrue(data["documentComplete"])
        self.assertTrue(data["scheduleComponentPresent"])

    def test_hidden_waf_mask_and_product_slider_are_not_challenges(self) -> None:
        data = self.extract(mask="hidden", body="室外网球场 11-01 11-02")[0]
        self.assertFalse(data["captcha"])
        self.assertTrue(data["ready"])

    def test_provider_rate_limit_is_not_empty_availability(self) -> None:
        data = self.extract(body='{"code":999998,"message":"您访问的频次过快，请休息一会儿!"}')[0]
        self.assertEqual(data["accessError"], "rate_limited")
        self.assertEqual(server._snapshot_issue(data, **OUTDOOR_IDENTITY), "rate_limited")

    def test_date_selection_alone_does_not_change_loaded_source_identity(self) -> None:
        initial, stale, fresh = self.extract(changeDate=True)
        self.assertEqual(initial["queryDate"], "2026-11-01")
        self.assertEqual(stale["queryDate"], "2026-11-02")
        self.assertEqual(stale["dataVersion"], initial["dataVersion"])
        self.assertEqual(
            server._snapshot_issue(
                stale, expected_date="2026-11-02", previous=initial, **OUTDOOR_IDENTITY
            ),
            "source_not_refreshed",
        )
        self.assertEqual(fresh["signature"], initial["signature"])
        self.assertIsNone(
            server._snapshot_issue(
                fresh, expected_date="2026-11-02", previous=initial, **OUTDOOR_IDENTITY
            )
        )

    def test_product_name_and_id_are_read_from_selected_source_object(self) -> None:
        data = self.extract()[0]
        self.assertEqual(data["productName"], "室外网球场")
        self.assertEqual(data["productNameField"], "itemName")
        self.assertEqual(data["sourceProduct"], "111317")
        self.assertTrue(data["productInCatalog"])
        self.assertIsNone(server._snapshot_issue(data, **OUTDOOR_IDENTITY))

    def test_missing_product_name_or_source_arrays_cannot_be_inferred(self) -> None:
        self.assertEqual(
            server._snapshot_issue(self.extract(noName=True)[0], **OUTDOOR_IDENTITY),
            "product_name_unverified",
        )
        self.assertEqual(
            server._snapshot_issue(self.extract(noSource=True)[0], **OUTDOOR_IDENTITY),
            "source_identity_unavailable",
        )

    def test_unavailable_states_are_excluded_but_court_inventory_remains(self) -> None:
        cells = []
        for index, extra in enumerate(
            (
                {},
                {"className": "col-inprocess"},
                {"className": "noOpen"},
                {"className": "col-completed"},
                {"className": "col-locked"},
                {"className": "col-scheduled"},
                {"expired": True},
                {"orderNoBook": True},
                {"orderInfo": {"dealState": 1}},
            )
        ):
            cells.append(
                {
                    "startTimeText": "18:00",
                    "endTimeText": "19:00",
                    "className": "",
                    "platformInfo": {"venueName": f"室外场{index + 1}号", "onlineBooking": 1},
                    "priceBean": {"price": 0},
                    **extra,
                }
            )
        data = self.extract(cells=cells)[0]
        self.assertEqual(data["courts"], {"室外场1号": [["18:00", "19:00"]]})
        self.assertEqual(data["cellCount"], len(cells))
        self.assertEqual(len(data["courtNames"]), len(cells))

    def test_booking_rules_reject_empty_but_unbookable_cells(self) -> None:
        base = {
            "startTimeText": "18:00",
            "endTimeText": "19:00",
            "className": "",
            "platformInfo": {"venueName": "室外场1号", "onlineBooking": 1},
            "priceBean": {"price": 0},
        }
        self.assertTrue(self.extract(cells=[base])[0]["courts"])
        for extra in (
            {"priceBean": None},
            {"platformInfo": {"venueName": "室外场1号", "onlineBooking": 0}},
            {"freeRange": True},
            {"rowspan": 2},
            {"colspan": 2},
            {"className": "new-vendor-blocked-state"},
            {"orderInfo": {}},
        ):
            with self.subTest(extra=extra):
                data = self.extract(cells=[{**base, **extra}])[0]
                self.assertEqual(data["courts"], {})
                self.assertEqual(data["courtNames"], ["室外场1号"])
                self.assertEqual(data["cellCount"], 1)
        self.assertEqual(self.extract(cells=[base], notOpen=True)[0]["courts"], {})

    def test_missing_or_changed_booking_predicate_fails_closed(self) -> None:
        for mode in ("noPredicate", "invalidPredicate"):
            with self.subTest(mode=mode), self.assertRaises(subprocess.CalledProcessError):
                self.extract(**{mode: True})


if __name__ == "__main__":
    unittest.main()
