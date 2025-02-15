#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : szw_watcher.py
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
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def find_available_slots(booked_slots: List[List[str]], time_range: dict) -> List[List[str]]:
    """查找可用的时间段"""
    if not booked_slots:
        return [[time_range['start_time'], time_range['end_time']]]
    
    # 将时间转换为分钟
    booked_in_minutes = sorted([(int(start[:2]) * 60 + int(start[3:]), 
                                int(end[:2]) * 60 + int(end[3:]))
                               for start, end in booked_slots])
    
    start_minutes = int(time_range['start_time'][:2]) * 60 + int(time_range['start_time'][3:])
    end_minutes = int(time_range['end_time'][:2]) * 60 + int(time_range['end_time'][3:])
    
    available = []
    current = start_minutes
    
    for booked_start, booked_end in booked_in_minutes:
        if current < booked_start:
            available.append([
                f"{current // 60:02d}:{current % 60:02d}",
                f"{booked_start // 60:02d}:{booked_start % 60:02d}"
            ])
        current = max(current, booked_end)
    
    if current < end_minutes:
        available.append([
            f"{current // 60:02d}:{current % 60:02d}",
            f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        ])
    
    return available

def get_free_tennis_court_infos_for_szw(date: str, proxy_list: list, time_range: dict) -> dict:
    """
    获取可预订的场地信息
    Args:
        date: 日期，格式为YYYY-MM-DD
        proxy_list: 代理列表
        time_range: 时间范围，格式为{"start_time": "HH:MM", "end_time": "HH:MM"}
    Returns:
        dict: 场地信息，格式为{场地名: [[开始时间, 结束时间], ...]}
    """
    szw_cookie = Variable.get("SZW_COOKIE", default_var="")
    got_response = False
    response = None
    index_list = list(range(len(proxy_list)))
    # 打乱列表的顺序
    random.shuffle(index_list)
    print(index_list)
    
    for index in index_list:
        data = {
            'VenueTypeID': 'd3bc78ba-0d9c-4996-9ac5-5a792324decb',
            'VenueTypeDisplayName': '',
            'billDay': date,
        }
        headers = {
            "Host": "program.springcocoon.com",
            "sec-ch-ua": "\" Not A;Brand\";v=\"99\", \"Chromium\";v=\"98\"",
            "sec-ch-ua-mobile": "?0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua-platform": "\"macOS\"",
            "Origin": "https://program.springcocoon.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": ("https://program.springcocoon.com/szbay/AppVenue/VenueBill/VenueBill"
                        "?VenueTypeID=d3bc78ba-0d9c-4996-9ac5-5a792324decb"),
            "Accept-Language": "zh-CN,zh",
            "Cookie": szw_cookie
        }
        url = 'https://program.springcocoon.com/szbay/api/services/app/VenueBill/GetVenueBillDataAsync'
        
        proxy = proxy_list[index]
        print(f"trying for {index} time for {proxy}")
        
        try:
            proxies = {"https": proxy}
            response = requests.post(url, headers=headers, data=data, proxies=proxies, verify=False, timeout=5)
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
        if response.status_code == 200:
            if len(response.json()['result']) == 1:
                # 场地名称转换
                venue_name_infos = {}
                for venue in response.json()['result'][0]['listVenue']:
                    venue_name_infos[venue['id']] = venue['displayName']
                print(venue_name_infos)

                booked_court_infos = {}
                if response.json()['result'][0].get("listWebVenueStatus") \
                        and response.json()['result'][0]['listWebVenueStatus']:
                    for venue_info in response.json()['result'][0]['listWebVenueStatus']:
                        if str(venue_info.get('bookLinker')) == '可定' or str(venue_info.get('bookLinker')) == '可订':
                            pass
                        else:
                            start_time = str(venue_info['timeStartEndName']).split('-')[0].replace(":30", ":00")
                            end_time = str(venue_info['timeStartEndName']).split('-')[1].replace(":30", ":00")
                            venue_name = venue_name_infos[venue_info['venueID']]
                            if booked_court_infos.get(venue_name):
                                booked_court_infos[venue_name].append([start_time, end_time])
                            else:
                                booked_court_infos[venue_name] = [[start_time, end_time]]
                else:
                    if response.json()['result'][0].get("listWeixinVenueStatus") and \
                            response.json()['result'][0]['listWeixinVenueStatus']:
                        for venue_info in response.json()['result'][0]['listWeixinVenueStatus']:
                            if venue_info['status'] == 20:
                                start_time = str(venue_info['timeStartEndName']).split('-')[0].replace(":30", ":00")
                                end_time = str(venue_info['timeStartEndName']).split('-')[1].replace(":30", ":00")
                                venue_name = venue_name_infos[venue_info['venueID']]
                                if booked_court_infos.get(venue_name):
                                    booked_court_infos[venue_name].append([start_time, end_time])
                                else:
                                    booked_court_infos[venue_name] = [[start_time, end_time]]
                            else:
                                pass
                    else:
                        pass

                available_slots_infos = {}
                for venue_id, booked_slots in booked_court_infos.items():
                    available_slots = find_available_slots(booked_slots, time_range)
                    available_slots_infos[venue_id] = available_slots
                return available_slots_infos
            else:
                raise Exception(response.text)
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

    # 设置查询时间范围
    time_range = {
        "start_time": "08:00",
        "end_time": "22:00"
    }

    # 查询空闲的球场信息
    up_for_send_data_list = []
    
    for index in range(0, 2):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        
        try:
            court_data = get_free_tennis_court_infos_for_szw(input_date, proxy_list, time_range)
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
                            "court_name": f"深圳湾{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue

    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = "深圳湾网球场"
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

        # 获取微信发送配置
        wcf_ip = Variable.get("WCF_IP", default_var="")
        for msg in up_for_send_msg_list:
            send_wx_msg(
                wcf_ip=wcf_ip,
                message=msg,
                receiver="38763452635@chatroom",
                aters=''
            )
            sended_msg_list.append(msg)

        # 更新Variable
        description = f"深圳湾网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-10:],
            description=description,
            serialize_json=True
        )
        print(f"updated {cache_key} with {sended_msg_list}")

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    '深圳湾网球场巡检',
    default_args=default_args,
    description='深圳湾网球场巡检',
    schedule_interval='*/5 * * * *',  # 每5分钟执行一次
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
