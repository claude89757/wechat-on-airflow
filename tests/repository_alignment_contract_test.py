from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NON_VENUE_DAGS = {
    "HTTPS可用代理巡检",
    "HTTPS可用代理巡检_ydmap",
    "zacks_phone_daily_reboot",
    "airflow_db_cleanup",
    "appium_wx_msg_watcher_for_zacks",
}
MYPY_ERROR_IGNORE_BACKLOG = {
    "wechat_airflow.proxy_tools.ydmap_https_proxy_watcher",
    "wechat_airflow.venues.jdwx_watcher",
    "wechat_airflow.venues.sysh_watcher",
    "wechat_airflow.venues.szw_watcher",
    "wechat_airflow.venues.tops_watcher",
    "wechat_airflow.venues.tyzx_watcher",
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_license_statements_match_the_mit_license_file() -> None:
    license_text = read("LICENSE")
    readme = read("README.md")
    readme_en = read("README.en.md")
    project = tomllib.loads(read("pyproject.toml"))["project"]

    assert license_text.startswith("MIT License\n")
    assert project["license"] == {"file": "LICENSE"}
    for document in (readme, readme_en):
        assert "License-MIT-blue" in document
        assert "Apache%202.0" not in document
        assert "Apache License 2.0" not in document
        assert "MIT License" in document


def test_living_acceptance_copy_matches_the_active_venue_count() -> None:
    manifest = yaml.safe_load(read("config/active-components.yaml"))
    runtime = yaml.safe_load(read("config/runtime-target.yaml"))
    venue_ids = [
        item["dag_id"] for item in manifest["active_dags"] if item["dag_id"] not in NON_VENUE_DAGS
    ]
    expected = runtime["managed_services"]["webapp"]["expected_venue_count"]

    assert expected == 27
    assert len(venue_ids) == expected
    assert len(venue_ids) == len(set(venue_ids))
    assert "宝安网球中心巡检" in venue_ids

    assert f"{expected} 个深圳场馆" in read("README.md")
    assert f"{expected} 场馆三次自然巡检" in read("README.md")
    assert f"{expected} Shenzhen venue DAGs" in read("README.en.md")
    assert f"all {expected} venues" in read("README.en.md")
    assert f"all {expected} active" in read("AGENTS.md")
    assert f"All {expected} venue DAGs" in read("ARCHITECTURE.md")
    assert "26 venue DAGs" not in read("AGENTS.md")
    assert "26 场馆" not in read("README.md")


def test_mypy_error_ignores_stay_inside_the_typed_backlog() -> None:
    config = tomllib.loads(read("pyproject.toml"))
    overrides = config["tool"]["mypy"]["overrides"]
    ignored: list[str] = []
    for override in overrides:
        modules = override["module"]
        if isinstance(modules, str):
            modules = [modules]
        if override.get("ignore_errors"):
            ignored.extend(modules)
            continue
        assert override.get("ignore_missing_imports") is True
        assert modules == ["airflow.*"]

    assert set(ignored) == MYPY_ERROR_IGNORE_BACKLOG
    assert "wechat_airflow.proxy_tools.https_proxy_watcher" not in ignored
    for module in ignored:
        relative = Path("src") / Path(*module.split(".")).with_suffix(".py")
        assert (ROOT / relative).is_file()
