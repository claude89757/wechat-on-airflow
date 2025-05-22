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

from utils.dify_sdk import DifyAgent
from utils.appium.wx_appium import get_recent_new_msg_by_appium
from utils.appium.wx_appium import send_wx_msg_by_appium
from utils.appium.wx_appium import send_top_n_image_or_video_msg_by_appium
from utils.appium.handler_video import push_file_to_device
from utils.appium.handler_video import clear_mp4_files_in_directory
from utils.appium.handler_video import upload_file_to_device_via_sftp


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

    include_video_msg = {}
    include_text_msg = {}
    for contact_name, messages in recent_new_msg.items():
        include_video = False
        for message in messages:
            if message['msg_type'] == 'video':
                include_video = True
                break
            else:
                pass
        if include_video:
            include_video_msg[contact_name] = messages
        else:
            include_text_msg[contact_name] = messages
    
    # 缓存到XCOM
    need_handle_tasks = []
    if include_video_msg:
        context['ti'].xcom_push(key=f'video_msg_{task_index}', value=include_video_msg)
        need_handle_tasks.append(f'wx_video_handler_{task_index}')
    if include_text_msg:
        context['ti'].xcom_push(key=f'text_msg_{task_index}', value=include_text_msg)
        need_handle_tasks.append(f'wx_text_handler_{task_index}')

    if Variable.get(f"ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[]) and task_index == 0:
        need_handle_tasks.append('handle_zacks_up_for_send_msg')

        # 传递下appium_url
        context['ti'].xcom_push(key=f'zacks_appium_url', value=appium_url)
        context['ti'].xcom_push(key=f'zacks_device_name', value=device_name)
    
    print(f"[WATCHER] 需要处理的任务: {need_handle_tasks}")
    return need_handle_tasks


def handle_zacks_up_for_send_msg(**context):
    """处理Zacks的待发送消息"""
    print(f"[HANDLE] 处理Zacks的待发送消息")
    zacks_up_for_send_msg_list = Variable.get(f"ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
    print(f"[HANDLE] Zacks的待发送消息: {zacks_up_for_send_msg_list}")

    # 发送消息
    zacks_appium_url = context['ti'].xcom_pull(key=f'zacks_appium_url')
    zacks_device_name = context['ti'].xcom_pull(key=f'zacks_device_name')
    print(f"[HANDLE] 获取XCOM: {zacks_appium_url}, {zacks_device_name}")
    for msg_info in zacks_up_for_send_msg_list:
        print(f"[HANDLE] 发送消息: {msg_info}")
        try:
            send_wx_msg_by_appium(zacks_appium_url, zacks_device_name, msg_info['room_name'], [msg_info['msg']])
        except Exception as e:
            print(f"[HANDLE] 发送消息失败: {e}")
    


def handle_text_messages(**context):
    """处理文本消息"""
    print(f"[HANDLE] 处理文本消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    appium_server_info = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)[task_index]
    print(f"[HANDLE] 获取Appium服务器信息: {appium_server_info}")

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']

    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key=f'text_msg_{task_index}')
    print(f"[HANDLE] 获取XCOM: {recent_new_msg}")
    
    # 发送消息
    for contact_name, messages in recent_new_msg.items():
        msg_list = []
        for message in messages:
            msg_list.append(message['msg'])
        msg = "\n".join(msg_list)

        # AI 回复
        response_msg_list = handle_msg_by_ai(dify_api_url, dify_api_key, wx_name, contact_name, msg)

        if response_msg_list:
            send_wx_msg_by_appium(appium_url, device_name, contact_name, response_msg_list)
        else:
            print(f"[HANDLE] 没有AI回复")

    return recent_new_msg


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


def handle_msg_by_ai(dify_api_url, dify_api_key, wx_user_name, room_id, msg) -> list:
    """
    使用AI回复消息
    Args:
        wx_user_name (str): 微信用户名
        room_id (str): 房间ID(这里指会话的名称)
        msg (str): 消息内容
    Returns:
        list: AI回复内容列表
    """
    
    # 初始化DifyAgent
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_api_url)

    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{room_id}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 获取在线图片信息
    dify_files = []
    online_img_info = Variable.get(f"{wx_user_name}_{room_id}_online_img_info", default_var={}, deserialize_json=True)
    if online_img_info:
        dify_files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": online_img_info.get("id", "")
        })
    
    # 获取AI回复
    try:
        print(f"[WATCHER] 开始获取AI回复")
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=msg,
            user_id=dify_user_id,
            conversation_id=conversation_id,
            files=dify_files,
            inputs={}
        )
    except Exception as e:
        if "Variable #conversation.section# not found" in str(e):
            # 清理会话记录
            conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
            if room_id in conversation_infos:
                del conversation_infos[room_id]
                Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
            print(f"已清除用户 {dify_user_id} 在房间 {room_id} 的会话记录")
            
            # 重新请求
            print(f"[WATCHER] 重新请求AI回复")
            full_answer, metadata = dify_agent.create_chat_message_stream(
                query=msg,
                user_id=dify_user_id,
                conversation_id=None,  # 使用新的会话
                files=dify_files,
                inputs={}
            )
        else:
            raise
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")

    if not conversation_id:
        try:
            # 新会话，重命名会话
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, dify_user_id, f"{wx_user_name}_{room_id}")
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    response_msg_list = []
    for response_part in re.split(r'\\n\\n|\n\n', full_answer):
        response_part = response_part.replace('\\n', '\n')
        if response_part and response_part != "#沉默#":  # 忽略沉默
            response_msg_list.append(response_part)

    return response_msg_list


# 定义 DAG
with DAG(
    dag_id='appium_wx_msg_watcher_for_zacks',
    default_args={'owner': 'claude89757'},
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=15),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
) as dag:

    # 监控聊天消息
    wx_watcher_0 = BranchPythonOperator(task_id='wx_watcher_0', python_callable=monitor_chats)
    wx_watcher_1 = BranchPythonOperator(task_id='wx_watcher_1', python_callable=monitor_chats)
    wx_watcher_2 = BranchPythonOperator(task_id='wx_watcher_2', python_callable=monitor_chats)

    # 处理文本消息
    wx_text_handler_0 = PythonOperator(task_id='wx_text_handler_0', python_callable=handle_text_messages)
    wx_text_handler_1 = PythonOperator(task_id='wx_text_handler_1', python_callable=handle_text_messages)
    wx_text_handler_2 = PythonOperator(task_id='wx_text_handler_2', python_callable=handle_text_messages)

    # 处理视频消息
    wx_video_handler_0 = PythonOperator(task_id='wx_video_handler_0', python_callable=handle_video_messages)
    wx_video_handler_1 = PythonOperator(task_id='wx_video_handler_1', python_callable=handle_video_messages)
    wx_video_handler_2 = PythonOperator(task_id='wx_video_handler_2', python_callable=handle_video_messages)

    # 处理Zacks的待发送消息
    handle_zacks_up_for_send_msg = PythonOperator(task_id='handle_zacks_up_for_send_msg', python_callable=handle_zacks_up_for_send_msg)

    # 设置依赖关系
    wx_watcher_0 >> wx_text_handler_0
    wx_watcher_1 >> wx_text_handler_1
    wx_watcher_2 >> wx_text_handler_2

    wx_watcher_0 >> wx_video_handler_0
    wx_watcher_1 >> wx_video_handler_1
    wx_watcher_2 >> wx_video_handler_2
    
    # 仅第一个账号是处理Zacks的待发送消息
    wx_watcher_0 >> handle_zacks_up_for_send_msg
