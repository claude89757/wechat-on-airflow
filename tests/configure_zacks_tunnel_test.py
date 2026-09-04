from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.configure_zacks_tunnel import PATH_PATTERN, _dump, with_zacks_rule


def test_inserts_host_core_path_before_general_airflow_rule() -> None:
    source = {
        "tunnel": "example",
        "ingress": [
            {
                "hostname": "airflow.claude89757.cc",
                "service": "http://127.0.0.1:8080",
            },
            {"service": "http_status:404"},
        ],
    }
    updated, changed = with_zacks_rule(
        source,
        hostname="airflow.claude89757.cc",
        service="http://127.0.0.1:8090",
    )
    assert changed is True
    assert updated["ingress"][0] == {
        "hostname": "airflow.claude89757.cc",
        "path": PATH_PATTERN,
        "service": "http://127.0.0.1:8090",
    }
    assert updated["ingress"][1] == source["ingress"][0]


def test_existing_host_core_rule_is_idempotent_and_deduplicated() -> None:
    rule = {
        "hostname": "airflow.claude89757.cc",
        "path": PATH_PATTERN,
        "service": "http://127.0.0.1:8090",
    }
    source = {
        "ingress": [rule, rule, {"service": "http_status:404"}],
    }
    updated, changed = with_zacks_rule(
        source,
        hostname="airflow.claude89757.cc",
        service="http://127.0.0.1:8090",
    )
    assert changed is True
    assert updated["ingress"].count(rule) == 1


def test_exact_existing_rule_requires_no_change() -> None:
    rule = {
        "hostname": "airflow.claude89757.cc",
        "path": PATH_PATTERN,
        "service": "http://127.0.0.1:8090",
    }
    updated, changed = with_zacks_rule(
        {"ingress": [rule, {"service": "http_status:404"}]},
        hostname="airflow.claude89757.cc",
        service="http://127.0.0.1:8090",
    )
    assert changed is False
    assert updated["ingress"][0] == rule


def test_dump_uses_only_keywords_supported_by_the_production_pyyaml(
    tmp_path: Path,
) -> None:
    output = tmp_path / "config.yml"
    document = {"ingress": [{"service": "http_status:404"}]}
    calls: list[dict[str, object]] = []

    def legacy_safe_dump(data: object, stream: object, **kwargs: object) -> None:
        calls.append(kwargs)
        assert "sort_keys" not in kwargs
        yaml.dump(data, stream, allow_unicode=bool(kwargs.get("allow_unicode")))

    with patch("scripts.configure_zacks_tunnel.yaml.safe_dump", side_effect=legacy_safe_dump):
        _dump(output, document, 0o600)

    assert calls == [{"allow_unicode": True}]
    assert yaml.safe_load(output.read_text(encoding="utf-8")) == document
    assert output.stat().st_mode & 0o777 == 0o600
