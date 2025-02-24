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
from utils.wechat_channl import get_wx_contact_list, send_wx_msg, get_wx_self_info


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


def should_pre_stop(current_message, wx_user_name):
    """
    检查是否需要提前停止流程
    """
    # 缓存的消息
    room_id = current_message.get('roomid')
    room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
    if current_message['id'] != room_msg_list[-1]['id']:
        print(f"[PRE_STOP] 最新消息id不一致，停止流程执行")
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else:
        print(f"[PRE_STOP] 最新消息id一致，继续执行")


def get_contact_name(source_ip: str, wxid: str, wx_user_name: str) -> str:
    """
    获取联系人/群名称，使用Airflow Variable缓存联系人列表，1小时刷新一次
    wxid: 可以是sender或roomid
    """

    print(f"获取联系人/群名称, source_ip: {source_ip}, wxid: {wxid}")
    # 获取缓存的联系人列表
    cache_key = f"{wx_user_name}_CONTACT_INFOS"
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cached_data = Variable.get(cache_key, default_var={"update_time": "1970-01-01 00:00:00", "contact_infos": {}}, deserialize_json=True)
    
    # 检查是否需要刷新缓存（1小时 = 3600秒）
    cached_time = datetime.strptime(cached_data["update_time"], '%Y-%m-%d %H:%M:%S')
    if (datetime.now() - cached_time).total_seconds() > 3600:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")
    else:
        print(f"使用缓存的联系人列表，数量: {len(cached_data['contact_infos'])}")

    # 返回联系人名称
    contact_name = cached_data["contact_infos"].get(wxid, {}).get('name', '')

    # 如果联系人名称不存在，则尝试刷新缓存
    if not contact_name:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")

        # 重新获取联系人名称
        contact_name = contact_infos.get(wxid, {}).get('name', '')

    print(f"返回联系人名称, wxid: {wxid}, 名称: {contact_name}")
    return contact_name


def get_and_cache_user_info(source_ip: str) -> dict:
    """
    获取用户信息，并缓存。对于新用户，会初始化其专属的 enable_ai_room_ids 列表
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    for account in wx_account_list:
        print(account)
        if source_ip == account['source_ip']:
            print(f"获取到缓存的用户信息: {account}")
            return account

    account = get_wx_self_info(wcf_ip=source_ip)
    account['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    account['source_ip'] = source_ip
    wx_account_list.append(account)
    print(f"新用户, 更新用户信息: {account}")
    
    # 初始化新用户的 enable_ai_room_ids 和 disable_ai_room_ids
    Variable.set(f"{account['wxid']}_enable_ai_room_ids", [], serialize_json=True)
    Variable.set(f"{account['wxid']}_disable_ai_room_ids", [], serialize_json=True)
    
    Variable.set("WX_ACCOUNT_LIST", wx_account_list, serialize_json=True)
    return account

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

    # 获取用户信息, 并缓存
    wx_account_info =get_and_cache_user_info(source_ip)
    wx_user_name = wx_account_info['name']
    # 将微信账号信息传递到xcom中供后续任务使用
    context['task_instance'].xcom_push(key='wx_account_info', value=wx_account_info)

    # 生成run_id
    now = datetime.now(timezone.utc)
    execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
    run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'

    # 分场景分发微信消息
    if WX_MSG_TYPES.get(msg_type) == "文字":
        # 用户的消息缓存列表
        room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
        room_msg_list.append(message_data)
        Variable.set(f'{wx_user_name}_{room_id}_msg_list', room_msg_list[-100:], serialize_json=True)  # 只缓存最近的100条消息

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
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']

    # 等待3秒，聚合消息
    time.sleep(3) 

    # 检查是否需要提前停止流程 
    should_pre_stop(message_data, wx_user_name)

    # 检查房间是否开启AI - 使用用户专属的配置
    enable_rooms = Variable.get(f"{wx_account_info['wxid']}_enable_ai_room_ids", default_var=[], deserialize_json=True)
    disable_rooms = Variable.get(f"{wx_account_info['wxid']}_disable_ai_room_ids", default_var=[], deserialize_json=True)
    ai_reply = "enable" if room_id in enable_rooms and room_id not in disable_rooms else "disable"

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    # 打印调试信息
    print(f"房间信息: {room_id}({room_name}), 发送者: {sender}({sender_name})")
    print(f"AI状态: {room_id} {ai_reply}")

    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))

    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_room(wx_user_name, room_id)

    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 如果开启AI，则遍历近期的消息是否已回复，没有回复，则合并到这次提问
    if ai_reply == "enable":
        room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
        up_for_reply_msg_content_list = []
        up_for_reply_msg_id_list = []
        for msg in room_msg_list[-10:]:  # 只取最近的10条消息
            if not msg.get('is_reply'):
                up_for_reply_msg_content_list.append(msg.get('content', ''))
                up_for_reply_msg_id_list.append(msg['id'])
            else:
                pass
        # 整合未回复的消息
        question = "\n\n".join(up_for_reply_msg_content_list)
    else:
        # 如果未开启AI，则直接使用消息内容
        question = content
    print("-"*50)
    print(f"question: {question}")
    print("-"*50)
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=question,
        user_id=wx_user_name,
        conversation_id=conversation_id,
        inputs={"ai_reply": ai_reply, 
                "room_id": room_id, 
                "room_name": room_name,
                "sender_name": sender_name, 
                "sender_id": sender, 
                "my_name": wx_user_name,
                "is_self": str(is_self),
                "is_group": str(is_group)}
    )
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer

    if not conversation_id:
        # 新会话，重命名会话
        conversation_id = metadata.get("conversation_id")
        dify_agent.rename_conversation(conversation_id, wx_user_name, room_name)

        # 保存会话ID
        conversation_infos = Variable.get(f"{wx_user_name}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{wx_user_name}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 开启AI，且不是自己发送的消息，则自动回复消息
    if ai_reply == "enable" and not is_self:
        dify_msg_id = metadata.get("message_id")
        try:
            for response_part in re.split(r'\\n\\n|\n\n', response):
                response_part = response_part.replace('\\n', '\n')
                send_wx_msg(wcf_ip=source_ip, message=response_part, receiver=room_id)
            # 记录消息已被成功回复
            dify_agent.create_message_feedback(message_id=dify_msg_id, user_id=wx_user_name, rating="like", content="微信自动回复成功")

            # 缓存的消息中，标记消息已回复
            room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
            for msg in room_msg_list:
                if msg['id'] in up_for_reply_msg_id_list:
                    msg['is_reply'] = True
            Variable.set(f'{wx_user_name}_{room_id}_msg_list', room_msg_list, serialize_json=True)

        except Exception as error:
            print(f"[WATCHER] 发送消息失败: {error}")
            # 记录消息已被成功回复
            dify_agent.create_message_feedback(message_id=dify_msg_id, user_id=wx_user_name, rating="dislike", content=f"微信自动回复失败, {error}")
    else:
        print(f"[WATCHER] {room_id} 未开启AI, 不发送消息")

    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, wx_user_name)
    print("-"*50)
    for msg in messages:
        print(msg)
    print("-"*50)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['微信工具', '监听消息'],
    description='微信消息监控',
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
