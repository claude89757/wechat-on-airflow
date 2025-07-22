#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL数据库工具模块

功能:
1. 初始化微信聊天记录表
2. 保存微信消息到数据库
3. 查询微信消息记录

特点:
1. 支持多账号数据隔离
2. 自动创建账号专属数据表
3. 异常重试和事务回滚
"""


import json
from airflow.hooks.base import BaseHook


def init_wx_chat_records_table(wx_user_id: str):
    """
    初始化微信聊天记录表
    """
    # 使用get_hook函数获取数据库连接
    db_hook = BaseHook.get_connection("wx_db").get_hook()
    db_conn = db_hook.get_conn()
    cursor = db_conn.cursor()
    
     # 聊天记录的创建数据包
    create_table_sql = """CREATE TABLE IF NOT EXISTS `wx_chat_records` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `msg_id` varchar(64) NOT NULL COMMENT '微信消息ID',
        `wx_user_id` varchar(64) NOT NULL COMMENT '微信用户ID',
        `wx_user_name` varchar(64) NOT NULL COMMENT '微信用户名',
        `room_id` varchar(64) NOT NULL COMMENT '聊天室ID',
        `room_name` varchar(128) DEFAULT NULL COMMENT '聊天室名称',
        `sender_id` varchar(64) NOT NULL COMMENT '发送者ID',
        `sender_name` varchar(128) DEFAULT NULL COMMENT '发送者名称',
        `msg_type` int(11) NOT NULL COMMENT '消息类型',
        `msg_type_name` varchar(64) DEFAULT NULL COMMENT '消息类型名称',
        `content` text COMMENT '消息内容',
        `is_self` tinyint(1) DEFAULT '0' COMMENT '是否自己发送',
        `is_group` tinyint(1) DEFAULT '0' COMMENT '是否群聊',
        `source_ip` varchar(64) DEFAULT NULL COMMENT '来源IP',
        `msg_timestamp` bigint(20) DEFAULT NULL COMMENT '消息时间戳',
        `msg_datetime` datetime DEFAULT NULL COMMENT '消息时间',
        `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (`id`),
        UNIQUE KEY `uk_msg_id_wx_user_id` (`msg_id`, `wx_user_id`),
        KEY `idx_room_id` (`room_id`),
        KEY `idx_sender_id` (`sender_id`),
        KEY `idx_wx_user_id` (`wx_user_id`),
        KEY `idx_msg_datetime` (`msg_datetime`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信聊天记录';
    """

    # 创建表（如果不存在）
    cursor.execute(create_table_sql)

    # 聊天记录的创建数据包
    create_table_sql_for_user = f"""CREATE TABLE IF NOT EXISTS `{wx_user_id}_wx_chat_records` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `msg_id` varchar(64) NOT NULL COMMENT '微信消息ID',
        `wx_user_id` varchar(64) NOT NULL COMMENT '微信用户ID',
        `wx_user_name` varchar(64) NOT NULL COMMENT '微信用户名',
        `room_id` varchar(64) NOT NULL COMMENT '聊天室ID',
        `room_name` varchar(128) DEFAULT NULL COMMENT '聊天室名称',
        `sender_id` varchar(64) NOT NULL COMMENT '发送者ID',
        `sender_name` varchar(128) DEFAULT NULL COMMENT '发送者名称',
        `msg_type` int(11) NOT NULL COMMENT '消息类型',
        `msg_type_name` varchar(64) DEFAULT NULL COMMENT '消息类型名称',
        `content` text COMMENT '消息内容',
        `is_self` tinyint(1) DEFAULT '0' COMMENT '是否自己发送',
        `is_group` tinyint(1) DEFAULT '0' COMMENT '是否群聊',
        `source_ip` varchar(64) DEFAULT NULL COMMENT '来源IP',
        `msg_timestamp` bigint(20) DEFAULT NULL COMMENT '消息时间戳',
        `msg_datetime` datetime DEFAULT NULL COMMENT '消息时间',
        `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (`id`),
        UNIQUE KEY `uk_msg_id_wx_user_id` (`msg_id`, `wx_user_id`),
        KEY `idx_room_id` (`room_id`),
        KEY `idx_sender_id` (`sender_id`),
        KEY `idx_wx_user_id` (`wx_user_id`),
        KEY `idx_msg_datetime` (`msg_datetime`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信聊天记录';
    """
    
    cursor.execute(create_table_sql_for_user)

    # 提交事务
    db_conn.commit()

    # 关闭连接
    cursor.close()
    db_conn.close()


def save_data_to_db(msg_data: dict):
    """
    保存消息到数据库
    """
    print(f"[DB_SAVE] 保存消息到数据库, msg_data: {msg_data}")
    
    # 提取消息信息
    msg_id = msg_data.get('msg_id', '')
    wx_user_id = msg_data.get('wx_user_id', '')
    wx_user_name = msg_data.get('wx_user_name', '')
    room_id = msg_data.get('room_id', '')
    room_name = msg_data.get('room_name', '')
    sender_id = msg_data.get('sender_id', '')
    sender_name = msg_data.get('sender_name', '')
    msg_type = msg_data.get('msg_type', 0)
    msg_type_name = msg_data.get('msg_type_name', '')
    content = msg_data.get('content', '')
    is_self = 1 if msg_data.get('is_self', False) else 0
    is_group = 1 if msg_data.get('is_group', False) else 0
    source_ip = msg_data.get('source_ip', '')
    msg_timestamp = msg_data.get('msg_timestamp', '')
    msg_datetime = msg_data.get('msg_datetime', '')

    # 插入数据SQL
    insert_sql = f"""INSERT INTO `{wx_user_id}_wx_chat_records` 
    (msg_id, 
    wx_user_id, 
    wx_user_name, 
    room_id, 
    room_name, 
    sender_id, 
    sender_name, 
    msg_type,
    msg_type_name, 
    content, 
    is_self, 
    is_group, 
    source_ip, 
    msg_timestamp, 
    msg_datetime) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
    content = VALUES(content),
    room_name = VALUES(room_name),
    sender_name = VALUES(sender_name),
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
            msg_id, 
            wx_user_id,
            wx_user_name,
            room_id,
            room_name,
            sender_id,
            sender_name,
            msg_type,
            msg_type_name,
            content,
            is_self,
            is_group,
            source_ip,
            msg_timestamp,
            msg_datetime
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
        raise Exception(f"[DB_SAVE] 保存消息到数据库失败, 稍后重试")
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


def get_wx_chat_history(contact_name: str, wx_user_id: str = None, start_time: str = None, end_time: str = None, limit: int = 100, offset: int = 0):
    """
    获取微信聊天记录
    
    Args:
        contact_name (str): 联系人微信名
        wx_user_id (str, optional): 微信用户ID，作为筛选条件
        start_time (str, optional): 开始时间，格式：YYYY-MM-DD HH:mm:ss
        end_time (str, optional): 结束时间，格式：YYYY-MM-DD HH:mm:ss
        limit (int, optional): 返回记录数量限制，默认100
        offset (int, optional): 分页偏移量，默认0
        
    Returns:
        list: 聊天记录列表
    """
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db").get_hook()
        db_conn = db_hook.get_conn()
        cursor = db_conn.cursor()
        
        # 构建查询条件
        conditions = ["sender_name = %s"]
        params = [contact_name]
        
        # 添加 wx_user_id 作为筛选条件
        if wx_user_id:
            conditions.append("wx_user_id = %s")
            params.append(wx_user_id)
        
        if start_time:
            conditions.append("msg_datetime >= %s")
            params.append(start_time)
            
        if end_time:
            conditions.append("msg_datetime <= %s")
            params.append(end_time)
            
        # 根据wx_user_id设置表名
        table_name = f"{wx_user_id}_wx_chat_records"
        
        # 构建查询SQL
        query_sql = f"""
            SELECT 
                msg_id,
                wx_user_id,
                wx_user_name,
                room_id,
                room_name,
                sender_id,
                sender_name,
                msg_type,
                msg_type_name,
                content,
                is_self,
                is_group,
                source_ip,
                msg_timestamp,
                msg_datetime,
                created_at
            FROM {table_name}
            WHERE {' AND '.join(conditions)}
            ORDER BY msg_datetime DESC
            LIMIT %s OFFSET %s
        """
        
        # 添加分页参数
        params.extend([limit, offset])
        
        # 打印SQL查询和参数
        print("===== 调试SQL查询 =====")
        print(f"SQL: {query_sql}")
        print(f"参数: {params}")
        print("======================")
        
        # 执行查询
        cursor.execute(query_sql, params)
        
        # 获取列名
        columns = [desc[0] for desc in cursor.description]
        
        # 获取结果
        results = []
        for row in cursor.fetchall():
            result = dict(zip(columns, row))
            # 转换布尔值
            result['is_self'] = bool(result['is_self'])
            result['is_group'] = bool(result['is_group'])
            results.append(result)
            
        return results
        
    except Exception as e:
        print(f"[DB_QUERY] 获取聊天记录失败: {e}")
        raise Exception(f"[DB_QUERY] 获取聊天记录失败: {e}")
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

def init_wx_chat_summary_table():
    """
    初始化微信聊天记录摘要表
    """
    # 使用get_hook函数获取数据库连接
    db_hook = BaseHook.get_connection("wx_db").get_hook()
    db_conn = db_hook.get_conn()
    cursor = db_conn.cursor()
    
    # 创建聊天记录摘要表
    create_table_sql = """CREATE TABLE IF NOT EXISTS `wx_chat_summary` (
        `id` BIGINT NOT NULL AUTO_INCREMENT,
        `contact_name` VARCHAR(100) NOT NULL COMMENT '联系人名',
        `room_name` VARCHAR(100) NOT NULL COMMENT '会话名称',
        `wx_user_id` VARCHAR(100) NOT NULL COMMENT '微信用户ID',
        
        -- I. 基础信息
        `name` VARCHAR(50) DEFAULT NULL COMMENT '客户姓名',
        `contact` VARCHAR(100) DEFAULT NULL COMMENT '联系方式',
        `age_group` VARCHAR(20) DEFAULT '未知' COMMENT '年龄段',
        `gender` VARCHAR(10) DEFAULT '未知' COMMENT '性别',
        `city_tier` VARCHAR(20) DEFAULT '未知' COMMENT '城市级别',
        `specific_location` VARCHAR(100) DEFAULT NULL COMMENT '具体城市/区域',
        `occupation_type` VARCHAR(20) DEFAULT '未知' COMMENT '职业类型',
        `marital_status` VARCHAR(20) DEFAULT '未知' COMMENT '婚姻状态',
        `family_structure` VARCHAR(30) DEFAULT '未知' COMMENT '家庭结构',
        `income_level_estimated` VARCHAR(20) DEFAULT '未知' COMMENT '估计收入水平',
        `core_values` JSON DEFAULT NULL COMMENT '核心价值观',
        `hobbies_interests` JSON DEFAULT NULL COMMENT '爱好和兴趣',
        `life_status_indicators` JSON DEFAULT NULL COMMENT '生活状态指标',
        `social_media_activity_level` VARCHAR(20) DEFAULT '未知' COMMENT '社交媒体活跃度',
        `info_acquisition_habits` JSON DEFAULT NULL COMMENT '信息获取习惯',
        
        -- II. 互动与认知
        `acquisition_channel_type` VARCHAR(20) DEFAULT '未知' COMMENT '获客渠道类型',
        `acquisition_channel_detail` VARCHAR(100) DEFAULT NULL COMMENT '具体渠道详情',
        `initial_intent` VARCHAR(20) DEFAULT '未知' COMMENT '初始意图',
        `intent_details` TEXT DEFAULT NULL COMMENT '具体意图详情',
        `product_knowledge_level` VARCHAR(20) DEFAULT '未知' COMMENT '产品知识水平',
        `communication_style` VARCHAR(20) DEFAULT '未知' COMMENT '沟通风格',
        `current_trust_level` VARCHAR(10) DEFAULT '未知' COMMENT '当前信任水平',
        `need_urgency` VARCHAR(20) DEFAULT '未知' COMMENT '需求紧迫性',
        
        -- III. 购买决策
        `core_need_type` VARCHAR(20) DEFAULT '未知' COMMENT '核心需求类型',
        `budget_sensitivity` VARCHAR(30) DEFAULT '未知' COMMENT '预算敏感度',
        `decision_drivers` JSON DEFAULT NULL COMMENT '决策驱动因素',
        `main_purchase_obstacles` JSON DEFAULT NULL COMMENT '主要购买障碍',
        `upsell_readiness` VARCHAR(20) DEFAULT '未知' COMMENT '升单准备度',
        
        -- IV. 客户关系与忠诚度
        `past_satisfaction_level` VARCHAR(20) DEFAULT '未知' COMMENT '过往满意度',
        `customer_loyalty_status` VARCHAR(30) DEFAULT '未知' COMMENT '客户忠诚度状态',
        `repurchase_drivers` JSON DEFAULT NULL COMMENT '复购驱动因素',
        `need_evolution_trend` VARCHAR(20) DEFAULT '未知' COMMENT '需求演变趋势',
        `engagement_level` VARCHAR(10) DEFAULT '未知' COMMENT '品牌互动活跃度',
        
        -- V. 特殊来源
        `partner_source_type` VARCHAR(20) DEFAULT NULL COMMENT '合作方类型',
        `partner_name` VARCHAR(100) DEFAULT NULL COMMENT '具体合作方名称',
        `partner_interest_focus` VARCHAR(30) DEFAULT NULL COMMENT '合作客户兴趣点',
        `partner_conversion_obstacles` JSON DEFAULT NULL COMMENT '合作客户转化障碍',
        
        -- 聊天关键事件
        `chat_key_event` JSON DEFAULT NULL COMMENT '聊天关键事件/产品咨询',
        
        -- 基础信息
        `start_time` DATETIME NOT NULL COMMENT '聊天开始时间',
        `end_time` DATETIME NOT NULL COMMENT '聊天结束时间',
        `message_count` INT NOT NULL DEFAULT 0 COMMENT '消息数量',
        `raw_summary` TEXT DEFAULT NULL COMMENT '原始摘要文本',
        `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        
        PRIMARY KEY (`id`),
        INDEX `idx_room_wx_user` (`contact_name`, `wx_user_id`),
        INDEX `idx_time_range` (`start_time`, `end_time`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信聊天记录客户标签摘要';
    """
    
    cursor.execute(create_table_sql)
    
    # 提交事务
    db_conn.commit()
    
    # 关闭连接
    cursor.close()
    db_conn.close()
    
    print("微信聊天记录摘要表初始化完成")


def save_chat_summary_to_db(summary_data: dict):
    """
    保存聊天记录摘要到数据库
    
    Args:
        summary_data (dict): 摘要数据
    """
    print(f"[DB_SAVE] 保存聊天记录摘要到数据库, summary_data: {summary_data}")
    
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db").get_hook()
        db_conn = db_hook.get_conn()
        cursor = db_conn.cursor()
        
        # 检查表是否存在，如果不存在则创建
        cursor.execute("SHOW TABLES LIKE 'wx_chat_summary'")
        if not cursor.fetchone():
            init_wx_chat_summary_table()
        
        # 准备数据
        params = {
            # 基础信息
            'contact_name': summary_data.get('contact_name'),
            'room_name': summary_data.get('room_name'),
            'wx_user_id': summary_data.get('wx_user_id'),
            
            # I. 基础信息
            'name': summary_data.get('name') or summary_data.get('基础信息', {}).get('name'),
            'contact': summary_data.get('contact') or summary_data.get('基础信息', {}).get('contact'),
            'age_group': summary_data.get('基础信息', {}).get('age_group', '未知'),
            'gender': summary_data.get('基础信息', {}).get('gender', '未知'),
            'city_tier': summary_data.get('基础信息', {}).get('city_tier', '未知'),
            'specific_location': summary_data.get('基础信息', {}).get('specific_location'),
            'occupation_type': summary_data.get('基础信息', {}).get('occupation_type', '未知'),
            'marital_status': summary_data.get('基础信息', {}).get('marital_status', '未知'),
            'family_structure': summary_data.get('基础信息', {}).get('family_structure', '未知'),
            'income_level_estimated': summary_data.get('基础信息', {}).get('income_level_estimated', '未知'),
            
            # 处理JSON字段
            'core_values': json.dumps(summary_data.get('价值观与兴趣', {}).get('core_values', []), ensure_ascii=False),
            'hobbies_interests': json.dumps(summary_data.get('价值观与兴趣', {}).get('hobbies_interests', []), ensure_ascii=False),
            'life_status_indicators': json.dumps(summary_data.get('价值观与兴趣', {}).get('life_status_indicators', []), ensure_ascii=False),
            'social_media_activity_level': summary_data.get('价值观与兴趣', {}).get('social_media_activity_level', '未知'),
            'info_acquisition_habits': json.dumps(summary_data.get('价值观与兴趣', {}).get('info_acquisition_habits', []), ensure_ascii=False),
            
            # II. 互动与认知
            'acquisition_channel_type': summary_data.get('互动与认知', {}).get('acquisition_channel_type', '未知'),
            'acquisition_channel_detail': summary_data.get('互动与认知', {}).get('acquisition_channel_detail'),
            'initial_intent': summary_data.get('互动与认知', {}).get('initial_intent', '未知'),
            'intent_details': summary_data.get('互动与认知', {}).get('intent_details'),
            'product_knowledge_level': summary_data.get('互动与认知', {}).get('product_knowledge_level', '未知'),
            'communication_style': summary_data.get('互动与认知', {}).get('communication_style', '未知'),
            'current_trust_level': summary_data.get('互动与认知', {}).get('current_trust_level', '未知'),
            'need_urgency': summary_data.get('互动与认知', {}).get('need_urgency', '未知'),
            
            # III. 购买决策
            'core_need_type': summary_data.get('购买决策', {}).get('core_need_type', '未知'),
            'budget_sensitivity': summary_data.get('购买决策', {}).get('budget_sensitivity', '未知'),
            'decision_drivers': json.dumps(summary_data.get('购买决策', {}).get('decision_drivers', []), ensure_ascii=False),
            'main_purchase_obstacles': json.dumps(summary_data.get('购买决策', {}).get('main_purchase_obstacles', []), ensure_ascii=False),
            'upsell_readiness': summary_data.get('购买决策', {}).get('upsell_readiness', '未知'),
            
            # IV. 客户关系与忠诚度
            'past_satisfaction_level': summary_data.get('客户关系', {}).get('past_satisfaction_level', '未知'),
            'customer_loyalty_status': summary_data.get('客户关系', {}).get('customer_loyalty_status', '未知'),
            'repurchase_drivers': json.dumps(summary_data.get('客户关系', {}).get('repurchase_drivers', []), ensure_ascii=False),
            'need_evolution_trend': summary_data.get('客户关系', {}).get('need_evolution_trend', '未知'),
            'engagement_level': summary_data.get('客户关系', {}).get('engagement_level', '未知'),
            
            # V. 特殊来源
            'partner_source_type': summary_data.get('特殊来源', {}).get('partner_source_type'),
            'partner_name': summary_data.get('特殊来源', {}).get('partner_name'),
            'partner_interest_focus': summary_data.get('特殊来源', {}).get('partner_interest_focus'),
            'partner_conversion_obstacles': json.dumps(summary_data.get('特殊来源', {}).get('partner_conversion_obstacles', []), ensure_ascii=False),
            
            # 聊天关键事件
            'chat_key_event': json.dumps(summary_data.get('chat_key_event', []), ensure_ascii=False),
            
            # 基础信息
            'start_time': summary_data.get('start_time'),
            'end_time': summary_data.get('end_time'),
            'message_count': summary_data.get('message_count', 0),
            'raw_summary': summary_data.get('raw_summary')
        }
        
        # 构建插入SQL
        fields = ', '.join(params.keys())
        placeholders = ', '.join(['%s'] * len(params))
        
        # 检查是否已存在记录
        check_sql = "SELECT id FROM wx_chat_summary WHERE contact_name = %s AND wx_user_id = %s LIMIT 1"
        cursor.execute(check_sql, (params['contact_name'], params['wx_user_id']))
        existing_record = cursor.fetchone()
        
        if existing_record:
            # 更新现有记录
            update_parts = [f"{field} = %s" for field in params.keys()]
            update_sql = f"UPDATE wx_chat_summary SET {', '.join(update_parts)} WHERE contact_name = %s AND wx_user_id = %s"
            cursor.execute(update_sql, list(params.values()) + [params['contact_name'], params['wx_user_id']])
            print(f"[DB_SAVE] 更新聊天记录摘要: contact_name={params['contact_name']}, wx_user_id={params['wx_user_id']}")
        else:
            # 插入新记录
            insert_sql = f"INSERT INTO wx_chat_summary ({fields}) VALUES ({placeholders})"
            cursor.execute(insert_sql, list(params.values()))
            print(f"[DB_SAVE] 插入聊天记录摘要: contact_name={params['contact_name']}, wx_user_id={params['wx_user_id']}")
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存聊天记录摘要到数据库")
        
    except Exception as e:
        print(f"[DB_SAVE] 保存聊天记录摘要到数据库失败: {e}")
        if db_conn:
            try:
                db_conn.rollback()
            except:
                pass
        raise Exception(f"[DB_SAVE] 保存聊天记录摘要到数据库失败: {e}")
        
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


def save_token_usage_to_db(token_usage_data: dict):
    """
    保存token用量到数据库
    """
    print(f"[DB_SAVE] 保存token用量到数据库, token_usage_data: {token_usage_data}")
    
    # 提取token信息
    token_source_platform = token_usage_data.get('token_source_platform', '')
    msg_id = token_usage_data.get('msg_id', '')
    prompt_tokens = token_usage_data.get('prompt_tokens', '')
    prompt_unit_price = token_usage_data.get('prompt_unit_price', '')
    prompt_price_unit = token_usage_data.get('prompt_price_unit', '')
    prompt_price = token_usage_data.get('prompt_price', '')
    completion_tokens = token_usage_data.get('completion_tokens', '')
    completion_unit_price = token_usage_data.get('completion_unit_price', '')
    completion_price_unit = token_usage_data.get('completion_price_unit', '')
    completion_price = token_usage_data.get('completion_price', '')
    total_tokens = token_usage_data.get('total_tokens', '')
    total_price = token_usage_data.get('total_price', '')
    currency = token_usage_data.get('currency', '')
    wx_user_id = token_usage_data.get('wx_user_id', '')
    wx_user_name = token_usage_data.get('wx_user_name', '')
    room_id = token_usage_data.get('room_id', '')
    room_name = token_usage_data.get('room_name', '')

    # 插入数据SQL
    insert_sql = """INSERT INTO `token_usage` 
    (token_source_platform, 
    msg_id, 
    prompt_tokens, 
    prompt_unit_price, 
    prompt_price_unit, 
    prompt_price, 
    completion_tokens, 
    completion_unit_price,
    completion_price_unit, 
    completion_price, 
    total_tokens, 
    total_price, 
    currency,
    wx_user_id,
    wx_user_name,
    room_id,
    room_name) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            token_source_platform, 
            msg_id, 
            prompt_tokens, 
            prompt_unit_price, 
            prompt_price_unit, 
            prompt_price, 
            completion_tokens, 
            completion_unit_price,
            completion_price_unit, 
            completion_price, 
            total_tokens, 
            total_price, 
            currency,
            wx_user_id,
            wx_user_name,
            room_id,
            room_name
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存token用量到数据库: {msg_id}")
    except Exception as e:
        print(f"[DB_SAVE] 保存token用量到数据库失败: {e}")
        if db_conn:
            try:
                db_conn.rollback()
            except:
                pass
        raise Exception(f"[DB_SAVE] 保存token用量到数据库失败, 稍后重试")
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
        

def init_wx_friend_circle_table(wx_user_id: str):
    """
    初始化微信朋友圈分析表
    
    Args:
        wx_user_id: 微信用户ID
    """
    # 使用get_hook函数获取数据库连接
    db_hook = BaseHook.get_connection("wx_db").get_hook()
    db_conn = db_hook.get_conn()
    cursor = db_conn.cursor()
    
    # 朋友圈分析表的创建数据包
    create_table_sql = f"""CREATE TABLE IF NOT EXISTS `{wx_user_id}_wx_friend_circle_table` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `wxid` varchar(64) NOT NULL COMMENT '好友微信ID',
        `nickname` varchar(128) DEFAULT NULL COMMENT '好友昵称',
        `basic` JSON DEFAULT NULL COMMENT '基础属性(性别、年龄等)',
        `consumption` JSON DEFAULT NULL COMMENT '消费能力',
        `core_interests` JSON DEFAULT NULL COMMENT '兴趣偏好',
        `life_pattern` JSON DEFAULT NULL COMMENT '生活方式',
        `social` JSON DEFAULT NULL COMMENT '社交特征',
        `values` JSON DEFAULT NULL COMMENT '价值观',
        `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (`id`),
        UNIQUE KEY `uk_wxid` (`wxid`),
        KEY `idx_created_at` (`created_at`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信朋友圈分析';
    """
    
    # 创建表（如果不存在）
    cursor.execute(create_table_sql)
    
    # 提交事务
    db_conn.commit()
    
    # 关闭连接
    cursor.close()
    db_conn.close()
