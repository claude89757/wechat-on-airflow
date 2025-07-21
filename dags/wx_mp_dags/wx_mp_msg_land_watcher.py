#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号消息监听处理DAG

功能：
1. 监听并处理来自webhook的微信公众号消息
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
from utils.wechat_mp_channl import WeChatMPBot
from utils.tts import text_to_speech
from utils.redis import RedisHandler
from wx_mp_dags.common.mysql_tools import save_token_usage_to_db
from wx_mp_dags.common.wx_mp_tools import get_mp_account_info, upload_mp_image_to_cos



DAG_ID = "wx_mp_msg_land_watcher"

# 添加消息类型常量
WX_MSG_TYPES = {
    'text': '文本消息',
    'image': '图片消息',
    'voice': '语音消息',
    'video': '视频消息',
    'shortvideo': '小视频消息',
    'location': '地理位置消息',
    'link': '链接消息',
    'event': '事件推送',
}


def process_wx_message(**context):
    """
    处理微信公众号消息的任务函数, 消息分发到其他DAG处理
    
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

    # 从Variable中获取微信公众号账号列表
    account_list_str = Variable.get("WX_MP_ACCOUNT_LIST", default_var=None)
    if not account_list_str:
        print("错误：未找到名为 'WX_MP_ACCOUNT_LIST' 的Airflow Variable。")
        return

    try:
        account_list = json.loads(account_list_str)
    except json.JSONDecodeError:
        print("错误：'WX_MP_ACCOUNT_LIST' Variable中的JSON格式不正确。")
        return

    # 查找指定名称的账号信息
    # TODO: 后续这里的名称应该从message_data中的ToUserName动态获取
    target_account_name = "地产"
    target_account = next((acc for acc in account_list if acc.get('name') == target_account_name), None)

    if not target_account:
        print(f"错误：在 'WX_MP_ACCOUNT_LIST' 中未找到名称为 '{target_account_name}' 的账号。")
        return

    # 获取 appid 和 appsecret
    app_id = target_account.get('WX_MP_APP_ID')
    app_secret = target_account.get('WX_MP_SECRET')

    if not all([app_id, app_secret]):
        print(f"错误：名称为 '{target_account_name}' 的账号缺少 WX_MP_APP_ID 或 WX_MP_SECRET。")
        return

    # 获取用户信息(注意，微信公众号并未提供详细的用户消息）
    mp_bot = WeChatMPBot(appid=app_id, appsecret=app_secret)
    user_info = mp_bot.get_user_info(message_data.get('FromUserName'))
    print(f"FromUserName: {message_data.get('FromUserName')}, 用户信息: {user_info}")
        
    # 获取公众号账号信息
    wx_mp_account_info = get_mp_account_info(message_data.get('ToUserName'))
    # 将账号信息传递到xcom中供后续任务使用
    context['task_instance'].xcom_push(key='wx_mp_account_info', value=wx_mp_account_info)
    
    # 判断消息类型
    msg_type = message_data.get('MsgType')
    print(f"[WATCHER] 消息类型: {msg_type}")
    
    if msg_type == 'text':
        return ['handler_text_msg', 'save_msg_to_mysql']
    elif msg_type == 'image':
        return ['handler_image_msg']
    elif msg_type == 'voice':
        return ['handler_voice_msg', 'save_msg_to_mysql']
    elif msg_type == 'event':
        # 处理事件消息
        event_type = message_data.get('Event')
        print(f"[WATCHER] 收到事件类型: {event_type}")
        
        if event_type == 'subscribe':
            return ['handler_subscribe_event']
        else:
            print(f"[WATCHER] 不支持的事件类型: {event_type}")
            return []
    else:
        print(f"[WATCHER] 不支持的消息类型: {msg_type}")
        return []


def handler_text_msg(**context):
    """
    处理文本类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取微信公众号消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID
    create_time = message_data.get('CreateTime')  # 消息创建时间
    content = message_data.get('Content')  # 消息内容
    msg_id = message_data.get('MsgId')  # 消息ID
    
    print(f"收到来自 {from_user_name} 的消息: {content}")
    
    # 从Variable中获取微信公众号账号列表
    account_list_str = Variable.get("WX_MP_ACCOUNT_LIST", default_var=None)
    if not account_list_str:
        print("错误：未找到名为 'WX_MP_ACCOUNT_LIST' 的Airflow Variable。")
        return

    try:
        account_list = json.loads(account_list_str)
    except json.JSONDecodeError:
        print("错误：'WX_MP_ACCOUNT_LIST' Variable中的JSON格式不正确。")
        return

    # 查找指定名称的账号信息
    # TODO: 后续这里的名称应该从message_data中的ToUserName动态获取
    target_account_name = "地产"
    target_account = next((acc for acc in account_list if acc.get('name') == target_account_name), None)

    if not target_account:
        print(f"错误：在 'WX_MP_ACCOUNT_LIST' 中未找到名称为 '{target_account_name}' 的账号。")
        return

    print(f"[WATCHER] 找到名称为 '{target_account_name}' 的账号----: {target_account}")

    # 获取 appid 和 appsecret
    app_id = target_account.get('WX_MP_APP_ID')
    app_secret = target_account.get('WX_MP_SECRET')
    print("="*50)
    print(f"app_id: {app_id}")
    print(f"app_secret: {app_secret}")
    print("="*50)

    if not all([app_id, app_secret]):
        print(f"错误：名称为 '{target_account_name}' 的账号缺少 WX_MP_APP_ID 或 WX_MP_SECRET。")
        return

    # 初始化redis
    redis_handler = RedisHandler()

    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=app_id, appsecret=app_secret)
    
    # 初始化dify
    dify_api_key = target_account.get("WX_MP_DIFY_API_KEY")
    dify_base_url = Variable.get("DIFY_BASE_URL")
    print("="*50)
    print(f"dify_api_key: {dify_api_key}")
    print(f"dify_base_url: {dify_base_url}")
    print("="*50)
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_base_url)
    
    # 获取会话ID - 只在这里获取一次
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)
    print(f"[WATCHER] 获取到会话ID: {conversation_id}")
    
    # 更新消息列表
    redis_handler.append_msg_list(f'{from_user_name}_{to_user_name}_msg_list', message_data)
    
    # 缩短等待时间到3秒，给更多消息合并的机会
    time.sleep(5)

    # 重新获取消息列表前先检查是否需要提前停止
    should_pre_stop(message_data, from_user_name, to_user_name)
    
    # 读取消息列表
    room_msg_list = redis_handler.get_msg_list(f'{from_user_name}_{to_user_name}_msg_list')
    
    # 整合未回复的消息
    # 获取最近5条消息内容并合并
    question = "\n\n".join([msg.get('Content', '') for msg in room_msg_list[-5:]])
    

    
    print("-"*50)
    print(f"[WATCHER] 准备发送到Dify的问题:\n{question}")
    print("-"*50)

    # 检查是否有缓存的图片信息
    dify_files = []
    # online_img_info = Variable.get(f"mp_{from_user_name}_online_img_info", default_var={}, deserialize_json=True)
    # if online_img_info:
    #     print(f"[WATCHER] 发现缓存的图片信息: {online_img_info}")
    #     dify_files.append({
    #         "type": "image",
    #         "transfer_method": "remote_url",  # 修改为remote_url
    #         "url": online_img_info.get("url", ""),  # 使用Dify返回的URL
    #         "upload_file_id": online_img_info.get("id", "")
    #     })
            
    #     print(f"[WATCHER] 发现图片，修改后的问题: {question}")
        
    #     # 使用完图片信息后清除缓存
    #     try:
    #         Variable.delete(f"mp_{from_user_name}_online_img_info")
    #         print("[WATCHER] 已清除图片缓存")
    #     except Exception as e:
    #         print(f"[WATCHER] 清除图片缓存失败: {e}")
    # else:
    #     print("[WATCHER] 没有发现图片信息")

    # 在发送到Dify之前再次检查是否需要提前停止
    should_pre_stop(message_data, from_user_name, to_user_name)

    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=question,
        user_id=from_user_name,
        conversation_id=conversation_id,  # 使用之前获取的会话ID
    )
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer

    if not conversation_id:
        # 新会话，重命名会话
        try:
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, f"微信公众号用户_{from_user_name[:8]}", "公众号对话")
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")
        
        # 保存会话ID
        conversation_infos = Variable.get("wechat_mp_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[from_user_name] = conversation_id
        Variable.set("wechat_mp_conversation_infos", conversation_infos, serialize_json=True)

    # 发送回复消息时的智能处理
    for response_part in re.split(r'\\n\\n|\n\n', response):
        response_part = response_part.replace('\\n', '\n')
        mp_bot.send_text_message(from_user_name, response_part.strip())
    
    # 删除缓存的消息
    redis_handler.delete_msg_key(f'{from_user_name}_{to_user_name}_msg_list')

    # 将response缓存到xcom中供后续任务使用
    context['task_instance'].xcom_push(key='ai_reply_msg', value=response)
    context['task_instance'].xcom_push(key='token_usage_data', value=metadata)


def save_ai_reply_msg_to_db(**context):
    """
    保存AI回复的消息到MySQL
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 获取AI回复的消息
    ai_reply_msg = context.get('task_instance').xcom_pull(key='ai_reply_msg')
    
    # 提取消息信息
    save_msg = {}
    save_msg['from_user_id'] = message_data.get('ToUserName', '')  # AI回复时发送者是公众号
    save_msg['from_user_name'] = message_data.get('ToUserName', '')
    save_msg['to_user_id'] = message_data.get('FromUserName', '')  # 接收者是原消息发送者
    save_msg['to_user_name'] = message_data.get('FromUserName', '')
    save_msg['msg_id'] = f"ai_reply_{message_data.get('MsgId', '')}"  # 使用原消息ID加前缀作为回复消息ID
    save_msg['msg_type'] = 'text'
    save_msg['msg_type_name'] = WX_MSG_TYPES.get('text')
    save_msg['content'] = ai_reply_msg
    save_msg['msg_timestamp'] = int(time.time())
    save_msg['msg_datetime'] = datetime.now()
    
    # 使用相同的数据库连接函数保存AI回复
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db")
        db_conn = db_hook.get_hook().get_conn()
        cursor = db_conn.cursor()
        
        # 插入AI回复数据的SQL
        insert_sql = """INSERT INTO `wx_mp_chat_records` 
        (from_user_id, from_user_name, to_user_id, to_user_name, msg_id, 
        msg_type, msg_type_name, content, msg_timestamp, msg_datetime) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        content = VALUES(content),
        msg_type_name = VALUES(msg_type_name),
        updated_at = CURRENT_TIMESTAMP
        """
        
        # 执行插入
        cursor.execute(insert_sql, (
            save_msg['from_user_id'],
            save_msg['from_user_name'],
            save_msg['to_user_id'],
            save_msg['to_user_name'],
            save_msg['msg_id'],
            save_msg['msg_type'],
            save_msg['msg_type_name'],
            save_msg['content'],
            save_msg['msg_timestamp'],
            save_msg['msg_datetime']
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存AI回复消息到数据库: {save_msg['msg_id']}")
        
    except Exception as e:
        print(f"[DB_SAVE] 保存AI回复消息到数据库失败: {e}")
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



def save_msg_to_mysql(**context):
    """
    保存消息到MySQL
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 获取公众号账号信息
    wx_mp_account_info = context.get('task_instance').xcom_pull(key='wx_mp_account_info')
    
    # 提取消息信息 - 使用正确的微信消息字段
    from_user_name = message_data.get('FromUserName', '')  # 发送者的OpenID
    to_user_name = message_data.get('ToUserName', '')      # 接收者的OpenID
    msg_id = message_data.get('MsgId', '')                 # 消息ID
    msg_type = message_data.get('MsgType', '')             # 消息类型
    content = message_data.get('Content', '')              # 消息内容
    
    # 确保create_time是整数类型
    try:
        create_time = int(message_data.get('CreateTime', 0))  # 消息时间戳
    except (ValueError, TypeError):
        create_time = 0
        print("[DB_SAVE] CreateTime转换为整数失败，使用默认值0")
    
    # 根据消息类型处理content
    if msg_type == 'image':
        cos_path = context['task_instance'].xcom_pull(key='mp_image_cos_path')
        print(f"[DB_SAVE] 图片COS路径: {cos_path}")
        if cos_path:
            content = cos_path
        else:
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
    create_table_sql = """CREATE TABLE IF NOT EXISTS `wx_mp_chat_records` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `from_user_id` varchar(64) NOT NULL COMMENT '发送者ID',
        `from_user_name` varchar(128) DEFAULT NULL COMMENT '发送者名称',
        `to_user_id` varchar(128) DEFAULT NULL COMMENT '接收者ID',
        `to_user_name` varchar(128) DEFAULT NULL COMMENT '接收者名称',
        `msg_id` varchar(64) NOT NULL COMMENT '微信消息ID',        
        `msg_type` varchar(32) NOT NULL COMMENT '消息类型',  # 改为varchar类型
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
        KEY `idx_msg_datetime` (`msg_datetime`),
        KEY `idx_msg_type` (`msg_type`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信公众号聊天记录';
    """
    
    # 插入数据SQL - 确保字段名与表结构一致
    insert_sql = """INSERT INTO `wx_mp_chat_records` 
    (from_user_id, from_user_name, to_user_id, to_user_name, msg_id, 
    msg_type, msg_type_name, content, msg_timestamp, msg_datetime) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        
        # 先尝试修改表结构（如果需要）
        try:
            alter_sql = "ALTER TABLE `wx_mp_chat_records` MODIFY COLUMN `msg_type` varchar(32) NOT NULL COMMENT '消息类型';"
            cursor.execute(alter_sql)
            db_conn.commit()
            print("[DB_SAVE] 成功修改表结构")
        except Exception as e:
            print(f"[DB_SAVE] 修改表结构失败或表结构已经正确: {e}")
            db_conn.rollback()
        
        # 创建表（如果不存在）
        cursor.execute(create_table_sql)
        
        # 插入数据 - 确保参数顺序与SQL语句一致
        cursor.execute(insert_sql, (
            from_user_name,     # from_user_id
            from_user_name,     # from_user_name
            to_user_name,       # to_user_id
            to_user_name,       # to_user_name
            msg_id,             # msg_id
            msg_type,           # msg_type (现在是字符串类型)
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

def save_image_to_mysql(**context):
    """
    保存图片消息到MySQL
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 获取公众号账号信息
    wx_mp_account_info = context.get('task_instance').xcom_pull(key='wx_mp_account_info')
    # 获取COS路径
    cos_path = context.get('task_instance').xcom_pull(key='mp_image_cos_path')

    # 提取消息信息
    save_msg = {}
    save_msg['from_user_id'] = message_data.get('FromUserName', '')  # 发送者的OpenID
    save_msg['from_user_name'] = message_data.get('FromUserName', '')
    save_msg['to_user_id'] = message_data.get('ToUserName', '')      # 接收者的OpenID
    save_msg['to_user_name'] = message_data.get('ToUserName', '')
    save_msg['msg_id'] = message_data.get('MsgId', '')              # 消息ID
    save_msg['msg_type'] = 'image'                                  # 消息类型
    save_msg['msg_type_name'] = WX_MSG_TYPES.get('image')           # 消息类型名称
    save_msg['content'] = cos_path                                  # 使用COS路径作为内容
    save_msg['msg_timestamp'] = int(message_data.get('CreateTime', 0))  # 消息时间戳
    save_msg['msg_datetime'] = datetime.fromtimestamp(save_msg['msg_timestamp']) if save_msg['msg_timestamp'] > 0 else datetime.now()
    
    # 使用相同的数据库连接函数保存图片消息
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db")
        db_conn = db_hook.get_hook().get_conn()
        cursor = db_conn.cursor()
        
        # 插入图片消息的SQL
        insert_sql = """INSERT INTO `wx_mp_chat_records` 
        (from_user_id, from_user_name, to_user_id, to_user_name, msg_id, 
        msg_type, msg_type_name, content, msg_timestamp, msg_datetime) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        content = VALUES(content),
        msg_type_name = VALUES(msg_type_name),
        updated_at = CURRENT_TIMESTAMP
        """
        
        # 执行插入
        cursor.execute(insert_sql, (
            save_msg['from_user_id'],
            save_msg['from_user_name'],
            save_msg['to_user_id'],
            save_msg['to_user_name'],
            save_msg['msg_id'],
            save_msg['msg_type'],
            save_msg['msg_type_name'],
            save_msg['content'],
            save_msg['msg_timestamp'],
            save_msg['msg_datetime']
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存图片消息到数据库: {save_msg['msg_id']}")
        
    except Exception as e:
        print(f"[DB_SAVE] 保存图片消息到数据库失败: {e}")
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

def download_image_from_wechat_mp(access_token, media_id, save_path=None):
    """
    从微信公众号下载临时素材(图片)
    
    Args:
        access_token: 微信公众号access_token
        media_id: 媒体文件ID
        save_path: 图片保存路径(可选)，如果不指定则返回二进制内容
        
    Returns:
        如果save_path为None，返回图片二进制内容
        如果指定了save_path，返回保存的文件路径
        如果失败，返回None
    """
    url = f"https://api.weixin.qq.com/cgi-bin/media/get?access_token={access_token}&media_id={media_id}"
    
    try:
        response = requests.get(url, stream=True)
        
        # 检查响应状态
        if response.status_code != 200:
            print(f"[WX_MP] 下载图片失败，HTTP状态码: {response.status_code}")
            try:
                error_data = response.json()
                print(f"[WX_MP] 微信返回错误: {error_data}")
            except:
                print("[WX_MP] 无法解析错误响应")
            return None
        
        # 检查是否是有效的图片响应
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            print(f"[WX_MP] 无效的图片响应类型: {content_type}")
            return None
        
        # 获取文件内容
        image_data = response.content
        
        # 如果指定了保存路径
        if save_path:
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            print(f"[WX_MP] 图片已保存到: {save_path}")
            return save_path
        else:
            return image_data
            
    except Exception as e:
        print(f"[WX_MP] 下载图片异常: {e}")
        return None
    
def handler_image_msg(**context):
    """
    处理图片类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    
    处理流程:
    1. 接收用户发送的图片消息
    2. 下载图片文件并保存到临时目录
    3. 上传图片到Dify获取图片信息
    4. 将图片信息发送给Dify AI进行处理
    5. 获取AI回复并发送给用户
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取微信公众号消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID
    create_time = message_data.get('CreateTime')  # 消息创建时间
    pic_url = message_data.get('PicUrl')  # 图片链接
    media_id = message_data.get('MediaId')  # 图片消息媒体id
    msg_id = message_data.get('MsgId')  # 消息ID
    
    print(f"收到来自 {from_user_name} 的图片消息，MediaId: {media_id}, PicUrl: {pic_url}")
    
    # 从Variable中获取微信公众号账号列表
    account_list_str = Variable.get("WX_MP_ACCOUNT_LIST", default_var=None)
    if not account_list_str:
        print("错误：未找到名为 'WX_MP_ACCOUNT_LIST' 的Airflow Variable。")
        return

    try:
        account_list = json.loads(account_list_str)
    except json.JSONDecodeError:
        print("错误：'WX_MP_ACCOUNT_LIST' Variable中的JSON格式不正确。")
        return

    # 查找指定名称的账号信息
    # TODO: 后续这里的名称应该从message_data中的ToUserName动态获取
    target_account_name = "地产"
    target_account = next((acc for acc in account_list if acc.get('name') == target_account_name), None)

    if not target_account:
        print(f"错误：在 'WX_MP_ACCOUNT_LIST' 中未找到名称为 '{target_account_name}' 的账号。")
        return

    # 获取 appid 和 appsecret
    app_id = target_account.get('WX_MP_APP_ID')
    app_secret = target_account.get('WX_MP_SECRET')

    if not all([app_id, app_secret]):
        print(f"错误：名称为 '{target_account_name}' 的账号缺少 WX_MP_APP_ID 或 WX_MP_SECRET。")
        return

    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=app_id, appsecret=app_secret)
    access_token = mp_bot.get_access_token()
    
    # 初始化dify
    dify_api_key = Variable.get("WX_MP_DIFY_API_KEYS")
    dify_base_url = Variable.get("DIFY_BASE_URL")
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_base_url)
    
    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)
    print(f"[WATCHER] 获取到会话ID: {conversation_id}")
    
    # 创建临时目录用于保存下载的图片文件
    import tempfile
    import os
    from datetime import datetime
    
    temp_dir = tempfile.gettempdir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    image_file_path = os.path.join(temp_dir, f"wx_image_{from_user_name}_{timestamp}.jpg")
    
    try:
        # 1. 下载图片文件
        saved_path = download_image_from_wechat_mp(access_token, media_id, image_file_path)
        if not saved_path:
            raise Exception("下载图片失败")
        
        print(f"[WATCHER] 图片已保存到: {saved_path}")

        # 2. 上传图片到Dify
        dify_user_id = f"{from_user_name}_{to_user_name}_{conversation_id}"
        online_img_info = dify_agent.upload_file(saved_path, dify_user_id)
        print(f"[WATCHER] 上传图片到Dify成功: {online_img_info}")

         # 3. 上传图片到COS
        wx_mp_account_info = context['task_instance'].xcom_pull(key='wx_mp_account_info')
        mp_name = wx_mp_account_info.get('name', to_user_name)
        
        cos_path = upload_mp_image_to_cos(
            image_file_path=saved_path,
            mp_name=mp_name,
            to_user_name=to_user_name,
            from_user_name=from_user_name,
            context=context
        )
        print(f"[WATCHER] 图片已上传到COS: {cos_path}")
        
        # 修改判断条件，检查是否有有效的文件ID
        if not online_img_info or not online_img_info.get("id"):
            raise Exception("上传图片到Dify失败")
        
        # 4. 发送图片信息到Dify
        question = "我发送了一张图片，请分析图片内容并回复"
        # 修改文件参数，使用正确的transfer_method值
        dify_files = [{
            "type": "image",
            "transfer_method": "local_file",  # 改为使用local_file
            "upload_file_id": online_img_info.get("id")
        }]
        
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=question,
            user_id=from_user_name,
            conversation_id=conversation_id,
            files=dify_files,
            inputs={
                "platform": "wechat_mp",
                "user_id": from_user_name,
                "msg_id": msg_id,
                "is_image_msg": True
            }
        )
        print(f"full_answer: {full_answer}")
        print(f"metadata: {metadata}")
        response = full_answer
        
        # 处理会话ID相关逻辑
        if not conversation_id:
            # 新会话，重命名会话
            try:
                conversation_id = metadata.get("conversation_id")
                dify_agent.rename_conversation(conversation_id, f"微信公众号用户_{from_user_name[:8]}", "公众号图片对话")
            except Exception as e:
                print(f"[WATCHER] 重命名会话失败: {e}")
            
            # 保存会话ID
            conversation_infos = Variable.get("wechat_mp_conversation_infos", default_var={}, deserialize_json=True)
            conversation_infos[from_user_name] = conversation_id
            Variable.set("wechat_mp_conversation_infos", conversation_infos, serialize_json=True)
        
        # 4. 发送回复消息
        for response_part in re.split(r'\\n\\n|\n\n', response):
            response_part = response_part.replace('\\n', '\n')
            if response_part.strip():  # 确保不发送空消息
                mp_bot.send_text_message(from_user_name, response_part)
                time.sleep(0.5)  # 避免发送过快
        
        # 记录消息已被成功回复
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id, 
                user_id=from_user_name, 
                rating="like", 
                content="微信公众号图片消息自动回复成功"
            )
            
        # 将response缓存到xcom中供后续任务使用
        context['task_instance'].xcom_push(key='ai_reply_msg', value=response)
        
    except Exception as e:
        print(f"[WATCHER] 处理图片消息失败: {e}")
        # 发送错误提示给用户
        try:
            mp_bot.send_text_message(from_user_name, f"很抱歉，无法处理您的图片消息，发生了以下错误：{str(e)}")
        except Exception as send_error:
            print(f"[WATCHER] 发送错误提示失败: {send_error}")
    finally:
        # 清理临时文件
        try:
            if 'image_file_path' in locals() and image_file_path and os.path.exists(image_file_path):
                os.remove(image_file_path)
                print(f"[WATCHER] 临时图片文件已删除: {image_file_path}")
        except Exception as e:
            print(f"[WATCHER] 删除临时文件失败: {e}")
    return[ 'save_msg_to_mysql']
    

def handler_voice_msg(**context):
    """
    处理语音类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    
    处理流程:
    1. 接收用户发送的语音消息
    2. 下载语音文件并保存到临时目录
    3. 使用语音转文字API将语音内容转为文本
    4. 将转换后的文本发送给Dify AI进行处理
    5. 将AI回复的文本转换为语音（使用阿里云文字转语音）
    6. 上传语音到微信公众号获取media_id
    7. 发送语音回复给用户
    8. 同时发送文字回复作为备份
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取微信公众号消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID
    create_time = message_data.get('CreateTime')  # 消息创建时间
    media_id = message_data.get('MediaId')  # 语音消息媒体id
    format_type = message_data.get('Format')  # 语音格式，如amr，speex等
    msg_id = message_data.get('MsgId')  # 消息ID
    media_id_16k = message_data.get('MediaId16K')  # 16K采样率语音消息媒体id
    
    print(f"收到来自 {from_user_name} 的语音消息，MediaId: {media_id}, Format: {format_type}, MediaId16K: {media_id_16k}")
    
    # 从Variable中获取微信公众号账号列表
    account_list_str = Variable.get("WX_MP_ACCOUNT_LIST", default_var=None)
    if not account_list_str:
        print("错误：未找到名为 'WX_MP_ACCOUNT_LIST' 的Airflow Variable。")
        return

    try:
        account_list = json.loads(account_list_str)
    except json.JSONDecodeError:
        print("错误：'WX_MP_ACCOUNT_LIST' Variable中的JSON格式不正确。")
        return

    # 查找指定名称的账号信息
    # TODO: 后续这里的名称应该从message_data中的ToUserName动态获取
    target_account_name = "地产"
    target_account = next((acc for acc in account_list if acc.get('name') == target_account_name), None)

    if not target_account:
        print(f"错误：在 'WX_MP_ACCOUNT_LIST' 中未找到名称为 '{target_account_name}' 的账号。")
        return

    # 获取 appid 和 appsecret
    app_id = target_account.get('WX_MP_APP_ID')
    app_secret = target_account.get('WX_MP_SECRET')

    if not all([app_id, app_secret]):
        print(f"错误：名称为 '{target_account_name}' 的账号缺少 WX_MP_APP_ID 或 WX_MP_SECRET。")
        return

    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=app_id, appsecret=app_secret)
    
    # 初始化dify
    dify_api_key = Variable.get("WX_MP_DIFY_API_KEYS")
    dify_base_url = Variable.get("DIFY_BASE_URL")
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_base_url)
    
    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)
    
    # 创建临时目录用于保存下载的语音文件
    import tempfile
    import os
    from datetime import datetime
    
    temp_dir = tempfile.gettempdir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # 优先使用16K采样率的语音(如果有)
    voice_media_id = media_id_16k if media_id_16k else media_id
    voice_file_path = os.path.join(temp_dir, f"wx_voice_{from_user_name}_{timestamp}.{format_type.lower()}")
    
    try:
        # 1. 下载语音文件
        mp_bot.download_temporary_media(voice_media_id, voice_file_path)
        print(f"[WATCHER] 语音文件已保存到: {voice_file_path}")
        
        # 2. 语音转文字
        try:
            # 转换音频格式 - 如果是AMR格式，转换为WAV格式
            converted_file_path = None
            if format_type.lower() == 'amr':                
                # 创建转换后的文件路径
                converted_file_path = os.path.join(temp_dir, f"wx_voice_{from_user_name}_{timestamp}.wav")
                
                # 进行格式转换
                print(f"[WATCHER] 正在将AMR格式转换为WAV格式...")
                sound = AudioSegment.from_file(voice_file_path, format="amr")
                sound.export(converted_file_path, format="wav")
                print(f"[WATCHER] 音频格式转换成功，WAV文件保存在: {converted_file_path}")
                
            # 使用可能转换过的文件路径进行语音转文字
            file_to_use = converted_file_path if converted_file_path else voice_file_path
            print(f"[WATCHER] 用于语音转文字的文件: {file_to_use}")
            
            transcribed_text = dify_agent.audio_to_text(file_to_use)
            print(f"[WATCHER] 语音转文字结果: {transcribed_text}")
            
            if not transcribed_text.strip():
                raise Exception("语音转文字结果为空")
        except Exception as e:
            print(f"[WATCHER] 语音转文字失败: {e}")
            # 如果语音转文字失败，使用默认文本
            transcribed_text = "您发送了一条语音消息，但我无法识别内容。请问您想表达什么？"
        
        # 3. 发送转写的文本到Dify
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=transcribed_text,  # 使用转写的文本
            user_id=from_user_name,
            conversation_id=conversation_id,
            inputs={
                "platform": "wechat_mp",
                "user_id": from_user_name,
                "msg_id": msg_id,
                "is_voice_msg": True,
                "transcribed_text": transcribed_text
            }
        )
        print(f"full_answer: {full_answer}")
        print(f"metadata: {metadata}")
        response = full_answer
        context['task_instance'].xcom_push(key='token_usage_data', value=metadata)

        # 处理会话ID相关逻辑
        if not conversation_id:
            # 新会话，重命名会话
            try:
                conversation_id = metadata.get("conversation_id")
                dify_agent.rename_conversation(conversation_id, f"微信公众号用户_{from_user_name[:8]}", "公众号语音对话")
            except Exception as e:
                print(f"[WATCHER] 重命名会话失败: {e}")
            
            # 保存会话ID
            conversation_infos = Variable.get("wechat_mp_conversation_infos", default_var={}, deserialize_json=True)
            conversation_infos[from_user_name] = conversation_id
            Variable.set("wechat_mp_conversation_infos", conversation_infos, serialize_json=True)
        
        # 4. 使用阿里云的文字转语音功能
        audio_response_path = os.path.join(temp_dir, f"wx_audio_response_{from_user_name}_{timestamp}.mp3")
        try:
            # 调用阿里云的TTS服务 - 直接生成MP3格式
            success, _ = text_to_speech(
                text=response, 
                output_path=audio_response_path, 
                model="cosyvoice-v2", 
                voice="longxiaoxia_v2"
            )
            
            if not success:
                raise Exception("文字转语音失败")
                
            print(f"[WATCHER] 文字转语音成功，保存到: {audio_response_path}")
            
            # 5. 上传语音文件到微信获取media_id
            upload_result = mp_bot.upload_temporary_media("voice", audio_response_path)
            response_media_id = upload_result.get('media_id')
            print(f"[WATCHER] 语音文件上传成功，media_id: {response_media_id}")
            
            # 6. 发送语音回复
            mp_bot.send_voice_message(from_user_name, response_media_id)
            print(f"[WATCHER] 语音回复发送成功")
            
            # 语音回复成功，不需要发送文字回复
            send_text_response = False
                
        except Exception as e:
            print(f"[WATCHER] 语音回复失败: {e}")
            send_text_response = True
        
        # 只有在语音回复失败时才发送文字回复
        if send_text_response:
            try:
                # 将长回复拆分成多条消息发送
                for response_part in re.split(r'\\n\\n|\n\n', response):
                    response_part = response_part.replace('\\n', '\n')
                    if response_part.strip():  # 确保不发送空消息
                        mp_bot.send_text_message(from_user_name, response_part)
                        time.sleep(0.5)  # 避免发送过快
                        
                print(f"[WATCHER] 文字回复发送成功")
            except Exception as text_error:
                print(f"[WATCHER] 文字回复发送失败: {text_error}")
        
        # 记录消息已被成功回复
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id, 
                user_id=from_user_name, 
                rating="like", 
                content="微信公众号语音消息自动回复成功"
            )
    except Exception as e:
        print(f"[WATCHER] 处理语音消息失败: {e}")
        # 发送错误提示给用户
        try:
            mp_bot.send_text_message(from_user_name, f"很抱歉，无法处理您的语音消息，发生了以下错误：{str(e)}")
        except Exception as send_error:
            print(f"[WATCHER] 发送错误提示失败: {send_error}")
    finally:
        # 清理临时文件
        try:
            # 定义需要清理的所有临时文件
            temp_files = []
            if 'voice_file_path' in locals() and voice_file_path:
                temp_files.append(voice_file_path)
            if 'audio_response_path' in locals() and audio_response_path:
                temp_files.append(audio_response_path)
            if 'converted_file_path' in locals() and converted_file_path:
                temp_files.append(converted_file_path)
            
            # 删除所有临时文件
            for file_path in temp_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[WATCHER] 临时文件已删除: {file_path}")
        except Exception as e:
            print(f"[WATCHER] 删除临时文件失败: {e}")


