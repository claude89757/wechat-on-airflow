#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信自动化操作SDK
提供基于Appium的微信自动化操作功能,包括:
- 进入聊天窗口
- 发送消息
- 滚动页面等基础操作

Author: claude89757
Date: 2025-01-09
"""

import os
import time
import subprocess
import datetime

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from xml.etree import ElementTree


FLICK_START_X = 300
FLICK_START_Y = 300
FLICK_DISTANCE = 700
SCROLL_SLEEP_TIME = 1


def is_video_time_less_than_x_seconds(time_text: str, max_seconds: int = 15) -> bool:
    """
    判断视频时间长度是否小于30秒
    :param time_text: 视频时间文本，格式为 "MM:SS"
    :return: 如果视频时间小于30秒，返回True；否则返回False
    """
    try:
        minutes, seconds = map(int, time_text.split(':'))
        total_seconds = minutes * 60 + seconds
        return total_seconds < max_seconds
    except ValueError:
        print("Invalid time format")
        return False
    

class WXAppOperator:
    def __init__(self, appium_server_url: str = 'http://localhost:4723',  force_app_launch: bool = False):
        """
        初始化
        """
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            deviceName='BH901V3R9E',
            appPackage='com.tencent.mm',  # 微信的包名
            appActivity='.ui.LauncherUI',  # 微信的启动活动
            noReset=True,  # 不重置应用的状态
            fullReset=False,  # 不完全重置应用
            forceAppLaunch=force_app_launch  # 强制重新启动应用
        )

        print('Loading driver...')
        driver = webdriver.Remote(appium_server_url, options=UiAutomator2Options().load_capabilities(capabilities))
        self.driver = driver
        print('Driver loaded successfully.')


    def enter_chat_page(self, chat_name: str):
        """
        进入聊天窗口
        :return:
        """
        # 使用显式完全加载
        WebDriverWait(self.driver, 60). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH, '//*[@text="微信"]')))

        WebDriverWait(self.driver, 60). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH,
                                                                   f'//*[@text="{chat_name}"]'))).click()

        print(f"enter chat ui of {chat_name} successfully")


    def find_video_element(self):
        """
        查找当前界面是否有触发指令消息文本或消息类型
        :return:
        """
        try:
            # 等待至少有一个指定ID的元素出现
            video_elements = WebDriverWait(self.driver, 5).until(
                expected_conditions.presence_of_all_elements_located((AppiumBy.ID, 'com.tencent.mm:id/boy'))
            )
            return video_elements[-1]
        except Exception as error:
            print(error)
            return None


    def save_video(self, element):
        """
        保存视频到本地
        :return:
        """
        video_time_text = element.text
        max_seconds = 60
        if is_video_time_less_than_x_seconds(video_time_text, max_seconds=max_seconds):
            element.click()
            time.sleep(1)
            WebDriverWait(self.driver, 60).until(
                expected_conditions.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, '更多信息'))).click()

            WebDriverWait(self.driver, 60). \
                until(expected_conditions.presence_of_element_located((AppiumBy.XPATH,
                                                                       f'//*[@text="保存视频"]'))).click()
            # 获取当前页面的 XML 结构
            page_source = self.driver.page_source
            # 解析 XML
            tree = ElementTree.fromstring(page_source)
            # 查找所有元素
            all_elements = tree.findall(".//*")
            print("Clickable elements on the current page:")
            for elem in all_elements:
                text = elem.attrib.get('text', 'N/A')
                if "视频已保存至" in text:
                    WebDriverWait(self.driver, 60).until(
                        expected_conditions.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, '关闭'))).click()
                    return text.strip("视频已保存至")
                else:
                    pass
            raise Exception(f"视频不见了？")
        else:
            print("The video time is not less than 30 seconds.")
            raise Exception(f"视频时长超过{max_seconds}秒, 太长了")


    def send_text_msg(self, msg: str):
        """
        输入文字消息并发送
        :param msg:
        :return:
        """
        input_box = WebDriverWait(self.driver, 60).until(
            expected_conditions.presence_of_element_located((AppiumBy.ID, 'com.tencent.mm:id/bkk')))
        input_box.click()
        input_box.send_keys(msg)
        WebDriverWait(self.driver, 60). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="发送"]'))).click()


    def send_first_image_msg(self):
        """
        发送相册中的一张图片
        :return:
        """
        WebDriverWait(self.driver, 60).until(
            expected_conditions.presence_of_element_located((AppiumBy.ID, 'com.tencent.mm:id/bjz'))).click()

        WebDriverWait(self.driver, 60). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="相册"]'))).click()

        WebDriverWait(self.driver, 10).until(
            expected_conditions.presence_of_element_located((AppiumBy.ID, 'com.tencent.mm:id/jdh'))).click()

        WebDriverWait(self.driver, 30). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="发送(1)"]'))).click()


    def print_clickable_elements(self):
        # 获取当前页面的 XML 结构
        page_source = self.driver.page_source
        # 解析 XML
        tree = ElementTree.fromstring(page_source)
        # 查找所有元素
        all_elements = tree.findall(".//*")
        print("Clickable elements on the current page:")
        for elem in all_elements:
            clickable = elem.attrib.get('clickable', 'false')
            resource_id = elem.attrib.get('resource-id', 'N/A')
            text = elem.attrib.get('text', 'N/A')
            class_name = elem.attrib.get('class', 'N/A')
            content_desc = elem.attrib.get('content-desc', 'N/A')
            bounds = elem.attrib.get('bounds', 'N/A')
            focusable = elem.attrib.get('focusable', 'N/A')
            enabled = elem.attrib.get('enabled', 'N/A')
            if clickable == 'true':
                print(f"**Resource ID: {resource_id}, Text: {text}, Class: {class_name}, Content-desc: {content_desc}, "
                      f"Bounds: {bounds}, Clickable: {clickable}, Focusable: {focusable}, Enabled: {enabled}")
            else:
                print(f"Resource ID: {resource_id}, Text: {text}, Class: {class_name}, Content-desc: {content_desc}, "
                      f"Bounds: {bounds}, Clickable: {clickable}, Focusable: {focusable}, Enabled: {enabled}")
              
               
    def print_current_page_source(self):
        """
        打印当前页面的XML结构
        :return:
        """
        page_source = self.driver.page_source
        print(page_source)

    
    def get_current_chat_list(self):
        """
        获取当前微信聊天列表
        :return: 聊天列表，包含每个聊天的名称、最后消息、时间和未读状态
        """
        page_source = self.driver.page_source
        tree = ElementTree.fromstring(page_source)
        
        def find_chat_items():
            items = tree.findall(".//android.widget.ListView//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/cj0']")
            if items:
                return items
            return []
        
        seen_names = set()  # 用于去重
        chat_items = []
        for chat in find_chat_items():
            try:
                views = chat.findall(".//android.view.View")
                
                chat_name_text = ''
                last_msg_text = ''
                time_text = ''
                
                # 检查是否有未读消息标记
                unread_count = 0
                # 查找头像区域内的TextView，通常未读消息数显示在头像右上角
                avatar_area = chat.find(".//android.widget.RelativeLayout")
                if avatar_area is not None:
                    # 查找所有TextView，筛选出数字内容的
                    for text_view in avatar_area.findall(".//android.widget.TextView"):
                        text = text_view.attrib.get('text', '')
                        # 检查是否是纯数字且位置在头像区域的上半部分
                        if text.isdigit():
                            bounds = text_view.attrib.get('bounds', '')
                            if bounds:  # bounds格式类似 "[93,148][125,180]"
                                try:
                                    # 解析bounds坐标
                                    coords = bounds.strip('[]').split('][')
                                    top_left = coords[0].split(',')
                                    bottom_right = coords[1].split(',')
                                    y_pos = int(top_left[1])
                                    
                                    # 检查y坐标是否在头像区域上半部分
                                    avatar_bounds = avatar_area.attrib.get('bounds', '')
                                    if avatar_bounds:
                                        avatar_coords = avatar_bounds.strip('[]').split('][')
                                        avatar_top = int(avatar_coords[0].split(',')[1])
                                        avatar_bottom = int(avatar_coords[1].split(',')[1])
                                        avatar_middle = (avatar_top + avatar_bottom) / 2
                                        
                                        if y_pos < avatar_middle:  # 在头像上半部分
                                            unread_count = int(text)
                                            break
                                except (ValueError, IndexError):
                                    continue
                
                for view in views:
                    text = view.attrib.get('text', '')
                    if not text:
                        continue
                        
                    if (':' in text or '-' in text) and len(text) <= 16:
                        time_text = text
                    elif '】' in text or len(text) > 20:
                        last_msg_text = text
                    elif not chat_name_text and len(text) < 30:
                        chat_name_text = text

                if chat_name_text and chat_name_text not in seen_names:
                    seen_names.add(chat_name_text)
                    
                    chat_items.append({
                        'name': chat_name_text,
                        'last_message': last_msg_text,
                        'time': time_text,
                        'unread_count': unread_count,
                        'element': chat
                    })
                    
            except Exception as e:
                print(f"处理聊天项时出错: {str(e)}")
                continue
            
        return chat_items


    def return_to_home_page(self):
        """
        返回微信聊天首页
        可以通过多种方式尝试：
        1. 点击底部的"微信" tab
        2. 点击返回按钮直到回到首页
        3. 使用Android返回键

        :raises: RuntimeError 当所有返回方式都失败时
        """
        def is_at_home_page():
            """检查是否在微信首页"""
            try:
                # 检查首页特有元素是否存在
                elements = [
                    ('//android.widget.TextView[@resource-id="android:id/text1" and contains(@text, "微信")]'),
                    ('//android.widget.RelativeLayout[@content-desc="搜索"]'),
                    ('//android.widget.RelativeLayout[@content-desc="更多功能按钮"]'),
                    ('//android.widget.ListView')
                ]
                
                for xpath in elements:
                    self.driver.find_element(AppiumBy.XPATH, xpath)
                return True
            except Exception:
                return False

        errors = []
  
        # 方式：循环点击返回按钮
        try:
            max_attempts = 5  # 最大尝试次数
            attempts = 0
            
            while attempts < max_attempts:
                if is_at_home_page():
                    print("已返回微信首页")
                    return
                    
                # 点击返回按钮
                back_button = WebDriverWait(self.driver, 5).until(
                    expected_conditions.presence_of_element_located(
                        (AppiumBy.ID, 'com.tencent.mm:id/actionbar_up_indicator')
                    )
                )
                back_button.click()
                attempts += 1
                time.sleep(0.5)  # 短暂等待页面加载
                
            errors.append(f"点击返回按钮{max_attempts}次后仍未能返回首页")
            
        except Exception as e:
            errors.append(f"通过点击返回按钮返回首页失败: {str(e)}")
        
        # 方式2：尝试点击底部的"微信" tab
        try:
            if is_at_home_page():
                print("当前已在微信首页")
                return
            
            tab = WebDriverWait(self.driver, 5).until(
                expected_conditions.presence_of_element_located(
                    (AppiumBy.XPATH, '//android.widget.TextView[@text="微信"]')
                )
            )
            tab.click()
            time.sleep(0.5)  # 等待点击生效
            
            if is_at_home_page():
                print("已通过点击微信tab返回首页")
                return
            errors.append("点击微信tab后未能返回首页")
        except Exception as e:
            errors.append(f"通过点击微信tab返回首页失败: {str(e)}")

        # 方式3：尝试使用Android返回键
        try:
            self.driver.press_keycode(4)  # Android返回键的keycode
            time.sleep(1)  # 等待返回操作完成
            
            if is_at_home_page():
                print("已通过Android返回键返回首页")
                return
            errors.append("使用Android返回键后未能返回到首页")
        except Exception as e:
            errors.append(f"使用Android返回键失败: {str(e)}")
        
        # 所有方式都失败时，抛出异常
        error_message = "\n".join(errors)
        raise RuntimeError(f"返回微信首页失败，尝试了以下方法但均未成功：\n{error_message}")
    

    def get_chat_msg_list(self):
        """
        获取当前聊天窗口的消息列表
        :return: 消息列表，每条消息包含：
            - type: 消息类型（text/image/video/voice/system等）
            - sender: 发送者名称
            - content: 消息内容
            - time: 消息时间（如果显示）
        """
        try:            
            page_source = self.driver.page_source
            tree = ElementTree.fromstring(page_source)
            messages = []
            
            # 找到消息列表容器 (RecyclerView)
            msg_container = tree.find(".//androidx.recyclerview.widget.RecyclerView")
            if msg_container is None:
                return []
            
            # 遍历消息项
            for msg_item in msg_container.findall("./android.widget.RelativeLayout"):
                try:
                    msg_data = {
                        'type': 'unknown',
                        'sender': '',
                        'content': '',
                        'time': ''
                    }
                    
                    # 获取时间信息（通常是单独的TextView，内容格式为 HH:mm）
                    for text_view in msg_item.findall(".//android.widget.TextView"):
                        text = text_view.attrib.get('text', '').strip()
                        if ':' in text and len(text) <= 5:  # 时间格式 HH:mm
                            msg_data['time'] = text
                            break
                    
                    # 获取消息内容区域（通常包含头像和内容的LinearLayout）
                    msg_content = msg_item.find(".//android.widget.LinearLayout")
                    if msg_content is not None:
                        # 获取发送者信息（通常是第一个TextView）
                        text_views = msg_content.findall(".//android.widget.TextView")
                        if text_views:
                            msg_data['sender'] = text_views[0].attrib.get('text', '')
                        
                        # 检查消息类型和内容
                        # 文本消息（通常是最后一个TextView）
                        if len(text_views) > 1:
                            content_text = text_views[-1].attrib.get('text', '')
                            if content_text and content_text != msg_data['sender']:
                                msg_data['type'] = 'text'
                                msg_data['content'] = content_text
                        
                        # 图片消息
                        image_views = msg_content.findall(".//android.widget.ImageView")
                        for image in image_views:
                            if image.attrib.get('content-desc', '') == '图片':
                                msg_data['type'] = 'image'
                                msg_data['content'] = '[图片]'
                                break
                        
                        # 视频消息（通常包含视频缩略图和时长）
                        video_frame = msg_content.find(".//android.widget.FrameLayout")
                        if video_frame is not None and video_frame.find(".//android.widget.TextView") is not None:
                            duration = video_frame.find(".//android.widget.TextView").attrib.get('text', '')
                            if ':' in duration and len(duration) <= 5:  # 视频时长格式
                                msg_data['type'] = 'video'
                                msg_data['content'] = f'[视频] {duration}'
                        
                        # 语音消息（通常显示秒数）
                        for text_view in text_views:
                            text = text_view.attrib.get('text', '')
                            if text.endswith('"') and text[:-1].isdigit():  # 语音时长格式
                                msg_data['type'] = 'voice'
                                msg_data['content'] = f'[语音] {text}'
                                break
                    
                    # 只添加有效的消息
                    if msg_data['content'] or msg_data['time']:
                        messages.append(msg_data)
                    
                except Exception as e:
                    print(f"处理单条消息时出错: {str(e)}")
                    continue
            
            return messages
            
        except Exception as e:
            print(f"获取聊天消息列表失败: {str(e)}")
            return []


    def close(self):
        self.driver.quit()
        print('Driver closed.')


# 测试代码
if __name__ == "__main__":
    appium_server_url = os.getenv('ZACKS_APPIUM_SERVER_URL', 'http://localhost:4723')
    wx_app_operator = WXAppOperator(appium_server_url=appium_server_url)

    # 先返回微信首页
    wx_app_operator.return_to_home_page()

    # 先进入聊天页面
    wx_app_operator.enter_chat_page("无限技术群")
    time.sleep(2)  # 等待页面完全加载
    
    # 获取并打印消息列表
    msg_list = wx_app_operator.get_chat_msg_list()
    for msg in msg_list:
        print(msg)

    wx_app_operator.close()
