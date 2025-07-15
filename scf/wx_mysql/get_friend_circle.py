#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取指定用户的朋友圈分析数据

Author: by cursor
Date: 2025-07-15
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
    云函数入口函数，获取指定用户的朋友圈分析数据
    
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
    wxid = query_params.get('wxid', '')
    nickname = query_params.get('nickname', '')
    
    # 如果必要参数存在
    if wx_user_id and (wxid or nickname):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 构建查询条件
            conditions = []
            params = []
            
            if wxid:
                conditions.append("wxid = %s")
                params.append(wxid)
            elif nickname:
                conditions.append("nickname = %s")
                params.append(nickname)
            
            # 查询指定用户的朋友圈分析数据
            query = f"""
            SELECT 
                id,
                wxid,
                nickname,
                basic,
                consumption,
                core_interests,
                life_pattern,
                social,
                `values`,
                created_at,
                updated_at
            FROM `{wx_user_id}_wx_friend_circle_table`
            WHERE {' AND '.join(conditions)}
            ORDER BY updated_at DESC
            LIMIT 1
            """
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            if result:
                # 处理datetime对象，转换为字符串
                for key, value in result.items():
                    if isinstance(value, datetime):
                        result[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                
                # 将JSON字段解析为Python对象
                for field in ['basic', 'consumption', 'core_interests', 'life_pattern', 'social', 'values']:
                    if result.get(field) and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            # 如果解析失败，保持原样
                            pass
                
                # 构建返回结果
                friend_data = {
                    "metadata": {
                        "id": result.get('id'),
                        "wxid": result.get('wxid'),
                        "nickname": result.get('nickname'),
                        "wx_user_id": wx_user_id,
                        "created_at": result.get('created_at'),
                        "updated_at": result.get('updated_at')
                    },
                    "analysis": {
                        "basic": result.get('basic'),
                        "consumption": result.get('consumption'),
                        "core_interests": result.get('core_interests'),
                        "life_pattern": result.get('life_pattern'),
                        "social": result.get('social'),
                        "values": result.get('values')
                    }
                }
                
                return {
                    'code': 0,
                    'message': 'success',
                    'data': friend_data
                }
            else:
                return {
                    'code': 0,
                    'message': 'no data found',
                    'data': None
                }
                
        except Exception as e:
            logger.error(f"获取朋友圈分析数据失败: {str(e)}")
            return {
                'code': -1,
                'message': f"获取朋友圈分析数据失败: {str(e)}",
                'data': None
            }
        finally:
            # 关闭数据库连接
            if 'conn' in locals() and conn:
                cursor.close()
                conn.close()
    else:
        missing_params = []
        if not wx_user_id:
            missing_params.append('wx_user_id')
        if not wxid and not nickname:
            missing_params.append('wxid or nickname')
            
        return {
            'code': -1,
            'message': f'{", ".join(missing_params)} is required',
            'data': None
        }