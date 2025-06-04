# 标准库导入
import os
from openai import OpenAI
import base64

from tennis_dags.ai_tennis_dags.action_score_v3_by_url.vision_agent_fuction import process_tennis_video

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import re
from airflow.models import Variable


def get_tennis_action_comment(action_image_path: str, model_name: str = "qwen-vl-max-latest", action_type: str = "击球动作") -> str:
    """
    通过阿里云的AI模型，获取网球动作的评论
    """
    if action_type == "引拍动作":
        action_standard = """
        引拍动作评判标准：
        - 重心转移：身体重心是否自然向后转移
        - 拍头路线：拍面是否拉开到位，形成合适的引拍弧线
        - 手腕固定：手腕是否保持稳定不松散
        - 肩部旋转：肩膀是否充分转动带动上半身
        - 握拍姿势：是否使用适合该击球的标准握法
        """ 
        specific_focus = "重点关注身体重心转移和拍面准备位置"
        common_issues = "常见问题：引拍幅度不足、手腕过于松散、重心未转移"
    elif action_type == "击球动作":
        action_standard = """
        击球动作评判标准：
        - 击球点：是否在最佳击球区域内完成击球
        - 拍面控制：击球瞬间拍面角度是否正确
        - 腿部支撑：下肢是否提供足够稳定的支撑
        - 力量传递：是否从地面经由腿部、核心到手臂形成完整动力链
        - 视线跟踪：眼睛是否始终注视球
        """
        specific_focus = "重点关注击球点位置和拍面控制"
        common_issues = "常见问题：击球点偏后、拍面角度不当、身体失衡"
    elif action_type == "随挥动作":
        action_standard = """
        随挥动作评判标准：
        - 动作完整性：是否完成充分的随挥跟随动作
        - 平衡保持：击球后身体是否保持平衡
        - 重心转移：重心是否自然向前转移
        - 收拍流畅度：是否平稳自然地完成收拍
        - 恢复能力：是否迅速恢复到击球后的准备姿态
        """
        specific_focus = "重点关注随挥完整性和身体平衡"
        common_issues = "常见问题：随挥不充分、收拍过急、身体失衡"
    else:
        raise ValueError(f"不支持的动作类型: {action_type}")

    system_prompt = f"""# Role and Objective
你是一位专业网球教练，拥有20年教学经验，专门负责分析和评估网球运动员的技术动作。你的目标是对照片中运动员的{action_type}进行专业、客观、准确的技术评估。

# Instructions
请仔细观察照片中运动员的{action_type}，并根据国际网球教学标准进行评估。

## 图片有效性检查
在进行技术评估前，必须先验证图片的有效性：
- 图片中是否包含网球运动员
- 是否能清楚看到运动员正在进行网球动作
- 图片是否对应当前要评估的{action_type}
- 图片质量是否足够清晰进行技术分析

## 技术评估标准
{action_standard}

## 评估重点
{specific_focus}

## 注意事项
- 评估时需要考虑动作的连贯性和实用性
- 注重技术动作的标准性和有效性
- {common_issues}
- 如果图片模糊、无关或无法识别网球动作，应明确说明

# Reasoning Steps
请按以下步骤进行分析：

1. **图片验证**：首先验证图片是否包含清晰的网球运动员和相应的{action_type}
2. **整体观察**：观察运动员的整体姿态和动作协调性
3. **细节分析**：逐项检查上述技术标准中的每个要点
4. **优缺点识别**：明确指出动作的优点和需要改进的地方
5. **等级判定**：基于技术标准综合评定等级
6. **建议制定**：针对发现的问题给出具体改进建议

# Output Format
请严格按照以下格式输出评估结果：

## 有效图片的输出格式：
```
评分等级：[S/A/B/C]
动作评价：[8-10字简明点评]
动作建议：[8-10字针对性建议]
```

## 无效图片的输出格式：
```
评分等级：无效
动作评价：图片无法识别网球动作
动作建议：请提供清晰的网球动作图片
```

# Examples

## Example 1 - S级评价示例
```
评分等级：S
动作评价：姿态标准，技术完美
动作建议：保持当前技术水平
```

## Example 2 - B级评价示例
```
评分等级：B
动作评价：基本动作到位，细节待优化
动作建议：注意拍面角度控制
```

## Example 3 - 无效图片示例
```
评分等级：无效
动作评价：图片中无网球运动员
动作建议：请提供包含网球动作的图片
```

## Example 4 - 错误动作类型示例
```
评分等级：无效
动作评价：图片显示的非{action_type}
动作建议：请提供对应的{action_type}图片
```

# Context
- 当前评估的是运动员的{action_type}
- 图片捕捉的是动作的关键瞬间
- 评估需要考虑动作的实战应用价值
- 必须确保图片内容与评估目标匹配

# Final Instructions
请仔细观察图片，首先验证图片的有效性和相关性，然后逐步分析运动员的{action_type}，严格按照技术标准进行评估。如果图片无效、模糊、无关或显示错误的动作类型，请明确指出并要求提供合适的图片。如果动作达到S或A级别，建议可以简化或省略。请确保评价客观、专业、有建设性。

现在请开始分析图片中的{action_type}："""

    #  base 64 编码格式
    def encode_image(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    # 将xxxx/test.png替换为你本地图像的绝对路径
    base64_image = encode_image(action_image_path)
    client = OpenAI(
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
        api_key=Variable.get('DASHSCOPE_API_KEY'),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    # 获取动作评价  
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": [{"type":"text","text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        # 需要注意，传入Base64，图像格式（即image/{format}）需要与支持的图片列表中的Content Type保持一致。"f"是字符串格式化的方法。
                        # PNG图像：  f"data:image/png;base64,{base64_image}"
                        # JPEG图像： f"data:image/jpeg;base64,{base64_image}"
                        # WEBP图像： f"data:image/webp;base64,{base64_image}"
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}, 
                    },
                ],
            }
        ],
    )
    return completion.choices[0].message.content

