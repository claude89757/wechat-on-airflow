import json
import os
import pymysql
import logging
import random
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


def update_current_answer(connection):
    """
    更新 current_answer 表中的 today 字段，增加一个 1～10 的随机数
    """
    try:
        with connection.cursor() as cursor:
            # 生成 1～10 的随机数
            random_value = random.randint(1, 10)
            
            # 更新 today 字段
            sql = "UPDATE current_answer SET today = today + %s"
            cursor.execute(sql, (random_value,))
            connection.commit()
            logger.info(f"成功更新 today 字段，增加了 {random_value}")
    except Exception as e:
        logger.error(f"更新数据失败: {str(e)}")
        connection.rollback()


def update_data_process():
    """
    数据更新处理函数：连接数据库并更新 today 字段
    """
    try:
        # 获取数据库连接
        connection = get_db_connection()
        logger.info("成功连接到数据库")
        
        # 更新 today 字段
        update_current_answer(connection)
        
        # 关闭数据库连接
        connection.close()
        logger.info("数据库连接已关闭")
        
        return {"status": "success", "message": "成功更新 today 字段"}
        
    except Exception as e:
        error_msg = f"执行过程中出错: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}


def main_handler(event, context):
    """
    云函数入口函数
    
    该函数设计为由定时触发器每 5 秒触发一次，每次更新 today 字段
    要实现每 5 秒更新一次，持续 1 分钟，请在设置定时触发器时配置为：
    - 触发周期：每 5 秒触发一次（配置 cron 表达式为 "*/5 * * * * *"）
    - 触发次数：配置为 12 次（或者手动停止）
    
    Args:
        event: 触发事件
        context: 函数上下文
        
    Returns:
        JSON格式的执行结果
    """
    logger.info(f"收到请求: {json.dumps(event, ensure_ascii=False)}")
    
    # 执行数据更新流程
    result = update_data_process()
    
    return result
