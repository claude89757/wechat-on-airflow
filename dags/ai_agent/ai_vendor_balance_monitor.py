#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI供应商账号余量监控DAG

功能:
1. 定时监控各AI供应商(阿里云、腾讯云、Deepseek等)的账号余额
2. 当余额低于阈值时发送告警通知
3. 记录历史余额数据用于分析
"""

from datetime import datetime, timedelta
import json
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from airflow.hooks.base import BaseHook

# 定义常量
DAG_ID = "ai_vendor_balance_monitor"
ALERT_THRESHOLD = {
    "aliyun": 100,  # 阿里云余额告警阈值(元)
    "tencent": 100, # 腾讯云余额告警阈值(元) 
    "deepseek": 50  # Deepseek余额告警阈值(美元)
}

def check_aliyun_balance(**context):
    """检查阿里云账号余额"""
    try:
        # 获取阿里云访问凭证
        access_key = Variable.get("ALIYUN_ACCESS_KEY")
        secret_key = Variable.get("ALIYUN_SECRET_KEY") 
        
        # 调用阿里云API获取账户余额
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkbssopenapi.request.v20171214.QueryAccountBalanceRequest import QueryAccountBalanceRequest
        
        client = AcsClient(access_key, secret_key, 'cn-hangzhou')
        request = QueryAccountBalanceRequest()
        request.set_accept_format('json')
        
        response = client.do_action_with_exception(request)
        
        # 解析返回的结果
        result = json.loads(response)
        print("Response: ", str(result, encoding='utf-8'))

        # 获取可用余额(单位:元)
        balance = float(result['Data']['AvailableAmount'])
        
        # 记录余额数据
        save_balance_history("aliyun", balance)
        
        # 检查是否需要告警
        # if balance < ALERT_THRESHOLD["aliyun"]:
        #     send_alert(
        #         vendor="阿里云",
        #         balance=balance,
        #         threshold=ALERT_THRESHOLD["aliyun"],
        #         currency="CNY"
        #     )
            
        return balance
        
    except Exception as e:
        print(f"检查阿里云余额失败: {e}")
        raise

def check_tencent_balance(**context):
    """检查腾讯云账号余额"""
    try:
        # 获取腾讯云访问凭证
        secret_id = Variable.get("TENCENT_SECRET_ID")
        secret_key = Variable.get("TENCENT_SECRET_KEY")
        
        # 调用腾讯云API获取账户余额
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.billing.v20180709 import billing_client, models
        
        cred = credential.Credential(secret_id, secret_key)
        httpProfile = HttpProfile()
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        client = billing_client.BillingClient(cred, "ap-guangzhou", clientProfile)
        req = models.DescribeAccountBalanceRequest()
        
        resp = client.DescribeAccountBalance(req)

        # 解析返回的结果
        print("Response: ", str(resp, encoding='utf-8'))

        # 获取可用余额(单位:元)
        balance = float(resp.Balance) / 100
        
        # 记录余额数据
        save_balance_history("tencent", balance)
        
        # 检查是否需要告警
        # if balance < ALERT_THRESHOLD["tencent"]:
        #     send_alert(
        #         vendor="腾讯云",
        #         balance=balance,
        #         threshold=ALERT_THRESHOLD["tencent"],
        #         currency="CNY"
        #     )
            
        return balance
        
    except Exception as e:
        print(f"检查腾讯云余额失败: {e}")
        raise

def check_deepseek_balance(**context):
    """检查Deepseek账号余额"""
    try:
        # 获取Deepseek API key
        api_key = Variable.get("DEEPSEEK_API_KEY")
        
        # 调用Deepseek API获取账户余额
        import requests
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Deepseek API endpoint (需要替换为实际的API地址)
        url = "https://api.deepseek.com/user/balance"
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()

        # 解析返回的结果
        print("Response: ", str(result, encoding='utf-8'))
        
        # 获取可用余额(单位:美元)
        balance = float(result['available_amount'])
        
        # 记录余额数据
        save_balance_history("deepseek", balance)
        
        # 检查是否需要告警
        # if balance < ALERT_THRESHOLD["deepseek"]:
        #     send_alert(
        #         vendor="Deepseek",
        #         balance=balance,
        #         threshold=ALERT_THRESHOLD["deepseek"],
        #         currency="USD"
        #     )
            
        return balance
        
    except Exception as e:
        print(f"检查Deepseek余额失败: {e}")
        raise

def save_balance_history(vendor, balance):
    """保存余额历史记录到Airflow Variables"""
    try:
        # 变量名格式: AI_BALANCE_HISTORY_{供应商名称}
        var_name = f"AI_BALANCE_HISTORY_{vendor.upper()}"
        
        # 获取现有历史记录
        try:
            history = json.loads(Variable.get(var_name, default="[]"))
        except:
            history = []
            
        # 添加新记录
        new_record = {
            "balance": float(balance),
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        history.append(new_record)
        
        # 只保留最近30天的记录
        thirty_days_ago = datetime.now() - timedelta(days=30)
        history = [
            record for record in history 
            if datetime.strptime(record["check_time"], "%Y-%m-%d %H:%M:%S") > thirty_days_ago
        ]
        
        # 更新变量
        Variable.set(
            var_name,
            json.dumps(history, ensure_ascii=False)
        )
        
        print(f"保存{vendor}余额历史记录成功")
        
    except Exception as e:
        print(f"保存余额历史记录失败: {e}")

def send_alert(vendor, balance, threshold, currency):
    """发送告警通知"""
    try:
        # 获取企业微信机器人webhook地址
        webhook_url = Variable.get("WEWORK_ROBOT_WEBHOOK")
        
        # 构造告警消息
        message = f"""⚠️ AI供应商余额告警
        
            供应商: {vendor}
            当前余额: {balance} {currency}
            告警阈值: {threshold} {currency}
            检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

            请及时充值以确保服务正常运行!"""

        # 发送告警到企业微信
        requests.post(
            webhook_url,
            json={
                "msgtype": "text",
                "text": {"content": message}
            }
        )
        
        print(f"发送{vendor}余额告警成功")
        
    except Exception as e:
        print(f"发送告警失败: {e}")

# 创建DAG
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    dag_id=DAG_ID,
    default_args=default_args,
    description='监控AI供应商账号余额',
    # schedule_interval='0 */2 * * *',  # 每2小时执行一次
    schedule_interval='*/2 * * * *',  # 每2分钟执行一次
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['监控'],
)

# 创建任务
check_aliyun = PythonOperator(
    task_id='check_aliyun_balance',
    python_callable=check_aliyun_balance,
    provide_context=True,
    dag=dag,
)

check_tencent = PythonOperator(
    task_id='check_tencent_balance', 
    python_callable=check_tencent_balance,
    provide_context=True,
    dag=dag,
)

check_deepseek = PythonOperator(
    task_id='check_deepseek_balance',
    python_callable=check_deepseek_balance,
    provide_context=True,
    dag=dag,
)

# 设置任务依赖
[check_aliyun, check_tencent, check_deepseek] 