# 三张动作图片+得分合并到一张长图
def extract_score_from_comment(comment_text):
    """从评论文本中提取分数等级和具体评价"""
    score_level = re.search(r'评分等级：([SABC])', comment_text)
    score_level = score_level.group(1) if score_level else "C"
    
    # 提取各项评价
    evaluations = []
    for line in comment_text.split('\n'):
        if "：" in line and "评分等级" not in line:
            key, value = line.split("：", 1)
            evaluations.append((key, value))
    
    return score_level, evaluations

def create_score_image(width, height, level, color):
    """创建一个带有等级的圆形图像"""
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # 画圆
    draw.ellipse((0, 0, width, height), fill=color)
    
    # 添加等级文字
    font_size = height // 2
    
    # 优先尝试使用已安装的字体
    font_paths = [
        # 已安装的字体包
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",  # Noto CJK 字体
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",         # 文泉驿正黑
        # 备用字体路径
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    
    # 尝试加载字体
    font = None
    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, font_size)
            break
        except Exception:
            continue
    
    # 如果仍然无法加载字体，使用默认字体
    if font is None:
        font = ImageFont.load_default()
        text = level  # 只显示字母S/A/B/C，不显示"级"字
    else:
        text = level
    
    # 计算文本位置并绘制
    # 使用textbbox获取文本边界框
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = right - left
    text_height = bottom - top
    
    # 计算居中位置 - 确保文本真正居中
    position_x = (width - text_width) // 2 - left  # 减去left偏移以修正位置
    position_y = (height - text_height) // 2 - top  # 减去top偏移以修正位置
    
    draw.text((position_x, position_y), text, fill="white", font=font)
    
    return img

