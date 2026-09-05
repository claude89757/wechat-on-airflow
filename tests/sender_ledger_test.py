"""Device process restarts cannot turn a sent/uncertain call into a second send."""

from sender_agent import ledger


def test_sent_result_survives_new_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "ledger.sqlite3"))
    assert ledger.claim("id", "payload") == ("claimed", None)
    result = {"success": True, "sent_count": 1}
    ledger.finish("id", "sent", result)
    assert ledger.claim("id", "payload") == ("sent", result)
    assert ledger.ready()


def test_interrupted_and_unknown_dispatch_are_not_replayed(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "ledger.sqlite3"))
    assert ledger.claim("id", "payload")[0] == "claimed"
    assert ledger.claim("id", "payload")[0] == "submission_unknown"
    ledger.finish("id", "submission_unknown")
    assert ledger.claim("id", "payload")[0] == "submission_unknown"


def test_same_id_with_different_payload_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "ledger.sqlite3"))
    assert ledger.claim("id", "a")[0] == "claimed"
    assert ledger.claim("id", "b")[0] == "conflict"
