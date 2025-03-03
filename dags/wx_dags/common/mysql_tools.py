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


def save_msg_to_db(msg_data: dict):
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
    insert_sql = """INSERT INTO `wx_chat_records` 
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


def get_wx_chat_history(room_id: str, wx_user_id: str = None, start_time: str = None, end_time: str = None, limit: int = 100, offset: int = 0):
    """
    获取微信聊天记录
    
    Args:
        room_id (str): 聊天室ID
        wx_user_id (str, optional): 微信用户ID，如果提供则查询特定用户的数据表
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
        conditions = ["room_id = %s"]
        params = [room_id]
        
        if start_time:
            conditions.append("msg_datetime >= %s")
            params.append(start_time)
            
        if end_time:
            conditions.append("msg_datetime <= %s")
            params.append(end_time)
            
        # 确定查询的表名
        table_name = f"{wx_user_id}_wx_chat_records" if wx_user_id else "wx_chat_records"
        
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
        