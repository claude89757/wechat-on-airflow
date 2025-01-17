#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from anthropic import Anthropic
from openai import OpenAI
from airflow.models import Variable


def get_llm_response(user_question: str, model_name: str = None, system_prompt: str = None) -> str:
    """
    调用AI API进行对话
    
    Args:
        user_question: 用户输入的问题
        model_name: 使用的模型名称,支持GPT和Claude系列
        system_prompt: 系统提示词
        
    Returns:
        str: AI的回复内容
    """
    # 保存原始代理
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    
    try:
        if not model_name:
            model_name = Variable.get("model_name", default_var="gpt-4o-mini")
        if not system_prompt:
            system_prompt = Variable.get("system_prompt", default_var="你是一个友好的AI助手，请用简短的中文回答问题。")
        
        print(f"[AI] 使用模型: {model_name}")
        print(f"[AI] 系统提示: {system_prompt}")
        print(f"[AI] 问题: {user_question}")
    
        # 设置代理
        proxy_url = Variable.get("PROXY_URL", default_var="")
        if proxy_url:
            os.environ['HTTPS_PROXY'] = proxy_url
            os.environ['HTTP_PROXY'] = proxy_url
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)

        if model_name.startswith("gpt-"):
            api_key = Variable.get("OPENAI_API_KEY")
            os.environ['OPENAI_API_KEY'] = api_key
            
            client = OpenAI()
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_question}
                ],
                temperature=0.5,
                max_tokens=500,
                top_p=0.8,
                frequency_penalty=0.3,
                presence_penalty=0.3
            )
            ai_response = response.choices[0].message.content.strip()
            
        elif model_name.startswith("claude-"):            
            api_key = Variable.get("CLAUDE_API_KEY")
            client = Anthropic(api_key=api_key)
            
            response = client.messages.create(
                model=model_name,
                max_tokens=500,
                temperature=0.5,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_question}
                ]
            )
            ai_response = response.content[0].text
            
        else:
            raise ValueError(f"不支持的模型: {model_name}")
        
        print(f"[AI] 回复: {ai_response}")
        return ai_response
        
    except Exception as e:
        error_msg = f"API调用失败: {str(e)}"
        print(f"[AI] {error_msg}")
        raise Exception(error_msg)
    finally:
        # 恢复代理
        if original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            
        if original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
        else:
            os.environ.pop('HTTPS_PROXY', None)
