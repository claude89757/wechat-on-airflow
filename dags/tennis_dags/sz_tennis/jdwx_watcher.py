#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : jdwx_watcher.py
@Software: PyCharm
"""
import time
import datetime
import requests
import random

from typing import List
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from tennis_dags.utils.tencent_sms import send_sms_for_news
from tennis_dags.utils.tencent_ses import send_template_email


# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'start_date': datetime.datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
}

def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """将时间段合并"""
    if not data:
        return data
    
    print(f"merging {data}")
    data_in_minutes = sorted([(int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:]))
                              for start, end in data])

    merged_data = []
    start, end = data_in_minutes[0]
    for i in range(1, len(data_in_minutes)):
        next_start, next_end = data_in_minutes[i]
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged_data.append((start, end))
            start, end = next_start, next_end
    merged_data.append((start, end))

    result = [[f'{start // 60:02d}:{start % 60:02d}', f'{end // 60:02d}:{end % 60:02d}'] for start, end in merged_data]
    print(f"merged {result}")
    return result

def update_proxy_cache(proxy: str, success: bool):
    """更新代理缓存"""
    cache_key = "JDWX_PROXY_CACHE"
    try:
        cached_proxies = Variable.get(cache_key, deserialize_json=True, default_var=[])
    except:
        cached_proxies = []
    
    if success:
        # 成功的代理加入缓存（如果不存在的话）
        if proxy not in cached_proxies:
            cached_proxies.insert(0, proxy)  # 插入到最前面
            cached_proxies = cached_proxies[:10]  # 保持最多10个
            print(f"添加成功代理到缓存: {proxy}")
    else:
        # 失败的代理从缓存中移除
        if proxy in cached_proxies:
            cached_proxies.remove(proxy)
            print(f"从缓存中移除失败代理: {proxy}")
    
    Variable.set(cache_key, cached_proxies, serialize_json=True)
    return cached_proxies

def get_free_tennis_court_infos_for_hjd(date: str, proxy_list: list) -> dict:
    """从弘金地获取可预订的场地信息"""
    got_response = False
    response = None
    successful_proxy = None
    
    # 获取缓存的代理
    cache_key = "JDWX_PROXY_CACHE"
    try:
        cached_proxies = Variable.get(cache_key, deserialize_json=True, default_var=[])
    except:
        cached_proxies = []
    
    print(f"缓存的代理数量: {len(cached_proxies)}")
    
    # 准备代理列表：优先使用缓存的代理，然后是其他代理
    remaining_proxies = [p for p in proxy_list if p not in cached_proxies]
    random.shuffle(remaining_proxies)
    all_proxies_to_try = cached_proxies + remaining_proxies
    
    print(f"总共尝试代理数量: {len(all_proxies_to_try)} (缓存: {len(cached_proxies)}, 其他: {len(remaining_proxies)})")
    
    params = {
        "gymId": "1479063349546192897",
        "sportsType": "1",
        "reserveDate": date
    }
    headers = {
        "Host": "gateway.gemdalesports.com",
        "referer": "https://servicewechat.com/wxf7ae96551d92f600/34/page-frame.html",
        "xweb_xhr": "1",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/"
                      "98.0.4758.102 Safari/537.36 MicroMessenger/6.8.0(0x16080000)"
                      " NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF XWEB/30626",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty"
    }
    url = "https://gateway.gemdalesports.com/inside-frontend/api/field/fieldReserve"
    
    for index, proxy in enumerate(all_proxies_to_try):
        is_cached_proxy = proxy in cached_proxies
        print(f"尝试第 {index + 1} 个代理: {proxy} {'(缓存)' if is_cached_proxy else '(新)'}")
        
        try:
            proxies = {"https": proxy}
            response = requests.get(url, headers=headers, params=params, proxies=proxies, verify=False, timeout=5)
            if response.status_code == 200 and response.json()['success']:
                print(f"代理成功: {proxy}")
                print("--------------------------------")
                print(response.text)
                print(response.json())
                print("--------------------------------")
                got_response = True
                successful_proxy = proxy
                time.sleep(1)
                break
            else:
                print(f"代理失败: {proxy}, 响应: {response}")
                # 更新代理缓存：标记为失败
                update_proxy_cache(proxy, False)
                continue
        except Exception as error:
            print(f"代理异常: {proxy}, 错误: {error}")
            # 更新代理缓存：标记为失败
            update_proxy_cache(proxy, False)
            continue
    
    # 如果成功，更新代理缓存
    if successful_proxy:
        update_proxy_cache(successful_proxy, True)

    if got_response and response:
        if response.json()['data'].get('array'):
            available_slots_infos = {}
            for file_info in response.json()['data']['array']:
                available_slots = []
                for slot in file_info['daySource']:
                    if slot['occupy']:  # 这里是特殊的逻辑, occupy为True表示空闲
                        available_slots.append([slot['startTime'], slot['endTime']])
                available_slots_infos[file_info['fieldName']] = merge_time_ranges(available_slots)
            print(f"available_slots_infos: {available_slots_infos}")
            return available_slots_infos
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

    # 获取代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    response = requests.get(url)
    text = response.text.strip()
    proxy_list = [line.strip() for line in text.split("\n")]
    random.shuffle(proxy_list)
    print(f"Loaded {len(proxy_list)} proxies from {url}")

    # 查询空闲的球场信息
    up_for_send_data_list = []
    for index in range(0, 2):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        print(f"checking {input_date}...")
        try:
            court_data = get_free_tennis_court_infos_for_hjd(input_date, proxy_list)
            
            # 打印网球场可预订场地详细信息
            print_with_timestamp(f"=== {input_date} 可预订场地详细信息 ===")
            if court_data:
                for court_name, free_slots in court_data.items():
                    print_with_timestamp(f"【{court_name}】:")
                    if free_slots:
                        for slot in free_slots:
                            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                            end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                            duration_minutes = (end_time - start_time).total_seconds() / 60
                            print_with_timestamp(f"  - {slot[0]}-{slot[1]} (时长: {int(duration_minutes)}分钟)")
                    else:
                        print_with_timestamp("  - 无可预订时间段")
            else:
                print_with_timestamp("无可预订场地数据")
            print_with_timestamp("=" * 50)
            
            time.sleep(1)
            
            for court_name, free_slots in court_data.items():
                if free_slots:
                    filtered_slots = []
                    check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                    is_weekend = check_date.weekday() >= 5
                    
                    for slot in free_slots:                        
                        # 计算时间段长度（分钟）
                        start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                        end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                        duration_minutes = (end_time - start_time).total_seconds() / 60
                        
                        # 只处理1小时或以上的时间段
                        if duration_minutes < 60:
                            print(f"slot: {slot}, duration_minutes: {duration_minutes}, skip")
                            continue
                        else:
                            print(f"slot: {slot}, duration_minutes: {duration_minutes}, process")
                            
                        # 检查时间段是否与目标时间范围有重叠
                        start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                        end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                        
                        if is_weekend:
                            # 周末关注15点到22点的场地
                            target_start = datetime.datetime.strptime("16:00", "%H:%M")
                            target_end = datetime.datetime.strptime("22:00", "%H:%M")
                        else:
                            # 工作日关注18点到22点的场地
                            target_start = datetime.datetime.strptime("18:00", "%H:%M")
                            target_end = datetime.datetime.strptime("22:00", "%H:%M")
                        
                        # 判断时间段是否有重叠：max(start1, start2) < min(end1, end2)
                        if max(start_time, target_start) < min(end_time, target_end):
                            filtered_slots.append(slot)
                    
                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"威新{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue
    
    print(f"up_for_send_data_list: {up_for_send_data_list}")
    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = "金地威新网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        up_for_send_msg_list = []
        up_for_send_sms_list = []
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

        # # 获取微信发送配置
        # wcf_ip = Variable.get("WCF_IP", default_var="")
        # for chat_room_id in ["57497883531@chatroom", "38763452635@chatroom", "51998713028@chatroom"]:
        #     print(f"sending to {chat_room_id}")
        #     for msg in up_for_send_msg_list:
        #         send_wx_msg(
        #             wcf_ip=wcf_ip,
        #             message=msg,
        #             receiver=chat_room_id,
        #             aters=''
        #         )
        #         sended_msg_list.append(msg)
        #     time.sleep(30)

        if up_for_send_msg_list:
            all_in_one_msg = "\n".join(up_for_send_msg_list) 

            # # 发送短信
            # for data in up_for_send_sms_list:
            #     try:
            #         phone_num_list = Variable.get("JDWX_PHONE_NUM_LIST", default_var=[], deserialize_json=True)
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
                            template_id=33340,
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
        description = f"深圳金地网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-10:],
            description=description,
            serialize_json=True
        )
        print(f"updated {cache_key} with {sended_msg_list}")
    else:
        pass

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    '深圳金地网球场巡检',
    default_args=default_args,
    description='金地威新网球场巡检',
    schedule_interval=timedelta(seconds=30), 
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
