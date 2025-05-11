#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头像数据查询
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import query_wx_sql
from utils.wechat_channl import get_wx_self_info


DAG_ID = "wx_avatars_watcher"


def save_wx_avatars_to_variable(**context):
    """
    获取并缓存微信昵称和头像数据
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息数量: {len(wx_account_list)}")

    for wx_account in wx_account_list:
        print(f"开始处理微信账号: {wx_account['name']}")
        try:
            # 获取WCF服务器IP和端口
            wcf_ip = wx_account['source_ip']

            # 获取当前登录账号信息
            self_info = get_wx_self_info(wcf_ip)
            print(f"当前登录账号信息: {self_info}")
            
            # 获取微信联系人的头像和昵称等信息
            db = "MicroMsg.db"
            sql = "select * from ContactHeadImgUrl"
            contact_head_img_url_infos = query_wx_sql(wcf_ip, db, sql)
            print(f"获取到联系人信息数量: {len(contact_head_img_url_infos)}")        
            
            # 更新账号列表
            updated_account_list = []
            
            # 添加自己的信息
            if self_info:  # 确保self_info不为空
                self_account = {
                    # "usrName": self_info.get("name", ""),
                    "wxid": self_info.get("wxid", ""),
                    "smallHeadImgUrl": self_info.get("small_head_url", ""),
                    "bigHeadImgUrl": self_info.get("big_head_url", ""),
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                updated_account_list.append(self_account)
            
            # 添加联系人信息
            for contact_head_img_url_info in contact_head_img_url_infos:
                account = {
                    # "wxid": contact.get("wxid", ""),
                    "wxid": contact_head_img_url_info.get("usrName", ""),
                    "smallHeadImgUrl": contact_head_img_url_info.get("smallHeadImgUrl",""),            
                    "bigHeadImgUrl": contact_head_img_url_info.get("bigHeadImgUrl",""),               
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                updated_account_list.append(account)
            print(f"更新后的账号信息数量: {len(updated_account_list)}")
            
            save_variable_name = f"{self_info['name']}_{self_info['wxid']}_CONTACT_LIST"
            Variable.set(save_variable_name, updated_account_list, serialize_json=True)
            print(f"成功更新微信联系人昵称头像信息到变量: {save_variable_name}")
        except Exception as e:
            print(f"{wx_account['name']}获取微信联系人昵称头像等数据失败: {str(e)}")


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'retries': 3,  # 增加重试次数
        'retry_delay': timedelta(minutes=1),  # 重试间隔
    },
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=60), # 刷新间隔时间
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),  # 增加超时时间
    catchup=False,
    tags=['个人微信'],
    description='个人微信账号监控',
)

# 创建处理缓存微信头像的任务
save_wx_avatars_to_variable_task = PythonOperator(
    task_id='save_wx_avatars_to_variable',
    python_callable=save_wx_avatars_to_variable,
    provide_context=True,
    dag=dag
)