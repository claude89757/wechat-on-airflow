#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信消息监听处理DAG

功能：
1. 监听并处理来自webhook的企业微信消息
2. 通过AI助手回复用户消息

特点：
1. 由webhook触发，不进行定时调度
2. 最大并发运行数为50
3. 支持消息分发到其他DAG处理
"""

# 标准库导入
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from threading import Thread

# 第三方库导入
import requests
from pydub import AudioSegment

# Airflow相关导入
from airflow import DAG
from airflow.api.common.trigger_dag import trigger_dag
from airflow.exceptions import AirflowException
from airflow.models import DagRun
from airflow.models.dagrun import DagRun
from airflow.models.variable import Variable
from airflow.hooks.base import BaseHook
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.redis import RedisHandler


DAG_ID = "wx_work_msg_watcher"

# 添加消息类型常量
WX_MSG_TYPES = {
    'text': '文本消息',
    'image': '图片消息',
    'voice': '语音消息',
    'video': '视频消息',
    'file': '文件消息',
    'location': '地理位置消息',
    'link': '链接消息',
    'event': '事件推送',
}


def process_wx_message(**context):
    """
    处理企业微信消息的任务函数, 消息分发到其他DAG处理
    
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
    print("--------------------------------")
    print(json.dumps(message_data, ensure_ascii=False, indent=2))
    print("--------------------------------")
    
    # 判断消息类型
    msg_type = message_data.get('MsgType')
    
    if msg_type == 'text':
        return ['handler_text_msg', 'save_msg_to_mysql']
    elif msg_type == 'image':
        return ['handler_image_msg', 'save_msg_to_mysql']
    elif msg_type == 'voice':
        return ['handler_voice_msg', 'save_msg_to_mysql']
    else:
        print(f"[WATCHER] 不支持的消息类型: {msg_type}")
        return []


