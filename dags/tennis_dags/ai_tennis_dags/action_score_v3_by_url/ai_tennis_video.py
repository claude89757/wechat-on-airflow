#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

from tennis_dags.ai_tennis_dags.action_score_v3_by_url.llm_score import get_tennis_action_score
from tennis_dags.ai_tennis_dags.action_score_v3_by_url.tencent_cos import TencentCosClient

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
    file_infos, score_result_text = get_tennis_action_score(local_file_path, output_dir)
    print(f"file_infos: {file_infos}")
    print(f"score_result_text: {score_result_text}")
    
    # 上传视频到腾讯云COS, 并返回视频的URL
    # file_infos: {'preparation_frame': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/prep_frame.jpg', 
    # 'contact_frame': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/contact_frame.jpg', 
    # 'follow_frame': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/follow_frame.jpg', 
    # one_action_video': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/tennis_action.mp4',
    # 'slow_action_video': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/tennis_action_slow.mp4',
    #  'analysis_image': '/tmp/tennis_video_output/416_1742834282.mp4_2025-04-13_03:51:51/tennis_analysis_416_1742834282.jpg'}
    
    cos_client = TencentCosClient()
    # 使用run_id作为COS文件夹名称
    file_urls = {}
    for file_type, local_file_path in file_infos.items():
        if os.path.exists(local_file_path):
            # 获取文件名
            file_name = os.path.basename(local_file_path)
            # 使用run_id作为文件夹名称
            cos_path = f"{run_id}/{file_name}"
            # 上传文件到COS
            upload_result = cos_client.upload_file(local_file_path, cos_path)

            # 获取文件的URL，有效期设为7天
            file_url = cos_client.get_object_url(cos_path, expires=14*24*3600)
            file_urls[file_type] = file_url

            print(f"文件 {file_type} 已上传至COS，URL: {file_url}\n{upload_result}")
    print(f"文件URLs已保存: {file_urls}")


    # 将结果保存到XCom
    context['ti'].xcom_push(key='output_video_url', value=file_urls["filtered_output_video"])
    context['ti'].xcom_push(key='output_image_url', value=file_urls["analysis_image"])
    context['ti'].xcom_push(key='output_text', value=score_result_text)

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

    return {
        "output_video_url": file_urls["filtered_output_video"],
        "output_image_url": file_urls["analysis_image"],
        "output_text": score_result_text
    }

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
