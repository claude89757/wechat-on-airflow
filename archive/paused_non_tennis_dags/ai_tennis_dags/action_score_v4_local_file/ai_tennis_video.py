#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
from datetime import datetime, timedelta

# 第三方库导入
import requests
import shutil
from airflow import DAG
from airflow.operators.python import PythonOperator

from tennis_dags.ai_tennis_dags.action_score_v4_local_file.llm_score import get_tennis_action_score


DAG_ID = "tennis_action_score_v4_local_file"

def process_ai_video(**context):
    """
    处理视频
    """
    # 当前消息
    run_id = context.get('dag_run').run_id
    video_url = context.get('dag_run').conf["video_url"]

    # 获取网球动作得分
    output_dir = f"/tmp/tennis_video_output/{run_id}"
    file_infos, score_result_text = get_tennis_action_score(video_url, output_dir)
    print(f"file_infos: {file_infos}")
    print(f"score_result_text: {score_result_text}")

    return file_infos
    
# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
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
