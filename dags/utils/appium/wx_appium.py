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
import uuid
from appium.webdriver.webdriver import WebDriver as AppiumWebDriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.android import UiAutomator2Options

from xml.etree import ElementTree

from utils.appium.handler_video import (
    save_video,
    clear_mp4_files_in_directory,
    pull_file_from_device,
    push_file_to_device,
    download_file_via_sftp
)

from utils.dify_sdk import DifyAgent
from utils.appium.ssh_control import (
    get_image_path,
    pull_image_from_device
)

from airflow.models.variable import Variable
from datetime import datetime
from appium_wx_dags.common.mysql_tools import save_data_to_db

class WeChatOperator:
    def __init__(self, appium_server_url: str = 'http://localhost:4723', device_name: str = 'BH901V3R9E', force_app_launch: bool = False, login_info: dict = None):
        """
        初始化微信操作器
        appium_server_url: Appium服务器URL
        device_name: 设备名称
        force_app_launch: 是否强制重启应用
        login_info: 登录信息
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
            resetKeyboard=True,  # 重置输入法
        )
        
        # 登录信息
        self.login_info = login_info
        self.device_name = device_name

        print('正在初始化微信控制器...')
        print("-"*100)
        print(json.dumps(capabilities, indent=4, ensure_ascii=False))
        print("-"*100)
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


    def send_top_n_image_or_video_msg(self, contact_name: str, top_n: int = 1):
        """
        发送指定数量的图片或视频消息给指定联系人
        """ 
        print(f"[INFO] 正在发送消息给 {contact_name}, 共 {top_n} 条消息")

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

        try:
            # 点击更多功能按钮
            print("[4] 正在点击更多功能按钮...")
            more_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    AppiumBy.XPATH,
                    "//android.widget.ImageButton[contains(@content-desc, '更多功能按钮')]"
                ))
            )
            print('更多功能按钮定位成功')
            more_btn.click()
            print("[4] 点击更多功能按钮成功")
            time.sleep(1)# 等待更多功能菜单弹出
            # 点击相册按钮
            print("[5] 正在点击相册按钮...")
            album_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    AppiumBy.XPATH,
                    "//android.widget.TextView[@text='相册']"
                ))
            )
            album_btn.click()
            print("[5] 点击相册按钮成功")
            
            # 选择前面的n张图片或视频
            print(f"[6] 正在选择前 {top_n} 张图片或视频...")
            time.sleep(2)  # 等待相册加载
            
            # 获取所有的图片/视频选择框
            checkboxes = WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((
                    AppiumBy.XPATH,
                    "//android.widget.CheckBox[@resource-id='com.tencent.mm:id/jdh']"
                ))
            )
            
            print(f"[INFO] 找到 {len(checkboxes)} 个可选择的图片/视频")
            
            # 选择前top_n个不同的图片/视频
            selected_count = 0
            for i, checkbox in enumerate(checkboxes):
                if selected_count >= top_n or i >= min(top_n * 2, len(checkboxes)):
                    break
                
                try:
                    # 检查是否已选中
                    is_checked = checkbox.get_attribute("checked") == "true"
                    
                    if not is_checked:
                        checkbox.click()
                        selected_count += 1
                        print(f"[6.{selected_count}] 已选择第 {i+1} 个图片/视频")
                        time.sleep(0.5)  # 短暂等待确保UI更新
                except Exception as e:
                    print(f"[WARNING] 选择第 {i+1} 个图片/视频时出错: {str(e)}")
            
            print(f"[INFO] 成功选择了 {selected_count} 个图片/视频")
            
            if selected_count == 0:
                print("[WARNING] 未能选择任何图片/视频，将返回聊天界面")
                # 按返回键返回聊天界面
                self.driver.press_keycode(4)
                time.sleep(1)
                self.return_to_chats()
                return
            
            # 点击发送按钮
            print("[7] 正在点击发送按钮...")
            try:
                # 首先尝试通过资源ID查找发送按钮
                send_btn = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.Button[@resource-id='com.tencent.mm:id/kaq']"
                    ))
                )
                send_btn.click()
            except:
                # 如果通过ID找不到，则尝试通过文本找
                try:
                    send_btn = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            AppiumBy.XPATH,
                            "//android.widget.Button[contains(@text, '发送')]"
                        ))
                    )
                    send_btn.click()
                except Exception as e:
                    print(f"[ERROR] 无法找到发送按钮: {str(e)}")
                    # 按返回键返回聊天界面
                    self.driver.press_keycode(4)
                    time.sleep(1)
                    self.driver.press_keycode(4)
                    time.sleep(1)
                    return
            
            print("[7] 点击发送按钮成功")
            time.sleep(2)  # 等待发送完成
            
            print(f"[SUCCESS] 已成功发送 {selected_count} 张图片或视频给 {contact_name}")
            
        except Exception as e:
            print(f"[ERROR] 发送图片或视频失败: {str(e)}")
            import traceback
            print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
        
        # 返回到聊天列表界面
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

    def scroll_down(self,start=0.8,end=0.2):
        """
        向下滑动页面
        """
        try:
            screen_size = self.driver.get_window_size()
            start_x = screen_size['width'] * 0.5
            start_y = screen_size['height'] *start
            end_y = screen_size['height'] * end
            
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
                    print(back_btn)
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
            # elements=[
            #     "//android.widget.TextView[@resource-id='com.tencent.mm:id/icon_tv' and @text='我']",
            #     "//android.widget.TextView[@resource-id='com.tencent.mm:id/icon_tv' and @text='发现']",
            #     "//android.widget.TextView[@resource-id='com.tencent.mm:id/icon_tv' and @text='通讯录']",
            #     "//android.widget.TextView[@resource-id='com.tencent.mm:id/icon_tv' and @text='微信']"
            # ]
            for xpath in elements:
                self.driver.find_element(AppiumBy.XPATH, xpath)
                print('定位成功')
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

    def _get_image_msg_content(self, msg_elem):
        """
        获取图片消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 查找带有图片标识的ImageView
            img_elem = msg_elem.find_element(
                by=AppiumBy.XPATH,
                value=".//android.widget.ImageView[@content-desc='图片'][@resource-id='com.tencent.mm:id/bkm']"
            )
            # 找到明确标识为图片的元素
            # TODO(claude89757): 下载图片，并上传到cos

            # 保存图片到本地
            print(f"[INFO] 正在保存图片...")

            try:
                img_elem.click()
                time.sleep(1)
                WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, '更多信息'))).click()

                WebDriverWait(self.driver, 60). \
                    until(EC.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="保存图片"]'))).click()
                # 返回聊天页面
                self.driver.press_keycode(4)
                print(f"[INFO] 图片保存成功")
            except Exception as e:
                print(f"[ERROR] 保存图片失败: {e}")
            

            # 提取login信息
            if self.login_info:
                print(f"[INFO] 登录信息: {self.login_info}")
                device_ip = self.login_info["device_ip"]
                username = self.login_info["username"]
                password = self.login_info["password"]
                port = self.login_info["port"]
                device_serial = self.device_name
            else:
                print(f"[INFO] 登录信息为空，无法传输图片")


            # 获取图片路径
            image_path = get_image_path(device_ip, username, password, device_serial, port=port)

            # 在主机上从手机上pull图片
            directory_path = image_path
            image_name = os.path.basename(directory_path)
            local_path = f"/tmp/image_downloads/{image_name}"
            print(f"[INFO] 从手机上pull图片: {local_path}")
            pull_image_from_device(device_ip, username, password, device_serial, directory_path, local_path, port=port)

            # 使用ftp传送图片
            # print(f"[INFO] 从主机上下载图片: {local_path}")
            # image_url = download_file_via_sftp(device_ip, username, password, local_path, local_path, port=port)
            # print(f"[INFO] 从主机上下载图片成功: {image_url}")
            
            image_url = local_path

            # cur_msg_text = "[图片]"
            cur_msg_text = f"[图片]:{image_url}"
            cur_msg_type = "image"
            print(f"[INFO] 通过content-desc='图片'找到图片消息")
        except Exception as e:
            print(f"[ERROR] 获取图片消息内容 错误信息: {e}")

        return cur_msg_text, cur_msg_type

    def _get_video_msg_content(self, msg_elem):
        """
        获取视频消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 尝试查找视频消息元素
            # 根据截图中的层级结构寻找视频元素
            video_container = msg_elem.find_element(
                by=AppiumBy.XPATH,
                value=".//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/oy_']"
            )
            if video_container:
                # 找到视频帧图像
                video_image = video_container.find_element(
                    by=AppiumBy.XPATH,
                    value=".//android.widget.FrameLayout[@resource-id='com.tencent.mm:id/bkg']/android.widget.ImageView"
                )
                # 找到视频时长文本
                video_duration = video_container.find_element(
                    by=AppiumBy.XPATH,
                    value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/boy']"
                )
                video_duration_text = video_duration.text

                video_url = ""
                if self.login_info:
                    print(f"正在保存视频...")
                    try:
                        print(f"[INFO] 登录信息: {self.login_info}")
                        # 保存视频到手机
                        print(f"[INFO] 保存视频到手机...")
                        phone_video_path = save_video(self.driver, video_duration)
                        print(f"[INFO] 保存视频到手机: {phone_video_path}")
                        
                        # 在主机上从手机上pull视频
                        device_ip = self.login_info["device_ip"]
                        username = self.login_info["username"]
                        password = self.login_info["password"]
                        port = self.login_info["port"]
                        device_serial = self.device_name
                        directory_path = phone_video_path
                        video_name = os.path.basename(phone_video_path)
                        local_path = f"/tmp/tennis_video_output/{video_name}"
                        print(f"[INFO] 从手机上pull视频: {local_path}")
                        pull_file_from_device(device_ip, username, password, device_serial, directory_path, local_path, port=port)

                        # 在主机上从主机上下载视频(路径均相同)
                        print(f"[INFO] 从主机上下载视频: {local_path}")
                        video_url = download_file_via_sftp(device_ip, username, password, local_path, local_path, port=port)
                        if not video_url:
                            print(f"[ERROR] 从主机上下载视频失败")
                            video_url = "下载视频失败"
                        print(f"[INFO] 从主机上下载视频: {video_url}")
                    except Exception as e:
                        print(f"[ERROR] 从主机上下载视频失败: {e}")
                        video_url = "下载视频失败"
                else:
                    print(f"登录信息为空，无法下载视频")

                video_length = video_duration_text if video_duration_text else "未知时长"
                cur_msg_text = f"[视频] {video_length}: {video_url}"
                cur_msg_type = "video"
                print(f"[INFO] 获取到视频消息: {cur_msg_text} (时长: {video_length})")
        except:
            print("非视频消息")
        return cur_msg_text, cur_msg_type

    def _get_voice_msg_content(self, msg_elem):
        """
        获取语音消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 尝试查找语音消息元素 - 基于用户提供的XML修改resource-id
            voice_container = msg_elem.find_element(
                by=AppiumBy.XPATH,
                value=".//android.widget.FrameLayout[@resource-id='com.tencent.mm:id/brr']"
            )
            
            # 如果没有找到，尝试旧的resource-id
            if not voice_container:
                voice_container = msg_elem.find_element(
                    by=AppiumBy.XPATH,
                    value=".//android.widget.FrameLayout[@resource-id='com.tencent.mm:id/brq']"
                )
            
            if voice_container:
                # 获取语音时长 - 根据XML直接使用content-desc属性
                voice_length = "1秒"  # 默认值
                try:
                    # 根据XML找到带有语音时长的元素
                    duration_elem = voice_container.find_element(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/bkl']"
                    )
                    if duration_elem.text:
                        voice_length = duration_elem.text
                except:
                    pass
                
                # 检查是否已经有转文字结果
                try:
                    # 使用resource-id查找
                    voice_text_elem = voice_container.find_element(
                        by=AppiumBy.XPATH, 
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/brv']"
                    )
                    voice_text = voice_text_elem.text
                    cur_msg_text = f"[语音] {voice_length}: {voice_text}"
                except:
                    # 检查是否有转文字按钮
                    try:
                        # 首先检查是否存在"转文字"按钮
                        convert_text_btn = voice_container.find_element(
                            by=AppiumBy.XPATH,
                            value=".//android.widget.RelativeLayout[@resource-id='com.tencent.mm:id/blv']"
                        )
                        
                        # 验证是否是"转文字"按钮
                        convert_text_label = convert_text_btn.find_element(
                            by=AppiumBy.XPATH,
                            value=".//android.widget.TextView[@text='转文字']"
                        )
                        
                        if convert_text_label:
                            print("[INFO] 找到转文字按钮，点击...")
                            convert_text_label.click()
                            time.sleep(2)  # 等待转换完成
                            
                            # 刷新页面DOM
                            page_source = self.driver.page_source
                            
                            # 点击转文字后，重新获取整个页面的元素
                            try:
                                # 获取当前页面中所有匹配的语音文字结果元素
                                voice_text_elems = self.driver.find_elements(
                                    by=AppiumBy.XPATH,
                                    value="//android.widget.TextView[@resource-id='com.tencent.mm:id/brv']"
                                )
                                
                                # 如果找到文字结果元素，使用最后一个（通常是最新转换的）
                                if voice_text_elems and len(voice_text_elems) > 0:
                                    voice_text = voice_text_elems[-1].text
                                    cur_msg_text = f"[语音] {voice_length}: {voice_text}"
                                else:
                                    cur_msg_text = f"[语音] {voice_length}"
                            except:
                                cur_msg_text = f"[语音] {voice_length}"
                        else:
                            cur_msg_text = f"[语音] {voice_length}"
                    except:
                        # 如果没有直接可见的转文字按钮，尝试长按唤出菜单
                        try:
                            # 长按语音消息唤出菜单
                            print("[INFO] 长按语音消息唤出菜单")
                            self.driver.execute_script("mobile: longClickGesture", {
                                "elementId": voice_container.id,
                                "duration": 1000
                            })
                            time.sleep(0.5)
                            
                            # 点击"转文字"按钮
                            try:
                                convert_btn = WebDriverWait(self.driver, 3).until(
                                    EC.presence_of_element_located((
                                        AppiumBy.XPATH,
                                        "//android.widget.TextView[contains(@text, '转文字')]"
                                    ))
                                )
                                print("[INFO] 点击转文字按钮")
                                convert_btn.click()
                                time.sleep(2)
                                
                                # 刷新页面DOM
                                page_source = self.driver.page_source
                                
                                # 点击转文字后，重新获取整个页面的元素
                                try:
                                    # 获取当前页面中所有匹配的语音文字结果元素
                                    voice_text_elems = self.driver.find_elements(
                                        by=AppiumBy.XPATH,
                                        value="//android.widget.TextView[@resource-id='com.tencent.mm:id/brv']"
                                    )
                                    
                                    # 如果找到文字结果元素，使用最后一个（通常是最新转换的）
                                    if voice_text_elems and len(voice_text_elems) > 0:
                                        voice_text = voice_text_elems[-1].text
                                        cur_msg_text = f"[语音] {voice_length}: {voice_text}"
                                    else:
                                        cur_msg_text = f"[语音] {voice_length}"
                                except:
                                    cur_msg_text = f"[语音] {voice_length}"
                            except:
                                # 如果没有找到"转文字"按钮，使用默认文本
                                print("[INFO] 未找到转文字按钮或转换失败")
                                # 点击空白区域关闭菜单
                                self.driver.press_keycode(4)  # 按返回键关闭菜单
                                time.sleep(0.5)
                                cur_msg_text = f"[语音] {voice_length}"
                        except:
                            cur_msg_text = f"[语音] {voice_length}"
                
                cur_msg_type = "voice"
                print(f"[INFO] 获取到语音消息: {cur_msg_text}")
        except:
            print(f"非语音消息")

        return cur_msg_text, cur_msg_type
        
    def _get_location_msg_content(self, msg_elem):
        """
        获取位置消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 尝试查找位置消息容器
            location_container = msg_elem.find_element(
                by=AppiumBy.XPATH,
                value=".//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/bp7']"
            )
            
            if location_container:
                # 获取位置标题 (如"中兴通讯员工宿舍")
                try:
                    location_title = location_container.find_element(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/bp8']"
                    )
                    title_text = location_title.text
                except:
                    title_text = "未知位置"
                
                # 获取位置详细地址 (如"广东省深圳市南山区西丽街道打石一路22号2号楼")
                try:
                    location_address = location_container.find_element(
                        by=AppiumBy.XPATH, 
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/bp6']"
                    )
                    address_text = location_address.text
                except:
                    address_text = ""
                
                # 构建位置消息文本
                if address_text:
                    cur_msg_text = f"[位置] {title_text}: {address_text}"
                else:
                    cur_msg_text = f"[位置] {title_text}"
                
                cur_msg_type = "location"
                print(f"[INFO] 获取到位置消息: {cur_msg_text}")
        except:
            print(f"非位置消息")
            
        return cur_msg_text, cur_msg_type

    def _get_file_msg_content(self, msg_elem):
        """
        获取文件消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 基于XML结构查找文件消息容器
            # 尝试查找包含文件信息的容器
            file_container = msg_elem.find_element(
                by=AppiumBy.XPATH,
                value=".//android.widget.FrameLayout[@resource-id='com.tencent.mm:id/bkg']"
            )
            
            # 查找文件名元素 - 尝试多种可能的resource-id
            file_name = None
            for resource_id in ['com.tencent.mm:id/bju', 'com.tencent.mm:id/bjp']:
                try:
                    file_name_elem = file_container.find_element(
                        by=AppiumBy.XPATH,
                        value=f".//android.widget.TextView[@resource-id='{resource_id}']"
                    )
                    file_name = file_name_elem.text
                    break
                except:
                    continue
            
            # 如果通过resource-id没找到，尝试查找第一个TextView元素
            if not file_name:
                try:
                    # 查找文件名可能在多个不同位置，尝试不同的路径
                    file_name_elems = file_container.find_elements(
                        by=AppiumBy.XPATH, 
                        value=".//android.widget.TextView"
                    )
                    # 通常第一个TextView就是文件名
                    if file_name_elems and len(file_name_elems) > 0:
                        file_name = file_name_elems[0].text
                except:
                    pass
            
            # 查找文件大小元素 - 尝试多种可能的resource-id
            file_size = None
            for resource_id in ['com.tencent.mm:id/bj2', 'com.tencent.mm:id/bjm']:
                try:
                    file_size_elem = file_container.find_element(
                        by=AppiumBy.XPATH,
                        value=f".//android.widget.TextView[@resource-id='{resource_id}']"
                    )
                    file_size = file_size_elem.text
                    break
                except:
                    continue
            
            # 如果通过resource-id没找到，尝试查找包含"KB"或"MB"的TextView
            if not file_size:
                try:
                    size_candidates = file_container.find_elements(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView[contains(@text, 'KB') or contains(@text, 'MB') or contains(@text, 'B')]"
                    )
                    if size_candidates:
                        file_size = size_candidates[0].text
                except:
                    pass
            
            # 构建文件消息文本
            if file_name:
                if file_size:
                    cur_msg_text = f"[文件] {file_name} ({file_size})"
                else:
                    cur_msg_text = f"[文件] {file_name}"
                cur_msg_type = "file"
                print(f"[INFO] 获取到文件消息: {cur_msg_text}")
            
        except Exception as e:
            # 尝试另一种方式查找文件消息
            try:
                # 查找包含文件图标的布局
                file_icon = msg_elem.find_element(
                    by=AppiumBy.XPATH,
                    value=".//android.widget.ImageView[@resource-id='com.tencent.mm:id/bjs']"
                )
                
                # 如果找到文件图标，再查找相邻的文件名和大小
                if file_icon:
                    # 查找所有TextView，通常第一个是文件名，第二个是大小
                    text_elems = msg_elem.find_elements(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView"
                    )
                    
                    file_name = None
                    file_size = None
                    
                    # 遍历找到的文本元素
                    for elem in text_elems:
                        text = elem.text
                        if text:
                            # 如果文本中包含尺寸单位，则可能是文件大小
                            if any(unit in text for unit in ['KB', 'MB', 'GB', 'B']):
                                file_size = text
                            # 否则第一个非空文本可能是文件名
                            elif file_name is None:
                                file_name = text
                    
                    # 构建文件消息文本
                    if file_name:
                        if file_size:
                            cur_msg_text = f"[文件] {file_name} ({file_size})"
                        else:
                            cur_msg_text = f"[文件] {file_name}"
                        cur_msg_type = "file"
                        print(f"[INFO] 获取到文件消息: {cur_msg_text}")
            except:
                print(f"非文件消息")
                
        return cur_msg_text, cur_msg_type

    def _get_text_msg_content(self, msg_elem):
        """
        获取文本消息内容
        """
        cur_msg_text = ""
        cur_msg_type = ""
        try:
            # 文本消息
            content_elem = msg_elem.find_element(
            by=AppiumBy.XPATH,
            value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/bkl']"
        )
            cur_msg_text = content_elem.text
            cur_msg_type = "text"
            print(f"[INFO] 获取到消息: {cur_msg_text[:50] if len(cur_msg_text) > 50 else cur_msg_text} (类型: {cur_msg_type})")
        except:
            print("非文本消息")
        return cur_msg_text, cur_msg_type
        

    def agree_friend_request(self):
        #自动通过好友请求
        try:
            # 确保在微信主页面
            if not self.is_at_main_page():
                self.return_to_chats()
                time.sleep(1)
            # 定位到第二个RelativeLayout元素
            try:
                #定位到通讯录元素
                AddressBook = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="(//android.widget.RelativeLayout[@resource-id='com.tencent.mm:id/nvt'])[2]"
                )
                print(f"[INFO] 找到RelativeLayout元素: {AddressBook}")
                
                # 在该元素下查找TextView元素，为未处理的联系人数量
                try:
                    unread_contact_count = int(AddressBook.find_element(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/osw']"
                    ).text)
                except:
                    #若找不到元素(小红点)，则表示没有待添加的联系人，返回
                    print('暂无待添加的联系人')
                    return True
                new_friends_list=[]
                print(f"[INFO] 未添加联系人数量: {unread_contact_count}")
                #点击进入通讯录页面
                AddressBook.click()
                #等待页面加载
                time.sleep(1)
                #定位到未处理联系人列表
                self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/g_9']"
                ).click()
                print(f"成功进入未处理联系人列表")
                
                #等待页面加载
                time.sleep(1)
                #待执行添加好友逻辑的元素列表
                contact_list = self.driver.find_elements(
                    by=AppiumBy.ID,
                    value='com.tencent.mm:id/g_3'
                )
                print(contact_list)
                for ele in contact_list:
                    friend_name=ele.find_element(
                        by=AppiumBy.XPATH,
                        value=".//android.widget.TextView[@resource-id='com.tencent.mm:id/g_4']"
                    ).text
                    try:
                        ele.find_element(
                            by=AppiumBy.XPATH,
                            value=".//android.widget.Button[@resource-id='com.tencent.mm:id/g_8' and @text='接受']"
                        ).click()
                    except Exception as e:
                        print(f'联系人{friend_name}已添加')
                        continue
                    #等待页面加载
                    time.sleep(1)
                    print(f'进入{friend_name}的好友验证界面')
                    self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[@resource-id='com.tencent.mm:id/g68' and @text='完成']"
                    ).click()
                    try:
                        #以好友界面作为添加成功的判断标准
                        WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.TextView[@resource-id='com.tencent.mm:id/o3b' and @text='发消息']"
                        )))   
                        new_friends_list.append(friend_name)
                        print(f'添加好友----{friend_name}成功')
                        #点击左上角返回，回到待添加列表
                        WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.ImageView[@content-desc='返回']"
                        ))).click()
                        #等待页面加载
                        time.sleep(1)   
                    except Exception as e :
                        print(f'添加好友失败----{friend_name}，失败原因:{e}')

                print('所有待通过好友已处理完成!')   
                #等待页面加载
                time.sleep(1)    
                WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.ImageView[@content-desc='返回']"
                        ))).click()
                #等待页面加载
                time.sleep(1)
                #回到消息页
                WebDriverWait(self.driver, 15).until(EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "(//android.widget.RelativeLayout[@resource-id='com.tencent.mm:id/nvt'])[1]"
                        ))).click()  
                return new_friends_list
                
            except Exception as locate_error:
                print(f"[WARNING] 无法定位到未添加联系人数量元素: {str(locate_error)}")
                
        
        except Exception as e:
            print(f"[ERROR] 获取未添加联系人数量时出错: {str(e)}")
            import traceback
            print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
            return False

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
                                print(f"[INFO] 获取到消息元素{len(msg_elements) - 1 - i}: {msg_elem}")

                                # 获取消息内容
                                cur_msg_text = ""
                                cur_msg_type = ""

                                # 先尝试图片消息内容
                                cur_msg_text, cur_msg_type = self._get_image_msg_content(msg_elem)

                                # 再尝试视频消息内容
                                if not cur_msg_text:
                                    cur_msg_text, cur_msg_type = self._get_video_msg_content(msg_elem)

                                # 再尝试语音消息内容
                                if not cur_msg_text:
                                    cur_msg_text, cur_msg_type = self._get_voice_msg_content(msg_elem)

                                # 再尝试位置消息内容
                                if not cur_msg_text:
                                    cur_msg_text, cur_msg_type = self._get_location_msg_content(msg_elem)

                                # 再尝试文件消息内容
                                if not cur_msg_text:
                                    cur_msg_text, cur_msg_type = self._get_file_msg_content(msg_elem)

                                # 最后尝试文本消息内容
                                if not cur_msg_text:
                                    cur_msg_text, cur_msg_type = self._get_text_msg_content(msg_elem)

                                if not cur_msg_text:
                                    print("[ERROR] 无法获取消息内容")
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
                                if cur_msg_text:
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
            
            # TODO(claude89757): 会话存在"有人@我"的消息, 则进入会话获取@我的消息
            
            print(f"[INFO] 发现 {unread_chats} 个带有未读消息的会话")
            print(f"[INFO] 成功获取了 {len(result)} 个会话的新消息", result)
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

    def get_wx_account_info(self):
        """
        获取微信账号信息
        """
        try:
            # 确保在微信主页面
            if not self.is_at_main_page():
                self.return_to_chats()
                time.sleep(1)
            
            # 进入个人信息页面
            self.driver.find_element(
                by=AppiumBy.XPATH,
                value="//android.widget.TextView[@text='我']"
            ).click()
            time.sleep(1)

            # 获取微信名称
            wx_name = self.driver.find_element(
                by=AppiumBy.XPATH,
                value="//android.view.View[@resource-id='com.tencent.mm:id/kbb']"
            ).text.strip()
            
            # 获取微信号
            wxid = self.driver.find_element(
                by=AppiumBy.XPATH,
                value="//android.widget.TextView[@resource-id='com.tencent.mm:id/ouv']"
            ).text.strip().split("：")[-1]

            print(f'[INFO] 微信名称: {wx_name}, 微信ID: {wxid}')

            # 返回聊天页面
            self.driver.find_element(
                by=AppiumBy.XPATH,
                value="//android.widget.TextView[@text='微信']"
            ).click()
            print({"wx_name": wx_name, "wxid": wxid})
            return {"wx_name": wx_name, "wxid": wxid}
        
        except Exception as e:
            print(f"[ERROR] 进入个人信息页面时出错: {str(e)}")
            import traceback
            print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
            return {}

    def close(self):
        """
        关闭微信操作器
        """
        if self.driver:
            self.driver.quit()
            print('控制器已关闭。')


