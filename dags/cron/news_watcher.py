#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests
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
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=60)
        response.raise_for_status()

        print(response.headers)
        # pprint(response.json())
        data = response.json()

        return data['news']['value']
    except Exception as error:
        return [{"name": f"Ops, 我崩溃了: {error}", "url": "？"}]

def send_news(**context):
    """发送新闻消息到微信群"""
    # 从 conf 获取关键字，默认为"智能客服"
    keyword = context['dag_run'].conf.get('keyword', '智能客服') if context['dag_run'].conf else '智能客服'
    
    # current_hour = datetime.now().hour
    weekday_cn = "星期" + "一二三四五六日"[datetime.now().weekday()]
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 获取新闻
    news_list = get_bing_news_msg(query=keyword)
    
    # 组合消息
    msg_list = []
    for news_data in news_list:
        msg_list.append(f"{news_data['name']}")
        msg_list.append(f"{news_data.get('url')}\n")
    
    # 根据时间设置不同的问候语
    first_line = f"【每日资讯】 {weekday_cn} {date_str} \n关键字: {keyword} \n"
    
    # 组装最终消息
    if msg_list:
        msg_list.insert(0, first_line)
    else:
        msg_list.append(first_line)
        msg_list.append("好像没什么新闻o(╥﹏╥)o")
    msg = '\n'.join(msg_list)

    # 发送消息
    wcf_ip = Variable.get("WCF_IP")
    news_room_id_list = Variable.get("NEWS_ROOM_ID_LIST", deserialize_json=True, default_var=[])
    for room_id in news_room_id_list:
        send_wx_msg(wcf_ip=wcf_ip, message=msg, receiver=room_id, aters='')

# DAG 定义
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'news_watcher',  # 改为更通用的名称
    default_args=default_args,
    description='每天定时发送新闻',
    schedule_interval='0 6,18 * * *',  # 每天6点和18点执行
    catchup=False,
)

send_news_task = PythonOperator(
    task_id='send_news',
    python_callable=send_news,
    provide_context=True,  # 添加这行以支持传入 context
    dag=dag,
)
