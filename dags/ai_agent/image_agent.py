#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
import time
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from smbclient import register_session, open_file

# 自定义库导入
from utils.wechat_channl import save_wx_image


DAG_ID = "image_agent_001"


def download_file_from_windows_server(remote_file_name: str, local_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """从SMB服务器下载文件
    
    Args:
        remote_file_name: 远程文件名
        local_file_name: 本地文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 本地文件路径
    """
    # 创建临时目录用于存储下载的文件
    temp_dir = "/tmp/image_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    
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

    # 构建远程路径和本地路径
    remote_path = f"//{server_name}/{share_name}/{server_path}/{remote_file_name}"
    local_path = os.path.join(temp_dir, local_file_name)  # 修改为使用临时目录

    # 执行文件下载
    for attempt in range(max_retries):
        try:
            with open_file(remote_path, mode="rb") as remote_file:
                with open(local_path, "wb") as local_file:
                    while True:
                        data = remote_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        local_file.write(data)
            print(f"文件成功下载到: {os.path.abspath(local_path)}")
            
            # 验证文件大小不为0
            if os.path.getsize(local_path) == 0:
                raise Exception("下载的文件大小为0字节")
                
            return local_path  # 下载成功，返回本地文件路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次下载失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件下载失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常

    return local_path  # 返回完整的本地文件路径

def process_ai_image(**context):
    """
    处理图片
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

    # 保存图片到微信客户端侧
    save_dir = f"C:/Users/Administrator/Downloads/{msg_id}.jpg"
    image_file_path = save_wx_image(wcf_ip=source_ip, id=msg_id, extra=extra, save_dir=save_dir, timeout=30)
    print(f"image_file_path: {image_file_path}")

    # 等待3秒
    time.sleep(3)

    # 下载图片到本地临时目录
    remote_file_name = os.path.basename(image_file_path)  # 使用os.path.basename获取文件名
    local_file_name = f"{msg_id}.jpg"
    local_file_path = download_file_from_windows_server(remote_file_name=remote_file_name, local_file_name=local_file_name)
    print(f"图片已下载到本地: {local_file_path}")

    # 处理图片
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
    tags=['图片消息处理'],
    description='图片消息处理',
)


process_ai_image_task = PythonOperator(
    task_id='process_ai_image',
    python_callable=process_ai_image,
    provide_context=True,
    dag=dag,
)

process_ai_image_task
