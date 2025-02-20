#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
欢迎新成员加入群聊的DAG

功能：
1. 监听新成员加入群聊事件
2. 使用AI生成个性化的网球主题欢迎词
3. 发送欢迎消息到群聊
"""

from datetime import datetime, timedelta
import re
from airflow import DAG
from airflow.operators.python import PythonOperator
from utils.wechat_channl import send_wx_msg
from utils.llm_channl import get_llm_response

def generate_welcome_message(member_id: str) -> str:
    """使用AI生成个性化的欢迎词"""
    
    prompt = f"""请你扮演一个热情友好的网球俱乐部管理员。
现在有一位新成员加入了我们的交流群。
请生成一段简短的欢迎词(50字以内)，要求：
1. 要体现网球运动的特点
2. 语气要活泼、友好
3. 可以适当加入一些网球相关的表情符号 🎾
4. 要让新成员感受到群的活力和温暖

只需要返回欢迎词文本，不需要任何解释。"""

    welcome_msg = get_llm_response(f"新成员(ID:{member_id})加入", model_name="gpt-4o-mini", system_prompt=prompt)
    return welcome_msg

def welcome_new_member(**context):
    """处理新成员加入群聊的任务函数"""
    
    # 获取消息数据
    dag_run = context.get('dag_run')
    if not dag_run or not dag_run.conf:
        print("没有收到消息数据")
        return
        
    message_data = dag_run.conf.get('current_message', {})
    content = message_data.get('content', '')
    room_id = message_data.get('roomid')
    source_ip = message_data.get('source_ip')
    
    # 提取新成员ID
    member_pattern = r'"([^"]+)"通过'
    match = re.search(member_pattern, content)
    if not match:
        print("未找到新成员ID")
        return
    
    member_id = match.group(1)
    
    # 生成欢迎词
    welcome_msg = generate_welcome_message(member_id)
    
    # 发送欢迎消息
    send_wx_msg(
        wcf_ip=source_ip,
        message=welcome_msg,
        receiver=room_id
    )
    print(f"已发送欢迎消息: {welcome_msg}")

# 创建DAG
dag = DAG(
    'welcome_agent_001',
    default_args={
        'owner': 'claude89757',
    },
    description='欢迎新成员加入群聊',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['微信群管理'],
)

# 创建欢迎任务
welcome_task = PythonOperator(
    task_id='welcome_new_member',
    python_callable=welcome_new_member,
    provide_context=True,
    dag=dag,
)

welcome_task
