from __future__ import annotations

import ast
import datetime as real_datetime
import importlib
import importlib.util
import shlex
import sys
import types
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FakeVariable:
    values: dict[str, object] = {}

    @classmethod
    def get(cls, key: str, default: object = None, deserialize_json: bool = False) -> object:
        return cls.values.get(key, default)

    @classmethod
    def set(
        cls,
        key: str,
        value: object,
        description: str | None = None,
        serialize_json: bool = False,
    ) -> None:
        cls.values[key] = value


def _install_import_stubs() -> None:
    sdk = types.ModuleType("airflow.sdk")
    sdk.Variable = FakeVariable  # type: ignore[attr-defined]
    sys.modules.setdefault("airflow", types.ModuleType("airflow"))
    sys.modules.setdefault("airflow.sdk", sdk)


_install_import_stubs()
booking_links = importlib.import_module("wechat_airflow.notifications.booking_links")
client = importlib.import_module("wechat_airflow.venues.dsh_ydmap_client")
ftty = importlib.import_module("wechat_airflow.venues.ftty_ydmap_watcher")

SSH = {
    "host": "203.0.113.10",
    "port": 6000,
    "username": "pi-user",
    "password": "secret",
    "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    FakeVariable.values = {"PI_DEVICE_SSH": dict(SSH), "SZ_TENNIS_CHATROOMS": "Zacks_网球场"}
    monkeypatch.setattr(ftty, "Variable", FakeVariable)
    state: dict[str, Any] = {"published": [], "sent": [], "fetches": [], "payload": None}

    def fake_fetch(config: object, *, days: int, venue: str) -> object:
        state["fetches"].append({"days": days, "venue": venue})
        if isinstance(state["payload"], Exception):
            raise state["payload"]
        return state["payload"]

    def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
        state["published"].append((args, kwargs))
        return {"success": True}

    def fake_send(chatrooms: list[str], message: str, **kwargs: object) -> object:
        state["sent"].append((chatrooms, message, kwargs))
        return {"success": True}

    monkeypatch.setattr(ftty, "fetch_inspect_payload", fake_fetch)
    monkeypatch.setattr(ftty, "publish_venue_observation", fake_publish)
    monkeypatch.setattr(ftty, "send_wechat_text_to_chatrooms_best_effort", fake_send)
    return state


def _at(monkeypatch: pytest.MonkeyPatch, hour: int, minute: int = 0) -> None:
    # 2026-11-27 is a Friday; 2026-11-28 is a Saturday.
    monkeypatch.setattr(
        ftty,
        "_local_now",
        lambda: real_datetime.datetime(2026, 11, 27, hour, minute, tzinfo=ftty.LOCAL_TIMEZONE),
    )


def test_catalog_supplies_names_dags_and_dedupe_keys() -> None:
    assert [venue.venue_id for venue in ftty.FTTY_VENUES] == ["xmty", "hmg", "lhty"]
    assert ftty.XMTY.name == "香蜜体育中心"
    assert ftty.HMG.dag_id == "黄木岗网球中心巡检"
    assert ftty.LHTY.cache_key == "莲花体育中心网球场"


@pytest.mark.parametrize(
    "file,callable_name,venue,cron",
    [
        ("xmty_ydmap_watcher.py", "run_check_xmty", "xmty", "0-59/6 * * * *"),
        ("hmg_ydmap_watcher.py", "run_check_hmg", "hmg", "2-59/6 * * * *"),
        ("lhty_ydmap_watcher.py", "run_check_lhty", "lhty", "4-59/6 * * * *"),
    ],
)
def test_dag_files_wire_their_venue_into_the_shared_browser_pool(
    file: str, callable_name: str, venue: str, cron: str
) -> None:
    tree = ast.parse((ROOT / "dags/tennis_dags/sz_tennis" / file).read_text(encoding="utf-8"))
    calls = {
        node.func.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    dag = calls["DAG"]
    entry = next(item for item in ftty.FTTY_VENUES if item.venue_id == venue)
    assert ast.literal_eval(dag.args[0]) == entry.dag_id
    dag_options = {keyword.arg: keyword.value for keyword in dag.keywords}
    assert ast.literal_eval(dag_options["schedule"]) == cron
    operator = {keyword.arg: keyword.value for keyword in calls["PythonOperator"].keywords}
    assert ast.literal_eval(operator["pool"]) == "ydmap_browser"
    python_callable = operator["python_callable"]
    assert isinstance(python_callable, ast.Name) and python_callable.id == callable_name


def test_ftty_dags_space_host_loads_two_minutes_apart() -> None:
    minutes = []
    for file in ("xmty_ydmap_watcher.py", "hmg_ydmap_watcher.py", "lhty_ydmap_watcher.py"):
        tree = ast.parse((ROOT / "dags/tennis_dags/sz_tennis" / file).read_text(encoding="utf-8"))
        dag = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "DAG"
        )
        cron = ast.literal_eval({k.arg: k.value for k in dag.keywords}["schedule"])
        first, step = cron.split()[0].split("/")
        minutes.extend(range(int(first.split("-")[0]), 60, int(step)))
    minutes.sort()
    gaps = [b - a for a, b in zip(minutes, [*minutes[1:], minutes[0] + 60], strict=True)]
    # The shared ftty.ydmap.cn host sees one page load every two minutes, never closer.
    assert set(gaps) == {2}


def test_before_booking_opens_publishes_empty_without_scraping(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 8, 59)
    ftty.run_check(ftty.XMTY)
    assert harness["fetches"] == []
    assert harness["published"] == [(("xmty", "香蜜体育中心", []), {"healthy": True})]
    assert harness["sent"] == []


def test_inspects_two_days_and_drops_training_walls(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 9, 0)
    harness["payload"] = {
        "ok": True,
        "captcha": False,
        "days": [
            {
                "date": "2026-11-27",
                "courts": {
                    "1号室外场": [["18:00", "18:30"], ["18:30", "19:00"], ["22:00", "22:30"]],
                    "1号训练墙": [["18:00", "20:00"]],
                },
            },
            {"date": "2026-11-28", "courts": {"7号风雨场": [["16:00", "17:00"]]}},
        ],
    }
    ftty.run_check(ftty.HMG)

    assert harness["fetches"] == [{"days": 2, "venue": "hmg"}]
    args, kwargs = harness["published"][0]
    assert args[:2] == ("hmg", "黄木岗网球中心") and kwargs == {"healthy": True}
    published_courts = {slot["court_name"] for slot in args[2]}
    assert published_courts == {"1号室外场", "7号风雨场"}
    chatrooms, message, options = harness["sent"][0]
    assert chatrooms == ["Zacks_网球场"]
    assert message.splitlines() == [
        "【黄木岗网球中心1号室外场】星期五(11-27)空场: 18:00-19:00",
        "【黄木岗网球中心7号风雨场】星期六(11-28)空场: 16:00-17:00",
    ]
    assert options == {"source": "黄木岗网球中心巡检", "booking_venue_id": "hmg"}
    assert FakeVariable.values["黄木岗网球中心"] == message.splitlines()


def test_repeated_availability_is_not_resent(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 12, 0)
    harness["payload"] = {
        "ok": True,
        "days": [{"date": "2026-11-27", "courts": {"1号网球场": [["19:00", "21:00"]]}}],
    }
    ftty.run_check(ftty.LHTY)
    ftty.run_check(ftty.LHTY)
    assert len(harness["sent"]) == 1
    assert len(harness["published"]) == 2


def test_scrape_failure_publishes_unhealthy_and_does_not_notify(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 12, 0)
    harness["payload"] = {"ok": False, "captcha": True, "days": []}
    ftty.run_check(ftty.XMTY)
    assert harness["published"] == [
        (("xmty", "香蜜体育中心", []), {"healthy": False, "error": "ValueError"})
    ]
    assert harness["sent"] == []


def _shell_words(command: str) -> list[str]:
    """Split like a POSIX shell, keeping control operators such as ``&`` apart."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def test_client_selects_the_venue_and_keeps_the_dashah_request(monkeypatch) -> None:
    commands: list[str] = []

    def fake_exec(*args: object, **kwargs: object) -> tuple[str, str, int]:
        commands.append(str(args[5]))
        return '{"ok": true, "days": []}', "", 0

    monkeypatch.setattr(client, "exec_pi_command", fake_exec)
    config = client.PiDeviceConfig.from_value(SSH)
    client.fetch_inspect_payload(config, days=2, venue="xmty")
    client.fetch_inspect_payload(config, days=5)
    # The Pi parses the command with a shell; the whole URL must stay one argument
    # (an unquoted "&" backgrounds curl and drops days=2).
    assert _shell_words(commands[0]) == [
        "curl",
        "-sS",
        "--max-time",
        "150",
        "http://127.0.0.1:8788/inspect?venue=xmty&days=2",
    ]
    assert _shell_words(commands[1])[-1] == "http://127.0.0.1:8788/inspect?days=5"
    with pytest.raises(ValueError):
        client.fetch_inspect_payload(config, days=2, venue="xmty;id")


def test_failed_scrape_reports_the_scraper_error_code(monkeypatch) -> None:
    body = '{"ok": false, "captcha": false, "error": "requested_date_unavailable", "days": []}'
    monkeypatch.setattr(client, "exec_pi_command", lambda *args, **kwargs: (body, "", 0))
    payload = client.fetch_inspect_payload(
        client.PiDeviceConfig.from_value(SSH), days=2, venue="hmg"
    )
    with pytest.raises(ValueError, match="requested_date_unavailable"):
        client.parse_inspect_payload(payload)


def _dag_run(run_type: str, run_after: real_datetime.datetime) -> object:
    return types.SimpleNamespace(run_type=run_type, run_after=run_after)


def test_start_delay_only_measures_scheduled_runs() -> None:
    tick = real_datetime.datetime(2026, 11, 27, 4, 0, tzinfo=real_datetime.UTC)
    later = tick + real_datetime.timedelta(seconds=102)
    assert ftty.start_delay(_dag_run("scheduled", tick), later) == real_datetime.timedelta(
        seconds=102
    )
    assert ftty.start_delay(_dag_run("manual", tick), later) is None
    assert ftty.start_delay(None, later) is None


def test_late_catch_up_runs_skip_without_loading_the_page(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 12, 0)
    harness["payload"] = {"ok": True, "days": []}
    # Release restore / unpause: the latest missed tick fires minutes late.
    monkeypatch.setattr(ftty, "_late_start", lambda: real_datetime.timedelta(seconds=204))
    ftty.run_check(ftty.LHTY)
    assert harness["fetches"] == [] and harness["published"] == []

    monkeypatch.setattr(ftty, "_late_start", lambda: real_datetime.timedelta(seconds=3))
    ftty.run_check(ftty.LHTY)
    assert harness["fetches"] == [{"days": 2, "venue": "lhty"}]


def _load(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pi_scraper_sources_match_the_installer_and_catalog(monkeypatch) -> None:
    for name in (
        "selenium",
        "selenium.webdriver",
        "selenium.webdriver.chrome",
        "selenium.webdriver.chrome.options",
        "selenium.webdriver.chrome.service",
    ):
        module = types.ModuleType(name)
        module.webdriver = module  # type: ignore[attr-defined]
        module.Options = object  # type: ignore[attr-defined]
        module.Service = object  # type: ignore[attr-defined]
        module.Remote = object  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, module)
    server = _load("ftty_pi_scraper_test", "pi_host/dsh_ydmap/server.py")
    install = _load("ftty_pi_installer_test", "pi_host/dsh_ydmap/install.py")

    assert sorted(server.VENUE_GROUPS) == install.SUPPORTED_VENUES == sorted(install.SOURCES)
    for venue in ftty.FTTY_VENUES:
        ((key, label, url),) = server.VENUE_GROUPS[venue.venue_id]
        parsed = urlparse(url)
        assert (key, label, parsed.hostname) == ("", "", "ftty.ydmap.cn")
        assert install.PRODUCTS[venue.venue_id] == {
            "": (parse_qs(parsed.query)["salesItemId"][0], "")
        }
        assert install.SOURCES[venue.venue_id] == (parsed.hostname, parsed.path.rsplit("/", 1)[-1])
        assert server.VENUE_NAMES[venue.venue_id] == venue.name
        assert venue.dag_id in install.DAG_IDS
        # The WeChat footer opens the same schedule page the Pi scrapes.
        program = booking_links.program_for_venue(venue.venue_id)
        assert program is not None and program.program_id == venue.venue_id
        assert program.link == url
