#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
from datetime import datetime, timedelta
from threading import Thread

# 第三方库导入
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from ragflow_sdk import RAGFlow

# 自定义库导入
from utils.wechat_channl import send_wx_msg


DAG_ID = "ragflow_agent_001"


def get_ragflow_agent_session(agent, room_id, sender):
    """
    获取对应room_id + sender_id 的RAGFLOW的AI助手会话
    """
    # 查询当前room_id + sender_id 是否存在会话
    agent_session_id_infos = Variable.get("ragflow_agent_session_id_infos", default_var={}, deserialize_json=True)
    roomd_sender_key = f"{room_id}_{sender}"
    existing_session = None
    if agent_session_id_infos.get(roomd_sender_key):
        session_id = agent_session_id_infos.get(roomd_sender_key)
        print(f"{roomd_sender_key} old session_id: {session_id}")

        # 查询存量会话
        sessions = agent.list_sessions(agent_id=agent.id, rag=agent.rag, id=session_id)
        print(f"total session count: {len(sessions)}")
        if sessions:
            existing_session = sessions[0]
            print(f"found session_id: {existing_session.id}, session_name: {existing_session.name}")
            print("="*20)
            for message in existing_session.messages:
                print(message)
            print("="*20)
        else:
            print(f"[WARNING] session_id: {session_id} not found, create new session")
    else:
        pass

    if not existing_session:
        print(f"{roomd_sender_key} session_id: None, create new session")
        new_session = agent.create_session(id=agent.id, rag=agent.rag, name=f"{room_id}_{sender}")
        existing_session = new_session
        session_id = new_session.id
        agent_session_id_infos[roomd_sender_key] = session_id
        Variable.set(f"ragflow_agent_session_id_infos", agent_session_id_infos, serialize_json=True)
        print(f"{roomd_sender_key} session_id: {session_id}, create new session")
    else:
        print(f"{roomd_sender_key} session_id: {session_id}, use old session")
    
    return existing_session


def chat_with_ragflow_agent(**context):
    """
    通过RAGFLOW的AI助手进行聊天，并回复微信消息
    """
    # 检查是否需要提前停止
    run_id = context.get('dag_run').run_id
    pre_stop = Variable.get(f'{run_id}_pre_stop', default_var=False, deserialize_json=True)
    if pre_stop:
        Variable.set(f'{run_id}_pre_stop', False)
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else:
        print(f"[PRE_STOP] 未检测到提前停止信号，继续执行")

        # 近期其他消息
        recent_message_list = context.get('dag_run').conf.get("recent_message_list", [])
        # 当前消息
        current_message_data = context.get('dag_run').conf.get("current_message", {})

        # 获取消息数据 
        sender = current_message_data.get('sender', '')  # 发送者ID
        room_id = current_message_data.get('roomid', '')  # 群聊ID
        msg_id = current_message_data.get('id', '')  # 消息ID
        content = current_message_data.get('content', '')  # 消息内容
        source_ip = current_message_data.get('source_ip', '')  # 获取源IP, 用于发送消息
        is_group = current_message_data.get('is_group', False)  # 是否群聊

        # 获取AI回复内容
        rag_object = RAGFlow(api_key=Variable.get("RAGFLOW_API_KEY"), base_url=Variable.get("RAGFLOW_BASE_URL"))
        agent = rag_object.list_agents(title="医美智能客服")[0]
        print(f"agent_id: {agent.id}, agent_name: {agent.title}, agent_rag: {agent.rag}")

        # 获取会话
        session = get_ragflow_agent_session(agent, room_id, sender)

        # 遍历近期的消息是否已回复，没有回复，则合并到这次提问
        msg_replied_infos = Variable.get("msg_replied_infos", default_var={}, deserialize_json=True)
        recent_message_content = ""
        for msg in recent_message_list:
            msg_id = msg.get('id', '')
            msg_replied = msg_replied_infos.get(msg_id, False)
            if not msg_replied:
                recent_message_content += f"\n\n{msg.get('content', '')}"
            else:
                print(f"[WARNNING] 已回复的消息: {msg_id} {msg.get('content', '')}")

        # 输入问题
        question = recent_message_content + content
        print("="*50)
        print(f"question: {question}")
        print("="*50)

        response = ""
        for ans in session.ask(question, stream=False):
            response = ans.content
        
        # 打印AI回复
        print("="*50)
        print(f"response: {response}")
        print("="*50)

    # 消息发送前，确认当前任务还是运行中，才发送消息
    pre_stop = Variable.get(f'{run_id}_pre_stop', default_var=False, deserialize_json=True)
    if pre_stop:
        Variable.set(f'{run_id}_pre_stop', False)
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else: 
        # 发送消息, 可能需要分段发送
        for response in response.split("\n\n"):
            send_wx_msg(wcf_ip=source_ip, message=response, receiver=room_id)

        # 记录消息是否被回复
        msg_replied_infos[msg_id] = True
        Variable.set("msg_replied_infos", msg_replied_infos, serialize_json=True)


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
    tags=['基于RAGFLOW的AI助手'],
    description='基于RAGFLOW的AI助手',
)


process_ai_chat_task = PythonOperator(
    task_id='process_ai_chat',
    python_callable=chat_with_ragflow_agent,
    provide_context=True,
    dag=dag,
)

process_ai_chat_task
