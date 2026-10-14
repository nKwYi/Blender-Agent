import re

def _clean_md(text):
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^#+\s*", "", t)
    return t.strip()

def parse_interactive_options(text):
    lines = (text or "").split("\n")
    intro_lines = []
    questions = []
    outro_lines = []
    
    current_q = None
    
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        clean = _clean_md(line)
        
        # 过滤预检噪音
        if "目前场景中仅有" in clean or "并不冲突或需要保留" in clean or "分析：目前场景" in clean:
            continue
            
        # 结语识别
        if any(k in clean for k in ["回复这几点", "按推荐来", "直接说", "欢迎随时告诉我", "我就开始车削", "开始建模"]):
            if current_q:
                questions.append(current_q)
                current_q = None
            outro_lines.append(clean)
            continue
            
        # 1. 识别单行问题：如 1. 杯型风格：A / B / C（推荐：A） 或 1. 款式（推荐：A / B）
        clean_numbered = re.sub(r"^[-*•\s]+", "", clean).strip()
        num_match = re.match(r"^([1-9][.、\s]+[^：:\n\r]+)[：:]([^\n\r]+)", clean_numbered)
        if num_match:
            raw_title = num_match.group(1).strip()
            rest = num_match.group(2).strip()
            clean_title = re.sub(r"[（(【].*", "", raw_title).strip()

            # 提取推荐值（支持在标题括号内或在后文内）
            rec_val = ""
            rec_match = re.search(r"[（(【]?推荐[：:\s]*([^）)】/]+)", clean)
            if rec_match:
                rec_val = rec_match.group(1).strip(" ；;，,")

            opts = []
            if "/" in rest:
                raw_opts = [o.strip(" ）)】;；") for o in rest.split("/") if o.strip(" ）)】;；")]
                for ro in raw_opts:
                    ro_clean = re.sub(r"^[;；\s]*也可选\s*", "", ro).strip()
                    is_rec = bool(rec_val and (rec_val in ro_clean or ro_clean in rec_val))
                    opts.append({
                        "label": f"{ro_clean[:14]} ★" if is_rec else ro_clean[:16],
                        "value": ro_clean,
                        "is_rec": is_rec
                    })
            elif rec_val:
                opts.append({
                    "label": f"{rec_val[:14]} ★",
                    "value": rec_val,
                    "is_rec": True
                })
            elif "要/不要" in clean:
                opts.append({"label": "要配套细节 ★", "value": f"带{rest.strip(' ）)】')}", "is_rec": True})
                opts.append({"label": "不要配套细节", "value": "仅基础款，不要椅脚抱枕等配件", "is_rec": False})

            if opts:
                if current_q:
                    questions.append(current_q)
                    current_q = None
                questions.append({
                    "title": clean_title,
                    "rec_value": rec_val,
                    "options": opts
                })
                continue
            
        # 2. 识别换行型问题标题：如 1. 派系风格 或 **1. 派系风格**
        q_match = re.match(r"^(?:[#*]*\s*)?([1-9][.、\s]+[^\n\r]+)", clean)
        if q_match and ("风格" in clean or "尺寸" in clean or "材质" in clean or "把手" in clean or "结构" in clean or "偏好" in clean or "容量" in clean or any(f"{i}." in clean[:4] for i in range(1, 10))):
            if current_q:
                questions.append(current_q)
            current_q = {"title": clean, "rec_value": "", "options": []}
            continue
            
        if current_q is not None:
            # 选项行: - A. ... 或 A. ...
            if re.match(r"^[-*•\s]*[A-Z0-9][.、\s)]", clean) or clean.startswith("- ") or clean.startswith("• "):
                opt_text = re.sub(r"^[-*•\s]*", "", clean)
                is_rec = "推荐" in opt_text or "★" in opt_text
                val = re.sub(r"[（(【].*?推荐.*?[）)】]", "", opt_text).strip()
                val = re.sub(r"^[A-Z0-9][.、\s)]*", "", val).strip()
                current_q["options"].append({
                    "label": f"{val[:14]} ★" if is_rec else val[:16],
                    "value": val,
                    "is_rec": is_rec
                })
                if is_rec and not current_q["rec_value"]:
                    current_q["rec_value"] = val
                continue
            else:
                questions.append(current_q)
                current_q = None
                intro_lines.append(clean)
                continue
                
        if not questions:
            intro_lines.append(clean)
        else:
            outro_lines.append(clean)
            
    if current_q:
        questions.append(current_q)
        
    # 汇总所有推荐值组合为一键开始指令
    rec_pieces = [q["rec_value"] or (q["options"][0]["value"] if q["options"] else "") for q in questions]
    rec_pieces = [p for p in rec_pieces if p]
    all_rec = "，".join(rec_pieces)
    if all_rec:
        all_rec = f"按推荐参数建模：{all_rec}"
    else:
        all_rec = "全部按推荐参数开始建模！"
        
    return {
        "intro": " ".join(intro_lines),
        "questions": questions,
        "all_recommended": all_rec,
        "outro": " ".join(outro_lines)
    }

