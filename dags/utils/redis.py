#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import List, Optional, Any, Dict, Union
import redis
import json
from airflow.hooks.base import BaseHook


class RedisHandler:
    def __init__(self, conn_id: str = 'wx_redis'):
        """
        初始化Redis处理器
        Args:
            conn_id: Airflow中配置的Redis连接ID
        """
        self.conn_id = conn_id
        self._client = None

    @property
    def client(self) -> redis.Redis:
        """获取Redis客户端连接"""
        if self._client is None:
            conn = BaseHook.get_connection(self.conn_id)
            self._client = redis.Redis(
                host=conn.host,
                port=conn.port,
                db=conn.extra_dejson.get('db', 0),
                decode_responses=True
            )
        return self._client


    def msg_list_append(self, key: str, value: Union[Dict, str], max_length: int = 100, expire_days: int = 30) -> bool:
        """
        消息列表追加：智能追加消息，支持最大长度限制和过期时间
        自动处理字典类型的数据（转换为JSON存储）
        Args:
            key: Redis键名
            value: 要追加的值（支持字典或字符串）
            max_length: 列表最大长度，超过时仅保留最新的N个值
            expire_days: 过期时间（天），默认30天
        Returns:
            bool: 操作是否成功
        """
        try:
            pipe = self.client.pipeline()
            
            # 如果是字典类型，转换为JSON字符串
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            
            # 追加新值到列表
            pipe.rpush(key, value)
            
            # 如果设置了最大长度，保留最新的N个值
            if max_length is not None:
                # 获取当前列表长度
                current_length = self.get_list_length(key)
                if current_length > max_length:
                    # 删除多余的旧值（从左侧删除）
                    pipe.ltrim(key, current_length - max_length, -1)
            
            # 设置过期时间（秒）
            expire_seconds = expire_days * 24 * 60 * 60
            pipe.expire(key, expire_seconds)
            
            # 执行所有操作
            pipe.execute()
            return True
            
        except Exception as e:
            print(f"消息列表追加操作失败: {str(e)}")
            return False

    def get_list_length(self, key: str) -> int:
        """获取列表长度"""
        try:
            return self.client.llen(key)
        except Exception as e:
            print(f"获取列表长度失败: {str(e)}")
            return 0
            
    def get_msg_list(self, key: str, start: int = 0, end: int = -1, auto_json: bool = True) -> List[Union[Dict, str]]:
        """
        读取消息列表数据，自动处理JSON格式
        Args:
            key: Redis键名
            start: 起始位置（默认0）
            end: 结束位置（默认-1，表示到列表末尾）
            auto_json: 是否自动解析JSON数据（默认True）
        Returns:
            List: 列表数据，如果auto_json为True，会尝试将JSON字符串转换为字典
        """
        try:
            data = self.client.lrange(key, start, end)
            if not auto_json:
                return data
            
            # 尝试解析JSON数据
            result = []
            for item in data:
                try:
                    # 尝试解析JSON
                    result.append(json.loads(item))
                except json.JSONDecodeError:
                    # 如果不是JSON格式，保持原样
                    result.append(item)
            return result
            
        except redis.RedisError as e:
            print(f"读取消息列表数据失败: {str(e)}")
            return []
        
    def append_msg_list(self, key: str, value: Union[Dict, str], max_length: int = 100, expire_days: int = 30) -> bool:
        """
        追加消息列表，包含过期时间和最大长度限制
        Args:
            key: Redis键名
            value: 要追加的值（支持字典或字符串）
            max_length: 列表最大长度，超过时仅保留最新的N个值
            expire_days: 过期时间（天），默认30天
        Returns:
            bool: 操作是否成功
        """
        try:
            pipe = self.client.pipeline()
            
            # 如果是字典类型，转换为JSON字符串
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
                
            # 追加新值到列表
            pipe.rpush(key, value)
            
            # 如果设置了最大长度，保留最新的N个值
            if max_length > 0:
                pipe.ltrim(key, -max_length, -1)
            
            # 设置过期时间（秒）
            if expire_days > 0:
                expire_seconds = expire_days * 24 * 60 * 60
                pipe.expire(key, expire_seconds)
            
            pipe.execute()
            return True
        except redis.RedisError as e:
            print(f"追加消息列表失败: {str(e)}")
            return False
    
    def delete_msg_key(self, key: str) -> bool:
        """
        删除消息键（原clear_msg_list）
        Args:
            key: Redis键名
        Returns:
            bool: 操作是否成功
        """
        try:
            self.client.delete(key)
            return True
        except redis.RedisError as e:
            print(f"删除Redis键失败: {str(e)}")
            return False
    
    def update_msg_list(self, key: str, values: List[Union[Dict, str]], max_length: int = 100, expire_days: int = 30) -> bool:
        """
        更新消息列表：完全替换当前列表内容
        Args:
            key: Redis键名
            values: 新的值列表（列表中的元素支持字典或字符串）
            max_length: 列表最大长度，超过时仅保留最新的N个值
            expire_days: 过期时间（天），默认30天
        Returns:
            bool: 操作是否成功
        """
        try:
            pipe = self.client.pipeline()
            
            # 删除原有列表
            pipe.delete(key)
            
            # 处理列表中的每个元素
            for item in values:
                # 如果是字典类型，转换为JSON字符串
                if isinstance(item, dict):
                    item = json.dumps(item, ensure_ascii=False)
                # 添加到列表
                pipe.rpush(key, item)
            
            # 如果设置了最大长度，保留最新的N个值
            if max_length is not None and len(values) > max_length:
                pipe.ltrim(key, 0, max_length - 1)
            
            # 设置过期时间（秒）
            expire_seconds = expire_days * 24 * 60 * 60
            pipe.expire(key, expire_seconds)
            
            # 执行所有操作
            pipe.execute()
            return True
            
        except Exception as e:
            print(f"更新消息列表操作失败: {str(e)}")
            return False
        
# 测试
if __name__ == "__main__":
    redis_handler = RedisHandler()
    redis_handler.append_msg_list("test_key", {"message": "Hello, World!"})
    print(redis_handler.get_msg_list("test_key"))
