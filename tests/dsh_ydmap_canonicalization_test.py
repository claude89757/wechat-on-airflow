from __future__ import annotations

import importlib
import sys
import types
import unittest


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


def install_airflow_stubs() -> None:
    airflow_module = types.ModuleType("airflow")
    airflow_sdk_module = types.ModuleType("airflow.sdk")
    airflow_sdk_module.Variable = FakeVariable
    sys.modules.setdefault("airflow", airflow_module)
    sys.modules.setdefault("airflow.sdk", airflow_sdk_module)


install_airflow_stubs()
dsh_watcher = importlib.import_module("wechat_airflow.venues.dsh_ydmap_watcher")
dsh_watcher.Variable = FakeVariable


class DshYdmapCanonicalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVariable.values = {
            "PI_DEVICE_SSH": {
                "host": "203.0.113.10",
                "port": 6000,
                "username": "pi-user",
                "password": "secret",
                "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
            "SZ_TENNIS_CHATROOMS": "Zacks_网球场",
        }

    def test_adjacent_scraper_cells_canonicalize_to_one_stable_range(self) -> None:
        split = {"7号场": [["21:00", "21:30"], ["21:30", "22:00"]]}
        merged = {"7号场": [["21:00", "22:00"]]}

        self.assertEqual(dsh_watcher.canonicalize_court_availability(split), merged)
        self.assertEqual(dsh_watcher.canonicalize_court_availability(merged), merged)

    def test_run_publishes_same_host_core_slot_for_split_and_merged_shapes(self) -> None:
        original_load = dsh_watcher._load_device_config
        original_fetch = dsh_watcher.fetch_inspect_payload
        original_publish = dsh_watcher.publish_venue_observation
        original_enqueue = dsh_watcher.enqueue_wechat_message
        original_datetime = dsh_watcher.datetime

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> FixedDatetime:
                return cls(2026, 9, 6, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        published: list[list[dict[str, str]]] = []
        payloads = [
            {
                "ok": True,
                "days": [
                    {
                        "date": "2026-09-06",
                        "courts": {"7号场": [["21:00", "21:30"], ["21:30", "22:00"]]},
                    }
                ],
            },
            {
                "ok": True,
                "days": [{"date": "2026-09-06", "courts": {"7号场": [["21:00", "22:00"]]}}],
            },
        ]

        def fake_fetch(config: object, *, days: int) -> dict[str, object]:
            return payloads.pop(0)

        def fake_publish(
            venue_id: str,
            venue_name: str,
            slots: list[dict[str, str]],
            **kwargs: object,
        ) -> dict[str, bool]:
            published.append(slots)
            return {"success": True}

        dsh_watcher._load_device_config = lambda: object()
        dsh_watcher.fetch_inspect_payload = fake_fetch
        dsh_watcher.publish_venue_observation = fake_publish
        dsh_watcher.enqueue_wechat_message = lambda message: {"success": True}
        dsh_watcher.datetime = FixedDatetimeModule
        try:
            dsh_watcher.run_check_tennis_courts()
            dsh_watcher.run_check_tennis_courts()
        finally:
            dsh_watcher._load_device_config = original_load
            dsh_watcher.fetch_inspect_payload = original_fetch
            dsh_watcher.publish_venue_observation = original_publish
            dsh_watcher.enqueue_wechat_message = original_enqueue
            dsh_watcher.datetime = original_datetime

        expected = [
            {
                "date": "2026-09-06",
                "court_name": "7号场",
                "start_time": "21:00",
                "end_time": "22:00",
            }
        ]
        self.assertEqual(published, [expected, expected])


if __name__ == "__main__":
    unittest.main()