def handler_file_msg(**context):
    """
    处理文件类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    """
    # TODO(claude89757): 处理文件类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    pass


def handler_subscribe_event(**context):
    """
    处理用户关注公众号事件，发送欢迎消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取微信公众号消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID (新关注用户)
    create_time = message_data.get('CreateTime')  # 消息创建时间
    event = message_data.get('Event')  # 事件类型 (subscribe)
    
    print(f"[SUBSCRIBE] 收到用户 {from_user_name} 关注事件")
    
    # 获取公众号账号信息
    wx_mp_account_info = context.get('task_instance').xcom_pull(key='wx_mp_account_info')
    print(f"[SUBSCRIBE] 公众号信息: {wx_mp_account_info}")
    
    # 创建微信公众号机器人实例
    mp_bot = WeChatMPBot(appid=Variable.get("WX_MP_APP_ID"), appsecret=Variable.get("WX_MP_SECRET"))
    
    # 欢迎消息
    welcome_message = "欢迎关注lucyai，我是医美小助手小希，您可以给我发送信息，我24小时都在线回复您～"
    
    try:
        # 发送欢迎消息
        print(f"[SUBSCRIBE] 发送欢迎消息给用户 {from_user_name}: {welcome_message}")
        mp_bot.send_text_message(from_user_name, welcome_message)
        print(f"[SUBSCRIBE] 成功发送欢迎消息")
        return True
    except Exception as e:
        print(f"[SUBSCRIBE] 发送欢迎消息失败: {e}")
        return False


def should_pre_stop(current_message, from_user_name, to_user_name):
    """
    检查是否需要提前停止流程
    """
    # 获取用户最近的消息列表
    redis_handler = RedisHandler()
    room_msg_list = redis_handler.get_msg_list(f'{from_user_name}_{to_user_name}_msg_list')
    if not room_msg_list:
        return
    
    if current_message['MsgId'] != room_msg_list[-1]['MsgId']:
        print(f"[PRE_STOP] 最新消息id不一致，停止流程执行")
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else:
        print(f"[PRE_STOP] 最新消息id一致，继续执行")


def save_token_usage(**context):
    """
    保存token用量到DB
    """
    message_data = context.get('dag_run').conf

    # 获取token用量信息
    token_usage_data = context.get('task_instance').xcom_pull(key='token_usage_data')

    if not token_usage_data:
        print("[WATCHER] 没有收到token用量信息")
        return

    # 提取token信息
    msg_id = token_usage_data.get('message_id', '')
    prompt_tokens = str(token_usage_data.get('metadata', {}).get('usage', {}).get('prompt_tokens', ''))
    prompt_unit_price = token_usage_data.get('metadata', {}).get('usage', {}).get('prompt_unit_price', '')
    prompt_price_unit = token_usage_data.get('metadata', {}).get('usage', {}).get('prompt_price_unit', '')
    prompt_price = token_usage_data.get('metadata', {}).get('usage', {}).get('prompt_price', '')
    completion_tokens = str(token_usage_data.get('metadata', {}).get('usage', {}).get('completion_tokens', ''))
    completion_unit_price = token_usage_data.get('metadata', {}).get('usage', {}).get('completion_unit_price', '')
    completion_price_unit = token_usage_data.get('metadata', {}).get('usage', {}).get('completion_price_unit', '')
    completion_price = token_usage_data.get('metadata', {}).get('usage', {}).get('completion_price', '')
    total_tokens = str(token_usage_data.get('metadata', {}).get('usage', {}).get('total_tokens', ''))
    total_price = token_usage_data.get('metadata', {}).get('usage', {}).get('total_price', '')
    currency = token_usage_data.get('metadata', {}).get('usage', {}).get('currency', '')

    save_token_usage_data = {}
    save_token_usage_data['token_source_platform'] = 'wx_mp_chat'
    save_token_usage_data['msg_id'] = msg_id
    save_token_usage_data['prompt_tokens'] = prompt_tokens
    save_token_usage_data['prompt_unit_price'] = prompt_unit_price
    save_token_usage_data['prompt_price_unit'] = prompt_price_unit
    save_token_usage_data['prompt_price'] = prompt_price
    save_token_usage_data['completion_tokens'] = completion_tokens
    save_token_usage_data['completion_unit_price'] = completion_unit_price
    save_token_usage_data['completion_price_unit'] = completion_price_unit
    save_token_usage_data['completion_price'] = completion_price
    save_token_usage_data['total_tokens'] = total_tokens
    save_token_usage_data['total_price'] = total_price
    save_token_usage_data['currency'] = currency
    save_token_usage_data['source_ip'] = message_data.get('source_ip', '')

    wx_mp_account_info = context.get('task_instance').xcom_pull(key='wx_mp_account_info')
    save_token_usage_data['wx_user_id'] = wx_mp_account_info.get('gh_user_id', '')
    save_token_usage_data['wx_user_name'] = wx_mp_account_info.get('name', '')
    save_token_usage_data['room_id'] = message_data.get('FromUserName', '')
    save_token_usage_data['room_name'] = message_data.get('FromUserName', '')


    # 保存token用量到DB
    save_token_usage_to_db(save_token_usage_data)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['微信公众号'],
    description='微信公众号消息监控',
)

# 创建处理消息的任务
process_message_task = BranchPythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 创建处理文本消息的任务
handler_text_msg_task = PythonOperator(
    task_id='handler_text_msg',
    python_callable=handler_text_msg,
    provide_context=True,
    dag=dag
)

# 创建处理图片消息的任务
handler_image_msg_task = PythonOperator(
    task_id='handler_image_msg',
    python_callable=handler_image_msg,
    provide_context=True,
    dag=dag
)

# 创建处理语音消息的任务
handler_voice_msg_task = PythonOperator(
    task_id='handler_voice_msg',
    python_callable=handler_voice_msg,
    provide_context=True,
    dag=dag
)

# 创建处理关注事件的任务
handler_subscribe_event_task = PythonOperator(
    task_id='handler_subscribe_event',
    python_callable=handler_subscribe_event,
    provide_context=True,
    dag=dag
)

# 创建保存消息到MySQL的任务
save_msg_to_mysql_task = PythonOperator(
    task_id='save_msg_to_mysql',
    python_callable=save_msg_to_mysql,
    provide_context=True,
    dag=dag
)

# 创建保存图片到MySQL的任务
save_image_to_mysql_task = PythonOperator(
    task_id='save_image_to_mysql',
    python_callable=save_image_to_mysql,
    provide_context=True,
    dag=dag
)

# 保存AI回复的消息到数据库
save_ai_reply_msg_task = PythonOperator(
    task_id='save_ai_reply_msg_to_db',
    python_callable=save_ai_reply_msg_to_db,
    provide_context=True,
    dag=dag
)

# 保存token用量到数据库
save_token_usage_task = PythonOperator(
    task_id='save_token_usage',
    python_callable=save_token_usage,
    provide_context=True,
    trigger_rule='one_success', 
    dag=dag
)


# 设置任务依赖关系
process_message_task >> [handler_text_msg_task, handler_image_msg_task, handler_voice_msg_task, handler_subscribe_event_task, save_msg_to_mysql_task]
handler_text_msg_task >> save_ai_reply_msg_task >> save_token_usage_task
handler_image_msg_task >> save_image_to_mysql_task
handler_voice_msg_task >> save_token_usage_task
