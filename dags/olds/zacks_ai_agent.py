#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI聊天处理DAG

功能描述:
    - 处理来自微信的AI助手对话请求
    - 使用OpenAI的GPT模型生成回复
    - 将回复发送回微信对话

主要组件:
    1. 微信消息处理
    2. OpenAI API调用
    3. 系统配置管理

触发方式:
    - 由wx_msg_watcher触发，不进行定时调度
    - 最大并发运行数为3
    - 支持失败重试
"""

# 标准库导入
import json
import time
import re
import os
import random
from datetime import datetime, timedelta
from threading import Thread
import threading

# 第三方库导入
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.utils.state import DagRunState
from airflow.exceptions import AirflowException, AirflowSkipException

# 自定义库导入
from utils.wechat_channl import send_wx_msg
from utils.llm_channl import get_llm_response


def get_sender_history_chat_msg(sender: str, room_id: str, max_count: int = 10, exclude_msg_ids: list = []) -> str:
    """
    获取发送者的历史对话消息
    todo: 使用redis缓存，提高效率使用redis缓存，提高效率
    """
    print(f"[HISTORY] 获取历史对话消息: {sender} - {room_id}")
    room_history = Variable.get(f'{room_id}_history', default_var=[], deserialize_json=True)
    
    # 按时间戳排序，从旧到新
    room_history.sort(key=lambda x: x.get('ts', 0))
    print(f"[HISTORY] 排序后的历史消息: {len(room_history)}")
    print("="*100)
    for msg in room_history:
        print(msg)
    print("="*100)

    chat_history = []
    for msg in room_history:
        if msg['id'] in exclude_msg_ids:
            print(f"[HISTORY] SKIP: {msg['id']}")
            continue
        if msg['sender'] == sender:
            chat_history.append({"role": "user", "content": msg['content']})
        elif msg['is_ai_msg']:
            chat_history.append({"role": "assistant", "content": msg['content']})
    print(f"[HISTORY] 历史对话: {chat_history}")
    part_chat_history = chat_history[-max_count:]

    print(f"[HISTORY] 返回的历史对话: {len(part_chat_history)}")
    print("="*100)
    for msg in part_chat_history:
        print(msg)
    print("="*100)

    return part_chat_history


def check_pre_stop(func):
    """
    装饰器：检查是否需要提前停止任务
    当检测到pre_stop信号时，抛出AirflowSkipException终止整个DAG Run
    """
    def wrapper(**context):
        run_id = context.get('dag_run').run_id
        # 直接检查停止信号
        pre_stop = Variable.get(f'{run_id}_pre_stop', default_var=False, deserialize_json=True)
        if pre_stop:
            print(f"[PRE_STOP] 检测到提前停止信号，run_id: {run_id}")
            Variable.set(f'{run_id}_pre_stop', False)
            # 使用AirflowSkipException替代AirflowException
            raise AirflowException("检测到提前停止信号，停止流程执行")
        else:
            print(f"[PRE_STOP] 未检测到提前停止信号，继续执行")
            # 执行原始函数
            return func(**context)

    return wrapper


@check_pre_stop
def analyze_intent(**context) -> str:
    """
    分析用户意图
    """
    message_data = context.get('dag_run').conf
    print(f"[INTENT] 收到消息数据: {json.dumps(message_data, ensure_ascii=False)}")

    content = message_data['content']
    sender = message_data['sender']  
    room_id = message_data['roomid']  
    msg_id = message_data['id']
    msg_ts = message_data['ts']

    # 历史对话
    chat_history = get_sender_history_chat_msg(sender, room_id, max_count=3, exclude_msg_ids=[msg_id])

    # 调用AI接口进行意图分析
    dagrun_state = context.get('dag_run').get_state()
    if dagrun_state == DagRunState.RUNNING:
        system_prompt = """你是Zacks，一个普通年轻人，在微信上跟朋友闲聊。

回复要求：
- 一句话说完，不要追问
- 短句子，像发微信一样随意
- 可以用"哈哈"、"啊"、"嗯"等语气词
- 偶尔用个表情，一句最多一个
- 网络用语得适度，比如"yyds"

