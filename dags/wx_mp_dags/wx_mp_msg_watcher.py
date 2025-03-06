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
from utils.redis import RedisLock
from utils.wechat_mp_channl import WeChatMPBot
from utils.tts import text_to_speech


DAG_ID = "wx_mp_msg_watcher"

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

    # 获取用户信息(注意，微信公众号并未提供详细的用户消息）
    mp_bot = WeChatMPBot(appid=Variable.get("WX_MP_APP_ID"), appsecret=Variable.get("WX_MP_SECRET"))
    user_info = mp_bot.get_user_info(message_data.get('FromUserName'))
    print(f"FromUserName: {message_data.get('FromUserName')}, 用户信息: {user_info}")
    # user_info = mp_bot.get_user_info(message_data.get('ToUserName'))
    # print(f"ToUserName: {message_data.get('ToUserName')}, 用户信息: {user_info}")
    
    
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
    
    # 将当前消息添加到缓存列表
    room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
    current_msg = {
        'ToUserName': to_user_name,
        'FromUserName': from_user_name,
        'CreateTime': create_time,
        'Content': content,
        'MsgId': msg_id,
        'is_reply': False,
        'processing': False
    }
    room_msg_list.append(current_msg)
    Variable.set(f'mp_{from_user_name}_msg_list', room_msg_list[-100:], serialize_json=True)
    
    # 缩短等待时间到3秒
    time.sleep(5)

    # 重新获取消息列表(可能有新消息加入)
    room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
    
    # 获取需要处理的消息组
    current_time = int(time.time())
    up_for_reply_msg_content_list = []
    up_for_reply_msg_id_list = []
    
    # 按时间排序消息，只看最近10条消息
    sorted_msgs = sorted(room_msg_list[-10:], key=lambda x: int(x.get('CreateTime', 0)))
    
    # 找到最后一条已回复消息的时间
    last_replied_time = 0
    for msg in reversed(sorted_msgs):
        if msg.get('is_reply'):
            last_replied_time = int(msg.get('CreateTime', 0))
            break
    
    # 收集需要回复的消息
    first_unreplied_time = None
    latest_msg_time = 0
    
    for msg in sorted_msgs:
        msg_time = int(msg.get('CreateTime', 0))
        latest_msg_time = max(latest_msg_time, msg_time)
        
        # 只处理最后一条已回复消息之后的消息
        if msg_time <= last_replied_time:
            continue
            
        # 跳过正在处理的消息
        if msg.get('processing'):
            continue
            
        if not msg.get('is_reply'):
            if first_unreplied_time is None:
                first_unreplied_time = msg_time
            
            # 优化聚合判断逻辑：
            # 1. 消息时间在第一条未回复消息5秒内
            # 2. 消息时间在当前时间5秒内
            content = msg.get('Content', '').lower()
            is_question = any(q in content for q in ['?', '？', '吗', '什么', '如何', '为什么', '怎么'])
            
            if ((msg_time - first_unreplied_time) <= 5 or  # 缩短时间窗口到5秒
                (current_time - msg_time) <= 5):           # 缩短最新消息判断时间到5秒
                up_for_reply_msg_content_list.append(msg.get('Content', ''))
                up_for_reply_msg_id_list.append(msg.get('MsgId'))

    if not up_for_reply_msg_content_list:
        print("[WATCHER] 没有需要回复的消息")
        return
        
    # 检查当前消息是否是最新的未回复消息，缩短检查时间到5秒
    current_msg_time = int(message_data.get('CreateTime', 0))
    if current_msg_time < latest_msg_time and (latest_msg_time - current_msg_time) > 5:
        print(f"[WATCHER] 发现更新的消息，当前消息时间: {current_msg_time}，最新消息时间: {latest_msg_time}")
        return

    # 标记消息为处理中状态
    room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
    for msg in room_msg_list:
        if msg['MsgId'] in up_for_reply_msg_id_list:
            msg['processing'] = True
    Variable.set(f'mp_{from_user_name}_msg_list', room_msg_list, serialize_json=True)
    
    # 获取微信公众号配置和初始化客户端
    appid = Variable.get("WX_MP_APP_ID", default_var="")
    appsecret = Variable.get("WX_MP_SECRET", default_var="")
    
    if not appid or not appsecret:
        print("[WATCHER] 微信公众号配置缺失")
        return
    
    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=appid, appsecret=appsecret)
    
    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("LUCYAI_DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)

    # 整合未回复的消息，添加序号
    questions = []
    for i, content in enumerate(up_for_reply_msg_content_list, 1):
        if len(up_for_reply_msg_content_list) > 1:
            questions.append(f"问题{i}：{content}")
        else:
            questions.append(content)
    
    question = "\n\n".join(questions)
    
    # 如果是多个问题，添加提示语
    if len(up_for_reply_msg_content_list) > 1:
        question = f"请帮我回答以下{len(up_for_reply_msg_content_list)}个问题：\n\n{question}"

    print("-"*50)
    print(f"合并后的问题:\n{question}")
    print("-"*50)

    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=question,
        user_id=from_user_name,
        conversation_id=conversation_id,
        inputs={
            "platform": "wechat_mp",
            "user_id": from_user_name,
            "msg_id": msg_id,
            "is_batch_questions": len(up_for_reply_msg_content_list) > 1,
            "question_count": len(up_for_reply_msg_content_list)
        }
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
    try:
        # 判断是否需要分段发送
        need_split = False
        
        # 1. 检查是否有明显的分点标记
        point_markers = ['1.', '2.', '3.','4.','5.','6.','7.','8.','9.', '①', '②', '③', 
                        '一、', '二、', '三、','四、','五、','六、','七、','八、','九、',
                        '\n1.', '\n2.', '\n3.','\n4.', '\n5.', '\n6.','\n7.', '\n8.', '\n9.',
                        '\n一、', '\n二、', '\n三、','\n四、','\n五、','\n六、','\n七、','\n八、','\n九、']
        if any(marker in response for marker in point_markers):
            need_split = True
            
        # 2. 检查是否有明显的段落分隔
        if response.count('\n\n') > 2:  # 有超过2个空行分隔的段落
            need_split = True
            
        # 3. 检查单段长度
        if len(response) > 500:  # 单段超过500字符
            need_split = True
            
        # 4. 检查是否是多个问题的回答
        if len(up_for_reply_msg_content_list) > 3:
            need_split = True

        if need_split:
            # 分段发送逻辑
            # 1. 首先尝试按问题分割
            if len(up_for_reply_msg_content_list) > 1:
                # 多个问题的情况，查找每个问题的答案
                segments = []
                current_question = 1
                for line in response.split('\n'):
                    if f"问题{current_question}" in line:
                        segments.append([line])
                        current_question += 1
                    elif segments:
                        segments[-1].append(line)
                
                # 发送每个问题的答案
                for i, segment in enumerate(segments, 1):
                    msg = f"问题 {i}/{len(segments)}:\n" + '\n'.join(segment).strip()
                    if msg.strip():
                        mp_bot.send_text_message(from_user_name, msg)
                        time.sleep(0.2)
            else:
                # 2. 按分点标记分割
                has_points = False
                for marker in ['1.', '一、', '①','\n\n']:
                    if marker in response:
                        has_points = True
                        segments = []
                        current_segment = []
                        
                        for line in response.split('\n'):
                            if any(line.strip().startswith(m) for m in point_markers):
                                if current_segment:
                                    segments.append('\n'.join(current_segment))
                                current_segment = [line]
                            else:
                                current_segment.append(line)
                        
                        if current_segment:
                            segments.append('\n'.join(current_segment))
                        
                        # 发送每个分点
                        for i, segment in enumerate(segments, 1):
                            msg = f"{segment.strip()}"
                            if msg.strip():
                                mp_bot.send_text_message(from_user_name, msg)
                                time.sleep(0.2)
                        break
                
                # 3. 如果没有分点，按段落分割
                if not has_points:
                    paragraphs = [p for p in re.split(r'\n\n+', response) if p.strip()]
                    if len(paragraphs) > 1:
                        for i, paragraph in enumerate(paragraphs, 1):
                            msg = f"({paragraph.strip()}"
                            if msg.strip():
                                mp_bot.send_text_message(from_user_name, msg)
                                time.sleep(0.2)
                    else:
                        # 4. 如果是单个长段落，按句子分割
                        sentences = re.split(r'([。！？])', response)
                        current_msg = ""
                        for i in range(0, len(sentences)-1, 2):
                            sentence = sentences[i] + (sentences[i+1] if i+1 < len(sentences) else '')
                            if len(current_msg) + len(sentence) > 300:
                                if current_msg.strip():
                                    mp_bot.send_text_message(from_user_name, current_msg.strip())
                                    time.sleep(0.2)
                                current_msg = sentence
                            else:
                                current_msg += sentence
                        
                        if current_msg.strip():
                            mp_bot.send_text_message(from_user_name, current_msg.strip())
        else:
            # 内容较短或结构简单，直接发送
            if response.strip():
                mp_bot.send_text_message(from_user_name, response.strip())
        
        # 标记消息为已回复状态
        room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
        for msg in room_msg_list:
            if msg['MsgId'] in up_for_reply_msg_id_list:
                msg['is_reply'] = True
                msg['processing'] = False
                msg['reply_time'] = int(time.time())
                msg['batch_reply'] = True if len(up_for_reply_msg_id_list) > 1 else False
                msg['reply_content'] = response
        Variable.set(f'mp_{from_user_name}_msg_list', room_msg_list, serialize_json=True)

        # 记录消息已被成功回复
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id,
                user_id=from_user_name,
                rating="like",
                content="微信公众号自动回复成功"
            )

        # 将response缓存到xcom中供后续任务使用
        context['task_instance'].xcom_push(key='ai_reply_msg', value=response)

    except Exception as error:
        # 发生错误时，清除处理中状态
        try:
            room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
            for msg in room_msg_list:
                if msg['MsgId'] in up_for_reply_msg_id_list:
                    msg['processing'] = False
            Variable.set(f'mp_{from_user_name}_msg_list', room_msg_list, serialize_json=True)
        except:
            pass
            
        print(f"[WATCHER] 发送消息失败: {error}")
        # 记录消息回复失败
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id,
                user_id=from_user_name,
                rating="dislike",
                content=f"微信公众号自动回复失败, {error}"
            )


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
    if not message_data:
        print("[DB_SAVE] 没有收到消息数据")
        return
    
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