def handler_text_msg(**context):
    """
    处理文本类消息, 通过Dify的AI助手进行聊天, 并回复企业微信消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取企业微信消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 企业微信企业ID
    from_user_name = message_data.get('FromUserName')  # 发送者的UserID
    create_time = message_data.get('CreateTime')  # 消息创建时间
    content = message_data.get('Content')  # 消息内容
    msg_id = message_data.get('MsgId')  # 消息ID
    
    # 获取房间ID (如果是群聊)
    room_id = message_data.get('RoomId', '')
    
    print(f"收到来自 {from_user_name} 的消息: {content}")
    
    # 初始化redis
    redis_handler = RedisHandler()
    
    # 更新消息列表
    redis_handler.append_msg_list(f'{from_user_name}_{to_user_name}_msg_list', message_data)
    
    # TODO: 实现企业微信API的消息处理和AI回复
    print("实现企业微信消息处理和AI回复")



def save_msg_to_mysql(**context):
    """
    保存消息到MySQL
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    if not message_data:
        print("[DB_SAVE] 没有收到消息数据")
        return
    
    # 提取消息信息
    from_user_name = message_data.get('FromUserName', '')  # 发送者的UserID
    to_user_name = message_data.get('ToUserName', '')      # 接收者的企业ID
    msg_id = message_data.get('MsgId', '')                 # 消息ID
    msg_type = message_data.get('MsgType', '')             # 消息类型
    content = message_data.get('Content', '')              # 消息内容
    room_id = message_data.get('RoomId', '')               # 群聊ID
    
    # 确保create_time是整数类型
    try:
        create_time = int(message_data.get('CreateTime', 0))  # 消息时间戳
    except (ValueError, TypeError):
        create_time = 0
        print("[DB_SAVE] CreateTime转换为整数失败，使用默认值0")
    
    # 根据消息类型处理content
    if msg_type == 'image':
        content = message_data.get('PicUrl', '')
    elif msg_type == 'voice':
        content = f"MediaId: {message_data.get('MediaId', '')}, Format: {message_data.get('Format', '')}"
    
    # 消息类型名称
    msg_type_name = WX_MSG_TYPES.get(msg_type, f"未知类型({msg_type})")
    
    # 转换时间戳为datetime
    try:
        if create_time > 0:
            msg_datetime = datetime.fromtimestamp(create_time)
        else:
            msg_datetime = datetime.now()
    except Exception as e:
        print(f"[DB_SAVE] 时间戳转换失败: {e}，使用当前时间")
        msg_datetime = datetime.now()
    
    # 聊天记录的创建数据包
    create_table_sql = """CREATE TABLE IF NOT EXISTS `wx_work_chat_records` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `from_user_id` varchar(64) NOT NULL COMMENT '发送者ID',
        `from_user_name` varchar(128) DEFAULT NULL COMMENT '发送者名称',
        `to_user_id` varchar(128) DEFAULT NULL COMMENT '接收者ID',
        `to_user_name` varchar(128) DEFAULT NULL COMMENT '接收者名称',
        `room_id` varchar(128) DEFAULT NULL COMMENT '群聊ID',
        `msg_id` varchar(64) NOT NULL COMMENT '微信消息ID',        
        `msg_type` varchar(32) NOT NULL COMMENT '消息类型',
        `msg_type_name` varchar(64) DEFAULT NULL COMMENT '消息类型名称',
        `content` text COMMENT '消息内容',
        `msg_timestamp` bigint(20) DEFAULT NULL COMMENT '消息时间戳',
        `msg_datetime` datetime DEFAULT NULL COMMENT '消息时间',
        `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (`id`),
        UNIQUE KEY `uk_msg_id` (`msg_id`),
        KEY `idx_to_user_id` (`to_user_id`),
        KEY `idx_from_user_id` (`from_user_id`),
        KEY `idx_room_id` (`room_id`),
        KEY `idx_msg_datetime` (`msg_datetime`),
        KEY `idx_msg_type` (`msg_type`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业微信聊天记录';
    """
    
    # 插入数据SQL
    insert_sql = """INSERT INTO `wx_work_chat_records` 
    (from_user_id, from_user_name, to_user_id, to_user_name, room_id, msg_id, 
    msg_type, msg_type_name, content, msg_timestamp, msg_datetime) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
    content = VALUES(content),
    msg_type_name = VALUES(msg_type_name),
    updated_at = CURRENT_TIMESTAMP
    """
    
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db")
        db_conn = db_hook.get_hook().get_conn()
        cursor = db_conn.cursor()
        
        # 创建表（如果不存在）
        cursor.execute(create_table_sql)
        
        # 插入数据
        cursor.execute(insert_sql, (
            from_user_name,     # from_user_id
            from_user_name,     # from_user_name
            to_user_name,       # to_user_id
            to_user_name,       # to_user_name
            room_id,            # room_id
            msg_id,             # msg_id
            msg_type,           # msg_type
            msg_type_name,      # msg_type_name
            content,            # content
            create_time,        # msg_timestamp
            msg_datetime        # msg_datetime
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存消息到数据库: {msg_id}")
        
    except Exception as e:
        print(f"[DB_SAVE] 保存消息到数据库失败: {e}")
        if db_conn:
            try:
                db_conn.rollback()
            except:
                pass
    finally:
        # 关闭连接
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if db_conn:
            try:
                db_conn.close()
            except:
                pass


def handler_image_msg(**context):
    """
    处理图片类消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # TODO: 实现企业微信图片消息处理
    print("实现企业微信图片消息处理")


def handler_voice_msg(**context):
    """
    处理语音类消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # TODO: 实现企业微信语音消息处理
    print("实现企业微信语音消息处理")


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['企业微信'],
    description='企业微信消息监听处理',
)

# 创建处理消息的任务
process_msg_task = BranchPythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 创建处理文本消息的任务
text_msg_task = PythonOperator(
    task_id='handler_text_msg',
    python_callable=handler_text_msg,
    provide_context=True,
    dag=dag
)

# 创建保存消息到MySQL的任务
save_msg_task = PythonOperator(
    task_id='save_msg_to_mysql',
    python_callable=save_msg_to_mysql,
    provide_context=True,
    dag=dag
)

# 创建处理图片消息的任务
image_msg_task = PythonOperator(
    task_id='handler_image_msg',
    python_callable=handler_image_msg,
    provide_context=True,
    dag=dag
)

# 创建处理语音消息的任务
voice_msg_task = PythonOperator(
    task_id='handler_voice_msg',
    python_callable=handler_voice_msg,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系
process_msg_task >> [text_msg_task, image_msg_task, voice_msg_task, save_msg_task]
