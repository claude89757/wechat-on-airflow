#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import re
import random
import time
from datetime import datetime, timedelta
from threading import Thread

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import save_wx_file


DAG_ID = "video_agent_001"


def download_file_from_windows_server(remote_file_name: str, local_file_name: str):
    """从SMB服务器下载文件
    
    Args:
        remote_file_name: 远程文件名
        local_file_name: 本地文件名
    Returns:
        str: 本地文件路径
    """
    import smbprotocol
    from smbprotocol import smbclient

    # 初始化 SMB 协议
    windows_smb_dir = Variable.get("WINDOWS_SMB_DIR")
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")
    smbprotocol.ClientConfig(username="Administrator", password=windows_server_password)  # 输入正确的用户名和密码
    smbprotocol.set_socket_timeout(30)

    # 设置远程文件共享的 Windows 服务器信息
    remote_file_path = f"{windows_smb_dir}\{remote_file_name}"  # 远程文件路径
    local_file_path = f"{local_file_name}"  # 下载到本地的文件路径

    # 下载文件
    smbclient.get(remote_file_path, local_file_path)
    print("文件已下载：", local_file_path)

    return local_file_path


def process_ai_video(**context):
    """
    处理视频
    """
    # 当前消息
    current_message_data = context.get('dag_run').conf["current_message"]
    # 获取消息数据 
    sender = current_message_data.get('sender', '')  # 发送者ID
    room_id = current_message_data.get('roomid', '')  # 群聊ID
    msg_id = current_message_data.get('id', '')  # 消息ID
    content = current_message_data.get('content', '')  # 消息内容
    source_ip = current_message_data.get('source_ip', '')  # 获取源IP, 用于发送消息
    is_group = current_message_data.get('is_group', False)  # 是否群聊
    extra = current_message_data.get('extra', '')  # 消息extra字段

    # 保存视频到微信客户端侧
    save_dir = f"C:/Users/Administrator/Downloads/{msg_id}.mp4"
    video_file_path = save_wx_file(wcf_ip=source_ip, id=msg_id, save_file_path=save_dir)
    print(f"video_file_path: {video_file_path}")

    # 下载视频到本地
    remote_file_name = video_file_path.split("/")[-1]
    local_file_name = f"{msg_id}.mp4"
    local_file_path = download_file_from_windows_server(remote_file_name=remote_file_name, local_file_name=local_file_name)

    # 处理视频
    pass


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['AI视频处理'],
    description='AI视频处理',
)


process_ai_video_task = PythonOperator(
    task_id='process_ai_video',
    python_callable=process_ai_video,
    provide_context=True,
    dag=dag,
)

process_ai_video_task
