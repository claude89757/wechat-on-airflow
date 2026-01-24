#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2026/1/23
@Author  : claude89757
@File    : sysh_watcher.py
@Software: PyCharm
@Description: 上越沙河网球场巡检 - 监控 Tennis168 平台未来 7 天的场地可预订情况
"""
import time
import datetime
import requests
import random
import urllib3

from typing import Dict, List
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from tennis_dags.utils.tencent_ses import send_template_email

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 常量配置
STORE_ID = 117
VENUE_NAME = "上越沙河"
CACHE_KEY = "上越沙河网球场"
PROXY_CACHE_KEY = "SYSH_PROXY_CACHE"
API_URL = "https://sysh.tennis168.vip/api/sports/space/date_list"

# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'start_date': datetime.datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
}


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


def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """将时间段合并"""
    if not data:
        return data

    print(f"merging {data}")

    # 处理时间转换，特殊处理 24:00
    def time_to_minutes(time_str: str) -> int:
        hour = int(time_str[:2])
        minute = int(time_str[3:])
        return hour * 60 + minute

    data_in_minutes = sorted([
        (time_to_minutes(start), time_to_minutes(end))
        for start, end in data
    ])

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

    result = [[f'{start // 60:02d}:{start % 60:02d}', f'{end // 60:02d}:{end % 60:02d}'] for start, end in merged_data]
    print(f"merged {result}")
    return result


def update_proxy_cache(proxy: str, success: bool):
    """更新代理缓存"""
    try:
        cached_proxies = Variable.get(PROXY_CACHE_KEY, deserialize_json=True, default_var=[])
    except:
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


def get_tennis_court_availability(date: str, proxy_list: list) -> Dict[str, List[List[str]]]:
    """
    调用 Tennis168 API 获取场地可用情况

    Args:
        date: 日期字符串，格式 YYYY-MM-DD
        proxy_list: 代理列表

    Returns:
        {"1号场": [["09:00", "10:00"], ...], ...}
    """
    got_response = False
    response = None
    successful_proxy = None

    # 获取缓存的代理
    try:
        cached_proxies = Variable.get(PROXY_CACHE_KEY, deserialize_json=True, default_var=[])
    except:
        cached_proxies = []

    print(f"缓存的代理数量: {len(cached_proxies)}")

    # 准备代理列表：优先使用缓存的代理，然后是其他代理
    remaining_proxies = [p for p in proxy_list if p not in cached_proxies]
    random.shuffle(remaining_proxies)
    all_proxies_to_try = cached_proxies + remaining_proxies

    print(f"总共尝试代理数量: {len(all_proxies_to_try)} (缓存: {len(cached_proxies)}, 其他: {len(remaining_proxies)})")

    params = {
        "date": date,
        "store_id": STORE_ID
    }
    headers = {
        "Host": "sysh.tennis168.vip",
        "store-id": str(STORE_ID),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002629) "
                      "NetType/WIFI Language/zh_CN"
    }

    for index, proxy in enumerate(all_proxies_to_try):
        is_cached_proxy = proxy in cached_proxies
        print(f"尝试第 {index + 1} 个代理: {proxy} {'(缓存)' if is_cached_proxy else '(新)'}")

        try:
            proxies = {"https": proxy}
            response = requests.get(
                API_URL,
                headers=headers,
                params=params,
                proxies=proxies,
                verify=False,  # SSL证书链不完整，需禁用验证
                timeout=5
            )
            if response.status_code == 200:
                json_data = response.json()
                if json_data.get('status') == 200 or json_data.get('msg') == 'ok':
                    print(f"代理成功: {proxy}")
                    print("--------------------------------")
                    print(response.text[:500])  # 只打印前500字符
                    print("--------------------------------")
                    got_response = True
                    successful_proxy = proxy
                    time.sleep(1)
                    break
                else:
                    print(f"代理失败: {proxy}, API返回错误: {json_data.get('msg')}")
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
        json_data = response.json()
        if json_data.get('data') and json_data['data'].get('children'):
            # 按场地名称收集可用时段
            # API 结构: data.children[] = 时间段列表，每个时间段的 children[] = 场地列表
            court_availability = {}  # {"1号场": [["06:00", "07:00"], ...]}

            for time_slot in json_data['data']['children']:
                # 解析时间段 "6:00~7:00" -> ["06:00", "07:00"]
                time_range = time_slot.get('time', '')  # e.g., "6:00~7:00"
                if '~' not in time_range:
                    continue

                start_time, end_time = time_range.split('~')
                start_time = normalize_time(start_time)
                end_time = normalize_time(end_time)

                # 遍历该时段的所有场地
                for court in time_slot.get('children', []):
                    if court.get('active') == "1":
                        court_name = court.get('name', '未知场地')
                        if court_name not in court_availability:
                            court_availability[court_name] = []
                        court_availability[court_name].append([start_time, end_time])

            # 合并连续时间段
            available_slots_infos = {}
            for court_name in court_availability:
                available_slots_infos[court_name] = merge_time_ranges(court_availability[court_name])

            print(f"available_slots_infos: {available_slots_infos}")
            return available_slots_infos
        else:
            print(f"API响应格式异常: {json_data}")
            return {}
    else:
        raise Exception("all proxies failed")


def check_tennis_courts():
    """主要检查逻辑"""
    # 0-8点不巡检
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return

    run_start_time = time.time()
    print_with_timestamp("start to check 上越沙河网球场...")

    # 获取代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    try:
        response = requests.get(url, timeout=10)
        text = response.text.strip()
        proxy_list = [line.strip() for line in text.split("\n") if line.strip()]
        random.shuffle(proxy_list)
        print(f"Loaded {len(proxy_list)} proxies from {url}")
    except Exception as e:
        print(f"获取代理列表失败: {e}")
        proxy_list = []

    # 查询空闲的球场信息 - 未来6天
    up_for_send_data_list = []
    for index in range(0, 6):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        print(f"checking {input_date}...")
        try:
            court_data = get_tennis_court_availability(input_date, proxy_list)

            # 打印网球场可预订场地详细信息
            print_with_timestamp(f"=== {input_date} 可预订场地详细信息 ===")
            if court_data:
                for court_name, free_slots in court_data.items():
                    print_with_timestamp(f"【{court_name}】:")
                    if free_slots:
                        for slot in free_slots:
                            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                            # 处理 24:00 的情况
                            if slot[1] == "24:00":
                                end_time = datetime.datetime.strptime("23:59", "%H:%M") + datetime.timedelta(minutes=1)
                            else:
                                end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                            duration_minutes = (end_time - start_time).total_seconds() / 60
                            print_with_timestamp(f"  - {slot[0]}-{slot[1]} (时长: {int(duration_minutes)}分钟)")
                    else:
                        print_with_timestamp("  - 无可预订时间段")
            else:
                print_with_timestamp("无可预订场地数据")
            print_with_timestamp("=" * 50)

            time.sleep(1)

            for court_name, free_slots in court_data.items():
                if free_slots:
                    filtered_slots = []
                    check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                    is_weekend = check_date.weekday() >= 5

                    for slot in free_slots:
                        # 计算时间段长度（分钟）
                        start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                        # 处理 24:00 的情况
                        if slot[1] == "24:00":
                            end_time = datetime.datetime.strptime("23:59", "%H:%M") + datetime.timedelta(minutes=1)
                        else:
                            end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                        duration_minutes = (end_time - start_time).total_seconds() / 60

                        # 只处理1小时或以上的时间段
                        if duration_minutes < 60:
                            print(f"slot: {slot}, duration_minutes: {duration_minutes}, skip")
                            continue
                        else:
                            print(f"slot: {slot}, duration_minutes: {duration_minutes}, process")

                        # 检查时间段是否与目标时间范围有重叠
                        start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                        if slot[1] == "24:00":
                            end_time = datetime.datetime.strptime("22:00", "%H:%M")  # 22点后的不考虑
                        else:
                            end_time = datetime.datetime.strptime(slot[1], "%H:%M")

                        if is_weekend:
                            # 周末关注16点到22点的场地
                            target_start = datetime.datetime.strptime("16:00", "%H:%M")
                            target_end = datetime.datetime.strptime("22:00", "%H:%M")
                        else:
                            # 工作日关注18点到22点的场地
                            target_start = datetime.datetime.strptime("18:00", "%H:%M")
                            target_end = datetime.datetime.strptime("22:00", "%H:%M")

                        # 判断时间段是否有重叠：max(start1, start2) < min(end1, end2)
                        if max(start_time, target_start) < min(end_time, target_end):
                            filtered_slots.append(slot)

                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"{VENUE_NAME}{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue

    print(f"up_for_send_data_list: {up_for_send_data_list}")

    # 处理通知逻辑
    if up_for_send_data_list:
        sended_msg_list = Variable.get(CACHE_KEY, deserialize_json=True, default_var=[])
        up_for_send_msg_list = []
        up_for_send_sms_list = []

        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']

            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]

            for free_slot in free_slot_list:
                notification = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                if notification not in sended_msg_list:
                    up_for_send_msg_list.append(notification)
                    up_for_send_sms_list.append({
                        "date": date,
                        "court_name": court_name,
                        "start_time": free_slot[0],
                        "end_time": free_slot[1]
                    })

        if up_for_send_msg_list:
            all_in_one_msg = "\n".join(up_for_send_msg_list)

            # 发送邮件
            try:
                email_list = Variable.get("SZW_EMAIL_LIST", default_var=[], deserialize_json=True)
                if email_list:
                    for data in up_for_send_sms_list:
                        date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{data['date']}", "%Y-%m-%d")
                        weekday = date_obj.weekday()
                        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
                        formatted_date = date_obj.strftime("%Y年%m月%d日")

                        result = send_template_email(
                            subject=f"【{data['court_name']}】星期{weekday_str} {data['start_time']} - {data['end_time']}",
                            template_id=33340,
                            template_data={
                                "COURT_NAME": data['court_name'],
                                "FREE_TIME": f"{formatted_date}(星期{weekday_str}) {data['start_time']}-{data['end_time']}"
                            },
                            recipients=email_list,
                            from_email="Zacks <tennis@zacks.com.cn>",
                            reply_to="tennis@zacks.com.cn",
                            trigger_type=1
                        )
                        print(result)
                        time.sleep(1)  # 避免发送过快
                else:
                    print("未配置邮件收件人列表 SZW_EMAIL_LIST")
            except Exception as e:
                print(f"发送邮件异常: {e}")

            # 发送微信消息
            chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
            zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
            chat_names_list = str(chat_names).splitlines()
            chat_names_list.insert(0, "Zacks_深圳湾")
            print(f"chat_names_list: {chat_names_list}")
            for contact_name in chat_names_list:
                zacks_up_for_send_msg_list.append({
                    "room_name": contact_name,
                    "msg": all_in_one_msg
                })
            Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)

            sended_msg_list.extend(up_for_send_msg_list)

        # 更新Variable - 保留最近100条
        description = f"上越沙河网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=CACHE_KEY,
            value=sended_msg_list[-100:],
            description=description,
            serialize_json=True
        )
        print(f"updated {CACHE_KEY} with {len(sended_msg_list)} records")

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time: {execution_time:.2f}s")


# 创建DAG
dag = DAG(
    '上越沙河网球场巡检',
    default_args=default_args,
    description='上越沙河网球场巡检 - Tennis168平台',
    schedule_interval=timedelta(seconds=30),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=['深圳']
)

# 创建任务
check_courts_task = PythonOperator(
    task_id='check_tennis_courts',
    python_callable=check_tennis_courts,
    dag=dag,
)

# 设置任务依赖关系
check_courts_task
