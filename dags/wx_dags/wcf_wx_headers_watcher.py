#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头像数据查询
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import get_wx_contact_list, get_wx_self_info, check_wx_login


DAG_ID = "wx_headers_watcher"


def check_wx_account_status(**context):
    """
    头像查询
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息: {len(wx_account_list)}")

    # TODO(claude89757): 获取头像数据

    
    print(f"当前已缓存的用户信息: {wx_account_list}")

    # 更新缓存（）
    # Variable.set("WX_ACCOUNT_LIST", updated_account_list, serialize_json=True)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=15),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=['个人微信'],
    description='个人微信账号监控',
)

# 创建处理消息的任务
check_wx_account_status_task = PythonOperator(
    task_id='check_wx_account_status',
    python_callable=check_wx_account_status,
    provide_context=True,
    dag=dag
)
