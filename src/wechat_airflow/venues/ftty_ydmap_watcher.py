"""福田区体育场馆（ftty.ydmap.cn）巡检：香蜜体育中心、黄木岗网球中心、莲花体育中心。

三个场馆与大沙河国际网球中心同属 YDMap 预订平台，由树莓派上的同一个
``dsh_ydmap`` Chromium 采集服务按 ``venue`` 读取。这里只负责场馆配置、
场地过滤、发布观测和微信去重。

页面规则是「09:00开放预定」，可订今明两天。09:00 前第二天尚未放场，
放场前日期条的形态没有经过验证，所以 09:00 前不巡检，之后固定读两天。

三个 DAG 用 cron 错开，同站每两分钟只加载一次页面。恢复调度或发布后，
Airflow 会立刻补跑每个 DAG 最近一次错过的 tick，三次加载挤在一分钟内会
触发站点滑块验证；所以明显晚于计划时间启动的运行（补跑、重试）直接跳过。

宝安网球中心（``baoti_ydmap_watcher``）复用这里的巡检流程：一个场馆有多
个独立产品，每次运行只读当前两分钟窗口对应的那一个产品，并通过代理池访问。
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable
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
ROTATION_MINUTES = 2
# Natural runs start within seconds of their tick. Anything later is a catch-up
# or retry that would land within a minute of a neighbouring venue's page load.
MAX_START_DELAY = datetime.timedelta(seconds=45)


@dataclass(frozen=True)
class YdmapProduct:
    """One product tab on a multi-product YDMap venue."""

    scraper_venue: str
    observation_scope: str


@dataclass(frozen=True)
class YdmapVenue:
    """One YDMap venue; names come from the venue catalog."""

    venue_id: str
    excluded_court_tokens: tuple[str, ...] = ()
    booking_open: datetime.time = BOOKING_OPEN_TIME
    products: tuple[YdmapProduct, ...] = ()
    proxy_provider: Callable[[], list[str]] | None = None

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


FttyVenue = YdmapVenue

XMTY = YdmapVenue("xmty")
# Training walls are practice walls, not bookable match courts.
HMG = YdmapVenue("hmg", excluded_court_tokens=("训练墙",))
LHTY = YdmapVenue("lhty")
FTTY_VENUES = (XMTY, HMG, LHTY)


def _local_now() -> datetime.datetime:
    return datetime.datetime.now(LOCAL_TIMEZONE)


def _load_device_config() -> PiDeviceConfig:
    return PiDeviceConfig.from_value(Variable.get(CONFIG_VARIABLE, deserialize_json=True))


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def exclude_courts(venue: YdmapVenue, court_data: CourtAvailability) -> CourtAvailability:
    return {
        name: slots
        for name, slots in court_data.items()
        if not any(token in name for token in venue.excluded_court_tokens)
    }


def enqueue_wechat_message(venue: YdmapVenue, all_in_one_msg: str) -> object:
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


def product_for(venue: YdmapVenue, slot: datetime.datetime) -> YdmapProduct | None:
    """The product a run reads: one per two-minute slot, cycling through all of them."""
    if not venue.products:
        return None
    index = int(slot.timestamp()) // (ROTATION_MINUTES * 60) % len(venue.products)
    return venue.products[index]


def _current_dag_run() -> object:
    try:
        from airflow.sdk import get_current_context

        return get_current_context().get("dag_run")
    except Exception:
        return None


def _late_start() -> datetime.timedelta | None:
    return start_delay(_current_dag_run(), datetime.datetime.now(datetime.UTC))


def _run_slot() -> datetime.datetime | None:
    """The run's own tick, so a delayed start still reads the product of its slot."""
    run_after = getattr(_current_dag_run(), "run_after", None)
    if isinstance(run_after, datetime.datetime) and run_after.tzinfo is not None:
        return run_after
    return None


def run_check(venue: YdmapVenue) -> None:
    now = _local_now()
    product = product_for(venue, _run_slot() or now)
    # Each product replaces only its own scope; None keeps a single-product venue's default.
    scope = product.observation_scope if product else None
    scope_kwargs = {"observation_scope": scope} if scope is not None else {}
    scraper_venue = product.scraper_venue if product else venue.venue_id
    if now.time() < venue.booking_open:
        opens = venue.booking_open.strftime("%H:%M")
        print(f"{venue.name}每天{opens}开放预定，{opens}前不巡检")
        publish_venue_observation(venue.venue_id, venue.name, [], healthy=True, **scope_kwargs)
        return
    delay = _late_start()
    if delay is not None and delay > MAX_START_DELAY:
        # Keep the previous observation; the next natural tick is two minutes away.
        print(
            f"{venue.name}本轮晚于计划 {int(delay.total_seconds())} 秒启动（补跑或重试），跳过以免同站连抓"
        )
        return

    run_start_time = time.time()
    print_with_timestamp(f"start to check {venue.name} ({scraper_venue})...")
    webapp_slots: list[dict[str, str]] = []
    up_for_send_data_list: list[NotificationCourt] = []
    try:
        if venue.proxy_provider is not None:
            proxies = venue.proxy_provider()
            payload = fetch_inspect_payload(
                _load_device_config(),
                days=LOOKAHEAD_DAYS,
                venue=scraper_venue,
                proxies=proxies or None,
            )
        else:
            payload = fetch_inspect_payload(
                _load_device_config(), days=LOOKAHEAD_DAYS, venue=scraper_venue
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
        publish_venue_observation(
            venue.venue_id, venue.name, webapp_slots, healthy=True, **scope_kwargs
        )
    except Exception as error:
        print(f"Error checking {venue.name}: {error}")
        publish_venue_observation(
            venue.venue_id,
            venue.name,
            webapp_slots,
            healthy=False,
            error=type(error).__name__,
            **scope_kwargs,
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
