#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : jdwx_watcher.py
@Software: PyCharm
"""
import time
import datetime
import requests
import random

from typing import List
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from utils.wechat_channl import send_wx_msg
from utils.wx_appium_for_sony import send_wx_msg_by_appium

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

def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """将时间段合并"""
    if not data:
        return data
    
    print(f"merging {data}")
    data_in_minutes = sorted([(int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:]))
                              for start, end in data])

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

def get_free_tennis_court_infos_for_hjd(date: str, proxy_list: list) -> dict:
    """从弘金地获取可预订的场地信息"""
    got_response = False
    response = None
    index_list = list(range(len(proxy_list)))
    random.shuffle(index_list)
    print(index_list)
    for index in index_list:
        params = {
            "gymId": "1479063349546192897",
            "sportsType": "1",
            "reserveDate": date
        }
        headers = {
            "Host": "gateway.gemdalesports.com",
            "referer": "https://servicewechat.com/wxf7ae96551d92f600/34/page-frame.html",
            "xweb_xhr": "1",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/"
                          "98.0.4758.102 Safari/537.36 MicroMessenger/6.8.0(0x16080000)"
                          " NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF XWEB/30626",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty"
        }
        url = "https://gateway.gemdalesports.com/inside-frontend/api/field/fieldReserve"
        proxy = proxy_list[index]
        print(f"trying for {index} time for {proxy}")
        try:
            proxies = {"https": proxy}
            response = requests.get(url, headers=headers, params=params, proxies=proxies, verify=False, timeout=5)
            if response.status_code == 200:
                print(f"success for {proxy}")
                got_response = True
                time.sleep(1)
                break
            else:
                print(f"failed for {proxy}: {response}")
                continue
        except Exception as error:
            print(f"failed for {proxy}: {error}")
            continue

    if got_response and response:
        if response.json()['data'].get('array'):
            available_slots_infos = {}
            for file_info in response.json()['data']['array']:
                available_slots = []
                for slot in file_info['daySource']:
                    if slot['occupy']:
                        time_obj = datetime.datetime.strptime(slot['startTime'], "%H:%M")
                        new_time_obj = time_obj + datetime.timedelta(hours=1)
                        end_time_str = new_time_obj.strftime("%H:%M")
                        available_slots.append([slot['startTime'], end_time_str])
                available_slots_infos[file_info['fieldName']] = merge_time_ranges(available_slots)
            return available_slots_infos
        else:
            raise Exception(response.text)
    else:
        raise Exception("all proxies failed")

def check_tennis_courts():
    """主要检查逻辑"""
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return
    
    run_start_time = time.time()
    print_with_timestamp("start to check...")

    # 获取系统代理
    system_proxy = Variable.get("PROXY_URL", default_var="")
    if system_proxy:
        proxies = {"https": system_proxy}
    else:
        proxies = None

    # 获取代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    response = requests.get(url, proxies=proxies)
    text = response.text.strip()
    proxy_list = [line.strip() for line in text.split("\n")]
    random.shuffle(proxy_list)
    print(f"Loaded {len(proxy_list)} proxies from {url}")

    # 查询空闲的球场信息
    up_for_send_data_list = []
    for index in range(0, 2):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        print(f"checking {input_date}...")
        try:
            court_data = get_free_tennis_court_infos_for_hjd(input_date, proxy_list)
            time.sleep(1)
            
            for court_name, free_slots in court_data.items():
                if free_slots:
                    filtered_slots = []
                    check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                    is_weekend = check_date.weekday() >= 5
                    
                    for slot in free_slots:
                        hour_num = int(slot[0].split(':')[0])
                        if is_weekend:
                            if 15 <= hour_num <= 21:  # 周末关注15点到21点的场地
                                filtered_slots.append(slot)
                        else:
                            if 18 <= hour_num <= 21:  # 工作日仍然只关注18点到21点的场地
                                filtered_slots.append(slot)
                    
                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"威新{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue
    
    print(f"up_for_send_data_list: {up_for_send_data_list}")
    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = "金地威新网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        up_for_send_msg_list = []
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

        # # 获取微信发送配置
        # wcf_ip = Variable.get("WCF_IP", default_var="")
        # for chat_room_id in ["57497883531@chatroom", "38763452635@chatroom", "51998713028@chatroom"]:
        #     print(f"sending to {chat_room_id}")
        #     for msg in up_for_send_msg_list:
        #         send_wx_msg(
        #             wcf_ip=wcf_ip,
        #             message=msg,
        #             receiver=chat_room_id,
        #             aters=''
        #         )
        #         sended_msg_list.append(msg)
        #     time.sleep(30)

        if up_for_send_msg_list:
            # 发送微信消息
            chat_names = Variable.get("MY_OWN_CHAT_NAMES", default_var="")
            for contact_name in str(chat_names).splitlines():
                send_wx_msg_by_appium(contact_name=str(contact_name).strip(), messages=up_for_send_msg_list)
                sended_msg_list.extend(up_for_send_msg_list)
                time.sleep(10)

            time.sleep(30)
            
            # 发送微信消息
            chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
            for contact_name in str(chat_names).splitlines():
                send_wx_msg_by_appium(contact_name=str(contact_name).strip(), messages=up_for_send_msg_list)
                sended_msg_list.extend(up_for_send_msg_list)
                time.sleep(10)

        # 更新Variable
        description = f"深圳金地网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-10:],
            description=description,
            serialize_json=True
        )
        print(f"updated {cache_key} with {sended_msg_list}")
    else:
        pass

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    '深圳金地网球场巡检',
    default_args=default_args,
    description='金地威新网球场巡检',
    schedule_interval='*/1 * * * *',  # 每1分钟执行一次
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=3),
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
