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
    platformInfo: {venueName: '室外场1号'}, ...extra,
  };
}
const rows = input.cells || [cell('')];
const table = {
  $options: {name: 'ScheduleTable'}, $children: [], $parent: parent,
  params: {dateTime: today, salesId: 104036, salesItem: product},
  tableLoadingCounter: 0, tableLoadingFlag: 1,
  serverData: {sportPlatformList: [{venueName: '室外场1号'}], orderInfoList: []},
  rows: [rows],
};
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
  body: {innerText: input.body || ''},
  querySelector: selector => selector === '#app' ? {__vue__: root} : null,
  querySelectorAll: selector => selector === '.waf-nc-mask' && input.mask ? [mask(input.mask === 'hidden')] : [],
};
const extract = new Function(input.script);
const results = [extract()];
if (input.changeDate) {
  parent.curDate = tomorrow;
  table.params.dateTime = tomorrow;
  table.tableLoadingFlag = 2;
  results.push(extract());
  table.serverData.sportPlatformList = [{venueName: '室外场1号'}];
  table.serverData.orderInfoList = [];
  results.push(extract());
}
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
        self.assertTrue(self.extract(mask="visible")[0]["captcha"])

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
                    "platformInfo": {"venueName": f"室外场{index + 1}号"},
                    **extra,
                }
            )
        data = self.extract(cells=cells)[0]
        self.assertEqual(data["courts"], {"室外场1号": [["18:00", "19:00"]]})
        self.assertEqual(data["cellCount"], len(cells))
        self.assertEqual(len(data["courtNames"]), len(cells))


if __name__ == "__main__":
    unittest.main()
