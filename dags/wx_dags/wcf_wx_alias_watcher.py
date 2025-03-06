#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
昵称数据查询
"""

# 标准库导入
from datetime import datetime, timedelta
import os

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import query_wx_sql, get_wx_contact_list, get_wx_self_info, check_wx_login


DAG_ID = "wx_alias_watcher"


def save_wx_alias_to_variable(**context):
    """
    获取并缓存微信昵称数据
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息数量: {len(wx_account_list)}")

    try:
        # 获取WCF服务器IP,使用环境变量作为备选
        wcf_ip = Variable.get(
            "WCF_IP", 
            default_var=os.getenv("WCF_IP")
        )
        if not wcf_ip:
            error_msg = (
                "未找到WCF服务器IP配置。请执行以下操作之一:\n"
                "1. 在Airflow变量中配置 WCF_SERVER_IP\n"
                "2. 设置环境变量 WCF_SERVER_IP"
            )
            print(error_msg)  # 打印错误信息
            return  # 直接返回而不是抛出异常
            
        # 获取WCF服务器端口
        wcf_port = os.getenv("WCF_API_PORT", "9999")
        
        # 检查WCF服务器是否可访问
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)  # 3秒超时
            result = sock.connect_ex((wcf_ip, int(wcf_port)))
            if result != 0:
                raise ConnectionError(
                    f"无法连接到WCF服务器 {wcf_ip}:{wcf_port}\n"
                    "请检查:\n"
                    "1. 服务器IP地址是否正确\n"
                    "2. 服务器是否已启动\n"
                    "3. 端口是否开放"
                )
        except Exception as e:
            raise ConnectionError(f"检查WCF服务器连接失败: {str(e)}")
        finally:
            sock.close()
            
        # 检查微信登录状态
        try:
            if not check_wx_login(wcf_ip):
                print("微信未登录")
                return
        except Exception as e:
            raise ConnectionError(f"检查微信登录状态失败: {str(e)}")
            
        # 获取当前登录账号信息
        try:
            self_info = get_wx_self_info(wcf_ip)
            print(f"当前登录账号信息: {self_info}")
        except Exception as e:
            raise RuntimeError(f"获取当前账号信息失败: {str(e)}")
        
        # 获取联系人列表
        try:
            db = "MicroMsg.db"
            sql = "select * from ContactHeadImgUrl"
            contacts = query_wx_sql(wcf_ip, db, sql)
            print(f"获取到联系人信息数量: {len(contacts)}")
        except Exception as e:
            raise RuntimeError(f"获取联系人列表失败: {str(e)}")
        
        # 更新账号列表
        updated_account_list = []
        
        # 添加自己的信息
        self_account = {
            "wxid": self_info.get("wxid", ""),
            "usrName": self_info.get("name", ""),
            "smallHeadImgUrl": self_info.get("small_head_url", ""),
            "bigHeadImgUrl": self_info.get("big_head_url", ""),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        updated_account_list.append(self_account)
        
        # 添加联系人信息
        for contact in contacts:
            # if not contact.get("wxid"):  # 跳过无效数据
            #     continue
                
            account = {
                # "wxid": contact.get("wxid", ""),
                "usrName": contact.get("usrName", ""),
                "headImgMd5": contact.get("headImgMd5",""),
                "smallHeadImgUrl": contact.get("smallHeadImgUrl",""),            
                "bigHeadImgUrl": contact.get("bigHeadImgUrl",""),               
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            updated_account_list.append(account)
        
        print(f"更新后的账号信息数量: {len(updated_account_list)}")
                
        # 更新Variable中的数据
        if updated_account_list:  # 只在有数据时更新Variable
            # save_variable_name = self_account.get("name","")+"_CONTACT_LIST"
            save_variable_name = "WX_CONTACT_LIST"
            Variable.set(save_variable_name, updated_account_list, serialize_json=True)
            print(f"成功更新微信昵称数据信息到变量: {save_variable_name}")
        else:
            print("无有效账号信息，跳过更新")
        
    except Exception as e:
        error_msg = f"获取微信昵称数据失败: {str(e)}"
        print(error_msg)
        # 这里我们不再抛出新的异常，而是直接返回
        return


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=60),
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
