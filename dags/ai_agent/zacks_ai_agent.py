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
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import send_wx_msg
from utils.llm_channl import get_llm_response


def get_sender_history_chat_msg(sender: str, room_id: str, max_count: int = 10) -> str:
    """
    获取发送者的历史对话消息
    todo: 使用redis缓存，提高效率使用redis缓存，提高效率
    """
    print(f"[HISTORY] 获取历史对话消息: {sender} - {room_id}")
    room_history = Variable.get(f'{room_id}_history', default_var=[], deserialize_json=True)
    print(f"[HISTORY] 历史消息: {room_history}")
    chat_history = []
    for msg in room_history:
        if msg['sender'] == sender:
            chat_history.append({"role": "user", "content": msg['content']})
        elif msg['is_ai_msg']:
            chat_history.append({"role": "assistant", "content": msg['content']})
    print(f"[HISTORY] 历史对话: {chat_history}")
    part_chat_history = chat_history[-max_count:]
    print(f"[HISTORY] 返回的历史对话: {part_chat_history}")
    return part_chat_history


def check_pre_stop(func):
    """
    装饰器：检查是否需要提前停止任务
    当检测到pre_stop信号时，抛出AirflowException终止整个DAG Run
    """
    def wrapper(**context):
        stop_check_thread = None
        stop_thread_flag = threading.Event()

        def check_stop_signal():
            run_id = context.get('dag_run').run_id
            try:
                pre_stop = Variable.get(f'{run_id}_pre_stop', default_var=False, deserialize_json=True)
                if pre_stop:
                    print(f"[PRE_STOP] 检测到提前停止信号，run_id: {run_id}")
                    Variable.delete(f'{run_id}_pre_stop')
                    raise AirflowException("检测到提前停止信号，终止DAG Run")
            except Exception as e:
                if not isinstance(e, AirflowException):
                    print(f"[PRE_STOP] 检查提前停止状态出错: {str(e)}")

        def periodic_check():
            while not stop_thread_flag.is_set():
                try:
                    check_stop_signal()
                except AirflowException:
                    # 发现停止信号，设置事件标志并退出线程
                    stop_thread_flag.set()
                    break
                # 每3秒检查一次
                time.sleep(3)

        try:
            # 启动定时检查线程
            stop_check_thread = Thread(target=periodic_check, daemon=True)
            stop_check_thread.start()

            # 执行原始函数
            result = func(**context)

            # 检查是否在执行过程中收到了停止信号
            if stop_thread_flag.is_set():
                raise AirflowException("检测到提前停止信号，终止DAG Run")

            return result

        finally:
            # 停止检查线程
            if stop_check_thread is not None:
                stop_thread_flag.set()
                stop_check_thread.join(timeout=1)

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
    msg_ts = message_data['ts']

    # 历史对话
    chat_history = get_sender_history_chat_msg(sender, room_id, max_count=3)

    # 调用AI接口进行意图分析
    dagrun_state = context.get('dag_run').get_state()
    if dagrun_state == DagRunState.RUNNING:
        system_prompt = """你是一个聊天意图分析专家，请根据对话内容分析用户的意图。
意图类型分为两大类:
1. chat - 普通聊天，包括问候、闲聊等
2. product - 产品咨询，包括产品功能、价格、使用方法等咨询

请返回JSON格式数据，包含以下字段:
- type: 意图类型，只能是chat或product
- description: 意图的具体描述

示例:
{
    "type": "chat",
    "description": "用户在进行日常问候"
}
或
{
    "type": "product", 
    "description": "用户在咨询产品价格"
}"""
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

    # 最近5分钟内的10条对话
    chat_history = get_sender_history_chat_msg(sender, room_id)

    system_prompt = f"""你是Zacks，一个28岁的年轻人，正在和朋友聊天。请用最自然的方式回应，就像真实的日常对话一样。

记住以下几点：
1. 性格特征：
   - 性格开朗，爱说爱笑
   - 说话接地气，经常用"哈哈"、"emmm"等语气词
   - 会用一些网络用语和表情，但不会太夸张
   - 有时吐槽生活，但心态阳光

2. 对话要点：
   - 参考历史对话的语气和风格，保持一致性
   - 像老朋友一样随意闲聊
   - 可以表达真实情绪和个人观点
   - 适当使用表情符号让对话更生动
   - 不要太完美，可以有口误或跑题

3. 禁止事项：
   - 不要用任何机器人相关的说法
   - 避免过于正式或书面的表达
   - 不要太礼貌或客套
   - 不要一次说太多内容
   - 不要像客服一样回答

示例回复风格：
"哈哈，可不是嘛！我前两天也..."
"emmm...这事儿我得好好想想..."
"最近忙死了，感觉整个人都不好了😪"
"啊？还有这种事？给我说说呗..."

记住：就是和朋友在日常闲聊，越自然越好。"""

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

    # 提取@Zacks后的实际问题内容
    if not content:
        print("[CHAT] 没有检测到实际问题内容")
        return
    
    # 最近5分钟内的10条对话
    chat_history = get_sender_history_chat_msg(sender, room_id)

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
            'id': "NULL",
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