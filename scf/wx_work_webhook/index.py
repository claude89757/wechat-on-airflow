#!/usr/bin/env python3
# -*- coding: utf8 -*-
"""
企业微信云函数处理程序

用于处理企业微信的消息接收、解密、回复等功能。
支持明文模式和安全模式(AES加密)。

主要功能:
1. 处理企业微信服务器的URL验证请求
2. 接收并解密企业微信消息
3. 处理不同类型的消息和事件
4. 加密并回复消息
5. 与Airflow集成,实现消息的异步处理

环境变量:
- TOKEN: 企业微信的Token
- ENCODING_AES_KEY: 消息加解密密钥
- CORPID: 企业微信的企业ID
- AIRFLOW_*: Airflow相关配置

Author: Claude
Date: 2024-03-20
"""

import json
import os
import time
import hashlib
import requests
import ierror
import xml.etree.cElementTree as ET
from WXBizMsgCrypt import WXBizMsgCrypt

# 企业微信配置信息
TOKEN = os.getenv("WX_WORK_TOKEN")
ENCODING_AES_KEY = os.getenv("WX_WORK_ENCODING_AES_KEY")
CORPID = os.getenv("WX_WORK_CORPID")  # 注意这里使用CORPID而不是APPID

# 从环境变量获取Airflow配置
AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD")
AIRFLOW_DAG_ID = os.getenv("AIRFLOW_DAG_ID", "wx_work_msg_watcher")


def json_to_xml(json_data):
    """将JSON格式的消息转换为XML格式"""
    root = ET.Element('xml')
    for key, value in json_data.items():
        element = ET.SubElement(root, key)
        if value is not None:
            if isinstance(value, dict):
                # 如果值是字典，递归创建子元素
                for sub_key, sub_value in value.items():
                    sub_element = ET.SubElement(element, sub_key)
                    sub_element.text = str(sub_value)
            else:
                element.text = str(value)
    xml_result = ET.tostring(root, encoding='utf-8')
    print(f"JSON转XML结果: {xml_result}")
    return xml_result

def xml_to_json(xml_str):
    """将XML格式的消息转换为JSON格式"""
    if isinstance(xml_str, bytes):
        xml_str = xml_str.decode('utf-8')
    print(f"准备解析的XML: {xml_str}")
    root = ET.fromstring(xml_str)
    result = {}
    
    def _extract(element, obj):
        """递归提取XML节点中的值"""
        for child in element:
            if len(child) > 0:
                # 如果有子节点，递归处理
                child_obj = {}
                _extract(child, child_obj)
                obj[child.tag] = child_obj
            else:
                obj[child.tag] = child.text
    
    _extract(root, result)
    print(f"XML转JSON结果: {json.dumps(result, ensure_ascii=False)}")
    return result

def verify_signature(token, timestamp, nonce, encrypt, msg_signature):
    """验证消息签名"""
    print(f"验证签名参数: token={token}, timestamp={timestamp}, nonce={nonce}, encrypt={encrypt}, msg_signature={msg_signature}")
    
    # 排序并拼接参数
    sort_list = [token, timestamp, nonce, encrypt]
    sort_list.sort()
    
    # 计算签名
    sha = hashlib.sha1()
    sha.update("".join(sort_list).encode('utf-8'))
    calculated_signature = sha.hexdigest()
    
    print(f"计算得到的签名: {calculated_signature}")
    print(f"企业微信传入的签名: {msg_signature}")
    
    # 检查签名是否匹配
    is_valid = calculated_signature == msg_signature
    print(f"签名验证结果: {'成功' if is_valid else '失败'}")
    return is_valid

