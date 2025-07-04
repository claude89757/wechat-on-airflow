#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/12/15
@Author  : claude89757
@File    : sy_watcher.py
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

from utils.tencent_sms import send_sms_for_news

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
    cache_key = "SY_PROXY_CACHE"
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

def get_free_tennis_court_infos_for_sy(date: str, proxy_list: list) -> dict:
    """从深圳地铁深云文体公园获取可预订的场地信息"""
    got_response = False
    response = None
    successful_proxy = None
    
    # 获取缓存的代理
    cache_key = "SY_PROXY_CACHE"
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
        "venueId": "31",
        "sportId": "55",
        "makeDate": date
    }
    headers = {
        "Host": "wtt.huangxuansoft.cn",
        "xweb_xhr": "1",
        "platform": "mp-weixin",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.10(0x13080a10) XWEB/1227",
        "tenantId": "1",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        # "Referer": "https://servicewechat.com/wx4ac7a768ffcdd5ce/21/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    url = "https://wtt.huangxuansoft.cn/api/mini/venue/make"
    
    for index, proxy in enumerate(all_proxies_to_try):
        is_cached_proxy = proxy in cached_proxies
        print(f"尝试第 {index + 1} 个代理: {proxy} {'(缓存)' if is_cached_proxy else '(新)'}")
        
        try:
            proxies = {"https": proxy}
            response = requests.get(url, headers=headers, params=params, proxies=proxies, verify=False, timeout=5)
            if response.status_code == 200:
                response_data = response.json()
                if response_data.get('code') == 20000:
                    print(f"代理成功: {proxy}")
                    print("--------------------------------")
                    print(response.text)
                    print(response_data)
                    print("--------------------------------")
                    got_response = True
                    successful_proxy = proxy
                    time.sleep(1)
                    break
                else:
                    print(f"代理失败: {proxy}, 响应码: {response_data.get('code')}")
                    update_proxy_cache(proxy, False)
                    continue
            else:
                print(f"代理失败: {proxy}, HTTP状态码: {response.status_code}")
                update_proxy_cache(proxy, False)
                continue
        except Exception as error:
            print(f"代理异常: {proxy}, 错误: {error}")
            update_proxy_cache(proxy, False)
            continue
    
    # 如果成功，更新代理缓存
    if successful_proxy:
        update_proxy_cache(successful_proxy, True)

    if got_response and response:
        response_data = response.json()
        if response_data.get('data', {}).get('list'):
            available_slots_infos = {}
            
            # 按场地分组时间段数据
            court_data = {}
            for slot_info in response_data['data']['list']:
                scene_name = slot_info['sceneName']
                if scene_name not in court_data:
                    court_data[scene_name] = []
                court_data[scene_name].append(slot_info)
            
            # 处理每个场地的可用时间段
            for court_name, slots in court_data.items():
                available_slots = []
                for slot in slots:
                    if slot['status'] == 'LOADING':  # LOADING表示可预订
                        available_slots.append([slot['makeTimeStart'], slot['makeTimeEnd']])
                available_slots_infos[court_name] = merge_time_ranges(available_slots)
            
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
        # return
    
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
            court_data = get_free_tennis_court_infos_for_sy(input_date, proxy_list)
            
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
                            # 周末关注15点到21点的场地
                            target_start = datetime.datetime.strptime("15:00", "%H:%M")
                            target_end = datetime.datetime.strptime("21:00", "%H:%M")
                        else:
                            # 工作日关注18点到21点的场地
                            target_start = datetime.datetime.strptime("18:00", "%H:%M")
                            target_end = datetime.datetime.strptime("21:00", "%H:%M")
                        
                        # 判断时间段是否有重叠：max(start1, start2) < min(end1, end2)
                        if max(start_time, target_start) < min(end_time, target_end):
                            filtered_slots.append(slot)
                    
                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"深云{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue
    
    print(f"up_for_send_data_list: {up_for_send_data_list}")
    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = "深圳地铁深云文体公园网球场"
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

        if up_for_send_msg_list:
            all_in_one_msg = "\n".join(up_for_send_msg_list) 

            # # 发送短信
            # for data in up_for_send_sms_list:
            #     try:
            #         phone_num_list = Variable.get("SY_PHONE_NUM_LIST", default_var=[], deserialize_json=True)
            #         send_sms_for_news(phone_num_list, param_list=[data["date"], data["court_name"], data["start_time"], data["end_time"]])
            #     except Exception as e:
            #         print(f"Error sending sms: {e}")

            # 发送微信消息
            chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
            zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
            for contact_name in str(chat_names).splitlines():
                zacks_up_for_send_msg_list.append({
                    "room_name": contact_name,
                    "msg": all_in_one_msg
                })
            Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
                    
            sended_msg_list.extend(up_for_send_msg_list)

        # 更新Variable
        description = f"深圳地铁深云文体公园网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
    '深圳地铁深云文体公园网球场巡检',
    default_args=default_args,
    description='深圳地铁深云文体公园网球场巡检',
    schedule_interval=timedelta(seconds=120), 
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