#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from ultralytics import YOLO 
import cv2
import pickle


class PlayerTracker:
    def __init__(self, model_path, batch_size=4):
        self.model = YOLO(model_path)
        self.batch_size = batch_size

    def detect_frames(self, frames, read_from_stub=False, stub_path=None):
        if read_from_stub and stub_path is not None:
            with open(stub_path, 'rb') as f:
                return pickle.load(f)

        player_detections = []
        total_frames = len(frames)
        
        # 批量处理帧
        for i in range(0, total_frames, self.batch_size):
            batch_frames = frames[i:i + self.batch_size]
            results = self.model.track(batch_frames, persist=True)
            
            # 处理每个批次的结果
            for result in results:
                player_dict = {}
                if result.boxes is not None:
                    for box in result.boxes:
                        try:
                            track_id = int(box.id.tolist()[0])
                            bbox = box.xyxy.tolist()[0]
                            object_cls_id = box.cls.tolist()[0]
                            object_cls_name = result.names[object_cls_id]
                            if object_cls_name == "person":
                                player_dict[track_id] = bbox
                        except Exception as error:
                            print(f"处理检测框时出错: {error}")
                
                player_detections.append(player_dict)
            
            # 打印进度
            print(f"已处理: {min(i + self.batch_size, total_frames)}/{total_frames} 帧")

        if stub_path is not None:
            with open(stub_path, 'wb') as f:
                pickle.dump(player_detections, f)
        
        return player_detections

    def draw_bboxes(self,video_frames, player_detections):
        output_video_frames = []
        for frame, player_dict in zip(video_frames, player_detections):
            # Draw Bounding Boxes
            for track_id, bbox in player_dict.items():
                x1, y1, x2, y2 = bbox
                cv2.putText(frame, f"Player ID: {track_id}",(int(bbox[0]),int(bbox[1] -10 )),cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
            output_video_frames.append(frame)
        
        return output_video_frames


    