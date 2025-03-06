#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
微信图片发送DAG

功能：
1. 支持从本地上传图片到Windows服务器
2. 支持从Windows服务器发送图片到微信
3. 支持发送图片到个人或群聊
"""

# 标准库导入
import os
import time
from datetime import datetime, timedelta

# 第三方库导入
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from dags.utils.wechat_channl import send_wx_msg, send_wx_image


DAG_ID = "wx_image_sender"


def send_image(**context):
    """
    发送图片到微信
    xxxx.png
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    image_path = input_data['image_path']  # 本地图片路径
    source_ip = input_data['source_ip']    # 微信客户端所在Windows服务器IP
    room_id = input_data['room_id']        # 接收者ID（个人或群ID）
    
        
    try:
        # 发送图片到微信
        send_wx_image(wcf_ip=source_ip, image_path=image_path, receiver=room_id)
        print(f"图片已发送到微信接收者: {room_id}")
        
    except Exception as e:
        error_msg = f"发送图片失败: {str(e)}"
        print(error_msg)
        # 发送错误通知
        try:
            send_wx_msg(wcf_ip=source_ip, message=error_msg, receiver=room_id)
        except:
            pass  # 忽略发送错误消息时的异常
        raise  # 重新抛出原始异常


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 1,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,  # 由外部触发
    max_active_runs=10,
    catchup=False,
    tags=['个人微信'],
    description='发送图片到微信',
)


# 创建任务
send_image_task = PythonOperator(
    task_id='send_image',
    python_callable=send_image,
    provide_context=True,
    dag=dag,
)

send_image_task