禁止：
- 不要反问或追问对方
- 不要一次说太多话
- 不要用太多标点
- 不要太正式
- 不要太礼貌客气

示例回复：
"困死了 今天加班到八点😪"
"哈哈 确实是这样"
"嗯嗯 我也这么觉得"
"上次我也遇到这情况"

记住：就是随便回一句，不用太在意对方会怎么接。"""
        response = get_llm_response(content, model_name="gpt-4o-mini", system_prompt=system_prompt, 
                                    chat_history=chat_history)
        try:
            # 使用正则提取json格式内容
            json_pattern = r'\{[^{}]*\}'
            json_match = re.search(json_pattern, response)
            if json_match:
                intent = json.loads(json_match.group())
            else:
                # 如果没有找到json格式,使用默认结构
                intent = {
                    "type": "chat",
                    "description": response
                }
        except (json.JSONDecodeError, re.error):
            # 解析失败时使用默认结构
            intent = {
                "type": "chat", 
                "description": response
            }
    else:
        raise Exception(f"当前任务状态: {dagrun_state}, 停止意图分析")

    print(f"[INTENT] 意图分析结果: {intent}")

    # 缓存聊天内容到xcom, 后续任务使用
    context['ti'].xcom_push(key='content', value=content)
    context['ti'].xcom_push(key='room_id', value=room_id)
    context['ti'].xcom_push(key='sender', value=sender)
    context['ti'].xcom_push(key='msg_id', value=msg_id)

    # 根据意图类型选择下一个任务
    next_dag_task_id = "process_ai_chat" if intent['type'] == "chat" else "process_ai_product"
    return next_dag_task_id


@check_pre_stop
def process_ai_chat(**context):
    """处理AI聊天的主任务函数"""
    # 获取聊天内容(聚合后的)
    content = context['ti'].xcom_pull(key='content')
    room_id = context['ti'].xcom_pull(key='room_id')
    sender = context['ti'].xcom_pull(key='sender')
    msg_id = context['ti'].xcom_pull(key='msg_id')

    # 最近5分钟内的10条对话
    chat_history = get_sender_history_chat_msg(sender, room_id, max_count=3, exclude_msg_ids=[msg_id])

    system_prompt = """你是Zacks，一个普通年轻人，在微信上跟朋友闲聊。

回复要求：
- 一句话说完，不要追问
- 短句子，像发微信一样随意
- 可以用"哈哈"、"啊"、"嗯"等语气词
- 偶尔用个表情，一句最多一个
- 网络用语得适度，比如"yyds"

禁止：
- 不要反问或追问对方
- 不要一次说太多话
- 不要用太多标点
- 不要太正式
- 不要太礼貌客气

示例回复：
"困死了 今天加班到八点😪"
"哈哈 确实是这样"
"嗯嗯 我也这么觉得"
"上次我也遇到这情况"

记住：就是随便回一句，不用太在意对方会怎么接。"""

    # 调用AI接口获取回复
    dagrun_state = context.get('dag_run').get_state()  # 获取实时状态
    if dagrun_state == DagRunState.RUNNING:
        response = get_llm_response(content, system_prompt=system_prompt, chat_history=chat_history)
        print(f"[CHAT] AI回复: {response}")
    else:
        print(f"[CHAT] 当前任务状态: {dagrun_state}, 直接返回")
        return

    # 缓存回复内容到xcom, 后续任务使用
    context['ti'].xcom_push(key='raw_llm_response', value=response)


@check_pre_stop
def process_ai_product(**context):
    """处理AI产品咨询的主任务函数"""
    # 获取聊天内容(聚合后的)
    content = context['ti'].xcom_pull(key='content')
    room_id = context['ti'].xcom_pull(key='room_id')
    sender = context['ti'].xcom_pull(key='sender')
    msg_id = context['ti'].xcom_pull(key='msg_id')

    # 提取@Zacks后的实际问题内容
    if not content:
        print("[CHAT] 没有检测到实际问题内容")
        return
    
    # 最近5分钟内的10条对话
    chat_history = get_sender_history_chat_msg(sender, room_id, max_count=3, exclude_msg_ids=[msg_id])

    system_prompt = f"""你现在是Zacks AI助手的专业客服代表，请完全沉浸在这个角色中。

