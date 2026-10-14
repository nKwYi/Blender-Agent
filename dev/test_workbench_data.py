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
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
STATES = ["idle", "clarify", "options", "running", "done", "partial", "failed"]
# Task 4 实测的每状态 ID 数（brief Step 1 要求精确匹配）
EXPECT_ID_COUNTS = {"idle": 5, "clarify": 5, "options": 8, "running": 5,
                    "done": 5, "partial": 5, "failed": 5}

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
            # 精确值，不是 >= 5：options 若悄悄把三张卡全丢掉，ID 数会掉到 5，
            # 用 >= 就放行了（实测：idle 5 / clarify 5 / options 8 / 其余各 5）。
            got = len([i for i in ids if i])
            ck("layout_ids_%s" % s, got == EXPECT_ID_COUNTS[s],
               "带 ID 的节点应为 %d 个，实际 %d" % (EXPECT_ID_COUNTS[s], got))
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
            txt = None
        if txt is not None:
            # 解码成功本身就是 utf8_* 的判据，所以这里恒真；真正的检查在上面的 except。
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
            api_doc = json.load(fh)
        with open(css, encoding="utf-8") as fh:
            css_txt = fh.read().lower()
        # 注释里的示例色值不算，先去掉 /* */ 注释再扫 style.css
        scan = re.sub(r"/\*.*?\*/", "", css_txt, flags=re.S)
        used = sorted(set(re.findall(r"#[0-9a-f]{3,6}\b", scan)))
        # 许可集 = native_api.json 里所有「整串就是色值」的字符串值，按集合比较。
        # 不能用 `c in api_txt` 子串包含：native_api.json 只要在散文里"提到"过
        # 某个色值（"推荐 #123456"），子串法就会放行 style.css 里的同款颜色。
        allowed = set(_hex_values(api_doc))
        alien = [c for c in used if c not in allowed]
        ck("colors_from_native", not alien,
           "style.css 出现 native_api.json 里没有的颜色：%s" % alien)
        ck("colors_used", len(used) >= 5, "style.css 几乎没用主题色：%s" % used)

    dom_key_check()

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


def _hex_values(doc):
    """递归收集 JSON 里整串就是一个色值的字符串（忽略散文里的顺带提及）。"""
    out = []
    stack = [doc]
    while stack:
        cur_ = stack.pop()
        if isinstance(cur_, dict):
            stack.extend(cur_.values())
        elif isinstance(cur_, list):
            stack.extend(cur_)
        elif isinstance(cur_, str):
            v = cur_.strip().lower()
            if re.fullmatch(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?|#[0-9a-f]{6}", v):
                out.append(v)
    return out


BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for p in BROWSERS:
        if p and os.path.exists(p):
            return p
    return None


def dom_key_check():
    """在真实浏览器里渲染 7 个状态，核对渲染出来的标注键。

    这是唯一能杀掉「无名节点共用一个标注键」那种 bug 的断言：Python 侧只看
    data/layout/*.json 的话，看不到 app.js 算出来的键。
    不变量：N 个树节点必须产出 N 个互不相同的 data-akey。
    """
    exe = find_browser()
    if not exe:
        print("WARN 找不到 Edge/Chrome，跳过 dom_key_check"
              "（渲染键唯一性未被验证）")
        return
    url_base = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    profile = tempfile.mkdtemp(prefix="uw_dom_")
    try:
        for s in STATES:
            try:
                p = subprocess.run(
                    [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                     "--no-default-browser-check", "--user-data-dir=" + profile,
                     "--window-size=1400,1100", "--virtual-time-budget=8000",
                     "--dump-dom", "%s#%s" % (url_base, s)],
                    capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                ck("dom_%s" % s, False, "浏览器调用失败：%s" % exc)
                continue
            html = p.stdout.decode("utf-8", "replace")
            akeys = re.findall(r'data-akey="([^"]*)"', html)
            nodes = len(re.findall(r'class="node[ "]', html))
            uniq = sorted(set(akeys))
            ck("dom_%s_nodes" % s, nodes > 0, "树没渲染出来")
            ck("dom_%s_keys" % s, len(akeys) == nodes,
               "data-akey 个数 %d != 节点数 %d" % (len(akeys), nodes))
            ck("dom_%s_keys_unique" % s, len(uniq) == len(akeys),
               "标注键有碰撞：%d 个节点只产出 %d 个键，例如 %s"
               % (len(akeys), len(uniq), _dups(akeys)))
            ck("dom_%s_keys_scoped" % s,
               all(k.startswith(s + "|") for k in akeys),
               "标注键没带状态前缀")
            print("   %-8s nodes=%-3d uniq_keys=%d" % (s, nodes, len(uniq)))
        # options 的三张规格卡必须拿到三个不同的键（且带路径，不是裸 ID）
        card_keys = []
        try:
            p = subprocess.run(
                [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--user-data-dir=" + profile,
                 "--window-size=1400,1100", "--virtual-time-budget=8000",
                 "--dump-dom", "%s#options" % url_base],
                capture_output=True, timeout=120)
            html = p.stdout.decode("utf-8", "replace")
            card_keys = re.findall(
                r'data-eid="chat\.options" data-akey="([^"]*)"', html)
            if not card_keys:  # 属性顺序不同时兜底
                blocks = re.findall(r'<div class="node[^"]*"[^>]*>', html)
                card_keys = [b for b in blocks if 'data-eid="chat.options"' in b]
                card_keys = [re.search(r'data-akey="([^"]*)"', b).group(1)
                             for b in card_keys]
        except (OSError, subprocess.SubprocessError) as exc:
            ck("dom_options_card_keys", False, "浏览器调用失败：%s" % exc)
            return
        ck("dom_options_card_keys", len(card_keys) == 3,
           "三张规格卡应产出 3 个键，实际 %d：%s" % (len(card_keys), card_keys))
        ck("dom_options_cards_distinct", len(set(card_keys)) == len(card_keys),
           "三张规格卡共用了同一个标注键：%s" % card_keys)
        ck("dom_options_cards_have_path",
           all("@" in k for k in card_keys),
           "规格卡键里没有路径，无法区分同名节点：%s" % card_keys)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _dups(seq):
    seen = set()
    out = set()
    for x in seq:
        if x in seen:
            out.add(x)
        seen.add(x)
    return sorted(out)[:3]


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
