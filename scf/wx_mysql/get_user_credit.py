#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取用户AI额度信息并检查余额是否充足

Author: by cursor
Date: 2025-04-02
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
    云函数入口函数，获取用户AI额度信息并检查余额是否充足
    
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
    
    # 检查必要参数
    if not wx_user_id:
        return {
            'code': -1,
            'message': 'wx_user_id is required',
            'data': None
        }
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询用户额度信息
        query = """
        SELECT 
            id,
            create_time,
            used_credit,
            wx_user_id,
            credit_limit
        FROM user_credit
        WHERE wx_user_id = %s
        ORDER BY create_time DESC
        LIMIT 1
        """
        
        cursor.execute(query, (wx_user_id,))
        result = cursor.fetchone()
        
        if result:
            # 处理日期时间字段
            if result.get('create_time'):
                result['create_time'] = result['create_time'].strftime('%Y-%m-%d %H:%M:%S')
            
            # 转换额度字段为数值类型进行比较
            try:
                used_credit = float(result.get('used_credit', 0))
                credit_limit = float(result.get('credit_limit', 0))
                
                # 检查余额是否充足
                is_sufficient = used_credit <= credit_limit
                remaining_credit = credit_limit - used_credit
                
                # 构建返回数据
                return_data = {
                    "user_info": {
                        "id": result.get('id'),
                        "wx_user_id": result.get('wx_user_id'),
                        "create_time": result.get('create_time')
                    },
                    "credit_info": {
                        "used_credit": used_credit,
                        "credit_limit": credit_limit,
                        "remaining_credit": remaining_credit,
                        "is_sufficient": is_sufficient
                    }
                }
                
                # 根据余额情况返回不同的消息
                if is_sufficient:
                    return {
                        'code': 0,
                        'message': 'Credit balance is sufficient',
                        'data': return_data
                    }
                else:
                    return {
                        'code': 1,
                        'message': 'Insufficient credit balance',
                        'data': return_data
                    }
                    
            except (ValueError, TypeError) as e:
                logger.error(f"额度数据转换失败: {str(e)}")
                return {
                    'code': -1,
                    'message': f'Credit data conversion failed: {str(e)}',
                    'data': None
                }
        else:
            return {
                'code': 0,
                'message': 'No credit data found for this user',
                'data': None
            }
            
    except Exception as e:
        logger.error(f"获取用户额度信息失败: {str(e)}")
        return {
            'code': -1,
            'message': f'Failed to get user credit info: {str(e)}',
            'data': None
        }
    finally:
        # 关闭数据库连接
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()