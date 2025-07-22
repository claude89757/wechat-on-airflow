#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取指定用户和聊天室的客户标签分析总结

Author: by cursor
Date: 2025-04-01
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
    云函数入口函数， 获取指定用户和聊天室的客户标签分析总结
    
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
    contact_name = query_params.get('contact_name', '')
    
    # 如果必要参数存在
    if wx_user_id and contact_name:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 查询指定用户和聊天室的客户标签分析总结
            query = """
            SELECT 
                id,
                contact_name,
                room_name,
                wx_user_id,
                start_time,
                end_time,
                message_count,
                raw_summary,
                name,
                contact,
                gender,
                age_group,
                city_tier,
                specific_location,
                occupation_type,
                marital_status,
                family_structure,
                income_level_estimated,
                core_values,
                hobbies_interests,
                life_status_indicators,
                social_media_activity_level,
                info_acquisition_habits,
                acquisition_channel_type,
                acquisition_channel_detail,
                initial_intent,
                intent_details,
                product_knowledge_level,
                communication_style,
                current_trust_level,
                need_urgency,
                core_need_type,
                budget_sensitivity,
                decision_drivers,
                main_purchase_obstacles,
                upsell_readiness,
                past_satisfaction_level,
                customer_loyalty_status,
                repurchase_drivers,
                need_evolution_trend,
                engagement_level,
                partner_source_type,
                partner_name,
                partner_interest_focus,
                partner_conversion_obstacles,
                chat_key_event,
                created_at,
                updated_at
            FROM wx_chat_summary
            WHERE wx_user_id = %s AND contact_name = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """
            
            cursor.execute(query, (wx_user_id, contact_name))
            result = cursor.fetchone()
            
            # 格式化日期时间
            if result:
                # 处理日期时间字段
                for key in ['start_time', 'end_time', 'created_at', 'updated_at']:
                    if key in result and result[key]:
                        result[key] = result[key].strftime('%Y-%m-%d %H:%M:%S')
                
                # 处理JSON字段
                for key in ['core_values', 'hobbies_interests', 'life_status_indicators', 
                           'info_acquisition_habits', 'decision_drivers', 'main_purchase_obstacles',
                           'repurchase_drivers', 'partner_conversion_obstacles', 'chat_key_event']:
                    if key in result and result[key]:
                        if isinstance(result[key], str):
                            try:
                                result[key] = json.loads(result[key])
                            except json.JSONDecodeError:
                                pass
                
                # 构建结构化的标签数据
                structured_data = {
                    "基础信息": {
                        "name": result.get('name'),
                        "contact": result.get('contact'),
                        "gender": result.get('gender'),
                        "age_group": result.get('age_group'),
                        "city_tier": result.get('city_tier'),
                        "specific_location": result.get('specific_location'),
                        "occupation_type": result.get('occupation_type'),
                        "marital_status": result.get('marital_status'),
                        "family_structure": result.get('family_structure'),
                        "income_level_estimated": result.get('income_level_estimated')
                    },
                    "价值观与兴趣": {
                        "core_values": result.get('core_values'),
                        "hobbies_interests": result.get('hobbies_interests'),
                        "life_status_indicators": result.get('life_status_indicators'),
                        "social_media_activity_level": result.get('social_media_activity_level'),
                        "info_acquisition_habits": result.get('info_acquisition_habits')
                    },
                    "互动与认知": {
                        "acquisition_channel_type": result.get('acquisition_channel_type'),
                        "acquisition_channel_detail": result.get('acquisition_channel_detail'),
                        "initial_intent": result.get('initial_intent'),
                        "intent_details": result.get('intent_details'),
                        "product_knowledge_level": result.get('product_knowledge_level'),
                        "communication_style": result.get('communication_style'),
                        "current_trust_level": result.get('current_trust_level'),
                        "need_urgency": result.get('need_urgency')
                    },
                    "购买决策": {
                        "core_need_type": result.get('core_need_type'),
                        "budget_sensitivity": result.get('budget_sensitivity'),
                        "decision_drivers": result.get('decision_drivers'),
                        "main_purchase_obstacles": result.get('main_purchase_obstacles'),
                        "upsell_readiness": result.get('upsell_readiness')
                    },
                    "客户关系": {
                        "past_satisfaction_level": result.get('past_satisfaction_level'),
                        "customer_loyalty_status": result.get('customer_loyalty_status'),
                        "repurchase_drivers": result.get('repurchase_drivers'),
                        "need_evolution_trend": result.get('need_evolution_trend'),
                        "engagement_level": result.get('engagement_level')
                    },
                    "特殊来源": {
                        "partner_source_type": result.get('partner_source_type'),
                        "partner_name": result.get('partner_name'),
                        "partner_interest_focus": result.get('partner_interest_focus'),
                        "partner_conversion_obstacles": result.get('partner_conversion_obstacles')
                    }
                }
                
                # 添加元数据
                metadata = {
                    "id": result.get('id'),
                    "contact_name": result.get('contact_name'),
                    "room_name": result.get('room_name'),
                    "wx_user_id": result.get('wx_user_id'),
                    "time_range": {
                        "start": result.get('start_time'),
                        "end": result.get('end_time')
                    },
                    "message_count": result.get('message_count'),
                    "created_at": result.get('created_at'),
                    "updated_at": result.get('updated_at')
                }
                
                # 处理关键事件数据
                chat_key_event = result.get('chat_key_event', [])
                
                # 结果对象
                return_data = {
                    "metadata": metadata,
                    "summary": result.get('raw_summary'),
                    "chat_key_event": chat_key_event,
                    "tags": structured_data
                }
                
                return {
                    'code': 0,
                    'message': 'success',
                    'data': return_data
                }
            else:
                return {
                    'code': 0,
                    'message': 'no data found',
                    'data': None
                }
                
        except Exception as e:
            logger.error(f"获取客户标签分析总结失败: {str(e)}")
            return {
                'code': -1,
                'message': f"获取客户标签分析总结失败: {str(e)}",
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
        if not contact_name:
            missing_params.append('contact_name')
            
        return {
            'code': -1,
            'message': f'{", ".join(missing_params)} is required',
            'data': None
        }