def decrypt_message(wx_crypt, encrypted_msg, msg_signature, timestamp, nonce):
    """解密企业微信消息"""
    print(f"解密消息参数: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}")
    print(f"待解密消息: {json.dumps(encrypted_msg, ensure_ascii=False) if isinstance(encrypted_msg, dict) else encrypted_msg}")
    
    xml_msg = None
    
    if isinstance(encrypted_msg, dict):
        # 如果是JSON格式，转换为XML
        # 检查是否有Encrypt字段
        if "Encrypt" in encrypted_msg:
            print(f"发现Encrypt字段: {encrypted_msg['Encrypt']}")
            xml_data = {"ToUserName": encrypted_msg.get("ToUserName", ""), "Encrypt": encrypted_msg["Encrypt"]}
            xml_msg = json_to_xml(xml_data)
        else:
            # 完整的XML结构
            print("未发现Encrypt字段，使用完整JSON转XML")
            xml_msg = json_to_xml(encrypted_msg)
    else:
        # 确保XML是字节类型
        if isinstance(encrypted_msg, str):
            print("输入是字符串，转换为字节")
            xml_msg = encrypted_msg.encode('utf-8')
        else:
            print("输入已经是字节类型")
            xml_msg = encrypted_msg
    
    if xml_msg is None:
        print("无法获取有效的XML消息")
        return ierror.WXBizMsgCrypt_ParseXml_Error, None
    
    print(f"准备解密的XML消息: {xml_msg}")
    ret, decrypted_xml = wx_crypt.DecryptMsg(xml_msg, msg_signature, timestamp, nonce)
    
    print(f"解密结果: ret={ret}")
    if ret != 0:
        print(f"解密失败，错误码: {ret}")
        return ret, None
    
    print(f"解密后的XML: {decrypted_xml}")
    
    # 解析XML为JSON
    try:
        if isinstance(decrypted_xml, bytes):
            decrypted_json = xml_to_json(decrypted_xml)
        else:
            decrypted_json = xml_to_json(decrypted_xml)
        return 0, decrypted_json
    except Exception as e:
        print("解析XML出错:", str(e))
        return ierror.WXBizMsgCrypt_ParseXml_Error, None

def encrypt_message(wx_crypt, reply_msg, nonce, timestamp=None):
    """加密回复消息"""
    if timestamp is None:
        timestamp = str(int(time.time()))
    
    print(f"加密回复消息参数: nonce={nonce}, timestamp={timestamp}")
    print(f"待加密消息: {json.dumps(reply_msg, ensure_ascii=False) if isinstance(reply_msg, dict) else reply_msg}")
    
    xml_str = None
    
    if isinstance(reply_msg, dict):
        # 将字典转换为XML字符串
        print("将字典转换为XML")
        xml_str = json_to_xml(reply_msg)
    elif isinstance(reply_msg, str):
        try:
            # 尝试解析JSON字符串
            print("尝试解析JSON字符串")
            reply_json = json.loads(reply_msg)
            xml_str = json_to_xml(reply_json)
        except:
            # 假设已经是XML格式字符串
            print("假设输入已经是XML格式")
            xml_str = reply_msg.encode('utf-8') if isinstance(reply_msg, str) else reply_msg
    
    # 确保xml_str是字符串类型
    if isinstance(xml_str, bytes):
        xml_str = xml_str.decode('utf-8')
    
    print(f"准备加密的XML: {xml_str}")
    ret, encrypted_xml = wx_crypt.EncryptMsg(xml_str, nonce, timestamp)
    
    print(f"加密结果: ret={ret}")
    if ret != 0:
        print(f"加密失败，错误码: {ret}")
        return ret, None
    
    print(f"加密后的XML: {encrypted_xml}")
    
    # 转换为JSON格式响应
    if isinstance(encrypted_xml, bytes):
        encrypted_xml = encrypted_xml.decode('utf-8')
    
    try:
        xml_root = ET.fromstring(encrypted_xml)
        result = {}
        for child in xml_root:
            result[child.tag] = child.text
        print(f"加密后的响应: {json.dumps(result, ensure_ascii=False)}")
        return 0, result
    except Exception as e:
        print("解析加密XML出错:", str(e))
        return ierror.WXBizMsgCrypt_ParseXml_Error, None

def handle_message(msg):
    """处理解密后的消息，并返回响应"""
    # 打印解密后的消息，用于调试
    print("收到消息: ", json.dumps(msg, ensure_ascii=False))
    
    # 根据消息类型处理
    msg_type = msg.get('MsgType')
    event_type = msg.get('Event')
    
    print(f"消息类型: {msg_type}, 事件类型: {event_type}")
    
    # 异步发送消息到Airflow进行处理
    try:
        # 在后台发送消息到Airflow
        send_result = send_message_to_airflow(msg)
        if send_result:
            print("成功发送消息到Airflow进行处理")
        else:
            print("发送消息到Airflow失败")
    except Exception as e:
        print(f"发送消息到Airflow时出错: {str(e)}")
    
    # 企业微信通常只要返回success即可
    # 注意：企业微信接口与公众号接口不同，一般不需要回复消息
    return "success"

