#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息处理模块集合
"""

from wx_dags.handlers.handler_text_msg import handler_text_msg
from wx_dags.handlers.handler_image_msg import handler_image_msg
from wx_dags.handlers.handler_voice_msg import handler_voice_msg

__all__ = [
    'handler_text_msg',
    'handler_image_msg',
    'handler_voice_msg',
]
