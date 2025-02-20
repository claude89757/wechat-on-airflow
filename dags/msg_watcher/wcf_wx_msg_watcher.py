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
from airflow.models import DagRun
from airflow.utils.state import DagRunState

from utils.wechat_channl import send_wx_msg
from utils.wechat_channl import get_wx_contact_list
from utils.redis import RedisLock

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



def excute_wx_command(content: str, room_id: str, sender: str, source_ip: str) -> bool:
    """执行命令"""

    # 检查是否是管理员
    admin_wxid = Variable.get('admin_wxid', default_var=[], deserialize_json=True)
    if sender not in admin_wxid:
        # 非管理员不执行命令
        print(f"[命令] {sender} 不是管理员，不执行命令")
        return False

    # 执行命令
    if content.replace('@Zacks', '').strip().lower() == 'clear':
        print("[命令] 清理历史消息")
        Variable.delete(f'{room_id}_history')
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已清理历史消息', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai off':
        print("[命令] 禁用AI聊天")
        Variable.set(f'{room_id}_disable_ai', True, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已禁用AI聊天', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai on':
        print("[命令] 启用AI聊天")
        Variable.delete(f'{room_id}_disable_ai')
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已启用AI聊天', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai reset':
        print("[命令] 重置AI聊天")
        roomd_sender_key = f"{room_id}_{sender}"
        agent_session_id_infos = Variable.get("dify_agent_session_id_infos", default_var={}, deserialize_json=True)
        if roomd_sender_key in agent_session_id_infos:
            print(f"[命令] 删除AI聊天会话: {roomd_sender_key}")
            agent_session_id_infos[roomd_sender_key] = ""
            Variable.set("dify_agent_session_id_infos", agent_session_id_infos, serialize_json=True)
            send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已重置AI聊天会话', receiver=room_id)
    elif content.replace('@Zacks', '').strip().lower() == 'jion ai room':
        # 加入AI聊天群
        enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
        enable_ai_room_ids.append(room_id)
        Variable.set('enable_ai_room_ids', enable_ai_room_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已加入AI聊天群', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'exit ai room':
        # 退出AI聊天群
        enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
        enable_ai_room_ids.remove(room_id)
        Variable.set('enable_ai_room_ids', enable_ai_room_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已退出AI聊天群', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai video on':
        # 开启AI视频处理
        enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
        enable_ai_video_ids.append(room_id)
        Variable.set('enable_ai_video_ids', enable_ai_video_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已打开AI视频处理', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai video off':
        # 关闭AI视频处理
        enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
        enable_ai_video_ids.remove(room_id)
        Variable.set('enable_ai_video_ids', enable_ai_video_ids, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已关闭AI视频处理', receiver=room_id)
        return True
    elif content.startswith('@Zacks') and "join big room" in content:
        # 加入超级微信大群聊
        supper_big_rood_ids = Variable.get('supper_big_rood_ids', default_var=[], deserialize_json=True)
        supper_big_rood_ids.append(room_id)
        supper_big_rood_ids = list(set(supper_big_rood_ids))
        Variable.set('supper_big_rood_ids', supper_big_rood_ids, serialize_json=True)

        # 获取群名称
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"wx_contact_list: {len(wx_contact_list)}")
        contact_infos = {}
        for contact in wx_contact_list:
            wxid = contact.get('wxid', '')
            contact_infos[wxid] = contact
        # 当前群聊列表
        room_name_list = []
        for supper_big_rood_id in supper_big_rood_ids:
            source_room_name = contact_infos.get(supper_big_rood_id, {}).get('name', '')
            room_name_list.append(source_room_name)
        room_name_str = "\n".join(room_name_list)

        send_wx_msg(wcf_ip=source_ip, message=f'🤖 已加入跨群聊天\n\n📋 当前跨群聊天列表:\n{room_name_str}\n\n💡 提示：请 @Zacks 发送跨群广播消息 📢', receiver=room_id)
        return True
    elif content.startswith('@Zacks') and "exit big room" in content:
        # 退出超级微信大群聊
        supper_big_rood_ids = Variable.get('supper_big_rood_ids', default_var=[], deserialize_json=True)
        supper_big_rood_ids.remove(room_id)
        Variable.set('supper_big_rood_ids', supper_big_rood_ids, serialize_json=True)

        # 获取群名称
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"wx_contact_list: {len(wx_contact_list)}")
        contact_infos = {}
        for contact in wx_contact_list:
            wxid = contact.get('wxid', '')
            contact_infos[wxid] = contact
        # 当前群聊列表
        room_name_list = []
        for supper_big_rood_id in supper_big_rood_ids:
            source_room_name = contact_infos.get(supper_big_rood_id, {}).get('name', '')
            room_name_list.append(source_room_name)
        room_name_str = "\n".join(room_name_list)

        send_wx_msg(wcf_ip=source_ip, message=f'🤖 已退出跨群聊天\n\n📋 当前跨群聊天列表:\n{room_name_str}\n\n💡 提示：请 @Zacks 发送跨群广播消息 📢', receiver=room_id)
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
    
    # 检查room_id是否在AI黑名单中
    if Variable.get(f'{room_id}_disable_ai', default_var=False, deserialize_json=True):
        print(f"[WATCHER] {room_id} 已禁用AI聊天，停止处理")
        return
    
    # 开启AI聊天群聊的room_id
    enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
    # 开启AI视频处理的room_id
    enable_ai_video_ids = Variable.get('enable_ai_video_ids', default_var=[], deserialize_json=True)
    # 加入"超级大群"的群ID
    supper_big_rood_ids = Variable.get('supper_big_rood_ids', default_var=[], deserialize_json=True)

    # 分场景分发微信消息
    now = datetime.now(timezone.utc)
    execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
    run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
    if msg_type == 1 and room_id in supper_big_rood_ids and "@Zacks" in content:
        print(f"[WATCHER] {room_id} 已加入超级大群, 触发AI聊天DAG")
        trigger_dag(
            dag_id='broadcast_agent_001',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )

    elif msg_type == 1 and  (is_group and room_id in enable_ai_room_ids):
        # 用户的消息缓存列表（跨DAG共享该变量）
        room_sender_msg_list = Variable.get(f'{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)
        if room_sender_msg_list and message_data['id'] != room_sender_msg_list[-1]['id']:
            # 消息不是最新，则更新消息缓存列表
            room_sender_msg_list.append(message_data)
            print(f"room_sender_msg_list: {room_sender_msg_list}")
            Variable.set(f'{room_id}_{sender}_msg_list', room_sender_msg_list, serialize_json=True)

            if not room_sender_msg_list[-1].get('is_reply'):
                # 消息未回复, 触发新的DAG运行agent
                print(f"[WATCHER] 消息未回复, 触发新的DAG运行agent")
                print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
                trigger_dag(
                    dag_id='dify_agent_001',
                    conf={"current_message": message_data},
                    run_id=run_id,
                    execution_date=execution_date
                )
                print(f"[WATCHER] 成功触发AI聊天DAG，execution_date: {execution_date}")
            else:
                print(f"[WATCHER] 消息已回复，不重复触发AI聊天DAG")

        elif not room_sender_msg_list:
            # 用户的消息缓存列表为空，则添加第一条消息
            room_sender_msg_list.append(message_data)
            Variable.set(f'{room_id}_{sender}_msg_list', room_sender_msg_list, serialize_json=True)

            # 第一条消息，触发新的DAG运行agent
            print(f"[WATCHER] 第一条消息，触发新的DAG运行agent")
            print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
            trigger_dag(
                dag_id='dify_agent_001',
                conf={"current_message": message_data},
                run_id=run_id,
                execution_date=execution_date
            )
            print(f"[WATCHER] 成功触发AI聊天DAG，execution_date: {execution_date}")
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
    elif WX_MSG_TYPES.get(msg_type) == "红包、系统消息" and "加入群聊" in content:
        # 系统消息，且消息内容包含"加入群聊"
        print(f"[WATCHER] {room_id} 收到系统消息, 触发AI加入群聊处理DAG")
        trigger_dag(
            dag_id='welcome_agent_001',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    elif WX_MSG_TYPES.get(msg_type) == "红包、系统消息" and "拍了拍我" in content:        
        # 检查是否有正在运行或排队的 dagrun
        active_runs = DagRun.find(
            dag_id='xhs_notes_watcher',
            state='running'  # 先检查运行中的
        )
        queued_runs = DagRun.find(
            dag_id='xhs_notes_watcher',
            state='queued'   # 再检查排队中的
        )
        
        if active_runs or queued_runs:
            print(f"[WATCHER] {room_id} 已有正在运行或排队的任务，跳过触发")
            return
            
        # 没有活跃任务时，触发新的 DAG
        print(f"[WATCHER] {room_id} 收到拍一拍消息, 触发AI拍一拍处理DAG")
        trigger_dag(
            dag_id='xhs_notes_watcher',
            conf={"current_message": message_data},
            run_id=run_id,
            execution_date=execution_date
        )
    else:
        # 非文字消息，暂不触发AI聊天流程
        print("[WATCHER] 不触发AI聊天流程")

# 创建DAG
dag = DAG(
    dag_id='wx_msg_watcher',
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
