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


def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """将时间段合并"""
    if not data:
        return data
    
    print(f"合并时间段: {data}")
    
    def parse_time_to_minutes(time_str: str) -> int:
        """将时间字符串转换为分钟数
        支持多种格式: "07", "07:00", "7", "7:00"
        """
        time_str = time_str.strip()
        if ':' in time_str:
            # 格式: "07:00"
            parts = time_str.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            # 格式: "07"
            hour = int(time_str)
            minute = 0
        return hour * 60 + minute
    
    def minutes_to_time_str(minutes: int) -> str:
        """将分钟数转换为时间字符串"""
        hour = minutes // 60
        minute = minutes % 60
        return f'{hour:02d}:{minute:02d}'
    
    # 转换为分钟数并排序
    data_in_minutes = []
    for start, end in data:
        try:
            start_minutes = parse_time_to_minutes(start)
            end_minutes = parse_time_to_minutes(end)
            data_in_minutes.append((start_minutes, end_minutes))
        except Exception as e:
            print(f"❌ 解析时间段失败: [{start}, {end}], 错误: {e}")
            continue
    
    if not data_in_minutes:
        print("❌ 没有有效的时间段可以合并")
        return []
    
    data_in_minutes = sorted(data_in_minutes)

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

    result = [[minutes_to_time_str(start), minutes_to_time_str(end)] for start, end in merged_data]
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
        print("📋 API响应中没有场地数据")
        return {}
    
    print(f"📊 API返回了 {len(court_data['body'])} 个时段数据")
    
    # 统计所有场地和时段信息
    all_courts_info = {}
    available_count = 0
    unavailable_count = 0
    
    # 按场地名称分组
    courts_by_name = {}
    for slot in court_data['body']:
        place_name = slot.get('placeName', '未知场地')
        # 处理时间格式，确保统一性
        raw_start_time = slot.get('startTime', '')
        raw_end_time = slot.get('endTime', '')
        
        # 标准化时间格式：从 "07:00:00" 或 "07:00" 格式提取小时
        def extract_hour(time_str):
            if not time_str:
                return ''
            # 分割时间字符串，取第一部分（小时）
            hour_part = time_str.split(':')[0] if ':' in time_str else time_str
            return hour_part.zfill(2)  # 确保两位数格式
        
        start_time = extract_hour(raw_start_time)
        end_time = extract_hour(raw_end_time)
        
        appoint_flag = slot.get('appointFlag', 0)
        price_info = slot.get('priceInfoList', [])
        
        # 检查价格和剩余数量信息
        if price_info and len(price_info) > 0:
            price = price_info[0].get('price', 0)
            remain_num = price_info[0].get('remainnum', 0)
        else:
            price = 0
            remain_num = 0
        
        # 记录所有场地信息（用于统计）
        if place_name not in all_courts_info:
            all_courts_info[place_name] = []
        
        # 检查锁定状态
        lock_remark = slot.get('lockRemark', '')
        lock_object_type = slot.get('lockObjectType', 0)
        is_locked = bool(lock_remark or lock_object_type)
        
        # 判断是否可预约的逻辑：需要appointFlag=1、有剩余数量、且未被锁定
        is_available = (appoint_flag == 1 and remain_num > 0 and not is_locked)
        
        all_courts_info[place_name].append({
            'time': f"{start_time}-{end_time}",
            'appointFlag': appoint_flag,
            'price': price,
            'remainNum': remain_num,
            'available': is_available,
            'locked': is_locked,
            'lockRemark': lock_remark
        })
        
        if is_available:
            available_count += 1
            if start_time and end_time:
                if place_name not in courts_by_name:
                    courts_by_name[place_name] = []
                courts_by_name[place_name].append([start_time, end_time])
        else:
            unavailable_count += 1
    
    # 打印详细统计信息
    print(f"📈 场地状态统计: 可预约 {available_count} 个时段, 不可预约 {unavailable_count} 个时段")
    
    # 打印每个场地的详细信息
    print("🏟️ 各场地详细信息:")
    for court_name, court_slots in all_courts_info.items():
        available_slots = [slot for slot in court_slots if slot['available']]
        unavailable_slots = [slot for slot in court_slots if not slot['available']]
        
        print(f"  📍 {court_name}:")
        print(f"    ✅ 可预约: {len(available_slots)} 个时段")
        if available_slots:
            for slot in available_slots:
                print(f"      {slot['time']} (¥{slot['price']}, 剩余{slot['remainNum']}个)")
        
        print(f"    ❌ 不可预约: {len(unavailable_slots)} 个时段")
        if unavailable_slots:
            for slot in unavailable_slots[:3]:  # 只显示前3个，避免日志太长
                # 修正状态判断逻辑
                if slot.get('locked', False):
                    lock_remark = slot.get('lockRemark', '')
                    status = f"锁定({lock_remark})" if lock_remark else "锁定"
                elif slot['appointFlag'] == 1 and slot['remainNum'] == 0:
                    status = "已满"
                elif slot['appointFlag'] == 2:
                    status = "不开放" 
                elif slot['appointFlag'] == 1 and slot['remainNum'] > 0:
                    status = "⚠️ 异常(应该可预约)"  # 这种情况不应该出现在不可预约列表中
                    print(f"      ⚠️ 发现逻辑错误: {court_name} {slot['time']} appointFlag=1但remainNum={slot['remainNum']}>0 却被标记为不可预约!")
                else:
                    status = f"未知状态(flag={slot['appointFlag']},remain={slot['remainNum']})"
                print(f"      {slot['time']} ({status}, ¥{slot['price']})")
            if len(unavailable_slots) > 3:
                print(f"      ... 还有{len(unavailable_slots)-3}个不可预约时段")
    
    # 合并每个场地的可用时间段
    available_slots_infos = {}
    for court_name, time_slots in courts_by_name.items():
        merged_slots = merge_time_ranges(time_slots)
        available_slots_infos[court_name] = merged_slots
        print(f"🔀 {court_name} 合并后可用时段: {merged_slots}")
    
    print(f"📝 最终可用场地: {len(available_slots_infos)} 个场地有空闲时段")
    
    return available_slots_infos