def handler_image_msg(**context):
    """
    处理图片类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
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
    
    # 获取微信公众号配置
    appid = Variable.get("WX_MP_APP_ID", default_var="")
    appsecret = Variable.get("WX_MP_SECRET", default_var="")
    
    if not appid or not appsecret:
        print("[WATCHER] 微信公众号配置缺失")
        return
    
    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=appid, appsecret=appsecret)
    
    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("LUCYAI_DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)
    
    # 创建临时目录用于保存下载的图片
    import tempfile
    import os
    from datetime import datetime
    
    temp_dir = tempfile.gettempdir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    img_file_path = os.path.join(temp_dir, f"wx_mp_img_{from_user_name}_{timestamp}.jpg")
    
    try:
        # 下载图片
        if pic_url:
            # 如果有直接的图片URL，使用URL下载
            img_response = requests.get(pic_url)
            with open(img_file_path, 'wb') as img_file:
                img_file.write(img_response.content)
        else:
            # 否则使用media_id获取临时素材
            mp_bot.download_temporary_media(media_id, img_file_path)
        
        print(f"[WATCHER] 图片已保存到: {img_file_path}")
        
        # 将图片本地路径传递到xcom中供后续任务使用
        context['task_instance'].xcom_push(key='image_local_path', value=img_file_path)
        
        # 上传图片到Dify
        try:
            online_img_info = dify_agent.upload_file(img_file_path, from_user_name)
            print(f"[WATCHER] 上传图片到Dify成功: {online_img_info}")
            
            if not online_img_info or 'id' not in online_img_info:
                raise Exception("上传图片失败：未获取到有效的文件ID")
                
            # 准备问题内容 - 使用更专业的提示语
            query = """请分析这张图片，重点关注以下几个方面：
