#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# 第三方库导入
import requests
from airflow.models import Variable
import json


class DifyAgent:
    def __init__(self, api_key, base_url, room_name="", room_id="", sender_name="", sender_id="", my_name="", is_group=""):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self.room_name = room_name
        self.room_id = room_id
        self.sender_name = sender_name
        self.sender_id = sender_id
        self.my_name = my_name
        self.is_group = is_group

    def create_chat_message(self, query, user_id, conversation_id="", inputs=None):
        """
        创建聊天消息
        """
        if inputs is None:
            inputs = {}

        # 增加会话名称, 对方名称, 自己的名称
        inputs["room_name"] = self.room_name
        inputs["room_id"] = self.room_id
        inputs["sender_name"] = self.sender_name
        inputs["sender_id"] = self.sender_id
        inputs["my_name"] = self.my_name
        inputs["is_group"] = self.is_group

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
        根据房间ID获取对应的会话ID
        
        Args:
            user_id (str): 用户标识
            room_id (str): 房间ID
            
        Returns:
            str: 会话ID。如果找不到有效会话则返回空字符串
            
        说明:
            1. 先从缓存中获取会话ID
            2. 如果缓存中有会话ID,则检查该会话是否仍然有效
            3. 如果会话无效或不存在,则返回空字符串,由调用方创建新会话
        """
        conversation_infos = Variable.get(f"{user_id}_conversation_infos", default_var={}, deserialize_json=True)
        
        # 检查是否存在会话ID
        conversation_id = conversation_infos.get(room_id)
        if conversation_id:
            print(f"{user_id} 使用已存在的会话ID: {conversation_id}")
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

        return ""

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

    def get_conversation_messages(self, conversation_id, user_id, first_id="", limit=100):
        """
        获取会话历史消息
        
        Args:
            conversation_id (str): 会话ID
            user_id (str): 用户标识
            first_id (str, optional): 当前页第一条聊天记录的ID，默认为空
            limit (int, optional): 一次请求返回的消息条数，默认20条
            
        Returns:
            dict: 包含消息列表的响应数据，格式如下：
                {
                    "data": [
                        {
                            "id": "消息ID",
                            "conversation_id": "会话ID",
                            "inputs": {}, # 用户输入参数
                            "query": "用户输入内容",
                            "message_files": [], # 消息文件列表
                            "answer": "回答内容",
                            "created_at": "创建时间",
                            "feedback": {
                                "rating": "like/dislike"
                            }
                        }
                    ],
                    "has_more": bool, # 是否还有更多消息
                    "limit": int # 返回的消息条数
                }
                
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/messages"
        params = {
            "conversation_id": conversation_id,
            "user": user_id,
            "first_id": first_id,
            "limit": limit
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code == 200:
            messages = response.json()["data"]
            return messages
        else:
            raise Exception(f"获取会话历史消息失败: {response.text}")

    def delete_conversation(self, conversation_id, user_id):
        """
        删除指定的会话
        
        Args:
            conversation_id (str): 要删除的会话ID
            user_id (str): 用户标识
            
        Returns:
            dict: 包含删除结果的响应数据，成功时返回 {"result": "success"}
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/conversations/{conversation_id}"
        payload = {
            "user": user_id
        }
        
        response = requests.delete(url, headers=self.headers, json=payload)
        if response.status_code == 200:
            # 从本地存储中删除会话ID映射
            conversation_infos = Variable.get(f"{user_id}_conversation_infos", default_var={}, deserialize_json=True)
            # 找到并删除对应的room_id
            for room_id, conv_id in list(conversation_infos.items()):
                if conv_id == conversation_id:
                    del conversation_infos[room_id]
                    Variable.set(f"{user_id}_conversation_infos", conversation_infos, serialize_json=True)
                    break
            return response.json()
        else:
            raise Exception(f"删除会话失败: {response.text}")

    def create_message_feedback(self, message_id, user_id, rating="like", content=""):
        """
        为消息添加反馈（点赞/点踩）
        
        Args:
            message_id (str): 消息ID
            user_id (str): 用户标识
            rating (str, optional): 反馈类型，可选值：'like'(点赞)、'dislike'(点踩)、None(撤销). 默认为'like'
            content (str, optional): 反馈的具体信息. 默认为空字符串
            
        Returns:
            dict: 包含反馈结果的响应数据，成功时返回 {"result": "success"}
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/messages/{message_id}/feedbacks"
        
        payload = {
            "rating": rating,
            "user": user_id,
            "content": content
        }
        
        print(f"创建消息反馈, url: {url}, payload: {payload}")  # 添加日志
        response = requests.post(url, headers=self.headers, json=payload)
        
        if response.status_code == 200:
            return response.json()
        else:
            # 增加更详细的错误信息
            error_msg = f"状态码: {response.status_code}, 响应内容: {response.text}"
            raise Exception(f"创建消息反馈失败: {error_msg}")

    def create_chat_message_stream(self, query, user_id, conversation_id="", inputs=None):
        """
        创建聊天消息并以流式方式返回结果
        
        Args:
            query (str): 用户输入内容
            user_id (str): 用户标识
            conversation_id (str, optional): 会话ID
            inputs (dict, optional): 输入参数
            
        Returns:
            tuple: (完整回答文本, 元数据字典)
                - 完整回答文本: AI助手的完整回答内容
                - 元数据字典: 包含message_id, conversation_id, task_id等信息
        """
        if inputs is None:
            inputs = {}

        # 增加会话相关信息
        inputs["room_name"] = self.room_name
        inputs["room_id"] = self.room_id
        inputs["sender_name"] = self.sender_name
        inputs["sender_id"] = self.sender_id
        inputs["my_name"] = self.my_name

        url = f"{self.base_url}/chat-messages"
        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": "streaming",  # 使用流式响应
            "conversation_id": conversation_id,
            "user": user_id,
            "auto_generate_name": False
        }

        full_answer = ""
        metadata = {}
        task_id = None
        workflow_metadata = {}
        
        with requests.post(url, headers=self.headers, json=payload, stream=True) as response:
            if response.status_code != 200:
                raise Exception(f"创建消息失败: {response.text}")
            
            for line in response.iter_lines():
                if line:
                    # 移除 "data: " 前缀并解析 JSON
                    line = line.decode('utf-8')
                    if not line.startswith("data: "):
                        continue
                    
                    data = json.loads(line[6:])  # 跳过 "data: " 前缀
                    print(f"data: {data}")
                    event = data.get("event")
                    
                    # 保存task_id和message_id
                    if "task_id" in data:
                        task_id = data["task_id"]
                    if "message_id" in data:
                        message_id = data["message_id"]

                    # 处理不同类型的事件
                    if event == "message":
                        # 累积回答文本
                        answer_chunk = data.get("answer", "")
                        full_answer += answer_chunk
                        
                    elif event == "message_end":
                        # 保存元数据
                        metadata = {
                            "message_id": data.get("message_id"),
                            "conversation_id": data.get("conversation_id"),
                            "metadata": data.get("metadata"),
                            "usage": data.get("usage"),
                            "retriever_resources": data.get("retriever_resources"),
                            "task_id": task_id,  # 添加task_id到元数据中
                            "workflow_metadata": workflow_metadata  # 添加workflow相关信息
                        }
                        
                    elif event == "workflow_started":
                        workflow_metadata["workflow_id"] = data.get("workflow_run_id")
                        workflow_metadata["started_at"] = data.get("data", {}).get("created_at")
                        
                    elif event == "workflow_finished":
                        workflow_data = data.get("data", {})
                        workflow_metadata.update({
                            "status": workflow_data.get("status"),
                            "elapsed_time": workflow_data.get("elapsed_time"),
                            "total_tokens": workflow_data.get("total_tokens"),
                            "total_steps": workflow_data.get("total_steps"),
                            "finished_at": workflow_data.get("finished_at")
                        })
                        
                    elif event == "node_started":
                        node_data = data.get("data", {})
                        if "nodes" not in workflow_metadata:
                            workflow_metadata["nodes"] = []
                        workflow_metadata["nodes"].append({
                            "node_id": node_data.get("node_id"),
                            "node_type": node_data.get("node_type"),
                            "title": node_data.get("title"),
                            "status": "started",
                            "started_at": node_data.get("created_at")
                        })
                        
                    elif event == "node_finished":
                        node_data = data.get("data", {})
                        for node in workflow_metadata.get("nodes", []):
                            if node.get("node_id") == node_data.get("node_id"):
                                node.update({
                                    "status": node_data.get("status"),
                                    "elapsed_time": node_data.get("elapsed_time"),
                                    "execution_metadata": node_data.get("execution_metadata"),
                                    "finished_at": node_data.get("created_at")
                                })
                                
                    elif event == "error":
                        error_msg = data.get("message", "未知错误")
                        raise Exception(f"流式响应错误: {error_msg}")
        
        return full_answer, metadata

    def stop_chat_message(self, task_id, user_id):
        """
        停止流式响应
        
        Args:
            task_id (str): 任务ID，从流式响应的chunk中获取
            user_id (str): 用户标识，必须和发送消息时的user_id保持一致
            
        Returns:
            dict: 包含停止结果的响应数据，成功时返回 {"result": "success"}
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        url = f"{self.base_url}/chat-messages/{task_id}/stop"
        
        payload = {
            "user": user_id
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"停止响应失败: {response.text}")
