#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取微信公众号每个会话的聊天记录

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
    云函数入口函数，用于查询微信公众号聊天数据并以JSON格式返回
    支持两种查询方式：
    1. 通过room_id查询（格式：gh_xxx_userid）
    2. 通过from_user_id和to_user_id查询
    """
    logger.info(f"收到请求: {json.dumps(event, ensure_ascii=False)}")
    
    # 解析查询参数
    query_params = {}
    if 'queryString' in event:
        query_params = event['queryString']
    elif 'body' in event:
        try:
            if isinstance(event['body'], str):
                query_params = json.loads(event['body'])
            else:
                query_params = event['body']
        except:
            pass
    
    # 构建查询条件
    conditions = []
    params = []
    
    # 支持两种查询方式
    room_id = query_params.get('room_id', '')
    from_user_id = query_params.get('from_user_id', '')
    to_user_id = query_params.get('to_user_id', '')
    
    if room_id:
        # 通过room_id查询
        try:
            mp_user_id, user_id = room_id.split('_', 1)
            conditions.append("((from_user_id = %s AND to_user_id = %s) OR (from_user_id = %s AND to_user_id = %s))")
            params.extend([mp_user_id, user_id, user_id, mp_user_id])
        except:
            return {
                "code": -1,
                "message": "room_id 格式错误，正确格式为：gh_xxx_userid",
                "data": None
            }
    elif from_user_id or to_user_id:
        # 通过from_user_id和to_user_id查询
        if from_user_id:
            conditions.append("from_user_id = %s")
            params.append(from_user_id)
        if to_user_id:
            conditions.append("to_user_id = %s")
            params.append(to_user_id)
    
    # 其他查询参数
    msg_type = query_params.get('msg_type', '')
    start_time = query_params.get('start_time', '')
    end_time = query_params.get('end_time', '')
    limit = int(query_params.get('limit', 100))  # 默认限制100条
    offset = int(query_params.get('offset', 0))  # 默认从0开始

    if msg_type:
        conditions.append("msg_type = %s")
        params.append(msg_type)
    
    if start_time:
        conditions.append("msg_datetime >= %s")
        params.append(start_time)
    
    if end_time:
        conditions.append("msg_datetime <= %s")
        params.append(end_time)

    # 构建SQL查询
    sql = """
        SELECT 
            msg_id,
            from_user_id as sender_id,
            from_user_name as sender_name,
            to_user_id as receiver_id,
            msg_type,
            content as msg_content,
            msg_datetime,
            create_time
        FROM wx_mp_chat_records
    """
    
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    # 添加排序和分页
    sql += " ORDER BY msg_datetime DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    # 查询总记录数
    count_sql = "SELECT COUNT(*) as total FROM wx_mp_chat_records"
    if conditions:
        count_sql += " WHERE " + " AND ".join(conditions)
    
    try:
        # 获取数据库连接
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询总记录数
        cursor.execute(count_sql, params[:-2])
        total_count = cursor.fetchone()['total']
        
        # 执行查询
        logger.info(f"执行SQL: {sql}, 参数: {params}")
        cursor.execute(sql, params)
        records = cursor.fetchall()
        
        # 处理日期时间格式
        for record in records:
            if record.get('msg_datetime'):
                record['msg_datetime'] = record['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')
            if record.get('create_time'):
                record['create_time'] = record['create_time'].strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建返回结果
        result = {
            "code": 0,
            "message": "success",
            "data": {
                "total": total_count,
                "records": records,
                "limit": limit,
                "offset": offset
            }
        }
        
        return result
    
    except Exception as e:
        logger.error(f"查询失败: {str(e)}")
        return {
            "code": -1,
            "message": f"查询失败: {str(e)}",
            "data": None
        }
    
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn' in locals() and conn:
            conn.close()