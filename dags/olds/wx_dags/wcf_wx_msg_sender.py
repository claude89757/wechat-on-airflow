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
import uuid
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# 自定义库导入
from utils.wechat_channl import send_wx_msg
from wx_dags.common.wx_tools import WX_MSG_TYPES
from wx_dags.common.wx_tools import update_wx_user_info
from wx_dags.common.wx_tools import get_contact_name
from wx_dags.common.mysql_tools import save_data_to_db


DAG_ID = "wx_msg_sender"


def send_msg(**context):
    """
    发送微信消息
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    up_for_send_msg = input_data['content']
    source_ip = input_data['source_ip']
    room_id = input_data['room_id']
    aters = input_data.get('aters', '')

    # 发送文本消息
    send_wx_msg(wcf_ip=source_ip, message=up_for_send_msg, receiver=room_id, aters=aters)
    

def save_msg(**context):
    """
    保存消息到数据库
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    print(f"保存消息到数据库, message_data: {message_data}")
    
    save_msg = {}
    # 提取消息信息
    save_msg['room_id'] = message_data.get('room_id', '')
    save_msg['sender_id'] = message_data.get('sender', '')
    save_msg['msg_id'] = message_data.get('id') or str(uuid.uuid4())
    save_msg['msg_type'] = message_data.get('msg_type', 0)
    save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], '未知')
    save_msg['content'] = message_data.get('content', '')
    save_msg['is_self'] =  message_data.get('is_self', True)  # 是否群聊
    save_msg['is_group'] = message_data.get('is_group', 0)  # 是否群聊
    save_msg['msg_timestamp'] = int(datetime.now().timestamp())
    save_msg['msg_datetime'] = datetime.now()
    save_msg['source_ip'] = message_data.get('source_ip', '')
    
    # 获取微信账号信息
    wx_account_info = update_wx_user_info(save_msg['source_ip'])
    save_msg['wx_user_name'] = wx_account_info.get('name', '')
    save_msg['wx_user_id'] = wx_account_info.get('wxid', '')

    # 获取房间和发送者信息
    save_msg['room_name'] = get_contact_name(save_msg['source_ip'], save_msg['room_id'], save_msg['wx_user_name'])
    if save_msg['is_self']:
        save_msg['sender_name'] = save_msg['wx_user_name']
    else:
        save_msg['sender_name'] = get_contact_name(save_msg['source_ip'], save_msg['sender_id'], save_msg['wx_user_name'])
    
    # 保存消息到数据库
    save_data_to_db(save_msg)

    try:
        # 账号的消息计时器+1
        msg_count = Variable.get(f"{save_msg['wx_user_name']}_msg_count", default_var=0, deserialize_json=True)
        Variable.set(f"{save_msg['wx_user_name']}_msg_count", msg_count+1, serialize_json=True)
    except Exception as error:
        # 不影响主流程
        print(f"[WATCHER] 更新消息计时器失败: {error}")


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['个人微信'],
    description='个人微信消息发送',
)

# 创建处理消息的任务
send_msg_task = PythonOperator(
    task_id='send_msg',
    python_callable=send_msg,
    provide_context=True,
    dag=dag
)

save_msg_to_db_task = PythonOperator(
    task_id='save_msg_to_db',
    python_callable=save_msg,
    provide_context=True,
    retries=5,
    retry_delay=timedelta(seconds=1),
    dag=dag
)

send_msg_task >> save_msg_to_db_task
