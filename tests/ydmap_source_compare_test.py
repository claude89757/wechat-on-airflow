from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SPEC = importlib.util.spec_from_file_location(
    "compare", Path(__file__).resolve().parents[1] / "scripts/ydmap_source_compare.py"
)
assert SPEC and SPEC.loader
compare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)


def test_source_identity_rejects_cross_product_and_cross_host():
    indoor = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
    assert compare.source_matches(indoor, "indoor")
    assert not compare.source_matches(indoor, "outdoor")
    assert not compare.source_matches(indoor.replace("bawtt", "wxsports"), "indoor")
    assert not compare.source_matches(indoor + "&salesItemId=103224", "indoor")


def test_resource_diagnostics_never_include_queries_or_other_hosts():
    assert (
        compare.public_resource("https://bawtt.ydmap.cn/js/app.js?token=private", "bawtt.ydmap.cn")
        == "/js/app.js"
    )
    assert compare.public_resource("https://other.example/js/app.js", "bawtt.ydmap.cn") is None
    assert compare.public_resource("https://bawtt.ydmap.cn/api/account", "bawtt.ydmap.cn") is None


def test_redaction_bounds_output():
    result = compare.redact(
        "https://example.test?token=private person@example.test token=secretvalue " + "a" * 80
    )
    assert "secretvalue" not in result
    assert "person@" not in result
    assert "private" not in result
    assert len(compare.redact("hello " * 2000)) <= 3500


def test_production_browser_never_reused_and_no_spoofing():
    text = (Path(__file__).resolve().parents[1] / "scripts/ydmap_source_compare.py").read_text()
    for forbidden in (
        "/tmp/dsh_ydmap_profile",
        "pkill",
        "--no-sandbox",
        "--user-agent=",
        "AutomationControlled",
        "Object.defineProperty",
        "get_cookies",
        "--dump-config",
    ):
        assert forbidden not in text
    assert "port == 9224" in text
    assert 'bookabilityVerified": False' in text


def test_empty_table_component_does_not_pass():
    assert (
        compare.classify({"tableFound": True, "classes": {}}, True, [], "indoor")
        == "schedule_component_only"
    )


def test_cells_without_query_responses_do_not_pass_new_source():
    page = {"tableFound": True, "classes": {"": 8}}
    assert (
        compare.classify(page, True, [], "indoor")
        == "schedule_cells_observed_without_query_samples"
    )
    queries = [
        {"path": "/x/getVenueCalendarList", "json": True},
        {"path": "/x/getVenueOrderList", "json": True},
    ]
    assert (
        compare.classify(page, True, queries, "indoor")
        == "query_samples_observed_not_bookability_acceptance"
    )


def test_visible_verification_or_wrong_source_never_passes():
    page = {"tableFound": True, "classes": {"": 8}, "visibleVerifications": ["NeVerify"]}
    assert compare.classify(page, True, [], "dashah_control") == "human_verification_required"
    assert compare.classify({"tableFound": True}, False, [], "indoor") == "unexpected_source"


def test_control_without_response_bodies_is_not_mislabeled_query_success():
    page = {"tableFound": True, "classes": {"completed": 8}}
    assert (
        compare.classify(page, True, [], "dashah_control")
        == "schedule_cells_observed_without_query_samples"
    )


def test_generic_slider_is_not_a_captcha_component():
    assert "name!=='NeVerify'" in compare.PUBLIC_JS
    assert "NeVerify|Slider" not in compare.PUBLIC_JS
    assert "style.opacity" in compare.PUBLIC_JS
    assert "innerHeight" in compare.PUBLIC_JS


def test_visible_access_check_against_real_javascript_cases():
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the actual browser extractor")
    setup = r"""
    const cases=[
      {name:'Slider',text:'网球',height:48,top:0,opacity:'1',expected:[]},
      {name:'NeVerify',text:'',height:0,top:766,opacity:'1',expected:[]},
      {name:'NeVerify',text:'',height:48,top:40,opacity:'1',expected:['NeVerify']},
      {name:'NeVerify',text:'',height:48,top:700,opacity:'1',expected:[]},
      {name:'NeVerify',text:'',height:48,top:40,opacity:'0',expected:[]},
    ];
    const result=[];
    for(const item of cases) {
      const ancestor={parentElement:null,style:{display:'block',visibility:'visible',opacity:item.opacity}};
      const el={parentElement:ancestor,innerText:item.text,
        style:{display:'block',visibility:'visible',opacity:'1'},
        getBoundingClientRect:()=>({width:300,height:item.height,left:0,right:300,top:item.top,bottom:item.top+item.height})};
      const child={$options:{name:item.name},$children:[],$el:el};
      const root={$options:{name:'Layout'},$data:{},$children:[child]};
      const context={
        document:{querySelector:()=>({__vue__:root,innerText:item.text}),body:{innerText:item.text},title:'booking',readyState:'complete'},
        location:{href:'https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317'},
        navigator:{language:'zh-CN',webdriver:false,userAgent:'test'},
        performance:{getEntriesByType:()=>[]},getComputedStyle:(node)=>node.style,
        innerHeight:668,innerWidth:1248,
      };
      const actual=require('vm').runInNewContext('(function(){'+SOURCE+'})()',context);
      result.push({actual:actual.visibleVerifications,expected:item.expected});
    }
    console.log(JSON.stringify(result));
    """
    program = "const SOURCE=" + json.dumps(compare.PUBLIC_JS) + ";\n" + setup
    result = subprocess.run(
        [node, "-e", program], capture_output=True, text=True, timeout=10, check=True
    )
    assert all(item["actual"] == item["expected"] for item in json.loads(result.stdout))


def test_loaded_business_resources_do_not_replay_requests_or_export_private_values():
    import json

    class Driver:
        def __init__(self):
            self.commands = []

        def execute_script(self, expression):
            return [
                "https://bawtt.ydmap.cn/api/account?token=never-export",
                "https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/getVenueOrderList?token=never-export",
                "https://other.example/js/booking-schedule-venue.b6226c5c.js",
            ]

        def execute_cdp_cmd(self, name, params):
            self.commands.append(name)
            if name == "Page.getResourceTree":
                return {"frameTree": {"frame": {"id": "test"}, "resources": []}}
            assert name == "Page.getResourceContent"
            return {"content": json.dumps({"code": 500, "success": False, "phone": "never-export"})}

    driver = Driver()
    result = compare.loaded_business_evidence(driver, "indoor")
    assert len(result) == 1
    assert result[0]["jsonParsed"] is True
    assert result[0]["businessSuccessVerified"] is False
    assert "never-export" not in str(result)
    assert driver.commands == ["Page.getResourceTree", "Page.getResourceContent"]


def test_loaded_verification_response_stops_further_body_reads():
    class Driver:
        def execute_script(self, expression):
            return [
                "https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/getVenueOrderList",
                "https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/getVenueCalendarList",
            ]

        def execute_cdp_cmd(self, name, params):
            if name == "Page.getResourceTree":
                return {"frameTree": {"frame": {"id": "test"}, "resources": []}}
            return {"content": "<html>Access Verification</html>"}

    result = compare.loaded_business_evidence(Driver(), "indoor")
    assert len(result) == 1
    assert result[0]["accessChallenge"] is True
    assert result[0]["reason"] == "verification_response_stop"
