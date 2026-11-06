from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from wechat_airflow.host_core.domain import VENUES
from wechat_airflow.notifications.wechat import VENUE_DEDUPE_CACHE_KEYS
from wechat_airflow.venue_catalog import VENUE_CATALOG

ROOT = Path(__file__).resolve().parents[1]
NON_VENUE_DAGS = {
    "HTTPS可用代理巡检",
    "HTTPS可用代理巡检_ydmap",
    "zacks_phone_daily_reboot",
    "airflow_db_cleanup",
    "appium_wx_msg_watcher_for_zacks",
}


def active_dags() -> list[dict[str, str]]:
    manifest = yaml.safe_load((ROOT / "config/active-components.yaml").read_text(encoding="utf-8"))
    return manifest["active_dags"]


def test_entries_are_complete_and_unique() -> None:
    for venue in VENUE_CATALOG:
        assert set(venue) == {"id", "name", "wechatName", "dagId"}
        assert re.fullmatch(r"[a-z][a-z0-9_]*", venue["id"])
        assert all(venue.values())
    for field in ("id", "name", "dagId"):
        values = [venue[field] for venue in VENUE_CATALOG]
        assert len(values) == len(set(values)), field


def test_every_venue_dag_has_exactly_one_catalog_entry() -> None:
    venue_dags = {item["dag_id"] for item in active_dags()} - NON_VENUE_DAGS

    assert {venue["dagId"] for venue in VENUE_CATALOG} == venue_dags
    assert "宝安网球中心巡检" not in venue_dags


def test_python_readers_follow_the_catalog() -> None:
    raw = json.loads((ROOT / "src/wechat_airflow/venue_catalog.json").read_text(encoding="utf-8"))

    assert list(VENUES) == [venue["id"] for venue in raw]
    assert VENUES == {venue["id"]: venue["name"] for venue in raw}
    assert VENUE_DEDUPE_CACHE_KEYS == {venue["id"]: venue["wechatName"] for venue in raw}


def test_living_docs_do_not_pin_a_venue_count() -> None:
    count = len(VENUE_CATALOG)
    for path, phrases in {
        "README.md": (f"{count} 个深圳场馆", f"{count} 场馆"),
        "README.en.md": (f"{count} Shenzhen venue", f"all {count} venues"),
        "AGENTS.md": (f"all {count} active",),
        "ARCHITECTURE.md": (f"All {count} venue",),
    }.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase not in text, path
