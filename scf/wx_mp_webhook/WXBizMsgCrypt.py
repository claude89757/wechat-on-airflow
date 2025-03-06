#!/usr/bin/env python
#-*- encoding:utf-8 -*-

""" 对公众平台发送给公众账号的消息加解密示例代码.
@copyright: Copyright (c) 1998-2014 Tencent Inc.

"""
# ------------------------------------------------------------------------

import base64
import string
import random
import hashlib
import time
import struct

import xml.etree.cElementTree as ET
import sys
import socket
from Crypto.Cipher import AES
#from cryptography.hazmat.primitives.ciphers.algorithms import AES

import ierror

try:
    reload(sys)
    sys.setdefaultencoding('utf-8')
except NameError:
    # Python 3 不需要 reload
    pass

"""
关于Crypto.Cipher模块，ImportError: No module named 'Crypto'解决方案
请到官方网站 https://www.dlitz.net/software/pycrypto/ 下载pycrypto。
下载后，按照README中的"Installation"小节的提示进行pycrypto安装。
"""
class FormatException(Exception):
    pass

def throw_exception(message, exception_class=FormatException):
    """my define raise exception function"""
    raise exception_class(message)

class SHA1:
    """计算公众平台的消息签名接口"""

    def getSHA1(self, token, timestamp, nonce, encrypt):
        """用SHA1算法生成安全签名
        @param token:  票据
        @param timestamp: 时间戳
        @param encrypt: 密文
        @param nonce: 随机字符串
        @return: 安全签名
        """
        try:
            sortlist = [token, timestamp, nonce, encrypt]
            sortlist.sort()
            sha = hashlib.sha1()
            sha.update("".join(sortlist).encode('utf-8'))
            return  ierror.WXBizMsgCrypt_OK, sha.hexdigest()
        except Exception as e:
            #print e
            return  ierror.WXBizMsgCrypt_ComputeSignature_Error, None


class XMLParse:
    """提供提取消息格式中的密文及生成回复消息格式的接口"""

    # xml消息模板
    AES_TEXT_RESPONSE_TEMPLATE = """<xml>
<Encrypt><![CDATA[%(msg_encrypt)s]]></Encrypt>
<MsgSignature><![CDATA[%(msg_signaturet)s]]></MsgSignature>
<TimeStamp>%(timestamp)s</TimeStamp>
<Nonce><![CDATA[%(nonce)s]]></Nonce>
</xml>"""

    def extract(self, xmltext):
        """提取出xml数据包中的加密消息
        @param xmltext: 待提取的xml字符串
        @return: 提取出的加密消息字符串
        """
        try:
            if isinstance(xmltext, bytes):
                xmltext = xmltext.decode('utf-8')
            xml_tree = ET.fromstring(xmltext)
            encrypt = xml_tree.find("Encrypt")
            touser_name = xml_tree.find("ToUserName")
            return ierror.WXBizMsgCrypt_OK, encrypt.text, touser_name.text
        except Exception as e:
            #print(e)
            return ierror.WXBizMsgCrypt_ParseXml_Error, None, None

    def generate(self, encrypt, signature, timestamp, nonce):
        """生成xml消息
        @param encrypt: 加密后的消息密文
        @param signature: 安全签名
        @param timestamp: 时间戳
        @param nonce: 随机字符串
        @return: 生成的xml字符串
        """
        resp_dict = {
                    'msg_encrypt': encrypt,
                    'msg_signaturet': signature,
                    'timestamp': timestamp,
                    'nonce': nonce,
                     }
        resp_xml = self.AES_TEXT_RESPONSE_TEMPLATE % resp_dict
        return resp_xml


class PKCS7Encoder():
    """提供基于PKCS7算法的加解密接口"""

    block_size = 32
    def encode(self, text):
        """ 对需要加密的明文进行填充补位
        @param text: 需要进行填充补位操作的明文
        @return: 补齐明文字符串
        """
        text_length = len(text)
        # 计算需要填充的位数
        amount_to_pad = self.block_size - (text_length % self.block_size)
        if amount_to_pad == 0:
            amount_to_pad = self.block_size
        # 获得补位所用的字符
        pad = chr(amount_to_pad)
        if isinstance(text, bytes):
            # 如果是bytes，补位字符也需要是bytes
            padded = text + (pad * amount_to_pad).encode('utf-8')
        else:
            padded = text + pad * amount_to_pad
        return padded

    def decode(self, decrypted):
        """删除解密后明文的补位字符
        @param decrypted: 解密后的明文
        @return: 删除补位字符后的明文
        """
        if isinstance(decrypted, bytes):
            # 如果是bytes，获取最后一个字节
            pad = decrypted[-1]
        else:
            pad = ord(decrypted[-1])
        if pad < 1 or pad > 32:
            pad = 0
        return decrypted[:-pad]


