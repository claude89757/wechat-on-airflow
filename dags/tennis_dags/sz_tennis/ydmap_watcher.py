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
    "大沙河国际网球交流中心",
    # "香蜜体育中心",
    # "黄木岗网球中心",
    # "简上体育综合体",
]

SKIP_COURT_NAME_KEY_WORD = [
    "墙",
    "匹克",
]

def get_tennis_court_infos():
    """从 Airflow Variable 中获取 I 深圳网球场信息"""
    
    # 要发送的消息列表（全局收集）
    up_for_send_msg_list = []
    
    for court_name in TENNIS_COURT_NAME_LIST:
        print(f"Checking {court_name}...")
        print("-"*100)
        data = Variable.get(f"tennis_court_{court_name}", default_var={}, deserialize_json=True)
        print(json.dumps(data.get('dates', []), ensure_ascii=False, indent=2))
        if not data:
            print(f"{court_name} not found")
            continue
        else:
            print(f"{court_name} found")
            
            # 获取缓存key和已发送消息列表
            cache_key = f"YDMAP_{court_name}_网球场"
            sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
            
            # 当前场馆的新消息列表
            current_court_new_msgs = []
            
            # 访问可用时段 - 适配新的数据结构
            dates = data.get('dates', [])
            
            # 遍历每个日期的可用时段
            for date_obj in dates:
                # 从日期对象中获取信息
                date_part = date_obj.get('date', '')  # "10-11"
                weekday_part = date_obj.get('weekday', '')  # "星期六"
                no_bookings = date_obj.get('noBookings', [])  # 可预定时段列表
                
                # 遍历每个可预定时段
                for booking in no_bookings:
                    venue_name = booking.get('venueName', '')
                    time_slot = booking.get('timeSlot', '')
                    
                    # 跳过不符合条件的场地名称
                    skip_flag = False
                    for skip_keyword in SKIP_COURT_NAME_KEY_WORD:
                        if skip_keyword in venue_name:
                            print(f"skip {venue_name}")
                            skip_flag = True
                            break
                    if skip_flag:
                        continue
                    
                    if time_slot:  # 如果有时间段
                        # 解析时间段
                        if '-' in time_slot:
                            start_time, end_time = time_slot.split('-')
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
                                current_court_new_msgs.append(notification)
                                up_for_send_msg_list.append(notification)  # 同时添加到全局发送列表
                                print(f"新空场: {notification}")
                            else:
                                print(f"已发送过: {notification}")
            
            # 更新当前场馆的已发送消息缓存
            if current_court_new_msgs:
                # 只将当前场馆的新消息添加到该场馆的已发送列表
                sended_msg_list.extend(current_court_new_msgs)
                
                # 更新缓存（只保留最近100条）
                description = f"{court_name}网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                Variable.set(
                    key=cache_key,
                    value=sended_msg_list[-100:],
                    description=description,
                    serialize_json=True
                )
                print(f"更新{cache_key}缓存，新增{len(current_court_new_msgs)}条消息，总共{len(sended_msg_list)}条消息")
            
            # 打印汇总信息（如果存在）
            if 'summary' in data:
                summary = data['summary']
                print(f"总共 {summary.get('totalNoBookings', 0)} 个可预定时段")
    
    # 发送邮件和微信消息
    if up_for_send_msg_list:
        print(f"准备发送 {len(up_for_send_msg_list)} 条新消息")
        all_in_one_msg = "\n".join(up_for_send_msg_list)
        
        # 发送邮件
        try:
            email_list = Variable.get("YDMAP_EMAIL_LIST", default_var=[], deserialize_json=True)
            if email_list:
                for msg in up_for_send_msg_list:
                    # 解析消息格式: 【场地名】星期X(MM-DD)空场: HH:MM-HH:MM
                    parts = msg.split('】')
                    if len(parts) >= 2:
                        court_name = parts[0].replace('【', '')
                        time_info = parts[1]
                        
                        # 解析星期和日期
                        weekday_match = time_info.split('(')[0] if '(' in time_info else ""
                        date_match = time_info.split('(')[1].split(')')[0] if '(' in time_info and ')' in time_info else ""
                        
                        # 解析时间段
                        time_slot = time_info.split('空场: ')[1] if '空场: ' in time_info else ""
                        
                        # 构建格式化日期
                        current_year = datetime.datetime.now().year
                        if date_match:
                            month, day = date_match.split('-')
                            formatted_date = f"{current_year}年{month}月{day}日"
                        else:
                            formatted_date = ""
                        
                        # 发送邮件
                        result = send_template_email(
                            subject=f"【{court_name}】{weekday_match} {time_slot}",
                            template_id=33340,
                            template_data={
                                "COURT_NAME": court_name,
                                "FREE_TIME": f"{formatted_date}({weekday_match}) {time_slot}"
                            },
                            recipients=email_list,
                            from_email="Zacks <tennis@zacks.com.cn>",
                            reply_to="tennis@zacks.com.cn",
                            trigger_type=1
                        )
                        print(f"邮件发送结果: {result}")
                        time.sleep(1)  # 避免发送过快
            else:
                print("未配置邮件收件人列表 YDMAP_EMAIL_LIST")
        except Exception as e:
            print(f"发送邮件异常: {e}")
            raise Exception(f"发送邮件异常: {e}")
        
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
    schedule_interval=timedelta(seconds=15), 
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
