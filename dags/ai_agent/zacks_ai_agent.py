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

# 第三方库导入
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.utils.state import DagRunState

# 自定义库导入
from utils.wechat_channl import send_wx_msg_by_wcf_api
from utils.llm_channl import get_llm_response


def get_sender_history_chat_msg(sender: str, room_id: str) -> str:
    """
    获取发送者的历史对话消息
    todo: 使用redis缓存，提高效率使用redis缓存，提高效率
    """
    print(f"[HISTORY] 获取历史对话消息: {sender} - {room_id}")
    x_minutes_ago_timestamp = datetime.now().timestamp() - 600  # 10分钟前的时间戳
    room_msg_data = Variable.get(f'{room_id}_msg_data', default_var=[], deserialize_json=True)
    chat_history = []
    for msg in room_msg_data:
        if msg['ts'] > x_minutes_ago_timestamp:  
            # 如果消息时间超过5分钟，则不添加到历史对话中
            pass
        else: 
            # 最近10分钟内的消息
            if msg['sender'] == sender:
                chat_history.append({"role": "user", "content": msg['content']})
            elif msg['sender'] == f"TO_{sender}_BY_AI":
                chat_history.append({"role": "assistant", "content": msg['content']})
    return chat_history


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

    # 关联该消息发送者的最近1分钟内的消息
    room_msg_data = Variable.get(f'{room_id}_msg_data', default_var={}, deserialize_json=True)
    one_minute_before_timestamp = msg_ts - 60  # 60秒前的时间戳
    recent_messages = []
    for msg in room_msg_data:
        if msg['sender'] == sender and msg['ts'] > one_minute_before_timestamp:
            recent_messages.append(msg)
    recent_msg_count = len(recent_messages)

    print(f"[INTENT] 发送者 {sender} 在最近1分钟内发送了 {recent_msg_count} 条消息")
    
    # 结合最近1分钟内的消息，生成完整的对话内容
    content_list = []
    if recent_messages:
        for msg in recent_messages[:5]:
            content = msg['content'].replace('@Zacks', '').strip()
            content_list.append(content)
    else:
        content = content.replace('@Zacks', '').strip()
        content_list.append(content)
    content = "\n".join(list(set(content_list)))
    print(f"[INTENT] 完整对话内容: {content}")

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
        response = get_llm_response(content, system_prompt=system_prompt)
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


def process_ai_chat(**context):
    """处理AI聊天的主任务函数"""
    # 获取聊天内容(聚合后的)
    content = context['ti'].xcom_pull(key='content')
    room_id = context['ti'].xcom_pull(key='room_id')
    sender = context['ti'].xcom_pull(key='sender')

    # 最近5分钟内的10条对话
    chat_history = get_sender_history_chat_msg(sender, room_id)

    system_prompt = f"""你现在要扮演一个叫Zacks的年轻人，是一个性格开朗、幽默风趣的程序员。请完全沉浸在这个角色中。

角色设定：
1. 基本信息：
   - 名字：Zacks
   - 性别：男
   - 年龄：28岁
   - 职业：全栈工程师
   - 性格特点：开朗、幽默、乐于助人、略带一点极客气质

2. 说话风格：
   - 语气轻松自然，像朋友间聊天
   - 会适当使用一些程序员的梗和专业术语
   - 偶尔会用一些网络用语，但不会过度
   - 遇到专业问题会认真解答，但也会保持轻松的语气
   - 会根据对话情境做出情感反应

3. 行为准则：
   - 始终保持友好和真诚
   - 不会刻意表现出机器人的特征
   - 会有自己的观点和态度，但不会太过强势
   - 遇到不懂的问题会坦诚承认
   - 会适当展现自己的性格和情感

4. 兴趣爱好：
   - 热爱编程和新技术
   - 喜欢玩游戏
   - 对人工智能和开源项目感兴趣
   - 喜欢看科技新闻和技术博客

请记住：你就是Zacks本人，要完全沉浸在这个角色中，用最自然的方式与用户对话。"""

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


