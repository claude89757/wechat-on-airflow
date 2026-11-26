from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest


class FakeVariable:
    values: dict[str, object] = {}

    @classmethod
    def get(cls, key: str, default: object = None, deserialize_json: bool = False) -> object:
        return cls.values.get(key, default)

    @classmethod
    def delete(cls, key: str) -> None:
        cls.values.pop(key, None)


def _install_import_stubs() -> None:
    sdk = types.ModuleType("airflow.sdk")
    sdk.Variable = FakeVariable  # type: ignore[attr-defined]
    sys.modules.setdefault("airflow", types.ModuleType("airflow"))
    sys.modules.setdefault("airflow.sdk", sdk)


_install_import_stubs()
watcher = importlib.import_module("wechat_airflow.proxy_tools.ydmap_https_proxy_watcher")


def test_is_valid_proxy_rejects_non_global_and_malformed() -> None:
    assert watcher.is_valid_proxy("36.147.78.166:443") is True
    for bad in ("127.0.0.1:8080", "10.0.0.1:8080", "192.168.1.1:8080", "http://1.2.3.4:80", "bad"):
        assert watcher.is_valid_proxy(bad) is False


def test_check_proxy_uses_strict_tls_baoti_html_and_rejects_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResp:
        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

    valid_html = "<!DOCTYPE html><html><head><title>宝安网球中心</title></head>" + ("x" * 1200)
    rate_limit = '{"code": 999998, "msg": "您访问的频次过快，请休息一会儿!"}'
    challenge_html = "<!DOCTYPE html><html><body>Access Verification" + ("x" * 1200)

    responses = iter(
        [
            FakeResp(200, valid_html),
            FakeResp(200, rate_limit),
            FakeResp(200, challenge_html),
            FakeResp(200, "<html>tiny</html>"),
            FakeResp(503, valid_html),
        ]
    )

    def fake_get(url: str, **kwargs: Any) -> FakeResp:
        calls.append({"url": url, **kwargs})
        return next(responses)

    monkeypatch.setattr(watcher.requests, "get", fake_get)

    assert watcher.check_proxy("36.147.78.166:443", {}) is True
    assert calls[0]["url"] == watcher.BAOTI_TARGET_URL
    assert calls[0]["verify"] is True
    assert calls[0]["timeout"] == watcher.PROXY_CHECK_TIMEOUT_SECONDS
    assert watcher.check_proxy("36.147.78.166:443", {}) is False
    assert watcher.check_proxy("36.147.78.166:443", {}) is False
    assert watcher.check_proxy("36.147.78.166:443", {}) is False
    assert watcher.check_proxy("36.147.78.166:443", {}) is False


def test_update_proxy_file_prunes_dead_when_live_found_and_preserves_fallback_when_empty(
    tmp_path: Path,
) -> None:
    proxy_file = tmp_path / "isz_https_proxies.txt"
    dead_existing = ["1.1.1.1:8080", "2.2.2.2:8080"]
    proxy_file.write_text("\n".join(dead_existing) + "\n", encoding="utf-8")

    # When live proxies are found, dead existing proxies are pruned immediately.
    watcher.update_proxy_file(str(proxy_file), ["36.147.78.166:443", "36.147.78.166:443"])
    assert proxy_file.read_text(encoding="utf-8").splitlines() == ["36.147.78.166:443"]

    # When a run finds 0 live proxies (e.g. transient VPS glitch), keep up to 20 fallback entries.
    many_existing = [f"8.8.{i // 250}.{i % 250 + 1}:8080" for i in range(25)]
    proxy_file.write_text("\n".join(many_existing) + "\n", encoding="utf-8")
    watcher.update_proxy_file(str(proxy_file), [])
    kept = proxy_file.read_text(encoding="utf-8").splitlines()
    assert len(kept) == 20
    assert kept == many_existing[:20]
