#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# 第三方库导入
import requests
from airflow.models import Variable


class DifyAgent:
    def __init__(self, api_key, base_url, room_name="", room_id="", user_name="", user_id="", my_name=""):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self.room_name = room_name
        self.room_id = room_id
        self.user_name = user_name
        self.user_id = user_id
        self.my_name = my_name

    def create_chat_message(self, query, user_id, conversation_id="", inputs=None):
        """
        创建聊天消息
        """
        if inputs is None:
            inputs = {}

        # 增加会话名称, 对方名称, 自己的名称
        inputs["room_name"] = self.room_name
        inputs["room_id"] = self.room_id
        inputs["user_name"] = self.user_name
        inputs["user_id"] = self.user_id
        inputs["my_name"] = self.my_name

        url = f"{self.base_url}/chat-messages"
        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": "blocking",  # 改为非流式响应
            "conversation_id": conversation_id,
            "user": user_id,
            "auto_generate_name": False
        }
        print("="*50)
        print(f"url: {url}")
        print(f"payload: {payload}")
        print("="*50)
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"创建消息失败: {response.text}")

    def list_conversations(self, user_id, last_id="", limit=20, sort_by="-updated_at"):
        """
        获取用户会话列表
        """
        url = f"{self.base_url}/conversations"
        params = {
            "user": user_id,
            "last_id": last_id,
            "limit": limit,
            "sort_by": sort_by
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"获取会话列表失败: {response.text}")

    def get_conversation_id_for_room(self, user_id, room_id):
        """
        获取对应room_id + sender_id 的Dify的AI助手会话
        """
        conversation_infos = Variable.get(f"{user_id}_conversation_infos", default_var={}, deserialize_json=True)
        
        # 检查是否存在会话ID
        conversation_id = conversation_infos.get(room_id)
        if conversation_id:
            # 尝试获取会话列表
            conversations = self.list_conversations(user_id=user_id, limit=100)
            conversation_exists = False
            # 检查会话是否存在且状态正常
            if conversations.get("data"):
                for conv in conversations["data"]:
                    if conv.get("id") == conversation_id and conv.get("status") == "normal":
                        conversation_exists = True
                        break
            if not conversation_exists:
                pass
            else:
                print(f"{user_id} 使用已存在的会话ID: {conversation_id}")
                return conversation_id
        else:
            pass

        # 创建新会话
        response = self.create_chat_message(
            query="hi",
            user_id=user_id,
            inputs={"enable_ai": 0}
        )
        conversation_id = response.get("conversation_id")

        # 重命名会话名称, 使用room_id来命名
        self.rename_conversation(conversation_id, user_id, name=room_id, auto_generate=False)

        # 保存会话ID
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{user_id}_conversation_infos", conversation_infos, serialize_json=True)
        print(f"{user_id} 创建新会话ID: {conversation_id}")
        
        return conversation_id

    def rename_conversation(self, conversation_id, user_id, name="", auto_generate=False):
        """
        重命名会话
        
        Args:
            conversation_id (str): 会话ID
            user_id (str): 用户标识，必填参数
            name (str, optional): 会话名称. 当auto_generate为True时可不传
            auto_generate (bool, optional): 是否自动生成标题. 默认为False
            
        Returns:
            dict: 包含会话信息的响应数据
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/conversations/{conversation_id}/name"
        
        if not user_id:
            raise ValueError("user_id 是必填参数")
            
        payload = {
            "user": user_id
        }
        
        if auto_generate:
            payload["auto_generate"] = True
        elif name:
            payload["name"] = name
        else:
            raise ValueError("必须提供name或设置auto_generate=True")
            
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"重命名会话失败: {response.text}")
