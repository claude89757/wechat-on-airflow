#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
获取深圳湾体育中心场地信息

Author: claude89757
Date: 2025-04-04
"""

import requests
import os
import json
import datetime
import re


def query_szw_venue_info(billDay: str):
    """
    查询深圳湾体育中心场地信息。

    Args:
        billDay: 查询日期，格式为 "YYYY-MM-DD"。

    Returns:
        dict: 格式化后的场地信息，格式适合大模型解读
    """
    cookie = os.environ.get("SZBAY_COOKIE")
    if not cookie:
        raise ValueError("环境变量 'SZBAY_COOKIE' 未设置。请设置该变量后重试。")

    url = "https://program.springcocoon.com/szbay/api/services/app/VenueBill/GetVenueBillDataAsync"

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
        "Cookie": cookie
    }

    data = {
        "VenueTypeID": "d3bc78ba-0d9c-4996-9ac5-5a792324decb",
        "VenueTypeDisplayName": "",
        "IsGetPrice": "true",
        # "isApp": "true",
        "billDay": billDay,
        # "webApiUniqueID": "90676cc1-4db1-dc97-5799-4e5e8833b1ad", # 注意：这个 ID 可能是动态生成的，可能需要调整
    }

    try:
        print(f"请求URL: {url}")
        print(f"请求头: {headers}")
        print(f"请求数据: {data}")
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status() # 检查 HTTP 请求是否成功 (状态码 2xx)
        # 尝试解析 JSON，如果内容不是有效的 JSON，会抛出 json.JSONDecodeError
        response_data = response.json()
        print(f"响应数据: {response_data}")
        
        # 格式化返回数据
        raw_venue_data = format_venue_data(response_data, billDay)
        
        # 将原始格式转换为适合大模型解读的格式
        return transform_to_model_friendly_format(raw_venue_data, billDay)
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        raise # 重新抛出异常，以便调用者可以处理
    except json.JSONDecodeError as e:
        print(f"无法解析 JSON 响应: {e}")
        print(f"响应内容: {response.text}")
        raise # 重新抛出异常
    except KeyError as e:
        print(f"解析数据时出错: {e}")
        print(f"响应内容: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
        raise

def parse_time_from_string(time_str):
    """
    从各种可能的时间字符串格式中提取时间（小时:分钟）
    
    Args:
        time_str: 时间字符串，可能是多种格式
        
    Returns:
        tuple: (小时, 分钟) 或者 None（如果解析失败）
    """
    # 处理ISO格式的时间 (如 "2025-04-04T11:30:00")
    iso_match = re.search(r'T(\d{2}):(\d{2})', time_str)
    if iso_match:
        hour = int(iso_match.group(1))
        minute = int(iso_match.group(2))
        return hour, minute
    
    # 处理标准时间格式 (如 "11:30")
    std_match = re.search(r'^(\d{1,2}):(\d{2})$', time_str.strip())
    if std_match:
        hour = int(std_match.group(1))
        minute = int(std_match.group(2))
        return hour, minute
    
    # 处理其他数字格式 (如 "1130")
    num_match = re.search(r'^(\d{1,2})(\d{2})$', time_str.strip())
    if num_match:
        hour = int(num_match.group(1))
        minute = int(num_match.group(2))
        return hour, minute
    
    return None

def format_venue_data(response_data, billDay):
    """
    格式化场地数据
    
    Args:
        response_data: API返回的原始数据
        billDay: 查询的日期
        
    Returns:
        dict: 格式化后的场地信息，格式为 {场地名: [[开始时间, 结束时间], ...]}
    """
    # 输出原始数据结构以进行调试
    print("返回的原始数据结构:")
    print(json.dumps(response_data, indent=2, ensure_ascii=False)[:1000] + "...")  # 只显示前1000个字符避免过长
    
    # 获取当前时间，用于过滤已过期的时间段
    current_datetime = datetime.datetime.now()
    current_date = current_datetime.date()
    query_date = datetime.datetime.strptime(billDay, '%Y-%m-%d').date()
    
    # 如果查询日期是今天，则需要过滤掉已经过去的时间
    is_today = query_date == current_date
    current_time = current_datetime.time() if is_today else None
    
    # print(f"当前日期: {current_date}, 查询日期: {query_date}, 是否为今天: {is_today}")
    if is_today:
        print(f"当前时间: {current_time.strftime('%H:%M')}, 将过滤掉已过去的时间段")
    
    # 初始化返回结果 - 使用与szw_watcher相同的格式
    available_court_infos = {}
    
    # 检查响应数据结构
    if not response_data.get('result') or len(response_data['result']) == 0:
        print("响应中没有result字段或result为空")
        return available_court_infos
    
    result = response_data['result'][0]
    
    # 打印result的所有顶级键，以便了解数据结构
    # print("Result包含的顶级键:", list(result.keys()))
    
    # 构建场地ID到名称的映射
    venue_name_map = {}
    if 'listVenue' in result:
        # print(f"找到listVenue，包含{len(result['listVenue'])}个场地")
        for venue in result['listVenue']:
            venue_name_map[venue['id']] = venue['displayName']
    else:
        # print("未找到listVenue字段")
        # 尝试其他可能的字段名
        for key in result.keys():
            if isinstance(result[key], list) and len(result[key]) > 0 and 'id' in result[key][0] and 'displayName' in result[key][0]:
                print(f"找到可能的场地列表字段: {key}")
                for venue in result[key]:
                    venue_name_map[venue['id']] = venue['displayName']
    
    # 收集已预订的时间段 - 按照szw_watcher.py的逻辑
    booked_court_infos = {}
    
    # 处理场地状态数据 - 优先使用listWebVenueStatus
    if 'listWebVenueStatus' in result and result['listWebVenueStatus']:
        print("处理listWebVenueStatus字段")
        
        for venue_status in result['listWebVenueStatus']:
            if 'venueID' not in venue_status:
                continue
                
            venue_id = venue_status['venueID']
            venue_name = venue_name_map.get(venue_id, f"未知场地_{venue_id}")
            
            # 获取时间信息
            time_start = None
            time_end = None
            
            # 尝试从各种可能的字段中获取时间信息
            if 'timeStartEndName' in venue_status:
                try:
                    time_start, time_end = venue_status['timeStartEndName'].split('-')
                    # 处理时间格式
                    time_start = format_time(time_start)
                    time_end = format_time(time_end)
                except:
                    pass
            elif 'startTime' in venue_status and 'endTime' in venue_status:
                time_start = format_time(venue_status['startTime'])
                time_end = format_time(venue_status['endTime'])
            
            if not time_start or not time_end:
                continue
            
            # 判断预订状态 - 参照szw_watcher.py的逻辑
            is_bookable = False
            if 'bookLinker' in venue_status:
                is_bookable = str(venue_status.get('bookLinker')) in ['可定', '可订']
            
            # 如果不可预订，添加到已预订列表
            if not is_bookable:
                if venue_name not in booked_court_infos:
                    booked_court_infos[venue_name] = []
                booked_court_infos[venue_name].append([time_start, time_end])
                
    # 如果listWebVenueStatus为空，尝试使用listWeixinVenueStatus
    elif 'listWeixinVenueStatus' in result and result['listWeixinVenueStatus']:
        print("处理listWeixinVenueStatus字段")
        
        for venue_status in result['listWeixinVenueStatus']:
            if 'venueID' not in venue_status:
                continue
                
            venue_id = venue_status['venueID']
            venue_name = venue_name_map.get(venue_id, f"未知场地_{venue_id}")
            
            # 获取时间信息
            time_start = None
            time_end = None
            
            # 尝试从各种可能的字段中获取时间信息
            if 'timeStartEndName' in venue_status:
                try:
                    time_start, time_end = venue_status['timeStartEndName'].split('-')
                    # 处理时间格式
                    time_start = format_time(time_start)
                    time_end = format_time(time_end)
                except:
                    pass
            elif 'startTime' in venue_status and 'endTime' in venue_status:
                time_start = format_time(venue_status['startTime'])
                time_end = format_time(venue_status['endTime'])
                
            if not time_start or not time_end:
                continue
            
            # 在微信接口中，status=20表示已预约，其他值表示可预约
            if venue_status.get('status') == 20:
                if venue_name not in booked_court_infos:
                    booked_court_infos[venue_name] = []
                booked_court_infos[venue_name].append([time_start, time_end])
    
    # 查找可用的时间段
    time_range = {
        "start_time": "08:30",
        "end_time": "22:30"
    }
    
    # 使用find_available_slots函数查找可用时间段
    for venue_name, booked_slots in booked_court_infos.items():
        available_slots = find_available_slots(booked_slots, time_range)
        
        # 过滤掉已过去的时间段
        if is_today:
            filtered_slots = []
            for slot in available_slots:
                start_hour, start_minute = map(int, slot[0].split(':'))
                slot_start_time = datetime.time(start_hour, start_minute)
                
                if slot_start_time > current_time:
                    filtered_slots.append(slot)
            available_slots = filtered_slots
        
        if available_slots:
            available_court_infos[venue_name] = available_slots
    
    return available_court_infos

def format_time(time_str):
    """格式化时间字符串为HH:MM格式"""
    time_tuple = parse_time_from_string(time_str)
    if time_tuple:
        hour, minute = time_tuple
        return f"{hour:02d}:{minute:02d}"
    return None

def find_available_slots(booked_slots, time_range):
    """
    查找可用的时间段，剔除小于1小时的时间段
    
    Args:
        booked_slots: 已预订的时间段列表，格式为[[开始时间,结束时间],...]
        time_range: 时间范围，格式为{"start_time": "HH:MM", "end_time": "HH:MM"}
        
    Returns:
        list: 可用的时间段列表（只包含大于或等于1小时的时间段），格式为[[开始时间,结束时间],...]
    """
    if not booked_slots:
        # 检查整个时间范围是否至少为1小时
        start_hour, start_minute = map(int, time_range['start_time'].split(':'))
        end_hour, end_minute = map(int, time_range['end_time'].split(':'))
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute
        
        if end_minutes - start_minutes >= 60:
            return [[time_range['start_time'], time_range['end_time']]]
        else:
            return []  # 时间段小于1小时，返回空列表
    
    # 将时间转换为分钟
    booked_in_minutes = []
    for start, end in booked_slots:
        try:
            start_hour, start_minute = map(int, start.split(':'))
            end_hour, end_minute = map(int, end.split(':'))
            start_minutes = start_hour * 60 + start_minute
            end_minutes = end_hour * 60 + end_minute
            booked_in_minutes.append((start_minutes, end_minutes))
        except:
            print(f"警告: 无法解析时间格式: {start}-{end}")
            continue
    
    booked_in_minutes.sort()  # 按开始时间排序
    
    # 转换时间范围
    start_hour, start_minute = map(int, time_range['start_time'].split(':'))
    end_hour, end_minute = map(int, time_range['end_time'].split(':'))
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    
    # 查找空闲时间段
    available = []
    current = start_minutes
    
    for booked_start, booked_end in booked_in_minutes:
        if current < booked_start:
            # 检查时间段是否至少为1小时
            if booked_start - current >= 60:
                available.append([
                    f"{current // 60:02d}:{current % 60:02d}",
                    f"{booked_start // 60:02d}:{booked_start % 60:02d}"
                ])
        current = max(current, booked_end)
    
    # 检查最后一个时间段
    if current < end_minutes:
        # 检查时间段是否至少为1小时
        if end_minutes - current >= 60:
            available.append([
                f"{current // 60:02d}:{current % 60:02d}",
                f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            ])
    
    return available

def transform_to_model_friendly_format(venue_data, billDay):
    """
    将原始场地数据转换为更适合大模型解读的格式
    
    Args:
        venue_data: 原始格式的场地数据，格式为 {场地名: [[开始时间, 结束时间], ...]}
        billDay: 查询日期，格式为 YYYY-MM-DD
        
    Returns:
        dict: 适合大模型解读的格式
    """
    # 获取日期信息
    date_obj = datetime.datetime.strptime(billDay, '%Y-%m-%d')
    weekday = date_obj.weekday()
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][weekday]
    date_str = date_obj.strftime('%Y年%m月%d日')
    
    # 转换为更友好的格式
    available_courts = []
    total_time_slots = 0
    earliest_time = "23:59"
    latest_time = "00:00"
    
    for court_name, time_slots in venue_data.items():
        court_data = {
            "name": court_name,
            "available_time_slots": []
        }
        
        for time_slot in time_slots:
            start_time = time_slot[0]
            end_time = time_slot[1]
            
            # 更新最早和最晚时间
            if start_time < earliest_time:
                earliest_time = start_time
            if end_time > latest_time:
                latest_time = end_time
            
            # 计算时长（小时）
            start_hour, start_minute = map(int, start_time.split(':'))
            end_hour, end_minute = map(int, end_time.split(':'))
            start_minutes = start_hour * 60 + start_minute
            end_minutes = end_hour * 60 + end_minute
            duration_hours = round((end_minutes - start_minutes) / 60, 1)
            
            # 添加时间段信息
            court_data["available_time_slots"].append({
                "start_time": start_time,
                "end_time": end_time,
                "duration_hours": duration_hours,
                "formatted": f"{start_time}-{end_time} ({duration_hours}小时)"
            })
            
            total_time_slots += 1
        
        available_courts.append(court_data)
    
    # 生成摘要信息
    if total_time_slots > 0:
        summary = f"在{date_str}（{weekday_cn}）共有{len(available_courts)}个场地有空闲时段，"
        summary += f"共{total_time_slots}个可预订时段，最早可预订时间为{earliest_time}，最晚结束时间为{latest_time}。"
    else:
        summary = f"{date_str}（{weekday_cn}）没有可预订的场地。"
    
    # 构造最终结果
    result = {
        "date": billDay,
        "date_formatted": date_str,
        "weekday": weekday_cn,
        "available_courts": available_courts,
        "summary": summary,
        "has_available_courts": len(available_courts) > 0,
        "total_available_time_slots": total_time_slots
    }
    
    return result


def main_handler(event, context):
    """
    云函数入口函数，获取微信公众号的会话列表和最新消息
    
    Args:
        event: 触发事件
        context: 函数上下文
        
    Returns:
        JSON格式的查询结果
    """
    print(f"收到请求: {json.dumps(event, ensure_ascii=False)}")
    
    # Get query parameters from the event
    query_params = event.get('queryString', {}) if event.get('queryString') else {}
    
    # Extract query parameters
    check_date = query_params.get('check_date', '')

    if not check_date:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "check_date 参数是必需的"})
        }

        
    print(f"正在查询日期 {check_date} 的场地信息...")
    venue_data = query_szw_venue_info(check_date)

    return {
        "statusCode": 200,
        "body": json.dumps(venue_data)
    }
        

# --- 示例用法 ---
if __name__ == "__main__":
    # 设置环境变量 SZBAY_COOKIE (在实际运行中，这应该在运行脚本前通过系统设置)
    # 例如在终端中运行: export SZBAY_COOKIE='你的cookie值'
    # os.environ['SZBAY_COOKIE'] = '你的cookie值' # 仅用于测试，不推荐硬编码

    # 获取今天的日期
    today_date = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # 测试日期，默认使用今天
    test_date = "2025-04-05"  # 或者指定一个未来日期，如 "2025-04-04"
    
    try:
        print(f"正在查询日期 {test_date} 的场地信息...")
        venue_data = query_szw_venue_info(test_date)
        
        # 打印摘要信息
        print("\n" + venue_data["summary"])
        
        # 打印可预订的场地信息
        if venue_data["has_available_courts"]:
            print("\n可预订的场地详情:")
            for court in venue_data["available_courts"]:
                print(f"\n场地: {court['name']}")
                print("可预订时间段:")
                for slot in court["available_time_slots"]:
                    print(f"  {slot['formatted']}")
        
        # 打印完整的格式化JSON数据
        print("\n完整数据结构:")
        print(json.dumps(venue_data, indent=2, ensure_ascii=False))
            
    except ValueError as e:
        print(e)
    except Exception as e:
        # 捕获其他潜在错误
        print(f"发生错误: {e}")
