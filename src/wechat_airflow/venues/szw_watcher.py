#!/usr/bin/env python
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : szw_watcher.py
@Software: PyCharm
"""

import base64
import binascii
import datetime
import json
import re
import ssl
import time
from dataclasses import dataclass

import requests
from airflow.sdk import Variable
from airflow.sdk.exceptions import AirflowFailException
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from wechat_airflow.notifications.webapp import (
    flatten_court_slots,
    publish_venue_observation,
)
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort

SZW_MATRIX_API_URL = "https://wlhmobile.crland.com.cn/business/client/field/area/matrix"
SZW_HOST = "wlhmobile.crland.com.cn"
SZW_APP_ID = "wx020209beec4251e0"
SZW_PROJECT_UUID = "3a59e62a07f811f1bec0aeefcf2e061a"
SZW_FIELD_AREA_UUID = "b7f8a0770a4d11f198f45a68b1262c30"
SZW_COVERED_FIELD_AREA_UUID = "71abff5590af11f195a452a64e4c2bdc"
GBA_PROJECT_UUID = "0ddda9c33d4e11f1b51c2273436a3e4e"
GBA_FIELD_AREA_UUID = "cec42d973dee11f1b51c2273436a3e4e"
CRLAND_REQUEST_ATTEMPTS = 3
CRLAND_RETRY_DELAY_SECONDS = 2
SSL_OP_LEGACY_SERVER_CONNECT = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)


@dataclass(frozen=True)
class CrlandBookingArea:
    project_uuid: str
    field_area_uuid: str
    start_time: str
    end_time: str
    court_name_prefix: str = ""


@dataclass(frozen=True)
class CrlandVenue:
    venue_id: str
    venue_name: str
    booking_areas: tuple[CrlandBookingArea, ...]
    cache_key: str
    dag_id: str


CRLAND_VENUES = {
    "szw": CrlandVenue(
        venue_id="szw",
        venue_name="深圳湾",
        booking_areas=(
            CrlandBookingArea(
                project_uuid=SZW_PROJECT_UUID,
                field_area_uuid=SZW_FIELD_AREA_UUID,
                start_time="08:30",
                end_time="22:30",
            ),
            CrlandBookingArea(
                project_uuid=SZW_PROJECT_UUID,
                field_area_uuid=SZW_COVERED_FIELD_AREA_UUID,
                start_time="07:30",
                end_time="22:30",
                court_name_prefix="风雨场",
            ),
        ),
        cache_key="深圳湾网球场",
        dag_id="深圳湾网球场巡检",
    ),
    "gba": CrlandVenue(
        venue_id="gba",
        venue_name="大湾区网球场",
        booking_areas=(
            CrlandBookingArea(
                project_uuid=GBA_PROJECT_UUID,
                field_area_uuid=GBA_FIELD_AREA_UUID,
                start_time="09:00",
                end_time="21:00",
            ),
        ),
        cache_key="大湾区网球场",
        dag_id="大湾区网球场巡检",
    ),
}


class CrlandLegacyTlsAdapter(HTTPAdapter):
    """Allow the CRLand host's legacy TLS renegotiation only."""

    def __init__(self) -> None:
        self.ssl_context = create_urllib3_context()
        self.ssl_context.options |= SSL_OP_LEGACY_SERVER_CONNECT
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def create_crland_http_session() -> requests.Session:
    session = requests.Session()
    session.mount(f"https://{SZW_HOST}/", CrlandLegacyTlsAdapter())
    return session


def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)


def find_available_slots(booked_slots: list[list[str]], time_range: dict) -> list[list[str]]:
    """查找可用的时间段"""
    if not booked_slots:
        return [[time_range["start_time"], time_range["end_time"]]]

    # 将时间转换为分钟
    booked_in_minutes = sorted(
        [
            (int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:]))
            for start, end in booked_slots
        ]
    )

    start_minutes = int(time_range["start_time"][:2]) * 60 + int(time_range["start_time"][3:])
    end_minutes = int(time_range["end_time"][:2]) * 60 + int(time_range["end_time"][3:])

    available = []
    current = start_minutes

    for booked_start, booked_end in booked_in_minutes:
        if current < booked_start:
            available.append(
                [
                    f"{current // 60:02d}:{current % 60:02d}",
                    f"{booked_start // 60:02d}:{booked_start % 60:02d}",
                ]
            )
        current = max(current, booked_end)

    if current < end_minutes:
        available.append(
            [
                f"{current // 60:02d}:{current % 60:02d}",
                f"{end_minutes // 60:02d}:{end_minutes % 60:02d}",
            ]
        )

    return available


def extract_time_hhmm(time_value: str) -> str:
    """从接口时间字段中提取 HH:MM。"""
    if not time_value:
        return ""

    matched = re.search(r"\d{2}:\d{2}", str(time_value))
    if matched:
        return matched.group(0)
    return ""


