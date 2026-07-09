#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
朋友圈信息保存模块

功能:
1. 保存朋友圈分析结果到数据库
"""

import json
from datetime import datetime

from airflow.hooks.base import BaseHook


def save_friend_circle_to_db(wx_user_id: str, wxid: str, nickname: str, analysis_data: dict):
    """
    保存朋友圈分析结果到数据库
    
    Args:
        wx_user_id: 微信用户ID
        wxid: 好友微信ID
        nickname: 好友昵称
        analysis_data: 分析结果数据，包含6个维度
    """
    print("analysis_data:", analysis_data,type(analysis_data))
    print(f"[DB_SAVE] 保存朋友圈分析到数据库, wx_user_id: {wx_user_id}, wxid: {wxid}, nickname: {nickname}")
    
    # 提取分析数据的6个维度
    basic = json.dumps(analysis_data.get('basic', {}), ensure_ascii=False)
    consumption = json.dumps(analysis_data.get('consumption', ''), ensure_ascii=False)
    core_interests = json.dumps(analysis_data.get('core_interests', []), ensure_ascii=False)
    life_pattern = json.dumps(analysis_data.get('life_pattern', {}), ensure_ascii=False)
    social = json.dumps(analysis_data.get('social', []), ensure_ascii=False)
    values_data = json.dumps(analysis_data.get('values', []), ensure_ascii=False)

    print(f"wx_user_id: {wx_user_id}, wxid: {wxid}, nickname: {nickname}")
    print(f"basic: {basic}")
    print(f"consumption: {consumption}")
    print(f"core_interests: {core_interests}")
    print(f"life_pattern: {life_pattern}")
    print(f"social: {social}")
    print(f"values: {values_data}")
    

    # 插入数据SQL
    insert_sql = f"""INSERT INTO `{wx_user_id}_wx_friend_circle_table` 
    (wxid, 
    nickname, 
    basic, 
    consumption, 
    core_interests, 
    life_pattern, 
    social, 
    `values`) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
    nickname = VALUES(nickname),
    basic = VALUES(basic),
    consumption = VALUES(consumption),
    core_interests = VALUES(core_interests),
    life_pattern = VALUES(life_pattern),
    social = VALUES(social),
    `values` = VALUES(`values`),
    updated_at = CURRENT_TIMESTAMP
    """
    
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db").get_hook()
        db_conn = db_hook.get_conn()
        cursor = db_conn.cursor()
        
        # 插入数据
        cursor.execute(insert_sql, (
            wxid,
            nickname,
            basic,
            consumption,
            core_interests,
            life_pattern,
            social,
            values_data
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存朋友圈分析到数据库: {wxid}")
    except Exception as e:
        print(f"[DB_SAVE] 保存朋友圈分析到数据库失败: {e}")
        if db_conn:
            try:
                db_conn.rollback()
            except:
                pass
        raise Exception(f"[DB_SAVE] 保存朋友圈分析到数据库失败, 稍后重试")
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