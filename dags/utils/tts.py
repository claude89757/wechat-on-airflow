#!/usr/bin/env python
# coding=utf-8

import os

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

try:
    from airflow.models.variable import Variable
except ImportError:
    pass


def text_to_speech(text, output_path='output.mp3', model="cosyvoice-v2", voice="longxiaoxia", api_key=None):
    """
    将文本转换为语音并保存为MP3文件
    
    参数:
        text (str): 要转换为语音的文本
        output_path (str): 输出音频文件的路径，默认为'output.mp3'
        model (str): 使用的模型，默认为'cosyvoice-v2'
        voice (str): 使用的声音，默认为'longxiaoxia'
        api_key (str, optional): DashScope API密钥，如果为None则使用环境变量中的配置
        
    返回:
        tuple: (成功标志, 音频数据或错误消息)
    """
    try:
        # 如果提供了API密钥，则设置它
        if api_key:
            dashscope.api_key = api_key
        else:
            dashscope.api_key = Variable.get("DASH_SCOPE_API_KEY")
        
        # 初始化语音合成器
        synthesizer = SpeechSynthesizer(model=model, voice=voice)
        
        # 调用API生成语音
        audio = synthesizer.call(text)
        
        # 获取请求ID和延迟指标
        request_id = synthesizer.get_last_request_id()
        first_package_delay = synthesizer.get_first_package_delay()
        
        # 记录指标
        print(f'[Metric] requestId: {request_id}, first package delay ms: {first_package_delay}')
        
        # 保存音频文件
        with open(output_path, 'wb') as f:
            f.write(audio)
        
        return True, audio
    
    except Exception as e:
        error_msg = f"语音生成失败: {str(e)}"
        print(error_msg)
        return False, error_msg

if __name__ == "__main__":
    # 测试函数
    success, result = text_to_speech("今天天气怎么样？")
    if success:
        print(f"语音生成成功，文件已保存至 output.mp3")
    else:
        print(result)