def get_cached_successful_proxies():
    """获取缓存的成功代理列表"""
    cache_key = "TYZX_SUCCESSFUL_PROXIES_CACHE"
    try:
        cached_proxies = Variable.get(cache_key, deserialize_json=True, default_var=[])
        print(f"📋 从缓存中获取到 {len(cached_proxies)} 个成功代理")
        if cached_proxies:
            print(f"   示例代理: {cached_proxies[:3]}")
        return cached_proxies
    except Exception as e:
        print(f"❌ 获取缓存代理失败: {e}")
        return []


def update_successful_proxy_cache(successful_proxy):
    """将成功的代理添加到缓存中"""
    cache_key = "TYZX_SUCCESSFUL_PROXIES_CACHE"
    try:
        cached_proxies = Variable.get(cache_key, deserialize_json=True, default_var=[])
        
        # 如果代理已存在，先移除（为了更新顺序）
        if successful_proxy in cached_proxies:
            cached_proxies.remove(successful_proxy)
        
        # 将成功的代理添加到前面
        cached_proxies.insert(0, successful_proxy)
        
        # 保持最多10个代理
        cached_proxies = cached_proxies[:10]
        
        Variable.set(cache_key, cached_proxies, serialize_json=True)
        print(f"✅ 代理缓存已更新: {successful_proxy} (缓存大小: {len(cached_proxies)})")
        
    except Exception as e:
        print(f"❌ 更新代理缓存失败: {e}")


def remove_failed_proxy_from_cache(failed_proxy):
    """从缓存中移除失败的代理"""
    cache_key = "TYZX_SUCCESSFUL_PROXIES_CACHE"
    try:
        cached_proxies = Variable.get(cache_key, deserialize_json=True, default_var=[])
        
        if failed_proxy in cached_proxies:
            cached_proxies.remove(failed_proxy)
            Variable.set(cache_key, cached_proxies, serialize_json=True)
            print(f"🗑️ 已从缓存中移除失败代理: {failed_proxy} (缓存大小: {len(cached_proxies)})")
        
    except Exception as e:
        print(f"❌ 移除失败代理缓存失败: {e}")


