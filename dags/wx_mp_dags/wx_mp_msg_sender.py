#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息发送DAG

功能：
1. 接收消息内容和目标接收者
2. 通过WCF API发送消息
3. 支持@群成员

特点：
1. 按需触发执行
2. 最大并发运行数为1
3. 支持发送文本消息
4. 超时时间1分钟
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

# 自定义库导入
from dags.utils.wechat_mp_channl import WeChatMPBot


DAG_ID = "wx_mp_msg_sender"


def send_wx_mp_msg(**context):
    """
    发送微信消息
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    
    msg = input_data.get('msg', 'test')
    to_user = input_data.get('to_user', 'oVSlU7PqMNpp7BqnxkhCWZtqrA5U')

    app_id = Variable.get('WX_MP_APP_ID')
    app_secret = Variable.get('WX_MP_SECRET')

    # 创建微信机器人实例
    wx_mp_bot = WeChatMPBot(appid=app_id, appsecret=app_secret)
    
    # 获取access_token
    wx_mp_bot.get_access_token()

    # 发送文本消息
    wx_mp_bot.send_text_message(to_user, msg)



# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['微信公众号'],
    description='微信公众号消息发送',
)

# 创建处理消息的任务
send_msg_task = PythonOperator(
    task_id='send_wx_mp_msg',
    python_callable=send_wx_mp_msg,
    provide_context=True,
    dag=dag
)
