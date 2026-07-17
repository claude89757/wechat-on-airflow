#!/usr/bin/env python
"""
@Time    : 2026/6/7
@Author  : claude89757
@File    : tops_watcher.py
@Software: PyCharm
@Description: TOPS科技园网球场巡检 - 监控未来 3 天的场地可预订情况
"""

import datetime
import random
import time

import requests
import urllib3
from airflow.sdk import Variable

from wechat_airflow.notifications.email import send_venue_email_batch
from wechat_airflow.notifications.wechat import send_wechat_text_to_chatrooms_best_effort

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 常量配置
STORE_ID = "6003356"
PROJECT_UID = "1768791757613876856"
VENUE_NAME = "TOPS科技园"
CACHE_KEY = "TOPS科技园网球场"
PROXY_CACHE_KEY = "TOPS_PROXY_CACHE"
API_URL = "https://wxservice-stg48.pospal.cn/wxapi/AppointmentVenue/LoadValidClassRoomApptSettingV2"
PROXY_LIST_URL = (
    "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
)


def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)


def normalize_time(time_str: str) -> str:
    """
    标准化时间格式
    将 "6:00" 转换为 "06:00"
    将 "24:00" 保持为 "24:00" (用于结束时间)
    """
    if not time_str:
        return time_str
    parts = time_str.split(":")
    if len(parts) == 2:
        hour = int(parts[0])
        minute = int(parts[1])
        return f"{hour:02d}:{minute:02d}"
    return time_str


def merge_time_ranges(data: list[list[str]]) -> list[list[str]]:
    """将时间段合并"""
    if not data:
        return data

    print(f"merging {data}")

    # 处理时间转换，特殊处理 24:00
    def time_to_minutes(time_str: str) -> int:
        hour = int(time_str[:2])
        minute = int(time_str[3:])
        return hour * 60 + minute

    data_in_minutes = sorted(
        [(time_to_minutes(start), time_to_minutes(end)) for start, end in data]
    )

    merged_data = []
    start, end = data_in_minutes[0]
    for i in range(1, len(data_in_minutes)):
        next_start, next_end = data_in_minutes[i]
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged_data.append((start, end))
            start, end = next_start, next_end
    merged_data.append((start, end))

    result = [
        [f"{start // 60:02d}:{start % 60:02d}", f"{end // 60:02d}:{end % 60:02d}"]
        for start, end in merged_data
    ]
    print(f"merged {result}")
    return result


