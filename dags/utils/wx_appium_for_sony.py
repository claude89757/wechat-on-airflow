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
    def __init__(self, appium_server_url: str = 'http://localhost:4723', device_name: str = 'BH901V3R9E', force_app_launch: bool = False):
        """
        初始化微信操作器
        appium_server_url: Appium服务器URL
        device_name: 设备名称
        force_app_launch: 是否强制重启应用
        """
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            udid=device_name,
            # deviceName=device_name,
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
        self.return_to_chats()


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


    def get_recent_new_msg(self):
        """
        获取最近聊天的新消息
        返回格式, 多个聊天会话的多个信息
        {
         "张三": [
            {
                "sender": "张三",
                "msg": "你好",
                "msg_type": "text",
                "msg_time": "2021-01-01 12:00:00"
            },
            {
                "sender": "张三",
                "msg": "在吗？",
                "msg_type": "text",
                "msg_time": "2021-01-01 12:00:00"
            }
         ],
         "李四": [
            {   
                "sender": "李四",
                "msg": "在吗？",
                "msg_type": "text",
                "msg_time": "2021-01-01 12:00:00"
            }
         ]
        }
        """
        try:
            # 确保在微信主页面
            if not self.is_at_main_page():
                self.return_to_chats()
                time.sleep(1)
                
            # 初始化结果字典
            result = {}
            
            # 先获取所有聊天列表项
            chat_items = self.driver.find_elements(
                by=AppiumBy.XPATH,
                value="//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/cj1']"
            )
            
            # 遍历每个聊天项，查找带有未读消息的
            unread_chats = 0
            for chat_item in chat_items:
                try:
                    # 检查是否有未读消息标记
                    unread_indicators = chat_item.find_elements(
                        by=AppiumBy.ID,
                        value="com.tencent.mm:id/o_u"
                    )
                    
                    # 如果没有未读消息，跳过
                    if not unread_indicators:
                        continue
                        
                    unread_chats += 1
                    
                    # 获取未读消息数量
                    unread_count = int(unread_indicators[0].text)
                    print(f"[INFO] 发现一个会话有 {unread_count} 条未读消息")
                    
                    # 获取联系人名称
                    contact_name_elem = chat_item.find_element(
                        by=AppiumBy.XPATH,
                        value=".//android.view.View[@resource-id='com.tencent.mm:id/kbq']"
                    )
                    contact_name = contact_name_elem.text
                    print(f"[INFO] 联系人: {contact_name}")
                    
                    # 获取会话时间
                    try:
                        time_elem = chat_item.find_element(
                            by=AppiumBy.XPATH,
                            value=".//android.view.View[@resource-id='com.tencent.mm:id/otg']"
                        )
                        chat_time = time_elem.text
                        print(f"[INFO] 会话时间: {chat_time}")
                    except:
                        chat_time = ""
                        print("[WARNING] 无法获取会话时间")
                    
                    # 获取最近一条消息的预览文本和类型
                    msg_text = ""
                    msg_type = "text"  # 默认为文本类型
                    try:
                        msg_preview_elem = chat_item.find_element(
                            by=AppiumBy.XPATH,
                            value=".//android.view.View[@resource-id='com.tencent.mm:id/ht5']"
                        )
                        msg_text = msg_preview_elem.text
                        
                        # 根据预览文本判断消息类型
                        if msg_text == "[图片]":
                            msg_type = "image"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 图片)")
                        elif msg_text == "[视频]":
                            msg_type = "video"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 视频)")
                        elif msg_text == "[语音]":
                            msg_type = "voice"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 语音)")
                        elif msg_text == "[位置]":
                            msg_type = "location"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 位置)")
                        elif msg_text == "[文件]":
                            msg_type = "file"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 文件)")
                        elif msg_text == "[动画表情]" or msg_text == "[表情]":
                            msg_type = "sticker"
                            print(f"[INFO] 最近消息预览: {msg_text} (类型: 表情)")
                        else:
                            print(f"[INFO] 最近消息预览: {msg_text}")
                    except:
                        print("[WARNING] 无法获取消息预览")
                    
                    # 点击进入聊天界面
                    print(f"[INFO] 正在进入与 {contact_name} 的聊天界面...")
                    chat_item.click()
                    time.sleep(2)  # 等待加载聊天界面
                    
                    # 获取消息内容
                    messages = []
                    try:
                        # 查找聊天消息列表
                        msg_elements = self.driver.find_elements(
                            by=AppiumBy.XPATH,
                            value="//androidx.recyclerview.widget.RecyclerView/android.widget.RelativeLayout"
                        )
                        
                        # 如果没有找到，尝试另一种元素查找方式
                        if not msg_elements:
                            msg_elements = self.driver.find_elements(
                                by=AppiumBy.XPATH,
                                value="//android.widget.ListView/android.widget.LinearLayout"
                            )
                        
                        print(f"[INFO] 找到 {len(msg_elements)} 条消息元素")
                        
                        # 从最新的消息开始获取，最多获取未读消息数量
                        for i in range(min(unread_count, len(msg_elements))):
                            try:
                                # 获取倒数第i+1条消息
                                msg_elem = msg_elements[len(msg_elements) - 1 - i]
                                
                                # 获取消息内容
                                content_elem = None
                                cur_msg_type = "text"  # 默认为文本类型
                                
                                # 尝试查找不同类型的消息元素
                                try:
                                    # 文本消息
                                    content_elem = msg_elem.find_element(
                                        by=AppiumBy.XPATH,
                                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/bkl']"
                                    )
                                    cur_msg_text = content_elem.text
                                except:
                                    try:
                                        # 查找其他可能的文本元素
                                        content_elem = msg_elem.find_element(
                                            by=AppiumBy.XPATH,
                                            value=".//android.widget.TextView"
                                        )
                                        cur_msg_text = content_elem.text
                                    except:
                                        # 如果找不到文本元素，检查是否有图片元素
                                        try:
                                            img_elem = msg_elem.find_element(
                                                by=AppiumBy.XPATH,
                                                value=".//android.widget.ImageView"
                                            )
                                            # 存在ImageView元素，可能是图片消息
                                            content_elem = img_elem
                                            cur_msg_text = "[图片]"  # 直接设置固定文本内容
                                            cur_msg_type = "image"
                                        except:
                                            print("[WARNING] 无法找到消息内容元素")
                                            continue
                                
                                # 获取消息时间
                                msg_time = chat_time
                                try:
                                    time_elem = msg_elem.find_element(
                                        by=AppiumBy.XPATH,
                                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/br1']"
                                    )
                                    msg_time = time_elem.text
                                except:
                                    pass
                                
                                # 获取发送者
                                sender = contact_name
                                try:
                                    # 尝试获取发送者头像的内容描述
                                    avatar_elem = msg_elem.find_element(
                                        by=AppiumBy.XPATH,
                                        value=".//android.widget.ImageView[@resource-id='com.tencent.mm:id/bk1']"
                                    )
                                    if avatar_elem.get_attribute("content-desc"):
                                        sender_desc = avatar_elem.get_attribute("content-desc")
                                        if "头像" in sender_desc:
                                            sender = sender_desc.replace("头像", "")
                                except:
                                    pass
                                
                                # 如果是首条消息，使用从会话列表中获取的类型
                                if i == 0 and msg_type != "text":
                                    cur_msg_type = msg_type
                                
                                # 构建消息对象
                                if content_elem:
                                    message = {
                                        "sender": sender,
                                        "msg": cur_msg_text,
                                        "msg_type": cur_msg_type,
                                        "msg_time": msg_time
                                    }
                                    messages.append(message)
                                    print(f"[INFO] 获取到消息: {cur_msg_text[:50] if len(cur_msg_text) > 50 else cur_msg_text} (类型: {cur_msg_type})")
                            except Exception as e:
                                print(f"[WARNING] 解析消息时出错: {str(e)}")
                                continue
                        
                    except Exception as e:
                        print(f"[ERROR] 获取消息内容时出错: {str(e)}")
                        import traceback
                        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
                    
                    # 将消息添加到结果字典
                    if messages:
                        result[contact_name] = messages
                    else:
                        # 如果没有获取到详细消息，至少添加一条消息（基于会话列表预览）
                        result[contact_name] = [{
                            "sender": contact_name,
                            "msg": msg_text or "无法获取具体消息内容",
                            "msg_type": msg_type,
                            "msg_time": chat_time
                        }]
                    
                    # 返回到主界面继续处理下一个会话
                    print(f"[INFO] 正在返回主界面...")
                    self.return_to_chats()
                    time.sleep(1.5)  # 等待返回
                    
                except Exception as e:
                    print(f"[ERROR] 处理会话时出错: {str(e)}")
                    import traceback
                    print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
                    
                    # 确保返回到主界面
                    if not self.is_at_main_page():
                        self.return_to_chats()
                        time.sleep(1.5)
                    continue
                    
            print(f"[INFO] 发现 {unread_chats} 个带有未读消息的会话")
            print(f"[INFO] 成功获取了 {len(result)} 个会话的新消息")
            return result
            
        except Exception as e:
            print(f"[ERROR] 获取最近新消息时出错: {str(e)}")
            import traceback
            print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
            
            # 确保返回到主界面
            if not self.is_at_main_page():
                try:
                    self.return_to_chats()
                except:
                    pass
                
            return {}

    def close(self):
        """
        关闭微信操作器
        """
        if self.driver:
            self.driver.quit()
            print('控制器已关闭。')


