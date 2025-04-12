#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

from ai_tennis_dags.action_score_v2.llm_score import get_tennis_action_score


DAG_ID = "tennis_action_score_v3"

def process_ai_video(**context):
    """
    处理视频
    """
    # 当前消息
    run_id = context.get('dag_run').run_id
    video_url = context.get('dag_run').conf["video_url"]
    video_name = context.get('dag_run').conf["video_name"]

    # 从URL下载视频
    local_file_path = f"/tmp/tennis_video_output/{video_name}"
    response = requests.get(video_url)
    with open(local_file_path, 'wb') as f:
        f.write(response.content)
    video_size = os.path.getsize(local_file_path)
    print(f"视频已下载到本地: {local_file_path}, 视频大小: {video_size} bytes")

    # 获取网球动作得分
    output_dir = f"/tmp/tennis_video_output/{run_id}"
    file_infos = get_tennis_action_score(local_file_path, output_dir)
    print(f"file_infos: {file_infos}")
    
    # 发送分析图片
    print("发送分析图片")
    output_image_path = file_infos["analysis_image"]
    remote_image_name = os.path.basename(output_image_path)
    print(f"remote_image_name: {remote_image_name}")
    print(f"output_image_path: {output_image_path}")

    # 删除临时文件
    try:    
        print(f"删除临时文件: {local_file_path}")
        os.remove(local_file_path)
        for file in file_infos.values():
            print(f"删除临时文件: {file}")
            os.remove(file)
        os.rmdir(output_dir)
        print(f"删除临时文件夹: {output_dir}")
    except Exception as e:
        print(f"删除临时文件失败: {e}")

    return {}

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
    retry_delay=timedelta(seconds=10),
    retries=2,
    dag=dag,
)

process_ai_video_task
