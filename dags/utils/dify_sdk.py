#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# 第三方库导入
import requests
from airflow.models import Variable
import json
import os


class DifyAgent:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def create_chat_message(self, query, user_id, conversation_id="", inputs=None, files=None):
        """
        创建聊天消息
        """
        if inputs is None:
            inputs = {}

        if files is None:
            files = []

        url = f"{self.base_url}/chat-messages"
        payload = {
            "inputs": inputs,
            "query": query,
            "response_mode": "blocking",  # 改为非流式响应
            "conversation_id": conversation_id,
            "user": user_id,
            "auto_generate_name": False,
            "files": files
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
            print(f"获取会话列表成功: {response.json()}")  
            print("="*50)
            print(f"response.json(): {response.json()}")
            print("="*50)
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
            print(f"{user_id} 没有找到会话ID")
        return ""

    def get_conversation_id_for_user(self, user_id):
        """
        根据用户ID获取对应的会话ID，主要用于微信公众号等一对一对话场景
        
        Args:
            user_id (str): 用户标识（如微信公众号的OpenID）
            
        Returns:
            str: 会话ID。如果找不到有效会话则返回空字符串
            
        说明:
            1. 先从缓存中获取会话ID
            2. 如果缓存中有会话ID,则检查该会话是否仍然有效
            3. 如果会话无效或不存在,则返回空字符串,由调用方创建新会话
        """
        conversation_infos = Variable.get("wechat_mp_conversation_infos", default_var={}, deserialize_json=True)
        
        # 检查是否存在会话ID
        conversation_id = conversation_infos.get(user_id)
        if conversation_id:
            print(f"用户 {user_id} 使用已存在的会话ID: {conversation_id}")
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
                print(f"用户 {user_id} 的会话 {conversation_id} 不存在或状态异常")
                return ""
            else:
                print(f"用户 {user_id} 使用已存在的会话ID: {conversation_id}")
                return conversation_id
        else:
            print(f"用户 {user_id} 没有找到会话ID")
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
            # 如果name为空，则使用用户ID作为会话名称
            payload["name"] = user_id
        
        print(f"重命名会话, url: {url}, payload: {payload}")
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

    def create_chat_message_stream(self, query, user_id, conversation_id="", inputs=None, files=None):
        """
        创建聊天消息并以流式方式返回结果
        
        Args:
            query (str): 用户输入内容
            user_id (str): 用户标识
            conversation_id (str, optional): 会话ID
            inputs (dict, optional): 输入参数
            files (list, optional): 文件列表
        Returns:
            tuple: (完整回答文本, 元数据字典)
                - 完整回答文本: AI助手的完整回答内容
                - 元数据字典: 包含message_id, conversation_id, task_id等信息
        """
        if inputs is None:
            inputs = {}

        if files is None:
            files = []

        url = f"{self.base_url}/chat-messages"
        if conversation_id:
            payload = {
                "inputs": inputs,
                "query": query,
                "response_mode": "streaming",  # 使用流式响应
                "conversation_id": conversation_id,
                "user": user_id,
                "auto_generate_name": False,
                "files": files
            }
        else:
            payload = {
                "inputs": inputs,
                "query": query,
                "response_mode": "streaming",  # 使用流式响应
                "user": user_id,
                "auto_generate_name": False,
                "files": files
            }
        print("="*50)
        print(f"payload: {payload}")
        print("="*50)

        full_answer = ""
        metadata = {}
        task_id = None
        workflow_metadata = {}
        
        print(f"创建聊天消息, url: {url}, payload: {payload}")
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

    def audio_to_text(self, audio_file_path):
        """
        将语音文件转换为文字
        
        Args:
            audio_file_path (str): 本地语音文件路径
            
        Returns:
            str: 转换后的文字内容
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        api_url = f"{self.base_url}/audio-to-text"
        
        # 根据文件扩展名确定文件类型
        ext = os.path.splitext(audio_file_path)[1].lower()[1:]  # 去掉点号，获取扩展名
        if ext in ['mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm']:
            mime_type = f'audio/{ext}'
        else:
            # 默认为 wav 格式
            mime_type = 'audio/wav'
        
        print(f"处理语音文件，路径: {audio_file_path}, MIME类型: {mime_type}")
        
        # 准备文件
        with open(audio_file_path, 'rb') as audio_file:
            files = {'file': (os.path.basename(audio_file_path), audio_file, mime_type)}
            
            # 发送请求
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.post(api_url, headers=headers, files=files)
        
        # 处理响应
        if response.status_code == 200:
            result = response.json()
            return result.get('text', '')
        else:
            raise Exception(f"语音转文字失败: [{response.status_code}] {response.text}")

    def text_to_audio(self, text, user_id, save_path):
        """
        将文字转换为语音并保存到指定路径
        
        Args:
            text (str): 要转换的文字内容
            user_id (str): 用户标识
            save_path (str): 保存语音文件的本地路径
            
        Returns:
            str: 保存的语音文件路径
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        api_url = f"{self.base_url}/text-to-audio"
        
        # 准备请求数据
        payload = {
            "text": text,
            "user": user_id
        }
        
        # 发送请求
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        # 使用流式下载，直接保存到文件
        with requests.post(api_url, headers=headers, json=payload, stream=True) as response:
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"文字已转换为语音，保存到: {save_path}")
                return save_path
            else:
                raise Exception(f"文字转语音失败: [{response.status_code}] {response.text}")

    def upload_file(self, file_path, user_id):
        """
        上传文件到 Dify 平台
        
        Args:
            file_path (str): 要上传的本地文件路径
            user_id (str): 用户标识
            
        Returns:
            dict: 包含上传文件信息的响应数据，格式如下：
                {
                    "id": "文件ID",
                    "name": "文件名",
                    "size": 文件大小(字节),
                    "extension": "文件扩展名",
                    "mime_type": "文件MIME类型",
                    "created_by": 创建者ID,
                    "created_at": 创建时间戳
                }
            
        Raises:
            Exception: 当API调用失败时抛出异常
        """
        api_url = f"{self.base_url}/files/upload"
        
        # 获取文件MIME类型
        ext = os.path.splitext(file_path)[1].lower()[1:]  # 去掉点号，获取扩展名
        mime_type = None
        
        # 根据文件扩展名设置MIME类型
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'mp4':'video/mp4'
        }
        mime_type = mime_types.get(ext)
        
        if not mime_type:
            raise ValueError(f"不支持的文件类型: {ext}。仅支持: {', '.join(mime_types.keys())}")
        
        print(f"上传文件，路径: {file_path}, MIME类型: {mime_type}")
        
        # 准备文件和表单数据
        with open(file_path, 'rb') as file:
            files = {
                'file': (os.path.basename(file_path), file, mime_type)
            }
            data = {
                'user': user_id
            }
            
            # 发送请求
            headers = {'Authorization': f'Bearer {self.api_key}'}
            response = requests.post(api_url, headers=headers, files=files, data=data)
        
        # 处理响应
        if response.status_code in [200, 201]:  # 同时接受200和201状态码
            return response.json()
        else:
            raise Exception(f"文件上传失败: [{response.status_code}] {response.text}")
