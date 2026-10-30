"""Offline events only: no website access, profiles or real credentials."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ydmap_query_evidence import QueryTrace, request_metadata  # noqa: E402

HOST = "bawtt.ydmap.cn"
URL = "https://" + HOST + "/srv100244/api/pub/sport/venue/getVenueOrderList"


@pytest.fixture
def trace(monkeypatch):
    sent = []

    class Idle(Exception):
        pass

    def recv():
        raise Idle()

    ws = SimpleNamespace(
        send=lambda value: sent.append(json.loads(value)),
        recv=recv,
        settimeout=lambda _: None,
        close=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "websocket",
        SimpleNamespace(create_connection=lambda *a, **k: ws, WebSocketTimeoutException=Idle),
    )
    result = QueryTrace("ws://127.0.0.1:9999/devtools/page/test", HOST)
    result.consume({"id": 0, "result": {}})
    return result, sent


def start(trace, rid, tick=10, *, url=URL, body=None, redirect=False):
    request = {"url": url, "method": "POST", "headers": {"Cookie": "DO-NOT-EXPORT"}}
    if body is not None:
        request.update(postData=body, hasPostData=True)
    params = {"requestId": rid, "timestamp": tick, "wallTime": 1789554919.25, "request": request}
    if redirect:
        params["redirectResponse"] = {"status": 302}
    trace.consume({"method": "Network.requestWillBeSent", "params": params})


def response(trace, rid, *, url=URL, tick=11):
    trace.consume(
        {
            "method": "Network.responseReceived",
            "params": {
                "requestId": rid,
                "timestamp": tick,
                "response": {"url": url, "status": 200, "mimeType": "application/json"},
            },
        }
    )


def finish(trace, rid, *, tick=12):
    trace.consume(
        {"method": "Network.loadingFinished", "params": {"requestId": rid, "timestamp": tick}}
    )
    return trace.next_id


def test_out_of_order_body_completion_keeps_real_start_order(trace):
    t, sent = trace
    start(
        t,
        "a",
        url=URL + "?salesItemId=111317&token=DO-NOT-EXPORT",
        body='{"bookingDate":"2026-09-16"}',
    )
    start(t, "b", tick=10.5, body='{"salesItemId":103224}')
    response(t, "a")
    response(t, "b")
    first = finish(t, "a")
    second = finish(t, "b", tick=11.5)
    t.consume({"id": second, "result": {"body": '{"code":0,"data":[]}'}})
    t.consume({"id": first, "result": {"body": "访问验证"}})
    assert [q["startOrder"] for q in t.results] == [2, 1]
    assert t.results[1]["durationMs"] == 2000
    assert t.results[1]["startedAt"].endswith("+00:00")
    assert t.results[1]["publicParameters"] == {
        "salesItemId": "111317",
        "bookingDate": "2026-09-16",
    }
    assert t.results[1]["state"] == "access_verification_required"
    assert all(not q["bookabilityVerified"] for q in t.results)
    assert "DO-NOT-EXPORT" not in json.dumps(t.results)
    assert {q["method"] for q in sent} == {"Network.enable", "Network.getResponseBody"}


@pytest.mark.parametrize(
    "request_data",
    [
        {"url": URL},
        {"url": URL, "hasPostData": True},
        {"url": URL, "postData": "opaque-not-a-public-parameter"},
        {"url": URL, "postData": '{"data":{"salesItemId":111317}}'},
    ],
)
def test_missing_or_wrapped_identity_not_inferred(request_data):
    assert request_metadata(request_data)["productBinding"] == "unknown"


@pytest.mark.parametrize(
    "request_data",
    [
        {"url": URL + "?salesItemId=111317&salesItemId=111317"},
        {"url": URL + "?salesItemId=111317", "postData": '{"salesItemId":103224}'},
        {"url": URL, "postData": '{"salesItemId":111317,"salesItemId":103224}'},
        {"url": URL, "postData": '{"salesItemId":true}'},
        {"url": URL + "?salesItemId=PRIVATE-TOKEN"},
    ],
)
def test_ambiguous_or_invalid_identity_never_exported(request_data):
    result = request_metadata(request_data)
    assert result["productBinding"] == "ambiguous"
    assert "salesItemId" not in result["publicParameters"]
    assert "PRIVATE-TOKEN" not in str(result)


def test_direct_form_ids_and_valid_date_only():
    result = request_metadata(
        {"url": URL, "postData": "salesItemId=111317&bookingDate=2026-02-30&token=PRIVATE-TOKEN"}
    )
    assert result["publicParameters"] == {"salesItemId": "111317"}
    assert "bookingDate" in result["ambiguousParameters"]
    assert "PRIVATE-TOKEN" not in str(result)


def test_response_without_start_stays_unknown(trace):
    t, _ = trace
    response(t, "early")
    command = finish(t, "early")
    t.consume({"id": command, "error": {"message": "SECRET-CDP-ERROR"}})
    q = t.results[0]
    assert q["startedAt"] is None and q["startOrder"] is None
    assert q["productBinding"] == "unknown" and q["durationMs"] is None
    assert t.coverage()["responsesWithoutStart"] == 1
    assert "SECRET" not in str(t.results)
    assert not t.coverage()["fullNavigationCaptured"]
    assert not t.coverage()["triggerRateEstimable"]


def test_limit_and_unfinished_requests_are_reported(trace):
    t, sent = trace
    for i in range(18):
        start(t, str(i))
        response(t, str(i))
    finish(t, "0")
    report = t.coverage()
    assert report["retainedRequests"] == 16
    assert report["droppedStartEvents"] == report["droppedResponseEvents"] == 2
    assert report["awaitingResponseOrFinish"] == 15 and report["awaitingBody"] == 1
    assert len(sent) == 2
    assert report["observedRequestStarts"] == 18


def test_redirect_chain_cannot_assign_old_product_to_new_request(trace):
    t, _ = trace
    start(t, "same", url=URL + "?salesItemId=111317")
    start(t, "same", tick=11, url=URL + "?salesItemId=103224", redirect=True)
    response(t, "same")
    command = finish(t, "same")
    t.consume({"id": command, "result": {"body": "{}"}})
    assert [q["publicParameters"]["salesItemId"] for q in t.results] == ["111317", "103224"]
    assert t.results[0]["state"] == "redirected"
    assert t.coverage()["redirects"] == 1


def test_response_source_change_and_network_failure_are_not_success(trace):
    t, sent = trace
    start(t, "a")
    response(t, "a", url="https://other.example/order")
    start(t, "b")
    t.consume(
        {
            "method": "Network.loadingFailed",
            "params": {"requestId": "b", "timestamp": 12, "errorText": "SECRET-URL"},
        }
    )
    assert [q["state"] for q in t.results] == ["response_source_mismatch", "loading_failed"]
    assert len(sent) == 1
    assert "SECRET" not in str(t.results)


def test_queue_drain_bound_and_enable_ack(trace):
    t, _ = trace
    t.ws.recv = lambda: "{}"
    t.drain()
    assert t.coverage()["drainLimitHits"] == 1 and not t.coverage()["queueDrained"]
    with pytest.raises(RuntimeError, match="enable_failed"):
        t.consume({"id": 0, "error": {"message": "SECRET"}})
    assert not t.coverage()["networkEnabled"]


def test_rejects_nonlocal_observation_socket(trace):
    with pytest.raises(ValueError, match="local_trace"):
        QueryTrace("ws://other.example/devtools/page/test", HOST)


def test_missing_invalid_clocks_do_not_manufacture_request_time(trace):
    t, _ = trace
    start(t, "a", tick=float("nan"))
    response(t, "a")
    command = finish(t, "a", tick=10**1000)
    t.consume({"id": command, "result": {"body": "{}"}})
    assert t.results[0]["requestTimestamp"] is None
    assert t.results[0]["finishedTimestamp"] is None
    assert t.results[0]["durationMs"] is None
    json.dumps(t.results, allow_nan=False)


def test_metadata_is_saved_in_finally_even_when_probe_fails():
    import ast

    path = Path(__file__).resolve().parents[1] / "scripts/ydmap_date_query.py"
    tree = ast.parse(path.read_text())
    final_statements = [
        statement
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for statement in node.finalbody
    ]
    text = "\n".join(ast.unparse(statement) for statement in final_statements)
    assert "trace.coverage()" in text
    assert "trace.results" in text
