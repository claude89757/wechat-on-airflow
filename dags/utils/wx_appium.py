#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信自动化操作SDK
提供基于Appium的微信自动化操作功能,包括:
- 发送消息
- 获取聊天记录
- 群操作等

Author: claude89757
Date: 2025-01-09
"""
import os
import json
import time

from appium.webdriver.webdriver import WebDriver as AppiumWebDriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.android import UiAutomator2Options
from xml.etree import ElementTree


class WeChatOperator:
    def __init__(self, appium_server_url: str = 'http://localhost:4723', force_app_launch: bool = False):
        """
        初始化微信操作器
        """
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            deviceName='BH901V3R9E',
            appPackage='com.tencent.mm',  # 微信的包名
            appActivity='.ui.LauncherUI',  # 微信的启动活动
            noReset=True,  # 保留应用数据
            fullReset=False,  # 不完全重置
            forceAppLaunch=force_app_launch,  # 是否强制重启应用
            autoGrantPermissions=True,  # 自动授予权限
            newCommandTimeout=60,  # 命令超时时间
            unicodeKeyboard=True,  # 使用 Unicode 输入法
            resetKeyboard=True,  # 重置输入法
        )

        print('正在初始化微信控制器...')
        self.driver: AppiumWebDriver = AppiumWebDriver(
            command_executor=appium_server_url,
            options=UiAutomator2Options().load_capabilities(capabilities)
        )
        print('控制器初始化完成。')

    def send_message(self, contact_name: str, message: str):
        """
        发送消息给指定联系人
        Args:
            contact_name: 联系人名称
            message: 要发送的消息
        """
        try:
            # 点击搜索按钮
            search_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.tencent.mm:id/j3x"))
            )
            search_btn.click()
            
            # 输入联系人名称
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.tencent.mm:id/cd7"))
            )
            search_input.send_keys(contact_name)
            
            # 点击联系人
            contact = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    AppiumBy.XPATH,
                    f"//android.widget.TextView[@text='{contact_name}']"
                ))
            )
            contact.click()
            
            # 输入消息
            message_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.tencent.mm:id/b4a"))
            )
            message_input.send_keys(message)
            
            # 点击发送按钮
            send_btn = self.driver.find_element(
                by=AppiumBy.ID,
                value="com.tencent.mm:id/b4h"
            )
            send_btn.click()
            
            print(f"消息已发送给 {contact_name}")
            
        except Exception as e:
            print(f"发送消息失败: {str(e)}")
            raise

    def get_chat_history(self, contact_name: str, max_messages: int = 20):
        """
        获取与指定联系人的聊天记录
        Args:
            contact_name: 联系人名称
            max_messages: 最大获取消息数
        Returns:
            list: 消息列表
        """
        messages = []
        try:
            # 进入聊天界面
            self.enter_chat(contact_name)
            
            # 循环获取消息
            while len(messages) < max_messages:
                # 获取可见的消息元素
                message_elements = self.driver.find_elements(
                    by=AppiumBy.ID,
                    value="com.tencent.mm:id/b4c"  # 消息内容的ID
                )
                
                for msg_elem in message_elements:
                    try:
                        # 获取消息内容
                        content = msg_elem.text
                        if content and content not in messages:
                            messages.append(content)
                            print(f"获取到消息: {content}")
                            
                            if len(messages) >= max_messages:
                                break
                    except:
                        continue
                
                if len(messages) >= max_messages:
                    break
                    
                # 向上滑动加载更多消息
                self.scroll_up()
                time.sleep(0.5)
            
            return messages
            
        except Exception as e:
            print(f"获取聊天记录失败: {str(e)}")
            raise

    def enter_chat(self, contact_name: str):
        """
        进入指定联系人的聊天界面
        """
        try:
            # 点击搜索按钮
            search_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.tencent.mm:id/j3x"))
            )
            search_btn.click()
            
            # 输入联系人名称
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, "com.tencent.mm:id/cd7"))
            )
            search_input.send_keys(contact_name)
            
            # 点击联系人
            contact = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    AppiumBy.XPATH,
                    f"//android.widget.TextView[@text='{contact_name}']"
                ))
            )
            contact.click()
            
            print(f"已进入与 {contact_name} 的聊天界面")
            
        except Exception as e:
            print(f"进入聊天界面失败: {str(e)}")
            raise

    def scroll_up(self):
        """
        向上滑动页面
        """
        try:
            screen_size = self.driver.get_window_size()
            start_x = screen_size['width'] * 0.5
            start_y = screen_size['height'] * 0.2
            end_y = screen_size['height'] * 0.8
            
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            time.sleep(0.5)
        except Exception as e:
            print(f"页面滑动失败: {str(e)}")
            raise

    def scroll_down(self):
        """
        向下滑动页面
        """
        try:
            screen_size = self.driver.get_window_size()
            start_x = screen_size['width'] * 0.5
            start_y = screen_size['height'] * 0.8
            end_y = screen_size['height'] * 0.2
            
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            time.sleep(0.5)
        except Exception as e:
            print(f"页面滑动失败: {str(e)}")
            raise

    def return_to_chats(self):
        """
        返回微信主界面
        """
        try:
            # 尝试点击返回按钮直到回到主界面
            max_attempts = 5
            for _ in range(max_attempts):
                try:
                    back_btn = self.driver.find_element(
                        by=AppiumBy.ID,
                        value="com.tencent.mm:id/g"  # 返回按钮ID
                    )
                    back_btn.click()
                    time.sleep(0.5)
                    
                    if self.is_at_main_page():
                        print("已返回主界面")
                        return
                except:
                    break
            
            # 如果还没回到主界面，使用Android返回键
            self.driver.press_keycode(4)
            time.sleep(0.5)
            
            if not self.is_at_main_page():
                raise Exception("无法返回主界面")
            
        except Exception as e:
            print(f"返回主界面失败: {str(e)}")
            raise

    def is_at_main_page(self):
        """
        检查是否在微信主界面
        """
        try:
            # 检查主界面特有元素
            elements = [
                "//android.widget.TextView[@text='微信']",
                "//android.widget.TextView[@text='通讯录']",
                "//android.widget.TextView[@text='发现']",
                "//android.widget.TextView[@text='我']"
            ]
            
            for xpath in elements:
                self.driver.find_element(AppiumBy.XPATH, xpath)
            return True
        except:
            return False

    def print_current_page_source(self):
        """
        打印当前页面的XML结构，用于调试
        """
        print(self.driver.page_source)

    def print_all_elements(self, element_type: str = 'all'):
        """
        打印当前页面所有元素的属性和值,使用XML解析优化性能
        """
        # 一次性获取页面源码
        page_source = self.driver.page_source
        root = ElementTree.fromstring(page_source)
        
        print("\n页面元素列表:")
        print("-" * 120)
        print("序号 | 文本内容 | 类名 | 资源ID | 描述 | 可点击 | 可用 | 已选中 | 坐标 | 包名")
        print("-" * 120)
        
        for i, element in enumerate(root.findall(".//*"), 1):
            try:
                # 从XML属性中直接获取值，避免多次网络请求
                attrs = element.attrib
                text = attrs.get('text', '无')
                class_name = attrs.get('class', '无')
                resource_id = attrs.get('resource-id', '无')
                content_desc = attrs.get('content-desc', '无')
                clickable = attrs.get('clickable', '否')
                enabled = attrs.get('enabled', '否')
                selected = attrs.get('selected', '否')
                bounds = attrs.get('bounds', '无')
                package = attrs.get('package', '无')
                
                if element_type == 'note' and '笔记' in content_desc:
                    print(f"{i:3d} | {text[:20]:20s} | {class_name:30s} | {resource_id:30s} | {content_desc:20s} | "
                          f"{clickable:4s} | {enabled:4s} | {selected:4s} | {bounds:15s} | {package}")
                elif element_type == 'video' and '视频' in content_desc:
                    print(f"{i:3d} | {text[:20]:20s} | {class_name:30s} | {resource_id:30s} | {content_desc:20s} | "
                          f"{clickable:4s} | {enabled:4s} | {selected:4s} | {bounds:15s} | {package}")
                elif element_type == 'all':
                    print(f"{i:3d} | {text[:20]:20s} | {class_name:30s} | {resource_id:30s} | {content_desc:20s} | "
                          f"{clickable:4s} | {enabled:4s} | {selected:4s} | {bounds:15s} | {package}")
                elif element_type == 'text' and text != '':
                    print(f"{i:3d} | {text[:20]:20s} | {class_name:30s} | {resource_id:30s} | {content_desc:20s} | "
                          f"{clickable:4s} | {enabled:4s} | {selected:4s} | {bounds:15s} | {package}")
                else:
                    raise Exception(f"元素类型错误: {element_type}")
                
            except Exception as e:
                continue
                
        print("-" * 120)

    def close(self):
        """
        关闭微信操作器
        """
        if self.driver:
            self.driver.quit()
            print('控制器已关闭。')


# 测试代码
if __name__ == "__main__":
    # 加载.env文件
    from dotenv import load_dotenv
    import os

    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 加载.env文件
    load_dotenv(os.path.join(current_dir, '.env'))
    
    # 获取Appium服务器URL
    appium_server_url = os.getenv('APPIUM_SERVER_URL')
    
    # 打印当前页面的XML结构
    wx = WeChatOperator(appium_server_url=appium_server_url)

    try:
        wx.print_all_elements()
    except Exception as e:
        
        print(f"运行出错: {str(e)}")
    finally:
        # 关闭操作器
        wx.close()
