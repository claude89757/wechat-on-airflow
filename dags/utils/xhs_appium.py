#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书自动化操作SDK
提供基于Appium的小红书自动化操作功能,包括:
- 自动搜索关键词
- 收集笔记内容
- 获取笔记详情等

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


class XHSOperator:
    def __init__(self, appium_server_url: str = 'http://localhost:4723', force_app_launch: bool = False):
        """
        初始化小红书操作器
        """
        capabilities = dict(
            platformName='Android',
            automationName='uiautomator2',
            deviceName='BH901V3R9E',
            appPackage='com.xingin.xhs',
            appActivity='com.xingin.xhs.index.v2.IndexActivityV2',
            noReset=True,  # 保留应用数据
            fullReset=False,  # 不完全重置
            forceAppLaunch=force_app_launch,  # 是否强制重启应用
            autoGrantPermissions=True,  # 自动授予权限
            newCommandTimeout=60,  # 命令超时时间
            unicodeKeyboard=True,  # 使用 Unicode 输入法
            resetKeyboard=True,  # 重置输入法
        )

        print('正在初始化小红书控制器...')
        self.driver: AppiumWebDriver = AppiumWebDriver(
            command_executor=appium_server_url,
            options=UiAutomator2Options().load_capabilities(capabilities)
        )
        print('控制器初始化完成。')
        
    def search_keyword(self, keyword: str, filters: dict = None):
        """
        搜索关键词并应用筛选条件
        Args:
            keyword: 要搜索的关键词
            filters: 筛选条件字典，可包含以下键值:
                sort_by: 排序方式 - '综合', '最新', '最多点赞', '最多评论', '最多收藏'
                note_type: 笔记类型 - '不限', '视频', '图文', '直播'
                time_range: 发布时间 - '不限', '一天内', '一周内', '半年内'
                search_scope: 搜索范围 - '不限', '已看过', '未看过', '已关注'
        """
        print(f"准备搜索关键词: {keyword}")
        try:
            # 通过 content-desc="搜索" 定位搜索按钮
            search_btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.Button[@content-desc='搜索']"))
            )
            search_btn.click()
            
            # 等待输入框出现并输入
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((AppiumBy.CLASS_NAME, "android.widget.EditText"))
            )
            search_input.send_keys(keyword)
            
            # 点击键盘上的搜索按钮
            self.driver.press_keycode(66)  # 66 是 Enter 键的 keycode
            print(f"已搜索关键词: {keyword}")
            
            # 等待搜索结果加载
            time.sleep(3)

            if filters:
                # 点击筛选按钮
                filter_btn = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.TextView[@text='筛选']"))
                )
                filter_btn.click()
                time.sleep(1)

                # 应用排序方式
                if filters.get('sort_by'):
                    sort_option = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            AppiumBy.XPATH, 
                            f"//android.widget.TextView[@text='{filters['sort_by']}']"
                        ))
                    )
                    sort_option.click()
                    time.sleep(0.5)

                # 应用笔记类型
                if filters.get('note_type'):
                    note_type = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            AppiumBy.XPATH, 
                            f"//android.widget.TextView[@text='{filters['note_type']}']"
                        ))
                    )
                    note_type.click()
                    time.sleep(0.5)

                # 应用发布时间
                if filters.get('time_range'):
                    time_range = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            AppiumBy.XPATH, 
                            f"//android.widget.TextView[@text='{filters['time_range']}']"
                        ))
                    )
                    time_range.click()
                    time.sleep(0.5)

                # 应用搜索范围
                if filters.get('search_scope'):
                    search_scope = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((
                            AppiumBy.XPATH, 
                            f"//android.widget.TextView[@text='{filters['search_scope']}']"
                        ))
                    )
                    search_scope.click()
                    time.sleep(0.5)

                # 点击收起按钮
                collapse_btn = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.XPATH, "//android.widget.TextView[@text='收起']"))
                )
                collapse_btn.click()
                time.sleep(1)

            print("筛选条件应用完成")
            
        except Exception as e:
            print(f"搜索或筛选失败: {str(e)}")
            raise
        
    def collect_notes_by_keyword(self, keyword: str, max_notes: int = 10, filters: dict = None, 
                                 include_comments: bool = False):
        """
        根据关键词收集笔记
        """
        # 搜索关键词
        print(f"搜索关键词: {keyword}")
        self.search_keyword(keyword, filters=filters)
        
        print(f"开始收集笔记,计划收集{max_notes}条...")
        notes = []
        while len(notes) < max_notes:
            # 获取所有笔记标题元素
            note_titles = self.driver.find_elements(
                by=AppiumBy.ID,
                value="com.xingin.xhs:id/g6_"
            )
            
            for note_element in note_titles:
                note_title = note_element.text
                if note_title not in notes:
                    print(f"收集笔记: {note_title}, 当前收集数量: {len(notes)}")

                    # 点击笔记
                    note_element.click()
                    time.sleep(1)

                    # 获取笔记内容
                    note_data = self.get_note_data(note_title, include_comments)
                    notes.append(note_data)

                    # 返回上一页
                    self.driver.press_keycode(4)  # Android 返回键
                    time.sleep(1)

                    if len(notes) >= max_notes:
                        break
                else:
                    print(f"笔记已收集过: {note_title}")
            
            # 滑动到下一页
            if len(notes) < max_notes:
                self.scroll_down()
                time.sleep(1)

        # 打印所有笔记数据
        for note in notes:
            print("-" * 120)
            print(json.dumps(note, ensure_ascii=False, indent=2))
            print("-" * 120)

        return notes
    
    def get_note_data(self, note_title: str, max_comments: int = 10, include_comments: bool = False):
        """
        获取笔记内容和评论
        Args:
            note_title: 笔记标题
            max_comments: 最大收集评论数，设为 None 则收集所有评论
        Returns:
            dict: 笔记数据
        """
        try:
            print(f"正在获取笔记内容: {note_title}")
            
            # 等待笔记内容加载
            time.sleep(1)
            
            # 获取笔记作者
            try:
                # 尝试查找作者元素
                author_element = None
                max_scroll_attempts = 3
                scroll_attempts = 0
                
                while not author_element and scroll_attempts < max_scroll_attempts:
                    try:
                        author_element = WebDriverWait(self.driver, 2).until(
                            EC.presence_of_element_located((AppiumBy.ID, "com.xingin.xhs:id/nickNameTV"))
                        )
                        print(f"找到作者信息元素: {author_element.text}")
                        author = author_element.text
                        break
                    except:
                        # 向下滚动一小段距离
                        self.scroll_down()
                        scroll_attempts += 1
                        time.sleep(1)
                
                if not author_element:
                    author = ""
                    print("未找到作者信息元素")
                    
            except Exception as e:
                author = ""
                print(f"获取作者信息失败: {str(e)}")
            
            # 获取笔记内容 - 需要滑动查找
            content = ""
            max_scroll_attempts = 5  # 最大滑动次数
            scroll_count = 0
            
            while scroll_count < max_scroll_attempts:
                try:
                    # 尝试获取正文内容
                    content_element = self.driver.find_element(
                        by=AppiumBy.ID,
                        value="com.xingin.xhs:id/dod"
                    )
                    content = content_element.text
                    if content:
                        print("找到正文内容")
                        break
                except:
                    print(f"第 {scroll_count + 1} 次滑动查找正文...")
                    # 向下滑动
                    self.scroll_down()
                    time.sleep(0.5)
                    scroll_count += 1
            
            if not content:
                print("未找到正文内容，使用标题作为内容")
                content = ""
          
            # 获取互动数据 - 分别处理每个数据
            likes = "0"
            try:
                # 获取点赞数
                likes_btn = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[contains(@content-desc, '点赞')]"
                )
                likes_text = likes_btn.find_element(
                    by=AppiumBy.ID,
                    value="com.xingin.xhs:id/g5i"
                ).text
                # 如果获取到的是"点赞"文本，则设为0
                likes = "0" if likes_text == "点赞" else likes_text
            except Exception as e:
                print(f"获取点赞数失败: {str(e)}")

            collects = "0"
            try:
                # 获取收藏数
                collects_btn = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[contains(@content-desc, '收藏')]"
                )
                collects_text = collects_btn.find_element(
                    by=AppiumBy.ID,
                    value="com.xingin.xhs:id/g3s"
                ).text
                # 如果获取到的是"收藏"文本，则设为0
                collects = "0" if collects_text == "收藏" else collects_text
            except Exception as e:
                print(f"获取收藏数失败: {str(e)}")

            total_comments = "0"
            try:
                # 获取评论数
                comments_btn = self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.Button[contains(@content-desc, '评论')]"
                )
                comments_text = comments_btn.find_element(
                    by=AppiumBy.ID,
                    value="com.xingin.xhs:id/g41"
                ).text
                # 如果获取到的是"评论"文本，则设为0
                total_comments = "0" if comments_text == "评论" else comments_text
            except Exception as e:
                print(f"获取评论数失败: {str(e)}")
            
            # 收集评论数据
            comments = []
            if include_comments:
                print(f"\n开始收集评论 (目标数量: {max_comments})")
                print("-" * 50)
                if int(total_comments) > 0:
                    # 循环滑动收集评论
                    no_new_comments_count = 0  # 连续没有新评论的次数
                    max_no_new_comments = 3  # 最大连续无新评论次数
                    page_num = 1  # 当前页码
                    
                    while True:
                        print(f"\n正在处理第 {page_num} 页评论...")
                        
                        # 检查是否到底或无评论
                        try:
                            # 检查"还没有评论哦"文本
                            no_comments = self.driver.find_element(
                                by=AppiumBy.ID,
                                value="com.xingin.xhs:id/es1"
                            )
                            if no_comments.text in ["还没有评论哦", "- 到底了 -"]:
                                print(f">>> 遇到终止条件: {no_comments.text}")
                                break
                        except:
                            pass
                        
                        # 获取当前可见的评论元素
                        comment_elements = self.driver.find_elements(
                            by=AppiumBy.ID,
                            value="com.xingin.xhs:id/j9m"
                        )
                        print(f"当前页面发现 {len(comment_elements)} 条评论")
                        
                        current_page_has_new = False  # 当前页面是否有新评论
                        
                        for idx, comment_elem in enumerate(comment_elements, 1):
                            try:
                                # 只获取评论内容
                                comment_text = comment_elem.text
                                
                                # 检查评论内容是否已存在
                                if comment_text not in comments:
                                    comments.append(comment_text)
                                    current_page_has_new = True
                                    print(f"[{len(comments)}/{max_comments}] 新评论: {comment_text}")
                                    
                                    # 检查是否达到最大评论数
                                    if max_comments and len(comments) >= max_comments:
                                        print(">>> 已达到目标评论数量")
                                        break
                            except Exception as e:
                                print(f"处理第 {idx} 条评论出错: {str(e)}")
                                continue
                        
                        # 如果达到最大评论数，退出循环
                        if max_comments and len(comments) >= max_comments:
                            break
                            
                        # 如果当前页面有新评论，重置计数器
                        if current_page_has_new:
                            print(f"第 {page_num} 页发现新评论，继续收集")
                            no_new_comments_count = 0
                        else:
                            no_new_comments_count += 1
                            print(f"第 {page_num} 页未发现新评论 ({no_new_comments_count}/{max_no_new_comments})")
                        
                        # 如果连续多次没有新评论，认为已到底
                        if no_new_comments_count >= max_no_new_comments:
                            print(">>> 连续多次未发现新评论，停止收集")
                            break
                        
                        # 向下滑动
                        print("向下滑动加载更多评论...")
                        self.scroll_down()
                        time.sleep(0.5)
                        page_num += 1
                    
                    # 返回笔记详情页
                    print("\n评论收集完成，返回笔记详情页")
                print(f"共收集到 {len(comments)} 条评论")
                print("-" * 50)
            else:
                print("不收集评论")

            # 5. 最后获取分享链接
            note_link = ""
            try:
                # 点击分享按钮
                share_btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.Button[@content-desc='分享']"
                    ))
                )
                share_btn.click()
                time.sleep(1)
                
                # 点击复制链接
                copy_link_btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((
                        AppiumBy.XPATH,
                        "//android.widget.TextView[@text='复制链接']"
                    ))
                )
                copy_link_btn.click()
                time.sleep(1)
                
                # 获取剪贴板内容
                clipboard_data = self.driver.get_clipboard_text()
                note_link = clipboard_data.strip()
                # 从分享文本中提取URL
                url_start = note_link.find('http://')
                url_end = note_link.find('，', url_start)
                if url_start != -1 and url_end != -1:
                    note_url = note_link[url_start:url_end]
                    print(f"提取到笔记URL: {note_url}")
                else:
                    note_url = note_link
                    print(f"未能从分享链接中提取URL: {note_link}")
            
            except Exception as e:
                print(f"获取分享链接失败: {str(e)}")
                note_url = ""

            note_data = {
                "title": note_title,
                "author": author,
                "content": content,
                "likes": int(likes),
                "collects": int(collects),
                "comments": comments,
                "note_link": note_url,
                "collect_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            return note_data
            
        except Exception as e:
            import traceback
            print(f"获取笔记内容失败: {str(e)}")
            print("异常堆栈信息:")
            print(traceback.format_exc())
            self.print_all_elements()
            return {
                "title": note_title,
                "error": str(e),
                "collect_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
    
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
            time.sleep(1)  # 等待内容加载
        except Exception as e:
            print(f"页面滑动失败: {str(e)}")
            raise
        
    def return_to_home_page(self):
        """
        返回小红书首页
        """
        try:
            # 尝试点击返回按钮直到回到首页
            max_attempts = 6
            for _ in range(max_attempts):
                try:
                    # 使用更通用的定位方式
                    back_btn = self.driver.find_element(
                        by=AppiumBy.XPATH,
                        value="//android.widget.ImageView[@content-desc='返回']"
                    )
                    back_btn.click()
                    time.sleep(0.5)
                    
                    # 检查是否已经回到首页
                    if self.is_at_xhs_home_page():
                        print("已返回首页")
                        return
                except:
                    break
            
            # 通过点击首页按钮返回首页
            try:
                home_btn =self.driver.find_element(
                    by=AppiumBy.XPATH,
                    value="//android.widget.TextView[contains(@text, '首页')]"
                )
                home_btn.click()
                time.sleep(0.5)
                if self.is_at_xhs_home_page():
                    print("已返回首页")
                    return
            except:
                pass
                
            # 如果还没回到首页，使用Android返回键
            self.driver.press_keycode(4)
            time.sleep(0.5)
            
            if not self.is_at_xhs_home_page():
                raise Exception("无法返回首页")
            
        except Exception as e:
            print(f"返回首页失败: {str(e)}")
            raise
            
    def is_at_xhs_home_page(self):
        """
        检查是否在首页
        """
        try:
            # 检查首页特有元素
            elements = [
                "//android.widget.TextView[contains(@text, '首页')]",
                "//android.widget.TextView[contains(@text, '发现')]",
                "//android.widget.TextView[contains(@text, '关注')]",
                "//android.widget.TextView[contains(@text, '购物')]",
                "//android.widget.TextView[contains(@text, '消息')]"
            ]
            
            for xpath in elements:
                self.driver.find_element(AppiumBy.XPATH, xpath)
            return True
        except:
            return False
        
    def save_notes(self, notes: list, output_file: str):
        """
        保存笔记到文件
        Args:
            notes: 笔记列表
            output_file: 输出文件路径
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(notes, f, ensure_ascii=False, indent=2)
            print(f"笔记已保存到: {output_file}")
        except Exception as e:
            print(f"保存笔记失败: {str(e)}")
            raise
        
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

    def find_elements_by_resource_id(self, resource_id: str):
        """
        查找笔记元素
        """
        # 获取页面源码并解析
        root = ElementTree.fromstring(self.driver.page_source)
        
        # 查找所有匹配resource-id的元素
        note_elements = []
        for element in root.findall(".//*"):
            if element.attrib.get('resource-id') == resource_id:
                note_elements.append(element)
        return note_elements
    
    def print_xml_structure(self):
        """
        打印当前页面的XML结构,便于分析页面层级
        """
        # 获取页面源码
        page_source = self.driver.page_source
        
        # 解析XML
        root = ElementTree.fromstring(page_source)
        
        def print_element(element, level=0):
            # 打印当前元素
            indent = "  " * level
            attrs = element.attrib
            class_name = attrs.get('class', '')
            text = attrs.get('text', '')
            resource_id = attrs.get('resource-id', '')
            
            # 构建元素描述
            element_desc = f"{class_name}"
            if text:
                element_desc += f" [text='{text}']"
            if resource_id:
                element_desc += f" [id='{resource_id}']"
                
            print(f"{indent}├─ {element_desc}")
            
            # 递归打印子元素
            for child in element:
                print_element(child, level + 1)
                
        print("\n页面XML结构:")
        print("根节点")
        print_element(root)
    
    def close(self):
        """
        关闭小红书操作器
        """
        if self.driver:
            self.driver.quit()
            print('控制器已关闭。')

    def scroll_in_element(self, element):
        """
        在指定元素内滑动
        """
        try:
            # 获取元素位置和大小
            location = element.location
            size = element.size
            
            # 计算滑动起点和终点
            start_x = location['x'] + size['width'] * 0.5
            start_y = location['y'] + size['height'] * 0.8
            end_y = location['y'] + size['height'] * 0.2
            
            # 执行滑动
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            time.sleep(0.5)  # 等待内容加载
        except Exception as e:
            print(f"元素内滑动失败: {str(e)}")
            raise

    def scroll_to_bottom(self):
        """
        滑动到页面底部
        """
        last_page_source = None
        max_attempts = 5
        attempts = 0
        
        while attempts < max_attempts:
            # 获取当前页面源码
            current_page_source = self.driver.page_source
            
            # 如果页面没有变化，说明已经到底
            if current_page_source == last_page_source:
                break
            
            # 保存当前页面源码
            last_page_source = current_page_source
            
            # 向下滑动
            self.scroll_down()
            time.sleep(0.5)
            attempts += 1

    def publish_note(self, title: str, content: str):
        """
        发布笔记
        """
        pass


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

    print(appium_server_url)
    
    # 初始化小红书操作器
    xhs = XHSOperator(appium_server_url=appium_server_url)

    xhs.print_all_elements()

    time.sleep(60)

    # # 检查是否在首页
    # if xhs.is_at_xhs_home_page():
    #     print("在首页")
    # else:
    #     # 重新进入首页
    #     xhs.return_to_home_page()
    #     if xhs.is_at_xhs_home_page():
    #         print("重新进入首页成功")
    #     else:
    #         raise Exception("重新进入首页失败")
    
    # try:
    #     notes = xhs.collect_notes_by_keyword("mac mini", max_notes=3)
    # except Exception as e:
    #     print(f"运行出错: {str(e)}")
    # finally:
    #     # 关闭操作器
    #     xhs.close()
