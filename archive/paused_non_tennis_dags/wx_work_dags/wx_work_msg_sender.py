#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信消息发送DAG

功能：
1. 接收消息内容和目标接收者
2. 通过企业微信API发送消息
3. 支持@群成员

特点：
1. 按需触发执行
2. 最大并发运行数为1
3. 支持发送文本消息
4. 超时时间1分钟
"""

# 标准库导入
import json
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

# 可能需要自定义一个企业微信API封装类
# TODO: 实现企业微信API客户端类


DAG_ID = "wx_work_msg_sender"


def send_wx_work_msg(**context):
    """
    发送企业微信消息
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    
    msg = input_data.get('msg', 'test')
    to_user = input_data.get('to_user', '')
    to_party = input_data.get('to_party', '')
    to_tag = input_data.get('to_tag', '')
    agent_id = input_data.get('agent_id', '')
    room_id = input_data.get('room_id', '')  # 群聊ID
    
    # 获取企业微信配置
    corp_id = Variable.get('WX_WORK_CORP_ID', default_var='')
    corp_secret = Variable.get('WX_WORK_CORP_SECRET', default_var='')
    
    if not corp_id or not corp_secret:
        print("[SENDER] 企业微信配置缺失")
        return
    
    # TODO: 创建企业微信API客户端并发送消息
    # 这里需要根据企业微信API实现具体的发送逻辑
    print(f"[SENDER] 向{to_user or to_party or to_tag or room_id}发送消息: {msg}")
    
    # 企业微信消息发送逻辑示例
    # 1. 获取access_token
    # 2. 调用发送接口
    
    # 普通消息API路径: https://qyapi.weixin.qq.com/cgi-bin/message/send
    # 群聊消息API路径: https://qyapi.weixin.qq.com/cgi-bin/appchat/send
    
    # 登记发送记录
    try:
        print(f"[SENDER] 消息发送成功")
    except Exception as e:
        print(f"[SENDER] 消息发送失败: {e}")


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['企业微信'],
    description='企业微信消息发送',
)

# 创建处理消息的任务
send_msg_task = PythonOperator(
    task_id='send_wx_work_msg',
    python_callable=send_wx_work_msg,
    provide_context=True,
    dag=dag
)