1. 如果是皮肤相关图片，请分析皮肤状况，包括敏感、泛红、痘痘等问题
2. 如果是产品图片，请识别产品类型和特点
3. 如果是其他类型图片，请简要描述内容

请用专业且友好的语气回复，如果无法看清图片或需要更多信息，请礼貌地询问用户。"""
            
            # 获取AI回复（带有图片分析）
            full_answer, metadata = dify_agent.create_chat_message_stream(
                query=query,
                user_id=from_user_name,
                conversation_id=conversation_id,
                inputs={
                    "platform": "wechat_mp",
                    "user_id": from_user_name,
                    "msg_id": msg_id,
                    "image_analysis": True,
                    "analysis_type": "beauty_consultation"  # 添加分析类型标记
                },
                files=[{
                    "type": "image",
                    "transfer_method": "remote_url",  # 使用remote_url方式
                    "url": pic_url if pic_url else "",  # 优先使用直接URL
                    "upload_file_id": online_img_info.get("id", ""),  # 同时提供上传的文件ID
                    "format": "png"
                }]
            )
            
            if not full_answer or full_answer.strip() == "":
                # 如果AI无法生成有效回复，使用默认的友好回复
                response = """感谢您发送的图片~
                
我需要更多信息来为您提供专业的建议呢。您可以告诉我：

