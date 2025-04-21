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
import random

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

    def send_message(self, contact_name: str, messages: list[str]):
        """
        发送消息给指定联系人
        Args:
            contact_name: 联系人名称
            messages: 要发送的消息列表
        """
        if not messages:
            print(f"[WARNING] 未提供需要发送的消息，将跳过发送")
            return
            
        print(f"[INFO] 正在发送消息给 {contact_name}, 共 {len(messages)} 条消息")
        print("="*100)
        print("\n".join(messages))
        print("="*100)

        # 先查找最近的会话中是否存在该联系人
        if self.is_contact_in_recent_chats(contact_name):
            print(f"[INFO] 联系人 {contact_name} 已在最近的会话中, 直接进入聊天界面")
        else:
            print(f"[INFO] 联系人 {contact_name} 不在最近的会话中, 先搜索并进入聊天界面")

            # 点击搜索按钮
            print("[1] 正在点击搜索按钮...")
            search_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "搜索"))
            )
            search_btn.click()
            print("[1] 点击搜索按钮成功")
            
            # 输入联系人名称
            print("[2] 正在输入联系人名称...")
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.EditText[@text='搜索']"))
            )
            search_input.send_keys(contact_name)
            print("[2] 输入联系人名称成功")

            # 点击联系人
            print("[3] 正在点击联系人...")
            contact = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    AppiumBy.XPATH,
                    f"//android.widget.TextView[@text='{contact_name}']"
                ))
            )
            contact.click()
            print("[3] 成功进入联系人聊天界面")

        # 循环发送每条消息
        for index, message in enumerate(messages, 1):
            try:
                # 输入消息
                print(f"[4.{index}] 正在输入第 {index}/{len(messages)} 条消息...")
                message_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.EditText"))
                )
                message_input.send_keys(message)

                # 点击发送按钮
                print(f"[5.{index}] 正在点击发送按钮...")
                send_btn = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[@text='发送']"
                )
                send_btn.click()
                print(f"[5.{index}] 第 {index}/{len(messages)} 条消息发送成功")
                
                # 如果不是最后一条消息，随机等待一小段时间避免发送过快
                if index < len(messages):
                    random_wait = random.uniform(0.3, 3)
                    time.sleep(random_wait)
            except Exception as e:
                print(f"[ERROR] 发送第 {index}/{len(messages)} 条消息失败: {str(e)}")
                raise

        print(f"[SUCCESS] 所有消息已发送给 {contact_name}")


    def is_contact_in_recent_chats(self, contact_name: str) -> bool:
        """
        检查指定联系人是否在最近的会话中
        Args:
            contact_name: 联系人名称
        Returns:
            bool: 如果联系人在最近会话中返回True，否则返回False
        Raises:
            Exception: 如果找到多个同名联系人则抛出异常
        """
        print(f"[INFO] 检查联系人 {contact_name} 是否在最近聊天中...")
        
        # 确保在微信主页面
        if not self.is_at_main_page():
            self.return_to_chats()
            time.sleep(1)
        
        # 最大尝试滑动次数
        max_scroll_attempts = 5
        
        for attempt in range(max_scroll_attempts):
            try:
                # 尝试查找联系人，只通过text属性查找
                contact_elements = self.driver.find_elements(
                    by=AppiumBy.XPATH,
                    value=f"//android.view.View[@text='{contact_name}']"
                )
                
                # 检查找到的联系人数量
                if len(contact_elements) > 1:
                    error_msg = f"[ERROR] 找到多个同名联系人 '{contact_name}'，无法确定要点击哪一个"
                    print(error_msg)
                    raise Exception(error_msg)
                    
                if contact_elements:
                    print(f"[INFO] 找到联系人 {contact_name} 在最近聊天中")
                    contact_elements[0].click()
                    time.sleep(1)
                    return True
                
                # 如果没找到并且还有尝试次数，向下滑动
                if attempt < max_scroll_attempts - 1:
                    print(f"[INFO] 在第 {attempt+1} 次尝试中未找到联系人，向下滑动...")
                    self.scroll_down()
                    time.sleep(0.5)
                
            except Exception as e:
                print(f"[ERROR] 检查联系人时出错: {str(e)}")
                raise  # 重新抛出异常
        
        print(f"[INFO] 联系人 {contact_name} 不在最近聊天中")
        return False

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


def send_wx_msg_by_appium(contact_name: str, messages: list[str]) -> bool:
    """发送消息到微信"""
    # 获取Appium服务器URL和初始化锁变量
    try:
        from airflow.models import Variable
        appium_server_url = Variable.get('ZACKS_APPIUM_SERVER_URL')
        
        # 检查锁状态
        lock_key = 'ZACKS_WX_APPIUM_LOCK'
        lock_status = None
        
        # 如果锁已被占用，最多等待180秒
        max_wait_time = 180  # 最大等待时间（秒）
        wait_interval = 5  # 每次检查间隔（秒）
        total_waited = 0
        
        while total_waited <= max_wait_time:
            try:
                lock_status = Variable.get(lock_key)
                print(f"当前锁状态: {lock_status}")
                
                if lock_status != 'LOCKED':
                    # 锁未被占用，可以继续执行
                    break
                
                # 锁被占用，等待一段时间后重试
                if total_waited == 0:
                    print(f"[WARN] 检测到微信操作锁被占用，将等待最多 {max_wait_time} 秒...")
                
                wait_time = min(wait_interval, max_wait_time - total_waited)
                if wait_time <= 0:
                    break
                    
                print(f"[INFO] 已等待 {total_waited} 秒，继续等待 {wait_time} 秒...")
                time.sleep(wait_time)
                total_waited += wait_time
                
            except:
                # 锁不存在，可以继续执行
                print(f"[INFO] 锁不存在，可以继续执行")
                break
                
        # 如果经过等待后锁仍被占用，则退出
        if lock_status == 'LOCKED' and total_waited >= max_wait_time:
            print(f"[ERROR] 等待超时（{max_wait_time}秒），微信操作锁仍被占用，无法执行操作")
            return False
            
        # 设置锁
        print(f"[INFO] 设置微信操作锁...")
        Variable.set(lock_key, 'LOCKED')
        print(f"[INFO] 微信操作锁设置成功")
        
    except Exception as e:
        print(f"[ERROR] 初始化锁或获取Appium服务器URL时出错: {str(e)}")
        return False

    # 发送消息
    wx = None
    try:
        wx = WeChatOperator(appium_server_url=appium_server_url, force_app_launch=True)
        time.sleep(3)
        wx.send_message(contact_name=contact_name, messages=messages)
        success = True
        return True
    except Exception as e:
        print(f"[ERROR] 发送消息时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
        return False
    finally:
        # 关闭操作器
        if wx:
            wx.close()
        
        # 释放锁
        try:
            print(f"[INFO] 释放微信操作锁...")
            Variable.set(lock_key, 'UNLOCKED')
            print(f"[INFO] 微信操作锁释放成功")
        except Exception as e:
            print(f"[ERROR] 释放锁时出错: {str(e)}")


# 测试代码
if __name__ == "__main__":    
    # 获取Appium服务器URL
    appium_server_url = os.getenv('APPIUM_SERVER_URL')
    
    # 打印当前页面的XML结构
    wx = WeChatOperator(appium_server_url=appium_server_url, force_app_launch=False)

    try:
        time.sleep(5)
        # print(wx.driver.page_source)
        # wx.print_all_elements()

        wx.send_message(contact_name="文件传输助手", messages=["test1", "test2", "test3"])
    except Exception as e:
        
        print(f"运行出错: {str(e)}")
    finally:
        # 关闭操作器
        wx.close()