def send_message_to_airflow(msg):
    """把收到的消息作为airflow流程的触发参数，触发airflow流程"""
    print(f"发送消息到Airflow: {msg}")
    
    if not all([AIRFLOW_BASE_URL, AIRFLOW_USERNAME, AIRFLOW_PASSWORD]):
        print("错误: 缺少Airflow配置环境变量")
        return False
    
    try:
        # 准备回调数据
        callback_data = msg
        
        # 根据Airflow的DAG run ID命名规范, 删除所有非字母数字字符
        # 企业微信消息可能使用MsgId或其他标识
        msg_id = msg.get('MsgId', str(int(time.time())))
        to_user_name = msg.get('ToUserName', 'unknown')
        dag_run_id = f"wxwork_{to_user_name}_{msg_id}"
        
        # 准备Airflow API的请求数据
        airflow_payload = {
            "conf": callback_data,
            "dag_run_id": dag_run_id,
            "note": "Triggered by WeiXin Work SCF"
        }
        
        print(f"准备触发Airflow DAG, dag_run_id: {dag_run_id}")
        print(f"请求URL: {AIRFLOW_BASE_URL}/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns")
        print(f"请求数据: {airflow_payload}")
        
        # 使用requests发送请求
        response = requests.post(
            f"{AIRFLOW_BASE_URL}/api/v1/dags/{AIRFLOW_DAG_ID}/dagRuns",
            json=airflow_payload,
            headers={'Content-Type': 'application/json'},
            auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD),
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            print(f"成功触发Airflow DAG: {AIRFLOW_DAG_ID}, dag_run_id: {dag_run_id}")
            return True
        else:
            print(f"触发Airflow DAG失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"触发Airflow DAG任务失败: {str(e)}")
        return False

def main_handler(event, context):
    print("收到事件: " + json.dumps(event, indent=2, ensure_ascii=False))
    print("环境变量TOKEN: " + TOKEN)
    print("环境变量ENCODING_AES_KEY: " + ENCODING_AES_KEY)
    print("环境变量CORPID: " + CORPID)
    
    try:
        # 创建加解密实例
        print("创建WXBizMsgCrypt实例")
        wx_crypt = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORPID)
        
        # 获取请求信息
        if 'queryString' in event:
            # 获取URL参数
            query_params = event.get('queryString', {})
            msg_signature = query_params.get('msg_signature', '')
            timestamp = query_params.get('timestamp', '')
            nonce = query_params.get('nonce', '')
            echostr = query_params.get('echostr', '')
            
            print(f"URL参数: msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce}")
            print(f"URL参数: echostr={echostr}")
            
            # 如果是验证请求，解密并返回echostr
            if echostr:
                print(f"收到验证请求，需要解密echostr: {echostr}")
                # 企业微信验证流程与公众号不同，需要解密echostr
                ret, decoded_echostr = wx_crypt.VerifyURL(msg_signature, timestamp, nonce, echostr)
                
                if ret != 0:
                    error_msg = f"验证URL失败，错误码: {ret}"
                    print(error_msg)
                    return {"errcode": ret, "errmsg": error_msg}
                
                print(f"解密后的echostr: {decoded_echostr}")
                return decoded_echostr
            
            # 获取请求体
            if 'body' in event:
                body = event.get('body', '')
                print(f"请求体: {body}")
                
                # 尝试解析为JSON
                if body and isinstance(body, str):
                    try:
                        body = json.loads(body)
                        print(f"解析JSON成功: {json.dumps(body, ensure_ascii=False)}")
                    except Exception as e:
                        # 非JSON格式，保持原样
                        print(f"解析JSON失败: {str(e)}")
                
                # 企业微信始终使用加密模式
                print("使用安全模式处理企业微信消息")
                # 验证并解密消息
                ret, decrypted_msg = decrypt_message(wx_crypt, body, msg_signature, timestamp, nonce)
                
                if ret != 0:
                    error_msg = f"解密失败，错误码: {ret}"
                    print(error_msg)
                    return {"errcode": ret, "errmsg": error_msg}
                
                # 处理解密后的消息
                print("处理解密后的消息")
                result = handle_message(decrypted_msg)
                
                # 企业微信只需返回字符串"success"
                print("返回处理结果")
                return result
        
        # 默认返回
        print("无法处理的请求，返回默认值")
        return "success"
    
    except Exception as e:
        error_msg = f"处理出错: {str(e)}"
        print(error_msg)
        import traceback
        print(f"异常堆栈: {traceback.format_exc()}")
        return {"errcode": -1, "errmsg": error_msg} 