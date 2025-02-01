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
from datetime import datetime, timedelta, timezone
import time

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.api.common.trigger_dag import trigger_dag
from airflow.models.dagrun import DagRun
from airflow.utils.state import DagRunState
from airflow.models.variable import Variable
from airflow.utils.session import create_session

from utils.wechat_channl import send_wx_msg
from utils.wechat_channl import get_wx_contact_list
from utils.redis import RedisLock
from utils.llm_channl import get_llm_response


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



WX_USERNAME = "H88-AI 教练胡哥"


def excute_wx_command(content: str, room_id: str, sender: str, source_ip: str) -> bool:
    """执行命令"""

    # 检查是否是管理员
    admin_wxid = Variable.get('admin_wxid', default_var=[], deserialize_json=True)
    if sender not in admin_wxid:
        # 非管理员不执行命令
        print(f"[命令] {sender} 不是管理员，不执行命令")
        return False

    if content.replace(f'@{WX_USERNAME}', '').strip().lower() == 'ai off':
        print("[命令] 禁用AI聊天")
        Variable.set(f'{room_id}_disable_ai', True, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已禁用AI聊天', receiver=room_id)
        return True
    elif content.replace(f'@{WX_USERNAME}', '').strip().lower() == 'ai on':
        print("[命令] 启用AI聊天")
        Variable.delete(f'{room_id}_disable_ai')
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已启用AI聊天', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "开启AI聊天" in content:
        # 加入AI聊天群
        enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
        enable_ai_room_ids.append(room_id)
        Variable.set('enable_ai_room_ids', enable_ai_room_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已加入AI聊天群', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "关闭AI聊天" in content:
        # 退出AI聊天群
        enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
        enable_ai_room_ids.remove(room_id)
        Variable.set('enable_ai_room_ids', enable_ai_room_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已退出AI聊天群', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "开启AI视频" in content:
        # 开启AI视频处理
        enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
        enable_ai_video_ids.append(room_id)
        Variable.set('enable_ai_video_ids', enable_ai_video_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已打开AI视频处理', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "关闭AI视频" in content:
        # 关闭AI视频处理
        enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
        enable_ai_video_ids.remove(room_id)
        Variable.set('enable_ai_video_ids', enable_ai_video_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已关闭AI视频处理', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "显示提示词" in content:
        # 显示系统提示词
        system_prompt = Variable.get("system_prompt", default_var="你是一个友好的AI助手，请用简短的中文回答关于图片的问题。", deserialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] 当前系统提示词: \n\n---\n{system_prompt}\n---', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "设置提示词" in content:
        # 设置系统提示词
        line_list = content.splitlines()
        system_prompt = "\n".join(line_list[1:])
        Variable.set("system_prompt", system_prompt, serialize_json=True, deserialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] 已设置系统提示词: \n\n---\n{system_prompt}\n---', receiver=room_id)
        return True
    elif f"@{WX_USERNAME}" in content and "帮助" in content:
        help_text = f"""[bot] 可用命令列表 🤖

1. @XX 帮助 - 显示此帮助信息 ❓
2. @XX 开启AI聊天 - 加入AI聊天群 💬
3. @XX 关闭AI聊天 - 退出AI聊天群 🔕
4. @XX 开启AI视频 - 开启AI视频处理 🎥
5. @XX 关闭AI视频 - 关闭AI视频处理 📴
6. @XX 显示提示词 - 显示当前系统提示词 📝
7. @XX 设置提示词 - 设置新的系统提示词 ⚙️
    (换行后输入新的提示词)

注意：以上命令仅管理员可用 """
        
        send_wx_msg(wcf_ip=source_ip, message=help_text, receiver=room_id)
        return True
    return False


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
    print("[WATCHER] 群聊ID:", message_data.get('roomid'))
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

    # 执行命令
    if excute_wx_command(content, room_id, sender, source_ip):
        return
    
    # 检查room_id是否在AI黑名单中(全局开关)
    if Variable.get(f'{room_id}_disable_ai', default_var=False, deserialize_json=True):
        print(f"[WATCHER] {room_id} 已禁用AI聊天，停止处理")
        return
    
    # 开启AI聊天群聊的room_id
    enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
    # 开启AI视频处理的room_id
    enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
    # 获取系统提示词
    system_prompt = Variable.get("system_prompt", default_var="你是一个友好的AI助手，请用简短的中文回答关于图片的问题。")

    # 生成run_id
    now = datetime.now(timezone.utc)
    execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
    run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
    
    # 分场景分发微信消息
    if msg_type == 1 and  (is_group and room_id in enable_ai_room_ids) and f"@{WX_USERNAME}" in content:
        # 用户的消息缓存列表（跨DAG共享该变量）
        llm_response = get_llm_response(content, model_name="gpt-4o-mini", system_prompt=system_prompt)
        # 发送LLM响应
        send_wx_msg(wcf_ip=source_ip, message=llm_response, receiver=room_id)

    elif WX_MSG_TYPES.get(msg_type) == "视频" and (not is_group or (is_group and room_id in enable_ai_video_ids)):
        # 视频消息
        print(f"[WATCHER] {room_id} 收到视频消息, 触发AI视频处理DAG")
        trigger_dag(
            dag_id='ai_tennis_video',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
        
    elif WX_MSG_TYPES.get(msg_type) == "图片" and (not is_group or (is_group and room_id in enable_ai_room_ids)):
        # 图片消息
        print(f"[WATCHER] {room_id} 收到图片消息, 触发AI图片处理DAG")
        trigger_dag(
            dag_id='image_agent_001',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    else:
        # 非文字消息，暂不触发AI聊天流程
        print("[WATCHER] 不触发AI聊天流程")

# 创建DAG
dag = DAG(
    dag_id='wx_msg_watcher_for_ai_tennis',
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
    max_active_runs=30,
    catchup=False,
    tags=['WCF-微信消息监控'],
    description='WCF-微信消息监控',
)

# 创建处理消息的任务
process_message = PythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系（当前只有一个任务，所以不需要设置依赖）
process_message
