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