def parse_tops_slot_time(begin_datetime: str, end_datetime: str) -> list[str]:
    """解析 TOPS 小时时段，将 07:59 这类闭区间结束时间归一化为 08:00。"""
    begin_dt = datetime.datetime.strptime(begin_datetime, "%Y-%m-%d %H:%M:%S")
    end_dt = datetime.datetime.strptime(end_datetime, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(
        minutes=1
    )

    start_time = begin_dt.strftime("%H:%M")
    if end_dt.date() > begin_dt.date():
        end_time = "24:00"
    else:
        end_time = end_dt.strftime("%H:%M")

    return [normalize_time(start_time), normalize_time(end_time)]


def parse_tops_availability(json_data: dict) -> dict[str, list[list[str]]]:
    """
    解析 TOPS API 响应，返回按场地分组且合并后的可预约时段。

    Returns:
        {"风雨棚1号场": [["18:00", "20:00"], ...], ...}
    """
    slots = json_data.get("result", {}).get("slots", [])
    court_availability = {}

    for slot in slots:
        appt_info = slot.get("apptInfo") or {}
        if appt_info.get("canApptOrNot") is not True:
            continue

        court_name = slot.get("classRoomName") or "未知场地"
        begin_datetime = slot.get("beginDatetime")
        end_datetime = slot.get("endDatetime")
        if not begin_datetime or not end_datetime:
            continue

        try:
            slot_time = parse_tops_slot_time(begin_datetime, end_datetime)
        except Exception as error:
            print(f"解析 TOPS 时段失败: {slot}, 错误: {error}")
            continue

        if court_name not in court_availability:
            court_availability[court_name] = []
        court_availability[court_name].append(slot_time)

    available_slots_infos = {}
    for court_name in court_availability:
        available_slots_infos[court_name] = merge_time_ranges(court_availability[court_name])

    print(f"available_slots_infos: {available_slots_infos}")
    return available_slots_infos


def parse_end_time_for_duration(end_time: str) -> datetime.datetime:
    """解析用于计算时长的结束时间，支持 24:00。"""
    if end_time == "24:00":
        return datetime.datetime.strptime("23:59", "%H:%M") + datetime.timedelta(minutes=1)
    return datetime.datetime.strptime(end_time, "%H:%M")


def parse_end_time_for_overlap(end_time: str) -> datetime.datetime:
    """解析用于黄金时段重叠判断的结束时间。"""
    if end_time == "24:00":
        return datetime.datetime.strptime("22:00", "%H:%M")
    return datetime.datetime.strptime(end_time, "%H:%M")


def filter_court_data_for_notification(
    input_date: str, court_data: dict[str, list[list[str]]]
) -> list[dict]:
    """按 SYSH 的时间窗口筛选需要通知的 TOPS 空场。"""
    up_for_send_data_list = []
    inform_date = datetime.datetime.strptime(input_date, "%Y-%m-%d").strftime("%m-%d")
    check_date = datetime.datetime.strptime(input_date, "%Y-%m-%d")
    is_weekend = check_date.weekday() >= 5

    if is_weekend:
        target_start = datetime.datetime.strptime("16:00", "%H:%M")
        target_end = datetime.datetime.strptime("22:00", "%H:%M")
    else:
        target_start = datetime.datetime.strptime("18:00", "%H:%M")
        target_end = datetime.datetime.strptime("22:00", "%H:%M")

    for court_name, free_slots in court_data.items():
        if not free_slots:
            continue

        filtered_slots = []
        for slot in free_slots:
            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
            end_time_for_duration = parse_end_time_for_duration(slot[1])
            duration_minutes = (end_time_for_duration - start_time).total_seconds() / 60

            # 只处理1小时或以上的时间段
            if duration_minutes < 60:
                print(f"slot: {slot}, duration_minutes: {duration_minutes}, skip")
                continue
            else:
                print(f"slot: {slot}, duration_minutes: {duration_minutes}, process")

            end_time_for_overlap = parse_end_time_for_overlap(slot[1])
            if max(start_time, target_start) < min(end_time_for_overlap, target_end):
                filtered_slots.append(slot)

        if filtered_slots:
            up_for_send_data_list.append(
                {
                    "date": inform_date,
                    "court_name": f"{VENUE_NAME}{court_name}",
                    "free_slot_list": filtered_slots,
                }
            )

    return up_for_send_data_list


def build_new_notifications(
    up_for_send_data_list: list[dict],
    sended_msg_list: list[str],
    current_year: int = None,
) -> tuple[list[str], list[dict]]:
    """根据已发送缓存构造本轮新增通知和邮件模板数据。"""
    if current_year is None:
        current_year = datetime.datetime.now().year

    up_for_send_msg_list = []
    up_for_send_sms_list = []

    for data in up_for_send_data_list:
        date = data["date"]
        court_name = data["court_name"]
        free_slot_list = data["free_slot_list"]

        date_obj = datetime.datetime.strptime(f"{current_year}-{date}", "%Y-%m-%d")
        weekday = date_obj.weekday()
        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]

        for free_slot in free_slot_list:
            notification = (
                f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
            )
            if notification not in sended_msg_list:
                up_for_send_msg_list.append(notification)
                up_for_send_sms_list.append(
                    {
                        "date": date,
                        "court_name": court_name,
                        "start_time": free_slot[0],
                        "end_time": free_slot[1],
                    }
                )

    return up_for_send_msg_list, up_for_send_sms_list


def update_proxy_cache(proxy: str, success: bool):
    """更新 TOPS 独立代理缓存"""
    try:
        cached_proxies = Variable.get(PROXY_CACHE_KEY, deserialize_json=True, default=[])
    except Exception:
        cached_proxies = []

    if success:
        # 成功的代理加入缓存（如果不存在的话）
        if proxy not in cached_proxies:
            cached_proxies.insert(0, proxy)  # 插入到最前面
            cached_proxies = cached_proxies[:10]  # 保持最多10个
            print(f"添加成功代理到缓存: {proxy}")
    else:
        # 失败的代理从缓存中移除
        if proxy in cached_proxies:
            cached_proxies.remove(proxy)
            print(f"从缓存中移除失败代理: {proxy}")

    Variable.set(PROXY_CACHE_KEY, cached_proxies, serialize_json=True)
    return cached_proxies


def get_tennis_court_availability(date: str, proxy_list: list) -> dict[str, list[list[str]]]:
    """
    调用 TOPS API 获取场地可用情况。

    Args:
        date: 日期字符串，格式 YYYY-MM-DD
        proxy_list: 代理列表

    Returns:
        {"风雨棚1号场": [["09:00", "10:00"], ...], ...}
    """
    got_response = False
    response = None
    successful_proxy = None

    # 获取缓存的代理
    try:
        cached_proxies = Variable.get(PROXY_CACHE_KEY, deserialize_json=True, default=[])
    except Exception:
        cached_proxies = []

    print(f"缓存的代理数量: {len(cached_proxies)}")

    # 准备代理列表：优先使用缓存的代理，然后是其他代理
    remaining_proxies = [p for p in proxy_list if p not in cached_proxies]
    random.shuffle(remaining_proxies)
    all_proxies_to_try = cached_proxies + remaining_proxies

    print(
        f"总共尝试代理数量: {len(all_proxies_to_try)} (缓存: {len(cached_proxies)}, 其他: {len(remaining_proxies)})"
    )

    headers = {
        "STOREID": STORE_ID,
        "Content-Type": "application/json",
    }
    payload = {
        "dateTime": date,
        "projectUid": PROJECT_UID,
    }

    for index, proxy in enumerate(all_proxies_to_try):
        is_cached_proxy = proxy in cached_proxies
        print(f"尝试第 {index + 1} 个代理: {proxy} {'(缓存)' if is_cached_proxy else '(新)'}")

        try:
            proxies = {"https": proxy}
            response = requests.post(
                API_URL, headers=headers, json=payload, proxies=proxies, verify=False, timeout=8
            )
            if response.status_code == 200:
                json_data = response.json()
                if json_data.get("successed") is True and json_data.get("status") == "success":
                    print(f"代理成功: {proxy}")
                    result_data = json_data.get("result", {})
                    print(
                        f"TOPS API返回成功: "
                        f"slots={len(result_data.get('slots', []))}, "
                        f"rooms={len(result_data.get('validClassRooms', []))}"
                    )
                    got_response = True
                    successful_proxy = proxy
                    time.sleep(1)
                    break
                else:
                    print(f"代理失败: {proxy}, API返回错误: {json_data}")
                    update_proxy_cache(proxy, False)
                    continue
            else:
                print(f"代理失败: {proxy}, HTTP状态码: {response.status_code}")
                update_proxy_cache(proxy, False)
                continue
        except Exception as error:
            print(f"代理异常: {proxy}, 错误: {error}")
            update_proxy_cache(proxy, False)
            continue

    # 如果成功，更新代理缓存
    if successful_proxy:
        update_proxy_cache(successful_proxy, True)

    if got_response and response:
        return parse_tops_availability(response.json())
    else:
        raise Exception("all proxies failed")


