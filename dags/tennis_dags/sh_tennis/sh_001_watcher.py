#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/7/13 23:31
@Author  : claude89757
@File    : tennis_court_watcher.py
@Software: PyCharm
"""
import os
import json
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
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def print_with_timestamp(*args, **kwargs):
    """
    打印函数带上当前时间戳
    """
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """
    将时间段合并
    """
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

def get_free_tennis_court_data(field_type: str, order_date: str, proxy_list: list = None, ok_proxy_list: list = None):
    """
    查询空闲场地信息
    """
    success_proxy_list = []
    url = "https://api.go-sports.cn/home/timesListNew"
    headers = {
        "Host": "api.go-sports.cn",
        "ua": Variable.get("SH_001_KEY"),
        "xweb_xhr": "1",
        "User-Agent": "Chrome",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wxa43e880705719304/81/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    data = {
        "venue_id": 1,
        "field_type": field_type,
        "order_date": order_date,
    }
    print(f"post body: {data}")
    res = None
    if proxy_list or ok_proxy_list:
        all_proxy_list = []
        if ok_proxy_list:
            all_proxy_list.extend(ok_proxy_list)
        if proxy_list:
            all_proxy_list.extend(proxy_list)

        try_time = 1
        for proxy in all_proxy_list:
            print(f"trying for {try_time} time for {proxy}")
            try_time += 1
            try:
                proxies = {"https": proxy}
                response = requests.post(url, headers=headers, data=data, proxies=proxies, verify=False, timeout=2)
                if response.status_code == 200:
                    print(f"success for {proxy}")
                    success_proxy_list.append(proxy)
                    res = response.json()
                    print(f"response: {response.text}")
                    break
                else:
                    print(f"failed for {proxy}")
                    time.sleep(1)
                    continue
            except Exception:  # pylint: disable=broad-except
                print(f"failed for {proxy}")
                continue

    else:
        print("no using proxy...")
        response = requests.post(url, headers=headers, data=data, verify=False)
        if response.status_code == 200:
            res = response.json()
        else:
            raise Exception(str(response.text))

    if res:
        print("请求成功:", res["msg"])
        times_list = res["data"]["times_list"]
        free_time_list = []
        for time_slot in times_list:
            print(f"{order_date} 时间段: {time_slot['name']}, 状态: {time_slot['status']}")
            if time_slot['status'] == 1:
                free_time_list.append(time_slot)
        return free_time_list, success_proxy_list
    else:
        raise Exception("未知异常")

def check_tennis_courts():
    """
    主要检查逻辑
    """
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
    ok_proxy_list = []
    
    for filed_type in ['in', 'out']:
        for index in range(0, 7):
            input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y%m%d')
            inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
            data_list, ok_proxy_list = get_free_tennis_court_data(filed_type,
                                                                 input_date,
                                                                 proxy_list=proxy_list,
                                                                 ok_proxy_list=ok_proxy_list)
            time.sleep(1)
            if data_list:
                if filed_type == 'in':
                    free_slot_list = []
                    for data in data_list:
                        hour_num = int(str(data['name']).split(':')[0])
                        start_time = str(data['name']).split('-')[0]
                        end_time = str(data['name']).split('-')[1]
                        if 9 <= hour_num <= 21:
                            free_slot_list.append([start_time, end_time])
                    if free_slot_list:
                        merged_free_slot_list = merge_time_ranges(free_slot_list)
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": "卢湾室内",
                            "free_slot_list": merged_free_slot_list
                        })
                else:
                    free_slot_list = []
                    for data in data_list:
                        hour_num = int(str(data['name']).split(':')[0])
                        start_time = str(data['name']).split('-')[0]
                        end_time = str(data['name']).split('-')[1]
                        if 18 <= hour_num <= 21:
                            free_slot_list.append([start_time, end_time])
                    if free_slot_list:
                        merged_free_slot_list = merge_time_ranges(free_slot_list)
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": "卢湾室外",
                            "free_slot_list": merged_free_slot_list
                        })
                        break

    # 处理通知逻辑
    if up_for_send_data_list:
        # 获取现有的通知缓存
        cache_key = "上海卢湾网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        print(f"sended_msg_list: {sended_msg_list}")
       
        # 添加新的通知
        up_for_send_msg_list = []
        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']
            
            # 获取星期几
            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
            
            for free_slot in free_slot_list:
                # 生成通知字符串
                msg = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                if msg not in sended_msg_list:
                    up_for_send_msg_list.append(msg)
                else:
                    print(f"msg {msg} already sended")

        print(f"up_for_send_msg_list: {up_for_send_msg_list}")

        # # 发送微信消息
        # wcf_ip = Variable.get("WCF_IP")
        # for msg in up_for_send_msg_list:
        #     send_wx_msg(
        #         wcf_ip=wcf_ip,
        #         message=msg,
        #         receiver="56351399535@chatroom",
        #         aters=''
        #     )
        #     sended_msg_list.append(msg)

        if up_for_send_msg_list:
            chat_names = Variable.get("SH_TENNIS_CHATROOMS", default_var="")
            for contact_name in str(chat_names).splitlines():
                send_wx_msg_by_appium(contact_name=str(contact_name).strip(), messages=up_for_send_msg_list)
                sended_msg_list.extend(up_for_send_msg_list)
                time.sleep(10)

        # 更新缓存信息
        description = f"上海卢湾网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-100:],
            description=description,
            serialize_json=True
        )

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    '上海卢湾网球场巡检',
    default_args=default_args,
    description='监控网球场地可用情况',
    schedule_interval='*/5 * * * *',  # 每2分钟执行一次
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=3),
    catchup=False,
    tags=['上海']
)

# 创建任务
check_courts_task = PythonOperator(
    task_id='check_tennis_courts',
    python_callable=check_tennis_courts,
    dag=dag,
)
# 设置任务依赖关系
check_courts_task

