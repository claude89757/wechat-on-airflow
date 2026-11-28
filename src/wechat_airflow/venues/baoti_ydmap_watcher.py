"""宝安网球中心（bawtt.ydmap.cn）巡检：室外、室内、风雨场三个产品。

与大沙河、福田三馆同属 YDMap 平台，由树莓派上同一个 ``dsh_ydmap`` Chromium
采集服务读取；宝安网球中心默认由树莓派在独立调试端口与互斥锁上直连采集，
仅当直连触发验证码或限流时自动熔断 30 分钟并切换至 ``isz_https_proxies.txt``
HTTPS 代理池兜底，不干扰其他场馆。

每个产品有自己的采集键，每次运行只加载一个页面：DAG 在独立池 ``ydmap_baoti_browser`` 中每 2 分钟运行一次
（与福田三馆和大沙河的 ``ydmap_browser`` 物理和调度完全隔离），按计划时间轮换产品，
每个产品 6 分钟刷新一次。三个产品发布独立的观测 scope，互不覆盖。
儿童短网不是标准网球场，不采集。

页面规则是「08:00开放预定」，可订今明两天；08:00 前不巡检。
"""

from __future__ import annotations

import datetime

import requests

from wechat_airflow.venues.dsh_ydmap_client import normalize_proxies
from wechat_airflow.venues.ftty_ydmap_watcher import YdmapProduct, YdmapVenue, run_check

BAOTI_PROXY_LIST_URL = (
    "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/isz_https_proxies.txt"
)


def fetch_baoti_proxies(timeout: float = 10.0) -> list[str]:
    """Fetch and validate candidate HTTPS proxies; fall back to Pi-side cache on error."""
    try:
        response = requests.get(
            BAOTI_PROXY_LIST_URL,
            timeout=timeout,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        response.raise_for_status()
        return normalize_proxies(response.text.splitlines())
    except Exception as error:
        print(f"获取宝安网球中心代理池失败，交由 Pi 端缓存兜底: {type(error).__name__}")
        return []


BAOTI = YdmapVenue(
    "baoti",
    booking_open=datetime.time(8, 0),
    products=(
        YdmapProduct("baoti_outdoor", "outdoor"),
        YdmapProduct("baoti_indoor", "indoor"),
        YdmapProduct("baoti_covered", "covered"),
    ),
    proxy_provider=fetch_baoti_proxies,
    max_start_delay=datetime.timedelta(seconds=60),
    rotation_minutes=2,
)


def run_check_tennis_courts() -> None:
    run_check(BAOTI)
