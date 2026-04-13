#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天定时重启 Zacks 对应手机的运维 DAG。
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

from utils.appium.ssh_control import (
    reboot_device_via_ssh_adb,
    wait_for_device_boot_completed,
)


TARGET_IDENTIFIERS = ("zacks",)
DAG_ID = "zacks_phone_daily_reboot"


def _matches_target(config: dict) -> bool:
    exact_match_fields = (
        config.get("wx_user_id"),
        config.get("wx_id"),
        config.get("wx_name"),
        config.get("name"),
    )
    normalized_exact_values = {
        str(value).strip().lower()
        for value in exact_match_fields
        if value is not None and str(value).strip()
    }
    if any(identifier in normalized_exact_values for identifier in TARGET_IDENTIFIERS):
        return True

    dag_id = str(config.get("dag_id", "")).strip().lower()
    return any(identifier in dag_id for identifier in TARGET_IDENTIFIERS)


def find_zacks_appium_server(appium_server_list: list[dict]) -> dict:
    """优先按标识字段匹配 zacks，匹配不到时回退到第一个配置。"""
    if not appium_server_list:
        raise ValueError("APPIUM_SERVER_LIST 为空，无法定位 zacks 设备")

    for appium_server in appium_server_list:
        if _matches_target(appium_server):
            return appium_server

    print("[REBOOT] 未找到明确的 zacks 标识，回退到 APPIUM_SERVER_LIST 第一个配置")
    return appium_server_list[0]


def load_zacks_device_config() -> dict:
    """从 Airflow Variable 中解析并校验 zacks 手机配置。"""
    appium_server_list = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)
    appium_server_info = find_zacks_appium_server(appium_server_list)

    login_info = appium_server_info.get("login_info") or {}
    missing_login_keys = [
        key for key in ("device_ip", "username", "password") if not login_info.get(key)
    ]
    if login_info.get("port") is None:
        missing_login_keys.append("port")
    if missing_login_keys:
        raise ValueError(f"zacks 设备 login_info 缺少必要字段: {missing_login_keys}")

    if not appium_server_info.get("device_name"):
        raise ValueError("zacks 设备缺少 device_name，无法执行 adb reboot")

    return appium_server_info


def resolve_zacks_device_config(**context):
    """输出非敏感设备摘要，便于在 Airflow UI 中观察。"""
    appium_server_info = load_zacks_device_config()
    sanitized_config = {
        "device_name": appium_server_info["device_name"],
        "device_ip": appium_server_info["login_info"]["device_ip"],
        "wx_name": appium_server_info.get("wx_name"),
    }
    print(f"[REBOOT] 已定位 zacks 设备配置: {sanitized_config}")
    return sanitized_config


def reboot_zacks_phone(**context):
    """执行整机重启。"""
    appium_server_info = load_zacks_device_config()
    login_info = appium_server_info["login_info"]
    device_name = appium_server_info["device_name"]

    if not reboot_device_via_ssh_adb(
        device_ip=login_info["device_ip"],
        username=login_info["username"],
        password=login_info["password"],
        device_serial=device_name,
        port=login_info["port"],
    ):
        raise RuntimeError(f"设备 {device_name} 执行 reboot 失败")

    return device_name


def wait_until_phone_ready(**context):
    """等待设备重启完成并重新可用。"""
    appium_server_info = load_zacks_device_config()
    login_info = appium_server_info["login_info"]
    device_name = appium_server_info["device_name"]

    if not wait_for_device_boot_completed(
        device_ip=login_info["device_ip"],
        username=login_info["username"],
        password=login_info["password"],
        device_serial=device_name,
        port=login_info["port"],
        timeout=600,
        interval=10,
    ):
        raise TimeoutError(f"设备 {device_name} 在 600s 内未完成启动")

    print(f"[REBOOT] 设备 {device_name} 已完成重启并恢复在线")
    return True


with DAG(
    dag_id=DAG_ID,
    default_args={
        "owner": "claude89757",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    description="每天定时重启 zacks 手机",
    schedule="0 5 * * *",
    start_date=datetime(2025, 4, 13),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=45),
    catchup=False,
    tags=["个人微信", "zacks", "运维"],
) as dag:
    resolve_zacks_device_config_task = PythonOperator(
        task_id="resolve_zacks_device_config",
        python_callable=resolve_zacks_device_config,
        provide_context=True,
    )

    reboot_zacks_phone_task = PythonOperator(
        task_id="reboot_zacks_phone",
        python_callable=reboot_zacks_phone,
        provide_context=True,
    )

    wait_until_phone_ready_task = PythonOperator(
        task_id="wait_until_phone_ready",
        python_callable=wait_until_phone_ready,
        provide_context=True,
    )

    resolve_zacks_device_config_task >> reboot_zacks_phone_task >> wait_until_phone_ready_task
