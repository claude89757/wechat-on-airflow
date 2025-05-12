# -*- coding: utf8 -*-
"""
获取指定聊天室的消息列表

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
    云函数入口函数，用于查询微信聊天数据并以JSON格式返回
    
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
        
    # 常规查询参数
    wx_user_id = query_params.get('wx_user_id', '')
    room_id = query_params.get('room_id', '')
    sender_id = query_params.get('sender_id', '')
    start_time = query_params.get('start_time', '')
    end_time = query_params.get('end_time', '')
    limit = int(query_params.get('limit', 100))  # 默认限制100条
    offset = int(query_params.get('offset', 0))  # 默认从0开始
    
    # 构建查询条件
    conditions = []
    params = []
    
    if room_id:
        conditions.append("room_id = %s")
        params.append(room_id)
    
    if wx_user_id:
        conditions.append("wx_user_id = %s")
        params.append(wx_user_id)
    
    if sender_id:
        conditions.append("sender_id = %s")
        params.append(sender_id)
    
    if start_time:
        conditions.append("msg_datetime >= %s")
        params.append(start_time)
    
    if end_time:
        conditions.append("msg_datetime <= %s")
        params.append(end_time)
    
    # 构建SQL查询
    sql = f"SELECT * FROM {wx_user_id}_wx_chat_records"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    # 添加排序和分页
    sql += " ORDER BY msg_datetime DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    # 查询总记录数
    count_sql = f"SELECT COUNT(*) as total FROM {wx_user_id}_wx_chat_records"
    if conditions:
        count_sql += " WHERE " + " AND ".join(conditions)
    
    try:
        # 获取数据库连接
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询总记录数
        cursor.execute(count_sql, params[:-2] if conditions else [])
        total_count = cursor.fetchone()['total']
        
        # 执行查询
        logger.info(f"执行SQL: {sql}, 参数: {params}")
        cursor.execute(sql, params)
        records = cursor.fetchall()
        
        # 处理日期时间格式，使其可JSON序列化
        for record in records:
            for key, value in record.items():
                if isinstance(value, datetime):
                    record[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        
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
        # 关闭数据库连接
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()