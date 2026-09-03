from __future__ import annotations

from scripts.configure_zacks_tunnel import PATH_PATTERN, with_zacks_rule


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