def send_wx_msg_by_appium(appium_server_url: str, device_name: str, contact_name: str, messages: list[str]):
    """
    发送消息到微信, 支持多条消息
    appium_server_url: Appium服务器URL
    device_name: 设备名称
    contact_name: 联系人名称
    messages: 消息列表
    """
    # 发送消息
    wx_operator = None
    try:
        # 首先尝试不重启应用
        print("[INFO] 尝试不重启应用，检查当前是否在微信...")
        wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=False)
        time.sleep(1)
        
        # 检查是否在微信主页面
        if wx_operator.is_at_main_page():
            print("[INFO] 已在微信主页面，无需重启应用")
        else:
            # 不在主页面，可能需要关闭当前实例并重启
            print("[INFO] 不在微信主页面，将关闭当前实例并重启应用")
            if wx_operator:
                wx_operator.close()

            # 重新启动微信
            wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=True)
            time.sleep(3)
        
        wx_operator.send_message(contact_name=contact_name, messages=messages)
    except Exception as e:
        print(f"[ERROR] 发送消息时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
    finally:
        # 关闭操作器
        if wx_operator:
            wx_operator.close()
        

def get_recent_new_msg_by_appium(appium_server_url: str, device_name: str) -> dict:
    """
    获取微信最近的新消息
    appium_server_url: Appium服务器URL
    device_name: 设备名称
    """
    # 获取消息
    wx_operator = None
    try:
        # 首先尝试不重启应用
        print("[INFO] 尝试不重启应用，检查当前是否在微信...")
        wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=False)
        time.sleep(1)
        
        # 检查是否在微信主页面
        if wx_operator.is_at_main_page():
            print("[INFO] 已在微信主页面，无需重启应用")
        else:
            # 不在主页面，可能需要关闭当前实例并重启
            print("[INFO] 不在微信主页面，将关闭当前实例并重启应用")
            if wx_operator:
                wx_operator.close()
                wx_operator = None
                time.sleep(1)
            
            # 重新启动微信
            wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=True)
            time.sleep(3)
        
        # 获取最近新消息
        result = wx_operator.get_recent_new_msg()

        return result
    except Exception as e:
        print(f"[ERROR] 获取消息时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
        return {}
    finally:
        # 关闭操作器
        if wx_operator:
            wx_operator.close()
        

# 测试代码
if __name__ == "__main__":    
    # 获取Appium服务器URL
    appium_server_url = os.getenv('APPIUM_SERVER_URL', 'http://localhost:4723')
    print(appium_server_url)

    # 打印当前页面的XML结构
    wx1 = WeChatOperator(appium_server_url=appium_server_url, device_name='BH901V3R9E', force_app_launch=False)

    try:
        time.sleep(5)
        # print(wx.driver.page_source)
        wx1.print_all_elements()

        wx1.print_all_elements()
        # wx1.send_message(contact_name="文件传输助手", messages=["test1", "test2", "test3"])

        print(wx1.get_recent_new_msg())
        
    except Exception as e:
        
        print(f"运行出错: {str(e)}")
    finally:
        # 关闭操作器
        wx1.close()
