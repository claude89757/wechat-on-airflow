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

from typing import List, Dict, Any
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from utils.wechat_channl import send_wx_msg
from utils.appium.wx_appium import send_wx_msg_by_appium

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

def timestamp_to_time(timestamp_ms: int) -> str:
    """
    将毫秒时间戳转换为HH:MM格式
    """
    dt = datetime.datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%H:%M")

def get_free_tennis_court_data(venue_id: str, date_str: str, proxy_list: list = None, ok_proxy_list: list = None):
    """
    查询Wilson网球场空闲场地信息
    """
    success_proxy_list = []
    url = "https://jsapp.jussyun.com/jiushi-core/venue/getVenueGround"
    
    # 将日期字符串转换为毫秒时间戳
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    book_time_ms = int(date_obj.timestamp() * 1000)
    
    headers = {
        "Host": "jsapp.jussyun.com",
        "os_type": "wechat_mini",
        # "fullMobile": Variable.get("WILSON_FULLMOBILE", default_var=""),
        "gw_channel": "api",
        "app_id": "0ff444f417de34c1352af3b3ffc30348",
        "js_sign": Variable.get("WILSON_JS_SIGN", default_var=""),
        "os_version": "Mac OS X 15.3.2",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.10(0x13080a10) XWEB/1227",
        "Content-Type": "application/json",
        "xweb_xhr": "1",
        "device_type": "Mac16,11",
        # "token": Variable.get("WILSON_TOKEN", default_var=""),
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wxbd4ec54a9e9ce6dd/131/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    
    payload = {
        "venueId": venue_id,
        "bookTime": str(book_time_ms)
    }
    
    print(f"post body: {payload}")
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
                response = requests.post(url, headers=headers, json=payload, proxies=proxies, verify=False, timeout=2)
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
        response = requests.post(url, headers=headers, json=payload, verify=False)
        if response.status_code == 200:
            res = response.json()
        else:
            raise Exception(str(response.text))

    if res and res.get("rtnCode") == "10000":
        print("请求成功:", res["rtnMessage"])
        
        # 解析返回的数据
        free_time_list = []
        status_list = res["data"]["statusList"]
        
        # 遍历每个时间段
        for time_block in status_list:
            start_time_ms = int(time_block["startTime"])
            end_time_ms = int(time_block["endTime"])
            start_time = timestamp_to_time(start_time_ms)
            end_time = timestamp_to_time(end_time_ms)
            
            # 遍历该时间段内的所有场地
            for court in time_block["blockModel"]:
                ground_name = court["groundName"]
                status = court["status"]
                price = float(court["price"])
                
                # 如果状态为0，表示场地可用
                if status == "0":
                    print(f"{date_str} 场地: {ground_name}, 时间段: {start_time}-{end_time}, 状态: 可用, 价格: {price}")
                    free_time_list.append({
                        "court_name": ground_name,
                        "time_range": [start_time, end_time],
                        "price": price
                    })
        
        return free_time_list, success_proxy_list
    else:
        error_msg = res.get("rtnMessage", "未知错误") if res else "请求失败"
        raise Exception(f"请求失败: {error_msg}")

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
    
    venue_id = "20"  # Wilson网球场的ID
    
    for index in range(0, 8):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        try:
            print(f"checking {input_date}...")
            data_list, ok_proxy_list = get_free_tennis_court_data(venue_id,
                                                                 input_date,
                                                                 # proxy_list=proxy_list,
                                                                 ok_proxy_list=ok_proxy_list)
        except Exception as e:
            print(f"error for {input_date}: {e}")
            continue
        time.sleep(1)
        if data_list:
            # 按照场地分组
            court_groups = {}
            for data in data_list:
                court_name = data['court_name']
                if court_name not in court_groups:
                    court_groups[court_name] = {
                        "time_ranges": [],
                        "price": data["price"]  # 记录价格
                    }
                
                time_range = data['time_range']
                hour_num = int(time_range[0].split(':')[0])
                
                # 根据时间筛选 (这里默认保留所有时间段，可根据需要调整)
                if 7 <= hour_num <= 22:
                    court_groups[court_name]["time_ranges"].append(time_range)
            
            # 处理每个场地的时间段
            for court_name, court_data in court_groups.items():
                free_slot_list = court_data["time_ranges"]
                price = court_data["price"]
                
                if free_slot_list:
                    merged_free_slot_list = merge_time_ranges(free_slot_list)
                    up_for_send_data_list.append({
                        "date": inform_date,
                        "court_name": f"Wilson{court_name}",
                        "free_slot_list": merged_free_slot_list,
                        "price": price
                    })

    # 处理通知逻辑
    if up_for_send_data_list:
        # 获取现有的通知缓存
        cache_key = "Wilson网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        print(f"sended_msg_list: {sended_msg_list}")
       
        # 添加新的通知
        up_for_send_msg_list = []
        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']
            price = data.get('price', 0)
            
            # 获取星期几
            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
            
            for free_slot in free_slot_list:
                # 生成通知字符串
                price_text = f"¥{price}" if price > 0 else ""
                msg = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]} {price_text}"
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
            appium_url = Variable.get("ZACKS_APPIUM_URL")
            device_name = Variable.get("ZACKS_DEVICE_NAME")
            for contact_name in str(chat_names).splitlines():
                send_wx_msg_by_appium(appium_url, device_name, contact_name, up_for_send_msg_list)
                sended_msg_list.extend(up_for_send_msg_list)
                time.sleep(10)

        # 更新缓存信息
        description = f"Wilson网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
    '上海Wilson网球场巡检',
    default_args=default_args,
    description='监控Wilson网球场地可用情况',
    schedule_interval='*/5 * * * *',  # 每5分钟执行一次
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

