#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

from utils.wechat_channl import send_wx_msg


def get_bing_news_msg(query: str) -> list:
    """
    get data from bing
    This sample makes a call to the Bing Web Search API with a query and returns relevant web search.
    Documentation: https://docs.microsoft.com/en-us/bing/search-apis/bing-web-search/overview
    """
    # Add your Bing Search V7 subscription key and endpoint to your environment variables.
    bing_subscription_key = Variable.get("BING_NEW_KEY")
    if not bing_subscription_key:
        raise Exception("no BING_KEY!!!")

    endpoint = "https://api.bing.microsoft.com/v7.0/search"

    # Construct a request
    mkt = 'zh-HK'
    params = {'q': query, 'mkt': mkt, 'answerCount': 5, 'promote': 'News', 'freshness': 'Day'}
    headers = {'Ocp-Apim-Subscription-Key': bing_subscription_key}

    # Call the API
    print(f"query: {query}")
    print(f"params: {params}")
    print(f"headers: {headers}")
    response = requests.get(endpoint, headers=headers, params=params, timeout=60)
    print(f"response: {response.text}")
    
    response_json = response.json()
    print(json.dumps(response_json, ensure_ascii=False, indent=2))

    response.raise_for_status()
    data = response.json()
    
    if data.get('news'):
        return data['news']['value']
    else:
        return None


def format_news_message(news_list: list, keyword: str) -> str:
    """
    格式化新闻消息内容

    Args:
        news_list: 新闻数据列表
        keyword: 搜索关键词

    Returns:
        str: 格式化后的消息文本
    """
    weekday_cn = "星期" + "一二三四五六日"[datetime.now().weekday()]
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 组合消息
    msg_list = []
    header = f"【每日资讯】 {weekday_cn} {date_str} \n关键字: {keyword} \n"
    msg_list.append(header)
    
    if not news_list:
        msg_list.append("好像没什么新闻o(╥﹏╥)o")
    else:
        for news_data in news_list:
            msg_list.append(f"{news_data['name']}")
            msg_list.append(f"{news_data.get('url')}\n")
    
    return '\n'.join(msg_list)


def send_news(**context) -> None:
    """
    发送新闻消息到微信群

    从Bing新闻API获取指定关键词的新闻，并发送到配置的微信群。

    Args:
        **context: Airflow上下文参数字典

    Returns:
        None

    Raises:
        Exception: 当无法获取必要的Airflow变量时抛出
    """
    # 获取关键词，默认为"智能客服"
    keyword = (context['dag_run'].conf.get('keyword', '网球') 
              if context['dag_run'].conf 
              else '网球')
    
    # 获取新闻数据
    news_list = get_bing_news_msg(query=keyword)

    if not news_list:
        print(f"no news for {keyword}")
        return
    
    # 格式化消息
    msg = format_news_message(news_list, keyword)

    # 获取微信发送配置
    zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
    news_room_list = Variable.get("NEWS_ROOM_LIST", deserialize_json=True, default_var=[])
    print(f"news_room_list: {news_room_list}")
    for news_room in news_room_list:
        zacks_up_for_send_msg_list.append({
            "room_name": news_room['room_name'],
            "msg": msg
        })
    Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)

# DAG 定义
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
    'retry_delay': timedelta(minutes=1),
}

dag = DAG(
    'tennis_news_watcher',  # 改为更通用的名称
    default_args=default_args,
    description='每天定时发送新闻',
    schedule_interval='0 9,19 * * *',  # 每天9点和19点执行
    catchup=False,
)

send_news_task = PythonOperator(
    task_id='send_news',
    python_callable=send_news,
    provide_context=True,  # 添加这行以支持传入 context
    dag=dag,
)
