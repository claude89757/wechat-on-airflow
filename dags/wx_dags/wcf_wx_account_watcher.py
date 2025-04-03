#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信账号状态监控DAG

功能：
1. 定期检查微信账号登录状态
2. 更新微信账号信息和联系人列表
3. 缓存账号状态供其他DAG使用

特点：
1. 每15分钟执行一次
2. 最大并发运行数为1
3. 支持多账号并行监控
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import get_wx_contact_list, get_wx_self_info, check_wx_login


DAG_ID = "wx_account_watcher"


def check_wx_account_status(**context):
    """
    检查微信账号状态
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息: {len(wx_account_list)}")

    # 更新微信账号信息
    updated_account_list = []
    for account in wx_account_list:
        print(f"checking account: {account}")
        source_ip = account['source_ip']
        
        try:
            # 获取当前微信账号信息
            new_wx_account_info = get_wx_self_info(source_ip)
        except Exception as e:
            print("="*50)
            print(f"账号异常:{account} {e}")
            print("="*50)
            continue

        if account['name'] != new_wx_account_info['name']:
            print(f"账号更换名称: {account['name']} {new_wx_account_info['name']}, 先删除缓存")
            continue

        # 检查微信登录状态
        new_wx_account_info['source_ip'] = source_ip
        new_wx_account_info['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 保留原始的创建时间，如果存在的话，否则设置为当前时间
        if 'create_time' in account:
            new_wx_account_info['create_time'] = account['create_time']
        else:
            new_wx_account_info['create_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 更新缓存
        updated_account_list.append(new_wx_account_info)

    # 更新缓存
    Variable.set("WX_ACCOUNT_LIST", updated_account_list, serialize_json=True)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=2),
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