1. 您目前遇到的具体问题（比如敏感、泛红等）
2. 想要改善的方面（如提亮肤色、改善痘痘等）
3. 是否有特殊的肤质情况

这样我就能为您推荐最适合的护理方案和产品啦！😊"""
            else:
                response = full_answer
                
            print(f"full_answer: {full_answer}")
            print(f"metadata: {metadata}")
            
        except Exception as upload_error:
            print(f"[WATCHER] 图片处理失败: {upload_error}")
            # 当图片处理失败时，返回友好的提示信息
            response = """抱歉没能看清图片呢~ 

您可以重新发送图片，或者直接告诉我：
1. 您的肤质类型
2. 目前遇到的护肤困扰
3. 想要改善的问题

我会根据您的描述提供专业的护理建议！💝"""

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
        
        # 发送回复消息
        try:
            # 将长回复拆分成多条消息发送，保持格式美观
            response_parts = re.split(r'\\n\\n|\n\n', response)
            for i, response_part in enumerate(response_parts):
                response_part = response_part.replace('\\n', '\n').strip()
                if response_part:
                    # 为第一条消息添加问候语
                    if i == 0:
                        response_part = f"亲爱的，{response_part}"
                    mp_bot.send_text_message(from_user_name, response_part)
                    time.sleep(0.5)  # 避免发送过快
            
            # 记录消息已被成功回复
            if metadata and 'message_id' in metadata:
                dify_msg_id = metadata.get("message_id")
                dify_agent.create_message_feedback(
                    message_id=dify_msg_id, 
                    user_id=from_user_name, 
                    rating="like", 
                    content="微信公众号图片消息自动回复成功"
                )

            # 将response缓存到xcom中供后续任务使用
            context['task_instance'].xcom_push(key='ai_reply_msg', value=response)

        except Exception as error:
            print(f"[WATCHER] 发送消息失败: {error}")
            if metadata and 'message_id' in metadata:
                dify_msg_id = metadata.get("message_id")
                dify_agent.create_message_feedback(
                    message_id=dify_msg_id, 
                    user_id=from_user_name, 
                    rating="dislike", 
                    content=f"微信公众号图片消息自动回复失败, {error}"
                )
    except Exception as e:
        print(f"[WATCHER] 处理图片消息失败: {e}")
        # 发送友好的错误提示
        try:
            mp_bot.send_text_message(from_user_name, """抱歉出现了一点小问题呢~ 

您可以：
1. 稍后重新发送图片
2. 直接描述您的护肤需求
3. 告诉我想要改善的问题

