#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from contextlib import contextmanager
from redis import Redis

class RedisLock:
    """Redis分布式锁实现"""
    
    def __init__(self, lock_name, expire_seconds=60):
        """
        初始化Redis锁
        :param lock_name: 锁的名称
        :param expire_seconds: 锁的超时时间(秒)
        """
        self.redis = Redis(host='airflow_redis', port=6379, decode_responses=True)
        self.lock_name = f"lock:{lock_name}"
        self.expire_seconds = expire_seconds
        
    def acquire(self, blocking=True, timeout=None) -> bool:
        """
        获取锁
        :param blocking: 是否阻塞等待
        :param timeout: 等待超时时间(秒)
        :return: 是否成功获取锁
        """
        start_time = time.time()
        
        while True:
            # 尝试获取锁
            if self.redis.set(self.lock_name, "1", nx=True, ex=self.expire_seconds):
                return True
                
            if not blocking:
                return False
                
            if timeout is not None:
                if time.time() - start_time >= timeout:
                    return False
            
            time.sleep(0.1)  # 避免频繁请求Redis
            
    def release(self):
        """释放锁"""
        self.redis.delete(self.lock_name)
        
    @contextmanager
    def lock(self, blocking=True, timeout=None):
        """
        上下文管理器方式使用锁
        :param blocking: 是否阻塞等待
        :param timeout: 等待超时时间(秒)
        """
        try:
            if self.acquire(blocking, timeout):
                yield self
            else:
                raise TimeoutError("无法获取锁")
        finally:
            self.release()


# 使用示例:
"""
# 方式1: 使用 with 语句
with RedisLock("my_lock", expire_seconds=60).lock():
    # 需要加锁的代码
    pass

# 方式2: 手动控制
lock = RedisLock("my_lock")
try:
    if lock.acquire(blocking=True, timeout=10):
        # 需要加锁的代码
        pass
finally:
    lock.release()
"""

