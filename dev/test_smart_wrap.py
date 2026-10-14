import re

def _clean_md(text):
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^#+\s*", "", t)
    return t.strip()

def parse_ai_message(text):
    """将 AI 回复智能解析为 Figma 风格的结构化分段：
    1. intro: 前导说明句
    2. questions: 追问卡片列表 [{'title': ..., 'options': [...]}]
    3. confirm_items: 复述确认清单 [str]
    4. general_lines: 普通文本/结语
    """
    lines = (text or "").split("\n")
    intro_lines = []
    questions = []
    confirm_items = []
    general_lines = []
    
    current_q = None
    in_questions = False
    
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
            
        clean = _clean_md(line)
        
        # 匹配确认项: ✔ 或 ✓
        if clean.startswith("✔") or clean.startswith("✓") or clean.startswith("- ✓") or clean.startswith("- ✔"):
            item_text = re.sub(r"^[-*•\s]*[✔✓]\s*", "", clean)
            confirm_items.append(item_text)
            continue
            
        # 匹配追问标题: **1. ...** 或 1. ... 或 1 ... 或 ### 1. ...
        q_match = re.match(r"^(?:[#*]*\s*)?([1-9][.、\s]+[^\n\r]+)", clean)
        if q_match and ("风格" in clean or "尺寸" in clean or "材质" in clean or "结构" in clean or "偏好" in clean or "参考" in clean or "容量" in clean or "器型" in clean or "颜色" in clean or any(f"{i}." in clean[:4] for i in range(1, 10))):
            if current_q:
                questions.append(current_q)
            current_q = {"title": clean, "options": []}
            in_questions = True
            continue
            
        if current_q is not None:
            # 选项行: - A. ... 或 A. ... 或 直筒型...
            if re.match(r"^[-*•\s]*[A-Z0-9][.、\s]", clean) or clean.startswith("- ") or clean.startswith("• "):
                opt_text = re.sub(r"^[-*•\s]*", "", clean)
                current_q["options"].append(opt_text)
                continue
            elif in_questions and not any(k in clean for k in ["可以回复", "告诉我", "确认", "下一步"]):
                current_q["options"].append(clean)
                continue
            else:
                # 追问段结束
                questions.append(current_q)
                current_q = None
                in_questions = False
                general_lines.append(clean)
                continue
                
        if not in_questions and not confirm_items:
            # 过滤场景预检无用废话
            if "目前场景中仅有" in clean or "并不冲突或需要保留" in clean:
                continue
            intro_lines.append(clean)
        else:
            general_lines.append(clean)
            
    if current_q:
        questions.append(current_q)
        
    return {
        "intro": intro_lines,
        "questions": questions,
        "confirm": confirm_items,
        "general": general_lines,
    }

# 测试 1: 用户实际运行的运动水杯文本
sample_sports = """已经为您分析：目前场景中仅有 Cube、Light、Camera 三个物体，并不冲突或需要保留...
在动手前，有几个关键细节想跟您确认一下（结合常见款的体验）：
**1. 派系风格**
- A. 直饮运动水杯（带硅胶圈、手提织带，现代简约【推荐】）
- B. 大容量吨吨桶（加宽提手、吸管，适合户外）
- C. 细长保温杯（Stanley 风格渐变防滑，商务感）
**2. 尺寸容量**（决定场景空间比例）
- A. 500ml：瓶身高约 23cm，口径约 7.0cm（推荐）
- B. 750ml：瓶身高约 27cm，口径约 7.4cm
- C. 1000ml：瓶身高约 31cm，口径约 8.0cm
**3. 材质偏好**
- A. 高透明 Tritan（晶莹透亮，适合展示杯内吸管结构【推荐】）
- B. 半透明磨砂（高级哑光质感）
- C. 全金属不锈钢（拉丝保温杯）
**4. 开盖结构**
- A. 弹跳盖（单手开启，运动感强，带锁扣【推荐】）
- B. 旋钮盖（经典紧凑）
- C. 敞口直饮水杯
您可以直接回复选项号（例如“1A 2A 3A 4A”），也可以直接说“按推荐来”，如果对某些方面有偏好，欢迎随时告诉我。"""

res = parse_ai_message(sample_sports)
print("INTRO:", res["intro"])
print("QUESTIONS COUNT:", len(res["questions"]))
for q in res["questions"]:
    print("  Q:", q["title"])
    for o in q["options"]:
        print("     opt:", o)
print("GENERAL:", res["general"])
