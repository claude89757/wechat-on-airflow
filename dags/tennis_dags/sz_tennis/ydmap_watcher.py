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

from tennis_dags.utils.tencent_sms import send_sms_for_news
from tennis_dags.utils.tencent_ses import send_template_email


TENNIS_COURT_NAME_LIST = [
    "莲花体育中心",
    "香蜜体育中心",
    "黄木岗体育中心",
]

def get_tennis_court_infos():
    """从 Airflow Variable 中获取 I 深圳网球场信息"""

    for court_name in TENNIS_COURT_NAME_LIST:
        print(f"Checking {court_name}...")
        print("-"*100)
        data = Variable.get(f"tennis_court_{court_name}", default_var={}, deserialize_json=True)
        if not data:
            print(f"{court_name} not found")
            continue
        else:
            print(f"{court_name} found")
            # 访问预订信息
            booking_table = data['bookingTable']
            for booking in booking_table:
                print(f"{booking['venueName']}: {booking['timeSlot']} - {booking['statusText']}")

            # 访问可用时段
            availability_table = data['availabilityTable']
            for venue in availability_table:
                if venue['hasAvailability']:
                    print(f"{venue['venueName']}: 可用 {venue['availableHourCount']} 小时")
                    print(f"  时段: {', '.join(venue['availableSlots'])}")

            # 获取汇总信息
            summary = data['summary']
            print(f"总共 {summary['totalAvailableSlots']} 小时可用")


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
