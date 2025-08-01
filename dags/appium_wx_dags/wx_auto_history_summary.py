#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化聊天记录总结与客户标签分析
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
from appium_wx_dags.common.mysql_tools import (
    get_wx_chat_history, 
    get_wx_contact_list,
    save_chat_summary_to_db, 
    save_token_usage_to_db
)
from utils.dify_sdk import DifyAgent

DAG_ID = "wx_auto_history_summary"
# 触发总结的新消息阈值
NEW_MESSAGES_THRESHOLD = 25


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


def get_latest_summary_record(wx_user_id, contact_name):
    """
    获取联系人的最新总结记录
    
    Args:
        wx_user_id (str): 微信用户ID
        contact_name (str): 联系人名称
        
    Returns:
        dict: 总结记录，如果不存在则返回None
    """
    # 使用Airflow变量作为缓存
    cache_key = f"{wx_user_id}_{contact_name}_chat_summary"
    try:
        return Variable.get(cache_key, deserialize_json=True)
    except:
        return None


def check_and_process_contact(wx_user_id, contact, **context):
    """
    检查并处理单个联系人的聊天记录总结
    
    Args:
        wx_user_id (str): 微信用户ID
        contact (dict): 联系人信息
        context: Airflow上下文
        
    Returns:
        dict: 处理结果
    """
    contact_name = contact.get('contact_name') or contact.get('remark_name')
    if not contact_name:
        print(f"联系人名称缺失，跳过处理: {contact}")
        return {"error": "联系人名称缺失"}
    
    print(f"处理联系人: {contact_name}")
    
    # 获取最新的聊天记录
    chat_history = get_wx_chat_history(contact_name=contact_name, wx_user_id=wx_user_id, limit=200)
    if not chat_history:
        print(f"未获取到聊天记录，跳过处理: {contact_name}")
        return {"error": "未获取到聊天记录"}
    
    # 获取文本消息数量（排除自己发送的消息）
    text_messages = [msg for msg in chat_history if msg['msg_type'] == 1 and not msg['is_self']]
    current_message_count = len(text_messages)
    
    # 获取最新的总结记录
    latest_summary = get_latest_summary_record(wx_user_id, contact_name)
    
    # 判断是否需要触发总结
    need_summary = False
    reason = ""
    
    if not latest_summary:
        need_summary = True
        reason = "新联系人，首次总结"
    elif current_message_count >= (latest_summary.get('message_count', 0) + NEW_MESSAGES_THRESHOLD):
        need_summary = True
        reason = f"新增消息超过阈值 ({current_message_count - latest_summary.get('message_count', 0)} > {NEW_MESSAGES_THRESHOLD})"
    
    if not need_summary:
        print(f"无需总结: {contact_name}, 当前消息数: {current_message_count}, 上次总结消息数: {latest_summary.get('message_count', 0)}")
        return {"status": "skipped", "reason": "消息数未达到总结阈值"}
    
    print(f"开始总结: {contact_name}, 原因: {reason}")
    
    # 将聊天记录转换为文本形式
    chat_text_list = []
    for msg in text_messages:
        chat_text_list.append(f"[{msg['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')}] {msg['sender_name']}: {msg['content']}")
    chat_text = "\n".join(chat_text_list)
    
    print("-"*100)
    print(f'处理联系人 {contact_name} 的聊天记录，共 {len(chat_text_list)} 条')
    print("-"*100)
    
    # 初始化Dify
    dify_agent = DifyAgent(api_key=Variable.get("CHAT_SUMMARY_TOKEN"), base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取AI总结 - 直接使用Dify中已配置的提示词
    response_data = dify_agent.create_chat_message(
        query=chat_text,  # 直接传递聊天记录，提示词已在Dify中配置
        user_id=f"{wx_user_id}_{contact_name}",
        conversation_id=""
    )
    context['task_instance'].xcom_push(key=f'chat_summary_token_usage_data_{contact_name}', value=response_data.get("metadata", {}))
    summary_text = response_data.get("answer", "")
    
    # 从返回的文本中提取JSON数据
    summary_json = extract_json_from_string(summary_text)
    
    print("-"*100)
    print(f"联系人 {contact_name} 的总结完成")
    print("-"*100)
    
    # 准备存储到数据库的数据
    db_summary_data = {
        # 基础信息
        'contact_name': contact_name,
        'room_name': chat_history[0].get('room_name', ''),
        'wx_user_id': wx_user_id,
        'start_time': chat_history[-1]['msg_datetime'],  # 最早的消息时间
        'end_time': chat_history[0]['msg_datetime'],     # 最近的消息时间
        'message_count': current_message_count,          # 当前消息总数
        'raw_summary': summary_text                      # 保存原始文本
    }
    
    # 保存到数据库
    try:
        save_chat_summary_to_db({
            **db_summary_data,
            **summary_json  # 合并AI提取的标签信息
        })
        print(f"聊天记录总结已保存到数据库: contact_name={contact_name}, wx_user_id={wx_user_id}")
    except Exception as e:
        print(f"保存聊天记录总结到数据库失败: {e}")
        return {"status": "error", "error": str(e)}
    
    # 同时保留原来的缓存功能，作为备份
    cache_key = f"{wx_user_id}_{contact_name}_chat_summary"
    cache_data = {
        'contact_name': contact_name,
        'room_name': chat_history[0].get('room_name', ''),
        'wx_user_id': wx_user_id,
        'summary_text': summary_text,
        'summary_json': summary_json,
        'time_range': {
            'start': chat_history[-1]['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S'),
            'end': chat_history[0]['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')
        },
        'message_count': current_message_count,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    Variable.set(cache_key, cache_data, serialize_json=True)
    
    return {
        "status": "success", 
        "contact_name": contact_name, 
        "message_count": current_message_count,
        "reason": reason
    }


def auto_summary_chat_history(**context):
    """
    自动化聊天记录总结与客户标签分析
    检查所有联系人的聊天记录，对符合条件的联系人进行总结
    """
    # 获取输入参数
    input_data = context.get('dag_run').conf or {}
    print(f"输入数据: {input_data}")
    
    # 获取微信用户ID
    wx_user_id = input_data.get('wx_user_id')
    if not wx_user_id:
        raise ValueError("缺少必填参数: wx_user_id")
    
    # 获取联系人列表
    try:
        contacts = get_wx_contact_list(wx_user_id=wx_user_id)
        print(f"获取到 {len(contacts)} 个联系人")
    except Exception as e:
        print(f"获取联系人列表失败: {e}")
        raise
    
    # 处理结果统计
    results = {
        "total": len(contacts),
        "processed": 0,
        "success": 0,
        "skipped": 0,
        "error": 0,
        "details": []
    }
    
    # 处理每个联系人
    for contact in contacts:
        try:
            result = check_and_process_contact(wx_user_id, contact, **context)
            results["processed"] += 1
            results["details"].append(result)
            
            if result.get("status") == "success":
                results["success"] += 1
            elif result.get("status") == "skipped":
                results["skipped"] += 1
            else:
                results["error"] += 1
        except Exception as e:
            print(f"处理联系人失败: {contact.get('contact_name')}, 错误: {e}")
            results["processed"] += 1
            results["error"] += 1
            results["details"].append({"status": "error", "contact_name": contact.get('contact_name'), "error": str(e)})
    
    print(f"处理完成: 总计 {results['total']} 个联系人, 成功 {results['success']}, 跳过 {results['skipped']}, 错误 {results['error']}")
    return results


def save_token_usage(**context):
    """
    保存token用量到DB
    """
    # 获取处理结果
    summary_results = context.get('task_instance').xcom_pull(task_ids='auto_summary_chat_history')
    if not summary_results:
        print("[WATCHER] 没有收到处理结果")
        return
    
    # 获取微信用户ID
    wx_user_id = context.get('dag_run').conf.get('wx_user_id', '')
    if not wx_user_id:
        print("[WATCHER] 缺少微信用户ID")
        return
    
    # 处理每个成功总结的联系人的token用量
    for detail in summary_results.get('details', []):
        if detail.get('status') != 'success':
            continue
        
        contact_name = detail.get('contact_name')
        if not contact_name:
            continue
        
        # 获取token用量信息
        token_usage_data = context.get('task_instance').xcom_pull(key=f'chat_summary_token_usage_data_{contact_name}')
        if not token_usage_data:
            print(f"[WATCHER] 没有收到联系人 {contact_name} 的token用量信息")
            continue
        
        # 提取token信息
        msg_id = token_usage_data.get('message_id', '')
        prompt_tokens = str(token_usage_data.get('usage', {}).get('prompt_tokens', ''))
        prompt_unit_price = token_usage_data.get('usage', {}).get('prompt_unit_price', '')
        prompt_price_unit = token_usage_data.get('usage', {}).get('prompt_price_unit', '')
        prompt_price = token_usage_data.get('usage', {}).get('prompt_price', '')
        completion_tokens = str(token_usage_data.get('usage', {}).get('completion_tokens', ''))
        completion_unit_price = token_usage_data.get('usage', {}).get('completion_unit_price', '')
        completion_price_unit = token_usage_data.get('usage', {}).get('completion_price_unit', '')
        completion_price = token_usage_data.get('usage', {}).get('completion_price', '')
        total_tokens = str(token_usage_data.get('usage', {}).get('total_tokens', ''))
        total_price = token_usage_data.get('usage', {}).get('total_price', '')
        currency = token_usage_data.get('usage', {}).get('currency', '')
        
        save_token_usage_data = {
            'token_source_platform': 'wx_history_summary',
            'msg_id': msg_id,
            'prompt_tokens': prompt_tokens,
            'prompt_unit_price': prompt_unit_price,
            'prompt_price_unit': prompt_price_unit,
            'prompt_price': prompt_price,
            'completion_tokens': completion_tokens,
            'completion_unit_price': completion_unit_price,
            'completion_price_unit': completion_price_unit,
            'completion_price': completion_price,
            'total_tokens': total_tokens,
            'total_price': total_price,
            'currency': currency,
            'source_ip': '',
            'wx_user_id': wx_user_id,
            'wx_user_name': wx_user_id,
            'room_id': contact_name,
            'room_name': contact_name
        }
        
        # 保存token用量到DB
        try:
            save_token_usage_to_db(save_token_usage_data, wx_user_id)
            print(f"[WATCHER] 已保存联系人 {contact_name} 的token用量")
        except Exception as e:
            print(f"[WATCHER] 保存联系人 {contact_name} 的token用量失败: {e}")


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    schedule_interval='*/5 * * * *',  # 每5分钟执行一次
    tags=['个人微信'],
    description='自动化聊天记录总结'
)

# 为DAG添加文档说明
dag.doc_md = """
## 自动化聊天记录总结与客户标签分析DAG

此DAG用于自动化总结微信聊天记录，提取客户标签信息，并使用AI生成摘要。
每5分钟自动检查一次，对符合条件的联系人进行总结。

### 触发条件:
1. 新联系人（没有总结记录）
2. 现有联系人的聊天记录新增了至少25条消息

### 如何使用:
1. 点击"Trigger DAG"按钮
2. 选择"Trigger DAG w/ config"
3. 在配置框中输入JSON格式的参数:
```json
{
  "wx_user_id": "你的微信用户ID"
}
```

### 必填参数:
- `wx_user_id`: 你的微信用户ID

### 输出:
- 会将摘要结果保存到数据库的`wx_chat_summary`表中
- 同时也会缓存到Airflow变量中，缓存键为`{wx_user_id}_{contact_name}_chat_summary`
"""

# 创建处理消息的任务
auto_summary_chat_history_task = PythonOperator(
    task_id='auto_summary_chat_history',
    python_callable=auto_summary_chat_history,
    provide_context=True,
    dag=dag
)

save_token_usage_task = PythonOperator(
    task_id='save_token_usage',
    python_callable=save_token_usage,
    provide_context=True,
    dag=dag
)
    
# 设置依赖关系
auto_summary_chat_history_task >> save_token_usage_task
