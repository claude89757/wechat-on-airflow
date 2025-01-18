#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from redis import Redis

# 连接到Airflow的Redis
airflow_redis = Redis(host='airflow_redis', port=6379, decode_responses=True)
