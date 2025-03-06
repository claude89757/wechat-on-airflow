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
from airflow.utils.decorators import apply_defaults
from tenacity import retry, stop_after_attempt, wait_exponential

# 自定义库导入
from utils.wechat_channl import query_wx_sql, get_wx_contact_list, get_wx_self_info, check_wx_login


DAG_ID = "wx_avatars_watcher"


def save_wx_avatars_to_variable(**context):
    """
    获取并缓存微信昵称和头像数据
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息数量: {len(wx_account_list)}")

    try:
        # 获取WCF服务器IP和端口
        wcf_ip = Variable.get("WCF_IP", default_var="10.1.12.10")
        wcf_port = Variable.get("WCF_API_PORT", default_var="9999")
        print(f"使用WCF服务器: {wcf_ip}:{wcf_port}")
        
        # 检查WCF服务是否可用
        try:
            if not check_wcf_availability(wcf_ip, wcf_port):
                error_msg = f"WCF服务不可用 ({wcf_ip}:{wcf_port})"
                print(error_msg)
                context['task_instance'].xcom_push(key='error', value=error_msg)
                return
        except Exception as e:
            error_msg = f"检查WCF服务可用性失败: {str(e)}"
            print(error_msg)
            context['task_instance'].xcom_push(key='error', value=error_msg)
            return
            
        # 检查微信登录状态
        if not check_wx_login(wcf_ip):
            error_msg = "微信未登录，跳过头像更新"
            print(error_msg)
            context['task_instance'].xcom_push(key='error', value=error_msg)
            return
            
        # 获取当前登录账号信息
        self_info = get_wx_self_info(wcf_ip)
        print(f"当前登录账号信息: {self_info}")
        
        # 获取微信联系人的头像和昵称等信息
        db = "MicroMsg.db"
        sql = "select * from ContactHeadImgUrl"
        contacts_info = query_wx_sql(wcf_ip, db, sql)
        print(f"获取到联系人信息数量: {len(contacts_info)}")        

        # 获取联系人列表
        # contacts = get_wx_contact_list(wcf_ip)  
        # print(f"获取到联系人数量: {len(contacts)}")
        
        # 更新账号列表
        updated_account_list = []
        
        # 添加自己的信息
        if self_info:  # 确保self_info不为空
            self_account = {
                "wxid": self_info.get("wxid", ""),
                "name": self_info.get("name", ""),
                "smallHeadImgUrl": self_info.get("small_head_url", ""),
                "bigHeadImgUrl": self_info.get("big_head_url", ""),
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            updated_account_list.append(self_account)
        
        # 添加联系人信息
        for contact in contacts_info:
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
        
        if updated_account_list:  # 只在有数据时更新Variable
            save_variable_name = self_account.get("name","")+"_CONTACT_LIST"
            Variable.set(save_variable_name, updated_account_list, serialize_json=True)
            print(f"成功更新微信联系人昵称头像信息到变量: {save_variable_name}")
        else:
            print("无有效账号信息，跳过更新")
            
    except Exception as e:
        error_msg = f"获取微信联系人昵称头像等数据失败: {str(e)}"
        print(error_msg)
        context['task_instance'].xcom_push(key='error', value=error_msg)


def check_wcf_availability(wcf_ip: str, wcf_port: str, timeout: int = 5) -> bool:
    """
    检查WCF服务是否可用
    
    Args:
        wcf_ip: WCF服务器IP
        wcf_port: WCF服务器端口
        timeout: 连接超时时间(秒)
    Returns:
        bool: 服务是否可用
    """
    import socket
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((wcf_ip, int(wcf_port)))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"检查WCF服务可用性时发生错误: {str(e)}")
        return False


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'retries': 3,  # 增加重试次数
        'retry_delay': timedelta(minutes=1),  # 重试间隔
    },
    start_date=datetime(2024, 1, 1),
    schedule_interval=timedelta(minutes=2), # 刷新间隔时间
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=5),  # 增加超时时间
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