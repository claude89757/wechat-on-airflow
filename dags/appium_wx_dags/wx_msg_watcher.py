#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Appium 自动化微信操作的流程
Author: claude89757
Date: 2025-04-22
"""
import re
import os
import time

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.models import Variable
from airflow.api.common.trigger_dag import trigger_dag
from airflow.models.dagrun import DagRun
from airflow.models import XCom
from airflow import settings


from utils.appium.wx_appium import get_recent_new_msg_by_appium
from utils.appium.wx_appium import send_wx_msg_by_appium
from utils.appium.wx_appium import send_top_n_image_or_video_msg_by_appium
from utils.appium.handler_video import push_file_to_device
from utils.appium.handler_video import clear_mp4_files_in_directory
from utils.appium.handler_video import upload_file_to_device_via_sftp

# 从handlers导入不同任务的handler
from appium_wx_dags.handlers.handler_image_msg import handle_image_messages
from appium_wx_dags.handlers.handler_text_msg import handle_text_messages, save_text_msg_to_db
from appium_wx_dags.handlers.handler_voice_msg import handle_voice_messages


def monitor_chats(**context):
    """监控聊天消息"""
    print(f"[WATCHER] 监控聊天消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    try:
        print(f"INDEX: {task_index}")
        appium_server_list = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)
        print(f"APPIUM_SERVER_LIST: {appium_server_list}")
        appium_server_info = appium_server_list[task_index]
        print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")
    except Exception as e:
        print(f"[WATCHER] 获取Appium服务器信息失败: {e}")
        return []

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']

    # 获取最近的新消息
    recent_new_msg = get_recent_new_msg_by_appium(appium_url, device_name, login_info)
    print(f"[WATCHER] 获取最近的新消息: {recent_new_msg}")

    # 用作保存消息的字典
    include_video_msg, include_image_msg, include_text_msg, include_voice_msg = {}, {}, {}, {}

    for contact_name, messages in recent_new_msg.items():
        # 消息类型状态符
        include_video, include_image, include_text, include_voice = False, False, False, False
        current_contact_video_msg, current_contact_image_msg, current_contact_text_msg, current_contact_voice_msg = [], [], [], []

        # 检查存在的消息类型
        for message in messages:
            if message['msg_type'] == 'video':
                include_video = True
                current_contact_video_msg.append(message)
                # break 
            elif message['msg_type'] == 'image':
                include_image = True
                current_contact_image_msg.append(message)
            elif message['msg_type'] == 'text':
                include_text = True
                current_contact_text_msg.append(message)
            elif message['msg_type'] == 'voice':
                include_voice = True
                current_contact_voice_msg.append(message)
            else:
                pass
        
        # 保存消息
        if include_video:
            include_video_msg[contact_name] = current_contact_video_msg
            
        if include_image:
            include_image_msg[contact_name] = current_contact_image_msg
            
        if include_text:
            include_text_msg[contact_name] = current_contact_text_msg

        if include_voice:
            include_voice_msg[contact_name] = current_contact_voice_msg
    
    # 缓存到XCOM
    need_handle_tasks = []
    if include_video_msg:
        context['ti'].xcom_push(key=f'video_msg_{task_index}', value=include_video_msg)
        need_handle_tasks.append(f'wx_video_handler_{task_index}')

    if include_image_msg:
        context['ti'].xcom_push(key=f'image_msg_{task_index}', value=include_image_msg)
        need_handle_tasks.append(f'wx_image_handler_{task_index}')

    if include_voice_msg:
        context['ti'].xcom_push(key=f'voice_msg_{task_index}', value=include_voice_msg)
        need_handle_tasks.append(f'wx_voice_handler_{task_index}')

    if include_text_msg:
        context['ti'].xcom_push(key=f'text_msg_{task_index}', value=include_text_msg)
        # 如果仅有文本消息，则直接执行文本消息处理
        if not need_handle_tasks:
            need_handle_tasks.append(f'wx_text_handler_{task_index}')
    
    print(f"[WATCHER] 需要处理的任务: {need_handle_tasks}")
    return need_handle_tasks


def handle_video_messages(**context):
    """处理视频消息"""
    print(f"[HANDLE] 处理视频消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    appium_server_info = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)[task_index]
    print(f"[HANDLE] 获取Appium服务器信息: {appium_server_info}")

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']
    
    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key=f'video_msg_{task_index}')
    print(f"[HANDLE] 获取XCOM: {recent_new_msg}")
    
    # 发送消息
    for contact_name, messages in recent_new_msg.items():
        # 通知用户
        send_wx_msg_by_appium(appium_url, device_name, contact_name, ["收到视频，AI分析中...🔄"])

        video_url = ""
        for message in messages:
            if message['msg_type'] == 'video':
                video_url = message['msg'].split(":")[-1].strip()
                break
        print(f"[HANDLE] 视频路径: {video_url}")

        # 创建DAG
        timestamp = int(time.time())
        print(f"[HANDLE] {contact_name} 收到视频消息, 触发AI视频处理DAG")
        dag_run_id = f'ai_tennis_{timestamp}'
        trigger_dag(
            dag_id='tennis_action_score_v4_local_file',
            conf={"video_url": video_url},
            run_id=dag_run_id,
        )

        # 循环等待dag运行完成
        while True:
            dag_run_list = DagRun.find(dag_id="tennis_action_score_v4_local_file", run_id=dag_run_id)
            print(f"dag_run_list: {dag_run_list}")
            if dag_run_list and (dag_run_list[0].state == 'success' or dag_run_list[0].state == 'failed'):
                break
            print(f"[HANDLE] 等待DAG运行完成，当前状态: {dag_run_list[0].state if dag_run_list else 'None'}")
            time.sleep(5)
        
        # 从XCom获取DAG的输出结果
        session = settings.Session()
        try:
            # 使用XCom.get_one获取return_value
            file_infos = XCom.get_one(
                run_id=dag_run_id,
                key="return_value",
                dag_id="tennis_action_score_v4_local_file",
                task_id="process_ai_video",
                session=session
            )
            print(f"[HANDLE] 从XCom获取AI视频处理结果: {file_infos}")
        finally:
            session.close()

        # 推送图片和视频到手机上
        device_ip = login_info['device_ip']
        username = login_info['username']
        password = login_info['password']
        port = login_info['port']
        analysis_image_path = file_infos['analysis_image']
        slow_action_video_path = file_infos['slow_action_video']
        analysis_image_name = analysis_image_path.split('/')[-1]
        slow_action_video_name = slow_action_video_path.split('/')[-1]

        # 先上传到管控手机的主机中
        print(f"[HANDLE] 上传图片到主机: {analysis_image_path}")
        upload_file_to_device_via_sftp(device_ip, username, password, analysis_image_path, analysis_image_path, port=port)
        print("-"*100)
        print(f"[HANDLE] 上传视频到主机: {slow_action_video_path}")
        upload_file_to_device_via_sftp(device_ip, username, password, slow_action_video_path, slow_action_video_path, port=port)
        print("-"*100)

        # 再通过主机的adb命令上传到手机中
        print(f"[HANDLE] 上传图片到手机: {analysis_image_path}")
        result_push_analysis_image = push_file_to_device(device_ip, username, password, device_name, 
                                                         analysis_image_path, f"/storage/emulated/0/Pictures/WeiXin/{analysis_image_name}", port=port)   
        print("-"*100)
        print(f"[HANDLE] 上传视频到手机: {slow_action_video_path}")
        result_push_slow_action_video = push_file_to_device(device_ip, username, password, device_name, 
                                                            slow_action_video_path, f"/storage/emulated/0/DCIM/WeiXin/{slow_action_video_name}", port=port)
        print("-"*100)

        # 发送图片和视频到微信
        print(f"[HANDLE] 发送图片和视频到微信")
        if result_push_analysis_image and result_push_slow_action_video:
            send_top_n_image_or_video_msg_by_appium(appium_url, device_name, contact_name, top_n=2)
        else:
            print(f"[HANDLE] 上传图片或视频到手机失败")

        # 清理视频缓存
        # clear_mp4_files_in_directory(device_ip, username, password, device_name, "/sdcard/DCIM/WeiXin/", port=port)

    return recent_new_msg



# 定义 DAG
with DAG(
    dag_id='appium_wx_msg_watcher',
    default_args={'owner': 'claude89757'},
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=60),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
) as dag:

    # 监控聊天消息
    wx_watcher_0 = BranchPythonOperator(task_id='wx_watcher_0', python_callable=monitor_chats)

    # 处理文本消息
    wx_text_handler_0 = PythonOperator(task_id='wx_text_handler_0', python_callable=handle_text_messages, trigger_rule='none_failed_min_one_success')

    # 处理图片消息
    wx_image_handler_0 = PythonOperator(task_id='wx_image_handler_0', python_callable=handle_image_messages)

    # 处理语音消息
    wx_voice_handler_0 = PythonOperator(task_id='wx_voice_handler_0', python_callable=handle_voice_messages)

    # 处理视频消息
    # wx_video_handler_0 = PythonOperator(task_id='wx_video_handler_0', python_callable=handle_video_messages)

    # 保存文本消息到数据库
    save_text_msg_to_db_0 = PythonOperator(task_id='save_text_msg_to_db_0', python_callable=save_text_msg_to_db)

    

    # 设置依赖关系
    wx_watcher_0 >> wx_text_handler_0 >> save_text_msg_to_db_0

    '''
        目前讨论文本消息和图片消息的处理。

        情况1：无图片消息，无文本消息。处理：无需处理，下游任务跳过
        情况2：有图片消息，无文本消息。处理：处理图片消息，再处理文本消息，处理文本消息时判空结束
        情况3：无图片消息，有文本消息。处理：处理文本消息
        情况4：有图片消息，有文本消息。处理：处理图片消息，再处理文本消息


        当图片消息存在时，先处理图片消息，再处理文本任务，对图片消息一并处理。此时文本消息可能不存在，在handle_text_messages中对任务已经进行判空检查
        由于wx_watcher是分支操作，所以可以只执行上述的任务链，或者执行下面的任务链
    '''
    wx_watcher_0 >> wx_image_handler_0 >> wx_text_handler_0
    
    wx_watcher_0 >> wx_voice_handler_0 >> wx_text_handler_0

    # wx_watcher_0 >> wx_video_handler_0
    # wx_watcher_1 >> wx_video_handler_1
    # wx_watcher_2 >> wx_video_handler_2
