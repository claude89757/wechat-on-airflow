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
import uuid
from datetime import datetime, timedelta, timezone
from threading import Thread

# Airflow相关导入
from airflow import DAG
from airflow.api.common.trigger_dag import trigger_dag
from airflow.exceptions import AirflowException
from airflow.models.variable import Variable
from airflow.operators.python import BranchPythonOperator, PythonOperator

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.wechat_channl import send_wx_msg
from wx_dags.common.wx_tools import WX_MSG_TYPES
from wx_dags.common.wx_tools import update_wx_user_info
from wx_dags.common.wx_tools import get_contact_name
from wx_dags.common.mysql_tools import save_msg_to_db


DAG_ID = "wx_msg_watcher"


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
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取用户信息, 并缓存
    wx_account_info = update_wx_user_info(source_ip)
    wx_user_name = wx_account_info['name']
    # 将微信账号信息传递到xcom中供后续任务使用
    context['task_instance'].xcom_push(key='wx_account_info', value=wx_account_info)

    try:
        # 账号的消息计时器+1
        msg_count = Variable.get(f"{wx_user_name}_msg_count", default_var=0, deserialize_json=True)
        Variable.set(f"{wx_user_name}_msg_count", msg_count+1, serialize_json=True)
    except Exception as error:
        # 不影响主流程
        print(f"[WATCHER] 更新消息计时器失败: {error}")
    
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
    else:
        # 其他类型消息暂不处理
        print("[WATCHER] 不触发AI聊天流程")

    # 检查房间是否开启AI - 使用用户专属的配置
    enable_rooms = Variable.get(f"{wx_account_info['wxid']}_enable_ai_room_ids", default_var=[], deserialize_json=True)
    disable_rooms = Variable.get(f"{wx_account_info['wxid']}_disable_ai_room_ids", default_var=[], deserialize_json=True)
    ai_reply = "enable" if room_id in enable_rooms and room_id not in disable_rooms else "disable"

    # 决策下游的任务
    if ai_reply == "enable" and not is_self:
        print("[WATCHER] 触发AI聊天流程")
        return ['handler_text_msg', 'save_message_to_db']
    else:
        print("[WATCHER] 不触发AI聊天流程",is_self,ai_reply)
        return ['save_message_to_db']


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

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    # 打印调试信息
    print(f"房间信息: {room_id}({room_name}), 发送者: {sender}({sender_name})")

    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))

    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_room(wx_user_name, room_id)

    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 如果开启AI，则遍历近期的消息是否已回复，没有回复，则合并到这次提问
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
        inputs={}
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

        # response缓存到xcom中
        context['task_instance'].xcom_push(key='ai_reply_msg', value=response)

    except Exception as error:
        print(f"[WATCHER] 发送消息失败: {error}")
        # 记录消息已被成功回复
        dify_agent.create_message_feedback(message_id=dify_msg_id, user_id=wx_user_name, rating="dislike", content=f"微信自动回复失败, {error}")

    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, wx_user_name)
    print("-"*50)
    for msg in messages:
        print(msg)
    print("-"*50)


def save_msg(**context):
    """
    保存消息到CDB
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
     # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')

    save_msg = {}
    # 提取消息信息
    save_msg['room_id'] = message_data.get('roomid', '')
    save_msg['sender_id'] = message_data.get('sender', '')
    save_msg['msg_id'] = message_data.get('id', '')
    save_msg['msg_type'] = message_data.get('type', 0)
    save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], f"未知类型({save_msg['msg_type']})")
    save_msg['content'] = message_data.get('content', '')
    save_msg['is_self'] = message_data.get('is_self', False)  # 是否自己发送的消息
    save_msg['is_group'] = message_data.get('is_group', False)  # 是否群聊
    save_msg['msg_timestamp'] = message_data.get('ts', 0)
    save_msg['msg_datetime'] = datetime.now() if not save_msg['msg_timestamp'] else datetime.fromtimestamp(save_msg['msg_timestamp'])
    save_msg['source_ip'] = message_data.get('source_ip', '')
    save_msg['wx_user_name'] = wx_account_info.get('name', '')
    save_msg['wx_user_id'] = wx_account_info.get('wxid', '')
    
    # 获取房间和发送者信息
    room_name = get_contact_name(save_msg['source_ip'], save_msg['room_id'], save_msg['wx_user_name'])
    if save_msg['is_self']:
        save_msg['sender_name'] = save_msg['wx_user_name']
    else:
        save_msg['sender_name'] = get_contact_name(save_msg['source_ip'], save_msg['sender_id'], save_msg['wx_user_name'])
    
    print(f"房间信息: {save_msg['room_id']}({room_name}), 发送者: {save_msg['sender_id']}({save_msg['sender_name']})")
    
    # 保存消息到DB
    save_msg_to_db(save_msg)


def save_ai_reply_msg(**context):
    """
    保存AI回复的消息到DB
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf      
    
    # 获取AI回复的消息
    ai_reply_msg = context.get('task_instance').xcom_pull(key='ai_reply_msg')

    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')

    # 提取消息信息
    save_msg = {}
    save_msg['room_id'] = message_data.get('roomid', '')
    save_msg['sender_id'] = wx_account_info.get('wxid', '')
    save_msg['msg_id'] = str(uuid.uuid4())
    save_msg['msg_type'] = 1  # 消息类型
    save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], '文本')
    save_msg['content'] = ai_reply_msg
    save_msg['is_self'] = 1  # 是否自己发送的消息
    save_msg['is_group'] = message_data.get('is_group', False)  # 是否群聊
    save_msg['msg_timestamp'] = message_data.get('ts', 0)
    save_msg['msg_datetime'] = datetime.now() if not save_msg['msg_timestamp'] else datetime.fromtimestamp(save_msg['msg_timestamp'])
    save_msg['source_ip'] = message_data.get('source_ip', '')
    save_msg['wx_user_name'] = wx_account_info.get('name', '')
    save_msg['wx_user_id'] = wx_account_info.get('wxid', '')

    # 获取房间和发送者信息
    room_name = get_contact_name(save_msg['source_ip'], save_msg['room_id'], save_msg['wx_user_name'])
    save_msg['room_name'] = room_name
    save_msg['sender_name'] = save_msg['wx_user_name']

    # 保存消息到DB
    save_msg_to_db(save_msg)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['个人微信'],
    description='个人微信消息监控',
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

# 创建保存消息到数据库的任务
save_message_task = PythonOperator(
    task_id='save_message_to_db',
    python_callable=save_msg,
    provide_context=True,
    retries=5,
    retry_delay=timedelta(seconds=1),
    dag=dag
)

# 保存AI回复的消息到数据库
save_ai_reply_msg_task = PythonOperator(
    task_id='save_ai_reply_msg',
    python_callable=save_ai_reply_msg,
    provide_context=True,
    dag=dag
)


# 设置任务依赖关系
process_message_task >> [handler_text_msg_task, save_message_task]
handler_text_msg_task >> save_ai_reply_msg_task