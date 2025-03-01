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

# Airflow相关导入
from airflow import DAG
from airflow.api.common.trigger_dag import trigger_dag
from airflow.exceptions import AirflowException
from airflow.models import DagRun
from airflow.models.dagrun import DagRun
from airflow.models.variable import Variable
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.redis import RedisLock
from utils.wechat_mp_channl import WeChatMPBot


DAG_ID = "wx_mp_msg_watcher"


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
    
    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=content,
        user_id=from_user_name,
        conversation_id=conversation_id,
        inputs={
            "platform": "wechat_mp",
            "user_id": from_user_name,
            "msg_id": msg_id
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
    
    # 发送回复消息
    try:
        # 将长回复拆分成多条消息发送
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
                content="微信公众号自动回复成功"
            )

        # 保存消息到MySQL
        # TODO(claude89757): 保存消息到MySQL

    except Exception as error:
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
    
    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, from_user_name)
    print("-"*50)
    for msg in messages:
        print(msg)
    print("-"*50)


def save_msg_to_mysql(**context):
    """
    保存消息到MySQL
    """
    # TODO(claude89757): 保存消息到MySQL
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
    
    # 准备问题内容
    query = "这是一张图片，请描述一下图片内容并给出你的分析"
    
    # 创建临时目录用于保存下载的图片
    import tempfile
    import os
    from datetime import datetime
    
    temp_dir = tempfile.gettempdir()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    img_file_path = os.path.join(temp_dir, f"wx_img_{from_user_name}_{timestamp}.jpg")
    
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
        
        # 获取AI回复（带有图片分析）
        # 注意：这里假设Dify支持图片处理，如果不支持，需要修改为其他图像处理API
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=query,
            user_id=from_user_name,
            conversation_id=conversation_id,
            inputs={
                "platform": "wechat_mp",
                "user_id": from_user_name,
                "msg_id": msg_id,
                "image_path": img_file_path  # 传递图片路径给Dify
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
        
        # 发送回复消息
        try:
            # 将长回复拆分成多条消息发送
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
        except Exception as error:
            print(f"[WATCHER] 发送消息失败: {error}")
            # 记录消息回复失败
            dify_msg_id = metadata.get("message_id")
            if dify_msg_id:
                dify_agent.create_message_feedback(
                    message_id=dify_msg_id, 
                    user_id=from_user_name, 
                    rating="dislike", 
                    content=f"微信公众号图片消息自动回复失败, {error}"
                )
    except Exception as e:
        print(f"[WATCHER] 处理图片消息失败: {e}")
        # 发送错误提示给用户
        try:
            mp_bot.send_text_message(from_user_name, f"很抱歉，无法处理您的图片，发生了以下错误：{str(e)}")
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


def handler_voice_msg(**context):
    """
    处理语音类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
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
    
    # 准备问题内容
    query = "这是一段语音消息，请进行转录并回复用户"
    
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
        # 下载语音文件
        mp_bot.download_temporary_media(voice_media_id, voice_file_path)
        print(f"[WATCHER] 语音文件已保存到: {voice_file_path}")
        
        # 获取AI回复（带有语音转录）
        # 注意：这里假设Dify支持语音处理，如果不支持，需要修改为其他语音识别API
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=query,
            user_id=from_user_name,
            conversation_id=conversation_id,
            inputs={
                "platform": "wechat_mp",
                "user_id": from_user_name,
                "msg_id": msg_id,
                "voice_path": voice_file_path,  # 传递语音文件路径给Dify
                "voice_format": format_type.lower()
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
        
        # 发送回复消息
        try:
            # 将长回复拆分成多条消息发送
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
                    content="微信公众号语音消息自动回复成功"
                )
        except Exception as error:
            print(f"[WATCHER] 发送消息失败: {error}")
            # 记录消息回复失败
            dify_msg_id = metadata.get("message_id")
            if dify_msg_id:
                dify_agent.create_message_feedback(
                    message_id=dify_msg_id, 
                    user_id=from_user_name, 
                    rating="dislike", 
                    content=f"微信公众号语音消息自动回复失败, {error}"
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
            if os.path.exists(voice_file_path):
                os.remove(voice_file_path)
                print(f"[WATCHER] 临时语音文件已删除: {voice_file_path}")
        except Exception as e:
            print(f"[WATCHER] 删除临时文件失败: {e}")


def handler_file_msg(**context):
    """
    处理文件类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    """
    # TODO(claude89757): 处理文件类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    pass


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

# 设置任务依赖关系
process_message_task >> [handler_text_msg_task, handler_image_msg_task, handler_voice_msg_task, save_msg_to_mysql_task]
