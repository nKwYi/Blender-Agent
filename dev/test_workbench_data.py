# -*- coding: utf-8 -*-
"""工作台数据完整性检查。纯标准库，不进 Blender。

除 brief Step 1 的基线断言外，另加四条与本任务硬约束直接对应的断言：
  * 三个源文件不得含 NUL 字节（禁字节级读写，避免中文文件写坏）
  * data/data.js 存在且含全部 8 个键（file:// 下唯一的取数途径）
  * app.js / style.css 同样不得引用远程资源
  * style.css 里出现的每个十六进制色值都必须能在 native_api.json 里查到
    （配色铁律：不得凭空发明颜色）
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
STATES = ["idle", "clarify", "options", "running", "done", "partial", "failed"]

FAILS = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def main():
    ck("index_exists", os.path.exists(os.path.join(WB, "index.html")), "缺 index.html")
    ck("app_exists", os.path.exists(os.path.join(WB, "app.js")), "缺 app.js")
    ck("style_exists", os.path.exists(os.path.join(WB, "style.css")), "缺 style.css")
    ck("constraints_exists", os.path.exists(os.path.join(WB, "constraints.json")), "缺 constraints.json")

    for s in STATES:
        lp = os.path.join(WB, "data", "layout", "%s.json" % s)
        sp = os.path.join(WB, "data", "shots", "%s.png" % s)
        ck("layout_%s" % s, os.path.exists(lp), "缺布局树")
        ck("shot_%s" % s, os.path.exists(sp), "缺截图")
        if os.path.exists(lp):
            with open(lp, encoding="utf-8") as fh:
                tree = json.load(fh)
            ck("layout_parse_%s" % s, tree.get("state") == s, "state 字段不匹配")
            ids = []
            _walk(tree, ids)
            ck("layout_ids_%s" % s, len([i for i in ids if i]) >= 5,
               "带 ID 的节点太少：%d" % len([i for i in ids if i]))
        if os.path.exists(sp):
            ck("shot_size_%s" % s, os.path.getsize(sp) > 8000, "截图疑似空文件")

    html = ""
    if os.path.exists(os.path.join(WB, "index.html")):
        with open(os.path.join(WB, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
    ck("no_remote_assets", "http://" not in html and "https://" not in html,
       "工作台必须完全离线，不得引用远程资源")
    # 断言名字只用下划线，方便变异脚本用 \w 抓取；并且要求两个视图按钮真的存在，
    # 而不是靠 "mirror" 这个子串（"mirrorx" 也能蒙混过关）。
    ck("has_view_switch", 'data-view="mirror"' in html and 'data-view="proposal"' in html,
       "index.html 必须同时声明镜像视图与提案视图")
    ck("has_proposal_slots", all(x in html for x in
       ("id=\"vocab-bar\"", "id=\"canvas\"", "id=\"prop-notes\"")),
       "提案视图的挂载点缺失，Task 7 无法接入")

    # --- 附加断言 ---
    for fn in ("index.html", "app.js", "style.css"):
        tag = fn.replace(".", "_")
        p = os.path.join(WB, fn)
        if not os.path.exists(p):
            ck("nul_" + tag, False, "文件不存在")
            continue
        with open(p, "rb") as fh:
            raw = fh.read()
        ck("nul_" + tag, b"\x00" not in raw, "含 NUL 字节，疑似字节级写坏")
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            ck("utf8_" + tag, False, "不是合法 UTF-8：%s" % exc)
            continue
        ck("utf8_" + tag, True)
        ck("offline_" + tag, "http://" not in txt and "https://" not in txt,
           "引用了远程资源")

    dj = os.path.join(WB, "data", "data.js")
    ck("data_js_exists", os.path.exists(dj), "缺 data/data.js，先跑 dev/build_data_js.py")
    if os.path.exists(dj):
        with open(dj, encoding="utf-8") as fh:
            body = fh.read()
        ck("data_js_global", "window.UW_DATA" in body, "data.js 未设置 window.UW_DATA")
        m = re.search(r"window\.UW_DATA\s*=\s*(\{.*\});?\s*$", body, re.S)
        if not m:
            ck("data_js_parse", False, "data.js 不是 window.UW_DATA = {...}; 形态")
        else:
            try:
                payload = json.loads(m.group(1))
            except ValueError as exc:
                payload = None
                ck("data_js_parse", False, "data.js 内容不是合法 JSON：%s" % exc)
            if payload is not None:
                ck("data_js_parse", True)
                want = ["constraints"] + ["layout/" + s for s in STATES]
                missing = [k for k in want if k not in payload]
                ck("data_js_keys", not missing, "data.js 缺键：%s" % missing)
                ck("layout_options_cards",
                   _count_id(payload.get("layout/options"), "chat.options") == 3,
                   "options 树的 chat.options 应为 3 张卡，实际 %d"
                   % _count_id(payload.get("layout/options"), "chat.options"))

    # 配色铁律：style.css 的每个色值都必须来自 native_api.json 实测主题色
    api = os.path.join(WB, "native_api.json")
    css = os.path.join(WB, "style.css")
    if not (os.path.exists(api) and os.path.exists(css)):
        ck("colors_from_native", False, "native_api.json 或 style.css 不存在")
    else:
        with open(api, encoding="utf-8") as fh:
            api_txt = fh.read().lower()
        with open(css, encoding="utf-8") as fh:
            css_txt = fh.read().lower()
        # 注释里的示例色值不算，逐行去掉 /* */ 内联注释后再扫
        scan = re.sub(r"/\*.*?\*/", "", css_txt, flags=re.S)
        used = sorted(set(re.findall(r"#[0-9a-f]{3,6}\b", scan)))
        alien = [c for c in used if c not in api_txt]
        ck("colors_from_native", not alien,
           "style.css 出现 native_api.json 里没有的颜色：%s" % alien)
        ck("colors_used", len(used) >= 5, "style.css 几乎没用主题色：%s" % used)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


def _walk(node, acc):
    acc.append(node.get("element_id"))
    for c in node.get("children", []):
        _walk(c, acc)


def _count_id(node, want, acc=None):
    acc = [] if acc is None else acc
    if not isinstance(node, dict):
        return 0
    if node.get("element_id") == want:
        acc.append(1)
    for c in node.get("children", []) or []:
        _count_id(c, want, acc)
    return len(acc)


main()
