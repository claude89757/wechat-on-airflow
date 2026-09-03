from __future__ import annotations

import importlib.util

import pytest


@pytest.mark.parametrize(
    "module",
    ["fastapi", "uvicorn", "sqlalchemy", "psycopg2", "redis", "requests"],
)
def test_notification_core_runtime_dependency_is_installed(module: str) -> None:
    assert importlib.util.find_spec(module) is not None, f"missing runtime dependency: {module}"
