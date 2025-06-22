#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/3/20
@Author  : claude89757
@File    : tyzx_watcher.py
@Software: PyCharm
深圳市体育中心网球场巡检
"""

import hashlib
import json
import time
import requests
import datetime
import random
from typing import Dict, Any, Optional, List

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta

from utils.tencent_sms import send_sms_for_news

# ============================
# 签名算法部分
# ============================

def md5_hash(text: str) -> str:
    """MD5哈希函数"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def object_to_search_str(params: Dict[str, Any]) -> str:
    """
    将参数对象转换为URL查询字符串格式
    例如: {'a': 1, 'b': 2} -> "?a=1&b=2"
    """
    if not params:
        return ""
    
    query_parts = []
    for key in params.keys():
        value = params[key]
        query_parts.append(f"{key}={value}")
    
    query_string = "&".join(query_parts)
    return f"?{query_string}" if query_string else ""

def set_md5(timestamp: int, content: Optional[str] = None) -> str:
    """
    生成MD5签名
    签名格式：MD5("Timestamp" + timestamp + "#&!6" + content)
    
    Args:
        timestamp: 时间戳（秒）
        content: 要签名的内容（可选）
    
    Returns:
        MD5签名字符串
    """
    if content:
        sign_string = f"Timestamp{timestamp}#&!6{content}"
    else:
        sign_string = f"Timestamp{timestamp}#&!6"
    
    return md5_hash(sign_string)

