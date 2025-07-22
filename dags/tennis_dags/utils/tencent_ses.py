import os
import json
import logging
from typing import List, Dict, Optional
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ses.v20201002 import ses_client, models


class TencentSESClient:
    """腾讯云SES邮件服务客户端"""
    
    def __init__(self, secret_id: Optional[str] = None, secret_key: Optional[str] = None, 
                 endpoint: str = "ses.tencentcloudapi.com", region: str = "ap-guangzhou"):
        """
        初始化SES客户端
        
        Args:
            secret_id: 腾讯云SecretId，默认从环境变量TENCENTCLOUD_SECRET_ID获取
            secret_key: 腾讯云SecretKey，默认从环境变量TENCENTCLOUD_SECRET_KEY获取
            endpoint: API端点
            region: 地域
        """
        self.secret_id = secret_id or os.getenv("TENCENTCLOUD_SECRET_ID")
        self.secret_key = secret_key or os.getenv("TENCENTCLOUD_SECRET_KEY")
        self.endpoint = endpoint
        self.region = region
        
        if not self.secret_id or not self.secret_key:
            raise ValueError("请设置腾讯云密钥：TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY")
        
        # 初始化客户端
        self._init_client()
    
    def _init_client(self):
        """初始化SES客户端"""
        try:
            # 实例化认证对象
            cred = credential.Credential(self.secret_id, self.secret_key)
            
            # 实例化HTTP选项
            http_profile = HttpProfile()
            http_profile.endpoint = self.endpoint
            
            # 实例化客户端选项
            client_profile = ClientProfile()
            client_profile.httpProfile = http_profile
            
            # 实例化SES客户端
            self.client = ses_client.SesClient(cred, self.region, client_profile)
            
        except Exception as e:
            logging.error(f"初始化腾讯云SES客户端失败: {e}")
            raise
    
    def send_template_email(self, 
                           subject: str,
                           template_id: str,
                           template_data: Dict,
                           recipients: List[str],
                           from_email: str,
                           reply_to: Optional[str] = None,
                           cc_emails: Optional[List[str]] = None,
                           bcc_emails: Optional[List[str]] = None,
                           trigger_type: int = 1) -> Dict:
        """
        发送模板邮件
        
        Args:
            subject: 邮件主题
            template_id: 模板ID
            template_data: 模板变量字典，例如：{"code": "1234", "name": "张三"}
            recipients: 收件人邮箱列表，最多50个
            from_email: 发件人邮箱地址，格式：别名 <邮箱地址> 或直接邮箱地址
            reply_to: 回复邮箱地址
            cc_emails: 抄送邮箱列表，最多20个
            bcc_emails: 密送邮箱列表，最多20个
            trigger_type: 邮件触发类型，0:营销类 1:触发类(验证码等)
            
        Returns:
            Dict: 包含MessageId和RequestId的响应字典
            
        Raises:
            ValueError: 参数错误
            TencentCloudSDKException: 腾讯云SDK异常
        """
        # 参数验证
        if not recipients:
            raise ValueError("收件人列表不能为空")
        
        if len(recipients) > 50:
            raise ValueError("收件人数量不能超过50个")
        
        if cc_emails and len(cc_emails) > 20:
            raise ValueError("抄送人数量不能超过20个")
        
        if bcc_emails and len(bcc_emails) > 20:
            raise ValueError("密送人数量不能超过20个")
        
        try:
            # 实例化请求对象
            req = models.SendEmailRequest()
            
            # 构建请求参数
            params = {
                "FromEmailAddress": from_email,
                "Destination": recipients,
                "Subject": subject,
                "Template": {
                    "TemplateID": template_id,
                    "TemplateData": json.dumps(template_data, ensure_ascii=False)
                },
                "TriggerType": trigger_type
            }
            
            # 可选参数
            if reply_to:
                params["ReplyToAddresses"] = reply_to
            
            if cc_emails:
                params["Cc"] = cc_emails
            
            if bcc_emails:
                params["Bcc"] = bcc_emails
            
            # 设置请求参数
            req.from_json_string(json.dumps(params))
            
            # 发送请求
            resp = self.client.SendEmail(req)
            
            # 解析响应
            response_data = json.loads(resp.to_json_string())
            
            logging.info(f"邮件发送成功，MessageId: {response_data.get('MessageId')}")
            
            return {
                "success": True,
                "message_id": response_data.get("MessageId"),
                "request_id": response_data.get("RequestId"),
                "error": None
            }
            
        except TencentCloudSDKException as e:
            error_msg = f"腾讯云SES发送失败: {e.code} - {e.message}"
            logging.error(error_msg)
            return {
                "success": False,
                "message_id": None,
                "request_id": None,
                "error": error_msg
            }
        except Exception as e:
            error_msg = f"邮件发送异常: {str(e)}"
            logging.error(error_msg)
            return {
                "success": False,
                "message_id": None,
                "request_id": None,
                "error": error_msg
            }


# 便捷函数
def send_template_email(subject: str,
                       template_id: str,
                       template_data: Dict,
                       recipients: List[str],
                       from_email: str,
                       reply_to: Optional[str] = None,
                       cc_emails: Optional[List[str]] = None,
                       bcc_emails: Optional[List[str]] = None,
                       trigger_type: int = 1) -> Dict:
    """
    发送模板邮件的便捷函数
    
    Args:
        subject: 邮件主题
        template_id: 模板ID
        template_data: 模板变量字典
        recipients: 收件人邮箱列表
        from_email: 发件人邮箱地址
        reply_to: 回复邮箱地址
        cc_emails: 抄送邮箱列表
        bcc_emails: 密送邮箱列表
        trigger_type: 邮件触发类型
        
    Returns:
        Dict: 发送结果
    """
    client = TencentSESClient()
    return client.send_template_email(
        subject=subject,
        template_id=template_id,
        template_data=template_data,
        recipients=recipients,
        from_email=from_email,
        reply_to=reply_to,
        cc_emails=cc_emails,
        bcc_emails=bcc_emails,
        trigger_type=trigger_type
    )


# 使用示例
if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试：发送网球场地预约邮件
    result = send_template_email(
        subject="Zacks网球场地预约通知",
        template_id=33340,  # 您的模板ID
        template_data={
            "COURT_NAME": "中央网球场",
            "FREE_TIME": "2024年1月15日 14:00-16:00"
        },
        recipients=["claude89757@gmail.com"],
        from_email="Zacks <tennis@zacks.com.cn>",
        reply_to="tennis@zacks.com.cn",
        trigger_type=1  # 触发类邮件
    )
    print(result)