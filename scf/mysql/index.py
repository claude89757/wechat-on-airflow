# -*- coding: utf8 -*-
"""
# 微信聊天记录查询API

## 功能说明
本API用于查询微信聊天记录数据，支持多种查询条件筛选，并以JSON格式返回结果。

## 调用方式
- 请求方法: GET/POST
- 请求URL: curl http://1300108802-e28slit0tb.in.ap-guangzhou.tencentscf.com
- 备注：只能在airflow服务器中访问，公网无法访问

## 请求参数
| 参数名      | 类型   | 必填 | 说明                                  |
|------------|--------|------|--------------------------------------|
| room_id    | string | 否   | 聊天室ID，用于筛选特定聊天室的消息      |
| wx_user_id | string | 否   | 微信用户ID，用于筛选特定用户的消息      |
| sender_id  | string | 否   | 发送者ID，用于筛选特定发送者的消息      |
| start_time | string | 否   | 开始时间，格式: 'YYYY-MM-DD HH:MM:SS' |
| end_time   | string | 否   | 结束时间，格式: 'YYYY-MM-DD HH:MM:SS' |
| limit      | int    | 否   | 返回记录数量限制，默认100              |
| offset     | int    | 否   | 分页偏移量，默认0                      |

## 返回结果
```json
{
    "code": 0,           // 状态码，0表示成功，非0表示失败
    "message": "success", // 状态描述
    "data": {
        "total": 100,    // 符合条件的总记录数
        "records": [     // 记录列表
            {
                "id": 1,
                "room_id": "room123",
                "wx_user_id": "user123",
                "sender_id": "sender123",
                "msg_content": "消息内容",
                "msg_datetime": "2023-01-01 12:00:00",
                // 其他字段...
            }
        ],
        "limit": 100,    // 当前限制数量
        "offset": 0      // 当前偏移量
    }
}
```

## 错误码说明
- 0: 成功
- -1: 查询失败，详细错误信息在message字段中

## 调用示例
```
GET /api?room_id=room123&limit=10&offset=0
```

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

def get_user_rooms_with_latest_message(wx_user_id: str) -> list:
    """
    获取指定用户的所有聊天室及其最新消息
    
    Args:
        wx_user_id: 微信用户ID
        
    Returns:
        list: 包含每个聊天室最新消息的列表，格式如下：
        [
            {
                "room_id": "room123",
                "wx_user_id": "user123",
                "sender_id": "sender123",
                "msg_content": "消息内容",
                "msg_datetime": "2023-01-01 12:00:00"
            },
            ...
        ]
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 使用子查询找到每个聊天室的最新消息ID
        query = """
        WITH latest_messages AS (
            SELECT room_id, MAX(msg_datetime) as latest_datetime
            FROM wx_chat_records
            WHERE wx_user_id = %s
            GROUP BY room_id
        )
        SELECT 
            r.room_id,
            r.wx_user_id,
            r.sender_id,
            r.content as msg_content,
            r.msg_datetime
        FROM wx_chat_records r
        INNER JOIN latest_messages lm
            ON r.room_id = lm.room_id
            AND r.msg_datetime = lm.latest_datetime
        WHERE r.wx_user_id = %s
        ORDER BY r.msg_datetime DESC
        """
        
        cursor.execute(query, (wx_user_id, wx_user_id))
        results = cursor.fetchall()
        
        # 格式化日期时间
        for row in results:
            if row['msg_datetime']:
                row['msg_datetime'] = row['msg_datetime'].strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.close()
        conn.close()
        
        return results
        
    except Exception as e:
        print(f"Error querying user rooms: {str(e)}")
        return []


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
    
    # 提取查询参数
    wx_user_id = query_params.get('wx_user_id', '')
    get_list = str(query_params.get('get_list', '')).lower() == 'true'
    
    # 如果是获取聊天室列表请求
    if wx_user_id and get_list:
        try:
            records = get_user_rooms_with_latest_message(wx_user_id)
            return {
                'code': 0,
                'message': 'success',
                'data': records
            }
        except Exception as e:
            logger.error(f"获取聊天室列表失败: {str(e)}")
            return {
                'code': -1,
                'message': f"获取聊天室列表失败: {str(e)}",
                'data': None
            }
    
    # 常规查询参数
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
    sql = "SELECT * FROM wx_chat_records"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    # 添加排序和分页
    sql += " ORDER BY msg_datetime DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    # 查询总记录数
    count_sql = "SELECT COUNT(*) as total FROM wx_chat_records"
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