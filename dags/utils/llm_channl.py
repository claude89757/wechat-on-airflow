#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from anthropic import Anthropic
from openai import OpenAI
from airflow.models import Variable
from contextlib import contextmanager

# LLM模型参数配置
LLM_CONFIG = {
    "temperature": 0.7,      # 提高温度使回复更自然活泼
    "max_tokens": 1200,      # 增加长度以支持更详细的回复
    "presence_penalty": 0.6, # 增加新话题的倾向
    "frequency_penalty": 0.2 # 降低重复内容
}

@contextmanager
def proxy_context():
    """
    代理设置的上下文管理器
    """
    # 保存原始代理设置
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    
    try:
        # 设置新代理
        proxy_url = Variable.get("PROXY_URL", default_var="")
        if proxy_url:
            os.environ['HTTPS_PROXY'] = proxy_url
            os.environ['HTTP_PROXY'] = proxy_url
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
        yield
    finally:
        # 恢复原始代理
        if original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            
        if original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
        else:
            os.environ.pop('HTTPS_PROXY', None)

def get_llm_response(user_question: str, model_name: str = None, system_prompt: str = None, chat_history: list = None) -> str:
    """
    调用AI API进行对话

    Args:
        user_question: 用户输入的问题
        model_name: 使用的模型名称,支持GPT和Claude系列
        system_prompt: 系统提示词
        chat_history: 历史对话记录
        
    Returns:
        str: AI的回复内容
    """
    try:
        if not model_name:
            model_name = Variable.get("model_name", default_var="gpt-4o-mini")
        if not system_prompt:
            system_prompt = Variable.get("system_prompt", default_var="你是一个友好的AI助手，请用简短的中文回答问题。")
        
        print(f"[AI] 使用模型: {model_name}")
        print(f"[AI] 系统提示: {system_prompt}")
        print(f"[AI] 问题: {user_question}")

        # 创建消息列表
        messages = chat_history or []
        # 添加当前用户问题
        messages.append({"role": "user", "content": user_question})

        print("[AI] 输入消息:")
        print("="*100)
        for msg in messages:
            print(msg)
        print("="*100)

        with proxy_context():
            if model_name.startswith("gpt-"):
                api_key = Variable.get("OPENAI_API_KEY")
                os.environ['OPENAI_API_KEY'] = api_key
                
                client = OpenAI()
                response = client.chat.completions.create(model=model_name, system=system_prompt, messages=messages, **LLM_CONFIG)
                ai_response = response.choices[0].message.content.strip()
                
            elif model_name.startswith("claude-"):            
                api_key = Variable.get("CLAUDE_API_KEY")
                client = Anthropic(api_key=api_key)
                
                # 剔除模型不支持的参数
                LLM_CONFIG.pop("presence_penalty", None)
                LLM_CONFIG.pop("frequency_penalty", None)

                response = client.messages.create(model=model_name, messages=messages, system=system_prompt, **LLM_CONFIG)
                ai_response = response.content[0].text
                
            else:
                raise ValueError(f"不支持的模型: {model_name}")
        
        print(f"[AI] 回复: {ai_response}")
        return ai_response
        
    except Exception as e:
        error_msg = f"API调用失败: {str(e)}"
        print(f"[AI] {error_msg}")
        raise Exception(error_msg)
