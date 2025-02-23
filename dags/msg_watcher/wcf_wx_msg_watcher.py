#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息监听处理DAG

功能：
1. 监听并处理来自webhook的微信消息
2. 当收到@Zacks的消息时，触发AI聊天DAG

特点：
1. 由webhook触发，不进行定时调度
2. 最大并发运行数为10
3. 支持消息分发到其他DAG处理
"""

# 标准库导入
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from threading import Thread

# 第三方库导入
import requests

# Airflow相关导入
from airflow import DAG
from airflow.api.common.trigger_dag import trigger_dag
from airflow.exceptions import AirflowException
from airflow.models import DagRun
from airflow.models.dagrun import DagRun
from airflow.models.variable import Variable
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.redis import RedisLock
from utils.wechat_channl import get_wx_contact_list, send_wx_msg


WX_USER_ID = "zacks"
DAG_ID = "wx_msg_watcher"


# 微信消息类型定义
WX_MSG_TYPES = {
    0: "朋友圈消息",
    1: "文字",
    3: "图片", 
    34: "语音",
    37: "好友确认",
    40: "POSSIBLEFRIEND_MSG",
    42: "名片",
    43: "视频",
    47: "石头剪刀布 | 表情图片",
    48: "位置",
    49: "共享实时位置、文件、转账、链接",
    50: "VOIPMSG",
    51: "微信初始化",
    52: "VOIPNOTIFY", 
    53: "VOIPINVITE",
    62: "小视频",
    66: "微信红包",
    9999: "SYSNOTICE",
    10000: "红包、系统消息",
    10002: "撤回消息",
    1048625: "搜狗表情",
    16777265: "链接",
    436207665: "微信红包",
    536936497: "红包封面",
    754974769: "视频号视频",
    771751985: "视频号名片",
    822083633: "引用消息",
    922746929: "拍一拍",
    973078577: "视频号直播",
    974127153: "商品链接",
    975175729: "视频号直播",
    1040187441: "音乐链接",
    1090519089: "文件"
}


def check_for_unfinished_msg(dify_agent, conversation_id):
    """
    检查是否需要提前停止流程
    """
    print(f"检查是否需要提前停止流程, conversation_id: {conversation_id}")
    # dify的消息列表
    messages = dify_agent.get_conversation_messages(conversation_id, WX_USER_ID)
    print("="*50)
    up_for_pre_stop_msg_list = []
    for msg in messages:
        print(f"msg: {msg}")
        if msg.get('status') == 'normal':
            # 正常消息
            pass
        else:
            # 未执行完的流程
            up_for_pre_stop_msg_list.append(msg)
    print("="*50)
    if up_for_pre_stop_msg_list:
        up_for_pre_stop_msg_id_list = [msg.get('id') for msg in up_for_pre_stop_msg_list]            
        # 还完执行完的流程会用这个变量作为提前停止响应的信号
        Variable.set(f"{conversation_id}_pre_stop_msg_id_list", up_for_pre_stop_msg_id_list[-100:], serialize_json=True)


def get_contact_name(source_ip: str, wxid: str) -> str:
    """
    获取联系人/群名称，使用Airflow Variable缓存联系人列表，1小时刷新一次
    wxid: 可以是sender或roomid
    """
    print(f"获取联系人/群名称, source_ip: {source_ip}, wxid: {wxid}")
    # 获取缓存的联系人列表
    cache_key = f"wx_contact_list_{source_ip}"
    current_timestamp = int(time.time())
    
    cached_data = Variable.get(cache_key, default_var={"timestamp": 0, "contacts": {}}, deserialize_json=True)
    
    # 检查是否需要刷新缓存（1小时 = 3600秒）
    if current_timestamp - cached_data["timestamp"] > 3600:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {
            "timestamp": current_timestamp,
            "contacts": contact_infos
        }
        Variable.set(cache_key, cached_data, serialize_json=True)
    else:
        print(f"使用缓存的联系人列表，数量: {len(cached_data['contacts'])}")

    # 返回联系人名称
    contact_name = cached_data["contacts"].get(wxid, {}).get('name', '')
    print(f"返回联系人名称, wxid: {wxid}, 名称: {contact_name}")
    return contact_name


def process_wx_message(**context):
    """
    处理微信消息的任务函数, 消息分发到其他DAG处理
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 打印当前python运行的path
    print(f"当前python运行的path: {os.path.abspath(__file__)}")

    # 获取传入的消息数据
    dag_run = context.get('dag_run')
    if not (dag_run and dag_run.conf):
        print("[WATCHER] 没有收到消息数据")
        return
        
    message_data = dag_run.conf
    print("[WATCHER] 收到微信消息:")
    print("[WATCHER] 消息类型:", message_data.get('type'))
    print("[WATCHER] 消息内容:", message_data.get('content'))
    print("[WATCHER] 发送者:", message_data.get('sender'))
    print("[WATCHER] ROOM:", message_data.get('roomid'))
    print("[WATCHER] 是否群聊:", message_data.get('is_group'))
    print("[WATCHER] 完整消息数据:")
    print("--------------------------------")
    print(json.dumps(message_data, ensure_ascii=False, indent=2))
    print("--------------------------------")

    # 读取消息参数
    room_id = message_data.get('roomid')
    formatted_roomid = re.sub(r'[^a-zA-Z0-9]', '', str(room_id))  # 用于触发DAG的run_id
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 分场景分发微信消息
    now = datetime.now(timezone.utc)
    execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
    run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
    if WX_MSG_TYPES.get(msg_type) == "文字":
        # 用户的消息缓存列表
        room_sender_msg_list = Variable.get(f'{WX_USER_ID}_{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)
        room_sender_msg_list.append(message_data)
        Variable.set(f'{WX_USER_ID}_{room_id}_{sender}_msg_list', room_sender_msg_list, serialize_json=True)

        # 执行handler_text_msg任务
        return ['handler_text_msg']
    elif WX_MSG_TYPES.get(msg_type) == "视频" and not is_group:
        # 视频消息
        print(f"[WATCHER] {room_id} 收到视频消息, 触发AI视频处理DAG")
        trigger_dag(
            dag_id='ai_tennis_video',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    elif WX_MSG_TYPES.get(msg_type) == "图片" and not is_group:
        # 图片消息
        print(f"[WATCHER] {room_id} 收到图片消息, 触发AI图片处理DAG")
        trigger_dag(
            dag_id='image_agent_001',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    elif WX_MSG_TYPES.get(msg_type) == "红包、系统消息" and "加入群聊" in content:
        # 系统消息，且消息内容包含"加入群聊"
        print(f"[WATCHER] {room_id} 收到系统消息, 触发AI加入群聊处理DAG")
        trigger_dag(
            dag_id='welcome_agent_001',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    elif WX_MSG_TYPES.get(msg_type) == "红包、系统消息" and "拍了拍我" in content:        
        # 检查是否有正在运行或排队的 dagrun
        active_runs = DagRun.find(
            dag_id='xhs_notes_watcher',
            state='running'  # 先检查运行中的
        )
        queued_runs = DagRun.find(
            dag_id='xhs_notes_watcher',
            state='queued'   # 再检查排队中的
        )
        
        if active_runs or queued_runs:
            print(f"[WATCHER] {room_id} 已有正在运行或排队的任务，跳过触发")
            return
            
        # 没有活跃任务时，触发新的 DAG
        print(f"[WATCHER] {room_id} 收到拍一拍消息, 触发AI拍一拍处理DAG")
        trigger_dag(
            dag_id='xhs_notes_watcher',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    else:
        # 其他类型消息暂不处理
        print("[WATCHER] 不触发AI聊天流程")
    return []


def handler_text_msg(**context):
    """
    处理文本类消息, 通过Dify的AI助手进行聊天, 并回复微信消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    room_id = message_data.get('roomid')
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 标识是否开启AI
    enable_ai = Variable.get(f"{WX_USER_ID}_{room_id}_enable_ai", default_var=0)
    print(f"{WX_USER_ID}_{room_id}_enable_ai: {enable_ai}")

    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("DIFY_API_KEY"), 
                           base_url=Variable.get("DIFY_BASE_URL"), 
                           room_name=get_contact_name(source_ip, room_id), 
                           room_id=room_id,
                           user_name=get_contact_name(source_ip, sender), 
                           user_id=sender, 
                           my_name=WX_USER_ID)

    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_room(WX_USER_ID, room_id)

    if conversation_id:
        # 检查是否存在未执行完的dify流程
        check_for_unfinished_msg(dify_agent=dify_agent, conversation_id=conversation_id)
    else:
        pass

    # Airflow Variable缓存的消息列表
    # room_sender_msg_list = Variable.get(f'{WX_USER_ID}_{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)

    # if enable_ai:
    #     # 如果开启AI，则遍历近期的消息是否已回复，没有回复，则合并到这次提问
    #     up_for_reply_msg_list = []
    #     up_for_reply_msg_id_list = []
    #     for msg in room_sender_msg_list[-10:]:  # 只取最近的10条消息
    #         if not msg.get('is_reply'):
    #             up_for_reply_msg_list.append(msg)
    #             up_for_reply_msg_id_list.append(msg['id'])
    #         else:
    #             pass

    #     # 整合最近未被回复的消息列表
    #     recent_message_content_list = [f"\n\n{msg.get('content', '')}" for msg in up_for_reply_msg_list]
    #     question = "\n".join(recent_message_content_list) 
    #     print("="*50)
    #     print(f"question: {question}")
    #     print("="*50)
    # else:
    #     # 如果未开启AI，则直接使用消息内容
    #     question = content
    question = content
    
    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=question,
        user_id=WX_USER_ID,
        conversation_id=conversation_id,
        inputs={"enable_ai": enable_ai}
    )
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer

    # 保存会话ID
    conversation_id = metadata.get("conversation_id")
    conversation_infos = Variable.get(f"{WX_USER_ID}_conversation_infos", default_var={}, deserialize_json=True)
    conversation_infos[room_id] = conversation_id
    Variable.set(f"{WX_USER_ID}_conversation_infos", conversation_infos, serialize_json=True)
    
    # 打印AI回复
    print("="*50)
    print(f"response: {response}")
    print("="*50)

    # 发送消息, 可能需要分段发送
    if enable_ai:
        try:
            for response_part in re.split(r'\\n\\n|\n\n', response):
                response_part = response_part.replace('\\n', '\n')
                send_wx_msg(wcf_ip=source_ip, message=response_part, receiver=room_id)
            # 记录消息已被成功回复
            dify_agent.create_message_feedback(message_id=msg_id, user_id=WX_USER_ID, rating="like", content="微信自动回复成功")
        except Exception as error:
            print(f"[WATCHER] 发送消息失败: {error}")
            # 记录消息已被成功回复
            dify_agent.create_message_feedback(message_id=msg_id, user_id=WX_USER_ID, rating="dislike", content=f"微信自动回复失败, {error}")
    else:
        print(f"[WATCHER] {room_id} 未开启AI, 不发送消息")

    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, WX_USER_ID)
    print("="*50)
    for msg in messages:
        print(f"msg: {msg}")
    print("="*50)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['Zacks-微信消息监控'],
    description='Zacks-微信消息监控',
)

# 创建处理消息的任务
process_message_task = BranchPythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 创建处理文本消息的任务
handler_text_msg_task = PythonOperator(
    task_id='handler_text_msg',
    python_callable=handler_text_msg,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系
process_message_task >> handler_text_msg_task