def generate_sign(
    method: str, 
    url: str, 
    data: Optional[Dict[str, Any]] = None, 
    params: Optional[Dict[str, Any]] = None,
    timestamp: Optional[int] = None
) -> tuple[str, int]:
    """
    根据HTTP方法生成签名
    
    Args:
        method: HTTP方法 (GET, POST, PUT, DELETE)
        url: 请求URL
        data: POST/PUT请求体数据
        params: GET请求参数
        timestamp: 时间戳（如果不提供则使用当前时间）
    
    Returns:
        (sign, timestamp) 签名和时间戳的元组
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    method = method.upper()
    
    # 提取URL路径的最后一部分（用于DELETE请求）
    last_slash_index = url.rfind("/")
    url_last_part = url[last_slash_index + 1:] if last_slash_index != -1 else url
    
    if method == "GET":
        # GET请求：URL + 查询参数
        query_str = object_to_search_str(params) if params else ""
        content = url + query_str
        sign = set_md5(timestamp, content)
        
    elif method == "PUT":
        # PUT请求：URL + JSON数据（如果有数据）
        if data and data != {}:
            content = url + json.dumps(data, separators=(',', ':'))
            sign = set_md5(timestamp, content)
        else:
            sign = set_md5(timestamp, url)
            
    elif method == "POST":
        # POST请求：JSON数据（如果有数据）
        if data and data != {}:
            if isinstance(data, dict):
                content = json.dumps(data, separators=(',', ':'))
            else:
                content = str(data)
            sign = set_md5(timestamp, content)
        else:
            sign = set_md5(timestamp)
            
    elif method == "DELETE":
        # DELETE请求：URL的最后一部分
        sign = set_md5(timestamp, url_last_part)
        
    else:
        # 其他方法：默认处理
        sign = set_md5(timestamp)
    
    return sign, timestamp

# ============================
# API调用部分
# ============================

class TennisCourtAPI:
    def __init__(self):
        self.base_url = "https://sports.sztyzx.com.cn"
        self.session = requests.Session()
        self.proxies = None
        
        # 设置默认headers（基于成功的curl请求）
        self.default_headers = {
            "Host": "sports.sztyzx.com.cn",
            "xweb_xhr": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.7(0x13080712) UnifiedPCMacWechat(0xf2640518) XWEB/13910",
            "content-type": "application/json",
            "accept": "*/*",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://servicewechat.com/wxea33bdce8cd5fd8e/40/page-frame.html",
            "accept-language": "zh-CN,zh;q=0.9",
            "priority": "u=1, i"
        }
    
    def set_proxy(self, proxies):
        """设置代理"""
        self.proxies = proxies
    
    def _make_request(self, method, endpoint, data=None, **kwargs):
        """
        发送HTTP请求的核心方法
        关键改进：使用原始JSON字符串，不使用requests的json参数
        """
        url = f"{self.base_url}{endpoint}"
        
        # 生成签名
        sign, timestamp = generate_sign(method, url, data)
        
        # 准备headers
        headers = self.default_headers.copy()
        headers.update({
            "timestamp": str(timestamp),
            "sign": sign
        })
        
        # 添加自定义headers
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
        
        try:
            if method.upper() == 'POST' and data:
                # 关键修正：使用原始JSON字符串！
                json_string = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
                # 使用data参数而不是json参数！
                response = self.session.post(url, data=json_string, headers=headers, 
                                           proxies=self.proxies, verify=False, timeout=5)
            else:
                response = self.session.request(method, url, headers=headers, 
                                              proxies=self.proxies, verify=False, timeout=5, **kwargs)
                
            return response
            
        except Exception as e:
            print(f"❌ 请求异常: {e}")
            raise
    
    def get_court_schedule(self, stadium_id, sports_cat_id, ground_type_id, use_date, **kwargs):
        """
        查询网球场时间安排
        
        Args:
            stadium_id (str): 场馆ID (如 "868")
            sports_cat_id (int): 运动类别ID (如 1621 代表网球)
            ground_type_id (int): 场地类型ID (如 1744)
            use_date (str): 使用日期 (格式: "2025-06-23")
            **kwargs: 其他可选参数
        
        Returns:
            dict: API响应数据
        """
        endpoint = "/module-stadium/stadiumRoundInfo/list"
        
        # 默认参数
        data = {
            "sportscatId": sports_cat_id,
            "groundtypeId": ground_type_id,
            "stadiumId": str(stadium_id),
            "useDate": use_date,
            "auditFlag": 3,
            "qryPriceFlag": 1,
            "isPriceEmpty": 1,
            "publicType": 2,
            "applicationId": "4"
        }
        
        # 合并额外参数
        data.update(kwargs)
        
        response = self._make_request("POST", endpoint, data)
        
        if response.status_code == 200:
            try:
                result = response.json()
                return result
            except json.JSONDecodeError:
                return {"error": "响应不是有效的JSON", "raw": response.text}
        else:
            return {"error": f"HTTP {response.status_code}", "message": response.text}

# ============================
# DAG 巡检部分
# ============================

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
    
    print(f"合并时间段: {data}")
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
    print(f"合并后: {result}")
    return result

def parse_tyzx_court_data(court_data: dict) -> dict:
    """
    解析深圳市体育中心的场地数据
    
    Args:
        court_data: API返回的场地数据
        
    Returns:
        dict: 按场地名称组织的可用时间段
    """
    if not court_data.get('body'):
        return {}
    
    # 按场地名称分组
    courts_by_name = {}
    for slot in court_data['body']:
        place_name = slot.get('placeName', '未知场地')
        start_time = slot.get('startTime', '').replace(':00', '')  # 去掉秒
        end_time = slot.get('endTime', '').replace(':00', '')
        
        # 检查是否可预约 (appointFlag=1 表示可预约，remainnum>0 表示有剩余)
        is_available = (slot.get('appointFlag') == 1 and 
                       slot.get('priceInfoList') and
                       len(slot.get('priceInfoList', [])) > 0 and
                       slot['priceInfoList'][0].get('remainnum', 0) > 0)
        
        if is_available and start_time and end_time:
            if place_name not in courts_by_name:
                courts_by_name[place_name] = []
            courts_by_name[place_name].append([start_time, end_time])
    
    # 合并每个场地的时间段
    available_slots_infos = {}
    for court_name, time_slots in courts_by_name.items():
        available_slots_infos[court_name] = merge_time_ranges(time_slots)
    
    return available_slots_infos

def get_free_tennis_court_infos_for_tyzx(date: str, proxy_list: list) -> dict:
    """从深圳市体育中心获取可预订的场地信息"""
    got_response = False
    result = None
    index_list = list(range(len(proxy_list)))
    random.shuffle(index_list)
    print(f"代理索引列表: {index_list}")
    
    for index in index_list:
        proxy = proxy_list[index]
        print(f"尝试第 {index} 次使用代理 {proxy}")
        
        try:
            api = TennisCourtAPI()
            # 为API设置代理
            proxies = {"https": proxy}
            api.set_proxy(proxies)
            
            result = api.get_court_schedule(
                stadium_id="868",
                sports_cat_id=1621,  # 网球
                ground_type_id=1744,
                use_date=date
            )
            
            if 'error' not in result and result.get('body'):
                print(f"成功使用代理 {proxy}")
                got_response = True
                time.sleep(1)
                break
            else:
                print(f"代理 {proxy} 响应无效: {result}")
                continue
                
        except Exception as e:
            print(f"代理 {proxy} 失败: {e}")
            continue
    
    if got_response and result:
        return parse_tyzx_court_data(result)
    else:
        raise Exception("所有代理都失败了")

def check_tennis_courts():
    """主要检查逻辑"""
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return
    
    run_start_time = time.time()
    print_with_timestamp("开始检查深圳市体育中心网球场...")

    # 获取代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    response = requests.get(url)
    text = response.text.strip()
    proxy_list = [line.strip() for line in text.split("\n")]
    random.shuffle(proxy_list)
    print(f"从 {url} 加载了 {len(proxy_list)} 个代理")

    # 查询空闲的球场信息
    up_for_send_data_list = []
    for index in range(0, 3):  # 查询今天、明天、后天
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        print(f"检查日期 {input_date}...")
        
        try:
            court_data = get_free_tennis_court_infos_for_tyzx(input_date, proxy_list)
            time.sleep(1)
            
            for court_name, free_slots in court_data.items():
                if free_slots:
                    filtered_slots = []
                    check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                    is_weekend = check_date.weekday() >= 5
                    
                    for slot in free_slots:
                        hour_num = int(slot[0].split(':')[0])
                        if is_weekend:
                            if 15 <= hour_num <= 21:  # 周末关注15点到21点的场地
                                filtered_slots.append(slot)
                        else:
                            if 18 <= hour_num <= 21:  # 工作日关注18点到21点的场地
                                filtered_slots.append(slot)
                    
                    if filtered_slots:
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"体育中心{court_name}",
                            "free_slot_list": filtered_slots
                        })
        except Exception as e:
            print(f"检查日期 {input_date} 时出错: {str(e)}")
            continue
    
    print(f"待发送数据列表: {up_for_send_data_list}")
    
    # 处理通知逻辑
    if up_for_send_data_list:
        cache_key = "深圳市体育中心网球场"
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
            #         phone_num_list = Variable.get("TYZX_PHONE_NUM_LIST", default_var=[], deserialize_json=True)
            #         send_sms_for_news(phone_num_list, param_list=[data["date"], data["court_name"], data["start_time"], data["end_time"]])
            #     except Exception as e:
            #         print(f"发送短信失败: {e}")

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
        description = f"深圳市体育中心网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-10:],  # 只保留最近10条记录
            description=description,
            serialize_json=True
        )
        print(f"更新缓存 {cache_key}: {sended_msg_list}")
    else:
        print("没有可用的场地信息")

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"总耗时：{execution_time:.2f} 秒")

# ============================
# 创建DAG
# ============================

dag = DAG(
    '深圳市体育中心网球场巡检',
    default_args=default_args,
    description='深圳市体育中心网球场巡检',
    schedule_interval='*/2 * * * *',  # 每2分钟执行一次
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