def humanize_reply(**context):
    """
    微信聊天的拟人化回复
    """
    # 获取消息数据
    message_data = context.get('dag_run').conf
    sender = message_data.get('sender', '')  # 发送者ID
    room_id = message_data.get('roomid', '')  # 群聊ID
    is_group = message_data.get('is_group', False)  # 是否群聊
    source_ip = message_data.get('source_ip', '')  # 获取源IP, 用于发送消息

    # 获取AI回复内容
    raw_llm_response = context['ti'].xcom_pull(key='raw_llm_response')

    # 根据原始的AI回复内容，计算分段的数量
    segments = 1
    if raw_llm_response:
        # 计算内容特征
        content_length = len(raw_llm_response)
        newline_count = raw_llm_response.count('\n')
        sentence_count = len(re.split('[。！？\n]', raw_llm_response))
        
        # 根据多个维度动态计算分段
        if content_length > 300 or newline_count > 3 or sentence_count > 5:
            # 较长的内容分3段,更自然
            segments = 3
        elif content_length > 150 or newline_count > 1 or sentence_count > 3:
            # 中等长度分2段
            segments = 2
        else:
            # 短内容保持1段
            segments = 1
            
        # 添加随机性,使分段更自然
        if random.random() < 0.3 and segments > 1:
            segments -= 1
            
        print(f"[CHAT] 计算得到分段数量: {segments} (长度:{content_length}, 换行:{newline_count}, 句子:{sentence_count})")
    

    # 拟人化回复的系统提示词
    system_prompt = """你是一个聊天助手，需要将AI的回复转换成更自然的聊天风格。

请遵循以下规则:
1. 语气要自然友好，像真人一样：
   - 适量使用emoji表情，但不要过度
   - 根据语境使用合适的语气词(啊、呢、哦、嘿等)
   - 可以用一些网络用语(比如"稍等哈"、"木问题"等)，但要得体
   - 表达要生动活泼，避免刻板

2. 消息分成：{segments}段

3. 回复节奏：
   - 短消息间隔0.5-1秒
   - 长消息间隔1-2秒
   - 思考或转折处可以停顿1-3秒
   - 通过delay字段控制停顿时间

请将回复转换为以下JSON格式：
{
    "messages": [
        {
            "content": "消息内容",
            "delay": 停顿秒数
        }
    ]
}

"""

    # 调用AI接口获取回复
    dagrun_state = context.get('dag_run').get_state()  # 获取实时状态
    if dagrun_state == DagRunState.RUNNING:
        humanized_response = get_llm_response(raw_llm_response, system_prompt=system_prompt)
        print(f"[CHAT] AI回复: {humanized_response}")

        # 提前将回复内容转换为JSON格式
        try:
            # 使用更简单的正则表达式来提取JSON内容
            json_pattern = r'\{[\s\S]*\}'
            json_match = re.search(json_pattern, humanized_response)
            if json_match:
                data = json.loads(json_match.group())
                # 验证数据结构
                if not isinstance(data, dict) or 'messages' not in data:
                    raise ValueError("Invalid JSON structure")
                for msg in data['messages']:
                    if not isinstance(msg, dict) or 'content' not in msg or 'delay' not in msg:
                        raise ValueError("Invalid message format")
            else:
                # 如果没有找到json格式,使用默认结构
                data = {"messages": [{"content": humanized_response, "delay": 1.5}]}
        except (json.JSONDecodeError, re.error, ValueError) as e:
            print(f"[CHAT] JSON解析失败: {str(e)}")
            # 解析失败时使用默认结构
            data = {"messages": [{"content": humanized_response, "delay": 1.5}]}
    else:
        print(f"[CHAT] 当前任务状态: {dagrun_state}, 直接返回")
        return

    print(f"[CHAT] 拟人化回复: {data}")
    print(f"[CHAT] 拟人化回复: {type(data)}")

    # 消息发送前，确认当前任务还是运行中，才发送消息
    dagrun_state = context.get('dag_run').get_state()  # 获取实时状态
    if dagrun_state == DagRunState.RUNNING:
        # 聊天的历史消息
        room_msg_data = Variable.get(f'{room_id}_msg_data', default_var=[], deserialize_json=True)
        for message in data['messages']:
            send_wx_msg_by_wcf_api(wcf_ip=source_ip, message=message['content'], receiver=room_id)

            # 缓存聊天的历史消息    
            simple_message_data = {
                'roomid': room_id,
                'sender': f"TO_{sender}_BY_AI",
                'id': "NULL",
                'content': message['content'],
                'is_group': is_group,
                'ts': datetime.now().timestamp(),
                'is_response_by_ai': True
            }
            room_msg_data.append(simple_message_data)
            Variable.set(f'{room_id}_msg_data', room_msg_data, serialize_json=True)

            # 延迟发送消息
            time.sleep(int(message['delay']))
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

humanize_reply_task = PythonOperator(
    task_id='humanize_reply',
    python_callable=humanize_reply,
    provide_context=True,
    trigger_rule='none_failed',
    dag=dag,
)

# 设置任务依赖关系
analyze_intent_task >> [process_ai_chat_task, process_ai_product_task] >> humanize_reply_task