# 1. 测试咖啡杯样本
coffee_sample = """好的，做个咖啡杯～动手前先跟你确认几个细节：
1. 杯型风格：经典直筒微收口 / 鼓腹圆润 / 手作厚壁窑变（推荐：直筒微收口，最百搭）
2. 容量尺寸：意式浓缩 80ml（小口杯） / 日常马克 300ml / 大杯 450ml（推荐：300ml，口径约 8.6cm，高约 9.5cm，壁厚 2.5mm）
3. 把手：单侧圆管把手 / 无把手厚壁杯 / 双耳杯（推荐：单侧圆管把手）
4. 材质配色：白瓷亮光 / 哑光陶瓷 / 深色釉面 + 咖啡液（推荐：白瓷亮光，内盛约七分满咖啡液）
• 回复这几点或直接说“按推荐来”，我就开始车削成型。"""

res = parse_interactive_options(coffee_sample)
assert len(res["questions"]) == 4, f"Expected 4 questions, got {len(res['questions'])}"
assert "直筒微收口" in res["all_recommended"]
assert "300ml" in res["all_recommended"]
assert "单侧圆管把手" in res["all_recommended"]
assert "白瓷亮光" in res["all_recommended"]

# 2. 测试红色沙发样本（用户最新实测样本）
sofa_sample = """好嘞，红色沙发这个我可以做！在动手前先跟你确认几个细节：
你确认后我就按你选的参数一次性车削出主体轮廓、熔接靠背
扶手、再赋予 PBR 材质。
• 1. 款式（推荐：现代简约直排三人沙发；也可选 L 型贵妃榻 / 复古拉扣布艺）
• 2. 尺寸（推荐：三人位 2.0m × 0.9m × 高 0.82m，座高 0.42m）
• 3. 材质（推荐：微绒 / 科技布暗红（1，0.0...面皮革 0.25 反射））
• 4. 配套细节（要/不要：木质锥形椅脚、抱枕、坐垫分缝）"""

s_res = parse_interactive_options(sofa_sample)
assert len(s_res["questions"]) == 4, f"Expected 4 questions in sofa, got {len(s_res['questions'])}"
assert s_res["questions"][0]["title"] == "1. 款式"
assert s_res["questions"][1]["title"] == "2. 尺寸"
assert s_res["questions"][2]["title"] == "3. 材质"
assert s_res["questions"][3]["title"] == "4. 配套细节"
assert "三人沙发" in s_res["all_recommended"]
assert "微绒" in s_res["all_recommended"]

# 3. 测试隔离存储算法（防止逗号切碎长选项，防止选材质取消尺寸）
import json

def simulate_json_select(sel_json, q_idx, opt_text, is_multi=False):
    sel = json.loads(sel_json or "{}")
    k = str(q_idx)
    cur = sel.get(k, [])
    if is_multi:
        if opt_text in cur:
            cur.remove(opt_text)
        else:
            cur.append(opt_text)
        sel[k] = cur
    else:
        if cur == [opt_text]:
            sel[k] = []
        else:
            sel[k] = [opt_text]
    return json.dumps(sel, ensure_ascii=False)

s0 = "{}"
# 用户选择尺寸（包含大量逗号与分号）
size_text = "口径 8.5cm, 高 6.5cm, 壁厚 2.5mm, 容量约 120ml; 或做成 6cm 口径的小品茶盏"
s1 = simulate_json_select(s0, 1, size_text)
assert json.loads(s1)["1"] == [size_text]

# 用户接着点击材质（胎体 / 素胎陶）
s2 = simulate_json_select(s1, 2, "素胎陶")
# 检验：问题 1 的尺寸丝毫未受影响，依然完整存在！
assert json.loads(s2)["1"] == [size_text]
assert json.loads(s2)["2"] == ["素胎陶"]

# 拼接最终指令
sel_dict = json.loads(s2)
all_chosen = []
for k in sorted(sel_dict.keys(), key=lambda x: int(x)):
    for val in sel_dict[k]:
        if val and val not in all_chosen:
            all_chosen.append(val)
final_cmd = f"参数已确认：{'；'.join(all_chosen)}，开始建模！"
# 验证：绝不重复加载！
assert final_cmd.count("口径 8.5cm") == 1
assert final_cmd == f"参数已确认：{size_text}；素胎陶，开始建模！"

print("ALL UNIT TESTS IN test_interactive_cards.py PASSED SUCCESSFULLY!")
