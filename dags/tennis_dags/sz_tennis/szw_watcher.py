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
import re
import requests
from typing import List

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

SZW_MATRIX_API_URL = "https://wlhmobile.crland.com.cn/business/client/field/area/matrix"
SZW_HOST = "wlhmobile.crland.com.cn"
SZW_APP_ID = "wx020209beec4251e0"
SZW_PROJECT_UUID = "3a59e62a07f811f1bec0aeefcf2e061a"
SZW_FIELD_AREA_UUID = "b7f8a0770a4d11f198f45a68b1262c30"

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


def extract_time_hhmm(time_value: str) -> str:
    """从接口时间字段中提取 HH:MM。"""
    if not time_value:
        return ""

    matched = re.search(r"\d{2}:\d{2}", str(time_value))
    if matched:
        return matched.group(0)
    return ""

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
    szw_authorization = Variable.get("SZW_API_AUTHORIZATION", default_var="").strip()
    if not szw_authorization:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 未配置")
    if "\n" in szw_authorization or "\r" in szw_authorization:
        raise ValueError("Airflow Variable SZW_API_AUTHORIZATION 格式非法")

    got_response = False
    response_data = None
    last_error = None

    for proxy in proxy_list:
        payload = {
            "fieldAreaUuid": SZW_FIELD_AREA_UUID,
            "reserveDate": date,
            "enterpriseUuid": "",
            "discountSpecUuid": "",
            "projectUuid": SZW_PROJECT_UUID,
        }
        headers = {
            "Host": SZW_HOST,
            "appid": SZW_APP_ID,
            "authorization": szw_authorization,
            "projectuuid": SZW_PROJECT_UUID,
            "xweb_xhr": "1",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 "
                          "Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
                          "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF "
                          "MacWechat/3.8.7(0x13080712) UnifiedPCMacWechat(0xf2641739) XWEB/18926",
            "accept": "*/*",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://servicewechat.com/wx020209beec4251e0/15/page-frame.html",
            "accept-language": "zh-CN,zh;q=0.9",
        }
        request_kwargs = {
            "headers": headers,
            "json": payload,
            "timeout": 15,
        }
        if proxy and proxy != "不使用代理":
            request_kwargs["proxies"] = {"https": proxy}

        print(f"trying for {proxy}")
        try:
            print(f"data: {payload}")
            response = requests.post(SZW_MATRIX_API_URL, **request_kwargs)
            print(f"response status_code: {response.status_code}")
            if response.status_code == 200:
                try:
                    response_data = response.json()
                except Exception as e:
                    last_error = f"invalid json response: {e}"
                    print(last_error)
                    continue
                if response_data.get("code") == 200 and response_data.get("result"):
                    print(f"api success, text: {response_data.get('text')}")
                    got_response = True
                    time.sleep(1)
                    break
                last_error = f"api error code={response_data.get('code')}, text={response_data.get('text')}"
                print(f"api error for {proxy}: {last_error}")
            else:
                last_error = f"http status code={response.status_code}"
                print(f"failed for {proxy}: {last_error}")
                continue
        except Exception as error:
            last_error = str(error)
            print(f"failed for {proxy}: {last_error}")
            continue

    if got_response and response_data:
        result = response_data["result"]
        venue_name_infos = {
            venue["fieldUuid"]: venue["fieldName"]
            for venue in result.get("fieldList", [])
        }
        print(venue_name_infos)

        booked_court_infos = {}

        for venue_info in result.get("matrix", []):
            venue_name = venue_name_infos.get(venue_info.get("fieldUuid"))
            if not venue_name:
                continue
            booked_court_infos.setdefault(venue_name, [])

            for slot_info in venue_info.get("matrix", []):
                if slot_info.get("isAbleReserve"):
                    continue

                start_time = extract_time_hhmm(slot_info.get("startTime", ""))
                end_time = extract_time_hhmm(slot_info.get("endTime", ""))
                if len(start_time) != 5 or len(end_time) != 5:
                    continue
                booked_court_infos[venue_name].append([start_time, end_time])

        available_slots_infos = {}
        for venue_name, booked_slots in booked_court_infos.items():
            available_slots = find_available_slots(booked_slots, time_range)
            if available_slots:
                available_slots_infos[venue_name] = available_slots
        return available_slots_infos
    else:
        raise Exception(f"all attempts failed: {last_error}")


def check_and_notify_for_day(day_offset: int):
    """检查指定天数后的网球场可用情况并发送通知

    Args:
        day_offset: 相对于今天的偏移天数（0表示今天，1表示明天，以此类推）
    """
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print(f"Day {day_offset}: 每天0点-8点不巡检")
        return

    run_start_time = time.time()
    input_date = (datetime.datetime.now() + datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
    inform_date = (datetime.datetime.now() + datetime.timedelta(days=day_offset)).strftime('%m-%d')
    print_with_timestamp(f"Checking tennis courts for {input_date}...")    

    # 使用可用代理查询空闲的球场信息
    up_for_send_data_list = []
    try:
        time_range = {"start_time": "08:30","end_time": "22:30"}
        court_data = get_free_tennis_court_infos_for_szw(input_date, ["不使用代理"], time_range)
        print(f"{input_date} court_data: {court_data}")

        for court_name, free_slots in court_data.items():
            if free_slots:
                filtered_slots = []
                check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                is_weekend = check_date.weekday() >= 5

                for slot in free_slots:
                    hour_num = int(slot[0].split(':')[0])
                    if is_weekend:
                        if 16 <= hour_num <= 21:  # 周末关注16点到21点的场地
                            filtered_slots.append(slot)
                    else:
                        if 18 <= hour_num <= 21:  # 工作日关注18点到21点的场地
                            filtered_slots.append(slot)

                if filtered_slots:
                    up_for_send_data_list.append({
                        "date": inform_date,
                        "court_name": f"深圳湾{court_name}",
                        "free_slot_list": filtered_slots
                    })
    except Exception as e:
        print(f"Error checking date {input_date}: {str(e)}")

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

        if up_for_send_msg_list:
            all_in_one_msg = "\n".join(up_for_send_msg_list)

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
                            subject=f"【{data['court_name']}】星期{weekday_str} {data['start_time']} - {data['end_time']}",
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
    print_with_timestamp(f"Day {day_offset} ({input_date}) completed in {execution_time:.2f}s")

# 创建DAG
dag = DAG(
    '深圳湾网球场巡检',
    default_args=default_args,
    description='深圳湾网球场巡检（并行多天）',
    schedule_interval=timedelta(seconds=15),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=['深圳']
)

# 动态创建巡检和通知任务（每天一个独立任务，并行执行）
for day_offset in range(4):  # 巡检今天到未来3天，共4天
    task = PythonOperator(
        task_id=f'check_and_notify_day_{day_offset}',
        python_callable=check_and_notify_for_day,
        op_kwargs={'day_offset': day_offset},
        dag=dag,
    )
    # 每个任务独立执行，互不依赖


# # 测试
# if __name__ == "__main__":
#     data = get_free_tennis_court_infos_for_szw("2025-02-15", ["34.215.74.117:1080"], {"start_time": "08:00", "end_time": "22:00"})
#     for court_name, free_slots in data.items():
#         print(f"{court_name}: {free_slots}")