def send_wx_msg_by_appium(appium_server_url: str, device_name: str, contact_name: str, messages: list[str], response_image_list: list[str]= None):
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
        if response_image_list:
            # 发送图片或视频消息
            print(f"[INFO] 发送 {len(response_image_list)} 张图片或视频消息到 {contact_name}...")
            wx_operator.send_top_n_image_or_video_msg(contact_name, top_n=len(response_image_list))
        wx_operator.send_message(contact_name=contact_name, messages=messages)
    except Exception as e:
        print(f"[ERROR] 发送消息时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
    finally:
        # 关闭操作器
        if wx_operator:
            wx_operator.close()
        

def get_recent_new_msg_by_appium(appium_server_url: str, device_name: str, wx_id: str, wx_name: str, login_info: dict = None) -> dict:
    """
    获取微信最近的新消息
    appium_server_url: Appium服务器URL
    device_name: 设备名称
    wx_id: 微信ID
    wx_name: 微信名称
    login_info: 登录信息
    """
    # 获取消息
    wx_operator = None
    #前端控制回复的信息列表
    response_msg = {}
    
    try:
        # 首先尝试不重启应用
        print("[INFO] 尝试不重启应用，检查当前是否在微信...")
        wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=False, login_info=login_info)
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
            wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=True, login_info=login_info)
            time.sleep(3)
        #自动通过新添加好友
        new_friend_list=wx_operator.agree_friend_request()  
        #前端控制手机回复信息
        try:
            reply_data = Variable.get("REPLY_LIST", default_var={}, deserialize_json=True)
        
            print(f'待回复的消息列表===={reply_data}')
            # 根据device_name提取对应的reply_list
            device_reply_info = reply_data.get(wx_name, {})
            if device_reply_info !={}:
                
                reply_list = device_reply_info.get('reply_list', [])
                if reply_list!=[]:
                    # 创建一个副本用于遍历，避免在遍历过程中修改原列表
                    reply_list_copy = reply_list.copy()
                    
                    # 遍历待回复消息列表
                    for reply in reply_list_copy:
                        response_msg_list=[]
                        try:
                            # 获取好友昵称
                            contact_name = reply.get('contact_name', '未知好友') 
                            message_content = reply.get('msg', '')
                            
                            # 发送消息
                            wx_operator.send_message(contact_name=contact_name, messages=[message_content])
                            
                            # 发送成功后从待回复列表中删除该条消息
                            reply_list.remove(reply)
                            if contact_name not in response_msg:
                                response_msg[contact_name] = []
                            response_msg[contact_name].append(message_content)
                            print(f'已发送----{message_content}到好友----{contact_name}，并从待回复列表中删除')
                            time.sleep(2)

                            # 发送成功后保存到数据库
                            try:
                            
                                # 构造保存到数据库的消息数据
                                save_msg_data = {
                                    'msg_id': str(uuid.uuid4()),
                                    'wx_user_id': wx_id,
                                    'wx_user_name': wx_name,
                                    'room_id': contact_name,  # 使用联系人名称作为room_id
                                    'room_name': contact_name,
                                    'sender_id': wx_id,  # 发送者是当前微信用户
                                    'sender_name': wx_name,
                                    'msg_type': 1,  # 文本消息类型
                                    'msg_type_name': '文本',
                                    'content': message_content,
                                    'is_self': True,  # 是自己发送的消息
                                    'is_group': False,  # 不是群聊
                                    'source_ip': '',
                                    'msg_timestamp': datetime.now().timestamp(),
                                    
                                }
                                save_msg_data['msg_datetime']= datetime.fromtimestamp(save_msg_data['msg_timestamp']).strftime('%Y-%m-%d %H:%M')
                                # 保存到数据库
                                save_data_to_db(save_msg_data)
                                print(f'[DB_SAVE] 已保存回复消息到数据库: {message_content[:50]}...')
                                
                            except Exception as db_error:
                                print(f'[DB_SAVE] 保存消息到数据库失败: {str(db_error)}')
                                # 数据库保存失败不影响消息发送流程
                        except Exception as e:
                            print(f'发送消息到{contact_name}失败: {str(e)}')
                            # 发送失败时不删除消息，保留在列表中等待下次重试
                            continue
            
                    # 更新设备的回复信息
                    if wx_name in reply_data:
                        reply_data[wx_name]['reply_list'] = reply_list
            
                    # 将更新后的数据保存回Variable
                    Variable.set("REPLY_LIST", reply_data, serialize_json=True)
                    print(f'用户{wx_name}的待回复列表已更新，剩余{len(reply_list)}条消息')
        except Exception as e:

            print('获取Variable中REPLY_LIST的值失败，跳过回复信息流程')
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