def validate_szw_authorization(authorization: str, *, now: float | None = None) -> str:
    """校验并规范化 Airflow Variable 中的 Wechat JWT，不记录令牌内容。"""
    authorization = authorization.strip()
    if not authorization:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 未配置")
    if "\n" in authorization or "\r" in authorization:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 格式非法")

    if authorization.startswith("Wechat "):
        token = authorization.removeprefix("Wechat ")
    elif " " not in authorization:
        token = authorization
    else:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 必须是 Wechat JWT")

    token_parts = token.split(".")
    if len(token_parts) != 3:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 必须是 Wechat JWT")

    try:
        payload_segment = token_parts[1]
        payload_segment += "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment).decode("utf-8"))
        expires_at = payload["exp"]
        if isinstance(expires_at, bool) or not isinstance(expires_at, int | float):
            raise TypeError("exp must be numeric")
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION JWT 格式非法") from None

    current_time = time.time() if now is None else now
    if expires_at <= current_time:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 已过期，请更新令牌")
    return f"Wechat {token}"


def get_free_tennis_court_infos_for_szw(
    date: str,
    proxy_list: list,
    time_range: dict,
    *,
    project_uuid: str = SZW_PROJECT_UUID,
    field_area_uuid: str = SZW_FIELD_AREA_UUID,
    court_name_prefix: str = "",
) -> dict:
    """
    获取可预订的场地信息
    Args:
        date: 日期，格式为YYYY-MM-DD
        proxy_list: 代理列表
        time_range: 时间范围，格式为{"start_time": "HH:MM", "end_time": "HH:MM"}
    Returns:
        dict: 场地信息，格式为{场地名: [[开始时间, 结束时间], ...]}
    """
    szw_authorization = validate_szw_authorization(
        Variable.get("SZW_API_AUTHORIZATION", default="")
    )

    got_response = False
    response_data = None
    last_error = None
    payload = {
        "fieldAreaUuid": field_area_uuid,
        "reserveDate": date,
        "enterpriseUuid": "",
        "discountSpecUuid": "",
        "projectUuid": project_uuid,
    }
    headers = {
        "Host": SZW_HOST,
        "appId": SZW_APP_ID,
        "Authorization": szw_authorization,
        "projectUuid": project_uuid,
        "xweb_xhr": "1",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 "
        "Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
        "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF "
        "MacWechat/3.8.7(0x13080712) UnifiedPCMacWechat(0xf2641c1d) XWEB/25300",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wx020209beec4251e0/59/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    with create_crland_http_session() as session:
        for proxy in proxy_list:
            request_kwargs = {
                "headers": headers,
                "json": payload,
                "timeout": 15,
            }
            if proxy and proxy != "不使用代理":
                request_kwargs["proxies"] = {"https": proxy}

            for attempt in range(1, CRLAND_REQUEST_ATTEMPTS + 1):
                print(f"trying for {proxy}, attempt {attempt}/{CRLAND_REQUEST_ATTEMPTS}")
                retryable = False
                try:
                    print(f"data: {payload}")
                    response = session.post(SZW_MATRIX_API_URL, **request_kwargs)
                    print(f"response status_code: {response.status_code}")
                    if response.status_code == 200:
                        try:
                            response_data = response.json()
                        except Exception as e:
                            last_error = f"invalid json response: {e}"
                            print(last_error)
                            retryable = True
                        else:
                            if response_data.get("code") == 200 and response_data.get("result"):
                                print(f"api success, text: {response_data.get('text')}")
                                got_response = True
                                time.sleep(1)
                                break
                            error_message = response_data.get("text") or response_data.get(
                                "message"
                            )
                            last_error = (
                                f"api error code={response_data.get('code')}, "
                                f"message={error_message}"
                            )
                            print(f"api error for {proxy}: {last_error}")
                            break
                    else:
                        last_error = f"http status code={response.status_code}"
                        print(f"failed for {proxy}: {last_error}")
                        retryable = (
                            response.status_code in {403, 429} or response.status_code >= 500
                        )
                except Exception as error:
                    last_error = str(error)
                    print(f"failed for {proxy}: {last_error}")
                    retryable = True

                if retryable and attempt < CRLAND_REQUEST_ATTEMPTS:
                    time.sleep(CRLAND_RETRY_DELAY_SECONDS)
                    continue
                break
            if got_response:
                break

    if got_response and response_data:
        result = response_data["result"]
        venue_name_infos = {
            venue["fieldUuid"]: f"{court_name_prefix}{venue['fieldName']}"
            for venue in result.get("fieldList", [])
        }
        print(venue_name_infos)

        booked_court_infos = {}

        for venue_info in result.get("matrix", []):
            venue_name = venue_name_infos.get(venue_info.get("fieldUuid"))
            if not venue_name:
                continue
            booked_court_infos.setdefault(venue_name, [])

            for slot_info in venue_info.get("matrix", []):
                if slot_info.get("isAbleReserve"):
                    continue

                start_time = extract_time_hhmm(slot_info.get("startTime", ""))
                end_time = extract_time_hhmm(slot_info.get("endTime", ""))
                if len(start_time) != 5 or len(end_time) != 5:
                    continue
                booked_court_infos[venue_name].append([start_time, end_time])

        available_slots_infos = {}
        for venue_name, booked_slots in booked_court_infos.items():
            available_slots = find_available_slots(booked_slots, time_range)
            if available_slots:
                available_slots_infos[venue_name] = available_slots
        return available_slots_infos
    else:
        raise Exception(f"all attempts failed: {last_error}")


def check_and_notify_for_day(day_offset: int, venue_key: str = "szw"):
    """检查指定天数后的网球场可用情况并发送通知

    Args:
        day_offset: 相对于今天的偏移天数（0表示今天，1表示明天，以此类推）
    """
    venue = CRLAND_VENUES.get(venue_key)
    if venue is None:
        raise ValueError(f"未知华润场地配置: {venue_key}")

    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print(f"Day {day_offset}: 每天0点-8点不巡检")
        publish_venue_observation(venue.venue_id, venue.venue_name, [], healthy=True)
        return

    run_start_time = time.time()
    input_date = (datetime.datetime.now() + datetime.timedelta(days=day_offset)).strftime(
        "%Y-%m-%d"
    )
    inform_date = (datetime.datetime.now() + datetime.timedelta(days=day_offset)).strftime("%m-%d")
    print_with_timestamp(f"Checking tennis courts for {input_date}...")

    # 使用可用代理查询空闲的球场信息
    up_for_send_data_list = []
    webapp_slots = []
    webapp_error = None
    booking_error = None
    try:
        court_data = {}
        for booking_area in venue.booking_areas:
            area_data = get_free_tennis_court_infos_for_szw(
                input_date,
                ["不使用代理"],
                {
                    "start_time": booking_area.start_time,
                    "end_time": booking_area.end_time,
                },
                project_uuid=booking_area.project_uuid,
                field_area_uuid=booking_area.field_area_uuid,
                court_name_prefix=booking_area.court_name_prefix,
            )
            duplicate_courts = court_data.keys() & area_data.keys()
            if duplicate_courts:
                raise ValueError(f"华润场地名称重复: {sorted(duplicate_courts)}")
            court_data.update(area_data)
        print(f"{input_date} court_data: {court_data}")
        webapp_slots.extend(flatten_court_slots(input_date, court_data))

        for court_name, free_slots in court_data.items():
            if free_slots:
                filtered_slots = []
                check_date = datetime.datetime.strptime(input_date, "%Y-%m-%d")
                is_weekend = check_date.weekday() >= 5

                for slot in free_slots:
                    hour_num = int(slot[0].split(":")[0])
                    if is_weekend:
                        if 16 <= hour_num <= 21:  # 周末关注16点到21点的场地
                            filtered_slots.append(slot)
                    else:
                        if 18 <= hour_num <= 21:  # 工作日关注18点到21点的场地
                            filtered_slots.append(slot)

                if filtered_slots:
                    up_for_send_data_list.append(
                        {
                            "date": inform_date,
                            "court_name": f"{venue.venue_name}{court_name}",
                            "free_slot_list": filtered_slots,
                        }
                    )
    except Exception as e:
        print(f"Error checking date {input_date}: {str(e)}")
        webapp_error = str(e)
        booking_error = e

    publish_venue_observation(
        venue.venue_id,
        venue.venue_name,
        webapp_slots,
        healthy=webapp_error is None,
        error=webapp_error,
    )
    if booking_error is not None:
        raise AirflowFailException(
            f"{venue.venue_name}场地接口巡检失败: {webapp_error}"
        ) from booking_error

    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = venue.cache_key
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default=[])
        up_for_send_msg_list = []
        for data in up_for_send_data_list:
            date = data["date"]
            court_name = data["court_name"]
            free_slot_list = data["free_slot_list"]

            date_obj = datetime.datetime.strptime(
                f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d"
            )
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]

            for free_slot in free_slot_list:
                notification = (
                    f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                )
                if notification not in sended_msg_list:
                    up_for_send_msg_list.append(notification)

        if up_for_send_msg_list:
            sended_msg_list.extend(up_for_send_msg_list)
            description = f"{venue.venue_name}场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            Variable.set(
                key=cache_key,
                value=sended_msg_list[-100:],
                description=description,
                serialize_json=True,
            )
            print(f"updated {cache_key} with {sended_msg_list} before delivery")

            all_in_one_msg = "\n".join(up_for_send_msg_list)

            # 发送微信消息
            chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default="")
            chat_names_list = str(chat_names).splitlines()
            print(f"chat_names_list: {chat_names_list}")
            send_wechat_text_to_chatrooms_best_effort(
                chat_names_list,
                all_in_one_msg,
                source=venue.dag_id,
            )

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Day {day_offset} ({input_date}) completed in {execution_time:.2f}s")
