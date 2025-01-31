#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from smbclient import register_session, open_file

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
    # 从Airflow变量获取配置
    windows_smb_dir = Variable.get("WINDOWS_SMB_DIR")
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")

    # 解析UNC路径
    unc_parts = windows_smb_dir.strip("\\").split("\\")
    if len(unc_parts) < 3:
        raise ValueError(f"无效的SMB路径格式: {windows_smb_dir}。正确格式示例: \\\\server\\share\\path")

    # 将服务器名称中的下划线替换为点号
    server_name = unc_parts[0].replace("_", ".")    # 10.1.12.10
    share_name = unc_parts[1]                       # Users
    server_path = "/".join(unc_parts[2:])          # Administrator/Downloads
    print(f"server_name: {server_name}, share_name: {share_name}, server_path: {server_path}")

    # 注册SMB会话
    try:
        register_session(
            server=server_name,
            username="Administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径（关键修改点）
    remote_path = f"//{server_name}/{share_name}/{server_path}/{remote_file_name}"
    local_path = os.path.abspath(local_file_name)

    # 执行文件下载
    try:
        with open_file(remote_path, mode="rb") as remote_file:
            with open(local_path, "wb") as local_file:
                while True:
                    data = remote_file.read(8192)  # 分块读取大文件
                    if not data:
                        break
                    local_file.write(data)
        print(f"文件成功下载到: {os.path.abspath(local_path)}")
    except Exception as e:
        print(f"文件下载失败: {str(e)}")
        raise

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
