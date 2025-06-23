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
from appium_wx_dags.handlers.handler_text_msg import handle_text_messages
from appium_wx_dags.handlers.handler_voice_msg import handle_voice_messages

# 导入saver
from appium_wx_dags.savers.saver_text_msg import save_text_msg_to_db
from appium_wx_dags.savers.saver_image_msg import save_image_msg_to_db, save_image_to_cos

WX_CONFIGS={
    "wxid1":{
            "appium_url": "http://42.193.193.179:6079",
            "device_name": "ZY22G2V44N",
            "dify_api_key": "app-JIuoukdsG1rFODEe0YoRWd30",
            "dify_api_url": "http://dify.lucyai.sale/v1",
            "login_info": {
                "device_ip": "42.193.193.179",
                "password": "18100273137@123",
                "port": 10005,
                "username": "a18100273137"
            },
            "wx_name": "Dr.Liu【ai客户猎手】",
            "dag_id": "wx_watcher_1"
        },
    "wxid2":{
            "appium_url": "http://42.193.193.179:6025",
            "device_name": "0864cf720705",
            "dify_api_key": "app-JIuoukdsG1rFODEe0YoRWd30",
            "dify_api_url": "http://dify.lucyai.sale/v1",
            "login_info": {
                "device_ip": "42.193.193.179",
                "password": "lucyai",
                "port": 8667,
                "username": "lucy"
            },
            "wx_name": "LucyAI",
            "dag_id": "wx_watcher_2"
        }       
}


def monitor_chats(**context):
    """监控聊天消息"""
    print(f"[WATCHER] 监控聊天消息")
    try:
        # 从 op_kwargs 传入的参数会被放入 context 中
        appium_server_info = context['wx_config']
        print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")
    except KeyError:
        print(f"[WATCHER] 获取Appium服务器信息失败: 未在 context 中找到 'wx_config'")
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
        context['ti'].xcom_push(key=f'video_msg', value=include_video_msg)
        need_handle_tasks.append(f'wx_video_handler')

    if include_image_msg:
        context['ti'].xcom_push(key=f'image_msg', value=include_image_msg)
        need_handle_tasks.append(f'wx_image_handler')

    if include_voice_msg:
        context['ti'].xcom_push(key=f'voice_msg', value=include_voice_msg)
        need_handle_tasks.append(f'wx_voice_handler')

    if include_text_msg:
        context['ti'].xcom_push(key=f'text_msg', value=include_text_msg)
        # 如果仅有文本消息，则直接执行文本消息处理
        if not need_handle_tasks:
            need_handle_tasks.append(f'wx_text_handler')
    
    print(f"[WATCHER] 需要处理的任务: {need_handle_tasks}")
    return need_handle_tasks


def handle_video_messages(**context):
    """处理视频消息"""
    print(f"[HANDLE] 处理视频消息")
    try:
        # 从 op_kwargs 传入的参数会被放入 context 中
        appium_server_info = context['wx_config']
        print(f"[HANDLE] 获取Appium服务器信息: {appium_server_info}")
    except KeyError:
        print(f"[HANDLE] 获取Appium服务器信息失败: 未在 context 中找到 'wx_config'")
        return []

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']
    
    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key=f'video_msg')
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
    schedule=timedelta(seconds=20),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
) as dag:

    # 监控聊天消息
    wx_watcher = PythonOperator(task_id='wx_watcher', python_callable=monitor_chats)

    # 处理文本消息
    wx_text_handler = PythonOperator(task_id='wx_text_handler', python_callable=handle_text_messages, trigger_rule='none_failed_min_one_success')

    # 处理图片消息
    wx_image_handler = PythonOperator(task_id='wx_image_handler', python_callable=handle_image_messages)

    # 处理语音消息
    wx_voice_handler = PythonOperator(task_id='wx_voice_handler', python_callable=handle_voice_messages)

    # 处理视频消息
    # wx_video_handler_0 = PythonOperator(task_id='wx_video_handler_0', python_callable=handle_video_messages)

    # 保存文本消息到数据库
    save_text_msg_to_db = PythonOperator(task_id='save_text_msg_to_db', python_callable=save_text_msg_to_db)

    # 保存图片消息到数据库
    save_image_msg_to_db = PythonOperator(task_id='save_image_msg_to_db', python_callable=save_image_msg_to_db)

    # 保存图片到腾讯云对象存储
    save_image_to_cos = PythonOperator(task_id='save_image_to_cos', python_callable=save_image_to_cos)
    

    # 设置依赖关系
    wx_watcher >> wx_text_handler >> save_text_msg_to_db

    wx_watcher >> wx_image_handler >> wx_text_handler
    
    wx_image_handler >> save_image_to_cos >> save_image_msg_to_db

    wx_watcher >> wx_voice_handler
    # wx_watcher >> wx_video_handler_0
    # wx_watcher_1 >> wx_video_handler_1
    # wx_watcher_2 >> wx_video_handler_2

for wx_key, wx_config in WX_CONFIGS.items():
    dag_id = wx_config['dag_id']
    globals()[dag_id] = create_wx_watcher_dag_function(wx_key,wx_config)

def create_wx_watcher_dag_function(wx_key,wx_config):
    dag=DAG(
        dag_id=wx_config['dag_id'],
        default_args={'owner': 'claude89757'},
        description='使用Appium SDK自动化微信操作',
        schedule=timedelta(seconds=20),
        start_date=datetime(2025, 4, 22),
        max_active_runs=1,
        catchup=False,
        tags=['个人微信',wx_config['wx_name']],
    )
    
    op_kwargs = {'wx_config': wx_config}

    wx_watcher = PythonOperator(task_id='wx_watcher', python_callable=monitor_chats, op_kwargs=op_kwargs, dag=dag)

    # 处理文本消息
    wx_text_handler = PythonOperator(task_id='wx_text_handler', python_callable=handle_text_messages, op_kwargs=op_kwargs, trigger_rule='none_failed_min_one_success',dag=dag)

    # 处理图片消息
    wx_image_handler = PythonOperator(task_id='wx_image_handler', python_callable=handle_image_messages, op_kwargs=op_kwargs, dag=dag)

    # 处理语音消息
    wx_voice_handler = PythonOperator(task_id='wx_voice_handler', python_callable=handle_voice_messages, op_kwargs=op_kwargs, dag=dag)

    # 处理视频消息
    # wx_video_handler = PythonOperator(task_id='wx_video_handler', python_callable=handle_video_messages, op_kwargs=op_kwargs, dag=dag)

    # 保存文本消息到数据库
    save_text_msg_to_db = PythonOperator(task_id='save_text_msg_to_db', python_callable=save_text_msg_to_db, op_kwargs=op_kwargs, dag=dag)

    # 保存图片消息到数据库
    save_image_msg_to_db = PythonOperator(task_id='save_image_msg_to_db', python_callable=save_image_msg_to_db, op_kwargs=op_kwargs, dag=dag)

    # 保存图片到腾讯云对象存储
    save_image_to_cos = PythonOperator(task_id='save_image_to_cos', python_callable=save_image_to_cos, op_kwargs=op_kwargs, dag=dag)
    
    # 设置依赖关系
    wx_watcher >> wx_text_handler >> save_text_msg_to_db

    wx_watcher >> wx_image_handler >> wx_text_handler
    
    wx_image_handler >> save_image_to_cos >> save_image_msg_to_db

    wx_watcher >> wx_voice_handler

    return dag
    