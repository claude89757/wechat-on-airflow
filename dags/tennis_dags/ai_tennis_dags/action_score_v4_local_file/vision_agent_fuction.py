#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import math
import cv2
from datetime import datetime
from pillow_heif import register_heif_opener
import time
import random
from contextlib import contextmanager

# 设置Vision Agent需要的环境变量
# 需要用户设置以下环境变量来解决认证问题：
# export VISION_AGENT_API_KEY="your-api-key"
# 或者 export ANTHROPIC_API_KEY="your-api-key"
# 或者 export GOOGLE_API_KEY="your-api-key"

def check_and_set_default_env():
    """
    检查并设置Vision Agent所需的环境变量
    如果没有设置必要的API密钥，会给出详细的错误提示
    """
    # 检查是否设置了任何必要的API密钥
    vision_agent_key = os.getenv('VISION_AGENT_API_KEY')
    anthropic_key = os.getenv('ANTHROPIC_API_KEY')
    google_key = os.getenv('GOOGLE_API_KEY')
    openai_key = os.getenv('OPENAI_API_KEY')
    
    if not any([vision_agent_key, anthropic_key, google_key, openai_key]):
        print("\n" + "="*80)
        print("❌ 错误：未找到Vision Agent所需的API密钥！")
        print("="*80)
        print("Vision Agent需要以下任一API密钥进行认证：")
        print()
        print("1. Vision Agent API密钥（推荐）：")
        print("   export VISION_AGENT_API_KEY='your-vision-agent-api-key'")
        print("   获取地址：https://support.landing.ai/docs/visionagent")
        print()
        print("2. Anthropic API密钥：")
        print("   export ANTHROPIC_API_KEY='your-anthropic-api-key'")
        print("   获取地址：https://console.anthropic.com/settings/keys")
        print()
        print("3. Google API密钥：")
        print("   export GOOGLE_API_KEY='your-google-api-key'")
        print("   获取地址：https://aistudio.google.com/")
        print()
        print("4. OpenAI API密钥：")
        print("   export OPENAI_API_KEY='your-openai-api-key'")
        print("   获取地址：https://platform.openai.com/api-keys")
        print()
        print("请设置以上任一环境变量后重试。")
        print("="*80)
        raise ValueError("缺少Vision Agent API认证密钥")
    
    # 输出当前设置的密钥状态（仅显示是否设置，不显示实际值）
    print("\n" + "="*50)
    print("🔑 API密钥状态检查：")
    print("="*50)
    print(f"VISION_AGENT_API_KEY: {'✅ 已设置' if vision_agent_key else '❌ 未设置'}")
    print(f"ANTHROPIC_API_KEY: {'✅ 已设置' if anthropic_key else '❌ 未设置'}")
    print(f"GOOGLE_API_KEY: {'✅ 已设置' if google_key else '❌ 未设置'}")
    print(f"OPENAI_API_KEY: {'✅ 已设置' if openai_key else '❌ 未设置'}")
    print("="*50)

# 在导入vision_agent之前检查环境变量
check_and_set_default_env()

