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
    get_device_id_by_adb,
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
    """严格按标识字段匹配 zacks 对应配置。"""
    if not appium_server_list:
        raise ValueError("APPIUM_SERVER_LIST 为空，无法定位 zacks 设备")

    for appium_server in appium_server_list:
        if _matches_target(appium_server):
            return appium_server

    raise ValueError("未在 APPIUM_SERVER_LIST 中找到 zacks 对应配置，拒绝回退到其他设备")


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


def choose_adb_serial(appium_server_info: dict, online_devices: list[str]) -> str:
    """从配置和在线设备列表中解析最终可用的 adb serial。"""
    if not online_devices:
        raise ValueError("宿主机 adb devices 未发现在线设备")

    preferred_serials = []
    for key in ("adb_serial", "device_name"):
        value = appium_server_info.get(key)
        if value and value not in preferred_serials:
            preferred_serials.append(value)

    for serial in preferred_serials:
        if serial in online_devices:
            return serial

    if len(online_devices) == 1:
        fallback_serial = online_devices[0]
        print(
            f"[REBOOT] 配置中的设备标识 {preferred_serials or ['<missing>']} 未出现在 adb 列表中，"
            f"回退使用唯一在线设备 {fallback_serial}"
        )
        return fallback_serial

    raise ValueError(
        f"无法确定 zacks 对应的 adb serial，配置标识={preferred_serials or ['<missing>']}，"
        f"在线设备={online_devices}"
    )


def resolve_adb_serial(appium_server_info: dict) -> str:
    """查询宿主机 adb 设备列表并解析可用序列号。"""
    login_info = appium_server_info["login_info"]
    online_devices = get_device_id_by_adb(
        host=login_info["device_ip"],
        port=login_info["port"],
        username=login_info["username"],
        password=login_info["password"],
    )
    adb_serial = choose_adb_serial(appium_server_info, online_devices)
    print(
        f"[REBOOT] 解析 adb serial 成功: config_device_name={appium_server_info.get('device_name')}, "
        f"adb_serial={adb_serial}, online_devices={online_devices}"
    )
    return adb_serial


def resolve_zacks_device_config(**context):
    """输出非敏感设备摘要，便于在 Airflow UI 中观察。"""
    appium_server_info = load_zacks_device_config()
    adb_serial = resolve_adb_serial(appium_server_info)
    sanitized_config = {
        "device_name": appium_server_info["device_name"],
        "adb_serial": adb_serial,
        "device_ip": appium_server_info["login_info"]["device_ip"],
        "wx_name": appium_server_info.get("wx_name"),
    }
    print(f"[REBOOT] 已定位 zacks 设备配置: {sanitized_config}")
    return sanitized_config


def get_resolved_target(context, appium_server_info: dict) -> dict:
    """读取并校验上游解析结果，确保整个 DAG Run 使用同一目标。"""
    resolved_config = context["ti"].xcom_pull(task_ids="resolve_zacks_device_config")
    if not isinstance(resolved_config, dict) or not resolved_config.get("adb_serial"):
        raise ValueError("未从 resolve_zacks_device_config 获取到有效的 adb_serial")

    current_device_ip = appium_server_info["login_info"]["device_ip"]
    current_device_name = appium_server_info["device_name"]
    if (
        resolved_config.get("device_ip") != current_device_ip
        or resolved_config.get("device_name") != current_device_name
    ):
        raise ValueError(
            "zacks 重启任务执行期间设备配置发生变化，"
            f"resolved={resolved_config}, current_device_name={current_device_name}, current_device_ip={current_device_ip}"
        )

    return resolved_config


def reboot_zacks_phone(**context):
    """执行整机重启。"""
    appium_server_info = load_zacks_device_config()
    login_info = appium_server_info["login_info"]
    resolved_config = get_resolved_target(context, appium_server_info)
    adb_serial = resolved_config["adb_serial"]

    if not reboot_device_via_ssh_adb(
        device_ip=login_info["device_ip"],
        username=login_info["username"],
        password=login_info["password"],
        device_serial=adb_serial,
        port=login_info["port"],
    ):
        raise RuntimeError(f"设备 {adb_serial} 执行 reboot 失败")

    return adb_serial


def wait_until_phone_ready(**context):
    """等待设备重启完成并重新可用。"""
    appium_server_info = load_zacks_device_config()
    login_info = appium_server_info["login_info"]
    resolved_config = get_resolved_target(context, appium_server_info)
    adb_serial = resolved_config["adb_serial"]

    if not wait_for_device_boot_completed(
        device_ip=login_info["device_ip"],
        username=login_info["username"],
        password=login_info["password"],
        device_serial=adb_serial,
        port=login_info["port"],
        timeout=600,
        interval=10,
    ):
        raise TimeoutError(f"设备 {adb_serial} 在 600s 内未完成启动")

    print(f"[REBOOT] 设备 {adb_serial} 已完成重启并恢复在线")
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
