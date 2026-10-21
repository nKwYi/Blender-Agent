# -*- coding: utf-8 -*-
import re

CIRCLED = {'①': '1.', '②': '2.', '③': '3.', '④': '4.', '⑤': '5.', '⑥': '6.', '⑦': '7.', '⑧': '8.', '⑨': '9.', '⑩': '10.'}

def _clean_md(text):
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^#+\s*", "", t)
    return t.strip()

def _opt_label(text, is_rec=False, limit=16):
    disp = str(text or "").strip()
    m = re.search(r"[（(]([^）)]*)[）)]", disp)
    if m and "推荐" not in m.group(1):
        disp = (disp[:m.start()] + disp[m.end():]).strip(" ·/、,，")
    else:
        cuts = [i for i in (disp.find("（"), disp.find("(")) if i > 0]
        if cuts:
            disp = disp[:min(cuts)].strip(" ·/、,，")
    disp = disp[:limit].rstrip(" ·/、,，")
    return f"{disp} (推荐)" if is_rec else disp

def parse_interactive_options(text):
    raw_text = str(text or "")
    raw_text = re.sub(r"([①②③④⑤⑥⑦⑧⑨⑩])", r"\n\1", raw_text)
    lines = raw_text.split("\n")
    intro_lines = []
    questions = []
    confirm_items = []
    outro_lines = []
    general_lines = []

    current_q = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        clean = _clean_md(line)

        if "目前场景中仅有" in clean or "并不冲突或需要保留" in clean or "分析：目前场景" in clean:
            continue

        if clean.startswith("✔") or clean.startswith("✓") or clean.startswith("- ✓") or clean.startswith("- ✔"):
            item_text = re.sub(r"^[-*•\s]*[✔✓]\s*", "", clean)
            confirm_items.append(item_text)
            continue

        if any(k in clean for k in ["回复这几点", "按推荐来", "直接说", "欢迎随时告诉我", "我就开始车削", "开始建模", "选项编号"]):
            if current_q:
                questions.append(current_q)
                current_q = None
            outro_lines.append(clean)
            continue

        # 归一化序号：将 ①②③... 转换为 1. 2. 3. ...
        norm_line = clean
        for c_char, num_str in CIRCLED.items():
            if norm_line.startswith(c_char):
                norm_line = num_str + " " + norm_line[len(c_char):]
                break

        # 归一化分隔符：将全角斜杠 ／、竖线 ｜/| 替换为半角 /
        norm_line = norm_line.replace("／", "/").replace("｜", "/").replace("|", "/")

        clean_numbered = re.sub(r"^[-*•\s]+", "", norm_line).strip()
        num_match = re.match(r"^([1-9][0-9]?[.、\s\)]+[^：:\n\r]+)[：:]([^\n\r]+)", clean_numbered)
        if num_match:
            raw_title = num_match.group(1).strip()
            rest = num_match.group(2).strip()
            clean_title = re.sub(r"[（(【].*", "", raw_title).strip()
            clean_title = re.sub(r"^[0-9]+[.、\s\)]*", "", clean_title).strip()

            rec_val = ""
            rec_match = re.search(r"[（(【]?推荐[：:\s]*([^）)】/]+)", clean)
            if rec_match:
                rec_val = rec_match.group(1).strip(" ；;，,")

            opts = []
            if "/" in rest:
                raw_opts = [o.strip(" \t；;,，") for o in rest.split("/") if o.strip(" \t；;,，")]
                for ro in raw_opts:
                    is_rec = bool("推荐" in ro or "★" in ro or (rec_val and (rec_val in ro or ro in rec_val)))
                    ro_clean = re.sub(r"[（(【]?\s*推荐[：:\s]*[^）)】]*[）)]?\s*", "", ro)
                    ro_clean = re.sub(r"^[;；\s]*也可选\s*", "", ro_clean).strip(" ；;，,")
                    if is_rec and not rec_val:
                        rec_val = ro_clean
                    opts.append({
                        "label": _opt_label(ro_clean, is_rec),
                        "value": ro_clean,
                        "is_rec": is_rec
                    })
            elif rec_val:
                opts.append({
                    "label": _opt_label(rec_val, True),
                    "value": rec_val,
                    "is_rec": True
                })

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
        else:
            if not questions and not confirm_items:
                intro_lines.append(clean)
            else:
                general_lines.append(clean)

    if current_q:
        questions.append(current_q)

    rec_pieces = [q.get("rec_value", "") or (q["options"][0]["value"] if q.get("options") else "") for q in questions]
    rec_pieces = [p for p in rec_pieces if p]
    all_rec = "，".join(rec_pieces)
    if all_rec:
        all_rec = f"按推荐参数建模：{all_rec}"
    else:
        all_rec = "全部按推荐参数开始建模！"

    return {
        "intro": " ".join(intro_lines),
        "questions": questions,
        "confirm": confirm_items,
        "all_recommended": all_rec,
        "outro": " ".join(outro_lines),
        "general": general_lines,
    }

sample = """雪屋小场景，先确认几个核心细节（括号内是我的推荐）：
① 雪屋风格：冰屋（推荐）／ 半球体+螺旋雪砖 ／ 烟囱的 A 字木屋
② 场景范围：纯雪屋（主体突出，推荐）／ 加旗杆、脚印路径、柴堆等氛围道具 ／ 再加周边雪山远景
③ 尺寸体量：单人间直径 3.5m ／ 家庭版直径 4.5m 带前室隧道入口（推荐）／ 大型 6m 多入口
④ 雪材质：启用 Real Snow 插件真实积雪（推荐）／ 不依赖插件，纯程序化雪材质+风蚀雪丘
直接回复选项编号或按推荐，立刻开始建模。"""

res = parse_interactive_options(sample)
print(f"Questions found: {len(res['questions'])}")
for q in res["questions"]:
    print(f"Q: {q['title']} | Rec: {q['rec_value']}")
    for o in q["options"]:
        print(f"   Option: {o['label']} -> {o['value']} (rec={o['is_rec']})")
print(f"All recommended: {res['all_recommended']}")
print(f"Intro: {res['intro']}")
print(f"Outro: {res['outro']}")