# 添加重试装饰器
def retry_with_backoff(max_retries=3, base_delay=1, max_delay=60):
    """
    重试装饰器，用于处理速率限制和网络错误
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e).lower()
                    
                    # 检查是否是速率限制错误
                    if "rate limit" in error_msg or "429" in error_msg:
                        if attempt < max_retries - 1:
                            # 指数退避 + 随机抖动
                            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                            print(f"⚠️ 遇到速率限制，{delay:.1f}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                            continue
                    
                    # 检查是否是网络连接错误
                    if "ssl" in error_msg or "connection" in error_msg:
                        if attempt < max_retries - 1:
                            delay = base_delay + random.uniform(0, 2)
                            print(f"⚠️ 网络连接问题，{delay:.1f}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                            continue
                    
                    # 其他错误直接抛出
                    raise e
            
            # 所有重试都失败了
            raise Exception(f"在{max_retries}次尝试后仍然失败: {str(e)}")
        
        return wrapper
    return decorator

def process_tennis_video(video_path: str, output_dir: str) -> dict:
    """
    Processes a tennis video to find a complete stroke that includes
    a contact moment between the player's tennis racket and the moving ball. 
    It returns a dictionary with paths to three key frames (preparation, contact, follow) 
    and the path to the short stroke video clip.

    Parameters
    ----------
    video_path : str
        The path to the tennis video file.

    Returns
    -------
    dict
        A dictionary containing:
        {
            "preparation_frame": str,
            "contact_frame": str,
            "follow_frame": str,
            "one_action_video": str,
            "slow_action_video": str
        }
    """
    import os
    import math
    import cv2
    from datetime import datetime
    from pillow_heif import register_heif_opener
    from vision_agent.tools import (
        extract_frames_and_timestamps,
        save_image,
        save_video,
        overlay_bounding_boxes,
        owlv2_sam2_video_tracking
    )

    register_heif_opener()

    # 创建唯一的输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"===== 开始处理网球视频: {video_path} =====")
    print(f"输出结果将保存在目录: {output_dir}")

    #########################################
    # 辅助函数定义
    #########################################
    
    # ===== 基础工具函数 =====

    # ===== 保存包含原始检测结果的视频 =====
    def save_video_with_raw_detections(output_dir: str, frames_list: list, ball_tracked: list, racket_tracked: list, player_tracked: list):
        """
        保存包含原始检测结果的视频
        """              
        # 生成网球检测结果视频
        print("  正在生成网球检测结果视频...")
        ball_frames = frames_list.copy()
        
        # 遍历所有帧，添加检测框
        for i, frame in enumerate(ball_frames):
            boxes = []
            # 查找当前帧的检测结果 - 直接使用帧索引访问检测结果
            if i < len(ball_tracked):
                for detection in ball_tracked[i]:
                    # 获取置信度分数，如果不存在则使用默认值0
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],  # 使用"bbox"键，而不是"box"
                        "label": "Tennis Ball",
                        "color": (0, 255, 0),  # 绿色
                        "score": score  # 添加score键
                    })
            # 将检测框叠加到帧上
            if boxes:
                ball_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存网球检测视频
        ball_video_path = os.path.join(output_dir, "ball_detection.mp4")
        save_video(ball_frames, ball_video_path, fps=30)
        print(f"  网球检测视频已保存至: {ball_video_path}")
        
        # 生成网球拍检测结果视频
        print("  正在生成网球拍检测结果视频...")
        racket_frames = frames_list.copy()
        
        # 遍历所有帧，添加检测框
        for i, frame in enumerate(racket_frames):
            boxes = []
            # 查找当前帧的检测结果 - 直接使用帧索引访问检测结果
            if i < len(racket_tracked):
                for detection in racket_tracked[i]:
                    # 获取置信度分数，如果不存在则使用默认值0
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],  # 使用"bbox"键，而不是"box"
                        "label": "Tennis Racket",
                        "color": (0, 0, 255),  # 红色
                        "score": score  # 添加score键
                    })
            # 将检测框叠加到帧上
            if boxes:
                racket_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存网球拍检测视频
        racket_video_path = os.path.join(output_dir, "racket_detection.mp4")
        save_video(racket_frames, racket_video_path, fps=30)
        print(f"  网球拍检测视频已保存至: {racket_video_path}")
        
        # 生成网球运动员检测视频
        player_frames = frames_list.copy()
        
        # 遍历所有帧，添加检测框
        for i, frame in enumerate(player_frames):
            boxes = []
            # 查找当前帧的检测结果 - 直接使用帧索引访问检测结果
            if i < len(player_tracked):
                for detection in player_tracked[i]:
                    # 获取置信度分数，如果不存在则使用默认值0
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],  # 使用"bbox"键，而不是"box"
                        "label": "Tennis Player",
                        "color": (0, 255, 0),  # 绿色
                        "score": score  # 添加score键
                    })
            # 将检测框叠加到帧上
            if boxes:
                player_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存网球运动员检测视频
        player_video_path = os.path.join(output_dir, "player_detection.mp4")
        save_video(player_frames, player_video_path, fps=30)
        print(f"  网球运动员检测视频已保存至: {player_video_path}")

    # ===== 保存包含过滤后的检测结果的视频 =====
    def save_video_with_filtered_detections(output_dir: str, frames_list: list, ball_tracked: list, racket_tracked: list, player_tracked: list):
        """
        保存包含过滤后的检测结果的视频
        """        
        # 生成叠加所有检测结果的综合视频
        print("  正在生成综合检测结果视频...")
        combined_frames = frames_list.copy()
        
        # 遍历所有帧，添加所有对象的检测框
        for i, frame in enumerate(combined_frames):
            boxes = []
            
            # 添加网球检测框
            if i < len(ball_tracked) and ball_tracked[i]:
                for detection in ball_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Ball {score:.2f}",
                        "color": (255, 255, 0),  # 黄色
                        "score": score
                    })
            
            # 添加球拍检测框
            if i < len(racket_tracked) and racket_tracked[i]:
                for detection in racket_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Racket {score:.2f}",
                        "color": (0, 0, 255),  # 红色
                        "score": score
                    })
            
            # 添加运动员检测框
            if i < len(player_tracked) and player_tracked[i]:
                for detection in player_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Player {score:.2f}",
                        "color": (0, 255, 0),  # 绿色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            if boxes:
                combined_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存综合检测视频，确保颜色正确
        combined_video_path = os.path.join(output_dir, "combined_detection.mp4")
        save_video(combined_frames, combined_video_path, fps=30)
        print(f"  综合检测视频已保存至: {combined_video_path}")
        
        # 生成仅包含网球的检测视频
        print("  正在生成网球检测结果视频...")
        ball_frames = frames_list.copy()
        
        # 遍历所有帧，添加网球检测框
        for i, frame in enumerate(ball_frames):
            boxes = []
            if i < len(ball_tracked) and ball_tracked[i]:
                for detection in ball_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Ball {score:.2f}",
                        "color": (255, 255, 0),  # 黄色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            if boxes:
                ball_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存网球检测视频，确保颜色正确
        ball_video_path = os.path.join(output_dir, "ball_detection_filtered.mp4")
        save_video(ball_frames, ball_video_path, fps=30)
        print(f"  过滤后的网球检测视频已保存至: {ball_video_path}")
        
        # 生成仅包含球拍的检测视频
        print("  正在生成球拍检测结果视频...")
        racket_frames = frames_list.copy()
        
        # 遍历所有帧，添加球拍检测框
        for i, frame in enumerate(racket_frames):
            boxes = []
            if i < len(racket_tracked) and racket_tracked[i]:
                for detection in racket_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Racket {score:.2f}",
                        "color": (0, 0, 255),  # 红色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            if boxes:
                racket_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存球拍检测视频，确保颜色正确
        racket_video_path = os.path.join(output_dir, "racket_detection_filtered.mp4")
        save_video(racket_frames, racket_video_path, fps=30)
        print(f"  过滤后的球拍检测视频已保存至: {racket_video_path}")
        
        # 生成仅包含运动员的检测视频
        print("  正在生成运动员检测结果视频...")
        player_frames = frames_list.copy()
        
        # 遍历所有帧，添加运动员检测框
        for i, frame in enumerate(player_frames):
            boxes = []
            if i < len(player_tracked) and player_tracked[i]:
                for detection in player_tracked[i]:
                    score = detection.get("score", 0)
                    boxes.append({
                        "bbox": detection["bbox"],
                        "label": f"Tennis Player {score:.2f}",
                        "color": (0, 255, 0),  # 绿色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            if boxes:
                player_frames[i] = overlay_bounding_boxes(frame, boxes)
        
        # 保存运动员检测视频，确保颜色正确
        player_video_path = os.path.join(output_dir, "player_detection_filtered.mp4")
        save_video(player_frames, player_video_path, fps=30)
        print(f"  过滤后的运动员检测视频已保存至: {player_video_path}")

    # ===== 过滤网球，仅保留一个网球 =====
    def filter_tennis_ball(ball_tracked: list, racket_tracked: list) -> list:
        """
        过滤网球，仅保留一个网球。要求：
        1. 保证运动轨迹连续的网球
        2. 一定过滤掉和网球拍重叠的网球

        Parameters:
        -----------
        ball_tracked: list
            owlv2_sam2_video_tracking返回的网球检测结果
        racket_tracked: list
            owlv2_sam2_video_tracking返回的网球拍检测结果
            
        Returns:
        --------
        list:
            过滤后的网球检测结果，每帧最多包含一个网球
        """
        # 输出基本信息
        print("\n开始处理网球检测结果...")
        print(f"总帧数: {len(ball_tracked)}")
        
        # 检查输入数据
        if not ball_tracked:
            print("警告: 网球检测数据为空")
            return []
        
        # 统计网球检测情况
        frames_with_balls = sum(1 for frame in ball_tracked if frame)
        total_balls = sum(len(frame) for frame in ball_tracked)
        print(f"检测到网球的帧数: {frames_with_balls}/{len(ball_tracked)}")
        print(f"检测到的网球总数: {total_balls}, 平均每帧: {total_balls/max(1, len(ball_tracked)):.2f}")
        
        # 初始化结果列表
        filtered_ball = [[] for _ in range(len(ball_tracked))]
        
        # 历史记录，用于维护轨迹连续性
        history_length = 8  # 保持多少帧的历史记录，网球移动快
        position_history = []  # 位置历史
        size_history = []      # 尺寸历史
        velocity_history = []  # 速度历史
        max_disappear_frames = 5  # 允许网球消失的最大帧数
        disappear_count = 0
        
        # 确定参考网球 - 找到一个好的轨迹起点
        # 寻找第一个具有良好置信度且不与球拍重叠的网球
        reference_frame_idx = None
        reference_ball = None
        
        for i in range(len(ball_tracked)):
            if not ball_tracked[i]:
                continue
                
            for ball in ball_tracked[i]:
                ball_center = [
                    (ball["bbox"][0] + ball["bbox"][2]) / 2,
                    (ball["bbox"][1] + ball["bbox"][3]) / 2
                ]
                
                # 检查是否与球拍重叠
                overlaps_with_racket = False
                
                if racket_tracked[i]:
                    for racket in racket_tracked[i]:
                        # 检查球的中心是否在球拍框内
                        if (ball_center[0] >= racket["bbox"][0] and 
                            ball_center[0] <= racket["bbox"][2] and
                            ball_center[1] >= racket["bbox"][1] and
                            ball_center[1] <= racket["bbox"][3]):
                            overlaps_with_racket = True
                            break
                
                # 如果不重叠并且有足够高的置信度
                confidence = ball.get("score", 0)
                if not overlaps_with_racket and confidence > 0.2:
                    reference_frame_idx = i
                    reference_ball = ball
                    filtered_ball[i] = [ball]
                    
                    # 记录初始历史
                    position_history = [ball_center] * history_length
                    
                    # 记录球的尺寸
                    ball_size = (
                        ball["bbox"][2] - ball["bbox"][0],  # 宽度
                        ball["bbox"][3] - ball["bbox"][1]   # 高度
                    )
                    size_history = [ball_size] * history_length
                    
                    # 初始化速度历史为零
                    velocity_history = [(0, 0)] * (history_length - 1)
                    
                    print(f"找到参考网球! 帧索引: {i}, 置信度: {confidence:.2f}")
                    break
            
            if reference_ball:
                break
        
        # 如果没找到参考网球，选择第一个检测到的网球
        if reference_ball is None:
            for i in range(len(ball_tracked)):
                if ball_tracked[i]:
                    reference_frame_idx = i
                    reference_ball = ball_tracked[i][0]
                    filtered_ball[i] = [reference_ball]
                    
                    # 记录网球中心位置
                    ball_center = [
                        (reference_ball["bbox"][0] + reference_ball["bbox"][2]) / 2,
                        (reference_ball["bbox"][1] + reference_ball["bbox"][3]) / 2
                    ]
                    position_history = [ball_center] * history_length
                    
                    # 记录球的尺寸
                    ball_size = (
                        reference_ball["bbox"][2] - reference_ball["bbox"][0],
                        reference_ball["bbox"][3] - reference_ball["bbox"][1]
                    )
                    size_history = [ball_size] * history_length
                    
                    # 初始化速度历史为零
                    velocity_history = [(0, 0)] * (history_length - 1)
                    
                    print(f"未找到高质量参考网球，使用第一个检测到的网球! 帧索引: {i}")
                    break
        
        # 如果仍然没有找到任何网球，返回空结果
        if reference_ball is None:
            print("错误: 未能找到任何网球！")
            return [[] for _ in range(len(ball_tracked))]
        
        # 前向遍历，从参考帧向后处理
        last_position = position_history[-1]
        last_velocity = velocity_history[-1] if velocity_history else (0, 0)
        
        for i in range(reference_frame_idx + 1, len(ball_tracked)):
            # 预测当前位置
            predicted_position = [
                last_position[0] + last_velocity[0],
                last_position[1] + last_velocity[1]
            ]
            
            # 如果当前帧没有检测到网球
            if not ball_tracked[i]:
                # 短时间内允许网球消失（可能被遮挡）
                if disappear_count < max_disappear_frames:
                    disappear_count += 1
                    filtered_ball[i] = []
                    
                    # 更新位置预测
                    last_position = predicted_position
                    # 保持速度不变，或根据物理规律调整（例如重力影响）
                    
                    # 可选: 使用预测的位置添加预测网球
                    # predicted_bbox = [...根据预测位置和历史尺寸生成预测边界框...]
                    # filtered_ball[i] = [{"bbox": predicted_bbox, "score": 0.5, "predicted": True}]
                else:
                    # 消失太长时间，停止跟踪
                    filtered_ball[i] = []
                continue
            
            # 有网球检测结果时，重置消失计数
            disappear_count = 0
            
            # 选择最佳网球
            best_ball = None
            best_score = -1
            
            for ball in ball_tracked[i]:
                ball_center = [
                    (ball["bbox"][0] + ball["bbox"][2]) / 2,
                    (ball["bbox"][1] + ball["bbox"][3]) / 2
                ]
                
                # 1. 检查与球拍重叠
                overlaps_with_racket = False
                if racket_tracked[i]:
                    for racket in racket_tracked[i]:
                        # 球的中心是否在球拍框内
                        if (ball_center[0] >= racket["bbox"][0] and 
                            ball_center[0] <= racket["bbox"][2] and
                            ball_center[1] >= racket["bbox"][1] and
                            ball_center[1] <= racket["bbox"][3]):
                            overlaps_with_racket = True
                            break
                
                # 如果与球拍重叠，跳过这个网球
                if overlaps_with_racket:
                    continue
                
                # 2. 计算与预测位置的接近度
                distance_to_prediction = math.sqrt(
                    (ball_center[0] - predicted_position[0])**2 + 
                    (ball_center[1] - predicted_position[1])**2
                )
                # 网球移动快，所以容忍较大的距离
                distance_score = 1.0 / (1.0 + 0.002 * distance_to_prediction)
                
                # 3. 检查尺寸一致性
                current_size = (
                    ball["bbox"][2] - ball["bbox"][0],
                    ball["bbox"][3] - ball["bbox"][1]
                )
                avg_size = [sum(s[0] for s in size_history) / len(size_history),
                           sum(s[1] for s in size_history) / len(size_history)]
                
                # 网球大小变化可能较大（远近效应），但比例应该相对稳定
                size_ratio = ((current_size[0] / avg_size[0]) + (current_size[1] / avg_size[1])) / 2
                size_score = 1.0 / (1.0 + abs(size_ratio - 1.0))
                
                # 4. 检查物理运动合理性
                if len(velocity_history) > 0:
                    # 计算新速度
                    new_velocity = (
                        ball_center[0] - last_position[0],
                        ball_center[1] - last_position[1]
                    )
                    
                    # 速度变化应该符合物理规律
                    velocity_change = math.sqrt(
                        (new_velocity[0] - last_velocity[0])**2 + 
                        (new_velocity[1] - last_velocity[1])**2
                    )
                    
                    # 网球可以有突然的速度变化（例如被击打时），所以容忍度较高
                    physics_score = 1.0 / (1.0 + 0.01 * velocity_change)
                else:
                    physics_score = 0.8  # 默认值
                
                # 5. 置信度分数
                confidence = ball.get("score", 0)
                
                # 综合评分
                total_score = (
                    0.35 * distance_score +  # 位置连续性最重要
                    0.15 * size_score +      # 尺寸次之
                    0.25 * physics_score +   # 物理运动合理性很重要
                    0.25 * confidence        # 检测置信度也重要
                )
                
                if total_score > best_score:
                    best_score = total_score
                    best_ball = ball
            
            # 添加选中的网球到结果
            if best_ball:
                filtered_ball[i] = [best_ball]
                
                # 更新历史记录
                ball_center = [
                    (best_ball["bbox"][0] + best_ball["bbox"][2]) / 2,
                    (best_ball["bbox"][1] + best_ball["bbox"][3]) / 2
                ]
                
                # 计算新速度
                new_velocity = (
                    ball_center[0] - last_position[0],
                    ball_center[1] - last_position[1]
                )
                
                # 更新历史
                position_history.append(ball_center)
                if len(position_history) > history_length:
                    position_history.pop(0)
                
                current_size = (
                    best_ball["bbox"][2] - best_ball["bbox"][0],
                    best_ball["bbox"][3] - best_ball["bbox"][1]
                )
                size_history.append(current_size)
                if len(size_history) > history_length:
                    size_history.pop(0)
                
                velocity_history.append(new_velocity)
                if len(velocity_history) > history_length - 1:
                    velocity_history.pop(0)
                
                # 更新最后的位置和速度
                last_position = ball_center
                last_velocity = new_velocity
            else:
                # 如果找不到符合条件的网球（例如全都与球拍重叠），则该帧没有网球
                filtered_ball[i] = []
        
        # 后向遍历，从参考帧向前处理
        last_position = position_history[0]  # 使用历史中最早的位置
        last_velocity = velocity_history[0] if velocity_history else (0, 0)  # 使用最早的速度，但需要反向
        last_velocity = (-last_velocity[0], -last_velocity[1])  # 反向速度
        
        for i in range(reference_frame_idx - 1, -1, -1):
            # 预测当前位置（后向）
            predicted_position = [
                last_position[0] + last_velocity[0],
                last_position[1] + last_velocity[1]
            ]
            
            # 如果当前帧没有检测到网球
            if not ball_tracked[i]:
                # 短时间内允许网球消失
                if disappear_count < max_disappear_frames:
                    disappear_count += 1
                    filtered_ball[i] = []
                    
                    # 更新位置预测
                    last_position = predicted_position
                else:
                    # 消失太长时间，停止跟踪
                    filtered_ball[i] = []
                continue
            
            # 有网球检测结果时，重置消失计数
            disappear_count = 0
            
            # 选择最佳网球
            best_ball = None
            best_score = -1
            
            for ball in ball_tracked[i]:
                ball_center = [
                    (ball["bbox"][0] + ball["bbox"][2]) / 2,
                    (ball["bbox"][1] + ball["bbox"][3]) / 2
                ]
                
                # 1. 检查与球拍重叠
                overlaps_with_racket = False
                if racket_tracked[i]:
                    for racket in racket_tracked[i]:
                        if (ball_center[0] >= racket["bbox"][0] and 
                            ball_center[0] <= racket["bbox"][2] and
                            ball_center[1] >= racket["bbox"][1] and
                            ball_center[1] <= racket["bbox"][3]):
                            overlaps_with_racket = True
                            break
                
                # 如果与球拍重叠，跳过这个网球
                if overlaps_with_racket:
                    continue
                
                # 2. 计算与预测位置的接近度
                distance_to_prediction = math.sqrt(
                    (ball_center[0] - predicted_position[0])**2 + 
                    (ball_center[1] - predicted_position[1])**2
                )
                distance_score = 1.0 / (1.0 + 0.002 * distance_to_prediction)
                
                # 3. 检查尺寸一致性
                current_size = (
                    ball["bbox"][2] - ball["bbox"][0],
                    ball["bbox"][3] - ball["bbox"][1]
                )
                size_ratio = (
                    (current_size[0] / size_history[0][0]) + 
                    (current_size[1] / size_history[0][1])
                ) / 2
                size_score = 1.0 / (1.0 + abs(size_ratio - 1.0))
                
                # 4. 检查物理运动合理性（后向）
                if len(velocity_history) > 0:
                    # 计算新速度（后向）
                    new_velocity = (
                        ball_center[0] - last_position[0],
                        ball_center[1] - last_position[1]
                    )
                    
                    # 速度变化应该符合物理规律
                    velocity_change = math.sqrt(
                        (new_velocity[0] - last_velocity[0])**2 + 
                        (new_velocity[1] - last_velocity[1])**2
                    )
                    physics_score = 1.0 / (1.0 + 0.01 * velocity_change)
                else:
                    physics_score = 0.8  # 默认值
                
                # 5. 置信度分数
                confidence = ball.get("score", 0)
                
                # 综合评分
                total_score = (
                    0.35 * distance_score + 
                    0.15 * size_score + 
                    0.25 * physics_score + 
                    0.25 * confidence
                )
                
                if total_score > best_score:
                    best_score = total_score
                    best_ball = ball
            
            # 添加选中的网球到结果
            if best_ball:
                filtered_ball[i] = [best_ball]
                
                # 更新历史记录（后向）
                ball_center = [
                    (best_ball["bbox"][0] + best_ball["bbox"][2]) / 2,
                    (best_ball["bbox"][1] + best_ball["bbox"][3]) / 2
                ]
                
                # 计算新速度（后向）
                new_velocity = (
                    ball_center[0] - last_position[0],
                    ball_center[1] - last_position[1]
                )
                
                # 更新位置和速度
                last_position = ball_center
                last_velocity = new_velocity
            else:
                # 如果找不到符合条件的网球，则该帧没有网球
                filtered_ball[i] = []
        
        # 统计过滤结果
        frames_with_filtered_balls = sum(1 for frame in filtered_ball if frame)
        print(f"过滤后有网球的帧数: {frames_with_filtered_balls}/{len(filtered_ball)}")
        
        return filtered_ball
    
    # ===== 过滤球拍，仅保留一个球拍 =====
    def filter_racket(racket_tracked: list, player_tracked: list) -> list:
        """
        过滤球拍，仅保留一个球拍。要求如下
        1. 选择和网球运动员距离较近的球拍
        2. 运动轨迹连续的球拍
        
        Parameters:
        -----------
        racket_tracked: list
            owlv2_sam2_video_tracking返回的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果，用于辅助球拍选择
            
        Returns:
        --------
        list:
            过滤后的球拍检测结果，每帧最多包含一个球拍
        """
        # 输出基本信息
        print("\n开始处理球拍检测结果...")
        print(f"总帧数: {len(racket_tracked)}")
        
        # 检查输入数据
        if not racket_tracked:
            print("警告: 球拍检测数据为空")
            return []
        
        # 统计球拍检测情况
        frames_with_rackets = sum(1 for frame in racket_tracked if frame)
        total_rackets = sum(len(frame) for frame in racket_tracked)
        print(f"检测到球拍的帧数: {frames_with_rackets}/{len(racket_tracked)}")
        print(f"检测到的球拍总数: {total_rackets}, 平均每帧: {total_rackets/len(racket_tracked):.2f}")
        
        # 初始化结果列表
        filtered_racket = [[] for _ in range(len(racket_tracked))]
        
        # 寻找合适的参考球拍
        reference_racket = None
        reference_frame_idx = None
        reference_racket_center = None
        
        # 首先尝试在有运动员的帧中寻找参考球拍
        for i in range(len(racket_tracked)):
            if racket_tracked[i] and player_tracked[i]:
                # 获取运动员中心位置
                player = player_tracked[i][0]
                player_center = [
                    (player["bbox"][0] + player["bbox"][2]) / 2,
                    (player["bbox"][1] + player["bbox"][3]) / 2
                ]
                
                # 获取运动员右侧边缘位置 (假设持拍手)
                player_right = player["bbox"][2]
                player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
                
                # 计算每个球拍到运动员的距离
                best_distance = float('inf')
                best_racket = None
                
                for racket in racket_tracked[i]:
                    # 计算球拍中心
                    racket_center = [
                        (racket["bbox"][0] + racket["bbox"][2]) / 2,
                        (racket["bbox"][1] + racket["bbox"][3]) / 2
                    ]
                    
                    # 计算到运动员右手的估计距离
                    hand_distance = math.sqrt(
                        (racket_center[0] - player_right)**2 + 
                        (racket_center[1] - player_middle_y)**2
                    )
                    
                    # 也考虑与运动员中心的距离
                    center_distance = math.sqrt(
                        (racket_center[0] - player_center[0])**2 + 
                        (racket_center[1] - player_center[1])**2
                    )
                    
                    # 综合距离 (偏重手部距离)
                    combined_distance = 0.7 * hand_distance + 0.3 * center_distance
                    
                    if combined_distance < best_distance:
                        best_distance = combined_distance
                        best_racket = racket
                
                if best_racket:
                    reference_racket = best_racket
                    reference_frame_idx = i
                    reference_racket_center = [
                        (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                        (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                    ]
                    filtered_racket[i] = [best_racket]
                    print(f"找到参考球拍! 帧索引: {i}, 距离: {best_distance:.2f}")
                    break
        
        # 如果没有找到参考球拍，尝试使用大小合适的球拍作为参考
        if reference_racket is None:
            print("未找到与运动员关联的球拍，尝试基于尺寸选择参考球拍...")
            for i in range(len(racket_tracked)):
                if racket_tracked[i]:
                    # 选择面积适中的球拍 (网球拍通常有一定尺寸)
                    best_racket = None
                    best_score = -1
                    
                    for racket in racket_tracked[i]:
                        width = racket["bbox"][2] - racket["bbox"][0]
                        height = racket["bbox"][3] - racket["bbox"][1]
                        area = width * height
                        
                        # 网球拍通常是长条状的，宽高比大约为 0.3-0.4
                        aspect_ratio = min(width, height) / max(width, height)
                        expected_ratio = 0.35
                        ratio_score = 1 - abs(aspect_ratio - expected_ratio)
                        
                        # 网球拍区域通常在一定范围内
                        # 假设理想区域是图像的 1/20 到 1/10
                        frame_area = 1920 * 1080  # 假设标准尺寸
                        expected_area = frame_area / 15
                        area_score = 1 - min(1, abs(area - expected_area) / expected_area)
                        
                        total_score = 0.6 * ratio_score + 0.4 * area_score
                        
                        if total_score > best_score:
                            best_score = total_score
                            best_racket = racket
                    
                    if best_racket and best_score > 0.7:  # 要求较高分数
                        reference_racket = best_racket
                        reference_frame_idx = i
                        reference_racket_center = [
                            (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                            (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                        ]
                        filtered_racket[i] = [best_racket]
                        print(f"找到基于尺寸的参考球拍! 帧索引: {i}, 分数: {best_score:.2f}")
                        break
        
        # 如果仍然没有找到参考球拍，使用第一个检测到的球拍
        if reference_racket is None:
            print("未能找到合适的参考球拍，使用第一个检测到的球拍...")
            for i in range(len(racket_tracked)):
                if racket_tracked[i]:
                    reference_racket = racket_tracked[i][0]
                    reference_frame_idx = i
                    reference_racket_center = [
                        (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                        (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                    ]
                    filtered_racket[i] = [reference_racket]
                    print(f"使用第一个检测到的球拍作为参考! 帧索引: {i}")
                    break
        
        # 如果依然没有找到任何球拍，返回空结果
        if reference_racket is None:
            print("错误: 未能找到任何球拍！")
            return [[] for _ in range(len(racket_tracked))]
        
        # 记录参考球拍的尺寸
        reference_width = reference_racket["bbox"][2] - reference_racket["bbox"][0]
        reference_height = reference_racket["bbox"][3] - reference_racket["bbox"][1]
        
        # 前向遍历，从参考帧向后处理
        last_good_center = reference_racket_center
        for i in range(reference_frame_idx + 1, len(racket_tracked)):
            if not racket_tracked[i]:
                continue
                
            best_racket = None
            best_score = 0
            
            # 是否有运动员在这一帧
            has_player = bool(player_tracked[i])
            
            for racket in racket_tracked[i]:
                racket_center = [
                    (racket["bbox"][0] + racket["bbox"][2]) / 2,
                    (racket["bbox"][1] + racket["bbox"][3]) / 2
                ]
                
                # 计算与上一个好球拍的距离分数
                dist_to_last = math.sqrt(
                    (racket_center[0] - last_good_center[0])**2 + 
                    (racket_center[1] - last_good_center[1])**2
                )
                position_score = 1.0 / (1.0 + 0.01 * dist_to_last)
                
                # 计算尺寸相似度分数
                width = racket["bbox"][2] - racket["bbox"][0]
                height = racket["bbox"][3] - racket["bbox"][1]
                width_ratio = min(width, reference_width) / max(width, reference_width)
                height_ratio = min(height, reference_height) / max(height, reference_height)
                size_score = (width_ratio + height_ratio) / 2
                
                # 基础总分
                total_score = 0.7 * position_score + 0.3 * size_score
                
                # 如果有运动员，额外考虑与运动员的距离
                if has_player:
                    player = player_tracked[i][0]
                    player_right = player["bbox"][2]
                    player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
                    
                    hand_dist = math.sqrt(
                        (racket_center[0] - player_right)**2 + 
                        (racket_center[1] - player_middle_y)**2
                    )
                    
                    player_score = 1.0 / (1.0 + 0.005 * hand_dist)
                    
                    # 重新计算总分，加入与运动员的关系
                    total_score = 0.5 * total_score + 0.5 * player_score
                
                if total_score > best_score:
                    best_score = total_score
                    best_racket = racket
            
            if best_racket:
                filtered_racket[i] = [best_racket]
                last_good_center = [
                    (best_racket["bbox"][0] + best_racket["bbox"][2]) / 2,
                    (best_racket["bbox"][1] + best_racket["bbox"][3]) / 2
                ]
        
        # 后向遍历，从参考帧向前处理
        last_good_center = reference_racket_center
        for i in range(reference_frame_idx - 1, -1, -1):
            if not racket_tracked[i]:
                continue
                
            best_racket = None
            best_score = 0
            
            # 是否有运动员在这一帧
            has_player = bool(player_tracked[i])
            
            for racket in racket_tracked[i]:
                racket_center = [
                    (racket["bbox"][0] + racket["bbox"][2]) / 2,
                    (racket["bbox"][1] + racket["bbox"][3]) / 2
                ]
                
                # 计算与上一个好球拍的距离分数
                dist_to_last = math.sqrt(
                    (racket_center[0] - last_good_center[0])**2 + 
                    (racket_center[1] - last_good_center[1])**2
                )
                position_score = 1.0 / (1.0 + 0.01 * dist_to_last)
                
                # 计算尺寸相似度分数
                width = racket["bbox"][2] - racket["bbox"][0]
                height = racket["bbox"][3] - racket["bbox"][1]
                width_ratio = min(width, reference_width) / max(width, reference_width)
                height_ratio = min(height, reference_height) / max(height, reference_height)
                size_score = (width_ratio + height_ratio) / 2
                
                # 基础总分
                total_score = 0.7 * position_score + 0.3 * size_score
                
                # 如果有运动员，额外考虑与运动员的距离
                if has_player:
                    player = player_tracked[i][0]
                    player_right = player["bbox"][2]
                    player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
                    
                    hand_dist = math.sqrt(
                        (racket_center[0] - player_right)**2 + 
                        (racket_center[1] - player_middle_y)**2
                    )
                    
                    player_score = 1.0 / (1.0 + 0.005 * hand_dist)
                    
                    # 重新计算总分，加入与运动员的关系
                    total_score = 0.5 * total_score + 0.5 * player_score
                
                if total_score > best_score:
                    best_score = total_score
                    best_racket = racket
            
            if best_racket:
                filtered_racket[i] = [best_racket]
                last_good_center = [
                    (best_racket["bbox"][0] + best_racket["bbox"][2]) / 2,
                    (best_racket["bbox"][1] + best_racket["bbox"][3]) / 2
                ]
        
        # 统计过滤结果
        frames_with_filtered_rackets = sum(1 for frame in filtered_racket if frame)
        print(f"过滤后有球拍的帧数: {frames_with_filtered_rackets}/{len(filtered_racket)}")
        
        return filtered_racket
    
    # ===== 过滤网球运动员，仅保留一个网球运动员 =====
    def filter_player(player_tracked: list) -> list:
        """
        过滤网球运动员，仅保留一个网球运动员。
        选择每帧中置信度最高的网球运动员，并保持轨迹的连续性。
        
        Parameters:
        -----------
        player_tracked: list
            owlv2_sam2_video_tracking返回的网球运动员检测结果
            
        Returns:
        --------
        list:
            过滤后的网球运动员检测结果，每帧最多包含一个网球运动员
        """
        filtered_player = []
        
        # 历史记录，用于维护过去几帧的位置和特征
        history_length = 10  # 保持多少帧的历史记录，运动员移动较慢，可以使用更长的历史
        position_history = []  # 位置历史
        size_history = []      # 尺寸历史
        velocity_history = []  # 速度历史
        max_disappear_frames = 10  # 允许运动员消失的最大帧数，运动员不太可能突然消失
        disappear_count = 0
        
        # 选择初始运动员 - 找到视频中第一个出现且置信度最高的运动员
        initial_frame_idx = None
        initial_player = None
        max_confidence = -1
        
        # 寻找前30帧中置信度最高的运动员作为参考
        search_range = min(30, len(player_tracked))
        for i in range(search_range):
            if player_tracked[i]:
                for player in player_tracked[i]:
                    confidence = player.get("score", 0)
                    # 运动员通常在画面中占比较大，可以加入尺寸因素作为参考
                    box_width = player["bbox"][2] - player["bbox"][0]
                    box_height = player["bbox"][3] - player["bbox"][1]
                    box_area = box_width * box_height
                    
                    # 结合置信度和区域大小来选择初始运动员
                    area_factor = min(1.0, box_area / 40000)  # 归一化区域因子，假设40000像素为参考
                    adjusted_confidence = confidence * (0.7 + 0.3 * area_factor)  # 区域权重占30%
                    
                    if adjusted_confidence > max_confidence:
                        initial_frame_idx = i
                        initial_player = player
                        max_confidence = adjusted_confidence
        
        # 如果没有找到任何运动员，返回空列表
        if initial_player is None:
            return [[] for _ in range(len(player_tracked))]
            
        # 初始化历史记录
        initial_position = initial_player["bbox"][:2]  # (x_min, y_min)
        initial_size = (
            initial_player["bbox"][2] - initial_player["bbox"][0],  # 宽度
            initial_player["bbox"][3] - initial_player["bbox"][1]   # 高度
        )
        
        # 填充历史记录
        position_history = [initial_position] * history_length
        size_history = [initial_size] * history_length
        velocity_history = [(0, 0)] * (history_length - 1)  # 速度需要两个点才能计算
        
        # 对视频帧进行处理
        for i in range(len(player_tracked)):
            if i < initial_frame_idx:
                # 初始帧之前的所有帧都设为空
                filtered_player.append([])
                continue
            
            if i == initial_frame_idx:
                # 初始帧直接使用初始运动员
                filtered_player.append([initial_player])
                continue
        
            # 开始主要处理逻辑
            frame_detections = player_tracked[i]
            
            # 如果当前帧没有检测到运动员
            if not frame_detections:
                if disappear_count < max_disappear_frames:
                    filtered_player.append([])
                    disappear_count += 1
                else:
                    # 如果消失太久，可以尝试根据速度预测位置
                    filtered_player.append([])
                continue
            
            # 检测到运动员，重置消失计数
            disappear_count = 0
            
            # 计算当前历史中的平均位置和尺寸
            avg_position = [sum(p[0] for p in position_history) / len(position_history),
                           sum(p[1] for p in position_history) / len(position_history)]
            
            avg_size = [sum(s[0] for s in size_history) / len(size_history),
                       sum(s[1] for s in size_history) / len(size_history)]
            
            # 计算平均速度向量
            if len(velocity_history) > 0:
                avg_velocity = [sum(v[0] for v in velocity_history) / len(velocity_history),
                               sum(v[1] for v in velocity_history) / len(velocity_history)]
            else:
                avg_velocity = [0, 0]
            
            # 预测当前帧的位置
            predicted_position = [avg_position[0] + avg_velocity[0], 
                                 avg_position[1] + avg_velocity[1]]
            
            # 多个检测结果时，选择最佳的运动员
            best_player = None
            best_score = -1
            
            for player in frame_detections:
                # 获取置信度，如果没有则默认为0
                confidence = player.get("score", 0)
                current_position = player["bbox"][:2]  # (x_min, y_min)
                
                # 计算当前运动员的尺寸
                current_size = (
                    player["bbox"][2] - player["bbox"][0],  # 宽度
                    player["bbox"][3] - player["bbox"][1]   # 高度
                )
                
                # 计算当前运动员的区域
                box_area = current_size[0] * current_size[1]
                
                # 1. 位置连续性评分 - 与预测位置的距离
                position_diff = math.sqrt((current_position[0] - predicted_position[0])**2 + 
                                         (current_position[1] - predicted_position[1])**2)
                position_score = 1.0 / (1.0 + 0.005 * position_diff)  # 归一化，运动员移动较慢，所以系数更小
                
                # 2. 尺寸连续性评分 - 与平均尺寸的相似度
                width_ratio = abs(current_size[0] / avg_size[0] - 1)
                height_ratio = abs(current_size[1] / avg_size[1] - 1)
                size_score = 1.0 / (1.0 + 2.0 * (width_ratio + height_ratio))  # 归一化
                
                # 3. 区域大小评分 - 运动员通常是画面中的主体
                area_score = min(1.0, box_area / 40000)  # 假设40000像素为参考
                
                # 4. 位置历史一致性评分 - 与历史轨迹的一致性
                history_diffs = []
                for pos in position_history:
                    diff = math.sqrt((current_position[0] - pos[0])**2 + 
                                    (current_position[1] - pos[1])**2)
                    history_diffs.append(diff)
                
                # 计算位置变化的标准差，变化越稳定越好
                if len(history_diffs) > 1:
                    mean_diff = sum(history_diffs) / len(history_diffs)
                    variance = sum((d - mean_diff)**2 for d in history_diffs) / len(history_diffs)
                    std_dev = math.sqrt(variance)
                    history_score = 1.0 / (1.0 + 0.05 * std_dev)  # 归一化，运动员移动较慢
                else:
                    history_score = 0.5  # 默认中等评分
                
                # 综合评分 - 置信度(20%)、位置预测(25%)、尺寸一致性(20%)、区域大小(15%)、历史轨迹一致性(20%)
                total_score = (0.2 * confidence + 
                              0.25 * position_score + 
                              0.2 * size_score + 
                              0.15 * area_score +
                              0.2 * history_score)
                
                # 更新最佳运动员
                if total_score > best_score:
                    best_player = player
                    best_score = total_score
            
            # 添加选中的运动员到结果列表
            if best_player:
                filtered_player.append([best_player])
                
                # 更新历史记录
                current_position = best_player["bbox"][:2]
                current_size = (
                    best_player["bbox"][2] - best_player["bbox"][0],
                    best_player["bbox"][3] - best_player["bbox"][1]
                )
                
                # 计算速度（当前位置 - 上一位置）
                if position_history:
                    last_position = position_history[-1]
                    current_velocity = (
                        current_position[0] - last_position[0],
                        current_position[1] - last_position[1]
                    )
                    velocity_history.append(current_velocity)
                    if len(velocity_history) > history_length - 1:
                        velocity_history.pop(0)
                
                # 更新位置和尺寸历史
                position_history.append(current_position)
                size_history.append(current_size)
                if len(position_history) > history_length:
                    position_history.pop(0)
                if len(size_history) > history_length:
                    size_history.pop(0)
            else:
                filtered_player.append([])
        
        return filtered_player
    
    # ===== 选择最佳接触帧 =====
    def select_contact_frame(ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
        """
        选择最佳接触帧（逻辑： 网球和网球拍最近距离的帧, 可能要考虑网球拍和网球不在同一帧的情况）
        
        Parameters:
        -----------
        ball_tracked: list
            过滤后的网球检测结果
        racket_tracked: list
            过滤后的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果
        fps: float
            视频帧率，用于计算基于时间的搜索范围
            
        Returns:
        --------
        int:
            最佳接触帧的索引
        """
        print("\n开始查找最佳接触帧...")
        
        # 初始化变量
        min_distance = float('inf')
        best_frame_idx = -1
        max_search_frames = len(ball_tracked)
        
        # 使用滑动窗口方法找出网球和球拍最近的帧
        # 同时考虑球速变化作为辅助标志（接触后球速通常有显著变化）
        window_size = 3  # 考虑前后共3帧
        
        # 1. 先找出所有同时包含网球和球拍的帧
        valid_frames = []
        for i in range(max_search_frames):
            if ball_tracked[i] and racket_tracked[i]:
                valid_frames.append(i)
        
        if not valid_frames:
            print("警告: 没有找到同时包含网球和球拍的帧，尝试使用时间插值...")
            # 如果没有同时包含两者的帧，尝试找最近的一对球和拍
            for i in range(max_search_frames):
                if ball_tracked[i]:  # 找到球的帧
                    ball_frame = i
                    ball_center = [
                        (ball_tracked[i][0]["bbox"][0] + ball_tracked[i][0]["bbox"][2]) / 2,
                        (ball_tracked[i][0]["bbox"][1] + ball_tracked[i][0]["bbox"][3]) / 2
                    ]
                    
                    # 查找最近的球拍帧
                    nearest_racket_frame = -1
                    min_frame_diff = float('inf')
                    
                    # 在前后0.5秒范围内查找
                    search_window = int(fps * 0.5)  # 前后0.5秒
                    search_start = max(0, i - search_window)
                    search_end = min(max_search_frames, i + search_window)
                    
                    for j in range(search_start, search_end):
                        if racket_tracked[j]:
                            frame_diff = abs(j - i)
                            if frame_diff < min_frame_diff:
                                min_frame_diff = frame_diff
                                nearest_racket_frame = j
                    
                    if nearest_racket_frame != -1:
                        # 找到了最近的球拍帧，添加到候选列表
                        valid_frames.append((i + nearest_racket_frame) // 2)  # 取中间帧作为近似接触帧
            
            # 如果仍然没有找到，选择视频中间的帧作为备选
            if not valid_frames:
                print("警告: 无法定位接触帧，使用视频中点作为接触帧...")
                return max_search_frames // 2
        
        print(f"找到 {len(valid_frames)} 个可能的接触帧")
        
        # 2. 对每个候选帧计算球和拍的距离
        frame_distances = []
        
        for frame_idx in valid_frames:
            # 获取网球中心
            if ball_tracked[frame_idx]:
                ball = ball_tracked[frame_idx][0]
                ball_center = [
                    (ball["bbox"][0] + ball["bbox"][2]) / 2,
                    (ball["bbox"][1] + ball["bbox"][3]) / 2
                ]
                
                # 获取球拍位置 - 使用球拍框与球的距离
                if racket_tracked[frame_idx]:
                    racket = racket_tracked[frame_idx][0]
                    
                    # 找到球拍边界框上最接近球的点
                    # 考虑到网球拍可能是一个矩形框，实际上球可能与拍线（框内部）接触
                    racket_bbox = racket["bbox"]
                    
                    # 检查球是否在球拍框内
                    if (ball_center[0] >= racket_bbox[0] and ball_center[0] <= racket_bbox[2] and
                        ball_center[1] >= racket_bbox[1] and ball_center[1] <= racket_bbox[3]):
                        # 球在球拍框内，这是一个很好的接触候选
                        distance = 0
                    else:
                        # 球在球拍框外，计算到框的最短距离
                        dx = max(racket_bbox[0] - ball_center[0], 0, ball_center[0] - racket_bbox[2])
                        dy = max(racket_bbox[1] - ball_center[1], 0, ball_center[1] - racket_bbox[3])
                        distance = math.sqrt(dx * dx + dy * dy)
                    
                    frame_distances.append((frame_idx, distance))
        
        # 按距离排序
        frame_distances.sort(key=lambda x: x[1])
        
        # 3. 使用球速变化作为额外的判断标准
        if frame_distances:
            # 取距离最小的前3个帧进行进一步分析
            top_candidates = [fd[0] for fd in frame_distances[:min(3, len(frame_distances))]]
            
            # 计算每个候选帧前后的球速变化
            best_velocity_change = -1
            for frame_idx in top_candidates:
                # 确保有足够的前后帧用于计算速度
                if frame_idx > 1 and frame_idx < max_search_frames - 2:
                    # 找到前后有球的帧
                    pre_ball_idx = frame_idx - 1
                    while pre_ball_idx > 0 and not ball_tracked[pre_ball_idx]:
                        pre_ball_idx -= 1
                    
                    post_ball_idx = frame_idx + 1
                    while post_ball_idx < max_search_frames - 1 and not ball_tracked[post_ball_idx]:
                        post_ball_idx += 1
                    
                    # 确保找到了前后的球
                    if ball_tracked[pre_ball_idx] and ball_tracked[post_ball_idx]:
                        pre_ball = ball_tracked[pre_ball_idx][0]
                        post_ball = ball_tracked[post_ball_idx][0]
                        
                        pre_center = [
                            (pre_ball["bbox"][0] + pre_ball["bbox"][2]) / 2,
                            (pre_ball["bbox"][1] + pre_ball["bbox"][3]) / 2
                        ]
                        
                        post_center = [
                            (post_ball["bbox"][0] + post_ball["bbox"][2]) / 2,
                            (post_ball["bbox"][1] + post_ball["bbox"][3]) / 2
                        ]
                        
                        # 计算前后速度向量
                        pre_velocity = [
                            (ball_center[0] - pre_center[0]) / (frame_idx - pre_ball_idx),
                            (ball_center[1] - pre_center[1]) / (frame_idx - pre_ball_idx)
                        ]
                        
                        post_velocity = [
                            (post_center[0] - ball_center[0]) / (post_ball_idx - frame_idx),
                            (post_center[1] - ball_center[1]) / (post_ball_idx - frame_idx)
                        ]
                        
                        # 计算速度变化量（方向和大小）
                        velocity_change = math.sqrt(
                            (post_velocity[0] - pre_velocity[0])**2 + 
                            (post_velocity[1] - pre_velocity[1])**2
                        )
                        
                        # 如果速度变化很大，这更可能是接触帧
                        if velocity_change > best_velocity_change:
                            best_velocity_change = velocity_change
                            best_frame_idx = frame_idx
            
            # 如果基于速度没有找到好的候选，就使用距离最小的
            if best_frame_idx == -1 and frame_distances:
                best_frame_idx = frame_distances[0][0]
        
        # 如果没有找到合适的帧，返回默认值
        if best_frame_idx == -1:
            print("警告: 无法确定接触帧，使用视频中点...")
            best_frame_idx = max_search_frames // 2
        
        print(f"最佳接触帧索引: {best_frame_idx}")
        return best_frame_idx

    # ===== 选择准备动作帧 =====
    def select_preparation_frame(contact_frame: int, ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
        """
        选择准备动作帧（逻辑： 最佳接触帧前，离最佳接触帧最近，网球拍速度最小的帧）
        
        Parameters:
        -----------
        contact_frame: int
            接触帧索引
        ball_tracked: list
            过滤后的网球检测结果
        racket_tracked: list
            过滤后的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果
        fps: float
            视频帧率，用于计算基于时间的搜索范围
            
        Returns:
        --------
        int:
            准备动作帧的索引
        """
        print("\n开始查找准备动作帧...")
        
        # 初始设定
        max_frames = len(racket_tracked)
        
        # 设置搜索范围 - 接触帧前1秒内
        search_frames = int(fps)  # 1秒内的帧数
        search_range = min(search_frames, contact_frame)
        min_search_idx = max(0, contact_frame - search_range)
        
        # 初始化变量
        best_prep_idx = min_search_idx  # 默认使用搜索范围内最早的帧
        min_velocity = float('inf')
        last_racket_center = None
        
        # 计算球拍在各帧中的速度，找到速度最小的帧
        for i in range(contact_frame - 1, min_search_idx - 1, -1):
            # 确保当前帧有球拍
            if not racket_tracked[i]:
                continue
                
            racket = racket_tracked[i][0]
            racket_center = [
                (racket["bbox"][0] + racket["bbox"][2]) / 2,
                (racket["bbox"][1] + racket["bbox"][3]) / 2
            ]
            
            # 需要有上一帧作为参考才能计算速度
            if last_racket_center is None:
                last_racket_center = racket_center
                last_idx = i
                continue
            
            # 计算球拍速度 (逐帧位移)
            velocity = math.sqrt(
                (racket_center[0] - last_racket_center[0])**2 + 
                (racket_center[1] - last_racket_center[1])**2
            )
            
            # 正规化速度 (考虑帧间距)
            frame_diff = last_idx - i
            if frame_diff > 0:
                velocity /= frame_diff
            
            # 更新最小速度
            if velocity < min_velocity:
                min_velocity = velocity
                best_prep_idx = i
            
            # 更新上一帧信息
            last_racket_center = racket_center
            last_idx = i
        
        # 额外检查：如果找到的准备帧离接触帧太近，可能不是真正的准备阶段
        # 理想情况下，准备动作应该发生在接触前的适当距离
        min_frame_distance = int(fps * 0.08)  # 大约为接触前0.08秒
        min_frame_distance = max(5, min_frame_distance)  # 至少5帧的距离
        
        if contact_frame - best_prep_idx < min_frame_distance and best_prep_idx > min_search_idx:
            # 尝试在更早的时间段内再次寻找
            secondary_search_end = best_prep_idx - 1
            secondary_search_start = max(0, min_search_idx - int(fps * 0.5))  # 再往前0.5秒
            
            secondary_best_idx = secondary_search_start
            secondary_min_velocity = float('inf')
            last_racket_center = None
            
            for i in range(secondary_search_end, secondary_search_start - 1, -1):
                if not racket_tracked[i]:
                    continue
                    
                racket = racket_tracked[i][0]
                racket_center = [
                    (racket["bbox"][0] + racket["bbox"][2]) / 2,
                    (racket["bbox"][1] + racket["bbox"][3]) / 2
                ]
                
                if last_racket_center is None:
                    last_racket_center = racket_center
                    last_idx = i
                    continue
                
                velocity = math.sqrt(
                    (racket_center[0] - last_racket_center[0])**2 + 
                    (racket_center[1] - last_racket_center[1])**2
                )
                
                frame_diff = last_idx - i
                if frame_diff > 0:
                    velocity /= frame_diff
                
                if velocity < secondary_min_velocity:
                    secondary_min_velocity = velocity
                    secondary_best_idx = i
                
                last_racket_center = racket_center
                last_idx = i
            
            # 如果找到了更好的准备帧，使用它
            if secondary_min_velocity < min_velocity * 1.2:  # 允许略微更高的速度
                best_prep_idx = secondary_best_idx
        
        # 如果没有找到合适的准备帧，使用默认帧（离接触帧适当距离的帧）
        if best_prep_idx == contact_frame:
            default_prep_idx = max(0, contact_frame - int(fps * 0.33))  # 默认使用接触帧前1/3秒
            best_prep_idx = default_prep_idx
            print(f"警告: 无法找到合适的准备帧，使用默认帧 (接触帧-{int(fps * 0.33)}帧)")
        
        print(f"最佳准备动作帧索引: {best_prep_idx} (接触帧: {contact_frame})")
        return best_prep_idx

    # ===== 选择跟随动作帧 =====
    def select_follow_frame(contact_frame: int, ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
        """
        选择跟随动作帧（逻辑： 最佳接触帧后, 离最佳接触帧最近，且网球拍位置最高的帧）
        
        Parameters:
        -----------
        contact_frame: int
            接触帧索引
        ball_tracked: list
            过滤后的网球检测结果
        racket_tracked: list
            过滤后的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果
        fps: float
            视频帧率，用于计算基于时间的搜索范围
            
        Returns:
        --------
        int:
            跟随动作帧的索引
        """
        print("\n开始查找跟随动作帧...")
        
        # 初始设定
        max_frames = len(racket_tracked)
        
        # 设置搜索范围 - 接触帧后1秒内
        search_frames = int(fps)  # 1秒内的帧数
        max_search_idx = min(max_frames - 1, contact_frame + search_frames)
        
        # 初始化变量
        best_follow_idx = max_search_idx  # 默认使用搜索范围内最晚的帧
        highest_position = float('inf')  # 注意：屏幕坐标y值越小，位置越高
        
        # 在接触帧之后查找球拍位置最高的帧
        for i in range(contact_frame + 1, max_search_idx + 1):
            # 确保当前帧有球拍
            if not racket_tracked[i]:
                continue
                
            racket = racket_tracked[i][0]
            
            # 计算球拍顶部位置 (y坐标最小值)
            racket_top = racket["bbox"][1]  # bbox = [x_min, y_min, x_max, y_max]
            
            # 查找球拍顶部位置最高（y值最小）的帧
            if racket_top < highest_position:
                highest_position = racket_top
                best_follow_idx = i
            
            # 如果发现球拍位置开始下降，这可能表示跟随动作已经完成
            # 检查后续几帧，如果球拍持续下降，则停止搜索
            if i > contact_frame + int(fps * 0.17) and racket_top < highest_position:  # 大约接触后0.17秒
                consecutive_drops = 0
                for j in range(i + 1, min(i + 5, max_search_idx + 1)):
                    if racket_tracked[j]:
                        next_racket_top = racket_tracked[j][0]["bbox"][1]
                        if next_racket_top > racket_top:  # y增加表示位置下降
                            consecutive_drops += 1
                
                # 如果连续3帧都在下降，认为跟随动作已经结束
                if consecutive_drops >= 3:
                    break
        
        # 确保跟随帧与接触帧有足够距离
        min_frame_distance = int(fps * 0.17)  # 大约接触后0.17秒
        min_frame_distance = max(10, min_frame_distance)  # 至少10帧的距离
        
        if best_follow_idx - contact_frame < min_frame_distance:
            # 如果太近，尝试找到稍远但仍然合理的帧
            secondary_search_start = contact_frame + min_frame_distance
            secondary_search_end = min(max_frames - 1, contact_frame + search_frames)
            
            if secondary_search_start <= secondary_search_end:
                secondary_best_idx = secondary_search_start
                secondary_highest_position = float('inf')
                
                for i in range(secondary_search_start, secondary_search_end + 1):
                    if not racket_tracked[i]:
                        continue
                        
                    racket = racket_tracked[i][0]
                    racket_top = racket["bbox"][1]
                    
                    if racket_top < secondary_highest_position:
                        secondary_highest_position = racket_top
                        secondary_best_idx = i
                
                # 如果找到了合适的帧，使用它
                if secondary_highest_position < float('inf'):
                    best_follow_idx = secondary_best_idx
        
        # 如果没有找到合适的跟随帧，使用默认帧（接触帧后适当距离的帧）
        if best_follow_idx == contact_frame or best_follow_idx >= max_frames:
            default_follow_idx = min(max_frames - 1, contact_frame + int(fps * 0.33))  # 默认使用接触帧后1/3秒
            best_follow_idx = default_follow_idx
            print(f"警告: 无法找到合适的跟随帧，使用默认帧 (接触帧+{int(fps * 0.33)}帧)")
        
        print(f"最佳跟随动作帧索引: {best_follow_idx} (接触帧: {contact_frame})")
        return best_follow_idx
    
    # ===== 视频帧提取 =====
    def extract_part_frames(video_path: str) -> list:
        """
        提取视频帧并返回帧数据列表
        """
        print("\n步骤1: 从视频中提取帧...")
        # 首先获取视频的实际帧率
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频: {video_path}")
        
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / actual_fps if actual_fps > 0 else 0
        cap.release()
        
        # 限制只分析前6秒的视频内容
        max_seconds = 6
        max_frames = int(actual_fps * max_seconds)
        
        print(f"  视频实际帧率: {actual_fps:.2f} fps")
        print(f"  视频总长度: {video_duration:.2f} 秒 ({total_frames} 帧)")
        print(f"  将仅分析前 {max_seconds} 秒的内容 (最多 {max_frames} 帧)")
        
        # 提取帧并限制数量
        frames_data = extract_frames_and_timestamps(video_path, fps=actual_fps)
        
        # 如果提取的帧超过了最大帧数，则只保留前max_frames帧
        if len(frames_data) > max_frames:
            frames_data = frames_data[:max_frames]
            print(f"  截取了前 {len(frames_data)} 帧用于分析")
        
        frames_list = [f["frame"] for f in frames_data]
        print(f"  最终使用 {len(frames_list)} 帧进行分析")
        return frames_list, actual_fps

    # ===== 保存最佳接触帧的完整动作的视频 =====
    def save_video_with_one_action(output_dir: str, frames_list: list, ball_tracked: list, racket_tracked: list, player_tracked: list, contact_frame: int, prep_frame: int, follow_frame: int):
        """
        保存最佳接触帧的完整动作视频，包含准备、接触和跟随三个阶段
        
        Parameters:
        -----------
        output_dir: str
            输出目录
        frames_list: list
            视频帧列表
        ball_tracked: list
            过滤后的网球检测结果
        racket_tracked: list
            过滤后的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果
        contact_frame: int
            接触帧索引
        prep_frame: int
            准备动作帧索引
        follow_frame: int
            跟随动作帧索引
            
        Returns:
        --------
        str:
            保存的视频路径
        """
        print("\n保存完整击球动作视频...")
        
        # 确定视频片段的起始和结束帧
        start_frame = prep_frame
        end_frame = follow_frame
        
        # 确保帧索引有效
        start_frame = max(0, start_frame)
        end_frame = min(len(frames_list) - 1, end_frame)
        
        # 提取动作视频帧
        action_frames = frames_list[start_frame:end_frame+1]
        
        # 为每一帧添加检测框
        annotated_frames = []
        
        for i, frame in enumerate(action_frames):
            current_frame_idx = start_frame + i
            boxes = []
            
            # 添加网球检测框
            if current_frame_idx < len(ball_tracked) and ball_tracked[current_frame_idx]:
                for ball in ball_tracked[current_frame_idx]:
                    score = ball.get("score", 0)
                    boxes.append({
                        "bbox": ball["bbox"],
                        "label": f"Tennis Ball {score:.2f}",
                        "color": (255, 255, 0),  # 黄色
                        "score": score
                    })
            
            # 添加球拍检测框
            if current_frame_idx < len(racket_tracked) and racket_tracked[current_frame_idx]:
                for racket in racket_tracked[current_frame_idx]:
                    score = racket.get("score", 0)
                    boxes.append({
                        "bbox": racket["bbox"],
                        "label": f"Tennis Racket {score:.2f}",
                        "color": (0, 0, 255),  # 红色
                        "score": score
                    })
            
            # 添加运动员检测框
            if current_frame_idx < len(player_tracked) and player_tracked[current_frame_idx]:
                for player in player_tracked[current_frame_idx]:
                    score = player.get("score", 0)
                    boxes.append({
                        "bbox": player["bbox"],
                        "label": f"Tennis Player {score:.2f}",
                        "color": (0, 255, 0),  # 绿色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            frame_with_boxes = frame.copy()
            if boxes:
                frame_with_boxes = overlay_bounding_boxes(frame, boxes)
            
            # 添加阶段标识
            # 在帧上添加文字说明当前是准备/接触/跟随阶段
            frame_height, frame_width = frame_with_boxes.shape[:2]
            
            # 确定当前帧的阶段
            phase_text = ""
            text_color = (255, 255, 255)  # 白色文字
            
            if current_frame_idx < contact_frame:
                phase_text = "preparation"
                text_color = (255, 255, 0)  # 黄色
            elif current_frame_idx == contact_frame:
                phase_text = "contact"
                text_color = (0, 0, 255)  # 红色
            else:
                phase_text = "follow"
                text_color = (0, 255, 0)  # 绿色
            
            # 在帧上添加阶段文字
            cv2.putText(
                frame_with_boxes, 
                phase_text, 
                (10, 30),  # 位置 (左上角)
                cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                1,  # 字体大小
                text_color,  # 字体颜色
                2,  # 线宽
                cv2.LINE_AA  # 抗锯齿
            )
            
            # 特殊标记关键帧
            if current_frame_idx == prep_frame:
                # 在准备帧上添加特殊标记
                cv2.putText(
                    frame_with_boxes, 
                    "preparation", 
                    (10, 70),  # 位置 (左上角)
                    cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                    1,  # 字体大小
                    (255, 255, 0),  # 黄色
                    2,  # 线宽
                    cv2.LINE_AA  # 抗锯齿
                )
                # 添加边框
                cv2.rectangle(
                    frame_with_boxes,
                    (0, 0),
                    (frame_width-1, frame_height-1),
                    (255, 255, 0),  # 黄色边框
                    5  # 边框宽度
                )
            
            if current_frame_idx == contact_frame:
                # 在接触帧上添加特殊标记
                cv2.putText(
                    frame_with_boxes, 
                    "contact", 
                    (10, 70),  # 位置 (左上角)
                    cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                    1,  # 字体大小
                    (0, 0, 255),  # 红色
                    2,  # 线宽
                    cv2.LINE_AA  # 抗锯齿
                )
                # 添加边框
                cv2.rectangle(
                    frame_with_boxes,
                    (0, 0),
                    (frame_width-1, frame_height-1),
                    (0, 0, 255),  # 红色边框
                    5  # 边框宽度
                )
            
            if current_frame_idx == follow_frame:
                # 在跟随帧上添加特殊标记
                cv2.putText(
                    frame_with_boxes, 
                    "follow", 
                    (10, 70),  # 位置 (左上角)
                    cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                    1,  # 字体大小
                    (0, 255, 0),  # 绿色
                    2,  # 线宽
                    cv2.LINE_AA  # 抗锯齿
                )
                # 添加边框
                cv2.rectangle(
                    frame_with_boxes,
                    (0, 0),
                    (frame_width-1, frame_height-1),
                    (0, 255, 0),  # 绿色边框
                    5  # 边框宽度
                )
                        
            annotated_frames.append(frame_with_boxes)
        
        # 保存完整动作视频
        action_video_path = os.path.join(output_dir, "tennis_action.mp4")
        save_video(annotated_frames, action_video_path, fps=30)
        print(f"完整击球动作视频已保存至: {action_video_path}")
        
        # 还可以保存慢动作版本
        slow_motion_video_path = os.path.join(output_dir, "tennis_action_slow.mp4")
        save_video(annotated_frames, slow_motion_video_path, fps=15)  # 半速
        print(f"慢动作击球视频已保存至: {slow_motion_video_path}")
        
        return action_video_path, slow_motion_video_path

    # ===== 保存完整的识别后的视频 =====
    def save_complete_detection_video(output_dir: str, frames_list: list, ball_tracked: list, racket_tracked: list, player_tracked: list, contact_frame: int, prep_frame: int, follow_frame: int):
        """
        保存完整的识别后的视频，包含所有帧的检测结果和关键帧标记
        
        Parameters:
        -----------
        output_dir: str
            输出目录
        frames_list: list
            视频帧列表
        ball_tracked: list
            过滤后的网球检测结果
        racket_tracked: list
            过滤后的球拍检测结果
        player_tracked: list
            过滤后的网球运动员检测结果
        contact_frame: int
            接触帧索引
        prep_frame: int
            准备动作帧索引
        follow_frame: int
            跟随动作帧索引
            
        Returns:
        --------
        str:
            保存的完整识别视频路径
        """
        print("\n生成完整的识别后的视频...")
        
        # 为每一帧添加检测框和标记
        annotated_frames = []
        
        for i, frame in enumerate(frames_list):
            boxes = []
            
            # 添加网球检测框
            if i < len(ball_tracked) and ball_tracked[i]:
                for ball in ball_tracked[i]:
                    score = ball.get("score", 0)
                    boxes.append({
                        "bbox": ball["bbox"],
                        "label": f"网球 {score:.2f}",
                        "color": (255, 255, 0),  # 黄色
                        "score": score
                    })
            
            # 添加球拍检测框
            if i < len(racket_tracked) and racket_tracked[i]:
                for racket in racket_tracked[i]:
                    score = racket.get("score", 0)
                    boxes.append({
                        "bbox": racket["bbox"],
                        "label": f"球拍 {score:.2f}",
                        "color": (0, 0, 255),  # 红色
                        "score": score
                    })
            
            # 添加运动员检测框
            if i < len(player_tracked) and player_tracked[i]:
                for player in player_tracked[i]:
                    score = player.get("score", 0)
                    boxes.append({
                        "bbox": player["bbox"],
                        "label": f"运动员 {score:.2f}",
                        "color": (0, 255, 0),  # 绿色
                        "score": score
                    })
            
            # 将检测框叠加到帧上
            frame_with_boxes = frame.copy()
            if boxes:
                frame_with_boxes = overlay_bounding_boxes(frame, boxes)
            
            # 获取帧的尺寸
            frame_height, frame_width = frame_with_boxes.shape[:2]
            
            # 添加帧信息文本（左上角）
            frame_info = f"帧: {i+1}/{len(frames_list)}"
            cv2.putText(
                frame_with_boxes, 
                frame_info, 
                (10, 30),  # 位置
                cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                0.8,  # 字体大小
                (255, 255, 255),  # 白色文字
                2,  # 线宽
                cv2.LINE_AA  # 抗锯齿
            )
            
            # 添加时间戳（左上角第二行）
            time_stamp = f"时间: {i/24:.2f}s"  # 假设24fps
            cv2.putText(
                frame_with_boxes, 
                time_stamp, 
                (10, 60),  # 位置
                cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                0.6,  # 字体大小
                (255, 255, 255),  # 白色文字
                2,  # 线宽
                cv2.LINE_AA  # 抗锯齿
            )
            
            # 标记关键帧
            border_color = None
            frame_label = ""
            
            if i == prep_frame:
                border_color = (255, 255, 0)  # 黄色边框
                frame_label = "准备动作帧"
            elif i == contact_frame:
                border_color = (0, 0, 255)  # 红色边框
                frame_label = "接触帧"
            elif i == follow_frame:
                border_color = (0, 255, 0)  # 绿色边框
                frame_label = "跟随动作帧"
            
            # 如果是关键帧，添加边框和标签
            if border_color is not None:
                # 添加边框
                cv2.rectangle(
                    frame_with_boxes,
                    (0, 0),
                    (frame_width-1, frame_height-1),
                    border_color,
                    8  # 边框宽度
                )
                
                # 添加关键帧标签（右上角）
                label_size = cv2.getTextSize(frame_label, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)[0]
                cv2.rectangle(
                    frame_with_boxes,
                    (frame_width - label_size[0] - 20, 10),
                    (frame_width - 10, 50),
                    border_color,
                    -1  # 填充矩形
                )
                
                cv2.putText(
                    frame_with_boxes, 
                    frame_label, 
                    (frame_width - label_size[0] - 15, 35),  # 位置
                    cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                    1.0,  # 字体大小
                    (0, 0, 0),  # 黑色文字
                    3,  # 线宽
                    cv2.LINE_AA  # 抗锯齿
                )
            
            # 添加检测统计信息（右下角）
            ball_count = len(ball_tracked[i]) if i < len(ball_tracked) and ball_tracked[i] else 0
            racket_count = len(racket_tracked[i]) if i < len(racket_tracked) and racket_tracked[i] else 0
            player_count = len(player_tracked[i]) if i < len(player_tracked) and player_tracked[i] else 0
            
            stats_lines = [
                f"网球: {ball_count}",
                f"球拍: {racket_count}",
                f"运动员: {player_count}"
            ]
            
            # 在右下角显示统计信息
            for j, stats_line in enumerate(stats_lines):
                y_pos = frame_height - 90 + (j * 25)
                cv2.putText(
                    frame_with_boxes, 
                    stats_line, 
                    (frame_width - 150, y_pos),  # 位置
                    cv2.FONT_HERSHEY_SIMPLEX,  # 字体
                    0.6,  # 字体大小
                    (255, 255, 255),  # 白色文字
                    2,  # 线宽
                    cv2.LINE_AA  # 抗锯齿
                )
                        
            annotated_frames.append(frame_with_boxes)
        
        # 保存完整的识别视频
        complete_video_path = os.path.join(output_dir, "complete_detection.mp4")
        save_video(annotated_frames, complete_video_path, fps=24)
        print(f"完整识别视频已保存至: {complete_video_path}")
        
        # 也保存一个慢速版本
        complete_slow_video_path = os.path.join(output_dir, "complete_detection_slow.mp4")
        save_video(annotated_frames, complete_slow_video_path, fps=12)  # 半速
        print(f"慢速完整识别视频已保存至: {complete_slow_video_path}")
        
        return complete_video_path, complete_slow_video_path

    # 从这里开始是主要处理逻辑
    #########################################
    # 1. 视频帧提取
    #########################################
    frames_list, actual_fps = extract_part_frames(video_path)

    #########################################
    # 2. 网球和球拍检测与跟踪
    #########################################
    print("\n步骤2: 使用目标检测和跟踪模型...")
    
    # 使用重试机制包装检测调用
    @retry_with_backoff(max_retries=5, base_delay=2, max_delay=120)
    def safe_object_detection(prompt, frames, threshold=0.3):
        """安全的目标检测调用，带重试机制"""
        print(f"  🔍 开始检测: {prompt}")
        print(f"  📊 处理帧数: {len(frames)}")
        print(f"  ⚡ 检测阈值: {threshold}")
        
        # 分批处理以减少API负载
        batch_size = 10  # 每批处理10帧，减少并发压力
        all_results = []
        
        for i in range(0, len(frames), batch_size):
            batch_frames = frames[i:i+batch_size]
            batch_end = min(i + batch_size, len(frames))
            
            print(f"  📦 处理批次 {i//batch_size + 1}: 帧 {i+1}-{batch_end}/{len(frames)}")
            
            # 添加批次间延迟
            if i > 0:
                delay = random.uniform(1, 3)  # 1-3秒随机延迟
                print(f"  ⏳ 批次间延迟 {delay:.1f}秒...")
                time.sleep(delay)
            
            try:
                from vision_agent.tools import owlv2_sam2_video_tracking
                batch_results = owlv2_sam2_video_tracking(prompt, batch_frames, box_threshold=threshold)
                all_results.extend(batch_results)
                print(f"  ✅ 批次 {i//batch_size + 1} 完成")
                
            except Exception as e:
                error_msg = str(e).lower()
                if "rate limit" in error_msg or "429" in error_msg:
                    print(f"  ⚠️ 批次 {i//batch_size + 1} 遇到速率限制，将触发重试...")
                    raise e  # 让重试装饰器处理
                else:
                    print(f"  ❌ 批次 {i//batch_size + 1} 失败: {e}")
                    raise e
        
        return all_results
    
    # 使用更精确的提示词，专注于运动中、带拖影、模糊的网球
    # 分别检测三个对象以降低API压力
    combined_prompt = "moving tennis ball with motion blur, tennis racket, tennis player"
    print(f"使用提示词: {combined_prompt}")
    
    try:
        combined_tracked = safe_object_detection(combined_prompt, frames_list, threshold=0.3)
    except Exception as e:
        print(f"❌ 检测失败: {e}")
        print("🔄 尝试使用更简单的提示词和更高阈值...")
        try:
            # 备用方案：使用更简单的提示词
            simple_prompt = "tennis ball, racket, player"
            combined_tracked = safe_object_detection(simple_prompt, frames_list, threshold=0.5)
        except Exception as e2:
            print(f"❌ 备用检测也失败: {e2}")
            print("⚠️ 将使用演示数据继续处理...")
            # 创建空的检测结果作为演示
            combined_tracked = [[] for _ in range(len(frames_list))]
    
    # 分离检测结果
    ball_tracked = []
    racket_tracked = []
    player_tracked = []
    
    for frame_detections in combined_tracked:
        frame_ball = []
        frame_racket = []
        frame_player = []
        
        for detection in frame_detections:
            if "tennis ball" in detection['label'].lower():
                frame_ball.append(detection)
            elif "racket" in detection['label'].lower():
                frame_racket.append(detection)
            elif "player" in detection['label'].lower():
                frame_player.append(detection)
        
        ball_tracked.append(frame_ball)
        racket_tracked.append(frame_racket)
        player_tracked.append(frame_player)
    
    print(f"  检测到网球数量: {sum(len(frame) for frame in ball_tracked)}")
    print(f"  检测到球拍数量: {sum(len(frame) for frame in racket_tracked)}")
    print(f"  检测到运动员数量: {sum(len(frame) for frame in player_tracked)}")

    #########################################
    # 4. 过滤和整理检测结果（逻辑： 仅保留一个网球拍和网球的轨迹）
    #########################################
    player_tracked = filter_player(player_tracked)
    racket_tracked = filter_racket(racket_tracked, player_tracked)
    ball_tracked = filter_tennis_ball(ball_tracked, racket_tracked)
    # save_video_with_raw_detections(output_dir, frames_list, ball_tracked, racket_tracked, player_tracked)
    # save_video_with_filtered_detections(output_dir, frames_list, ball_tracked, racket_tracked, player_tracked)

    #########################################
    # 5. 选择最佳接触帧（逻辑： 网球和网球拍最近距离的帧, 可能要考虑网球拍和网球不在同一帧的情况）
    #########################################
    contact_frame = select_contact_frame(ball_tracked, racket_tracked, player_tracked, actual_fps)

    #########################################
    # 6. 选择准备动作帧（逻辑： 最佳接触帧前，离最佳接触帧最近，网球拍速度最小的帧）
    #########################################
    prep_frame = select_preparation_frame(contact_frame, ball_tracked, racket_tracked, player_tracked, actual_fps)

    #########################################
    # 7. 选择完成动作帧（逻辑： 最佳接触帧后, 离最佳接触帧最近，且网球拍位置最高的帧）
    #########################################
    follow_frame = select_follow_frame(contact_frame, ball_tracked, racket_tracked, player_tracked, actual_fps)

    #########################################
    # 8. 保存最佳接触帧、准备动作帧、完成动作帧
    #########################################
    print(f"击球帧: {contact_frame}, 准备动作帧: {prep_frame}, 完成动作帧: {follow_frame}")

    # 保存最佳接触帧
    contact_frame_path = os.path.join(output_dir, "contact_frame.jpg")
    contact_frame_rgb = cv2.cvtColor(frames_list[contact_frame], cv2.COLOR_RGB2BGR)
    cv2.imwrite(contact_frame_path, contact_frame_rgb)

    # 保存准备动作帧
    prep_frame_path = os.path.join(output_dir, "prep_frame.jpg")
    prep_frame_rgb = cv2.cvtColor(frames_list[prep_frame], cv2.COLOR_RGB2BGR)
    cv2.imwrite(prep_frame_path, prep_frame_rgb)

    # 保存完成动作帧
    follow_frame_path = os.path.join(output_dir, "follow_frame.jpg")
    follow_frame_rgb = cv2.cvtColor(frames_list[follow_frame], cv2.COLOR_RGB2BGR)
    cv2.imwrite(follow_frame_path, follow_frame_rgb)

    #########################################
    # 9. 保存最佳接触帧的完整动作的视频
    #########################################
    # 获取最佳接触帧的完整动作视频
    one_action_video_path, slow_action_video_path = save_video_with_one_action(output_dir, frames_list, ball_tracked, racket_tracked, player_tracked,
                                                                               contact_frame, prep_frame, follow_frame)
                                                                               
    #########################################
    # 10. 保存完整的识别后的视频
    #########################################
    # 获取完整的识别后的视频
    complete_video_path, complete_slow_video_path = save_complete_detection_video(output_dir, frames_list, ball_tracked, racket_tracked, player_tracked,
                                                                                   contact_frame, prep_frame, follow_frame)

    # 返回结果字典
    return {
        "preparation_frame": prep_frame_path,
        "contact_frame": contact_frame_path,
        "follow_frame": follow_frame_path,
        "one_action_video": one_action_video_path,
        "slow_action_video": slow_action_video_path,
        "complete_video": complete_video_path,
        "complete_slow_video": complete_slow_video_path
    }


# 测试
if __name__ == "__main__":
    # 打印当前目录
    print(f"当前目录: {os.getcwd()}")
    video_path = "videos/roger.mp4"  # 使用相对路径
    output_dir = "videos/"  # 使用相对路径
    print(f"video_path: {video_path}")
    print(f"output_dir: {output_dir}")
    process_tennis_video(video_path, output_dir)