def merge_images_with_scores(preparation_image, preparation_score, 
                            contact_image, contact_score,
                            follow_image, follow_score,
                            output_path="/tmp/tennis_analysis.jpg"):
    """合并三张图片和评分为一张长图"""
    # 打开三张图片
    prep_img = Image.open(preparation_image)
    contact_img = Image.open(contact_image)
    follow_img = Image.open(follow_image)
    
    # 调整所有图片为相同宽度
    width = 900  # 增加宽度以适应更多内容
    height = int(width * prep_img.height / prep_img.width)
    
    prep_img = prep_img.resize((width, height))
    contact_img = contact_img.resize((width, height))
    follow_img = follow_img.resize((width, height))
    
    # 解析评分
    prep_level, prep_eval = extract_score_from_comment(preparation_score)
    contact_level, contact_eval = extract_score_from_comment(contact_score)
    follow_level, follow_eval = extract_score_from_comment(follow_score)
    
    # 设置颜色(S和A用绿色，B和C用橙色)
    level_colors = {
        "S": (0, 180, 0),  # 深绿色
        "A": (34, 139, 34),  # 森林绿
        "B": (255, 140, 0),  # 深橙色
        "C": (255, 69, 0)   # 红橙色
    }
    
    prep_color = level_colors.get(prep_level, (255, 128, 0))
    contact_color = level_colors.get(contact_level, (255, 128, 0))
    follow_color = level_colors.get(follow_level, (255, 128, 0))
    
    # 创建分数图标
    score_size = 120
    prep_score_img = create_score_image(score_size, score_size, prep_level, prep_color)
    contact_score_img = create_score_image(score_size, score_size, contact_level, contact_color)
    follow_score_img = create_score_image(score_size, score_size, follow_level, follow_color)
    
    # 设置每个部分的标题
    titles = ["【引拍动作】", "【击球动作】", "【随挥动作】"]
    
    # 加载字体
    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    
    title_font = None
    eval_font = None
    
    for font_path in font_paths:
        try:
            title_font = ImageFont.truetype(font_path, 40)
            eval_font = ImageFont.truetype(font_path, 28)
            break
        except Exception:
            continue
    
    if title_font is None or eval_font is None:
        title_font = ImageFont.load_default()
        eval_font = ImageFont.load_default()
        print("警告：未能加载中文字体，将使用默认字体")
        titles = ["[Preparation]", "[Start]", "[Hitting]"]
    
    # 计算各部分的高度
    # 每个评价项目的高度
    item_height = 45
    # 计算每个部分评价区域所需的高度
    eval_height_prep = (len(prep_eval) * item_height) + 50  # 增加底部边距
    eval_height_contact = (len(contact_eval) * item_height) + 50
    eval_height_follow = (len(follow_eval) * item_height) + 50
    
    # 最大评价区域高度
    max_eval_height = max(eval_height_prep, eval_height_contact, eval_height_follow)
    
    # 每个部分的高度 = 标题(60) + 间距(20) + 图片高度 + 间距(30) + 评价区域高度 + 部分间距(60)
    title_height = 60
    title_margin = 20
    img_eval_margin = 30
    section_margin = 60
    
    section_height = title_height + title_margin + height + img_eval_margin + max_eval_height + section_margin
    
    # 创建最终图像 - 增加高度以确保足够空间
    final_height = section_height * 3 + 50  # 底部增加一些边距
    final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
    draw = ImageDraw.Draw(final_image)
    
    # 计算左边距和评价文本起始位置
    left_margin = 30
    text_start_x = score_size + left_margin + 30
    
    # 绘制三个部分
    for i in range(3):
        # 计算当前部分的起始位置
        y_offset = i * section_height
        
        # 绘制标题
        title_width = draw.textbbox((0, 0), titles[i], font=title_font)[2]
        title_x = (width - title_width) // 2  # 居中
        draw.text((title_x, y_offset + 30), titles[i], fill=(0, 0, 0), font=title_font)
        
        # 确定图片位置
        img_y = y_offset + title_height + title_margin
        
        # 选择当前部分的图片和评分
        if i == 0:
            img = prep_img
            score_img = prep_score_img
            evaluations = prep_eval
        elif i == 1:
            img = contact_img
            score_img = contact_score_img
            evaluations = contact_eval
        else:
            img = follow_img
            score_img = follow_score_img
            evaluations = follow_eval
        
        # 粘贴图片
        final_image.paste(img, (0, img_y))
        
        # 计算评价区域顶部y坐标
        eval_section_top = img_y + height + img_eval_margin
        
        # 粘贴分数图标
        final_image.paste(score_img, (left_margin, eval_section_top), score_img)
        
        # 绘制评价文本
        eval_y = eval_section_top + 10
        for item, value in evaluations:
            text = f"【{item}】 {value}"
            draw.text((text_start_x, eval_y), text, fill=(0, 0, 0), font=eval_font)
            eval_y += item_height
    
    # 保存最终图像
    final_image.save(output_path)
    
    return output_path


def get_tennis_action_score(video_path: str, output_dir: str):
    """
    获取网球动作得分
    """
    print(f"video_path: {video_path}")
    print(f"output_dir: {output_dir}")
    result = process_tennis_video(video_path, output_dir)
    print(f"result: {result}")

    preparation_image = result["preparation_frame"]
    contact_image = result["contact_frame"]
    follow_image = result["follow_frame"]

    # 获取准备动作得分
    preparation_score = get_tennis_action_comment(preparation_image, action_type="引拍动作")
    print(f"preparation_score: {preparation_score}")

    # 获取击球动作得分
    contact_score = get_tennis_action_comment(contact_image, action_type="击球动作")
    print(f"contact_score: {contact_score}")

    # 获取跟随动作得分
    follow_score = get_tennis_action_comment(follow_image, action_type="随挥动作")
    print(f"follow_score: {follow_score}")
    
    # 合并三张图片和评分
    output_image = merge_images_with_scores(
        preparation_image, preparation_score,
        contact_image, contact_score,
        follow_image, follow_score,
        output_path=f"{output_dir}/tennis_analysis_{os.path.basename(video_path).split('.')[0]}.jpg"
    )
    
    # 将合并后的图片路径添加到结果中
    result["analysis_image"] = output_image

    print(f"result: {result}")
    return result