def load_proxy_list() -> list:
    """读取和 SYSH 一样的外部代理列表。"""
    try:
        response = requests.get(PROXY_LIST_URL, timeout=10, verify=False)
        text = response.text.strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        random.shuffle(proxy_list)
        print(f"Loaded {len(proxy_list)} proxies from {PROXY_LIST_URL}")
        return proxy_list
    except Exception as e:
        print(f"获取代理列表失败: {e}")
        return []


def print_court_data(input_date: str, court_data: dict[str, list[list[str]]]):
    """打印网球场可预订场地详细信息。"""
    print_with_timestamp(f"=== {input_date} 可预订场地详细信息 ===")
    if court_data:
        for court_name, free_slots in court_data.items():
            print_with_timestamp(f"【{court_name}】:")
            if free_slots:
                for slot in free_slots:
                    start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                    end_time = parse_end_time_for_duration(slot[1])
                    duration_minutes = (end_time - start_time).total_seconds() / 60
                    print_with_timestamp(
                        f"  - {slot[0]}-{slot[1]} (时长: {int(duration_minutes)}分钟)"
                    )
            else:
                print_with_timestamp("  - 无可预订时间段")
    else:
        print_with_timestamp("无可预订场地数据")
    print_with_timestamp("=" * 50)


def enqueue_wechat_message(all_in_one_msg: str):
    """通过 best-effort 旁路发送微信消息。"""
    chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default="")
    chat_names_list = str(chat_names).splitlines()
    print(f"chat_names_list: {chat_names_list}")
    return send_wechat_text_to_chatrooms_best_effort(
        chat_names_list,
        all_in_one_msg,
        source="TOPS科技园网球场巡检",
    )


def send_email_notifications(up_for_send_sms_list: list[dict]):
    """批量发送邮件通知。"""
    return send_venue_email_batch(
        "TOPS科技园网球场",
        up_for_send_sms_list,
        recipients_var="TOPS_EMAIL_LIST",
    )


def run_check_tennis_courts():
    """主要检查逻辑"""
    # 0-8点不巡检
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return

    run_start_time = time.time()
    print_with_timestamp("start to check TOPS科技园网球场...")

    # 获取代理列表
    proxy_list = load_proxy_list()

    # 查询空闲的球场信息 - 未来3天
    up_for_send_data_list = []
    for index in range(0, 3):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime("%Y-%m-%d")
        print(f"checking {input_date}...")
        try:
            court_data = get_tennis_court_availability(input_date, proxy_list)
            print_court_data(input_date, court_data)
            time.sleep(1)

            up_for_send_data_list.extend(filter_court_data_for_notification(input_date, court_data))
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue

    print(f"up_for_send_data_list: {up_for_send_data_list}")

    # 处理通知逻辑
    if up_for_send_data_list:
        sended_msg_list = Variable.get(CACHE_KEY, deserialize_json=True, default=[])
        up_for_send_msg_list, up_for_send_sms_list = build_new_notifications(
            up_for_send_data_list,
            sended_msg_list,
        )

        if up_for_send_msg_list:
            # 先落库再发送：发送失败也不重复推同一时段，避免邮件/微信刷屏
            sended_msg_list.extend(up_for_send_msg_list)
            description = (
                f"TOPS科技园网球场场地通知 - 最后更新: "
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            Variable.set(
                key=CACHE_KEY,
                value=sended_msg_list[-100:],
                description=description,
                serialize_json=True,
            )
            print(f"updated {CACHE_KEY} with {len(sended_msg_list)} records")

            all_in_one_msg = "\n".join(up_for_send_msg_list)
            send_email_notifications(up_for_send_sms_list)
            enqueue_wechat_message(all_in_one_msg)

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time: {execution_time:.2f}s")
