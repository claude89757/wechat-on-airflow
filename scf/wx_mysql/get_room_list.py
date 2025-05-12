
#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取指定用户的所有聊天室及其最新消息

Author: by cursor
Date: 2025-03-01
"""

import json
import os
import pymysql
import logging
from datetime import datetime

# 配置日志
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def get_db_connection():
    """
    获取数据库连接
    """
    try:
        # 从环境变量获取数据库连接信息
        db_name = os.environ.get('DB_NAME')
        db_ip = os.environ.get('DB_IP')
        db_port = int(os.environ.get('DB_PORT', 3306))
        db_user = os.environ.get('DB_USER')
        db_password = os.environ.get('DB_PASSWORD')
        
        # 创建数据库连接
        connection = pymysql.connect(
            host=db_ip,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        return connection
    except Exception as e:
        logger.error(f"数据库连接失败: {str(e)}")
        raise e


def main_handler(event, context):
    """
    云函数入口函数， 获取指定用户的所有聊天室及其最新消息
    
    Args:
        event: 触发事件，包含查询参数
        context: 函数上下文
        
    Returns:
        JSON格式的查询结果
    """
    logger.info(f"收到请求: {json.dumps(event, ensure_ascii=False)}")
    
    # 解析查询参数
    query_params = {}
    if 'queryString' in event:
        query_params = event['queryString']
    elif 'body' in event:
        try:
            # 尝试解析body为JSON
            if isinstance(event['body'], str):
                query_params = json.loads(event['body'])
            else:
                query_params = event['body']
        except:
            pass
    
    # 提取查询参数
    wx_user_id = query_params.get('wx_user_id', '')
    
    # 如果是获取聊天室列表请求
    if wx_user_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            table_name = f'{wx_user_id}_wx_chat_records'

            # 使用子查询找到每个聊天室的最新消息
            query = f"""
            WITH room_messages AS (
                SELECT 
                    room_id,
                    room_name,
                    wx_user_id,
                    wx_user_name,
                    sender_id,
                    sender_name,
                    msg_id,
                    content as msg_content,
                    msg_datetime,
                    msg_type,
                    is_group,
                    ROW_NUMBER() OVER (PARTITION BY room_id ORDER BY msg_datetime DESC) as rn
                FROM {table_name}
                WHERE wx_user_id = %s
            )
            SELECT 
                room_id,
                room_name,
                wx_user_id,
                wx_user_name,
                sender_id,
                sender_name,
                msg_id,
                msg_content,
                msg_datetime,
                msg_type,
                is_group
            FROM room_messages
            WHERE rn = 1
            ORDER BY msg_datetime DESC
            """
            
            cursor.execute(query, (wx_user_id,))
            results = cursor.fetchall()
            
            # 格式化日期时间
            for row in results:
                if row['msg_datetime']:
                    row['msg_datetime'] = row['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')            
            return {
                'code': 0,
                'message': 'success',
                'data': results
            }
        except Exception as e:
            logger.error(f"获取聊天室列表失败: {str(e)}")
            return {
                'code': -1,
                'message': f"获取聊天室列表失败: {str(e)}",
                'data': None
            }
        finally:
            # 关闭数据库连接
            if 'conn' in locals() and conn:
                cursor.close()
                conn.close()
    else:
        return {
            'code': -1,
            'message': 'wx_user_id is required',
            'data': None
        }