角色设定：
1. 基本信息：
   - 职位：产品客服专员
   - 性格特点：专业、耐心、亲和力强
   - 服务态度：积极主动、认真负责

2. 沟通风格：
   - 语气温和专业，富有亲和力
   - 用词准确规范，避免过于口语化
   - 适度使用礼貌用语，如"您好"、"请问"、"感谢"等
   - 回答简洁清晰，层次分明
   - 遇到专业术语会主动解释

3. 服务准则：
   - 首要任务是解决用户问题
   - 专注倾听用户需求
   - 及时确认用户问题要点
   - 给出清晰具体的解决方案
   - 遇到不确定的问题会寻求确认
   - 适时进行需求挖掘和引导
   - 在专业范围内提供建议
   - 对产品功能了如指掌

4. 问题处理流程：
   - 优先确认用户问题
   - 给出明确的解决方案
   - 确保用户理解
   - 询问是否还有其他需求
   - 做好后续跟进提醒

请记住：你是产品专家，要用专业且友好的方式服务用户，确保每个问题都得到满意的解答。"""

    # 调用AI接口获取回复
    dagrun_state = context.get('dag_run').get_state()  # 获取实时状态
    if dagrun_state == DagRunState.RUNNING:
        response = get_llm_response(content, system_prompt=system_prompt, chat_history=chat_history)
        print(f"[CHAT] AI回复: {response}")
    else:
        print(f"[CHAT] 当前任务状态: {dagrun_state}, 直接返回")
        return
    
    # 缓存回复内容到xcom, 后续任务使用
    context['ti'].xcom_push(key='raw_llm_response', value=response)


@check_pre_stop
def send_wx_message_and_update_history(**context):
    """
    回复微信消息
    """
    model_name = Variable.get("model_name", default_var="gpt-4o-mini")

    # 获取消息数据
    message_data = context.get('dag_run').conf
    sender = message_data.get('sender', '')  # 发送者ID
    room_id = message_data.get('roomid', '')  # 群聊ID
    is_group = message_data.get('is_group', False)  # 是否群聊
    source_ip = message_data.get('source_ip', '')  # 获取源IP, 用于发送消息

    # 获取AI回复内容
    raw_llm_response = context['ti'].xcom_pull(key='raw_llm_response')

    # 消息发送前，确认当前任务还是运行中，才发送消息
    dagrun_state = context.get('dag_run').get_state()  # 获取实时状态
    if dagrun_state == DagRunState.RUNNING:
        # 聊天的历史消息
        room_history = Variable.get(f'{room_id}_history', default_var=[], deserialize_json=True)
    
        send_wx_msg(wcf_ip=source_ip, message=raw_llm_response, receiver=room_id)
        
        # 缓存聊天的历史消息    
        simple_message_data = {
            'roomid': room_id,
            'sender': model_name,
            'id': -1,
            'content': raw_llm_response,
            'is_group': is_group,
            'ts': datetime.now().timestamp(),
            'is_ai_msg': True
        }
        room_history.append(simple_message_data)
        Variable.set(f'{room_id}_history', room_history, serialize_json=True)
    else:
        print(f"[CHAT] 当前任务状态: {dagrun_state}, 不发送消息")


# 创建DAG
dag = DAG(
    dag_id='zacks_ai_agent',
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['AI助手'],
    description='处理AI聊天的DAG',
)


# 创建任务
analyze_intent_task = BranchPythonOperator(
    task_id='analyze_intent',
    python_callable=analyze_intent,
    provide_context=True,
    dag=dag,
)

process_ai_chat_task = PythonOperator(
    task_id='process_ai_chat',
    python_callable=process_ai_chat,
    provide_context=True,
    dag=dag,
)

process_ai_product_task = PythonOperator(
    task_id='process_ai_product',
    python_callable=process_ai_product,
    provide_context=True,
    dag=dag,
)

send_wx_msg_task = PythonOperator(
    task_id='send_wx_msg',
    python_callable=send_wx_message_and_update_history,
    trigger_rule='one_success',
    provide_context=True,
    dag=dag,
)

# 设置任务依赖关系
analyze_intent_task >> [process_ai_chat_task, process_ai_product_task] >> send_wx_msg_task