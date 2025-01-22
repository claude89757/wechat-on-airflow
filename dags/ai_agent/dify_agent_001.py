#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
from datetime import datetime, timedelta
from threading import Thread

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import send_wx_msg


DAG_ID = "dify_agent_001"


class DifyAgent:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def create_chat_message(self, query, user_id, conversation_id="", inputs=None):
        """
        创建聊天消息
        """
        if inputs is None:
            inputs = {}
            
        url = f"{self.base_url}/chat-messages"
        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": "blocking",  # 改为非流式响应
            "conversation_id": conversation_id,
            "user": user_id
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"创建消息失败: {response.text}")

    def list_conversations(self, user_id, last_id="", limit=20, sort_by="-updated_at"):
        """
        获取用户会话列表
        """
        url = f"{self.base_url}/conversations"
        params = {
            "user": user_id,
            "last_id": last_id,
            "limit": limit,
            "sort_by": sort_by
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"获取会话列表失败: {response.text}")

def get_dify_agent_session(agent, room_id, sender):
    """
    获取对应room_id + sender_id 的Dify的AI助手会话
    """
    roomd_sender_key = f"{room_id}_{sender}"
    agent_session_id_infos = Variable.get("dify_agent_session_id_infos", default_var={}, deserialize_json=True)
    
    # 检查是否存在会话ID
    conversation_id = agent_session_id_infos.get(roomd_sender_key)
    
    if conversation_id:
        # 查询该会话的状态，是否正常，如果不存在或不正确，则重新创建新会话
        try:
            # 尝试获取会话列表
            conversations = agent.list_conversations(user_id=roomd_sender_key, limit=1)
            conversation_exists = False
            
            # 检查会话是否存在且状态正常
            if conversations.get("data"):
                for conv in conversations["data"]:
                    if conv.get("id") == conversation_id and conv.get("status") == "normal":
                        conversation_exists = True
                        break
            
            if not conversation_exists:
                print(f"[WARNING] 会话ID {conversation_id} 不存在或状态异常，创建新会话")
                # 创建新会话
                response = agent.create_chat_message(
                    query="你好",
                    user_id=roomd_sender_key
                )
                conversation_id = response.get("conversation_id")
                
                # 更新会话ID
                agent_session_id_infos[roomd_sender_key] = conversation_id
                Variable.set("dify_agent_session_id_infos", agent_session_id_infos, serialize_json=True)
                print(f"{roomd_sender_key} 创建新会话ID: {conversation_id}")
            else:
                print(f"{roomd_sender_key} 使用已存在的会话ID: {conversation_id}")
        except Exception as e:
            print(f"[ERROR] 检查会话状态时发生错误: {str(e)}，创建新会话")
            # 创建新会话
            response = agent.create_chat_message(
                query="你好",
                user_id=roomd_sender_key
            )
            conversation_id = response.get("conversation_id")
            
            # 更新会话ID
            agent_session_id_infos[roomd_sender_key] = conversation_id
            Variable.set("dify_agent_session_id_infos", agent_session_id_infos, serialize_json=True)
            print(f"{roomd_sender_key} 创建新会话ID: {conversation_id}")

        return conversation_id
    else:
        # 创建新会话
        response = agent.create_chat_message(
            query="你好",
            user_id=roomd_sender_key
        )
        conversation_id = response.get("conversation_id")
        
        # 保存会话ID
        agent_session_id_infos[roomd_sender_key] = conversation_id
        Variable.set("dify_agent_session_id_infos", agent_session_id_infos, serialize_json=True)
        print(f"{roomd_sender_key} 创建新会话ID: {conversation_id}")
        
        return conversation_id
    

def should_pre_stop(current_message):
    """
    检查是否需要提前停止流程
    """
    # 缓存的消息
    room_id = current_message.get('roomid')
    sender = current_message.get('sender')
    room_sender_msg_list = Variable.get(f'{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)
    if current_message['id'] != room_sender_msg_list[-1]['id']:
        print(f"[PRE_STOP] 检测到提前停止信号，停止流程执行")
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else:
        print(f"[PRE_STOP] 未检测到提前停止信号，继续执行")


def chat_with_dify_agent(**context):
    """
    通过Dify的AI助手进行聊天，并回复微信消息
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

    # 检查是否需要提前停止
    should_pre_stop(current_message_data)

    # 创建Dify的AI助手
    dify_agent = DifyAgent(api_key=Variable.get("DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))

    # 获取会话ID
    conversation_id = get_dify_agent_session(dify_agent, room_id, sender)

    # 遍历近期的消息是否已回复，没有回复，则合并到这次提问
    room_sender_msg_list = Variable.get(f'{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)
    up_for_reply_msg_list = []
    up_for_reply_msg_id_list = []
    for msg in room_sender_msg_list[-10:]:
        if not msg.get('reply_status', False):
            up_for_reply_msg_list.append(msg)
            up_for_reply_msg_id_list.append(msg['id'])
        else:
            pass

    # 整合最近未被回复的消息列表
    recent_message_content_list = [f"\n\n{msg.get('content', '')}" for msg in up_for_reply_msg_list]
    question = "\n".join(recent_message_content_list) 
    print("="*50)
    print(f"question: {question}")
    print("="*50)

    # 检查是否需要提前停止
    should_pre_stop(current_message_data)

    # 获取AI回复
    response_data = dify_agent.create_chat_message(
        query=question,
        user_id=f"{room_id}_{sender}",
        conversation_id=conversation_id
    )
    response = response_data.get("answer", "")
    
    # 打印AI回复
    print("="*50)
    print(f"response: {response}")
    print("="*50)

    # 检查是否需要提前停止
    should_pre_stop(current_message_data)
    # 发送消息, 可能需要分段发送
    for response in response.split("\n\n"):
        send_wx_msg(wcf_ip=source_ip, message=response, receiver=room_id)

    # 记录消息已被成功回复
    for msg in room_sender_msg_list:
        if msg['id'] in up_for_reply_msg_id_list:
            msg['reply_status'] = True
            print(f"[WATCHER] 消息已回复: {room_id} {sender} {msg['id']} {msg['content']}")
    Variable.set(f'{room_id}_{sender}_msg_list', room_sender_msg_list, serialize_json=True)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['基于Dify的AI助手'],
    description='基于Dify的AI助手',
)


process_ai_chat_task = PythonOperator(
    task_id='process_ai_chat',
    python_callable=chat_with_dify_agent,
    provide_context=True,
    dag=dag,
)

process_ai_chat_task
