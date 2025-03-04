#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
昵称数据查询
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import get_wx_contact_list, get_wx_self_info, check_wx_login


DAG_ID = "wx_alias_watcher"


def save_wx_alias_to_variable(**context):
    """
    获取并缓存微信昵称数据
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息数量: {len(wx_account_list)}")

    # 获取WCF服务器IP
    wcf_ip = Variable.get("WCF_SERVER_IP")
    
    try:
        # 检查微信登录状态
        if not check_wx_login(wcf_ip):
            print("微信未登录")
            return
            
        # 获取当前登录账号信息
        self_info = get_wx_self_info(wcf_ip)
        print(f"当前登录账号信息: {self_info}")
        
        # 获取联系人列表
        contacts = get_wx_contact_list(wcf_ip)
        print(f"获取到联系人数量: {len(contacts)}")
        
        # 更新账号列表
        updated_account_list = []
        
        # 添加自己的信息
        self_account = {
            "wxid": self_info.get("wxid", ""),
            "nickname": self_info.get("nickname", ""),
            "avatar": self_info.get("avatar", ""),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        updated_account_list.append(self_account)
        
        # 添加联系人信息
        for contact in contacts:
            if not contact.get("wxid"):  # 跳过无效数据
                continue
                
            account = {
                "wxid": contact.get("wxid", ""),
                "nickname": contact.get("nickname", ""),
                "avatar": contact.get("avatar", ""),
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            updated_account_list.append(account)
        
        print(f"更新后的账号信息数量: {len(updated_account_list)}")
        
        # 更新Variable中的数据
        Variable.set("WX_ACCOUNT_LIST", updated_account_list, serialize_json=True)
        
    except Exception as e:
        print(f"获取微信昵称数据失败: {str(e)}")
        raise e


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=15),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=['个人微信'],
    description='个人微信账号监控',
)

# 创建处理缓存微信昵称的任务
save_wx_alias_to_variable_task = PythonOperator(
    task_id='save_wx_alias_to_variable',
    python_callable=save_wx_alias_to_variable,
    provide_context=True,
    dag=dag
)
