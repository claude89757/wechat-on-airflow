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
import json

from typing import List
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from tennis_dags.utils.tencent_sms import send_sms_for_news
from tennis_dags.utils.tencent_ses import send_template_email


TENNIS_COURT_NAME_LIST = [
    "莲花体育中心",
    "香蜜体育中心",
    "黄木岗网球中心",
    "简上体育综合体",
]

SKIP_COURT_NAME_KEY_WORD = [
    "墙",
    "匹克",
]

def get_tennis_court_infos():
    """从 Airflow Variable 中获取 I 深圳网球场信息"""
    
    # 要发送的消息列表
    up_for_send_msg_list = []
    
    for court_name in TENNIS_COURT_NAME_LIST:
        print(f"Checking {court_name}...")
        print("-"*100)
        data = Variable.get(f"tennis_court_{court_name}", default_var={}, deserialize_json=True)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if not data:
            print(f"{court_name} not found")
            continue
        else:
            print(f"{court_name} found")
            
            # 获取缓存key和已发送消息列表
            cache_key = f"YDMAP_{court_name}_网球场"
            sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
            
            # 访问可用时段 - 适配新的数据结构
            availability_table = data.get('availabilityTable', {})
            
            # 遍历每个日期的可用时段
            for date_with_weekday, venues in availability_table.items():
                # 解析日期和星期 (格式: "09-08(星期一)")
                date_part = date_with_weekday.split('(')[0]  # "09-08"
                weekday_part = date_with_weekday.split('(')[1].replace(')', '')  # "星期一"
                
                # 遍历每个场地的可用时段
                for venue_name, time_slots in venues.items():
                    skip_flag = False
                    for skip_keyword in SKIP_COURT_NAME_KEY_WORD:
                        if skip_keyword in venue_name:
                            print(f"skip {venue_name}")
                            skip_flag = True
                            break
                    if skip_flag:
                        continue
                    
                    if time_slots:  # 如果有可用时段
                        for time_slot in time_slots:
                            # 解析时间段，可能是 "13:00-14:00" 或 ["13:00", "14:00"] 格式
                            if isinstance(time_slot, str):
                                start_time, end_time = time_slot.split('-')
                            elif isinstance(time_slot, list) and len(time_slot) == 2:
                                start_time, end_time = time_slot[0], time_slot[1]
                            else:
                                continue
                            
                            # 过滤时间段 - 只关注黄金时段
                            start_hour = int(start_time.split(':')[0])
                            
                            # 判断是否为周末
                            is_weekend = '六' in weekday_part or '日' in weekday_part
                            
                            should_notify = False
                            if is_weekend:
                                # 周末关注下午和晚上的场地（12-21点）
                                if 12 <= start_hour <= 21:
                                    should_notify = True
                            else:
                                # 工作日关注晚上的场地（18-21点）
                                if 18 <= start_hour <= 21:
                                    should_notify = True
                            
                            if should_notify:
                                # 构建通知消息
                                notification = f"【{court_name}{venue_name}】{weekday_part}({date_part})空场: {start_time}-{end_time}"
                                
                                # 检查是否已发送过此消息
                                if notification not in sended_msg_list:
                                    up_for_send_msg_list.append(notification)
                                    print(f"新空场: {notification}")
                                else:
                                    print(f"已发送过: {notification}")
            
            # 更新已发送消息的缓存
            if up_for_send_msg_list:
                # 将新消息添加到已发送列表
                sended_msg_list.extend(up_for_send_msg_list)
                
                # 更新缓存（只保留最近100条）
                description = f"{court_name}网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                Variable.set(
                    key=cache_key,
                    value=sended_msg_list[-100:],
                    description=description,
                    serialize_json=True
                )
                print(f"更新{cache_key}缓存，共{len(sended_msg_list)}条消息")
            
            # 打印汇总信息（如果存在）
            if 'summary' in data:
                summary = data['summary']
                print(f"总共 {summary.get('totalAvailableSlots', 0)} 小时可用")
    
    # 发送微信消息
    if up_for_send_msg_list:
        print(f"准备发送 {len(up_for_send_msg_list)} 条新消息")
        all_in_one_msg = "\n".join(up_for_send_msg_list)
        
        # 获取微信群配置
        chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
        zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
        
        for contact_name in str(chat_names).splitlines():
            if contact_name.strip():
                zacks_up_for_send_msg_list.append({
                    "room_name": contact_name.strip(),
                    "msg": all_in_one_msg
                })
        
        Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
        print(f"已添加消息到发送队列: {all_in_one_msg}")
    else:
        print("没有新的空场信息需要发送")


# 创建DAG
dag = DAG(
    'I深圳网球场信息监控',
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'start_date': datetime.datetime(2024, 1, 1),
    },
    description='I深圳网球场信息监控',
    schedule_interval=timedelta(seconds=60), 
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=3),
    catchup=False,
    tags=['深圳']
)

# 创建任务
check_courts_task = PythonOperator(
    task_id='get_tennis_court_infos',
    python_callable=get_tennis_court_infos,
    dag=dag,
)

# 设置任务依赖关系
check_courts_task
