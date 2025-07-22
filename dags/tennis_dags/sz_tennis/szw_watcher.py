#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : szw_watcher.py
@Software: PyCharm
"""
import time
import datetime
import requests
import random
from typing import List
import ssl
import urllib3
from urllib3.poolmanager import PoolManager

from tennis_dags.utils.tencent_ses import send_template_email
from tennis_dags.utils.tencent_sms import send_sms_for_news

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta


# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'start_date': datetime.datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def find_available_slots(booked_slots: List[List[str]], time_range: dict) -> List[List[str]]:
    """查找可用的时间段"""
    if not booked_slots:
        return [[time_range['start_time'], time_range['end_time']]]
    
    # 将时间转换为分钟
    booked_in_minutes = sorted([(int(start[:2]) * 60 + int(start[3:]), 
                                int(end[:2]) * 60 + int(end[3:]))
                               for start, end in booked_slots])
    
    start_minutes = int(time_range['start_time'][:2]) * 60 + int(time_range['start_time'][3:])
    end_minutes = int(time_range['end_time'][:2]) * 60 + int(time_range['end_time'][3:])
    
    available = []
    current = start_minutes
    
    for booked_start, booked_end in booked_in_minutes:
        if current < booked_start:
            available.append([
                f"{current // 60:02d}:{current % 60:02d}",
                f"{booked_start // 60:02d}:{booked_start % 60:02d}"
            ])
        current = max(current, booked_end)
    
    if current < end_minutes:
        available.append([
            f"{current // 60:02d}:{current % 60:02d}",
            f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
        ])
    
    return available

def get_legacy_session():
    class CustomHttpAdapter(requests.adapters.HTTPAdapter):
        def __init__(self, *args, **kwargs):
            self.poolmanager = None
            super().__init__(*args, **kwargs)

        def init_poolmanager(self, connections, maxsize, block=False):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.set_ciphers('DEFAULT@SECLEVEL=1')
            ctx.options |= 0x4  # 启用legacy renegotiation
            self.poolmanager = PoolManager(
                num_pools=connections,
                maxsize=maxsize,
                block=block,
                ssl_context=ctx
            )
    
    session = requests.Session()
    adapter = CustomHttpAdapter()
    session.mount('https://', adapter)
    return session

def get_free_tennis_court_infos_for_szw(date: str, proxy_list: list, time_range: dict) -> dict:
    """
    获取可预订的场地信息
    Args:
        date: 日期，格式为YYYY-MM-DD
        proxy_list: 代理列表
        time_range: 时间范围，格式为{"start_time": "HH:MM", "end_time": "HH:MM"}
    Returns:
        dict: 场地信息，格式为{场地名: [[开始时间, 结束时间], ...]}
    """
    szw_cookie = Variable.get("SZW_COOKIE", default_var="")
    got_response = False
    response = None
    
    session = get_legacy_session()
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 禁用不安全请求警告
    
    for proxy in proxy_list:
        data = {
            'VenueTypeID': 'd3bc78ba-0d9c-4996-9ac5-5a792324decb',
            'VenueTypeDisplayName': '',
            # 'IsGetPrice': 'true',
            # 'isApp': 'true',
            'billDay': {date},
            # 'webApiUniqueID': '811e68e7-f189-675c-228d-3739e48e57b2'
        }
        headers = {
            "Host": "program.springcocoon.com",
            "sec-ch-ua": "\" Not A;Brand\";v=\"99\", \"Chromium\";v=\"98\"",
            # "X-XSRF-TOKEN": "rs3gB5gQUqeG-YcaRXgB13JMlQAn9N4e_vS29wl-_HV5-MZb6gCL7eLhiC030tJP-cFa0c2qgK9UfSKuwLH5vhZK_
            # 2KYA_j7Df_NAn9ts9q3N0A9XIJe7vAXdhZLTaywn0VRMA2",
            "sec-ch-ua-mobile": "?0",
            # "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)
            # Chrome/98.0.4758.102 Safari/537.36 MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv
            # /Mac MacWechat/WMPF XWEB/30803",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua-platform": "\"macOS\"",
            "Origin": "https://program.springcocoon.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://program.springcocoon.com/szbay/AppVenue/VenueBill/"
                       "VenueBill?VenueTypeID=d3bc78ba-0d9c-4996-9ac5-5a792324decb",
            "Accept-Language": "zh-CN,zh",
            "Cookie": szw_cookie
        }
        url = 'https://program.springcocoon.com/szbay/api/services/app/VenueBill/GetVenueBillDataAsync'
        
        print(f"trying for {proxy}")
        try:
            print(f"data: {data}")
            print(f"headers: {headers}" )
            response = session.post(url, headers=headers, data=data, timeout=15, verify=False)
            print(f"response: {response.text}")
            if response.status_code == 200:
                try:
                    print(response.json())
                except Exception as e:
                    print(f"error: {e}")
                    continue
                got_response = True
                time.sleep(1)
                break
            else:
                print(f"failed for {proxy}: {response.text}")
                continue
        except Exception as error:
            print(f"failed for {proxy}: {error}")
            continue

    if got_response and response:
        if response.status_code == 200:
            if len(response.json()['result']) == 1:
                # 场地名称转换
                venue_name_infos = {}
                for venue in response.json()['result'][0]['listVenue']:
                    venue_name_infos[venue['id']] = venue['displayName']
                print(venue_name_infos)

                booked_court_infos = {}
                if response.json()['result'][0].get("listWebVenueStatus") \
                        and response.json()['result'][0]['listWebVenueStatus']:
                    for venue_info in response.json()['result'][0]['listWebVenueStatus']:
                        if str(venue_info.get('bookLinker')) == '可定' or str(venue_info.get('bookLinker')) == '可订':
                            pass
                        else:
                            start_time = str(venue_info['timeStartEndName']).split('-')[0]
                            end_time = str(venue_info['timeStartEndName']).split('-')[1]
                            venue_name = venue_name_infos[venue_info['venueID']]
                            if booked_court_infos.get(venue_name):
                                booked_court_infos[venue_name].append([start_time, end_time])
                            else:
                                booked_court_infos[venue_name] = [[start_time, end_time]]
                else:
                    if response.json()['result'][0].get("listWeixinVenueStatus") and \
                            response.json()['result'][0]['listWeixinVenueStatus']:
                        for venue_info in response.json()['result'][0]['listWeixinVenueStatus']:
                            if venue_info['status'] == 20:
                                start_time = str(venue_info['timeStartEndName']).split('-')[0]
                                end_time = str(venue_info['timeStartEndName']).split('-')[1]
                                venue_name = venue_name_infos[venue_info['venueID']]
                                if booked_court_infos.get(venue_name):
                                    booked_court_infos[venue_name].append([start_time, end_time])
                                else:
                                    booked_court_infos[venue_name] = [[start_time, end_time]]
                            else:
                                pass
                    else:
                        pass

                available_slots_infos = {}
                for venue_id, booked_slots in booked_court_infos.items():
                    available_slots = find_available_slots(booked_slots, time_range)
                    available_slots_infos[venue_id] = available_slots
                return available_slots_infos
            else:
                raise Exception(response.text)
        else:
            raise Exception(response.text)
    else:
        raise Exception("all proxies failed")


def check_tennis_courts():
    """主要检查逻辑"""
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return
    
    run_start_time = time.time()
    print_with_timestamp("start to check...")

    # 获取系统代理
    system_proxy = Variable.get("PROXY_URL", default_var="")
    if system_proxy:
        proxies = {"https": system_proxy}
    else:
        proxies = None

    # 获取代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    response = requests.get(url, proxies=proxies)
    text = response.text.strip()
    proxy_list = [line.strip() for line in text.split("\n")]    
    random.shuffle(proxy_list)

    # 设置查询时间范围
    time_range = {
        "start_time": "08:30",
        "end_time": "22:30"
    }

    # 使用可用代理查询空闲的球场信息
    up_for_send_data_list = []
    for index in range(0, 4):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        
        try:
            court_data = get_free_tennis_court_infos_for_szw(input_date, proxy_list, time_range)
            print(f"court_data: {court_data}")
            time.sleep(1)
            
            for court_name, free_slots in court_data.items():
                if free_slots:
                    filtered_slots = []
                    check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                    is_weekend = check_date.weekday() >= 5
                    
                    for slot in free_slots:
                        hour_num = int(slot[0].split(':')[0])
                        if is_weekend:
                            if 16 <= hour_num <= 21:  # 周末关注15点到21点的场地
                                filtered_slots.append(slot)
                        else:
                            if 18 <= hour_num <= 21:  # 工作日仍然只关注18点到21点的场地
                                filtered_slots.append(slot)
                    
                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"深圳湾{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue

    # 处理通知逻辑
    up_for_send_sms_list = []
    if up_for_send_data_list:
        cache_key = "深圳湾网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        up_for_send_msg_list = []
        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']
            
            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
            
            for free_slot in free_slot_list:
                notification = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                if notification not in sended_msg_list:
                    up_for_send_msg_list.append(notification)
                    up_for_send_sms_list.append({
                        "date": date,
                        "court_name": court_name,
                        "start_time": free_slot[0],
                        "end_time": free_slot[1]
                    })

        # 获取微信发送配置
        # wcf_ip = Variable.get("WCF_IP", default_var="")
        # for chat_room_id in ["38763452635@chatroom", "51998713028@chatroom"]:
        #     print(f"sending to {chat_room_id}")
        #     for msg in up_for_send_msg_list:
        #         send_wx_msg(
        #             wcf_ip=wcf_ip,
        #             message=msg,
        #             receiver=chat_room_id,
        #             aters=''
        #         )
        #         sended_msg_list.append(msg)
        #     time.sleep(10)

        if up_for_send_msg_list:
            all_in_one_msg = "\n".join(up_for_send_msg_list)

            # # 发送短信
            # for data in up_for_send_sms_list:
            #     try:
            #         phone_num_list = Variable.get("SZW_PHONE_NUM_LIST", default_var=[], deserialize_json=True)
            #         send_sms_for_news(phone_num_list, param_list=[data["date"], data["court_name"], data["start_time"], data["end_time"]])
            #     except Exception as e:
            #         print(f"Error sending sms: {e}")

            # 发送邮件
            try:
                email_list = Variable.get("SZW_EMAIL_LIST", default_var=[], deserialize_json=True)
                if email_list:
                    for data in up_for_send_sms_list:
                        date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{data['date']}", "%Y-%m-%d")
                        weekday = date_obj.weekday()
                        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
                        formatted_date = date_obj.strftime("%Y年%m月%d日")
                        
                        result = send_template_email(
                            subject=f"【{data['court_name']}】网球场空场通知",
                            template_id="33340",
                            template_data={
                                "COURT_NAME": data['court_name'],
                                "FREE_TIME": f"{formatted_date}(星期{weekday_str}) {data['start_time']}-{data['end_time']}"
                            },
                            recipients=email_list,
                            from_email="Zacks <tennis@zacks.com.cn>",
                            reply_to="tennis@zacks.com.cn",
                            trigger_type=1
                        )
                        print(result)
                        time.sleep(1)  # 避免发送过快
                else:
                    print("未配置邮件收件人列表 SZW_EMAIL_LIST")
            except Exception as e:
                print(f"发送邮件异常: {e}")

            # 发送微信消息
            chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
            zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
            chat_names_list = str(chat_names).splitlines()
            chat_names_list.insert(0, "Zacks_深圳湾")
            print(f"chat_names_list: {chat_names_list}")
            for contact_name in chat_names_list:
                zacks_up_for_send_msg_list.append({
                    "room_name": contact_name,
                    "msg": all_in_one_msg
                })
            Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
            
            sended_msg_list.extend(up_for_send_msg_list)

        # 更新Variable
        description = f"深圳湾网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-100:],
            description=description,
            serialize_json=True
        )
        print(f"updated {cache_key} with {sended_msg_list}")

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    '深圳湾网球场巡检',
    default_args=default_args,
    description='深圳湾网球场巡检',
    schedule_interval='*/1 * * * *',  # 每1分钟执行一次
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=['深圳']
)

# 创建任务
check_courts_task = PythonOperator(
    task_id='check_tennis_courts',
    python_callable=check_tennis_courts,
    dag=dag,
)

# 设置任务依赖关系
check_courts_task


# # 测试
# if __name__ == "__main__":
#     data = get_free_tennis_court_infos_for_szw("2025-02-15", ["34.215.74.117:1080"], {"start_time": "08:00", "end_time": "22:00"})
#     for court_name, free_slots in data.items():
#         print(f"{court_name}: {free_slots}")
