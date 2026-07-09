#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import math
import requests
import tempfile
from pillow_heif import register_heif_opener
from pathlib import Path
from typing import List, Optional, IO
import av
import numpy as np

# 设置OpenCV为headless模式，避免GUI依赖
os.environ['OPENCV_HEADLESS'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import cv2

register_heif_opener()


def save_video(
    frames: List[np.ndarray], 
    output_video_path: Optional[str] = None, 
    fps: float = 24.0
) -> str:
    """
    保存视频帧列表为MP4视频文件，使用H.264编码格式，支持在微信中发送
    
    Parameters:
    -----------
    frames: List[np.ndarray]
        要保存的视频帧列表
    output_video_path: Optional[str]
        输出视频文件路径，如果为None则创建临时文件
    fps: float
        视频帧率，默认24fps
        
    Returns:
    --------
    str:
        保存的视频文件路径
    """
    if isinstance(fps, str):
        fps = float(fps)
    if fps <= 0:
        raise ValueError(f"fps必须大于0，当前值: {fps}")

    if not isinstance(frames, list) or len(frames) == 0:
        raise ValueError("frames必须是非空的numpy数组列表")

    for frame in frames:
        if not isinstance(frame, np.ndarray) or (frame.shape[0] == 0 and frame.shape[1] == 0):
            raise ValueError("帧必须是有效的numpy数组，形状为(H, W, C)")

    # 创建输出文件
    output_file: IO[bytes]
    if output_video_path is None:
        output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    else:
        Path(output_video_path).parent.mkdir(parents=True, exist_ok=True)
        output_file = open(output_video_path, "wb")

    try:
        with output_file as file:
            _write_video_h264(frames, fps, file)
        return output_file.name
    except Exception as e:
        print(f"保存视频时出错: {e}")
        raise


def _write_video_h264(
    frames: List[np.ndarray],
    fps: float,
    file: IO[bytes]
) -> None:
    """
    使用H.264编码写入视频文件，优化为微信兼容格式
    """
    with av.open(file, "w", format="mp4") as container:
        # 配置H.264视频流，使用微信兼容的设置
        stream = container.add_stream("h264", rate=fps)
        
        # 获取第一帧的尺寸
        height, width = frames[0].shape[:2]
        
        # 确保尺寸是偶数（H.264要求）
        stream.height = height - (height % 2)
        stream.width = width - (width % 2)
        
        # 设置像素格式为yuv420p（微信兼容）
        stream.pix_fmt = "yuv420p"
        
        # H.264编码器选项，优化为微信兼容
        stream.options = {
            "crf": "23",  # 恒定质量因子，23是良好的质量/大小平衡
            "preset": "medium",  # 编码速度预设
            "profile": "baseline",  # H.264 baseline profile，最大兼容性
            "level": "3.0",  # H.264 level 3.0，广泛支持
        }
        
        # 写入每一帧
        for frame in frames:
            # 确保帧是RGB格式（移除alpha通道如果存在）
            if frame.shape[2] == 4:  # RGBA
                frame_rgb = frame[:, :, :3]
            else:  # RGB
                frame_rgb = frame[:, :, :3]
            
            # 调整帧尺寸为偶数
            frame_rgb = _resize_frame_for_h264(frame_rgb, stream.width, stream.height)
            
            # 创建AV帧
            av_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
            
            # 编码并写入
            for packet in stream.encode(av_frame):
                container.mux(packet)

        # 写入剩余的编码数据
        for packet in stream.encode():
            container.mux(packet)


def _resize_frame_for_h264(frame: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
    """
    调整帧尺寸为H.264要求的偶数尺寸
    """
    height, width = frame.shape[:2]
    
    # 如果尺寸已经匹配，直接返回
    if width == target_width and height == target_height:
        return frame
    
    # 调整尺寸
    return cv2.resize(frame, (target_width, target_height))


def get_video_info(video_path: str) -> dict:
    """获取视频基本信息"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()
    
    return {
        'fps': fps, 'total_frames': total_frames, 'width': width,
        'height': height, 'duration': duration, 'file_size': os.path.getsize(video_path)
    }

def trim_video_if_needed(video_path: str, max_duration: float = 6.0, max_size_mb: float = 50.0) -> str:
    """如果视频过长或过大，则裁剪视频"""
    print("\n检查视频是否需要裁剪...")
    
    video_info = get_video_info(video_path)
    file_size_mb = video_info['file_size'] / (1024 * 1024)
    
    print(f"视频信息: 时长{video_info['duration']:.2f}秒, 大小{file_size_mb:.2f}MB")
    
    needs_trim = video_info['duration'] > max_duration or file_size_mb > max_size_mb
    if not needs_trim:
        print("✅ 视频无需裁剪")
        return video_path
    
    temp_dir = tempfile.mkdtemp()
    temp_video_path = os.path.join(temp_dir, "trimmed_" + os.path.basename(video_path))
    
    try:
        print(f"🔄 正在裁剪视频至前 {max_duration} 秒...")
        cap = cv2.VideoCapture(video_path)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video_path, fourcc, video_info['fps'], 
                             (video_info['width'], video_info['height']))
        
        target_frames = int(video_info['fps'] * max_duration)
        frame_count = 0
        
        while frame_count < target_frames:
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
            frame_count += 1
        
        cap.release()
        out.release()
        
        if os.path.exists(temp_video_path):
            print("✅ 裁剪完成")
            return temp_video_path
        else:
            return video_path
    except Exception as e:
        print(f"❌ 裁剪过程出错: {e}")
        return video_path

def call_vision_agent_api(video_path: str, prompts: list) -> list:
    """调用Vision Agent API进行视频目标检测"""
    print(f"\n🔍 调用Vision Agent API...")
    print(f"🎯 检测目标: {prompts}")
    
    url = "https://api.va.landing.ai/v1/tools/text-to-object-detection"
    api_key = os.getenv('VISION_AGENT_API_KEY')
    
    files = {"video": open(video_path, "rb")}
    data = {"prompts": prompts, "model": "owlv2", "function_name": "owl_v2_video"}
    headers = {"Authorization": f"Basic {api_key}"}
    
    try:
        print("📡 发送API请求...")
        print(f"url: {url}")
        print(f"files: {str(files)[:100]}")
        print(f"data: {data}")
        print(f"headers: {headers}")
        response = requests.post(url, files=files, data=data, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ API调用成功")
            print("="*100)
            print(result)
            print("="*100)
            return result.get('data', [])
        else:
            error_msg = f"API请求失败: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
            raise Exception(error_msg)
            
    except Exception as e:
        print(f"❌ API调用异常: {e}")
        raise e
    finally:
        files["video"].close()

def convert_api_detections_to_tracked_format(api_detections: list) -> tuple:
    """将API检测结果转换为跟踪格式"""
    print("\n🔄 转换API检测结果格式...")
    
    ball_tracked, racket_tracked, player_tracked = [], [], []
    
    for frame_detections in api_detections:
        frame_ball, frame_racket, frame_player = [], [], []
        
        for detection in frame_detections:
            converted_detection = {
                "bbox": detection["bounding_box"],
                "score": detection["score"],
                "label": detection["label"]
            }
            
            label_lower = detection['label'].lower()
            if "ball" in label_lower:
                frame_ball.append(converted_detection)
            elif "racket" in label_lower:
                frame_racket.append(converted_detection)
            elif "player" in label_lower:
                frame_player.append(converted_detection)
        
        ball_tracked.append(frame_ball)
        racket_tracked.append(frame_racket)
        player_tracked.append(frame_player)
    
    print(f"📊 检测结果: 网球{sum(len(f) for f in ball_tracked)}, 球拍{sum(len(f) for f in racket_tracked)}, 运动员{sum(len(f) for f in player_tracked)}")
    return ball_tracked, racket_tracked, player_tracked

def extract_frames_from_video(video_path: str) -> tuple:
    """从视频中提取帧数据"""
    print("\n📽️ 从视频提取帧数据...")
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames_list = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames_list.append(frame_rgb)
    
    cap.release()
    print(f"✅ 提取完成: {len(frames_list)} 帧, {fps:.2f} fps")
    return frames_list, fps


# ===== 过滤网球，仅保留一个网球 =====
def filter_tennis_ball(ball_tracked: list, racket_tracked: list) -> list:
    """
    过滤网球，仅保留一个网球。要求：
    1. 保证运动轨迹连续的网球
    2. 一定过滤掉和网球拍重叠的网球
    3. 过滤掉置信度小于0.3的网球

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
            # 首先检查置信度，过滤掉置信度小于0.3的网球
            confidence = ball.get("score", 0)
            if confidence < 0.3:
                continue
                
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
    
    # 如果没找到参考网球，选择第一个检测到的网球（仍需满足置信度要求）
    if reference_ball is None:
        for i in range(len(ball_tracked)):
            if ball_tracked[i]:
                valid_balls = [ball for ball in ball_tracked[i] if ball.get("score", 0) >= 0.3]
                if valid_balls:
                    reference_frame_idx = i
                    reference_ball = valid_balls[0]
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
                    
                    print(f"未找到高质量参考网球，使用第一个满足置信度要求的网球! 帧索引: {i}")
                    break
    
    # 如果仍然没有找到任何网球，返回空结果
    if reference_ball is None:
        print("错误: 未能找到任何满足置信度要求的网球！")
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
            # 首先检查置信度，过滤掉置信度小于0.3的网球
            confidence = ball.get("score", 0)
            if confidence < 0.3:
                continue
                
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
            # 首先检查置信度，过滤掉置信度小于0.3的网球
            confidence = ball.get("score", 0)
            if confidence < 0.3:
                continue
                
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
    过滤球拍，仅保留一个球拍。
    简化逻辑：在每帧中选择置信度最高的球拍，剔除置信度小于0.3的球拍。
    
    Parameters:
    -----------
    racket_tracked: list
        owlv2_sam2_video_tracking返回的球拍检测结果
    player_tracked: list
        过滤后的网球运动员检测结果（此参数保留但不使用）
        
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
    filtered_racket = []
    
    # 对每一帧进行处理
    for i in range(len(racket_tracked)):
        frame_rackets = racket_tracked[i]
        
        # 如果当前帧没有检测到球拍
        if not frame_rackets:
            filtered_racket.append([])
            continue
        
        # 先过滤掉置信度小于0.3的球拍
        valid_rackets = [racket for racket in frame_rackets if racket.get("score", 0) >= 0.3]
        
        # 如果过滤后没有有效的球拍
        if not valid_rackets:
            filtered_racket.append([])
            continue
        
        # 在有效的球拍中找到置信度最高的球拍
        best_racket = None
        max_confidence = -1
        
        for racket in valid_rackets:
            confidence = racket.get("score", 0)
            if confidence > max_confidence:
                max_confidence = confidence
                best_racket = racket
        
        # 添加置信度最高的球拍到结果中
        if best_racket:
            filtered_racket.append([best_racket])
        else:
            filtered_racket.append([])
    
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


def overlay_bounding_boxes(image, boxes):
    """在图像上叠加边界框"""
    result = image.copy()
    
    for box in boxes:
        bbox = box["bbox"]
        label = box.get("label", "")
        color = box.get("color", (255, 0, 0))
        score = box.get("score", 0)
        
        # 绘制边界框
        cv2.rectangle(result, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
        
        # 绘制标签
        if label:
            # 如果有置信度分数，添加到标签中
            if score > 0:
                display_label = f"{label} {score:.2f}"
            else:
                display_label = label
            
            # 计算文本大小以确定背景框大小
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            (text_width, text_height), baseline = cv2.getTextSize(display_label, font, font_scale, thickness)
            
            # 绘制文本背景框
            cv2.rectangle(result, 
                         (int(bbox[0]), int(bbox[1] - text_height - 10)), 
                         (int(bbox[0] + text_width), int(bbox[1])), 
                         color, -1)
            
            # 绘制文本
            cv2.putText(result, display_label, (int(bbox[0]), int(bbox[1] - 5)), 
                       font, font_scale, (0, 0, 0), thickness)
    
    return result


def save_video_with_with_detection_boxes(output_dir: str, filename: str, frames_list: list, 
                                         ball_tracked: list, racket_tracked: list, player_tracked: list, 
                                         contact_frame: int, prep_frame: int, follow_frame: int, fps: int = 24):
    """
    保存最佳接触帧的完整动作视频，包含准备、接触和跟随三个阶段
    
    Parameters:
    -----------
    output_dir: str
        输出目录
    filename: str
        文件名
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
    fps: int
        帧率
        
    Returns:
    --------
    str:
        保存的视频路径
    """
    print(f"\n保存完整动作视频: {output_dir}/{filename}...")
     # 为每一帧添加检测框
    frames_with_boxes = []
    for i, frame in enumerate(frames_list):
        current_frame_idx = i
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
        frames_with_boxes.append(frame_with_boxes)
    
    # 保存完整动作视频
    output_path = os.path.join(output_dir, filename)
    save_video(frames_with_boxes, output_path, fps=fps)
    return output_path


def process_tennis_video(video_path: str, output_dir: str) -> dict:
    """使用新API处理网球视频，检测击球动作的关键帧"""
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"===== 开始处理网球视频: {video_path} =====")
    print(f"输出结果将保存在目录: {output_dir}")

    try:
        # 1. 检查并裁剪视频
        processed_video_path = trim_video_if_needed(video_path)
        
        # 2. 调用API进行目标检测
        prompts = ["moving tennis ball with motion blur", "tennis racket", "tennis player"]
        api_detections = call_vision_agent_api(processed_video_path, prompts)
        
        if not api_detections:
            raise ValueError("API未返回任何检测结果")
        
        # 3. 转换API结果格式
        ball_tracked, racket_tracked, player_tracked = convert_api_detections_to_tracked_format(api_detections)
        print("="*50)
        print(f"ball_tracked: {len(ball_tracked)}")
        print(f"racket_tracked: {len(racket_tracked)}")
        print(f"player_tracked: {len(player_tracked)}")
        print("="*50)
        
        # 4. 提取视频帧
        frames_list, actual_fps = extract_frames_from_video(processed_video_path)
        
        # 确保数据长度一致
        min_length = min(len(frames_list), len(ball_tracked), len(racket_tracked), len(player_tracked))
        frames_list = frames_list[:min_length]
        ball_tracked = ball_tracked[:min_length]
        racket_tracked = racket_tracked[:min_length]
        player_tracked = player_tracked[:min_length]
        
        # 5. 过滤检测结果 (剔除部分检测误差大的帧)
        print("\n🔍 过滤检测结果...")
        filtered_player_tracked = filter_player(player_tracked)
        filtered_racket_tracked = filter_racket(racket_tracked, filtered_player_tracked)
        filtered_ball_tracked = filter_tennis_ball(ball_tracked, filtered_racket_tracked)
        
        # 6. 选择关键帧
        print("\n🎯 选择关键帧...")
        contact_frame = select_contact_frame(filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        prep_frame = select_preparation_frame(contact_frame, filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        follow_frame = select_follow_frame(contact_frame, filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        
        # 7. 保存关键帧图片
        print("\n💾 保存关键帧图片...")
        prep_frame_path = os.path.join(output_dir, "preparation_frame.jpg")
        contact_frame_path = os.path.join(output_dir, "contact_frame.jpg")
        follow_frame_path = os.path.join(output_dir, "follow_frame.jpg")

        cv2.imwrite(prep_frame_path, cv2.cvtColor(frames_list[prep_frame], cv2.COLOR_RGB2BGR))
        cv2.imwrite(contact_frame_path, cv2.cvtColor(frames_list[contact_frame], cv2.COLOR_RGB2BGR))
        cv2.imwrite(follow_frame_path, cv2.cvtColor(frames_list[follow_frame], cv2.COLOR_RGB2BGR))
        
        # 8. 保存视频: 完整的单个击球动作视频
        output_video_path = save_video_with_with_detection_boxes(
            output_dir, "output_video.mp4", frames_list,
            ball_tracked, racket_tracked, player_tracked,
            contact_frame, prep_frame, follow_frame)

        # 保存视频: 过滤后的完整检测视频
        filtered_video_path = save_video_with_with_detection_boxes(
            output_dir, "filtered_output_video.mp4", frames_list, 
            filtered_ball_tracked, filtered_racket_tracked, filtered_player_tracked,
            contact_frame, prep_frame, follow_frame)
        
        # 9. 清理临时文件
        if processed_video_path != video_path:
            try:
                os.remove(processed_video_path)
                temp_dir = os.path.dirname(processed_video_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception as e:
                print(f"⚠️ 清理临时文件时出错: {e}")
        
        # 10. 返回结果
        result = {
            "preparation_frame": prep_frame_path,
            "contact_frame": contact_frame_path,
            "follow_frame": follow_frame_path,
            "output_video": output_video_path,
            "filtered_output_video": filtered_video_path,
        }
        
        print("\n✅ 视频处理完成！")
        return result
        
    except Exception as error:
        print(f"\n❌ 处理过程中出错: {error}")
        raise error


# 测试函数
if __name__ == "__main__":
    print(f"当前目录: {os.getcwd()}")
    video_path = "/Users/claude89757/github/wechat-on-airflow/dags/tennis_dags/ai_tennis_dags/action_score_v4_local_file/videos/roger.mp4"
    output_dir = "/Users/claude89757/github/wechat-on-airflow/dags/tennis_dags/ai_tennis_dags/action_score_v4_local_file/videos/output"
    
    result = process_tennis_video(video_path, output_dir)
    
    print("\n🎉 测试完成！")
    print("="*50)
    import json
    print(f"result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    print("="*50)