def get_free_tennis_court_infos_for_tyzx(date: str, proxy_list: list) -> dict:
    """从深圳市体育中心获取可预订的场地信息"""
    print(f"🌐 开始查询 {date} 的场地信息，共有 {len(proxy_list)} 个代理可用")
    
    # 获取缓存的成功代理，优先使用
    cached_proxies = get_cached_successful_proxies()
    
    # 合并代理列表：缓存的代理在前，新的代理在后
    all_proxies = cached_proxies.copy()
    for proxy in proxy_list:
        if proxy not in all_proxies:
            all_proxies.append(proxy)
    
    print(f"📋 合并后代理总数: {len(all_proxies)} (缓存: {len(cached_proxies)}, 新增: {len(proxy_list) - len([p for p in proxy_list if p in cached_proxies])})")
    
    got_response = False
    result = None
    successful_proxy = None
    
    # 优先使用缓存的代理（不打乱顺序），然后随机使用其他代理
    cached_indices = list(range(len(cached_proxies)))
    other_indices = list(range(len(cached_proxies), len(all_proxies)))
    random.shuffle(other_indices)
    
    all_indices = cached_indices + other_indices
    
    for i, index in enumerate(all_indices):
        proxy = all_proxies[index]
        proxy_type = "缓存" if index < len(cached_proxies) else "新"
        print(f"🔄 尝试第 {i+1} 个代理: {proxy} ({proxy_type})")
        
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
                print(f"✅ 代理 {proxy} 请求成功!")
                print(f"📦 API响应摘要: code={result.get('code')}, msg='{result.get('msg')}', 数据条数={len(result.get('body', []))}")
                got_response = True
                successful_proxy = proxy
                time.sleep(1)
                break
            else:
                print(f"❌ 代理 {proxy} 响应无效: code={result.get('code', 'N/A')}, msg='{result.get('msg', 'N/A')}'")
                # 如果是缓存的代理失败了，从缓存中移除
                if proxy in cached_proxies:
                    remove_failed_proxy_from_cache(proxy)
                continue
                
        except Exception as e:
            print(f"❌ 代理 {proxy} 请求失败: {e}")
            # 如果是缓存的代理失败了，从缓存中移除
            if proxy in cached_proxies:
                remove_failed_proxy_from_cache(proxy)
            continue
    
    if got_response and result and successful_proxy:
        # 将成功的代理加入缓存
        update_successful_proxy_cache(successful_proxy)
        print(f"🔍 开始解析 {date} 的场地数据...")
        return parse_tyzx_court_data(result)
    else:
        print(f"🚫 所有 {len(all_proxies)} 个代理都失败了")
        raise Exception("所有代理都失败了")


def get_proxy_list():
    """获取代理列表（包含缓存的代理和新获取的代理）"""
    # 首先获取缓存的成功代理
    cached_proxies = get_cached_successful_proxies()
    
    # 获取新的代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    print(f"🌐 正在获取新代理列表: {url}")
    
    new_proxy_list = []
    try:
        response = requests.get(url, timeout=10)
        print(f"📡 代理列表请求状态: {response.status_code}")
        
        if response.status_code == 200:
            text = response.text.strip()
            print(f"📄 原始响应内容长度: {len(text)} 字符")
            print(f"📋 原始响应前500字符:\n{text[:500]}")
            
            # 分割并过滤空行，同时验证代理格式
            all_lines = text.split("\n")
            raw_proxies = [line.strip() for line in all_lines if line.strip()]
            
            # 简单验证代理格式 (应该包含 : 表示端口)
            invalid_lines = []
            
            for proxy in raw_proxies:
                if ':' in proxy and len(proxy.split(':')) >= 2:
                    # 检查是否包含协议前缀，如果没有则添加
                    if not proxy.startswith(('http://', 'https://')):
                        proxy = f"http://{proxy}"
                    new_proxy_list.append(proxy)
                else:
                    invalid_lines.append(proxy)
            
            if invalid_lines:
                print(f"⚠️ 发现 {len(invalid_lines)} 个格式无效的行:")
                for invalid in invalid_lines[:3]:  # 只显示前3个
                    print(f"   ❌ '{invalid}'")
                if len(invalid_lines) > 3:
                    print(f"   ... 还有 {len(invalid_lines) - 3} 个无效行")
            
            print(f"📊 新代理处理统计:")
            print(f"   🔢 总行数: {len(all_lines)}")
            print(f"   📝 非空行数: {len(raw_proxies)}")
            print(f"   ✅ 有效代理: {len(new_proxy_list)}")
            print(f"   ❌ 无效格式: {len(invalid_lines)}")
            print(f"   📭 空行数: {len(all_lines) - len(raw_proxies)}")
            
            if new_proxy_list:
                print(f"📝 新代理示例 (显示前5个):")
                for i, proxy in enumerate(new_proxy_list[:5], 1):
                    print(f"   {i}. {proxy}")
                if len(new_proxy_list) > 5:
                    print(f"   ... 还有 {len(new_proxy_list) - 5} 个新代理")
            else:
                print(f"⚠️ 警告: 没有获取到任何有效的新代理!")
                
        else:
            print(f"❌ 代理列表请求失败: HTTP {response.status_code}")
            print(f"📄 错误响应: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ 获取代理列表异常: {e}")
    
    # 合并代理列表：优先使用缓存代理，然后是新代理（去重）
    final_proxy_list = cached_proxies.copy()
    new_count = 0
    for proxy in new_proxy_list:
        if proxy not in final_proxy_list:
            final_proxy_list.append(proxy)
            new_count += 1
    
    # 对新代理部分进行随机打乱（保持缓存代理的优先顺序）
    if len(final_proxy_list) > len(cached_proxies):
        new_proxies = final_proxy_list[len(cached_proxies):]
        random.shuffle(new_proxies)
        final_proxy_list = cached_proxies + new_proxies
    
    print(f"📊 最终代理统计:")
    print(f"   📋 缓存代理: {len(cached_proxies)}")
    print(f"   🆕 新增代理: {new_count}")
    print(f"   🎯 总代理数: {len(final_proxy_list)}")
    print(f"   🔀 新代理已随机打乱")
    
    return final_proxy_list


