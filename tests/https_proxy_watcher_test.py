from __future__ import annotations

import importlib
import sys
import types

airflow = types.ModuleType("airflow")
airflow_sdk = types.ModuleType("airflow.sdk")
airflow_sdk.Variable = types.SimpleNamespace(get=lambda *args, **kwargs: "")
sys.modules.setdefault("airflow", airflow)
sys.modules.setdefault("airflow.sdk", airflow_sdk)

https_proxy_watcher = importlib.import_module("wechat_airflow.proxy_tools.https_proxy_watcher")


def test_proxy_candidate_requires_dotted_host_and_numeric_port() -> None:
    assert https_proxy_watcher.is_valid_proxy("1.2.3.4:8080") is True
    assert https_proxy_watcher.is_valid_proxy("1.2.3.4") is False
    assert https_proxy_watcher.is_valid_proxy("not-a-proxy") is False
    assert https_proxy_watcher.is_valid_proxy("1.2.3.4:abc") is False
    assert https_proxy_watcher.is_valid_proxy("1.2.3.4:80:extra") is False
