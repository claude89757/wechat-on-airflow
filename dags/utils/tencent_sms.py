#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/7/4 15:24
@Author  : claude89757
@File    : send_text.py
@Software: PyCharm
"""
import os
import json
import hashlib
import hmac
import sys
import time
from datetime import datetime

if sys.version_info[0] <= 2:
    from httplib import HTTPSConnection
else:
    from http.client import HTTPSConnection

def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def send_sms_for_news(phone_num_list: list, param_list: list, template_id: str = '1856675'):
    """
    发生短信通知
    example: send_sms_for_news(["xxxxx"], param_list=["08-03", "大沙河", "21:00", "20:00"])
    """
    try:
        from airflow.models import Variable
        TENCENT_CLOUD_SECRET_ID = Variable.get("TENCENT_CLOUD_SECRET_ID")
        TENCENT_CLOUD_SECRET_KEY = Variable.get("TENCENT_CLOUD_SECRET_KEY")
    except Exception as e:
        print(f"Error: {e}")
        TENCENT_CLOUD_SECRET_ID = os.environ.get("TENCENT_CLOUD_SECRET_ID")
        TENCENT_CLOUD_SECRET_KEY = os.environ.get("TENCENT_CLOUD_SECRET_KEY")

    if not TENCENT_CLOUD_SECRET_ID or not TENCENT_CLOUD_SECRET_KEY:
        raise ValueError("TENCENT_CLOUD_SECRET_ID or TENCENT_CLOUD_SECRET_KEY is not set")

    sign_name = "网球场预定助手小程序"
    try:
        # 必要参数
        secret_id = TENCENT_CLOUD_SECRET_ID
        secret_key = TENCENT_CLOUD_SECRET_KEY
        service = "sms"
        host = "sms.tencentcloudapi.com"
        region = "ap-guangzhou"
        version = "2021-01-11"
        action = "SendSms"
        token = ""
        
        # 构造请求体
        request_data = {
            "SmsSdkAppId": "1400835675",
            "SignName": sign_name,
            "TemplateId": template_id,
            "TemplateParamSet": param_list,
            "PhoneNumberSet": phone_num_list,
            "SessionContext": "",
            "ExtendCode": "",
            "SenderId": ""
        }
        
        payload = json.dumps(request_data)
        
        # 签名步骤
        algorithm = "TC3-HMAC-SHA256"
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        # 步骤 1：拼接规范请求串
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (http_request_method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)
        
        # 步骤 2：拼接待签名字符串
        credential_scope = date + "/" + service + "/" + "tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = (algorithm + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)
        
        # 步骤 3：计算签名
        secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        
        # 步骤 4：拼接 Authorization
        authorization = (algorithm + " " +
                        "Credential=" + secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)
        
        # 步骤 5：构造并发起请求
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version
        }
        
        if region:
            headers["X-TC-Region"] = region
        if token:
            headers["X-TC-Token"] = token
        
        conn = HTTPSConnection(host)
        conn.request("POST", "/", headers=headers, body=payload)
        response = conn.getresponse()
        result = response.read().decode("utf-8")
        conn.close()
        
        return json.loads(result)
        
    except Exception as err:
        print(err)
        return {"Error": str(err)}


# testing
if __name__ == '__main__':
    phone = "xxx"
    sms_res = send_sms_for_news([phone], param_list=["08-03", "大沙河", "21:00", "20:00"])
    print(sms_res)