我会竭诚为您服务！🌟""")
        except Exception as send_error:
            print(f"[WATCHER] 发送错误提示失败: {send_error}")
    finally:
        # 清理临时文件
        try:
            if os.path.exists(img_file_path):
                os.remove(img_file_path)
                print(f"[WATCHER] 临时图片文件已删除: {img_file_path}")
        except Exception as e:
            print(f"[WATCHER] 删除临时文件失败: {e}")


def save_image_to_db(**context):
    """
    保存图片消息到MySQL
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 获取图片本地路径
    image_local_path = context.get('task_instance').xcom_pull(key='image_local_path')
    
    # 提取消息信息
    save_msg = {}
    save_msg['from_user_id'] = message_data.get('FromUserName', '')  # 发送者的OpenID
    save_msg['from_user_name'] = message_data.get('FromUserName', '')
    save_msg['to_user_id'] = message_data.get('ToUserName', '')  # 公众号原始ID
    save_msg['to_user_name'] = message_data.get('ToUserName', '')
    save_msg['msg_id'] = message_data.get('MsgId', '')
    save_msg['msg_type'] = 'image'
    save_msg['msg_type_name'] = WX_MSG_TYPES.get('image')
    save_msg['content'] = f"[图片] URL: {message_data.get('PicUrl', '')}\nMediaId: {message_data.get('MediaId', '')}"
    save_msg['msg_timestamp'] = int(message_data.get('CreateTime', time.time()))
    save_msg['msg_datetime'] = datetime.fromtimestamp(save_msg['msg_timestamp'])
    
    # 使用相同的数据库连接函数保存图片消息
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db")
        db_conn = db_hook.get_hook().get_conn()
        cursor = db_conn.cursor()
        
        # 插入数据的SQL
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
    
    # 获取微信公众号配置
    appid = Variable.get("WX_MP_APP_ID", default_var="")
    appsecret = Variable.get("WX_MP_SECRET", default_var="")
    
    if not appid or not appsecret:
        print("[WATCHER] 微信公众号配置缺失")
        return
    
    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=appid, appsecret=appsecret)
    
    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("LUCYAI_DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))
    
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


def should_pre_stop(current_message, from_user_name):
    """
    检查是否需要提前停止流程
    """
    # 获取用户最近的消息列表
    room_msg_list = Variable.get(f'mp_{from_user_name}_msg_list', default_var=[], deserialize_json=True)
    if not room_msg_list:
        return
    
    # 获取最新消息的时间戳
    try:
        latest_msg_time = int(room_msg_list[-1].get('CreateTime', 0))
    except (ValueError, TypeError):
        latest_msg_time = int(time.time())
        print(f"[PRE_STOP] 最新消息时间戳转换失败: {room_msg_list[-1].get('CreateTime')}")
    
    try:
        current_msg_time = int(current_message.get('CreateTime', 0))
    except (ValueError, TypeError):
        current_msg_time = int(time.time())
        print(f"[PRE_STOP] 当前消息时间戳转换失败: {current_message.get('CreateTime')}")
    
    # 如果当前消息不是最新消息，且时间差超过5秒，则停止处理
    if current_msg_time < latest_msg_time and (latest_msg_time - current_msg_time) > 5:
        print(f"[PRE_STOP] 发现更新的消息，当前消息时间: {current_msg_time}，最新消息时间: {latest_msg_time}")
        raise AirflowException("检测到更新消息，停止当前处理")
    
    print(f"[PRE_STOP] 消息时间检查通过，继续执行")


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

# 创建保存消息到MySQL的任务
save_msg_to_mysql_task = PythonOperator(
    task_id='save_msg_to_mysql',
    python_callable=save_msg_to_mysql,
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

# 保存图片消息到数据库
save_image_to_db_task = PythonOperator(
    task_id='save_image_to_db',
    python_callable=save_image_to_db,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系
process_message_task >> [handler_text_msg_task, handler_image_msg_task, handler_voice_msg_task, save_msg_to_mysql_task]
handler_text_msg_task >> save_ai_reply_msg_task
handler_image_msg_task >> [save_image_to_db_task, save_ai_reply_msg_task]
