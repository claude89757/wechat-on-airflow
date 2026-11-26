"""福田区体育场馆（ftty.ydmap.cn）巡检：香蜜体育中心、黄木岗网球中心、莲花体育中心。

三个场馆与大沙河国际网球中心同属 YDMap 预订平台，由树莓派上的同一个
``dsh_ydmap`` Chromium 采集服务按 ``venue`` 读取。这里只负责场馆配置、
场地过滤、发布观测和微信去重。

页面规则是「09:00开放预定」，可订今明两天。09:00 前第二天尚未放场，
放场前日期条的形态没有经过验证，所以 09:00 前不巡检，之后固定读两天。

三个 DAG 用 cron 错开，同站每两分钟只加载一次页面。恢复调度或发布后，
Airflow 会立刻补跑每个 DAG 最近一次错过的 tick，三次加载挤在一分钟内会
触发站点滑块验证；所以明显晚于计划时间启动的运行（补跑）直接跳过。

延迟按任务进入 ``run_check`` 的墙钟计算，其中包含等待 ``ydmap_browser``
单槽池的时间。采集本身最长约 150 秒，阈值必须高于该上界，否则大沙河占着
池子时福田的正点巡检会被误判成补跑而整轮跳过。
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from airflow.sdk import Variable

from wechat_airflow.notifications.webapp import (
    flatten_court_slots,
    publish_venue_observation,
)
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort
from wechat_airflow.venue_catalog import VENUE_CATALOG, Venue
from wechat_airflow.venues.dsh_ydmap_client import (
    CONFIG_VARIABLE,
    CourtAvailability,
    PiDeviceConfig,
    fetch_inspect_payload,
    parse_inspect_payload,
)
from wechat_airflow.venues.dsh_ydmap_watcher import (
    NotificationCourt,
    build_new_notifications,
    canonicalize_court_availability,
    filter_court_data_for_notification,
    print_court_data,
    print_with_timestamp,
)

LOOKAHEAD_DAYS = 2
BOOKING_OPEN_TIME = datetime.time(9, 0)
MAX_CACHED_MESSAGES = 100
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
# Wall-clock delay includes ydmap_browser pool wait (curl --max-time 150).
# Keep the threshold above that ceiling so a natural tick queued behind Dashah
# still inspects; only release-restore / unpause catch-ups (minutes late) skip.
MAX_START_DELAY = datetime.timedelta(minutes=5)


@dataclass(frozen=True)
class FttyVenue:
    """One ftty.ydmap.cn venue; names come from the venue catalog."""

    venue_id: str
    excluded_court_tokens: tuple[str, ...] = ()

    @property
    def _entry(self) -> Venue:
        return next(item for item in VENUE_CATALOG if item["id"] == self.venue_id)

    @property
    def name(self) -> str:
        return self._entry["name"]

    @property
    def dag_id(self) -> str:
        return self._entry["dagId"]

    @property
    def cache_key(self) -> str:
        # The catalog's wechatName is the WeChat dedupe Variable for this venue.
        return self._entry["wechatName"]


XMTY = FttyVenue("xmty")
# Training walls are practice walls, not bookable match courts.
HMG = FttyVenue("hmg", excluded_court_tokens=("训练墙",))
LHTY = FttyVenue("lhty")
FTTY_VENUES = (XMTY, HMG, LHTY)


def _local_now() -> datetime.datetime:
    return datetime.datetime.now(LOCAL_TIMEZONE)


def _load_device_config() -> PiDeviceConfig:
    return PiDeviceConfig.from_value(Variable.get(CONFIG_VARIABLE, deserialize_json=True))


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def exclude_courts(venue: FttyVenue, court_data: CourtAvailability) -> CourtAvailability:
    return {
        name: slots
        for name, slots in court_data.items()
        if not any(token in name for token in venue.excluded_court_tokens)
    }


def enqueue_wechat_message(venue: FttyVenue, all_in_one_msg: str) -> object:
    chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default="")
    return send_wechat_text_to_chatrooms_best_effort(
        str(chat_names).splitlines(),
        all_in_one_msg,
        source=venue.dag_id,
        booking_venue_id=venue.venue_id,
    )


def start_delay(dag_run: object, now: datetime.datetime) -> datetime.timedelta | None:
    """How late a scheduled run started; None for manual or unknown runs."""
    run_type = getattr(dag_run, "run_type", None)
    run_after = getattr(dag_run, "run_after", None)
    if str(getattr(run_type, "value", run_type)) != "scheduled":
        return None
    if not isinstance(run_after, datetime.datetime) or run_after.tzinfo is None:
        return None
    return now - run_after


def _late_start() -> datetime.timedelta | None:
    try:
        from airflow.sdk import get_current_context

        context = get_current_context()
    except Exception:
        return None
    return start_delay(context.get("dag_run"), datetime.datetime.now(datetime.UTC))


def run_check(venue: FttyVenue) -> None:
    now = _local_now()
    if now.time() < BOOKING_OPEN_TIME:
        print(f"{venue.name}每天09:00开放预定，09:00前不巡检")
        publish_venue_observation(venue.venue_id, venue.name, [], healthy=True)
        return
    delay = _late_start()
    if delay is not None and delay > MAX_START_DELAY:
        # Keep the previous observation; the next natural tick is two minutes away.
        print(
            f"{venue.name}本轮晚于计划 {int(delay.total_seconds())} 秒启动（补跑），跳过以免同站连抓"
        )
        return

    run_start_time = time.time()
    print_with_timestamp(f"start to check {venue.name}...")
    webapp_slots: list[dict[str, str]] = []
    up_for_send_data_list: list[NotificationCourt] = []
    try:
        payload = fetch_inspect_payload(
            _load_device_config(), days=LOOKAHEAD_DAYS, venue=venue.venue_id
        )
        availability = parse_inspect_payload(payload)
        for offset in range(LOOKAHEAD_DAYS):
            input_date = (now.date() + datetime.timedelta(days=offset)).isoformat()
            court_data = canonicalize_court_availability(
                exclude_courts(venue, availability.get(input_date, {}))
            )
            webapp_slots.extend(flatten_court_slots(input_date, court_data))
            print_court_data(input_date, court_data)
            up_for_send_data_list.extend(
                filter_court_data_for_notification(input_date, court_data, venue.name)
            )
        publish_venue_observation(venue.venue_id, venue.name, webapp_slots, healthy=True)
    except Exception as error:
        print(f"Error checking {venue.name}: {error}")
        publish_venue_observation(
            venue.venue_id,
            venue.name,
            webapp_slots,
            healthy=False,
            error=type(error).__name__,
        )
        print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")
        return

    if up_for_send_data_list:
        sended_msg_list = _as_str_list(
            Variable.get(venue.cache_key, deserialize_json=True, default=[])
        )
        up_for_send_msg_list = build_new_notifications(
            up_for_send_data_list, sended_msg_list, current_year=now.year
        )
        if up_for_send_msg_list:
            sended_msg_list.extend(up_for_send_msg_list)
            Variable.set(
                key=venue.cache_key,
                value=sended_msg_list[-MAX_CACHED_MESSAGES:],
                description=(
                    f"{venue.name}网球场场地通知 - 最后更新: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                serialize_json=True,
            )
            enqueue_wechat_message(venue, "\n".join(up_for_send_msg_list))

    print_with_timestamp(f"Total cost time: {time.time() - run_start_time:.2f}s")


def run_check_xmty() -> None:
    run_check(XMTY)


def run_check_hmg() -> None:
    run_check(HMG)


def run_check_lhty() -> None:
    run_check(LHTY)