class Prpcrypt(object):
    """提供接收和推送给公众平台消息的加解密接口"""

    def __init__(self, key):
        #self.key = base64.b64decode(key+"=")
        self.key = key
        # 设置加解密模式为AES的CBC模式
        self.mode = AES.MODE_CBC

    def encrypt(self, text, appid):
        """对明文进行加密
        @param text: 需要加密的明文
        @return: 加密得到的字符串
        """
        # 确保text是字符串
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        
        # 确保appid是字符串
        if isinstance(appid, bytes):
            appid = appid.decode('utf-8')
            
        # 16位随机字符串添加到明文开头
        random_str = self.get_random_str()
        
        # 将所有内容转为字节
        text_bytes = text.encode('utf-8')
        appid_bytes = appid.encode('utf-8')
        random_str_bytes = random_str.encode('utf-8')
        
        # 拼接内容
        text_bytes_len = len(text_bytes)
        packed_len = struct.pack("I", socket.htonl(text_bytes_len))
        content = random_str_bytes + packed_len + text_bytes + appid_bytes
        
        # 使用自定义的填充方式对明文进行补位填充
        pkcs7 = PKCS7Encoder()
        padded_content = pkcs7.encode(content)
        
        # 加密
        cryptor = AES.new(self.key, self.mode, self.key[:16])
        try:
            ciphertext = cryptor.encrypt(padded_content)
            # 使用BASE64对加密后的字符串进行编码
            return ierror.WXBizMsgCrypt_OK, base64.b64encode(ciphertext).decode('utf-8')
        except Exception as e:
            #print(e)
            return ierror.WXBizMsgCrypt_EncryptAES_Error, None

    def decrypt(self, text, appid):
        """对解密后的明文进行补位删除
        @param text: 密文
        @return: 删除填充补位后的明文
        """
        try:
            cryptor = AES.new(self.key, self.mode, self.key[:16])
            # 使用BASE64对密文进行解码，然后AES-CBC解密
            if isinstance(text, str):
                text = text.encode('utf-8')
            plain_text = cryptor.decrypt(base64.b64decode(text))
        except Exception as e:
            #print(e)
            return ierror.WXBizMsgCrypt_DecryptAES_Error, None
        try:
            # 去掉补位字符串
            pkcs7 = PKCS7Encoder()
            plain_text = pkcs7.decode(plain_text)
            
            # 去除16位随机字符串
            xml_len = socket.ntohl(struct.unpack("I", plain_text[16:20])[0])
            xml_content = plain_text[20:20 + xml_len]
            from_appid = plain_text[20 + xml_len:]
            
            # 确保appid是字节类型，用于比较
            if isinstance(appid, str):
                appid = appid.encode('utf-8')
                
        except Exception as e:
            #print(e)
            return ierror.WXBizMsgCrypt_IllegalBuffer, None
            
        if from_appid != appid:
            return ierror.WXBizMsgCrypt_ValidateAppid_Error, None
            
        return 0, xml_content

    def get_random_str(self):
        """ 随机生成16位字符串
        @return: 16位字符串
        """
        rule = string.ascii_letters + string.digits
        random_chars = random.sample(rule, 16)
        return "".join(random_chars)


class WXBizMsgCrypt(object):
    #构造函数
    #@param sToken: 公众平台上，开发者设置的Token
    # @param sEncodingAESKey: 公众平台上，开发者设置的EncodingAESKey
    # @param sAppId: 企业号的AppId
    def __init__(self, sToken, sEncodingAESKey, sAppId):
        try:
            self.key = base64.b64decode(sEncodingAESKey + "=")
            assert len(self.key) == 32
        except:
            throw_exception("[error]: EncodingAESKey unvalid !", FormatException)
            #return ierror.WXBizMsgCrypt_IllegalAesKey)
        self.token = sToken
        self.appid = sAppId

    def EncryptMsg(self, sReplyMsg, sNonce, timestamp=None):
        #将公众号回复用户的消息加密打包
        #@param sReplyMsg: 企业号待回复用户的消息，xml格式的字符串
        #@param sTimeStamp: 时间戳，可以自己生成，也可以用URL参数的timestamp,如为None则自动用当前时间
        #@param sNonce: 随机串，可以自己生成，也可以用URL参数的nonce
        #sEncryptMsg: 加密后的可以直接回复用户的密文，包括msg_signature, timestamp, nonce, encrypt的xml格式的字符串,
        #return：成功0，sEncryptMsg,失败返回对应的错误码None
        pc = Prpcrypt(self.key)
        ret, encrypt = pc.encrypt(sReplyMsg, self.appid)
        if ret != 0:
            return ret, None
        if timestamp is None:
            timestamp = str(int(time.time()))
        # 生成安全签名
        sha1 = SHA1()
        ret, signature = sha1.getSHA1(self.token, timestamp, sNonce, encrypt)
        if ret != 0:
            return ret, None
        xmlParse = XMLParse()
        return ret, xmlParse.generate(encrypt, signature, timestamp, sNonce)

    def DecryptMsg(self, sPostData, sMsgSignature, sTimeStamp, sNonce):
        # 检验消息的真实性，并且获取解密后的明文
        # @param sMsgSignature: 签名串，对应URL参数的msg_signature
        # @param sTimeStamp: 时间戳，对应URL参数的timestamp
        # @param sNonce: 随机串，对应URL参数的nonce
        # @param sPostData: 密文，对应POST请求的数据
        #  xml_content: 解密后的原文，当return返回0时有效
        # @return: 成功0，失败返回对应的错误码
        # 验证安全签名
        xmlParse = XMLParse()
        ret, encrypt, touser_name = xmlParse.extract(sPostData)
        if ret != 0:
            return ret, None
        sha1 = SHA1()
        ret, signature = sha1.getSHA1(self.token, sTimeStamp, sNonce, encrypt)
        if ret != 0:
            return ret, None
        if not signature == sMsgSignature:
            return ierror.WXBizMsgCrypt_ValidateSignature_Error, None
        pc = Prpcrypt(self.key)
        ret, xml_content = pc.decrypt(encrypt, self.appid)
        return ret, xml_content

