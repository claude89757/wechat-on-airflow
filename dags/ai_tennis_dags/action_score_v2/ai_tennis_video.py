#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from openai import OpenAI
import base64

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from smbclient import register_session, open_file

# 自定义库导入
from utils.wechat_channl import (
    save_wx_file,
    send_wx_msg, 
    send_wx_image,
    save_wx_image
)

from ai_tennis_dags.action_score_v2.llm_score import get_tennis_action_score
from ai_tennis_dags.common.wcf_tools import (
    download_file_from_windows_server,
    upload_file_to_windows_server
)

DAG_ID = "tennis_action_score_v2"
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
    download_video_file = f"C:/Users/Administrator/Downloads/{msg_id}.mp4"
    result = save_wx_file(wcf_ip=source_ip, id=msg_id, save_file_path=download_video_file)
    print(f"result: {result}")

    # 等待3秒
    time.sleep(3)

    # 下载视频到本地临时目录
    local_file_name = f"{msg_id}.mp4"
    local_file_path = download_file_from_windows_server(server_ip=source_ip, remote_file_name=download_video_file, local_file_name=local_file_name)
    print(f"视频已下载到本地: {local_file_path}")

    # 处理视频
    start_time = time.time()
    start_msg = f"Zacks 正在分析视频，请稍后（3分钟~5分钟）..."
    send_wx_msg(wcf_ip=source_ip, message=start_msg, receiver=room_id)

    # 获取网球动作得分
    output_dir = f"/tmp/tennis_video_output"
    file_infos = get_tennis_action_score(local_file_path, output_dir)
    print(f"file_infos: {file_infos}")
    output_image_path = file_infos["analysis_image"]

    end_time = time.time()
    end_msg = f"视频分析完成，耗时: {end_time - start_time:.2f}秒"
    send_wx_msg(wcf_ip=source_ip, message=end_msg, receiver=room_id)

    # 发送图片到微信: 先把图片上传到Windows服务器，然后从Windows服务器转发到微信
    remote_image_name = os.path.basename(output_image_path)
    print(f"remote_image_name: {remote_image_name}")
    print(f"output_image_path: {output_image_path}")
    windows_image_path = upload_file_to_windows_server(
        server_ip=source_ip,
        local_file_path=output_image_path,
        remote_file_name=remote_image_name
    )
    print(f"windows_image_path: {windows_image_path}")
    send_wx_image(wcf_ip=source_ip, image_path=windows_image_path, receiver=room_id)

    # 删除临时文件
    try:    
        os.remove(local_file_path)
        os.rmdir(output_dir)
    except Exception as e:
        print(f"删除临时文件失败: {e}")

# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=1,
    catchup=False,
    tags=['AI网球'],
    description='网球关键动作识别',
)


process_ai_video_task = PythonOperator(
    task_id='process_ai_video',
    python_callable=process_ai_video,
    provide_context=True,
    dag=dag,
)

process_ai_video_task
