#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import types
import unittest


class FakeDAG:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self) -> FakeDAG:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class FakePythonOperator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __rshift__(self, other: object) -> object:
        return other


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


def install_import_stubs() -> None:
    airflow_module = types.ModuleType("airflow")
    airflow_sdk_module = types.ModuleType("airflow.sdk")
    airflow_sdk_module.DAG = FakeDAG
    airflow_sdk_module.Variable = FakeVariable
    python_module = types.ModuleType("airflow.providers.standard.operators.python")
    python_module.PythonOperator = FakePythonOperator
    sys.modules.setdefault("airflow", airflow_module)
    sys.modules.setdefault("airflow.sdk", airflow_sdk_module)
    sys.modules.setdefault("airflow.providers", types.ModuleType("airflow.providers"))
    sys.modules.setdefault(
        "airflow.providers.standard", types.ModuleType("airflow.providers.standard")
    )
    sys.modules.setdefault(
        "airflow.providers.standard.operators",
        types.ModuleType("airflow.providers.standard.operators"),
    )
    sys.modules["airflow.providers.standard.operators.python"] = python_module


install_import_stubs()
tyzx_watcher = importlib.import_module("wechat_airflow.venues.tyzx_watcher")
tyzx_watcher.Variable = FakeVariable


class TyzxWatcherTest(unittest.TestCase):
    def test_filter_slots_uses_weekday_and_weekend_windows(self) -> None:
        weekday = tyzx_watcher.filter_court_data_for_notification(
            "2026-08-31",
            {
                "1号场": [
                    ["17:00", "18:00"],
                    ["18:00", "19:00"],
                    ["20:00", "21:00"],
                    ["21:00", "22:00"],
                ]
            },
        )
        weekend = tyzx_watcher.filter_court_data_for_notification(
            "2026-08-30",
            {
                "2号场": [
                    ["16:00", "17:00"],
                    ["16:00", "18:00"],
                    ["17:00", "18:00"],
                    ["20:00", "21:00"],
                ]
            },
        )

        self.assertEqual(
            weekday,
            [
                {
                    "date": "08-31",
                    "court_name": "体育中心1号场",
                    "free_slot_list": [["18:00", "19:00"], ["20:00", "21:00"]],
                }
            ],
        )
        self.assertEqual(
            weekend,
            [
                {
                    "date": "08-30",
                    "court_name": "体育中心2号场",
                    "free_slot_list": [
                        ["16:00", "18:00"],
                        ["17:00", "18:00"],
                        ["20:00", "21:00"],
                    ],
                }
            ],
        )
        self.assertEqual(tyzx_watcher.wechat_window_label(True), "17:00-21:00")
        self.assertEqual(tyzx_watcher.wechat_window_label(False), "18:00-21:00")


if __name__ == "__main__":
    unittest.main()
