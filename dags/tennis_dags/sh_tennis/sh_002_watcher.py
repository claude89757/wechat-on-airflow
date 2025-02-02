#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/7/13 23:31
@Author  : claude89757
@File    : tennis_court_watcher.py
@Software: PyCharm
"""
import os
import json
import time
import datetime
import requests
import random
import shelve
import warnings
import hashlib
import hmac
import string
import urllib.parse

from typing import List
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta


# 忽略 SSL 警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

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

# 全局常量
CURRENT_TIME = int(time.time() * 1000)  # 当前时间戳（毫秒）
APP_VERSION = "3.0.9"
LATITUDE = "21.53092098"
LONGITUDE = "114.94631578"
CITY_ID = 321
CITY_NAME = "上海"
VER = "2.9"
VENUES_ID = "22377"
CAT_ID = "12"
RAISE_PACKAGE_ID = 0
PHONE_ENCODE = "ks/Whad334TXSmRMAqxKvw=="

# 在文件开头添加常量定义
SERVERLESS_ACCESS_TOKEN = "QYD_SERVERLESS_ACCESS_TOKEN"
SIGN_INFO = "QYD_SIGN_INFO" 
API_ACCESS_TOKEN = "QYD_API_ACCESS_TOKEN"
LOGIN_TOKEN = "QYD_LOGIN_TOKEN"

def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def generate_nonce():
    timestamp = str(int(time.time() * 1000))  # current time in milliseconds
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    noncestr = f"{timestamp}{random_str}"
    return noncestr


NONCE = generate_nonce()


def load_data_from_variable(filename: str, expire_time: int, using_cached: bool = False):
    """
    从 Airflow Variable 读取数据，若不存在或超时，则重新拉取
    """
    print(f"load_data_from_variable: {filename}")
    try:
        # 从 Variable 获取数据和时间戳
        var_data = Variable.get(filename, deserialize_json=True)
        local_data = var_data.get('data', '')
        last_update = var_data.get('timestamp', 0)
        
        # 计算数据年龄
        current_time = time.time()
        data_age = current_time - last_update
        print(f"{filename} last update: {datetime.datetime.fromtimestamp(last_update)}")
        
    except Exception as e:
        print(f"Failed to get Variable {filename}: {str(e)}")
        if filename == LOGIN_TOKEN:
            raise Exception(f"import new LOGIN_ACCESS_TOKEN！！！！")
        local_data = ''
        data_age = expire_time + 1  # 确保会刷新数据

    if data_age > expire_time or not local_data or not using_cached:
        print(f"data is expired, getting new data for {filename}")
        if filename == SERVERLESS_ACCESS_TOKEN:
            new_data = get_serverless_access_token()
        elif filename == SIGN_INFO:
            serverless_access_token = get_serverless_access_token()
            new_data = get_sign_info_from_serverless(access_token=serverless_access_token)
        elif filename == API_ACCESS_TOKEN:
            sign_info = load_sign_info()
            new_data = get_api_access_token(sign_info=sign_info)
        elif filename == LOGIN_TOKEN:
            sign_info = load_sign_info()
            api_access_token = load_api_access_token()
            new_data = refresh_login_token(sign_info=sign_info,
                                         api_access_token=api_access_token,
                                         login_token=local_data)
        else:
            raise Exception(f"unknown filename {filename}")
            
        # 保存数据到 Variable
        var_data = {
            'data': new_data,
            'timestamp': time.time()
        }
        Variable.set(filename, var_data, serialize_json=True)
        
        return new_data
    else:
        print(f"data is loaded from Variable {filename}")
        if isinstance(local_data, str):
            try:
                return json.loads(local_data)
            except (json.JSONDecodeError, TypeError):
                return local_data
        return local_data


def load_serverless_token(using_cached: bool = True):
    """
    加载云函数的token
    """
    return load_data_from_variable(SERVERLESS_ACCESS_TOKEN, 500, using_cached)


def load_sign_info(using_cached: bool = True):
    """
    加载云函数的token
    """
    return load_data_from_variable(SIGN_INFO, 6000, using_cached)


def load_api_access_token(using_cached: bool = True):
    """
    加载云函数的token
    """
    return load_data_from_variable(API_ACCESS_TOKEN, 6000, using_cached)


def load_login_token(using_cached: bool = True):
    """
    加载云函数的token
    """
    return load_data_from_variable(LOGIN_TOKEN, 4320000, using_cached)


def Ae(body, secret):
    """
    云函数的签名函数
    """
    # 1. 对字典按键排序
    sorted_items = sorted(body.items())
    # 2. 拼接成字符串，并进行 URL 编码
    query_string = '&'.join([f"{k}={str(v)}" for k, v in sorted_items if v])
    # 3. HMAC-MD5 签名
    signature = hmac.new(secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.md5).hexdigest()
    return signature


def get_serverless_access_token():
    url = "https://api.next.bspapp.com/client"

    data = {
        "method": "serverless.auth.user.anonymousAuthorize",
        "params": "{}",
        "spaceId": Variable.get("QYD_SERVERLESS_SPACE_ID"),
        "timestamp": CURRENT_TIME
    }
    print(data)
    serverless_sign = Ae(data, Variable.get("QYD_SERVERLESS_CLIENT_SECRET"))
    # print(f"serverless_sign: {serverless_sign}")
    headers = {
        "Host": "api.next.bspapp.com",
        "xweb_xhr": "1",
        "x-serverless-sign": serverless_sign,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) NetType/"
                      "WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    print(url)
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False, proxies={"https": PROXY},
                                 timeout=5)
    else:
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
    print(response.text)
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("success"):
            access_token = response_json["data"]["accessToken"]
            return access_token
        else:
            raise Exception("Request was not successful: {}".format(response_json))
    else:
        raise Exception("Failed to get a valid response: HTTP {}".format(response.status_code))


def get_sign_info_from_serverless(access_token: str):
    """
    access_token:
    """
    url = "https://api.next.bspapp.com/client?"
    data = {
        "method": "serverless.function.runtime.invoke",
        "params": json.dumps({
            "functionTarget": "get-sign-info",
            "functionArgs": {
                "client_time": CURRENT_TIME,
                "device_id": CURRENT_TIME,
                "sign_key": "",
                "noncestr": NONCE,
                "utm_source": "miniprogram",
                "utm_medium": "wechatapp",
                "app_version": "3.0.9",
                "latitude": 0,
                "longitude": 0,
                "access_token": "",
                "login_token": "",
                "url": "https://xapi.quyundong.com/Api/Cloud/getSignInfo",
                "clientInfo": {
                    "PLATFORM": "mp-weixin",
                    "OS": "mac",
                    "APPID": "__UNI__902073B",
                    "DEVICEID": CURRENT_TIME,
                    "scene": 1074,
                    "albumAuthorized": True,
                    "benchmarkLevel": -1,
                    "bluetoothEnabled": False,
                    "cameraAuthorized": True,
                    "locationAuthorized": True,
                    "locationEnabled": True,
                    "microphoneAuthorized": True,
                    "notificationAuthorized": True,
                    "notificationSoundEnabled": True,
                    "power": 100,
                    "safeArea": {
                        "bottom": 736,
                        "height": 736,
                        "left": 0,
                        "right": 414,
                        "top": 0,
                        "width": 414
                    },
                    "screenHeight": 736,
                    "screenWidth": 414,
                    "statusBarHeight": 0,
                    "theme": "light",
                    "wifiEnabled": True,
                    "windowHeight": 736,
                    "windowWidth": 414,
                    "enableDebug": False,
                    "devicePixelRatio": 2,
                    "deviceId": "17219164685639263029",
                    "safeAreaInsets": {
                        "top": 0,
                        "left": 0,
                        "right": 0,
                        "bottom": 0
                    },
                    "appId": "__UNI__902073B",
                    "appName": "趣运动(新)",
                    "appVersion": "1.0.0",
                    "appVersionCode": "100",
                    "appLanguage": "zh-Hans",
                    "uniCompileVersion": "3.99",
                    "uniRuntimeVersion": "3.99",
                    "uniPlatform": "mp-weixin",
                    "deviceBrand": "apple",
                    "deviceModel": "MacBookPro18,1",
                    "deviceType": "pc",
                    "osName": "mac",
                    "osVersion": "OS",
                    "hostTheme": "light",
                    "hostVersion": "3.8.8",
                    "hostLanguage": "zh-CN",
                    "hostName": "WeChat",
                    "hostSDKVersion": "3.3.5",
                    "hostFontSizeSetting": 15,
                    "windowTop": 0,
                    "windowBottom": 0,
                    "locale": "zh-Hans",
                    "LOCALE": "zh-Hans"
                }
            }
        }),
        "spaceId": Variable.get("QYD_SERVERLESS_SPACE_ID"),
        "timestamp": CURRENT_TIME,
        "token": access_token
    }
    serverless_sign = Ae(data, Variable.get("QYD_SERVERLESS_CLIENT_SECRET"))
    # print(f"serverless_sign: {serverless_sign}")
    headers = {
        "Host": "api.next.bspapp.com",
        "x-basement-token": access_token,
        "xweb_xhr": "1",
        "x-serverless-sign": serverless_sign,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    print(url)
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False, proxies={"https": PROXY},
                                 timeout=5)
    else:
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
    print(response.text)
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("success"):
            return response_json["data"]['result']['data']['data']
        else:
            raise Exception(response.text)
    else:
        raise Exception(response.text)


def generate_api_sign(body: dict, url: str, api_key: str):
    n = ""
    if url:
        # 假设 p 是某个已知的前缀
        p = "https://xapi.quyundong.com"
        n = url.split(f"{p}/")[1].replace("/", ":").lower()
    i = n
    if body:
        # 获取并排序键
        keys = sorted(body.keys())
        a = {}
        for key in keys:
            a[key] = body[key]
        # 生成查询字符串
        for key in a:
            i += f"{key}={urllib.parse.quote(str(a[key]))}&"
        # 拼接 api_key
        i += api_key
    print(i)
    return hashlib.sha256(i.encode('utf-8')).hexdigest()


def refresh_login_token(sign_info: dict, api_access_token: str, login_token: str):
    """
    获取业务接口的token
    # 60天过期一次
    """
    url = "https://xapi.quyundong.com/Api/User/refreshLoginToken"
    nonce = generate_nonce()
    params = {
        "utm_source": "miniprogram",
        "utm_medium": "wechatapp",
        "client_time": CURRENT_TIME,
        "sign_key": sign_info['set_time'],
        "device_id": sign_info['set_device_id'],
        "app_version": "3.0.9",
        "latitude": "0",
        "longitude": "0",
        "noncestr": nonce,
        "access_token": api_access_token,
        "login_token": login_token,
        "city_id": "0",
        "city_name": "0",
    }
    print(params)
    api_sign = generate_api_sign(params, url, sign_info['api_key'])
    print(f"api_sign: {api_sign}")
    params['api_sign'] = api_sign

    headers = {
        "Host": "xapi.quyundong.com",
        "systeminfo": "{\"model\":\"MacBookPro18,1\",\"system\":\"Mac OS X 14.5.0\",\"version\":\"3.8.8\","
                      "\"brand\":\"apple\",\"platform\":\"mac\",\"pixelRatio\":2,\"windowWidth\":414,\""
                      "windowHeight\":736,\"language\":\"zh_CN\",\"screenWidth\":414,\"screenHeight\":736,\""
                      "SDKVersion\":\"3.3.5\",\"fontSizeSetting\":15,\"statusBarHeight\":0}",
        "xweb_xhr": "1",
        "env-tag": "feature/v405",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "content-type": "application/json",
        "accept": "*/*",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "accept-language": "zh-CN,zh;q=0.9"
    }
    print(url)
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.get(url, headers=headers, params=params, verify=False, proxies={"https": PROXY}, timeout=5)
    else:
        response = requests.get(url, headers=headers, params=params, verify=False)
    print(response.text)
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("status") == "0000":
            return response_json['data']['value']
        else:
            raise Exception(response.text)
    else:
        raise Exception(response.text)


def get_api_access_token(sign_info: dict):
    """
    获取业务接口的token
    """
    url = "https://xapi.quyundong.com/Api/User/getAccessToken"
    params = {
        "utm_source": "miniprogram",
        "utm_medium": "wechatapp",
        "client_time": CURRENT_TIME,
        "sign_key": sign_info['set_time'],
        "device_id": sign_info['set_device_id'],
        "app_version": "3.0.9",
        "latitude": "0",
        "longitude": "0",
        "noncestr": NONCE,
        "access_token": "",
        "login_token": "",
        "city_id": "0",
        "city_name": "0"
    }
    api_sign = generate_api_sign(params, url, sign_info['api_key'])
    print(f"api_sign: {api_sign}")
    params['api_sign'] = api_sign

    headers = {
        "Host": "xapi.quyundong.com",
        "systeminfo": "{\"model\":\"MacBookPro18,1\",\"system\":\"Mac OS X 14.5.0\",\"version\":\"3.8.8\","
                      "\"brand\":\"apple\",\"platform\":\"mac\",\"pixelRatio\":2,\"windowWidth\":414,\""
                      "windowHeight\":736,\"language\":\"zh_CN\",\"screenWidth\":414,\"screenHeight\":736,\""
                      "SDKVersion\":\"3.3.5\",\"fontSizeSetting\":15,\"statusBarHeight\":0}",
        "xweb_xhr": "1",
        "env-tag": "feature/v405",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "content-type": "application/json",
        "accept": "*/*",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "accept-language": "zh-CN,zh;q=0.9"
    }
    print(url)
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.get(url, headers=headers, params=params, verify=False, proxies={"https": PROXY}, timeout=5)
    else:
        response = requests.get(url, headers=headers, params=params, verify=False)
    print(response.text)
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("status") == "0000":
            return response_json["data"]['token']
        else:
            raise Exception(response.text)
    else:
        raise Exception(response.text)


def get_api_sign_from_serverless(sign_info: dict, serverless_token: str, api_access_token: str, login_token: str,
                                 date: str):
    """
    从云函数获取签名
    """
    url = "https://api.next.bspapp.com/client"
    data = {
        "method": "serverless.function.runtime.invoke",
        "params": json.dumps({
            "functionTarget": "uni-cloud-request",
            "functionArgs": {
                "api_key": sign_info['api_key'],
                "interfaceStr": "api:venues:booktable",
                "data": {
                    "utm_source": "miniprogram",
                    "utm_medium": "wechatapp",
                    "client_time": CURRENT_TIME,
                    "sign_key": sign_info['set_time'],
                    "device_id": sign_info['set_device_id'],
                    "app_version": APP_VERSION,
                    "latitude": LATITUDE,
                    "longitude": LONGITUDE,
                    "noncestr": NONCE,
                    "access_token": api_access_token,
                    "login_token": login_token,
                    "city_id": CITY_ID,
                    "city_name": CITY_NAME,
                    "ver": VER,
                    "venues_id": VENUES_ID,
                    "cat_id": CAT_ID,
                    "book_date": date,
                    "raise_package_id": RAISE_PACKAGE_ID,
                    "phone_encode": PHONE_ENCODE
                },
                "clientInfo": {
                    "PLATFORM": "mp-weixin",
                    "OS": "mac",
                    "APPID": "__UNI__902073B",
                    "DEVICEID": sign_info['set_device_id'],
                    "scene": 1089,
                    "albumAuthorized": True,
                    "benchmarkLevel": -1,
                    "bluetoothEnabled": False,
                    "cameraAuthorized": True,
                    "locationAuthorized": True,
                    "locationEnabled": True,
                    "microphoneAuthorized": True,
                    "notificationAuthorized": True,
                    "notificationSoundEnabled": True,
                    "power": 100,
                    "safeArea": {
                        "bottom": 736,
                        "height": 736,
                        "left": 0,
                        "right": 414,
                        "top": 0,
                        "width": 414
                    },
                    "screenHeight": 736,
                    "screenWidth": 414,
                    "statusBarHeight": 0,
                    "theme": "light",
                    "wifiEnabled": True,
                    "windowHeight": 736,
                    "windowWidth": 414,
                    "enableDebug": False,
                    "devicePixelRatio": 2,
                    "deviceId": sign_info['set_device_id'],
                    "safeAreaInsets": {
                        "top": 0,
                        "left": 0,
                        "right": 0,
                        "bottom": 0
                    },
                    "appId": "__UNI__902073B",
                    "appName": "趣运动(新)",
                    "appVersion": "1.0.0",
                    "appVersionCode": "100",
                    "appLanguage": "zh-Hans",
                    "uniCompileVersion": "3.99",
                    "uniRuntimeVersion": "3.99",
                    "uniPlatform": "mp-weixin",
                    "deviceBrand": "apple",
                    "deviceModel": "MacBookPro18,1",
                    "deviceType": "pc",
                    "osName": "mac",
                    "osVersion": "OS",
                    "hostTheme": "light",
                    "hostVersion": "3.8.8",
                    "hostLanguage": "zh-CN",
                    "hostName": "WeChat",
                    "hostSDKVersion": "3.3.5",
                    "hostFontSizeSetting": 15,
                    "windowTop": 0,
                    "windowBottom": 0,
                    "locale": "zh-Hans",
                    "LOCALE": "zh-Hans"
                }
            }
        }),
        "spaceId": Variable.get("QYD_SERVERLESS_SPACE_ID"),
        "timestamp": CURRENT_TIME,
        "token": serverless_token
    }
    # print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
    # pprint.pprint(data)
    # print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
    serverless_sign = Ae(data, Variable.get("QYD_SERVERLESS_CLIENT_SECRET"))

    headers = {
        "Host": "api.next.bspapp.com",
        "x-basement-token": serverless_token,
        "xweb_xhr": "1",
        "x-serverless-sign": serverless_sign,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }

    print("-------------------[GET API SIGN]--------------------------------")
    print(f"url: {url}")
    print(f"headers: {headers}")
    print(f"data: {data}")
    print(url)
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False, proxies={"https": PROXY},
                                 timeout=5)
    else:
        response = requests.post(url, headers=headers, data=json.dumps(data), verify=False)
    print(response.text)
    print("---------------------------------------------------")
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("success"):
            return response_json
        else:
            raise Exception(response.text)
    else:
        raise Exception(response.text)


def get_tennis_court_data(sign_info: dict, api_access_token: str, login_token: str, serverless_api_sign_info: dict,
                          date: str, is_retry: bool = False):
    """
    查询场地数据
    """
    print(f"sign_info: {sign_info}")
    print(f"api_access_token: {api_access_token}")
    print(f"login_token: {login_token}")
    print(f"serverless_api_sign_info: {serverless_api_sign_info}")
    print(f"nonce: {NONCE}")

    url = "https://xapi.quyundong.com/Api/Venues/bookTable"
    headers = {
        "Host": "xapi.quyundong.com",
        "systeminfo": "{\"model\":\"MacBookPro18,1\",\"system\":\"Mac OS X 14.5.0\",\"version\":\"3.8.8\",\"brand"
                      "\":\"apple\",\"platform\":\"mac\",\"pixelRatio\":2,\"windowWidth\":414,\"windowHeight\":736,"
                      "\"language\":\"zh_CN\",\"screenWidth\":414,\"screenHeight\":736,\"SDKVersion\":\"3.3.5\","
                      "\"fontSizeSetting\":15,\"statusBarHeight\":0}",
        "xweb_xhr": "1",
        "env-tag": "feature/v405",
        "unicloudrequestid": serverless_api_sign_info['header']['x-serverless-request-id'],
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) "
                      "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.8(0x13080812) XWEB/1216",
        "content-type": "application/json",
        "accept": "*/*",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": "https://servicewechat.com/wxbb9c3b35727d8ce8/149/page-frame.html",
        "accept-language": "zh-CN,zh;q=0.9"
    }

    params = {
                "utm_source": "miniprogram",
                "utm_medium": "wechatapp",
                "client_time": CURRENT_TIME,
                "sign_key": sign_info['set_time'],
                "device_id": sign_info['set_device_id'],
                "app_version": APP_VERSION,
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "noncestr": NONCE,
                "access_token": api_access_token,
                "login_token": login_token,
                "city_id": CITY_ID,
                "city_name": CITY_NAME,
                "ver": VER,
                "venues_id": VENUES_ID,
                "cat_id": CAT_ID,
                "book_date": date,
                "raise_package_id": RAISE_PACKAGE_ID,
                "phone_encode": PHONE_ENCODE
    }
    # print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
    # pprint.pprint(params)
    # print('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
    api_sign = generate_api_sign(params, url, sign_info['api_key'])
    print(f"api_sign: {api_sign}")
    params['api_sign'] = serverless_api_sign_info['data']

    print("------------------[GET DATA]---------------------------------")
    print(f"url: {url}")
    print(f"headers: {headers}")
    print(f"params: {params}")
    if PROXY:
        print(f"PROXY: {PROXY}")
        response = requests.get(url, headers=headers, params=params, verify=False, proxies={"https": PROXY}, timeout=5)
    else:
        response = requests.get(url, headers=headers, params=params, verify=False)
    print(response.text)
    print("---------------------------------------------------")
    if response.status_code == 200:
        response_json = response.json()
        if response_json.get("status") == "0000":
            return response_json['data']
        elif response_json.get('msg') == "AccessToken已失效(1)" and not is_retry:
            api_access_token = load_api_access_token(using_cached=False)
            serverless_token = load_serverless_token(using_cached=False)
            api_sign_info = get_api_sign_from_serverless(sign_info, serverless_token, api_access_token, login_token,
                                                         date)
            data = get_tennis_court_data(sign_info, api_access_token, login_token, api_sign_info, date, is_retry=True)
            return data
        elif response_json.get('msg') == "AccessToken已失效或不存在" and not is_retry:
            api_access_token = load_api_access_token(using_cached=False)
            serverless_token = load_serverless_token(using_cached=False)
            api_sign_info = get_api_sign_from_serverless(sign_info, serverless_token, api_access_token, login_token,
                                                         date)
            data = get_tennis_court_data(sign_info, api_access_token, login_token, api_sign_info, date, is_retry=True)
            return data
        else:
            raise Exception(response.text)
    else:
        raise Exception(response.text)


def get_proxy_list() -> list:
    """
    获取代理列表
    """
    # 获取公网HTTPS代理列表
    url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt"
    response = requests.get(url, verify=False)
    text = response.text.strip()
    lines = text.split("\n")
    proxy_list = [line.strip() for line in lines]
    random.shuffle(proxy_list)  # 每次都打乱下
    print(f"Loaded {len(proxy_list)} proxies from {url}")
    return proxy_list


def get_tennis_court_data_by_proxy(date: str, last_proxy: str = None):
    """
    通过代理查询场地数据
    """
    global PROXY
    global NONCE
    proxy_list = get_proxy_list()
    if last_proxy:
        proxy_list.insert(0, last_proxy)
    else:
        pass
    for proxy in proxy_list:
        print(f"try proxy {proxy}....")
        PROXY = proxy
        try:
            sign_info = load_sign_info(using_cached=True)
            access_token = load_serverless_token(using_cached=True)
            api_access_token = load_api_access_token(using_cached=True)
            login_token = load_login_token(using_cached=True)

            print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
            NONCE = generate_nonce()
            print(f"NONCE: {NONCE}")
            print(f"sign_info: {sign_info}")
            print(f"access_token: {access_token}")
            print(f"api_access_token: {api_access_token}")
            print(f"login_token: {login_token}")
            print(f"sign_info: {sign_info}")
            api_sign_info = get_api_sign_from_serverless(sign_info, access_token, api_access_token, login_token, date)
            data = get_tennis_court_data(sign_info, api_access_token, login_token, api_sign_info, date)
            print(f"data: {data}")
            print(f"[success]: {PROXY}")

            court_free_time_infos = {}
            for good in data['goods_list']:
                court_name = good['course_name']
                free_time_slot_list = []
                for item in good['items']:
                    item_list = str(item).split(',')
                    status = item_list[3]
                    start_time = item_list[1]
                    end_time = item_list[8]
                    if len(start_time) == 4:
                        start_time = "0" + start_time
                    if len(end_time) == 4:
                        end_time = "0" + end_time
                    if status == '0':
                        free_time_slot_list.append([start_time, end_time])
                    else:
                        pass
                if free_time_slot_list:
                    court_free_time_infos[court_name] = free_time_slot_list
                else:
                    pass
            return court_free_time_infos, proxy
        except Exception as error:
            print(f"[fail]: {PROXY}, {str(error)}")
            continue
    raise Exception(f"all proxy failed!")


def print_with_timestamp(*args, **kwargs):
    """
    打印函数带上当前时间戳
    """
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)


def merge_time_ranges(data: List[List[str]]) -> List[List[str]]:
    """
    将时间段合并
    Args:
        data: 包含多个时间段的列表，每个时间段由开始时间和结束时间组成，格式为[['07:00', '08:00'], ['07:00', '09:00'], ...]
    Returns:
        合并后的时间段列表，每个时间段由开始时间和结束时间组成，格式为[['07:00', '09:00'], ['09:00', '16:00'], ...]
    """
    if not data:
        return data
    else:
        pass
    print(f"merging {data}")
    # 将时间段转换为分钟数，并按照开始时间排序
    data_in_minutes = sorted([(int(start[:2]) * 60 + int(start[3:]), int(end[:2]) * 60 + int(end[3:]))
                              for start, end in data])

    # 合并重叠的时间段
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

    # 将分钟数转换为时间段
    result = [[f'{start // 60:02d}:{start % 60:02d}', f'{end // 60:02d}:{end % 60:02d}'] for start, end in merged_data]
    print(f"merged {result}")
    return result


def check_tennis_courts():
    """主要检查逻辑"""
    if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(8, 0):
        print("每天0点-8点不巡检")
        return
    
    run_start_time = time.time()
    print_with_timestamp("start to check...")

    # 查询空闲的球场信息
    up_for_send_data_list = []
    success_proxy = None
    
    for index in range(0, 7):
        input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
        inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
        print(f"checking {input_date}")
        
        try:
            court_data, success_proxy = get_tennis_court_data_by_proxy(input_date, success_proxy)
            time.sleep(5)
            
            if court_data:
                free_slot_list = []
                for court_name, free_time_slot_list in court_data.items():
                    for time_slot in free_time_slot_list:
                        hour_num = int(time_slot[0].split(':')[0])
                        if 8 <= hour_num <= 21:
                            free_slot_list.append(time_slot)
                
                if free_slot_list:
                    merged_free_slot_list = merge_time_ranges(free_slot_list)
                    up_for_send_data_list.append({
                        "date": inform_date,
                        "court_name": "青少体育",
                        "free_slot_list": merged_free_slot_list
                    })
                    break  # 有场地第一时间通知，不检查其他时间
        except Exception as e:
            print(f"Error checking date {input_date}: {str(e)}")
            continue

    # 处理通知逻辑
    # 获取现有的通知缓存
    cache_key = "上海青少体育网球场"
    try:
        notifications = Variable.get(cache_key, deserialize_json=True)
    except:
        notifications = []
    if up_for_send_data_list:

        
        # 添加新的通知
        for data in up_for_send_data_list:
            date = data['date']
            court_name = data['court_name']
            free_slot_list = data['free_slot_list']
            
            # 获取星期几
            date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
            weekday = date_obj.weekday()
            weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
            
            for free_slot in free_slot_list:
                # 生成通知字符串
                notification = f"【{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                
                # 如果不存在，则添加到列表开头
                if notification not in notifications:
                     notifications.append(notification)

        # 只保留最新的10条消息
        notifications = notifications[-10:]
        
        # 更新Variable
        description = f"上海青少体育网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        Variable.set(
            key=cache_key,
            value=notifications,
            description=description,
            serialize_json=True
        )

    print(f"up_for_send_data_list: {up_for_send_data_list}")
    print(f"notifications: {notifications}")
    run_end_time = time.time()
    execution_time = run_end_time - run_start_time
    print_with_timestamp(f"Total cost time：{execution_time} s")

# 创建DAG
dag = DAG(
    dag_id='上海青少体育网球场巡检',
    default_args=default_args,
    description='监控网球场地可用情况',
    schedule_interval='*/5 * * * *',  # 每3分钟执行一次
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=3),
    catchup=False,
    tags=['上海']
)

# 创建任务
check_courts_task = PythonOperator(
    task_id='check_tennis_courts',
    python_callable=check_tennis_courts,
    dag=dag,
)

# 设置任务依赖关系
check_courts_task