def check_tennis_courts():
    """主要检查逻辑"""
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return
    
    run_start_time = time.time()

    # 获取代理列表
    proxy_list = get_proxy_list()

    # 查询空闲的球场信息
    up_for_send_data_list = []
    
    print(f"\n🗓️ 开始查询未来4天的场地信息...")
    print("=" * 60)
    
    for index in range(0, 4):  # 查询今天、明天、后天、大后天
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
        is_weekend = check_date.weekday() >= 5
        weekday_str = ["一", "二", "三", "四", "五", "六", "日"][check_date.weekday()]
        day_type = "周末" if is_weekend else "工作日"
        
        print(f"\n📅 检查日期: {input_date} (星期{weekday_str}, {day_type})")
        print("-" * 40)
        
        try:
            court_data = get_free_tennis_court_infos_for_tyzx(input_date, proxy_list)
            print(f"court_data: {court_data}")
            time.sleep(1)
            
            if not court_data:
                print(f"📭 {input_date} 没有可用的场地")
                continue
            
            print(f"🎾 {input_date} 场地筛选结果:")
            total_available_slots = 0
            total_filtered_slots = 0
            
            for court_name, free_slots in court_data.items():
                if free_slots:
                    total_available_slots += len(free_slots)
                    filtered_slots = []
                    
                    print(f"  🏟️ {court_name}: 原始可用时段 {len(free_slots)} 个")
                    for slot in free_slots:
                        print(f"    📍 {slot[0]}-{slot[1]}")
                    
                    # 根据工作日/周末筛选时段
                    for slot in free_slots:
                        # 安全地解析时间格式
                        try:
                           # 检查时间段是否与目标时间范围有重叠
                            start_time = datetime.datetime.strptime(slot[0], "%H:%M")
                            end_time = datetime.datetime.strptime(slot[1], "%H:%M")
                            
                            if is_weekend:
                                # 周末关注15点到21点的场地
                                target_start = datetime.datetime.strptime("16:00", "%H:%M")
                                target_end = datetime.datetime.strptime("21:00", "%H:%M")
                            else:
                                # 工作日关注18点到21点的场地
                                target_start = datetime.datetime.strptime("18:00", "%H:%M")
                                target_end = datetime.datetime.strptime("21:00", "%H:%M")
                            
                            # 判断时间段是否有重叠：max(start1, start2) < min(end1, end2)
                            if max(start_time, target_start) < min(end_time, target_end):
                                filtered_slots.append(slot)
                                
                        except (ValueError, IndexError) as e:
                            print(f"      ⚠️ 解析时间格式失败: {slot}, 错误: {e}")
                            continue
                    
                    if filtered_slots:
                        total_filtered_slots += len(filtered_slots)
                        print(f"    ✅ 筛选后符合时段要求: {len(filtered_slots)} 个")
                        for slot in filtered_slots:
                            print(f"      ⭐ {slot[0]}-{slot[1]}")
                        
                        up_for_send_data_list.append({
                            "date": inform_date,
                            "court_name": f"体育中心{court_name}",
                            "free_slot_list": filtered_slots
                        })
                    else:
                        print(f"    ❌ 筛选后无符合时段要求的场地 (需要{day_type}{'15-21点' if is_weekend else '18-21点'})")
            
            time_filter = "15:00-21:00" if is_weekend else "18:00-21:00"
            print(f"📊 {input_date} 统计: 总可用{total_available_slots}个时段, 符合{time_filter}条件{total_filtered_slots}个时段")
            
        except Exception as e:
            print(f"❌ 检查日期 {input_date} 时出错: {str(e)}")
            continue
    
    print(f"\n" + "=" * 60)
    print(f"🎯 查询完成, 共找到 {len(up_for_send_data_list)} 个符合条件的场地时段")
    
    # 处理通知逻辑
    if up_for_send_data_list:
        print(f"\n📢 开始处理通知逻辑...")
        print("-" * 40)
        
        cache_key = "深圳市体育中心网球场"
        sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
        up_for_send_msg_list = []
        up_for_send_sms_list = []
        
        print(f"📝 历史已发送通知数量: {len(sended_msg_list)}")
        if sended_msg_list:
            print(f"📋 最近发送的通知 (最多显示3条):")
            for msg in sended_msg_list[-3:]:
                print(f"  💬 {msg}")
        
        print(f"\n🔍 开始检查新通知...")
        
        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']
            
            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
            
            print(f"📅 处理 {court_name} 在 {date} (星期{weekday_str}) 的 {len(free_slot_list)} 个时段:")
            
            for free_slot in free_slot_list:
                notification = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                if notification not in sended_msg_list:
                    print(f"  ✅ 新通知: {notification}")
                    up_for_send_msg_list.append(notification)
                    up_for_send_sms_list.append({
                        "date": date,
                        "court_name": court_name,
                        "start_time": free_slot[0],
                        "end_time": free_slot[1]
                    })
                else:
                    print(f"  ⏭️ 已发送过: {notification}")

        if up_for_send_msg_list:
            print(f"\n📨 准备发送 {len(up_for_send_msg_list)} 条新通知:")
            for i, msg in enumerate(up_for_send_msg_list, 1):
                print(f"  {i}. {msg}")
            
            all_in_one_msg = "\n".join(up_for_send_msg_list) 

            # 发送微信消息
            print(f"\n💬 准备发送微信消息...")
            chat_names = Variable.get("SZ_TYZX_TENNIS_CHATROOMS", default_var="")
            if chat_names.strip():
                chat_list = [name.strip() for name in str(chat_names).splitlines() if name.strip()]
                print(f"📋 目标微信群: {len(chat_list)} 个")
                for chat_name in chat_list:
                    print(f"  💬 {chat_name}")
                
                zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
                for contact_name in chat_list:
                    zacks_up_for_send_msg_list.append({
                        "room_name": contact_name,
                        "msg": all_in_one_msg
                    })
                    print(f"✅ 已加入发送队列: {contact_name}")
                
                Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
                print(f"📤 微信消息队列已更新, 当前队列长度: {len(zacks_up_for_send_msg_list)}")
            else:
                print(f"⚠️ 未配置微信群聊 (SZ_TYZX_TENNIS_CHATROOMS为空)")
                    
            sended_msg_list.extend(up_for_send_msg_list)

        # 更新Variable
        description = f"深圳市体育中心网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=sended_msg_list[-10:],  # 只保留最近10条记录
            description=description,
            serialize_json=True
        )
        print(f"\n💾 更新通知缓存:")
        print(f"   📝 缓存键: {cache_key}")
        print(f"   📊 保留记录数: {len(sended_msg_list[-10:])}/10")
        print(f"   🕐 更新时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if up_for_send_msg_list:
            print(f"   ✅ 本次新增: {len(up_for_send_msg_list)} 条通知")
        else:
            print(f"   ℹ️ 本次无新通知")
    else:
        print(f"\n📭 本次巡检结果: 未发现符合条件的空闲场地")

    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print(f"总耗时：{execution_time:.2f} 秒")

# ============================
# 创建DAG
# ============================

dag = DAG(
    '深圳市体育中心网球场巡检',
    default_args={'owner': 'claude89757', 'start_date': datetime.datetime(2025, 1, 1)},
    description='深圳市体育中心网球场巡检',
    schedule_interval='*/1 * * * *',  # 每2分钟执行一次
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
