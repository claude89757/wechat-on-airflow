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
from smbclient import register_session, open_file

# 自定义库导入
from utils.wechat_channl import send_wx_msg, send_wx_image


DAG_ID = "wx_image_sender"


def upload_file_to_windows_server(server_ip: str, local_file_path: str, remote_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """上传文件到SMB服务器
    
    Args:
        server_ip: Windows服务器IP
        local_file_path: 本地文件路径
        remote_file_name: 远程文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 远程文件的完整路径
    """
    # 从Airflow变量获取配置
    windows_server_password = Variable.get("AI_TENNIS_WINDOWS_SERVER_PASSWORD")

    # 注册SMB会话
    try:
        register_session(
            server=server_ip,
            username="administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径
    remote_path = f"//{server_ip}/Users/Administrator/Downloads/{remote_file_name}"

    # 执行文件上传
    for attempt in range(max_retries):
        try:
            with open(local_file_path, "rb") as local_file:
                with open_file(remote_path, mode="wb") as remote_file:
                    while True:
                        data = local_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        remote_file.write(data)
            
            print(f"文件成功上传到: {remote_path}")
            return f"C:/Users/Administrator/Downloads/{remote_file_name}"  # 返回Windows格式的路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次上传失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件上传失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常


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
    
    # 检查本地文件是否存在
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"本地文件不存在: {image_path}")
        
    try:
        # 1. 上传图片到Windows服务器
        # remote_image_name = os.path.basename(image_path)
        # windows_image_path = upload_file_to_windows_server(
        #     server_ip=source_ip,
        #     local_file_path=image_path,
        #     remote_file_name=remote_image_name
        # )
        # print(f"图片已上传到Windows服务器: {windows_image_path}")
        
        # 2. 发送图片到微信
        send_wx_image(wcf_ip=source_ip, image_path=windows_image_path, receiver=room_id)
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

send_image_task  # 设置任务依赖