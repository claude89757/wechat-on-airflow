from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ydmap_query_evidence import query_path, summarize_body  # noqa: E402


def test_query_identity_is_tenant_scoped():
    path = "/srv100244/api/pub/sport/venue/getVenueOrderList"
    assert query_path("https://bawtt.ydmap.cn" + path, "bawtt.ydmap.cn") == path
    for url in (
        "http://bawtt.ydmap.cn" + path,
        "https://wxsports.ydmap.cn" + path,
        "https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/createOrder",
    ):
        assert query_path(url, "bawtt.ydmap.cn") is None


def test_business_error_json_never_passes():
    result = summarize_body(200, "application/json", '{"code":500,"success":false,"data":null}')
    assert result["json"]
    assert result["state"] == "business_error"
    assert not result["businessSuccess"]
    assert not result["bookabilityVerified"]


def test_http_error_json_is_not_success():
    result = summarize_body(403, "application/json", '{"success":true}')
    assert result["state"] == "http_error"
    assert not result["businessSuccess"]


def test_unknown_success_code_is_not_invented():
    for raw in ('{"code":0,"data":[]}', '{"code":200,"data":[]}', "[]"):
        result = summarize_body(200, "application/json", raw)
        assert result["state"] == "json_observed_contract_unverified"
        assert not result["businessSuccess"]


def test_challenge_and_non_json_are_distinct():
    assert summarize_body(200, "text/html", "Access Verification")["accessChallenge"]
    result = summarize_body(200, "text/html", "<title>Temporarily unavailable</title>")
    assert result["state"] == "non_json_response"
    assert not result["json"]


def test_private_values_are_not_exported():
    result = summarize_body(
        200,
        "application/json",
        '{"code":500,"success":false,"token":"PRIVATE-TOKEN","customerName":"PRIVATE-NAME","msg":"token=PRIVATE-MSG"}',
    )
    assert "PRIVATE" not in str(result)
    assert summarize_body(200, "text/plain", "x" * 500001)["state"] == "oversized_response"


def test_trace_keeps_http_evidence_and_reads_only_matching_source(monkeypatch):
    import json
    from types import SimpleNamespace

    from ydmap_query_evidence import QueryTrace

    class NoEvent(Exception):
        pass

    path = "/srv100244/api/pub/sport/venue/getVenueOrderList"
    frames = [
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "a",
                "response": {
                    "url": "https://bawtt.ydmap.cn" + path + "?token=SECRET",
                    "status": 200,
                    "mimeType": "application/json",
                    "headers": {"secret": "SECRET"},
                },
            },
        },
        {"method": "Network.loadingFinished", "params": {"requestId": "a"}},
        {"id": 1, "result": {"body": '{"code":500,"success":false}', "base64Encoded": False}},
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "b",
                "response": {"url": "https://wxsports.ydmap.cn" + path, "status": 200},
            },
        },
        {"method": "Network.loadingFinished", "params": {"requestId": "b"}},
    ]
    sent = []

    def recv():
        if not frames:
            raise NoEvent()
        return json.dumps(frames.pop(0))

    ws = SimpleNamespace(
        send=lambda x: sent.append(json.loads(x)),
        recv=recv,
        settimeout=lambda t: None,
        close=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=lambda *a, **k: ws, WebSocketTimeoutException=NoEvent),
    )
    trace = QueryTrace("ws://127.0.0.1:9011/devtools/page/one", "bawtt.ydmap.cn")
    trace.drain()
    assert len(trace.results) == 1
    assert trace.results[0]["state"] == "business_error"
    assert trace.results[0]["httpStatus"] == 200
    assert "SECRET" not in str(trace.results)
    assert [s["method"] for s in sent] == ["Network.enable", "Network.getResponseBody"]


def test_chinese_access_challenge_is_not_empty_data():
    for body in (
        "<div>访问验证</div><p>为保证您的正常访问,请进行如下验证</p>",
        '<div class="waf-nc-mask"></div>',
        "<title>访问 验证</title>",
        r'{"code":403,"msg":"\u8bbf\u95ee\u9a8c\u8bc1"}',
    ):
        result = summarize_body(200, "text/html", body)
        assert result["state"] == "access_verification_required"
        assert result["accessChallenge"]
        assert not result["businessSuccess"]
        assert not result["bookabilityVerified"]


def test_real_dom_detector_handles_external_mask_not_generic_slider():
    import json
    import shutil
    import subprocess

    import pytest
    from ydmap_query_evidence import PAGE_ACCESS_JS

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual browser JavaScript regression")
    harness = r"""
const js=JSON.parse(process.argv[1]);
const run=new Function('document','getComputedStyle','innerWidth','innerHeight',js);
function element({hidden=false,outside=false,transparentAncestor=false}={}) {
  return {parentElement:transparentAncestor?{style:{opacity:'0'}}:null,
    style:{display:hidden?'none':'block',visibility:'visible',opacity:'0.5'},
    getBoundingClientRect:()=>({width:100,height:100,left:outside?1300:0,
      top:0,right:outside?1400:100,bottom:100})};
}
const cases=[
  {text:'访问验证',elements:[],expected:true},
  {text:'',elements:[element()],expected:true},
  {text:'09-16 星期三 网球',elements:[],expected:false},
  {text:'',elements:[element({hidden:true})],expected:false},
  {text:'',elements:[element({outside:true})],expected:false},
  {text:'',elements:[element({transparentAncestor:true})],expected:false}
];
for(const c of cases){
  const doc={body:{innerText:c.text},querySelectorAll:selector=>{
    if(selector!=='.waf-nc-mask') throw new Error('unexpected or generic selector');
    return c.elements;
  }};
  const actual=run(doc,e=>({display:'block',visibility:'visible',opacity:'1',...e.style}),1248,668);
  if(actual.accessChallenge!==c.expected) throw new Error('incorrect challenge classification');
}
console.log(JSON.stringify({cases:cases.length,passed:true}));
"""
    result = subprocess.run(
        [node, "-e", harness, json.dumps(PAGE_ACCESS_JS)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {"cases": 6, "passed": True}
