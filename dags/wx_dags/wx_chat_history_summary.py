#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天记录总结
"""

# 标准库导入
from datetime import datetime, timedelta
import json
import re

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from wx_dags.common.mysql_tools import get_wx_chat_history
from utils.dify_sdk import DifyAgent


DAG_ID = "wx_chat_history_summary"


def extract_json_from_string(text):
    """
    从字符串中提取有效的JSON数据
    
    Args:
        text (str): 可能包含JSON数据的字符串
        
    Returns:
        dict: 提取的JSON数据，如果提取失败则返回空字典
    """
    try:
        # 尝试直接解析整个字符串
        return json.loads(text)
    except json.JSONDecodeError:
        # 如果直接解析失败，尝试查找JSON对象
        try:
            # 查找最外层的花括号对
            match = re.search(r'({.*})', text, re.DOTALL)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            
            # 如果没找到花括号对，尝试查找方括号（数组）
            match = re.search(r'(\[.*\])', text, re.DOTALL)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
        except (json.JSONDecodeError, AttributeError):
            pass
            
        # 更复杂的情况：尝试严格匹配JSON对象
        try:
            pattern = r'({(?:[^{}]|(?:\{[^{}]*\}))*})'
            matches = re.finditer(pattern, text, re.DOTALL)
            
            # 尝试每一个匹配项
            for match in matches:
                try:
                    json_str = match.group(1)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
            
    # 如果所有尝试都失败，返回空字典
    print("无法从字符串中提取有效的JSON数据")
    return {}


def summary_chat_history(**context):
    """
    聊天记录总结
    """
    # 获取输入参数
    input_data = context.get('dag_run').conf or {}
    print(f"输入数据: {input_data}")

    # 参数验证
    if not input_data:
        raise ValueError("请提供参数！请使用 'Trigger DAG w/ config' 并输入JSON格式的参数")
    
    # 检查必填参数
    room_id = input_data.get('room_id')
    wx_user_id = input_data.get('wx_user_id')
    
    if not room_id:
        raise ValueError("缺少必填参数: room_id")
    if not wx_user_id:
        raise ValueError("缺少必填参数: wx_user_id")

    # 获取聊天记录
    chat_history = get_wx_chat_history(room_id=room_id, wx_user_id=wx_user_id, limit=100)
    print(f"获取到 {len(chat_history)} 条聊天记录")
    
    if not chat_history:
        print("未获取到聊天记录，请检查room_id和wx_user_id是否正确")
        return {"error": "未获取到聊天记录"}

    # 将聊天记录转换为文本形式，只处理文本类型的消息
    chat_text_list = []
    text_messages = []
    for msg in chat_history:
        if msg['msg_type'] == 1:  # 1表示文本类型消息
            text_messages.append(msg)
            chat_text_list.append(f"[{msg['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')}] {msg['sender_name']}: {msg['content']}")
    chat_text = "\n".join(chat_text_list)

    print("="*100)
    print(chat_text)
    print("="*100)

    # 初始化Dify
    dify_agent = DifyAgent(api_key=Variable.get("CHAT_SUMMARY_TOKEN"), base_url=Variable.get("DIFY_BASE_URL"))

    # 获取AI总结
    response_data = dify_agent.create_chat_message(
        query=chat_text,  # 直接传递文本形式的聊天记录
        user_id=f"{wx_user_id}_{room_id}",
        conversation_id=""
    )
    summary_text = response_data.get("answer", "")
    
    # 从返回的文本中提取JSON数据
    summary_json = extract_json_from_string(summary_text)
    
    print("="*100)
    print("原始总结内容:")
    print(summary_text)
    print("-"*100)
    print("提取的JSON内容:")
    print(json.dumps(summary_json, ensure_ascii=False, indent=2))
    print("="*100)

    # 缓存总结结果
    cache_key = f"{wx_user_id}_{room_id}_chat_summary"
    cache_data = {
        'room_id': room_id,
        'room_name': chat_history[0]['room_name'],
        'wx_user_id': wx_user_id,
        'summary_text': summary_text,  # 保存原始文本
        'summary_json': summary_json,  # 保存提取的JSON
        'time_range': {
            'start': chat_history[0]['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S'),
            'end': chat_history[-1]['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')
        },
        'message_count': len(text_messages),  # 只统计文本消息数量
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    Variable.set(cache_key, cache_data, serialize_json=True)

    print(f"聊天记录总结完成，已缓存到 {cache_key}")
    return summary_json  # 返回提取的JSON数据


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    tags=['个人微信'],
    description='聊天记录总结'
)

# 为DAG添加文档说明
dag.doc_md = """
## 聊天记录总结DAG

此DAG用于总结微信群聊的聊天记录，并使用AI生成摘要。

### 如何使用:
1. 点击"Trigger DAG"按钮
2. 选择"Trigger DAG w/ config"
3. 在配置框中输入JSON格式的参数:
```json
{
  "room_id": "你的微信会话ID",
  "wx_user_id": "你的微信用户ID"
}
```

### 必填参数:
- `room_id`: 微信会话ID
- `wx_user_id`: 微信用户ID

### 输出:
- 会将摘要结果缓存到Airflow变量中，缓存键为`{wx_user_id}_{room_id}_chat_summary`
"""

# 创建处理消息的任务
summary_chat_history_task = PythonOperator(
    task_id='summary_chat_history',
    python_callable=summary_chat_history,
    provide_context=True,
    dag=dag
)