def send_top_n_image_or_video_msg_by_appium(appium_server_url: str, device_name: str, contact_name: str, top_n: int = 1):
    """
    发送消息到微信, 支持多条消息
    appium_server_url: Appium服务器URL
    device_name: 设备名称
    contact_name: 联系人名称
    top_n: 发送的图片或视频数量
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
        
        wx_operator.send_top_n_image_or_video_msg(contact_name=contact_name, top_n=top_n)
    except Exception as e:
        print(f"[ERROR] 发送消息时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")
    finally:
        # 关闭操作器
        if wx_operator:
            wx_operator.close()

def get_wx_account_info_by_appium(appium_server_url: str, device_name: str, login_info: dict) -> dict:
    '''
        获取微信账号信息
        appium_server_url: Appium服务器URL
        device_name: 设备名称
        login_info: 登录信息

        return: wx_account_info: 微信账号信息
    '''
    # 获取消息
    wx_operator = None
    try:
        # 首先尝试不重启应用
        print("[INFO] 尝试不重启应用，检查当前是否在微信...")
        wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=False, login_info=login_info)
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
            wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=True, login_info=login_info)
            time.sleep(3)
        
        # 获取微信账号信息
        result = wx_operator.get_wx_account_info()

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

def search_contact_name(appium_server_url: str, device_name: str, contact_name: str, login_info: dict):
    try:
        wx_operator = WeChatOperator(appium_server_url=appium_server_url, device_name=device_name, force_app_launch=False)
        # 确保在微信主页面
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
        
        # 点击搜索按钮
        print("[1] 正在点击搜索按钮...")
        search_btn = WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "搜索"))
        )
        search_btn.click()
        print("[1] 点击搜索按钮成功")
            
        # 输入联系人名称
        print("[2] 正在输入联系人名称...")
        search_input = WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.EditText[@text='搜索']"))
        )
        search_input.send_keys(contact_name)
        print("[2] 输入联系人名称成功")

        # 点击联系人
        print("[3] 正在点击联系人...")
        contact = WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((
                AppiumBy.XPATH,
                f"//android.widget.TextView[@text='{contact_name}']"
            ))
        )
        contact.click()
        print("[3] 成功进入联系人聊天界面")
        print("[4] 正在点击“更多信息”按钮...")
        more_info_btn = WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.ImageView[@content-desc='更多信息']"))
        )
        more_info_btn.click()
        print("[4] 点击“更多信息”按钮成功")

        detail=WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((AppiumBy.XPATH, f"//android.widget.TextView[@text='{contact_name}']"))
        )
        detail.click()
        print("[5] 点击“细节信息”成功")

        print("[6] 正在点击朋友圈...")
        friend_circle_btn = WebDriverWait(wx_operator.driver, 10).until(
            EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.TextView[@text='朋友圈']"))
        )
        friend_circle_btn.click()
        print("[6] 点击朋友圈成功")

        # 获取要用的login_info
        WX_CONFIG_LIST = Variable.get("WX_CONFIG_LIST", deserialize_json=True)
        for wx_config in WX_CONFIG_LIST:
            if wx_config['appium_url'] == appium_server_url:
                login_info = wx_config['login_info']
                print(login_info)
                break

        print("[7] 正在分析朋友圈...")
        
        # 朋友圈分析条数限制，默认为10条
        max_posts_limit = 10
        processed_posts = 0
        all_dify_img_info_list = []
        all_dify_text_info_list = []
        

        after_scroll_page_source=''    
        while processed_posts < max_posts_limit:
            # 获取当前页面的朋友圈内容
            friend_circle_details = wx_operator.driver.find_elements(AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.tencent.mm:id/n9w']")
            frien_circle_texts = wx_operator.driver.find_elements(AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.tencent.mm:id/cut']")
            
            current_page_posts = len(friend_circle_details)
            print(f"当前页面朋友圈视频图片-数量: {current_page_posts}")
            
            if current_page_posts == 0:
                print("[INFO] 当前页面没有更多朋友圈内容，结束分析")
                break
            
            # 计算本次处理的条数
            posts_to_process = min(current_page_posts, max_posts_limit - processed_posts)
            
            dify_img_info_list = []
            dify_text_info_list = []
            
            # 处理当前页面的朋友圈内容（限制条数）
            actual_processed_count = 0  # 实际处理的媒体内容计数
            
            for i in range(posts_to_process):
                detail = friend_circle_details[i]
                
                content_desc = detail.get_attribute('content-desc')
                print(f"详情[{processed_posts + actual_processed_count + 1}]: {content_desc}")
                dify_text_info_list.append(content_desc)
     
                # 分类处理
                if content_desc:
                    # 优化数据清洗逻辑，处理中文逗号和英文逗号
                    content = content_desc
                    media_type = "未知类型"
                    
                    # 检查是否包含媒体类型标识
                    media_indicators = ["包含一张图片", "包含多张图片", "包含一条小视频"]
                    
                    for indicator in media_indicators:
                        if indicator in content_desc:
                            # 找到媒体类型标识的位置
                            indicator_pos = content_desc.find(indicator)
                            
                            # 提取内容部分（媒体标识之前的部分）
                            content = content_desc[:indicator_pos].strip()
                            
                            # 移除内容末尾的逗号（中文或英文）
                            if content.endswith("，") or content.endswith(","):
                                content = content[:-1].strip()
                            
                            # 设置媒体类型
                            media_type = indicator
                            break
                    
                    print(f'类型：{media_type}')
                    if "包含一张图片" in media_type:
                        print(f"[INFO] 发现单张图片内容: {content}")
                        dify_img_info = deal_picture(wx_operator, login_info, detail, content, contact_name, device_name)
                        print("单张图片到dify_img_info:", dify_img_info)
                        if dify_img_info:
                            dify_img_info_list.append(dify_img_info)
                            actual_processed_count += 1  # 实际处理计数+1

                    elif "包含多张图片" in media_type:
                        print(f"[INFO] 发现多张图片内容: {content}")
                        # deal_pictures(wx_operator,login_info, detail, content,contact_name,device_name)
                        # actual_processed_count += 1  # 实际处理计数+1

                    elif "包含一条小视频" in media_type:
                        print(f"[INFO] 发现视频内容: {content}")
                        # dify_img_info=deal_video(wx_operator,login_info, detail, content,contact_name,device_name)
                        # print("单个视频到dify_img_info:",dify_img_info)
                        # dify_img_info_list.append(dify_img_info)
                        # actual_processed_count += 1  # 实际处理计数+1
                    else:
                        print(f"[INFO] 未知类型内容: {content_desc}")
                
                # 检查是否已达到实际处理限制
                if actual_processed_count >= max_posts_limit:
                    print(f"[INFO] 已达到实际处理限制({max_posts_limit}条)，停止当前页面处理")
                    break
            
            # 处理当前页面的文本内容（限制条数）
            current_page_texts = min(len(frien_circle_texts), len(dify_text_info_list))
            print(f"当前页面朋友圈文本-数量: {current_page_texts}")
            for i in range(current_page_texts):
                if i < len(frien_circle_texts):
                    text = frien_circle_texts[i]
                    content = text.text
                    # 避免重复添加相同的文本内容
                    if content and content not in dify_text_info_list:
                        dify_text_info_list.append(content)
            
            # 累加到总列表
            all_dify_img_info_list.extend(dify_img_info_list)
            all_dify_text_info_list.extend(dify_text_info_list)
            
            processed_posts += actual_processed_count  # 只累加实际处理的媒体内容数量
            print(f"已实际处理朋友圈媒体条数: {processed_posts}/{max_posts_limit}")
            # 获取翻页前源码
            before_scroll_page_source = wx_operator.driver.page_source
            # 如果已达到限制条数，分析当前批次
            if processed_posts >= max_posts_limit or before_scroll_page_source==after_scroll_page_source:
                print(f"已达到实际处理条数限制({max_posts_limit}条),或者已无朋友圈可收集，开始分析...")
                print("dify_text_info_list:", all_dify_text_info_list, "dify_img_info_list:", all_dify_img_info_list)
                upload_file_text_to_dify(contact_name, all_dify_text_info_list, all_dify_img_info_list)
                break
            
            
            # 如果还没达到限制条数，向下滑动页面加载更多内容
            if processed_posts < max_posts_limit:
                print("[INFO] 向下滑动页面加载更多朋友圈内容...")
                try:
                   wx_operator.scroll_down(0.8,0.1)
                   
                   time.sleep(0.5)
                   after_scroll_page_source=wx_operator.driver.page_source
                except Exception as e:
                    print(f"[WARNING] 页面滑动失败: {str(e)}")
                    break

        print("[7] 分析朋友圈成功")

    except Exception as e:
        print(f"[ERROR] 搜索联系人时出错: {str(e)}")
        import traceback
        print(f"[ERROR] 详细错误堆栈:\n{traceback.format_exc()}")


def deal_picture(wx_operator: WeChatOperator,login_info: dict, detail, content: str,contact_name: str,device_name: str):
    # 获取屏幕尺寸和元素位置
    
    screen_size = wx_operator.driver.get_window_size()
    element_location = detail.location
    screen_height = screen_size['height']
    element_y = element_location['y']

    # 检查元素是否位于屏幕高度的3/4以上
    if element_y > screen_height * 0.25:
        # 点击标题元素而不是整个卡片
        print("处理图片类型内容:",content)
        detail.click()
        time.sleep(1)

        # 点击朋友圈页面的图片
        img_elem = wx_operator.driver.find_element(
                    by=AppiumBy.XPATH,
                    value=".//android.view.View[@content-desc='图片'][@resource-id='com.tencent.mm:id/q3']"
                )
        # 保存图片到手机
        print(f"[INFO] 正在保存图片...")
        try:
            img_elem.click()
            time.sleep(0.5)
            touch_elem=None
            elems = wx_operator.driver.find_elements(
                by=AppiumBy.XPATH,
                value="//*[contains(@content-desc, '第1页共1页，轻触两下关闭图片')]"
            )
            if elems:
                touch_elem = elems[0]
            else:
                # 可以尝试更宽泛的匹配
                elems = wx_operator.driver.find_elements(
                    by=AppiumBy.XPATH,
                    value="//*[contains(@content-desc, '轻触两下关闭图片')]"
                )
                if elems:
                    touch_elem = elems[0]
                else:
                    print("[ERROR] 找不到关闭图片的元素")
                    touch_elem = None
            
            touch_elem_rect = touch_elem.rect
            print("touch_elem_rect:",touch_elem_rect)
            x = touch_elem_rect['x'] + touch_elem_rect['width'] / 2
            y = touch_elem_rect['y'] + touch_elem_rect['height'] / 2
            
            wx_operator.driver.execute_script('mobile: longClickGesture', {
                'x': x,
                'y': y,
                'duration': 1500
            })
            WebDriverWait(wx_operator.driver, 60). \
                until(EC.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="保存图片"]'))).click()
            print(f"[INFO] 图片保存成功")
            time.sleep(1)
            touch_elem.click()
        except Exception as e:
            print(f"[ERROR] 保存图片失败: {e}")
            
        # 处理图片到dify上并返回dify文件信息
        # 1. 图片传递
        local_path = transfer_single_image_from_device(login_info, device_name)

        # 2. 上传图片到Dify
        dify_agent = DifyAgent(api_key=Variable.get("WX_FRIEND_CIRCLE_ANALYSIS"), base_url=Variable.get("DIFY_BASE_URL"))
        dify_user_id = f"wxid_{contact_name}"
        try:
            dify_img_info = dify_agent.upload_file(local_path, dify_user_id)
            print(f"[INFO] 上传图片到Dify成功: {dify_img_info}")
        
        except Exception as e:
            print(f"[ERROR] 上传图片到Dify失败: {e}")

        #返回朋友圈列表
        wx_operator.driver.press_keycode(4)
        return dify_img_info



def deal_video(wx_operator: WeChatOperator,login_info: dict, detail, content: str,contact_name: str,device_name: str):
    print("处理视频类型内容:",content)
    detail.click()
    time.sleep(1)

    # 点击朋友圈页面的视频
    img_elem = wx_operator.driver.find_element(
                by=AppiumBy.XPATH,
                value="//android.view.View[@resource-id='com.tencent.mm:id/h88']"
            )
    # 保存视频到手机
    print(f"[INFO] 正在保存视频...")
    try:
        img_elem.click()
        time.sleep(0.5)
        touch_elem=None
        elems = wx_operator.driver.find_elements(
            by=AppiumBy.XPATH,
            value="//android.view.View"
        )
        if elems:
            touch_elem = elems[0]
        else:
            # 可以尝试更宽泛的匹配
            elems = wx_operator.driver.find_elements(
                by=AppiumBy.XPATH,
                value="//android.widget.RelativeLayout[@content-desc='视频]"
            )
            if elems:
                touch_elem = elems[0]
            else:
                print("[ERROR] 找不到关闭图片的元素")
                touch_elem = None
        
        touch_elem_rect = touch_elem.rect
        print("touch_elem_rect:",touch_elem_rect)
        x = touch_elem_rect['x'] + touch_elem_rect['width'] / 2
        y = touch_elem_rect['y'] + touch_elem_rect['height'] / 2
        
        wx_operator.driver.execute_script('mobile: longClickGesture', {
            'x': x,
            'y': y,
            'duration': 1500
        })
        WebDriverWait(wx_operator.driver, 60). \
            until(EC.presence_of_element_located((AppiumBy.XPATH, f'//*[@text="保存视频"]'))).click()
        print(f"[INFO] 视频保存成功")
        touch_elem.click()
    except Exception as e:
        print(f"[ERROR] 保存视频失败: {e}")
        
    # 处理图片到dify上并返回dify文件信息
    # 1. 图片传递
    local_path = transfer_single_image_from_device(login_info, device_name)

    # 2. 上传图片到Dify
    dify_agent = DifyAgent(api_key=Variable.get("WX_FRIEND_CIRCLE_ANALYSIS"), base_url=Variable.get("DIFY_BASE_URL"))
    dify_user_id = f"wxid_{contact_name}"
    try:
        dify_img_info = dify_agent.upload_file(local_path, dify_user_id)
        print(f"[INFO] 上传视频到Dify成功: {dify_img_info}")
    
    except Exception as e:
        print(f"[ERROR] 上传视频到Dify失败: {e}")

    #返回朋友圈列表
    wx_operator.driver.press_keycode(4)
    return dify_img_info

def transfer_single_image_from_device(login_info: dict, device_name: str):
    device_ip = login_info["device_ip"]
    username = login_info["username"]
    password = login_info["password"]
    port = login_info["port"]
    device_serial = device_name

    # 获取手机上的图片路径
    image_path = get_image_path(device_ip, username, password, device_serial, port=port)

    # 在主机上从手机上pull图片
    directory_path = image_path
    image_name = os.path.basename(directory_path)
    local_path = f"/tmp/image_downloads/{image_name}"
    print(f"[INFO] 从手机上pull图片: {local_path}")
    pull_image_from_device(device_ip, username, password, device_serial, directory_path, local_path, port=port)

    # 主机传递到服务器
    download_file_via_sftp(device_ip, username, password, local_path, local_path, port=port)
    print(f"[HANDLE] 下载图片到本地: {local_path}")
    return local_path

def upload_file_text_to_dify(contact_name:str,dify_text_info_list:list,dify_img_info_list:list):
    dify_files = []
    for dify_img_info in dify_img_info_list:
        dify_files.append({
            "type": "image" ,
            "transfer_method": "local_file",
            "upload_file_id": dify_img_info.get("id", "")
        })
    text_query="\n".join(item for item in dify_text_info_list)

    dify_agent = DifyAgent(api_key=Variable.get("WX_FRIEND_CIRCLE_ANALYSIS"), base_url=Variable.get("DIFY_BASE_URL"))
    dify_user_id = f"wxid_{contact_name}"
    try:
        print(f"[WATCHER] 开始获取AI回复")
        full_answer, metadata = dify_agent.create_chat_message_stream(
                query=text_query,
                user_id=dify_user_id,
                conversation_id=None,
                files=dify_files,
                inputs={}
            )
    except Exception as e:
        raise
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    return metadata
    
def identify_friend_circle_content(appium_server_url: str, device_name: str, contact_name: str, login_info: dict):
    pass

def deal_pictures(wx_operator: WeChatOperator,login_info: dict, detail, content: str,contact_name: str,device_name: str):
    print("处理多张图片类型内容:",content)
    detail.click()
    time.sleep(1)
    wx_operator.print_all_elements()
    wx_operator.driver.press_keycode(4)

# 测试代码
if __name__ == "__main__":    
    # 获取Appium服务器URL
    appium_server_url = os.getenv('APPIUM_SERVER_URL', 'http://localhost:6025')
    print(appium_server_url)

    # 打印当前页面的XML结构
    wx1 = WeChatOperator(appium_server_url=appium_server_url, device_name='ZY22FX4H65', force_app_launch=False)

    try:
        # time.sleep(5)
        # print(wx.driver.page_source)
        # wx1.print_all_elements()

        wx1.agree_friend_request()
        
    except Exception as e:
        
        print(f"运行出错: {str(e)}")
    finally:
        # 关闭操作器
        wx1.close()
