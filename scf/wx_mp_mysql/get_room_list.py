#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取微信公众号的会话列表和每个会话的最新消息

Author: lys
Date: 2025-03-03
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
    云函数入口函数，获取微信公众号的会话列表和最新消息
    
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
            
            # 使用子查询找到每个用户与公众号的最新消息
            query = """
            WITH latest_messages AS (
                SELECT 
                    wx_user_id,
                    from_user_id,
                    msg_type,
                    content as msg_content,
                    create_time as msg_datetime,
                    ROW_NUMBER() OVER (PARTITION BY mp_id, user_id ORDER BY create_time DESC) as rn
                FROM wx_mp_chat_records
                WHERE mp_id = %s
            )
            SELECT 
                wx_user_id,
                from_user_id,
                msg_type,
                msg_content,
                msg_datetime
            FROM latest_messages
            WHERE rn = 1
            ORDER BY msg_datetime DESC
            """
            
            cursor.execute(query, (mp_id,))
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
            logger.error(f"获取公众号会话列表失败: {str(e)}")
            return {
                'code': -1,
                'message': f"获取公众号会话列表失败: {str(e)}",
                'data': None
            }
        finally:
            if 'conn' in locals() and conn:
                cursor.close()
                conn.close()
    else:
        return {
            'code': -1,
            'message': 'mp_id is required',
            'data': None
        }


