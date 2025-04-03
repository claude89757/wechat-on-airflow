#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import requests
from typing import List, Dict, Any, Optional


class OpenRouter:
    """
    OpenRouter API客户端
    OpenRouter是一个API聚合器，支持多种AI模型，包括OpenAI、Anthropic等
    """
    
    BASE_URL = "https://openrouter.ai/api/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化OpenRouter客户端
        
        Args:
            api_key: OpenRouter API密钥，如果为None则从Airflow变量中获取
        """
        self.api_key = api_key

        self.default_config = {
            "temperature": 0.7,
            "max_tokens": 1200,
            "top_p": 0.9,
            "stream": False
        }
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "openai/gpt-3.5-turbo",
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        创建聊天完成请求
        
        Args:
            messages: 消息列表，格式为[{"role": "user", "content": "..."}, ...]
            model: 要使用的模型ID，例如"openai/gpt-3.5-turbo"或"anthropic/claude-3-opus"
            system_prompt: 系统提示，如果提供则添加到消息列表的开头
            **kwargs: 其他参数传递给API
            
        Returns:
            API响应字典
        """
        if system_prompt and not any(msg.get("role") == "system" for msg in messages):
            messages.insert(0, {"role": "system", "content": system_prompt})
        
        # 合并默认配置和用户提供的参数
        params = {**self.default_config, **kwargs}
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://your-app-or-website.com",  # 应替换为实际网站
            "X-Title": "WeChat on Airflow"  # 应用标题
        }
        
        data = {
            "model": model,
            "messages": messages,
            **params
        }
        
        print(f"[OpenRouter] 请求模型: {model}")
        print(f"[OpenRouter] 请求参数: {json.dumps(params, ensure_ascii=False)}")
        
        try:
            response = requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=headers,
                json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[OpenRouter] 请求失败: {str(e)}")
            if hasattr(response, 'text'):
                print(f"[OpenRouter] 响应内容: {response.text}")
            raise
    
    def get_models(self) -> List[Dict[str, Any]]:
        """
        获取可用模型列表
        
        Returns:
            可用模型列表
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/models",
                headers=headers
            )
            response.raise_for_status()
            return response.json().get("data", [])
        except Exception as e:
            print(f"[OpenRouter] 获取模型列表失败: {str(e)}")
            raise

    def extract_text_response(self, response: Dict[str, Any]) -> str:
        """
        从API响应中提取文本内容
        
        Args:
            response: API响应字典
            
        Returns:
            响应文本内容
        """
        try:
            return response.get("choices", [{}])[0].get("message", {}).get("content", "")
        except (IndexError, KeyError, AttributeError):
            print("[OpenRouter] 无法从响应中提取文本")
            return ""


# 测试示例
def test_openrouter():
    """
    OpenRouter API基础测试示例
    """
    # 初始化客户端
    client = OpenRouter(api_key="xxx")
    
    # 测试1: 简单聊天完成
    print("\n=== 测试1: 简单聊天完成 ===")
    response = client.chat_completion(
        messages=[{"role": "user", "content": "你好，请介绍一下自己"}],
        model="openai/gpt-3.5-turbo"
    )
    print(f"响应: {client.extract_text_response(response)}")
    
    # 测试2: 使用系统提示
    print("\n=== 测试2: 使用系统提示 ===")
    response = client.chat_completion(
        messages=[{"role": "user", "content": "给我讲个笑话"}],
        model="anthropic/claude-3-haiku",
        system_prompt="你是一个幽默的AI助手，专注于讲笑话"
    )
    print(f"响应: {client.extract_text_response(response)}")
    
    # 测试3: 多轮对话
    print("\n=== 测试3: 多轮对话 ===")
    response = client.chat_completion(
        messages=[
            {"role": "user", "content": "中国的首都是哪里？"},
            {"role": "assistant", "content": "中国的首都是北京。"},
            {"role": "user", "content": "它有什么著名的景点？"}
        ],
        model="openai/gpt-4o"
    )
    print(f"响应: {client.extract_text_response(response)}")
    
    # 测试4: 获取可用模型
    print("\n=== 测试4: 获取可用模型 ===")
    models = client.get_models()
    print(f"可用模型数量: {len(models)}")
    for i, model in enumerate(models[:5]):  # 只打印前5个模型
        print(f"模型 {i+1}: {model.get('id')} - {model.get('name')}")


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    test_openrouter()
