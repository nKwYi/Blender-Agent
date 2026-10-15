# -*- coding: utf-8 -*-
"""Task 7：受限词汇表 + 提案画布的验收检查。纯标准库，不进 Blender。

用 UW_ROOT 环境变量可以把被测根目录指向任意副本（变异验证靠这个）：
    $env:UW_ROOT = 'C:\\temp\\mutated'; python dev\\test_proposal_vocab.py
不设时测仓库里的 ui_workbench。

两条腿：
  1. Python 侧查 vocabulary.json / data.js / app.js 的静态性质（schema、数量、
     逐字一致、配色铁律、无远程资源、无 NUL）。
  2. 无头 Edge 侧真渲染提案视图，核对 12 个控件与全部降级方案能不能插入、
     拦截拦不拦得住——静态检查看不到 app.js 算出来的 DOM。
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
ROOT = os.environ.get("UW_ROOT") or os.path.dirname(HERE)
DEV = os.path.join(ROOT, "dev")
WB = os.path.join(ROOT, "ui_workbench")

EXPECT_WIDGETS = 12          # brief Step 2
EXPECT_REJECTED = 9          # constraints.json 里 native_ok=false 的实数（brief 写的 8 是笔误）
DEMO_PROPS = ["size", "color", "scale", "text"]   # size/color 命中 blocked，scale 不在清单，text 合法

FAILS = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def main():
    cons = json.loads(read(os.path.join(WB, "constraints.json")))
    n_no = len([e for e in cons["entries"] if not e["native_ok"]])

    ck("constraints_not_9", n_no == EXPECT_REJECTED,
       "constraints.json 里 native_ok=false 应为 %d 条，实际 %d（词汇表数量按此为准）"
       % (EXPECT_REJECTED, n_no))

    # ---------- 生成器 ----------
    sys.path.insert(0, DEV)
    import build_vocabulary as bv
    vocab = bv.build(cons)

    ck("gen_widget_count", len(vocab["widgets"]) == EXPECT_WIDGETS,
       "widgets 应为 %d，实际 %d" % (EXPECT_WIDGETS, len(vocab["widgets"])))
    ck("gen_reject_count", len(vocab["rejected"]) == EXPECT_REJECTED,
       "rejected 应为 %d，实际 %d" % (EXPECT_REJECTED, len(vocab["rejected"])))
    keys = [w["key"] for w in vocab["widgets"]]
    ck("gen_widget_keys_unique", len(set(keys)) == len(keys), "widget key 重复：%s" % keys)
    # 字段集仍是精确相等：新增 demo / props_example / props_hint 之后，
    # 任何「多出来的字段」照样要红。这不是放宽断言，是把它跟着数据一起长。
    ck("gen_widget_schema", all(
        set(w) == {"key", "label", "uiloayout", "allowed_props", "blocked_props",
                   "note", "constraint_key", "demo", "props_example", "props_hint"}
        for w in vocab["widgets"]), "widget 字段集不对")
    # docstring 承诺「只有 native_ok=true 的能力才能进词汇表」，这条断言把它钉死：
    # 声称依赖某条判定的控件，那条判定必须真的是 native_ok=true
    reg = {e["key"]: e for e in cons["entries"]}
    ck("gen_constraint_key_resolves", all(
        (w["constraint_key"] is None) or (w["constraint_key"] in reg)
        for w in vocab["widgets"]), "有 widget 指向 constraints 里不存在的判定")
    ck("gen_constraint_key_is_ok", all(
        (w["constraint_key"] is None) or reg[w["constraint_key"]]["native_ok"]
        for w in vocab["widgets"]),
       "有 widget 依赖的判定已不是 native_ok=true：%s"
       % [w["key"] for w in vocab["widgets"]
          if w["constraint_key"] and not reg[w["constraint_key"]]["native_ok"]])
    # 而且承诺必须真的被强制：把 constraints 里那条翻脸，build() 要停下来
    bad = json.loads(json.dumps(cons))
    for e in bad["entries"]:
        if e["key"] == "grid_flow":
            e["native_ok"] = False
            e["blocker"] = "翻脸了"
            e["fallback"] = "改用别的"
    try:
        bv.build(bad)
        raised = False
        why = "build() 照发不误"
    except bv.VocabularyError as exc:
        raised = True
        why = str(exc)
    ck("gen_enforces_native_ok", raised, why)
    ck("gen_props_disjoint", all(
        not (set(w["allowed_props"]) & set(w["blocked_props"])) for w in vocab["widgets"]),
        "同一控件的允许清单与拦截清单有交集")
    ck("gen_props_scope_says_subset", bool(vocab.get("props_scope")) and
       "精选子集" in vocab["props_scope"],
       "缺少「allowed_props 是精选子集不是全量 API」的说明")
    ck("gen_reject_schema", all(
        set(r) == {"key", "label", "blocker", "fallback"} for r in vocab["rejected"]),
        "rejected 字段集不对")
    ck("gen_reject_from_nofail", sorted(r["key"] for r in vocab["rejected"]) ==
       sorted(e["key"] for e in cons["entries"] if not e["native_ok"]),
       "rejected 必须与 native_ok=false 的条目一一对应")

    # 降级方案不能是空话：逐字取自 constraints.json，且提到具体手段
    src = json.dumps(cons, ensure_ascii=False)
    ck("gen_fallback_verbatim", all(r["fallback"] and r["fallback"] in src for r in vocab["rejected"]),
       "有 fallback 不是 constraints.json 的原句或为空")
    ck("gen_fallback_actionable", all(
        re.search(r"layout\.|icon=|alert|分页|折叠|active|enabled|#[0-9a-fA-F]{6}", r["fallback"])
        for r in vocab["rejected"]),
       "有 fallback 没给出可执行手段：%s" % [r["key"] for r in vocab["rejected"]
                                          if not re.search(r"layout\.|icon=|alert|分页|折叠|active|enabled|#[0-9a-fA-F]{6}", r["fallback"])])
    ck("gen_blocker_verbatim", all(r["blocker"] and r["blocker"] in src for r in vocab["rejected"]),
       "有 blocker 不是 constraints.json 的原句或为空")

    # 「可做、但词汇表没收录」的能力不许无声消失（Important 3）：
    # progress_bar 在 constraints 里 native_ok=true，却既不在 12 个控件里、
    # 也不在 rejected 里，只能靠这张表在提案视图里显式说出来。
    mapped = set(w["constraint_key"] for w in vocab["widgets"] if w["constraint_key"])
    want_unmapped = sorted(e["key"] for e in cons["entries"]
                           if e["native_ok"] and e["key"] not in mapped)
    ck("gen_unmapped_ok", sorted(u["key"] for u in vocab["unmapped_ok"]) == want_unmapped,
       "unmapped_ok 应为 %s，实际 %s"
       % (want_unmapped, [u["key"] for u in vocab["unmapped_ok"]]))
    ck("gen_unmapped_schema", all(
        set(u) == {"key", "label", "uiloayout", "evidence"} for u in vocab["unmapped_ok"]),
        "unmapped_ok 字段集不对")
    ck("gen_progress_bar_visible", "progress_bar" in want_unmapped,
       "progress_bar 是 native_ok=true 却没人映射，提案视图里会彻底消失")

    # ---------- 落盘产物 ----------
    vp = os.path.join(WB, "vocabulary.json")
    ck("vocab_file_exists", os.path.exists(vp), "缺 ui_workbench/vocabulary.json")
    if os.path.exists(vp):
        raw = open(vp, "rb").read()
        ck("vocab_nul", b"\x00" not in raw, "含 NUL 字节")
        on_disk = json.loads(raw.decode("utf-8"))
        ck("vocab_matches_generator", on_disk == vocab,
           "vocabulary.json 与 build() 输出不一致，需要重跑 dev/build_vocabulary.py")
        ck("vocab_generated_for", on_disk.get("generated_for") == cons["generated_for"],
           "generated_for 没跟着 constraints 走")

    dj = os.path.join(WB, "data", "data.js")
    ck("data_js_has_vocab", os.path.exists(dj), "缺 data/data.js")
    payload = None
    if os.path.exists(dj):
        body = read(dj)
        m = re.search(r"window\.UW_DATA\s*=\s*(\{.*\});?\s*$", body, re.S)
        if m:
            payload = json.loads(m.group(1))
        ck("data_js_vocab_key", payload is not None and "vocabulary" in payload,
           "data/data.js 里没有 vocabulary 键，重跑 python dev\\build_data_js.py")
        if payload is not None and "vocabulary" in payload:
            ck("data_js_vocab_same", payload["vocabulary"] == vocab,
               "data.js 里的 vocabulary 与 vocabulary.json 不一致")

    # ---------- 静态检查 app.js / index.html ----------
    app = read(os.path.join(WB, "app.js"))
    html = read(os.path.join(WB, "index.html"))
    raw = open(os.path.join(WB, "app.js"), "rb").read()
    ck("app_nul", b"\x00" not in raw, "app.js 含 NUL 字节")
    ck("app_no_remote", "http://" not in app and "https://" not in app,
       "app.js 引用了远程资源")
    # 配色铁律：app.js 里不允许出现字面色值（Task 6 只扫 style.css，
    # 这里补上——brief 给的示例代码里有 #e0716a 这种主题里根本没有的红）
    hexes = sorted(set(re.findall(r"#[0-9a-fA-F]{3,6}\b", re.sub(r"/\*.*?\*/", "", app, flags=re.S))))
    ck("app_no_literal_colors", not hexes, "app.js 里出现字面色值：%s" % hexes)

    for fn in ("el(\"vocab-bar\")", "el(\"canvas\")", "el(\"prop-notes\")"):
        ck("app_uses_%s" % re.sub(r"\W", "", fn), fn in app, "app.js 未挂载 %s" % fn)
    ck("app_blocked_check", "w.blocked_props.indexOf(p) >= 0" in app,
       "app.js 丢了 blocked_props 拦截")
    ck("app_allowlist_check", "w.allowed_props.indexOf(p) < 0" in app,
       "app.js 丢了允许清单之外的拦截")
    ck("app_downgraded_flag", "dataset.downgraded" in app and "downgraded: true" in app,
       "降级项没有被标记成降级")
    ck("app_export_proposal", '"proposal": proposal' in app or "proposal: proposal" in app,
       "导出按钮没有带上提案")
    ck("app_missing_vocab_msg", "vocabulary.json 缺失" in app and "build_vocabulary.py" in app,
       "缺 vocabulary.json 时没有可操作的错误提示")
    ck("html_slots", all(x in html for x in ('id="vocab-bar"', 'id="canvas"', 'id="prop-notes"')),
       "index.html 的提案视图挂载点不全")

    # ---------- Task 10：拖拽排序 ----------
    # 拖拽视觉三件套必须真的有样式，否则「有 draggable 属性但看不出来」等于没做。
    css = read(os.path.join(WB, "style.css"))
    ck("css_drop_handler", ".drop-handler" in css, "style.css 没定义拖拽手柄 .drop-handler")
    ck("css_drop_line", ".drop-line" in css, "style.css 没定义放置指示线 .drop-line")
    ck("css_dragging", ".pnode.dragging" in css, "style.css 没定义拖拽中的 .pnode.dragging")
    for ev in ("dragstart", "dragover", "drop", "dragend"):
        ck("app_drag_%s" % ev, '"%s"' % ev in app,
           "app.js 没有监听 %s（原生 draggable 四件套缺一不可）" % ev)
    # 零依赖铁律：拖拽只能用原生 draggable。
    # 匹配具体库名而不是 "dnd" 这种三字母子串——后者会误伤 bindCanvasDnd。
    ck("app_drag_no_library",
       not any(s in app.lower() for s in
               ("sortablejs", "dnd-kit", "react-dnd", "jquery-ui", "interactjs"))
       and "draggable" in app,
       "拖拽只能靠原生 draggable；app.js 里出现了拖拽库或连原生都没用")
    # reorderTo 的静态负面检查：重排只许换顺序，碰 uid 就是让标注串块。
    # 这里不重演算法（语义交给浏览器里真跑的那条），只查它有没有改写身份。
    rb = js_body(app, "function reorderTo")
    ck("app_reorder_exists", bool(rb), "app.js 里找不到 reorderTo")
    ck("app_reorder_no_uid_mint", bool(rb) and "nextUid" not in rb,
       "reorderTo 里调了 nextUid——重排绝不能重建身份")
    ck("app_reorder_no_uid_write", bool(rb) and not re.search(r"\buid\b\s*=(?!=)", rb),
       "reorderTo 里给 uid 赋值——重排绝不能改写身份")
    ck("app_undo_present", "lastDeleted" in app and "undoDelete" in app,
       "缺单步撤销（lastDeleted / undoDelete）")

    # ---------- Task 11：折叠积木 / 整块可拖 / 提案视图隐藏胶片条 ----------
    # 静态侧钉的是「谁负责」，DOM 侧钉的是「实际长什么样」，两边都要。
    # 先抹掉 CSS 注释再扫。style.css 顶上那段解释「为什么需要 !important」的
    # 注释里就写着 [hidden]{display:none} 这个字面量——不抹的话，
    # 把真规则删掉这条断言照样绿（变异验证实测过：删掉规则，142 条全过）。
    css_scan = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    ck("css_hidden_rule",
       re.search(r"\[hidden\]\s*\{[^}]*display:\s*none", css_scan) is not None,
       "style.css 必须有 [hidden]{display:none} —— .filmstrip 声明了 display:flex，"
       "会盖掉 UA 的 [hidden]{display:none}，hidden=true 就不生效")
    ck("css_pnode_grab_cursor",
       re.search(r"\.pnode\s*\{[^}]*cursor:\s*grab", css_scan) is not None,
       "整块可拖必须让光标说清楚（.pnode 上的 cursor: grab），否则用户读不出可拖")
    aw = js_body(app, "function addWidget")
    ck("app_addwidget_defaults_collapsed", bool(aw) and re.search(r"expanded\s*:\s*false", aw),
       "新建积木必须 expanded: false —— 默认不折叠的话，每块仍是 3 个常驻输入框")
    sp = js_body(app, "function setParams")
    ck("app_setparams_auto_expands",
       bool(sp) and re.search(r"errors\.length\)\s*\{\s*n\.expanded\s*=\s*true", sp),
       "拦截时必须把 n.expanded 置成 true（自动展开给你看违规在哪）")
    rb2 = js_body(app, "function dupNode")
    ck("app_dup_keeps_expanded",
       bool(rb2) and not re.search(r"\bexpanded\b\s*=(?!=)", rb2),
       "dupNode 不该复位 expanded —— 复制的是「当前这块的样子」，"
       "复制一块配好的积木不该把参数又藏回折叠态")
    # dragstart 的按钮豁免：整块可拖放开之后，这条守卫就是复制 / 删除还能不能点的命。
    ds = js_body(app, "function bindCanvasDnd")
    ck("app_dragstart_skips_buttons",
       bool(ds) and re.search(r'closest\("input,\s*textarea,\s*button"\)', ds) is not None,
       "dragstart 必须排除 button —— 不挡的话点「复制」「删除」会变成一次拖拽")
    sw = js_body(app, "function switchView")
    ck("app_switchview_hides_filmstrip",
       bool(sw) and "filmstrip" in sw,
       "胶片条归 switchView 管：提案视图下那 7 个状态按钮毫无意义，"
       "却会让人以为得先选状态才能提案")

    # ---------- Task 12：图示 / 参数示例 / 元素 ID 说明 / 示例面板 ----------
    # 「数据描述形状、代码负责画」的分工，两侧都要查：静态侧查数据，
    # dom_checks 查 DOM。缺一侧就会出现「数据里有图示、界面上没画」。
    demo_static_checks(vocab)
    preview_static_checks(vocab)
    task17_static_checks()

    dom_checks()

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# ---------- Task 12 的常量 ----------
# app.js 的 renderDemo 只画这 11 种形状；多一种数据里的 kind 而这里没有，
# 界面就会渲染出一个没有样式的空盒子。清单不是文档，是契约。
DEMO_KINDS = ["row", "col", "box", "split", "grid", "panel", "label", "btn",
              "prop", "rule", "gap"]
# rule / gap 不画小方块，画的是一根线 / 一条空隙，所以它们不该有 items。
DEMO_BARELESS = ["rule", "gap"]
# Task 15 起，这条不再是「恰好 8 块」。
#
# 原来钉死块数，本意是防示例面板无声变形（悄悄少一块 / 多一块都算变形），
# 但它挡住的是明显正确的改进：页签条补上三个页签按钮、规格区补上带勾选的
# 选项按钮、输入框上面补上 2x2 的按钮网格（都要照着 data/shots/options.png）。
# 所以改成钉「关键块都在」：下面这份清单是对着真实面板 options.png 逐条点出来
# 的——顶上三个页签、细节标题、三个勾选选项、两列网格里的四个按钮、
# 输入框、操作行。少任何一块都红，多出来的块不红（示例面板允许再加东西）。
#
# 仍然硬的约束一条没丢：块序与参数由 panel_blocks_as_specified 逐条比
# vocabulary.json，块数由 panel_dom_count 与 panel_preview_node_per_block
# 拿「浏览器真渲染出来的块数」与「数据里的块数」对齐（下面用 len(blocks) 现算，
# 不再拿一个写死的整数当标准答案）。
EXPECT_PANEL_KEY_BLOCKS = [
    # (块在 vocabulary.json 里的下标, 说明) —— 下标即界面上从上到下的次序
    (0, "页签条横排 chat.tabbar"),
    (1, "页签按钮 AI 对话"),
    (2, "页签按钮 详情"),
    (3, "页签按钮 设置"),
    (4, "整根竖排 chat.stream"),
    (5, "消息盒"),
    (6, "状态行"),
    (7, "规格竖排 chat.options"),
    # 块 8 从横排改成竖排（一个选项占一行，照 ui.py 的 qbox.row() 与 options.png）。
    # 断言本身一个字没松：下标、块序、参数、DOM 节点数仍旧逐条比数据，
    # 这里只把说明文字从「横排」改成它现在的真实形状，免得注释骗人。
    (8, "细节标题竖排（规格选项一行一个）"),
    (9, "勾选选项 · 经典直筒微收口"),
    (10, "勾选选项 · 鼓腹圆润"),
    (11, "勾选选项 · 手感厚壁窑变"),
    (12, "两列按钮网格"),
    (13, "网格按钮 · 修改尺寸"),
    (14, "网格按钮 · 更换材质"),
    (15, "网格按钮 · 增加倒角"),
    (16, "网格按钮 · 平滑着色"),
    (17, "指令输入框 chat.composer"),
    (18, "操作行 chat.action_row"),
]
EXPECT_PANEL_TAB_LABELS = ["AI 对话", "详情", "设置"]
EXPECT_PANEL_CHECK_OPTS = ["选择：经典直筒微收口（推荐）", "选择：鼓腹圆润",
                           "选择：手感厚壁窑变"]
EXPECT_PANEL_GRID_BTNS = ["修改尺寸", "更换材质", "增加倒角", "平滑着色"]


def panel_expect_blocks(vjson):
    """示例面板「应该有几块」的唯一真身：vocabulary.json 自己。

    不写死整数：写死的整数既会被正当的改进挡住，又会在数据真变形时
    变成在维护第二份副本。
    """
    return len((vjson.get("example_panel") or {}).get("blocks") or [])


def collect_element_ids():
    """收全部已提交布局树里出现过的 element_id。"""
    seen = set()
    d = os.path.join(WB, "data", "layout")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(d, fn), encoding="utf-8") as fh:
            doc = json.load(fh)
        stack = [doc]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if isinstance(cur.get("element_id"), str) and cur["element_id"]:
                    seen.add(cur["element_id"])
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
    return seen


def known_icons():
    """实测用过的图标名：布局树里捕获到的，加上 ui.py 里真实写过的。

    native_api.json 的 icon 枚举没抓下来（bpy_struct 不支持 IDProperties，
    notes 里那条 present=false 就是它），所以证据只能取自真正跑过的产物。
    """
    out = set()
    d = os.path.join(WB, "data", "layout")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(d, fn), encoding="utf-8") as fh:
            src_txt = fh.read()
        out.update(re.findall(r'"icon"\s*:\s*"([A-Z0-9_]+)"', src_txt))
    ui_py = os.path.join(ROOT, "blender_deepseek_agent", "ui.py")
    if os.path.exists(ui_py):
        with open(ui_py, encoding="utf-8") as fh:
            out.update(re.findall(r"icon=['\"]([A-Z0-9_]+)['\"]", fh.read()))
    return out


def hint_target(hint):
    """从 props_hint 里认出它演示的是哪个 UILayout 函数或哪个 layout 属性。

    返回 ("fn", "grid_flow") / ("prop", "scale_y")；认不出来返回 ("?", "")。
    只认这两种形态，因为允许清单之外的参数本来就该被拦下。
    """
    m = re.search(r"layout\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", hint)
    if m:
        return "fn", m.group(1)
    m = re.search(r"^\s*[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)\s*=", hint)
    if m:
        return "prop", m.group(1)
    return "?", ""


def hint_kwargs(hint):
    """抽出 hint 里带了取值的那些参数名。

    只抓 `name=` / `name =` 这种真关键字传参。位置参数（layout / data /
    第一个字符串）不在这里核对——它们是「这段代码长什么样」的一部分，
    核对它们要的是调用形态而不是参数名。
    """
    body = re.sub(r"['\"][^'\"]*['\"]", "''", hint)     # 先掐掉字符串字面量
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]", body))


def demo_static_checks(vocab):
    """Task 12 的静态侧：数据齐不齐、示例值合不合法、元素 ID 真不真实。"""
    app = read(os.path.join(WB, "app.js"))
    css_scan = re.sub(r"/\*.*?\*/", "", read(os.path.join(WB, "style.css")), flags=re.S)
    ws = vocab["widgets"]

    # --- A：12 个控件都有 demo，且 kind 是渲染器认识的形状 ---
    no_demo = [w["key"] for w in ws if not isinstance(w.get("demo"), dict)
               or not w["demo"].get("kind")]
    ck("demo_every_widget", len(ws) == EXPECT_WIDGETS and not no_demo,
       "%d 个控件里这 %d 个没有可用的 demo：%s" % (len(ws), len(no_demo), no_demo))
    kinds = [w["demo"].get("kind") for w in ws if isinstance(w.get("demo"), dict)]
    unknown = sorted(set(kinds) - set(DEMO_KINDS))
    ck("demo_kinds_known", len(kinds) == EXPECT_WIDGETS and not unknown,
       "有 demo kind 不在渲染器的清单里：%s（清单 %s）" % (unknown, DEMO_KINDS))
    missing_items = [w["key"] for w in ws
                     if w["demo"].get("kind") not in DEMO_BARELESS
                     and not w["demo"].get("items")]
    ck("demo_items_declared", not missing_items,
       "这些控件的 demo 没给 items，界面画不出内容：%s" % missing_items)
    over_items = [w["key"] for w in ws
                  if w["demo"].get("kind") in DEMO_BARELESS and w["demo"].get("items")]
    ck("demo_bareless_has_no_items", not over_items,
       "rule / gap 不画小方块，不该带 items：%s" % over_items)
    # 形状靠 CSS 画出来：每种 kind 都得有对应的一条规则，否则是个没样式的空盒子。
    nostyle = [k for k in DEMO_KINDS if ".d-%s" % k not in css_scan]
    ck("demo_kinds_have_css", not nostyle,
       "style.css 里没有这些图示样式：%s（缺 %s）" % (nostyle, ".d-<kind>"))
    # 分栏比例与网格列数必须来自数据，不是写死在 CSS 里的一刀切。
    ck("demo_data_driven_dims",
       "d.factor" in app and "d.cols" in app and "d.items" in app,
       "renderDemo 没读数据里的 factor / cols / items——"
       "那样分栏和网格就退化成固定形状，等于图示没跟着数据走")

    # --- B：参数示例必须能原样粘进参数框 ---
    # 这层是便宜的前置检查；真正证明「粘进去不报错」的是浏览器里那条
    # dom_examples_no_intercept（走真的 input 事件）。
    def toks(s):
        return [t for t in re.split(r"[,，\s]+", s or "") if t]

    illegal = []
    for w in ws:
        for t in toks(w.get("props_example")):
            if t in w["blocked_props"] or t not in w["allowed_props"]:
                illegal.append("%s:%s" % (w["key"], t))
    ck("props_example_tokens_allowed", not illegal,
       "参数示例里有词粘进去就会被拦：%s" % illegal)
    nonempty = [w["key"] for w in ws if toks(w.get("props_example"))]
    empty = [w["key"] for w in ws if not toks(w.get("props_example"))]
    ck("props_example_covers_widgets", len(nonempty) == EXPECT_WIDGETS - len(empty)
       and set(empty) == {"separator"},
       "只有没有任何参数的控件该留空示例，实际留空的是 %s" % empty)
    # 示例覆盖了多少个参数：写死 20 是逐个数出来的
    # （2+2+1+1+2+2+2+3+2+2+0+1，separator 合法地一个参数都没有）。
    ck("props_example_tokens_total",
       sum(len(toks(w.get("props_example"))) for w in ws) == 20,
       "参数示例总共应给出 20 个可粘的参数名，实际 %d"
       % sum(len(toks(w.get("props_example"))) for w in ws))

    # 带取值的真实写法，逐条对着 native_api.json 的实测签名核
    with open(os.path.join(WB, "native_api.json"), encoding="utf-8") as fh:
        api = json.load(fh)
    funcs = api["ui"]["functions"]
    props_of_ui = api["ui"]["properties"]
    checked_fn, checked_prop, bad_hint, bad_icon = [], [], [], []
    icons = known_icons()
    for w in ws:
        hint = w.get("props_hint") or ""
        kind, name = hint_target(hint)
        kws = hint_kwargs(hint)
        if kind == "fn":
            if name not in funcs:
                bad_hint.append("%s: 未知函数 %s" % (w["key"], name))
            else:
                allowed = set(p.get("name") for p in funcs[name])
                checked_fn.append(w["key"])
                extra = sorted(kws - allowed)
                if extra:
                    bad_hint.append("%s: %s 没有参数 %s" % (w["key"], name, extra))
        elif kind == "prop":
            if name not in props_of_ui:
                bad_hint.append("%s: 不是 UILayout 属性 %s" % (w["key"], name))
            else:
                checked_prop.append(w["key"])
        else:
            bad_hint.append("%s: 认不出演示的是函数还是属性：%r" % (w["key"], hint))
        for ic in re.findall(r"icon=['\"]([A-Z0-9_]+)['\"]", hint):
            if ic not in icons:
                bad_icon.append("%s: %s" % (w["key"], ic))
    ck("props_hint_native", not bad_hint, "参数示例的写法与实测签名对不上：%s" % bad_hint)
    # 非空洞：11 个控件里至少 10 个真的被核到了函数签名，其余是 layout 属性
    ck("props_hint_native_coverage",
       len(checked_fn) >= 9 and len(checked_fn) + len(checked_prop) == EXPECT_WIDGETS,
       "只核到 %d 个函数 / %d 个属性（共 %d 个控件）——覆盖率不够，这条断言不可证伪"
       % (len(checked_fn), len(checked_prop), EXPECT_WIDGETS))
    ck("props_hint_icons_real", not bad_icon and len(icons) >= 8,
       "参数示例里用了没实测过的图标：%s（可用集合 %d 个）"
       % (bad_icon, len(icons)))

    # --- C：元素 ID 说明 ---
    help_doc = vocab.get("element_id_help") or {}
    ck("element_id_help_schema",
       set(help_doc) == {"title", "what", "naming", "optional", "examples"},
       "element_id_help 字段集不对：%s" % sorted(help_doc))
    ck("element_id_help_says_naming",
       bool(help_doc.get("naming")) and "chat." in help_doc["naming"],
       "元素 ID 说明没讲命名规则：%r" % help_doc.get("naming"))
    ck("element_id_help_says_optional",
       bool(help_doc.get("optional")) and ("留空" in help_doc["optional"]
                                           or "可空" in help_doc["optional"]),
       "元素 ID 说明没讲「可以留空」：%r" % help_doc.get("optional"))
    ck("element_id_help_says_what",
       bool(help_doc.get("what")) and "ui.py" in help_doc["what"],
       "元素 ID 说明没讲它是什么、挂在代码哪里：%r" % help_doc.get("what"))
    ids = collect_element_ids()
    ex = help_doc.get("examples") or []
    ck("element_id_help_examples_real",
       len(ex) >= 2 and all(e in ids for e in ex),
       "说明里的例子 %s 不是已提交布局树里的真实 ID（真实的有 %s）" % (ex, sorted(ids)))

    # --- D：示例面板 ---
    panel = vocab.get("example_panel") or {}
    blocks = panel.get("blocks") or []
    ck("example_panel_schema",
       set(panel) == {"title", "caption", "blocks"}
       and all(set(b) == {"wkey", "params", "element_id", "note", "content"} for b in blocks),
       "example_panel 字段集不对：%s / %s"
       % (sorted(panel), sorted(blocks[0]) if blocks else "<no blocks>"))
    # 原来这里是 example_panel_block_count（块数恰好 = 8）。Task 15 起改成
    # 钉「关键块都在」——理由与 EXPECT_PANEL_KEY_BLOCKS 上方那段一致：
    # 块数写死会挡住照着 options.png 做的正当补齐，而缺块 / 错序 / 非法
    # 参数 / 假元素 ID 这四类变形由下面各条断言继续盯着，一条没放松。
    ck("example_panel_block_count_at_least_key_blocks",
       len(blocks) >= len(EXPECT_PANEL_KEY_BLOCKS),
       "示例面板至少要有 %d 块（关键块清单），实际 %d"
       % (len(EXPECT_PANEL_KEY_BLOCKS), len(blocks)))
    missing_key = [(i, why) for i, why in EXPECT_PANEL_KEY_BLOCKS
                   if i >= len(blocks)]
    ck("example_panel_key_blocks_present", not missing_key,
       "示例面板缺这些关键块：%s" % missing_key)
    panel_texts = [str(v) for b in blocks
                   for v in ((b.get("content") or {}).values())]
    for want in EXPECT_PANEL_TAB_LABELS + EXPECT_PANEL_CHECK_OPTS + EXPECT_PANEL_GRID_BTNS:
        ck("example_panel_has_text_%s" % want.split("：")[-1][:8], want in panel_texts,
           "示例面板里找不到这段字：%r" % want)
    tab_ids = [b["element_id"] for b in blocks if b["wkey"] == "row"][:1]
    ck("example_panel_tabbar_first", tab_ids == ["chat.tabbar"],
       "示例面板第一块应是页签条横排 chat.tabbar，实际 %s" % tab_ids)
    reg = {w["key"]: w for w in ws}
    bad_w = [b["wkey"] for b in blocks if b["wkey"] not in reg]
    ck("example_panel_wkeys_resolve", not bad_w,
       "示例面板里有词汇表不存在的控件：%s" % bad_w)
    bad_p = []
    for b in blocks:
        w = reg.get(b["wkey"])
        if not w:
            continue
        for t in toks(b["params"]):
            if t in w["blocked_props"] or t not in w["allowed_props"]:
                bad_p.append("%s:%s" % (b["wkey"], t))
    ck("example_panel_params_allowed", not bad_p,
       "示例面板里有粘进去就被拦的参数：%s" % bad_p)
    # 元素 ID 用真实存在的；留空是允许的，但不允许填一个不存在的。
    panel_ids = [b["element_id"] for b in blocks if b["element_id"]]
    ck("example_panel_ids_real", panel_ids and all(i in ids for i in panel_ids),
       "示例面板里有不存在的元素 ID：%s（真实的有 %s）"
       % ([i for i in panel_ids if i not in ids], sorted(ids)))
    ck("example_panel_has_empty_id",
       any(not b["element_id"] for b in blocks) and len(panel_ids) >= 4,
       "示例面板应当既演示了真实 ID，也演示了「元素 ID 可以留空」，"
       "实际非空 %d 条 / 留空 %d 条" % (len(panel_ids), len(blocks) - len(panel_ids)))
    # 面板得真的用上竖排与横排：这是用户问的「横排竖排怎么用」的核心。
    n_row = sum(1 for b in blocks if b["wkey"] == "row")
    n_col = sum(1 for b in blocks if b["wkey"] == "column")
    ck("example_panel_uses_row_and_column", n_row >= 2 and n_col >= 2,
       "示例面板里横排 %d 块 / 竖排 %d 块——这套示例本来就要示范两者怎么配合"
       % (n_row, n_col))

    # --- Task 14：三个界面各一套示例面板 + 嵌套表 ---
    # 必须逐条对着真实面板核，而不是「有三套就行」：
    # 详情 / 设置这两套是从 blender_deepseek_agent/ui.py 的 draw_detail_content()
    # 与 draw_settings_content() 抄结构来的，抄漏了这里就该红。
    panels = vocab.get("example_panels") or {}
    parents = vocab.get("example_panel_parents") or {}
    ck("example_panels_three_tabs",
       sorted(panels) == ["chat", "detail", "settings"],
       "example_panels 应覆盖对话 / 详情 / 设置三个界面，实际 %s" % sorted(panels))
    ck("example_panel_parents_three_tabs", sorted(parents) == sorted(panels),
       "嵌套表必须与三套面板一一对应：%s vs %s" % (sorted(parents), sorted(panels)))
    ck("example_panel_chat_unchanged",
       (panels.get("chat") or {}).get("blocks") == blocks,
       "example_panels.chat 必须与老键 example_panel 一致（既有断言按老键核对）")
    for tab in sorted(panels):
        pb = panels[tab].get("blocks") or []
        pm = parents.get(tab) or {}
        ck("example_panels_%s_nonempty" % tab, len(pb) >= 8,
           "%s 示例面板应至少 8 块，实际 %d" % (tab, len(pb)))
        ck("example_panels_%s_parent_index_complete" % tab,
           sorted(int(k) for k in pm) == list(range(len(pb))),
           "%s 的嵌套表下标必须是 0..%d 的完整区间，实际 %s"
           % (tab, len(pb) - 1, sorted(pm, key=int)))
        ck("example_panels_%s_parents_in_range" % tab,
           all(-1 <= int(v) < len(pb) for v in pm.values()),
           "%s 的嵌套表有越界的父下标：%s" % (tab, sorted(pm.items())))
        ck("example_panels_%s_parents_are_containers" % tab,
           all(pb[int(v)]["wkey"] in CONTAINER_WKEYS + ["row", "column"]
               for v in pm.values() if int(v) >= 0),
           "%s 有块挂在非容器下面（Blender 那边写不出来）：%s"
           % (tab, sorted(pm.items())))
        ck("example_panels_%s_has_nesting" % tab,
           any(int(v) >= 0 for v in pm.values()),
           "%s 示例面板一块都没嵌套——容器能装孩子却没装" % tab)
        bad_p2 = []
        for b in pb:
            w = reg.get(b["wkey"])
            if not w:
                continue
            for t in toks(b["params"]):
                if t in w["blocked_props"] or t not in w["allowed_props"]:
                    bad_p2.append("%s:%s" % (b["wkey"], t))
        ck("example_panels_%s_params_allowed" % tab, not bad_p2,
           "%s 示例面板里有粘进去就被拦的参数：%s" % (tab, bad_p2))
        ck("example_panels_%s_containers_silent" % tab,
           all(not (b.get("content") or {}) for b in pb if b["wkey"] in CONTAINER_WKEYS),
           "%s 的容器类控件不该带 content" % tab)

    # 详情 / 设置这两套必须真的长成两个不同的界面：
    # 只查「有三套」的话，把 detail 复制一份 settings 就照样绿。
    dkeys = [(b["wkey"], b["element_id"]) for b in (panels.get("detail") or {}).get("blocks", [])]
    skeys = [(b["wkey"], b["element_id"]) for b in (panels.get("settings") or {}).get("blocks", [])]
    ck("example_panels_detail_is_its_own",
       dkeys and any("detail." in (i or "") for _, i in dkeys),
       "详情面板的元素 ID 该带 detail. 前缀（真实面板里就是 detail 这一套）：%s" % dkeys[:4])
    ck("example_panels_settings_is_its_own",
       skeys and any("settings." in (i or "") for _, i in skeys),
       "设置面板的元素 ID 该带 settings. 前缀：%s" % skeys[:4])
    ck("example_panels_detail_vs_settings_differ", dkeys != skeys,
       "详情与设置不能是同一套面板换个名字（块序与元素 ID 必须不同）")
    # 详情要有「用量 / 转录」这两块真实结构，设置要有「服务商 / API Key / 模型」。
    dtext = json.dumps(panels.get("detail"), ensure_ascii=False)
    stext = json.dumps(panels.get("settings"), ensure_ascii=False)
    for want in ("工具调用", "转录", "本次用量"):
        ck("example_panel_detail_has_%s" % want, want in dtext,
           "详情示例面板缺少真实面板里的「%s」那段" % want)
    for want in ("服务商", "API Key", "当前模型"):
        ck("example_panel_settings_has_%s" % want, want in stext,
           "设置示例面板缺少真实面板里的「%s」那段" % want)
    ck("app_example_panel_button",
       'id = "demo-panel-btn"' in app and "insertExamplePanel" in app,
       "app.js 没有「插入示例面板」按钮 / 没有对应的插入函数")


# ---------- Task 13：界面预览 + 积木内容 ----------
# 内容字段只有 4 类控件有（label / operator / prop / textbox）；容器类控件
# 只分组或占位，不写字。写死成列表而不是从 vocabulary.json 推，是为了让
# 「多一类 / 少一类」在两边都变红。
CONTENT_WKEYS = ["label", "operator", "prop", "textbox"]
CONTENT_FIELDS = {"row": ["heading"], "column": ["heading"],
                  "label": ["text", "icon"], "operator": ["text", "icon"],
                  "prop": ["label", "value"], "textbox": ["placeholder", "lines"]}
# 这些控件只分组或占位，一个字都不写，界面上也就不该给它们内容输入框。
CONTAINER_WKEYS = ["box", "split", "grid_flow", "panel", "separator", "scale_y"]
# 每个控件在预览里必须长成什么形状。键是 data-pv，值是「标签名/display/
# flexDirection」——浏览器算出来的样式，不是我们自己写的 class 名。
# 注意 block 级元素的 flexDirection 浏览器仍报 row（初始值），
# 区分横竖排靠的是 display:flex 的那几个，别把这里写成 none。
PV_SHAPES = {
    "row": "div/flex/row",
    "column": "div/flex/column",
    "box": "div/block/row",
    "split": "div/flex/row",
    "grid_flow": "div/grid/row/2",
    "panel": "div/block/row/head/body",
    "label": "div/block/row",
    "operator": "div/block/row",
    "prop": "div/flex/row/2",
    "textbox": "div/block/row",
    "separator": "hr/block/row",
    "scale_y": "div/block/row",
}
EXPECT_PREVIEW_NODES = EXPECT_WIDGETS + EXPECT_REJECTED   # 12 控件 + 9 条降级记录


def preview_static_checks(vocab):
    """Task 13 静态侧：内容字段、名册、预览样式、以及「预览不是拼字符串」。"""
    app = read(os.path.join(WB, "app.js"))
    css = read(os.path.join(WB, "style.css"))
    css_scan = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    html = read(os.path.join(WB, "index.html"))

    starter = vocab.get("starter_content") or {}
    ck("preview_starter_covers_content_wkeys", sorted(starter) == sorted(CONTENT_WKEYS),
       "起手内容应只覆盖 %s，实际 %s" % (sorted(CONTENT_WKEYS), sorted(starter)))
    bad = []
    for wk, fields in CONTENT_FIELDS.items():
        got = starter.get(wk)
        if wk not in CONTENT_WKEYS:
            # row / column 有内容字段（heading），但不该自带起手内容：
            # 空的横排竖排本来就该是空的。
            if got is not None:
                bad.append("%s:容器不该有起手内容" % wk)
            continue
        got = got or {}
        if sorted(got) != sorted(fields):
            bad.append("%s:%s" % (wk, sorted(got)))
        elif wk == "textbox":
            if not isinstance(got.get("lines"), int) or got["lines"] < 1:
                bad.append("%s:lines=%r" % (wk, got.get("lines")))
        elif not str(got.get(fields[0]) or "").strip():
            bad.append("%s:%s 为空" % (wk, fields[0]))
    ck("preview_starter_fields", not bad,
       "起手内容字段不对 / 主字段是空的：%s" % bad)
    ck("preview_starter_operator_readable", "发送指令" in starter.get("operator", {}).get("text", ""),
       "新建的 operator 积木应当一放上来就写着「发送指令」，实际 %r"
       % starter.get("operator", {}).get("text"))

    # 示例面板的内容：预览要能拼出一个界面，光有起手内容不够——每一块都得
    # 写上它在示例面板里该有的字。只数「content 非空」的块数，期望值写死。
    blocks = (vocab.get("example_panel") or {}).get("blocks") or []
    with_text = [b["wkey"] for b in blocks
                 if any(str(v or "").strip() for v in (b.get("content") or {}).values())]
    ck("preview_example_content_count", len(with_text) >= 4,
       "示例面板里带内容的块应至少 4 块（页签标题 / 状态行 / 输入框提示 / 操作行），"
       "实际 %d 块：%s" % (len(with_text), with_text))
    ck("preview_example_textbox_content",
       any(b["wkey"] == "textbox" and (b.get("content") or {}).get("placeholder")
           and (b.get("content") or {}).get("lines", 0) >= 1 for b in blocks),
       "示例面板里的 textbox 必须自带占位提示与行数，否则预览画不出多行输入框")
    ck("preview_example_containers_have_no_content",
       all(not (b.get("content") or {}) for b in blocks if b["wkey"] in CONTAINER_WKEYS),
       "容器类控件不该带 content：%s"
       % [b["wkey"] for b in blocks if b["wkey"] in CONTAINER_WKEYS
          and (b.get("content") or {})])

    # 图标名册：逐条对着 native_api.json 的实测枚举比，不看数量。
    icons = vocab.get("icons")
    ck("preview_icons_present", isinstance(icons, list) and len(icons) > 0,
       "vocabulary.json 里没有 icons 名册，图标框就没有候选")
    if isinstance(icons, list):
        with open(os.path.join(WB, "native_api.json"), encoding="utf-8") as fh:
            api = json.load(fh)
        want = api["panels"]["properties"]["bl_icon"]["items"]
        ck("preview_icons_match_native", list(icons) == list(want),
           "图标名册与 native_api.json 实测枚举不一致：%d vs %d"
           % (len(icons), len(want)))
        ck("preview_icons_count", len(icons) == api["icons"]["count"],
           "名册长度应与 icons.count（%d）一致，实际 %d"
           % (api["icons"]["count"], len(icons)))

    # 预览的形状全部落在 CSS 上：改了 CSS 浏览器才算得出新形状。
    need_css = [".pv-row", ".pv-col", ".pv-box", ".pv-split", ".pv-grid", ".pv-panel",
                ".pv-label", ".pv-btn", ".pv-prop", ".pv-textbox", ".pv-sep", ".pv-gap",
                ".pv-empty", ".pv-down", ".canvas-split"]
    miss_css = [c for c in need_css if c not in css_scan]
    ck("preview_css_defined", not miss_css, "style.css 缺这些预览样式：%s" % miss_css)
    ck("preview_row_is_row",
       re.search(r"\.pv-row\s*\{[^}]*flex-direction:\s*row", css_scan) is not None,
       ".pv-row 必须是横向容器——横排竖排是这套工具的第一课")
    ck("preview_col_is_column",
       re.search(r"\.pv-col\s*\{[^}]*flex-direction:\s*column", css_scan) is not None,
       ".pv-col 必须是纵向容器")

    # 预览必须从数据建 DOM。拼 HTML 字符串的话，积木数据一改预览就悄悄过期
    # （迷你图示那条教训）。所以画控件的那个函数里不许有 innerHTML。
    pw = js_body(app, "function pvWidget")
    ck("preview_built_from_data", bool(pw) and "innerHTML" not in pw,
       "pvWidget 里出现了 innerHTML：预览一旦拼 HTML 字符串就会和数据脱节")
    rp = js_body(app, "function renderPreview")
    ck("preview_renders_proposal", bool(rp) and "proposal.forEach" in rp,
       "renderPreview 必须遍历 proposal 渲染")
    ck("preview_walks_all_wkeys", all(('"%s"' % k) in app for k in CONTAINER_WKEYS + CONTENT_WKEYS),
       "app.js 里少了某些控件的预览分支")

    # 两栏：预览与积木列表必须是同一个容器的两个子节点，否则「左预览右积木」
    # 在 DOM 上就不成立。
    m = re.search(r'<div class="canvas-split">(.*?)</div>\s*</div>\s*<div id="prop-notes"', html, re.S)
    split = m.group(1) if m else ""
    ck("preview_two_pane_html", 'id="preview"' in split and 'id="canvas"' in split
       and split.index('id="preview"') < split.index('id="canvas"'),
       "index.html 的提案视图不是「左预览 / 右积木」两栏：%r" % split[:120])
    ck("preview_pane_width", re.search(r"\.preview-pane\s*\{[^}]*420px", css_scan) is not None,
       "预览栏必须固定在 420px 左右（与实机 N 面板同宽）")


def find_browser():
    for p in BROWSERS:
        if p and os.path.exists(p):
            return p
    return None


def dump(exe, url, profile):
    p = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--user-data-dir=" + profile,
         "--window-size=1400,1400", "--virtual-time-budget=9000",
         "--dump-dom", url],
        capture_output=True, timeout=180)
    return p.stdout.decode("utf-8", "replace")


def dom_checks():
    exe = find_browser()
    if not exe:
        # 不能只 WARN 就 return：那样 12 条真正证明「拦截会触发」的断言会全部
        # 蒸发，而 rc 仍然是 0——这正是全局约束禁掉的假绿。默认记失败；
        # 确实没有浏览器的机器可以显式设 UW_SKIP_DOM=1 承认这一点。
        ck("dom_browser_present", os.environ.get("UW_SKIP_DOM") == "1",
           "找不到 Edge/Chrome，渲染腿整条没跑（UW_SKIP_DOM=1 可显式承认）")
        return
    url = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    profile = tempfile.mkdtemp(prefix="uw_proposal_")
    try:
        with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
            vjson = json.load(fh)
        empty = dump(exe, url + "#proposal-empty", profile)
        ck("dom_vocab_buttons", len(re.findall(r'<button data-wkey="[^"]+"', empty)) == EXPECT_WIDGETS,
           "提案视图应渲染 %d 个控件按钮，实际 %d"
           % (EXPECT_WIDGETS, len(re.findall(r'<button data-wkey="[^"]+"', empty))))
        ck("dom_reject_buttons", len(re.findall(r'<button data-rkey="[^"]+"', empty)) == EXPECT_REJECTED,
           "应渲染 %d 条降级按钮，实际 %d"
           % (EXPECT_REJECTED, len(re.findall(r'<button data-rkey="[^"]+"', empty))))
        ck("dom_empty_hint", 'id="empty-hint"' in empty, "空画布没有提示")
        hint = empty_hint_of(empty)
        ck("dom_empty_hint_teaches_drag", "拖" in hint,
           "空态引导还在教人用表单（只字未提「拖」）——"
           "用户原话是「还是有点不太会用」：%r" % hint)
        ck("dom_empty_hint_keeps_fallback", "做不到" in hint,
           "空态引导丢了「做不到」列表的指引：%r" % hint)
        ck("dom_empty_hint_keeps_scope", "顺序" in hint,
           "空态引导没说明「积木顺序 = 面板顺序」，用户不知道为什么能重排：%r" % hint)
        bar = vocab_bar_of(empty)
        ck("dom_vocab_bar_head_teaches_drag",
           "拖动换位" in "".join(re.findall(r"<b>(.*?)</b>", bar, re.S)),
           "控件架的标题没提示积木可以拖动换位：%r" % bar[:160])
        btitles = re.findall(r'<button data-wkey="[^"]*" title="([^"]*)"', bar)
        ck("dom_vocab_bar_button_title_teaches_drag",
           len(btitles) == EXPECT_WIDGETS and all("拖动换位" in t for t in btitles),
           "12 个控件按钮的 title 里，有 %d 个没说明可拖动换位（抓到 %d 个按钮）"
           % (sum(1 for t in btitles if "拖动换位" not in t), len(btitles)))
        ck("dom_empty_no_nodes", 'class="note pnode' not in empty,
           "没点任何控件就不该有提案节点")
        # 可做但没收录的能力必须在提案视图里显形（Important 3）
        ck("dom_unmapped_row", 'data-ukey="progress_bar"' in empty,
           "提案视图没有列出「可做但词汇表尚未收录」的能力")
        ck("dom_unmapped_note", "尚未收录" in empty,
           "缺少「尚未收录」的说明文案")
        ck("dom_props_scope", "精选子集" in empty,
           "没有说明 allowed_props 是精选子集，容易被当成全量 API")

        # --- Task 11-C：提案视图下的胶片条 ---
        # 必须切到「提案视图」和「镜像视图」各渲染一次来比：
        # 只看提案视图那份，删掉整行胶片条和「没藏起来」长得一模一样。
        mirror = dump(exe, url, profile)
        ptag, mtag = tag_of(empty, "filmstrip"), tag_of(mirror, "filmstrip")
        ck("filmstrip_tag_found", bool(ptag) and bool(mtag),
           "两份 dump 里都该找得到 #filmstrip，实际 %r / %r" % (ptag, mtag))
        ck("filmstrip_hidden_in_proposal", bool(ptag) and "hidden" in ptag,
           "提案视图下状态胶片条必须隐藏：那 7 个按钮切的是镜像视图的实机截图，"
           "放在提案视图上方会让人以为要先选状态：%r" % ptag)
        ck("filmstrip_visible_in_mirror", bool(mtag) and "hidden" not in mtag,
           "切回镜像视图后胶片条必须恢复：%r" % mtag)
        # 隐藏 ≠ 清空：两份 dump 里的按钮数应当一样多，变的只是 hidden。
        # 拿「同一个数互相比」而不是写死 7，镜像视图以后加减状态也不会误报。
        pbtns = len(re.findall(r"<button", filmstrip_of(empty)))
        mbtns = len(re.findall(r"<button", filmstrip_of(mirror)))
        ck("filmstrip_hidden_not_emptied",
           mbtns > 0 and pbtns == mbtns,
           "胶片条应当只是被藏起来，不是被清空：镜像 %d 个按钮 / 提案 %d 个"
           % (mbtns, pbtns))
        # 视图本体本身不许被连带藏掉：藏胶片条不能顺手把镜像视图也藏了
        mv = re.search(r'<section id="view-mirror"[^>]*>', mirror)
        ck("filmstrip_does_not_hide_mirror_view",
           mv is not None and "hidden" not in mv.group(0),
           "镜像视图本体在默认状态下必须可见：%r" % (mv.group(0) if mv else "<missing>"))

        allp = dump(exe, url + "#proposal-all", profile)
        nodes = re.findall(r'<div class="note pnode[^"]*"[^>]*>', allp)
        ck("dom_all_count", len(nodes) == EXPECT_WIDGETS + EXPECT_REJECTED,
           "点击后应有 %d 个提案节点，实际 %d" % (EXPECT_WIDGETS + EXPECT_REJECTED, len(nodes)))
        # 12 个控件全部 status=ok / errors=0 —— 这是「词汇表内全部合法」的判定
        wnodes = re.findall(r'<div class="note pnode"[^>]*data-wkey="([^"]*)" data-downgraded="0" '
                            r'data-status="([^"]*)" data-errors="([^"]*)"', allp)
        ck("dom_all_widgets_ok", len(wnodes) == EXPECT_WIDGETS and
           all(s == "ok" and e == "0" for _, s, e in wnodes),
           "词汇表内控件应全部合法，实际 %s" % [(k, s, e) for k, s, e in wnodes if s != "ok" or e != "0"])
        dnodes = re.findall(r'<div class="note pnode down"[^>]*data-wkey="__downgraded__" '
                            r'data-downgraded="1" data-status="downgraded" data-errors="0" '
                            r'data-rkey="([^"]*)"', allp)
        ck("dom_all_downgraded", len(dnodes) == EXPECT_REJECTED and
           sorted(dnodes) == sorted(r["key"] for r in vjson["rejected"]),
           "%d 条降级方案应全部插入且标记为 downgraded，实际 %s"
           % (EXPECT_REJECTED, sorted(dnodes)))
        # 每条降级方案都要把「原需求做不到 + 降级方案」两行写进画布节点里。
        # 必须只扫 #canvas：按钮的 title 里也抄了一遍 fallback 文案，
        # 扫全文档的话这条断言就算画布上什么都没写也会绿（变异验证实测过）。
        canvas = canvas_of(allp)
        ck("dom_all_canvas_found", bool(canvas.strip()), "定位不到画布区域")
        missing_fb = [k for k in dnodes if _fb_for(k) not in canvas]
        ck("dom_all_fallback_text", not missing_fb,
           "有降级方案没写进画布：%s" % missing_fb)
        missing_bl = [k for k in dnodes if _fb_for_blocker(k) not in canvas]
        ck("dom_all_blocker_text", not missing_bl,
           "有原需求理由没写进画布：%s" % missing_bl)
        ck("dom_all_strike", canvas.count('class="strike"') == EXPECT_REJECTED,
           "原需求删除线应出现 %d 次，实际 %d"
           % (EXPECT_REJECTED, canvas.count('class="strike"')))
        ck("dom_all_uilayout", canvas.count("layout.") >= EXPECT_WIDGETS,
           "12 个控件的 UILayout 调用没都渲染进画布（必须数 canvas 切片："
           "按钮 title 里也有一份，数整份文档的话这条不可证伪）")

        blk = dump(exe, url + "#proposal-blocked", profile)
        m = re.search(r'<div class="note pnode blocked"[^>]*data-wkey="label" '
                      r'data-downgraded="0" data-status="blocked" data-errors="(\d+)"', blk)
        ck("dom_block_label", m is not None,
           "label 写了违规参数后没有被标成 blocked")
        if m:
            ck("dom_block_errors", m.group(1) == "3",
               "size/color/scale/text 应产生 3 条拦截，实际 %s" % m.group(1))
        ck("dom_block_perr", blk.count('class="perr"') == 3,
           "应有 3 条拦截文案，实际 %d" % blk.count('class="perr"'))
        ck("dom_block_msg_blocked", blk.count("不被 UILayout 支持") == 2,
           "size/color 应各报一次「不被支持」，实际 %d" % blk.count("不被 UILayout 支持"))
        ck("dom_block_msg_allowlist", blk.count("不在「") == 1,
           "scale 应报一次「不在允许清单」，实际 %d" % blk.count("不在「"))
        lab = blk.split('<div class="note pnode blocked"')[-1].split("</textarea>")[0] \
            if '<div class="note pnode blocked"' in blk else ""
        chips_ok = lab.count('<span class="chip">text</span>')
        chips_bad = len(re.findall(r'<span class="chip bad">[^<]*✗</span>', lab))
        ck("dom_block_chip_ok", chips_ok == 1,
           "合法参数 text 应渲染成非 bad chip，实际 %d" % chips_ok)
        ck("dom_block_chip_bad", chips_bad == 3,
           "3 个违规参数应各渲染一个 bad chip，实际 %d" % chips_bad)
        ck("dom_block_status_span", 'data-status="blocked"' in blk and 'data-status="ok"' in blk,
           "合法与违规节点应共存：合法控件 11 个，违规 1 个")
        ck("dom_block_others_ok", len(re.findall(
            r'data-wkey="[^"]*" data-downgraded="0" data-status="ok" data-errors="0"', blk)) == 11,
           "除 label 外其余 11 个控件仍应合法")

        # --- Important 1：真 input 事件下的焦点与字符完整性 ---
        # #proposal-blocked 走的是 setParams() 直调，绕开了用户真正会走的那条路。
        # 这里派发真的 input 事件逐字符敲，模拟浏览器的真实行为：
        # 元素一旦被 renderCanvas 摘出文档，后续按键就打到 body，字符会丢。
        typ = dump(exe, url + "#proposal-typing", profile)
        rep = re.search(r'<div id="typing-report"([^>]*)>', typ)
        ck("dom_typing_report", rep is not None, "没有拿到逐字符输入报告")
        if rep:
            at = dict(re.findall(r'data-([a-z]+)="([^"]*)"', rep.group(1)))
            ck("dom_typing_no_char_lost", at.get("lost") == "0",
               "有 %s 个字符被吞掉（每敲一个键都重建画布，输入框失焦）"
               % at.get("lost"))
            ck("dom_typing_value", at.get("value") == "scale_ys",
               "输入框最终值应为 scale_ys，实际 %r" % at.get("value"))
            ck("dom_typing_focus", at.get("focused") == "true",
               "输入完焦点已丢，后续按键会打到 body")
            ck("dom_typing_caret", at.get("caret") == str(len(at.get("value", "")) // 2),
               "光标位置没还原到插入点（应在中间），实际在 %s" % at.get("caret"))
            ck("dom_typing_blocked", at.get("status") == "blocked" and at.get("errors") == "1",
               "多敲的那个 s 应被判违规，实际 status=%s errors=%s"
               % (at.get("status"), at.get("errors")))

        # --- Task 9：稳定 uid + 删除 + 复制 ---
        # 每块积木都要带身份。没有身份就没有任何东西能把「我编辑的是哪一块」
        # 这个问题问对——data-idx 是位置，删掉中间一块后面全串位。
        uids = re.findall(r'<div class="note pnode[^"]*"[^>]*data-uid="([^"]*)"', allp)
        ck("dom_uid_on_every_node", len(uids) == EXPECT_WIDGETS + EXPECT_REJECTED,
           "每块积木都要有 data-uid，实际 %d / 共 %d 块"
           % (len(uids), EXPECT_WIDGETS + EXPECT_REJECTED))
        ck("dom_uid_unique_all", bool(uids) and all(uids) and len(set(uids)) == len(uids),
           "uid 重复或为空：%s" % uids)
        # 每块一个删除、一个复制按钮。
        # 期望值写死成字面量 21，不写成 node_count()：两边同时为 0 时
        # 0 == 0 恒真，只能靠别的断言兜底——依赖别人保证非空洞等于没保证。
        cvs = canvas_of(allp)
        ck("dom_del_button_per_node", cvs.count('data-act="del"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个删除按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="del"')))
        ck("dom_dup_button_per_node", cvs.count('data-act="dup"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个复制按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="dup"')))
        ck("fold_button_per_node", cvs.count('data-act="fold"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个展开/收起按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="fold"')))

        # --- Task 11-A：默认折叠 ---
        # 12 块常驻输入框 = 1800px 的滚动，这就是它读起来还像表单的原因。
        # 这里数 canvas 切片里 data-field 的出现次数：折叠时它们一个都不该在 DOM 里。
        # 期望值写死成 0（不是 count()==count()），两边同时为 0 时那种恒真不许出现。
        ck("fold_default_no_fields_in_dom",
           cvs.count('data-field="params"') == 0 and
           cvs.count('data-field="id"') == 0 and
           cvs.count('data-field="note"') == 0 and
           cvs.count('data-expanded="1"') == 0,
           "点完控件后积木应当全是折叠的：params=%d id=%d note=%d 已展开=%d"
           % (cvs.count('data-field="params"'), cvs.count('data-field="id"'),
              cvs.count('data-field="note"'), cvs.count('data-expanded="1"')))

        # 删除：#proposal-del 里点的是画布上真实的删除按钮
        dele = dump(exe, url + "#proposal-del", profile)
        ck("dom_delete_noop_on_stale_uid", del_on_stale_uid_is_noop(dele),
           "块已经被删掉后再点它那个过期按钮，必须什么都不做——"
           "idxByUid 返回 -1，proposal.splice(-1, 1) 会静默删掉最后一块")
        ck("dom_delete_removes_one", del_last_node(dele), "删除最后一块后块数应减一")
        ck("dom_delete_no_uid_reuse", del_last_node_then_check_uid(dele),
           "删掉中间一块后，其余积木的 uid 必须原样保留（身份不等于位置）")
        ck("dom_delete_dom_uids_match", del_dom_uids_match_array(dele),
           "删除后渲染出来的存活积木 uid 必须与数组一致（否则焦点/标注会串到别的块）")

        # 复制：副本必须拿到全新 uid，否则焦点和标注会串回原块
        dupd = dump(exe, url + "#proposal-dup", profile)
        ck("dom_dup_adds_one", dup_last_node(dupd), "复制后块数应加一")
        ck("dom_dup_gets_new_uid", dup_gets_distinct_uid(dupd),
           "复制的积木必须是新 uid，否则焦点和标注会串到原块上")

        # --- Task 10：拖拽 ---
        # 每块积木都要能拖，拖拽视觉（手柄）也必须真的渲染出来。
        # 期望值写死成字面量 21，不写成 count() == count()：两边同时为 0 时
        # 恒真，只能靠别的断言兜底——依赖别人保证非空洞等于没保证。
        ck("drag_dom_draggable_nodes",
           cvs.count('draggable="true"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 块积木带 draggable=true，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('draggable="true"')))
        ck("drag_dom_handler_per_node",
           cvs.count('class="drop-handler"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "每块积木左侧都该有一个拖拽手柄，实际 %d"
           % cvs.count('class="drop-handler"'))
        drag_checks(dump(exe, url + "#proposal-drag", profile))
        undo_checks(dump(exe, url + "#proposal-undo", profile), empty)
        fold_checks(dump(exe, url + "#proposal-fold", profile))

        # --- Task 12：图示 / 参数示例 / 元素 ID 说明 / 示例面板 ---
        demo_checks(empty, vjson)
        help_checks(empty, vjson)
        examples_checks(dump(exe, url + "#proposal-examples", profile), vjson)
        panel_checks(dump(exe, url + "#proposal-panel", profile), vjson)
        preview_checks(dump(exe, url + "#proposal-preview", profile), vjson)
        nest_checks(dump(exe, url + "#proposal-nest", profile), vjson)
        move_checks(dump(exe, url + "#proposal-move", profile), vjson)
        # Task 17：选中双向同步 / 自动保存 / 三种导出。
        # save 与 restore 必须是两次不同的页面加载（同一份浏览器档案），
        # 否则「刷新不丢」就退化成了「同一个页面里读自己刚写的东西」。
        select_checks(dump(exe, url + "#proposal-select", profile))
        select_leaf_checks(dump(exe, url + "#proposal-select-leaf", profile))
        save_checks(dump(exe, url + "#proposal-save", profile),
                    dump(exe, url + "#proposal-restore", profile))
        export_checks(dump(exe, url + "#proposal-export", profile), vjson)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def preview_of(p):
    """取 #preview 切片。

    必须切：#canvas 的节点里也写着控件名与参数示例，整份文档里找
    `data-pv=` 的话，测试就成了在验「字符串在不在」，而不是「预览画没画」。
    """
    if '<div id="preview"' not in p or '<div class="block-pane"' not in p:
        return ""
    return p.split('<div id="preview"')[1].split('<div class="block-pane"')[0]


def preview_checks(page, vocab):
    """Task 13 的 DOM 侧：12 种控件在预览里各自长成该长的形状，内容跟着改。

    读数来自浏览器算出来的样式与几何（flex 方向 / grid 列数 / 元素高度），
    不是我们自己写的 class 名——改 CSS 就改形状，这条才抓得住。
    """
    at = report(page, "preview-report")
    ck("preview_hook_ran", at.get("count") == str(EXPECT_PREVIEW_NODES)
       and at.get("proposal") == str(EXPECT_PREVIEW_NODES) and at.get("missing") == "0",
       "预览钩子没跑起来或节点对不上：count=%s proposal=%s missing=%s"
       % (at.get("count"), at.get("proposal"), at.get("missing")))
    shapes = {}
    for r in (at.get("shapes") or "").split("|"):
        if "=" in r:
            k, v = r.split("=", 1)
            shapes[k] = v
    widget_shapes = {k: v for k, v in shapes.items() if k != "__downgraded__"}
    ck("preview_shapes_cover_all", sorted(widget_shapes) == sorted(PV_SHAPES),
       "预览应覆盖 12 种控件，实际 %s" % sorted(widget_shapes))
    ck("preview_shapes_keep_downgraded",
       (at.get("shapes") or "").count("__downgraded__=") == EXPECT_REJECTED,
       "9 条降级记录也各占一个预览位置（画成「做不到」），实际 %d"
       % (at.get("shapes") or "").count("__downgraded__="))
    for wk, want in sorted(PV_SHAPES.items()):
        got = widget_shapes.get(wk, "")
        ck("preview_shape_%s" % wk, got.startswith(want),
           "%s 在预览里应长成 %s…，实际 %r" % (wk, want, got))

    # 三处必须落在具体数字上的：网格列数、留白高度、分栏宽度。
    # 期望值写死，不写成「比 0 大」那种放水写法。
    gcols = shapes.get("grid_flow", "").rsplit("/", 1)[-1]
    ck("preview_grid_two_columns", gcols == "2",
       "grid_flow 在预览里应是 2 列网格，实际列数 %r（%s）" % (gcols, shapes.get("grid_flow")))
    gh = shapes.get("scale_y", "").rsplit("/", 1)[-1]
    ck("preview_scale_y_has_height", gh.isdigit() and int(gh) >= 6,
       "scale_y 必须在预览里撑出一条空白，实际高度 %r" % gh)
    sw = shapes.get("split", "").rsplit("/", 1)[-1]
    ck("preview_split_left_halved", sw.isdigit() and 0 < int(sw) < 420,
       "split 的左栏应按 factor 占一部分，实际宽 %r" % sw)
    th = shapes.get("textbox", "").rsplit("/", 1)[-1]
    ck("preview_textbox_multiline", th.isdigit() and int(th) >= 32,
       "textbox 应画成多行输入区，实际高 %r" % th)

    # 改内容 -> 预览跟着变（走的是真的输入框 + 真的 input 事件）。
    # 期望值由起手内容 + 敲进去的字拼出来，不写死：写死的话，起手图标一改
    # 这条就变成在维护第二份文案，而不是在验「预览跟不跟内容走」。
    st = (vocab.get("starter_content") or {}).get("label") or {}
    want_typed = (("%s%s" % (st.get("icon") or "", "正在改你的场景 · 第 2 步")))
    ck("preview_follows_content", at.get("typed-text") == want_typed,
       "改了 label 的文字，预览里应出现新文字，期望 %r，实际 %r"
       % (want_typed, at.get("typed-text")))
    # 清空 -> 占位形状，不是空白。
    ck("preview_empty_is_placeholder", at.get("cleared") == "empty",
       "内容清空后预览应显示压暗的占位形状，实际 %r" % at.get("cleared"))
    ck("preview_panel_closed_collapse", at.get("closed-head") == "▸",
       "面板写上 default_closed 后预览应收起（标题条只留 ▸），实际 %r" % at.get("closed-head"))

    ck("preview_icon_datalist", at.get("icon-list") == "1033",
       "图标候选表应喂进 1033 个实测图标名，实际 %r" % at.get("icon-list"))
    ck("preview_two_pane_live", at.get("two-pane") == "1",
       "预览与积木列表必须是同一个容器的两个子节点（左右两栏）")

    # 直接看渲染出来的标记：分隔线必须是 hr，网格容器必须写了 repeat()。
    pv = preview_of(page)
    ck("preview_dom_found", bool(pv.strip()), "定位不到预览区域")
    ck("preview_dom_separator_is_hr",
       re.search(r'<hr[^>]*data-pv="separator"', pv) is not None,
       "separator 在预览里必须是 <hr>")
    ck("preview_dom_grid_repeat",
       re.search(r'data-pv="grid_flow"[^>]*style="[^"]*grid-template-columns:\s*repeat\(2, 1fr\)', pv)
       is not None,
       "grid_flow 的预览节点必须写死 repeat(2, 1fr) 的网格：%r"
       % re.findall(r'<div[^>]*data-pv="grid_flow"[^>]*>', pv))
    ck("preview_dom_node_per_block",
       len(re.findall(r'data-pvuid="', pv)) == EXPECT_PREVIEW_NODES,
       "预览里应每块积木一个节点，实际 %d"
       % len(re.findall(r'data-pvuid="', pv)))
    ck("preview_dom_uses_no_images",
       "<img" not in pv and "background-image" not in pv,
       "预览不许用图片或背景图（零资源铁律）")


def demo_nodes(bar):
    """把 #vocab-bar 切片里的迷你图示逐个拆出来。

    必须切到 #vocab-bar 里看：#canvas 与 #prop-notes 也可能有 .demo（现在没有，
    但那是巧合不是约定）。每块的 body 截到「下一个 .demo 的起始标签」为止，
    否则最后一个小方块会被算进上一块里，两块的计数一起错。
    """
    out = []
    for m in re.finditer(r'<div class="demo([^"]*)"([^>]*)>', bar):
        attrs = m.group(2)
        wk = re.search(r'data-dwkey="([^"]*)"', attrs)
        dk = re.search(r'data-dkind="([^"]*)"', attrs)
        out.append({
            "cls": m.group(1),
            "wkey": wk.group(1) if wk else "",
            "kind": dk.group(1) if dk else "",
            "tag": m.start(),
            "end": m.end(),
        })
    for i, n in enumerate(out):
        stop = out[i + 1]["tag"] if i + 1 < len(out) else len(bar)
        body = bar[n["end"]:stop]
        n["items"] = body.count('class="d-it"')
    return out


def demo_checks(page, vjson):
    """A：12 个控件各自画出一张小图示，图示里的小方块数量与数据一致。"""
    bar = vocab_bar_of(page)
    nodes = demo_nodes(bar)
    ck("dom_demo_one_per_widget", len(nodes) == EXPECT_WIDGETS,
       "控件架里应有 %d 张图示，实际 %d" % (EXPECT_WIDGETS, len(nodes)))
    want = {w["key"]: w["demo"] for w in vjson["widgets"]}
    ck("dom_demo_keys_match",
       sorted(n["wkey"] for n in nodes) == sorted(want),
       "图示的 data-dwkey 与词汇表对不上：%s"
       % sorted(set(n["wkey"] for n in nodes) ^ set(want)))
    wrong_kind = [n["wkey"] for n in nodes
                  if n["kind"] != (want.get(n["wkey"], {}).get("kind"))]
    ck("dom_demo_kind_matches", not wrong_kind,
       "这些图示画的形状与 demo.kind 不符：%s" % wrong_kind)
    # 逐块比小方块数量：这一条专治「图示框画出来了，里面是空的」。
    bad_items = [(n["wkey"], n["items"], len((want.get(n["wkey"], {}).get("items") or [])))
                 for n in nodes
                 if n["items"] != len(want.get(n["wkey"], {}).get("items") or [])]
    ck("dom_demo_items_match", not bad_items,
       "图示里的小方块数量与数据对不上（wkey, 画了几个, 应该有）：%s" % bad_items)
    total_items = sum(n["items"] for n in nodes)
    ck("dom_demo_items_total", total_items == 18,
       "12 张图示里应一共画出 18 个小方块（rule / gap 不画方块），实际 %d"
       % total_items)


def help_checks(page, vjson):
    """C：元素 ID 说明要真的渲染出来，而不是只躺在 vocabulary.json 里。"""
    hlp = vjson["element_id_help"]
    if '<div id="prop-notes"' not in page or "</body>" not in page:
        ck("dom_element_id_help", False, "定位不到 #prop-notes")
        return
    notes = page.split('<div id="prop-notes"')[1]
    m = re.search(r'<div id="element-id-help"[^>]*>(.*?)</div>\s*(?:<h3|</section|<div id="annot)',
                  notes, re.S)
    ck("dom_element_id_help", m is not None,
       "元素 ID 的说明没有渲染出来——数据里有、界面上没有，用户还是不知道填什么")
    if m is None:
        return
    body = unescape_html(m.group(1))
    ck("dom_element_id_help_naming", hlp["naming"] in body,
       "说明里缺命名规则这一句：%r" % body[:200])
    ck("dom_element_id_help_optional", hlp["optional"] in body,
       "说明里缺「可以留空」这一句：%r" % body[:200])
    ck("dom_element_id_help_what", hlp["what"] in body,
       "说明里缺「它是什么、挂在代码哪」的这句话：%r" % body[:200])
    dm = re.search(r'<div class="chips" data-examples="([^"]*)"', body)
    ck("dom_element_id_help_examples",
       dm is not None and dm.group(1) == ",".join(hlp["examples"]),
       "说明里给的例子应为 %s，实际 %r"
       % (hlp["examples"], dm.group(1) if dm else None))


def examples_checks(page, vjson):
    """B（重头）：把 12 个控件的参数示例真的敲进参数框，一条拦截都不许有。"""
    at = report(page, "examples-report")
    rows = [r for r in at.get("rows", "").split("|") if r]
    ck("examples_hook_ran", len(rows) == EXPECT_WIDGETS,
       "参数示例钩子没跑起来（抓到 %d 条，应为 %d）：%s"
       % (len(rows), EXPECT_WIDGETS, at.get("rows")))
    if len(rows) != EXPECT_WIDGETS:
        return
    blocked = [r for r in rows if not re.search(r":0:ok$", r)]
    ck("dom_examples_no_intercept", not blocked,
       "这些参数示例粘进去就被拦了（示例给错了比不给更糟）：%s" % blocked)
    ck("examples_all_widgets_covered",
       at.get("covered") == ",".join(w["key"] for w in vjson["widgets"]),
       "示例没有覆盖全部 12 个控件：%s" % at.get("covered"))
    # 值要真的落进输入框：只报 errors=0 的话，「示例压根没写进去」照样全绿。
    got = dict(kv.split("=", 1) for kv in at.get("values", "").split("|") if kv)
    want = {w["key"]: w["props_example"] for w in vjson["widgets"]}
    ck("examples_value_landed", got == want,
       "示例值没有原样落进参数框：实际 %r" % got)
    ck("examples_one_block_per_widget", at.get("total") == str(EXPECT_WIDGETS)
       and len(set(_uids(at, "uids"))) == EXPECT_WIDGETS,
       "示例跑完画布上应有 %d 块、uid 互不相同，实际 %s / %r"
       % (EXPECT_WIDGETS, at.get("total"), at.get("uids")))


def panel_checks(page, vjson):
    """D：点一下「插入示例面板」，画布里出现一整套能抄的积木。

    块数的标准答案一律取 vocabulary.json 里的 blocks（panel_expect_blocks），
    不再拿一个写死的整数：写死的整数既会挡住正当的补齐（Task 15 就被它挡过），
    又等于在测试里养了第二份副本。
    """
    at = report(page, "panel-report")
    want_n = panel_expect_blocks(vjson)
    ck("panel_hook_ran", at.get("after") == str(want_n)
       and at.get("before") == "0",
       "示例面板没插进去：before=%s after=%s（应为 0 -> %d）"
       % (at.get("before"), at.get("after"), want_n))
    if at.get("after") != str(want_n):
        return
    ck("panel_dom_count", at.get("dom-count") == str(want_n),
       "画布上应渲染出 %d 块，实际 %s" % (want_n, at.get("dom-count")))
    uids = _uids(at, "dom-uids")
    ck("panel_uids_unique", len(uids) == want_n
       and all(uids) and len(set(uids)) == len(uids),
       "示例面板各块的 uid 必须互不相同：%s" % uids)
    rows = [r for r in at.get("rows", "").split("|") if r]
    ck("panel_rows_count", len(rows) == want_n,
       "应逐块报出 %d 条读数，实际 %d：%s"
       % (want_n, len(rows), at.get("rows")))
    bad = [r for r in rows
           if not re.search(r":0:", r) or re.search(r":[1-9]\d*:", r)]
    ck("panel_params_legal", not bad,
       "示例面板里有块自带违规参数（用户点开就看到「违规」）：%s" % bad)
    ck("panel_no_blocked_node", at.get("blocked-nodes") == "0",
       "示例面板不该出现任何违规块，实际 %s 块" % at.get("blocked-nodes"))
    want_rows = ["%s:0:%s" % (b["wkey"], b["params"] or "-")
                 for b in vjson["example_panel"]["blocks"]]
    ck("panel_blocks_as_specified", at.get("rows") == "|".join(want_rows),
       "示例面板的块序 / 参数与 vocabulary.json 不一致：\n实际 %s\n应为 %s"
       % (at.get("rows"), "|".join(want_rows)))
    want_ids = [b["element_id"] for b in vjson["example_panel"]["blocks"] if b["element_id"]]
    ck("panel_element_ids", at.get("ids") == ",".join(want_ids),
       "示例面板的元素 ID 应为 %s，实际 %s" % (want_ids, at.get("ids")))

    # --- 规格选项必须竖排一行一个（照 ui.py 的 qbox.row() 与 options.png）---
    # 之前这块是横排，三个按钮并排后每条只剩三分之一宽，
    # 「选择：经典直筒微收口（推荐）」被折成两行，跟真实面板对不上。
    # 这条既钉数据（选项组是竖排、三个选项各归它），也钉渲染出来的 DOM
    # （预览里真有一个装着这三个按钮的竖排容器）。只钉数据的话，
    # 谁把渲染改回并排照样绿。
    opt_group = (vjson["example_panel"]["blocks"] or [])[8]
    opt_par = {int(k): int(v) for k, v in
               ((vjson.get("example_panel_parents") or {}).get("chat") or {}).items()}
    ck("panel_options_group_is_column",
       opt_group.get("wkey") == "column"
       and [opt_par.get(i) for i in (9, 10, 11)] == [8, 8, 8],
       "规格选项组（第 8 块）应是竖排，三个选项各挂在它下面：wkey=%r 归属=%r"
       % (opt_group.get("wkey"), [opt_par.get(i) for i in (9, 10, 11)]))
    pv_opt = preview_of(page)
    n_col_pv = len(re.findall(r'data-pv="column"', pv_opt))
    ck("panel_options_render_column_in_dom", n_col_pv >= 3,
       "预览里至少要有 3 个竖排容器（根 / 规格区 / 选项组），实际 %d —— "
       "选项组没渲染成竖排就是并排回去了" % n_col_pv)

    # 插完之后左边预览必须真的拼出了一个界面，而不是一片空壳。
    # 逐条拿示例面板自己声明的内容去预览切片里找——写死一句文案的话，
    # 示例面板换了字这条就会变成在维护第二份副本。
    pv = preview_of(page)
    want_text = []
    for b in vjson["example_panel"]["blocks"]:
        for k, v in (b.get("content") or {}).items():
            if isinstance(v, str) and v.strip():
                want_text.append("%s:%s" % (k, v))
    missing_text = [w for w in want_text if w.split(":", 1)[1] not in pv]
    ck("panel_preview_has_content", bool(want_text) and not missing_text,
       "插完示例面板后预览里缺这些内容：%s" % missing_text)
    ck("panel_preview_node_per_block",
       len(re.findall(r'data-pvuid="', pv)) == want_n,
       "示例面板 %d 块应各占预览一个节点，实际 %d"
       % (want_n, len(re.findall(r'data-pvuid="', pv))))
    ck("panel_preview_multiline_composer",
       'data-pv="textbox"' in pv and re.search(r'data-pv="textbox"[^>]*height:\s*56px', pv)
       is not None,
       "示例面板的输入框在预览里应是 3 行高（3*16+8），实际 %r"
       % re.findall(r'<div[^>]*data-pv="textbox"[^>]*>', pv))


def panel_subtree(vjson, index, tab="chat"):
    """按 example_panel_parents 数出第 index 块的子树块数（自己 + 所有后代）。

    为什么从数据现算而不是写死整数：示例面板这一轮补了页签按钮、勾选选项
    与按钮网格，子树大小跟着变。写死的整数既会误报（数据合法地变大），
    又会在数据真变形时给出错误的「期望值」。从同一份数据现算，
    期望值与数据同源、但仍非空洞：浏览器那边量的是真删/真复制出来的块数。
    """
    pm = {int(k): int(v)
          for k, v in ((vjson.get("example_panel_parents") or {})
                       .get(tab) or {}).items()}
    kids = {}
    for k, p in pm.items():
        kids.setdefault(p, []).append(k)
    seen, stack = set(), [index]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        stack.extend(kids.get(i, []))
    return len(seen)


def panel_child_count(vjson, index, tab="chat"):
    """第 index 块有几个直接孩子（孙块不算）。"""
    pm = {int(k): int(v)
          for k, v in ((vjson.get("example_panel_parents") or {})
                       .get(tab) or {}).items()}
    return sum(1 for p in pm.values() if p == index)


def panel_index_of(vjson, element_id, tab="chat"):
    """按元素 ID 找到块下标；找不到给 -1（调用方据此判红，不会蒙过去）。"""
    blocks = (vjson.get("example_panels") or {}).get(tab, {}).get("blocks") or []
    for i, b in enumerate(blocks):
        if b.get("element_id") == element_id:
            return i
    return -1


def nest_checks(page, vjson):
    """Task 14：积木嵌套 + 三个界面各自独立的列表。

    读数全部来自浏览器真算出来的 DOM 父子关系与真点过的按钮结果，不是数组自证：
      pv-max-depth —— 预览节点在 DOM 里最多套着几层别的预览节点
      groups       —— 画布上渲染出的分组框数
      dup-count    —— 复制一个容器之后净增几块（子树复制则 > 1）
      dup-tree     —— 副本 uid:它的直接孩子数（孩子必须改指副本，不能还挂在原件下）
      del-count    —— 删掉一个容器之后掉几块（连子树一起）
      del-orphans  —— 删完之后还指着已删容器的块数（必须为 0）
      tabs         —— 三个子页签各自的块数
      sel-*        —— 归属下拉的选项数与选项文本
    """
    at = report(page, "nest-report")
    ck("nest_hook_ran", bool(at.get("pv-count")) and bool(at.get("tabs")),
       "嵌套钩子没跑起来：%s" % at)
    if not at.get("pv-count"):
        return

    # --- 预览是不是真的树 ---
    # 容器不装孩子时 maxDepth 会掉到 1（全是 panel-root 的直接孩子）。
    # 写死 >= 2，不写「preview 里出现过 data-pv=column」那种恒真写法。
    d = at.get("pv-max-depth", "0")
    ck("nest_preview_is_tree", d.isdigit() and int(d) >= 2,
       "预览里容器没把子控件装进去（最大套嵌层数 %r，期望 >= 2）" % d)
    ck("nest_preview_node_per_block",
       at.get("pv-count") == at.get("blocks") and int(at.get("pv-count", "0")) > 0,
       "预览应每块积木一个节点：预览 %s 块 / 积木 %s 块"
       % (at.get("pv-count"), at.get("blocks")))

    # --- 画布上的分组框 ---
    ck("nest_groups_rendered", at.get("groups", "0").isdigit()
       and int(at.get("groups", "0")) > 0,
       "画布上没渲染出任何分组框（容器积木没把孩子装进去）：%s" % at.get("groups"))

    # --- 复制容器 = 连子树一起复制，且子孙改指副本 ---
    # 期望值从 example_panel_parents 现算（chat.stream 那棵子树有多少块），
    # 浏览器那边量的是真点过复制按钮之后的净增块数。
    s_ix = panel_index_of(vjson, "chat.stream")
    want_dup = panel_subtree(vjson, s_ix)
    want_kids = panel_child_count(vjson, s_ix)
    ck("nest_dup_copies_subtree", want_dup > 1 and at.get("dup-count") == str(want_dup),
       "复制 chat.stream（整棵子树 %d 块）应净增 %d 块，实际 %s"
       % (want_dup, want_dup, at.get("dup-count")))
    mt = re.match(r"^(\w+):(\d+)$", at.get("dup-tree", ""))
    ck("nest_dup_children_reparented", bool(mt) and mt.group(2) == str(want_kids),
       "副本应带 %d 个直接孩子，且它们的 parent 必须改指副本的"
       "新 uid，否则改一块会动两处：dup-tree=%r" % (want_kids, at.get("dup-tree")))

    # --- 删除容器 = 整棵子树一起删，且不留孤儿 ---
    # 删的是规格竖排 chat.options：它底下套着「细节横排 -> 三个勾选选项」，
    # 一次能验掉三层——孙块也得跟着走。
    o_ix = panel_index_of(vjson, "chat.options")
    want_del = panel_subtree(vjson, o_ix)
    ck("nest_del_takes_subtree", want_del > 1 and at.get("del-count") == str(want_del),
       "删掉 chat.options（连子树共 %d 块）应掉 %d 块，实际 %s"
       % (want_del, want_del, at.get("del-count")))
    ck("nest_del_no_orphans", at.get("del-orphans") == "0",
       "删完之后不许剩指着已删容器的孤儿块（它们既不显示也删不掉），实际 %s 个"
       % at.get("del-orphans"))

    # --- 三个界面各自独立 ---
    ck("nest_tabs_independent",
       at.get("tabs", "").count("=") == 3
       and "detail=0" in at.get("tabs", "") and "settings=0" in at.get("tabs", ""),
       "三个界面应各有独立列表：对话那边增删过之后，详情 / 设置仍应是 0 块，实际 %r"
       % at.get("tabs"))

    # --- 归属下拉：首项是顶层，选项数与文本数一致 ---
    texts = [t for t in at.get("sel-texts", "").split("|") if t]
    ck("nest_parent_select_present", bool(texts), "画布上没渲染出归属下拉")
    ck("nest_parent_select_lists_top", bool(texts) and texts[0] == "（顶层）",
       "归属下拉第一项必须是「（顶层）」，实际 %r" % (texts[:1] or None))
    ck("nest_parent_select_excludes_leaves",
       bool(texts) and at.get("sel-options") == str(len(texts)),
       "归属下拉的选项数与读到的文本数对不上：%s vs %d"
       % (at.get("sel-options"), len(texts)))


def move_checks(page, vjson):
    """Task 15：树线 / 分组框 / 两个换父级的快捷按钮 / 拖进容器。

    读数全部来自浏览器真画出来的 DOM 与真点过的按钮、真派发过的 DragEvent：
      kidzones / zoneKids —— 孩子区（树线那一截）有几个、里面装着几块
      counts / countBad  —— 容器标题上的「· N」逐个与真孩子数对账
      in-* / out-*        —— 两个按钮每块都有，没得移的被置灰（不是消失）
      out-parent / in-parent —— 依次点过之后 parent 变成什么
      drag-cands / drag-parent —— 拖起来时标了几个能装的容器、落上去之后 parent 变成什么
      deny-status        —— 落点不能装时，状态条说了什么
    """
    at = report(page, "move-report")
    n = panel_expect_blocks(vjson)
    ck("move_hook_ran", at.get("blocks") == str(n),
       "快捷按钮钩子没跑起来或块数不对：blocks=%s（应 %d）" % (at.get("blocks"), n))
    if at.get("blocks") != str(n):
        return

    # --- 树：孩子区必须真存在，而且里面真的装着积木 ---
    zones = at.get("kidzones", "0")
    ck("move_tree_kidzones", zones.isdigit() and int(zones) > 0,
       "画布上没有孩子区（树线画不出来）：%s" % zones)
    ck("move_tree_kidzone_has_kids",
       at.get("zone-kids", "0").isdigit() and int(at.get("zone-kids", "0")) > 0,
       "孩子区里一块子积木都没有——分组框和树线只是画了个空壳：%s" % at.get("zone-kids"))

    # --- 容器标题上的子块数：标签上的 N 必须等于真孩子数 ---
    ck("move_count_badge_matches_kids", at.get("count-bad") == "0",
       "容器标题上的「· N」与真孩子数对不上，有 %s 个对不上：%s"
       % (at.get("count-bad"), at.get("counts")))
    ck("move_empty_container_marked", at.get("empty-marked", "0").isdigit()
       and int(at.get("empty-marked", "0")) > 0,
       "一个空容器都没有标「· 0」——空容器必须看得见是空的：%s" % at.get("counts"))

    # --- 两个快捷按钮：每块都有，且「没得移」要置灰 ---
    ck("move_buttons_on_every_block",
       at.get("in-all") == str(n) and at.get("out-all") == str(n),
       "每块积木都该有「移入上一个容器」「移出上一层」两个按钮，实际 in=%s out=%s（应各 %d）"
       % (at.get("in-all"), at.get("out-all"), n))
    ck("move_out_button_greys_top_level",
       at.get("out-off", "0").isdigit() and 0 < int(at.get("out-off", "0")) < n,
       "顶层积木的「移出上一层」必须置灰（不是消失），实际置灰 %s 个 / 共 %d 块"
       % (at.get("out-off"), n))
    ck("move_in_button_greys_when_no_container",
       at.get("in-off", "0").isdigit() and 0 < int(at.get("in-off", "0")) < n,
       "上面没有可装容器时「移入上一个容器」必须置灰，实际置灰 %s 个 / 共 %d 块"
       % (at.get("in-off"), n))

    # --- 点这两个按钮真的换了父级，块数不变 ---
    ck("move_out_then_in_round_trip",
       at.get("blocks-before") == at.get("blocks")
       and at.get("out-parent") == ""
       and at.get("in-parent") not in ("", "?", "None"),
       "「移出上一层」应把这块放到顶层（parent 空），「移入上一个容器」再把它装回"
       "一个容器里：blocks %s->%s out=%r in=%r"
       % (at.get("blocks-before"), at.get("blocks"), at.get("out-parent"),
          at.get("in-parent")))
    ck("move_in_target_is_container",
       at.get("in-parent-wkey") in CONTAINER_WKEYS + ["row", "column"],
       "「移入上一个容器」必须装进一个真容器里（Blender 只让容器收子控件），"
       "实际落点 wkey=%r" % at.get("in-parent-wkey"))
    ck("move_in_button_enabled_when_target_exists",
       at.get("in-disabled") == "false",
       "上面明明有可装的容器，按钮却还是置灰的（按钮不能只标不灵）：%r"
       % at.get("in-status"))

    # --- 拖到容器上 = 成为它的子块 ---
    ck("move_drag_marks_drop_targets",
       at.get("drag-cands", "0").isdigit() and int(at.get("drag-cands", "0")) > 0,
       "拖起来时没有任何容器被标成「能装进去」——用户只能一个个拖过去试：%s"
       % at.get("drag-cands"))
    # 这条以前只钉「parent 是个容器」，而被拖的那块（box）本来就装在
    # chat.stream 里——落点分支整个没走掉它照样绿，于是 M3（落点判定反转）
    # 红 0 条。现在钉死两件事：落点就是这次拖的那个容器 uid，且落之前
    # parent 不是它。「从 A 真的挪到了 B」，没有空档可钻。
    ck("move_drag_into_container",
       at.get("drag-target-uid", "") not in ("", "?")
       and at.get("drag-parent") == at.get("drag-target-uid")
       and at.get("drag-parent-wkey") in CONTAINER_WKEYS + ["row", "column"],
       "落在 chat.options 上之后，这一块必须成为它的子块（parent 就是落点那个容器），"
       "实际 from=%r 落点=%r parent=%r wkey=%r"
       % (at.get("drag-from"), at.get("drag-target-uid"),
          at.get("drag-parent"), at.get("drag-parent-wkey")))
    ck("move_drag_actually_moved",
       at.get("drag-from", "?") not in ("", "?")
       and at.get("drag-parent") != at.get("drag-from"),
       "拖拽必须真的换了父级（落之前 %r ≠ 落之后 %r）——不然这条只是在说"
       "「它本来就装在某个容器里」" % (at.get("drag-from"), at.get("drag-parent")))

    # --- 拒绝时：树不许变，而且必须说话 ---
    # 两条一起钉：只钉「状态条里有个『不能』」的话，把环检测整段删掉也照样绿
    # （reparent 自己还有一道，消息里同样有「不能」）——所以还要钉住
    # 「被拒之后 parent 原样不动」。
    ck("move_deny_explains", "不能" in (at.get("deny-status") or ""),
       "把容器拖进它自己的子孙里必须给出拒绝说明（静默弹回像坏了），实际状态条 %r"
       % at.get("deny-status"))
    ck("move_deny_keeps_tree",
       at.get("deny-parent") == "" and at.get("blocks") == str(n),
       "拖拽被拒之后树不许变（容器仍停在顶层、块数不变），实际 parent=%r blocks=%s"
       % (at.get("deny-parent"), at.get("blocks")))


def vocab_bar_of(p):
    """取 #vocab-bar 宿主的切片。

    上一版这条断言扫的是整份 dump，而空态引导的文案里就含「拖动换位」——
    把 renderVocabBar 的标题和按钮 title 全改回原文，它照样绿。
    同一个坑本文件的 canvas_of docstring 早就记过一次，这里是第二次。
    #canvas 在 index.html 里紧跟在 #vocab-bar 后面，按这对标记切最省事。
    """
    if '<div id="vocab-bar"' not in p or '<div id="canvas"' not in p:
        return ""
    return p.split('<div id="vocab-bar"')[1].split('<div id="canvas"')[0]


def empty_hint_of(p):
    """取空态引导那一句的正文。

    不做「整份文档里有没有『拖』」的判断：控件按钮的 title 里也写着拖，
    那样这条断言在引导文案一个字没改的情况下照样绿（不可证伪）。
    """
    m = re.search(r'<p id="empty-hint"[^>]*>(.*?)</p>', p, re.S)
    if not m:
        return ""
    txt = m.group(1)
    for a, b in (("&quot;", '"'), ("&#39;", "'"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&amp;", "&")):
        txt = txt.replace(a, b)
    return txt


def unescape_html(s):
    """把 dump 里被转义过的实体还原回去。

    必须还原：元素 ID 的命名规则里带 <区块> 这种尖括号占位符，
    dump 出来是 &lt;区块&gt;，直接拿原文去比永远比不中。
    """
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&amp;", "&")):
        s = s.replace(a, b)
    return s


def tag_of(p, eid):
    """取 id=`<eid>` 那个元素的起始标签（含全部属性）。

    胶片条这条断言要看的是 hidden 属性——而 hidden 是设在外层
    #filmstrip 上的，只看内层第一个 <button> 就会把「藏了」判成「没藏」。
    找不到返回空串：后续 `X in ""` 恒为 False，判定必红，不会蒙过去。
    """
    m = re.search(r'<[a-z]+[^>]*\bid="%s"[^>]*>' % re.escape(eid), p)
    return m.group(0) if m else ""


def filmstrip_of(p):
    """取 #filmstrip 的内容切片（#view-mirror 是它的下一个兄弟）。"""
    if '<div id="filmstrip"' not in p or '<section id="view-mirror"' not in p:
        return ""
    return p.split('<div id="filmstrip"')[1].split('<section id="view-mirror"')[0]


def drag_checks(p):
    """拖拽排序：语义与清理都在浏览器里真跑一遍，不在 Python 侧重演算法。

    「在 Python 侧重放 reorderTo 的语义」是靠不住的：源码能区分变体，
    断言却仍可能恒真恒假（Task 7 的 SUBSTR in texts 就栽在这儿）。
    这里直接派发真的 DragEvent，走的是用户拖鼠标时同一条代码路径。
    """
    at = report(p, "drag-report")
    before = _uids(at, "before-uids")
    after = _uids(at, "after-uids")
    after2 = _uids(at, "after-fwd-uids")
    want_n = EXPECT_WIDGETS + EXPECT_REJECTED
    ck("drag_hook_ran",
       len(before) == want_n and len(after) == want_n and len(after2) == want_n,
       "拖拽钩子没跑起来或块数不对：before=%d after=%d after2=%d"
       % (len(before), len(after), len(after2)))
    if len(before) != want_n or len(after) != want_n or len(after2) != want_n:
        return

    # 拖起过程中必须有落位指示线；不画线的话用户根本不知道会落在哪。
    ck("drag_line_shown_on_dragover", at.get("line-seen") == "1",
       "dragover 期间画布上应恰好有一条放置指示线，实际 %s" % at.get("line-seen"))
    # 语义一：把第 3 块拖到第 1 位 -> [3,1,2,4…]（往前拖）
    want = [before[2], before[0], before[1]] + before[3:]
    ck("drag_reorder_semantics", after == want,
       "从第 3 块拖到第 1 位后顺序应为 %s，实际 %s" % (want, after))
    # 语义二：再把第 1 块拖到第 4 位 -> [2,3,1,4…]（往后拖）。
    # 这一条才是 at 里那个 -1 的照妖镜：源被取出后后面的元素已经往前挪了一位，
    # 少减/多减一格都会在这里现形。只测「往前拖」的话这半边代码形同虚设。
    want2 = [after[1], after[2], after[0]] + after[3:]
    ck("drag_reorder_semantics_backward", after2 == want2,
       "把第 1 块往后拖到第 4 位后顺序应为 %s，实际 %s" % (want2, after2))
    # 身份不随位置变：uid 集合必须原样（重建 uid 的话标注会整片串块）。
    ck("drag_reorder_keeps_uid", sorted(after) == sorted(before) and sorted(after2) == sorted(before),
       "重排改写了 uid 集合：before=%d after=%d after2=%d 差集 %s"
       % (len(before), len(after), len(after2),
          sorted(set(before) ^ set(after) ^ set(after2))))
    ck("drag_reorder_dom_matches", _uids(at, "dom-uids") == after2,
       "重排后画布上渲染出来的 uid 顺序与数组不一致")
    # 落位成功那条：drop 自己就要收干净，不许指望 dragend——
    # drop 里 renderCanvas() 会把源节点摘掉，之后的 dragend 未必还冒泡得到。
    ck("drag_drop_clears_line", at.get("line-after-drop") == "0",
       "drop 之后放置指示线必须消失，实际 %s" % at.get("line-after-drop"))
    ck("drag_drop_clears_state", at.get("state-after-drop") == "null",
       "drop 之后 dragState 必须置空，实际 %s" % at.get("state-after-drop"))
    # 取消那条：拖到一半按 Esc / 丢在画布外，只有 dragend 能收尾。
    # 这三条就是「漏掉 dragend 清理」的照妖镜——漏了画布会永久卡在拖拽态。
    ck("drag_cancel_clears_line", at.get("line-after-cancel") == "0",
       "取消拖拽后放置指示线必须消失，实际 %s" % at.get("line-after-cancel"))
    ck("drag_cancel_clears_dragging", at.get("dragging-after-cancel") == "0",
       "取消拖拽后 .pnode.dragging 必须摘干净，实际还剩 %s 块"
       % at.get("dragging-after-cancel"))
    ck("drag_cancel_clears_state", at.get("state-after-cancel") == "null",
       "取消拖拽后 dragState 必须置空，实际 %s" % at.get("state-after-cancel"))
    ck("drag_cancel_keeps_order", at.get("order-after-cancel") == ",".join(before),
       "取消拖拽不许改动任何积木的顺序")

    # 整块可拖之后，按钮上按下不许触发拖拽——不然复制 / 删除就点不动了。
    ck("drag_button_press_not_drag", at.get("state-after-btn") == "null",
       "在复制按钮上按下必须被 dragstart 挡掉，实际 dragState=%s"
       % at.get("state-after-btn"))
    ck("drag_button_press_no_dragging_class",
       at.get("dragging-after-btn") == "0",
       "在按钮上按下不该给积木挂上 .dragging，实际 %s 块"
       % at.get("dragging-after-btn"))

    # reorderTo 的负 toIdx 守卫。UI 走不到这条路（dropIndexAt 只给 0..n），
    # 所以这里直接调那个被明确导出为「拖拽与测试共用」的入口。
    # 不夹紧的话 splice(-1, 0, item) 会把最后一块插回倒数第二位——
    # 顺序看上去纹丝不动，正是最难被发现的那种错。
    gb, ga = _uids(at, "guard-before-uids"), _uids(at, "guard-after-uids")
    moved = at.get("guard-moved-uid", "")
    ck("reorder_negative_to_idx_is_clamped",
       bool(gb) and len(gb) == len(ga) and bool(moved) and
       ga[0] == moved and sorted(ga) == sorted(gb),
       "reorderTo(n-1, -1) 应把最后一块移到最前（实际首位 %r，目标 %r）；"
       "长度 %d -> %d" % (ga[0] if ga else None, moved, len(gb), len(ga)))
    ck("reorder_negative_to_idx_dom_matches", _uids(at, "guard-dom-uids") == ga,
       "负 toIdx 重排后画布上渲染出来的 uid 顺序与数组不一致")


# 折叠 / 展开 / 拦截自动展开。
# 每个读数都是 "params/id/note/perr/expanded" 五段：前四段数的是这块积木的
# DOM 里到底有没有那几个输入框与拦截文案。数组字段对了但 DOM 没渲染的话，
# 只有这一串抓得住。
def _fields(at, key):
    v = at.get(key, "")
    return v.split("/") if v else []


FOLDED = ["0", "0", "0", "0", "0"]           # params/id/note/perr/expanded
OPENED = ["1", "1", "1", "0", "1"]           # 没写参数 -> 没有拦截文案


def fold_checks(p):
    at = report(p, "fold-report")
    ck("fold_hook_ran", bool(at.get("uid")) and bool(at.get("before")),
       "折叠钩子没跑起来：%s" % at)
    if not at.get("uid"):
        return
    ck("fold_default_collapsed", _fields(at, "before") == FOLDED,
       "新建的积木应当默认折叠（三个输入框都不在 DOM 里），实际 %r" % at.get("before"))
    ck("fold_expand_shows_fields", _fields(at, "opened") == OPENED,
       "点「展开」后参数 / 元素 ID / 备注三个输入框都该在，实际 %r" % at.get("opened"))
    ck("fold_manual_collapse", _fields(at, "recollapsed") == FOLDED,
       "再点一次「收起」应当真的折回去，实际 %r" % at.get("recollapsed"))
    ck("fold_block_auto_expands", _fields(at, "after-block") == ["1", "1", "1", "1", "1"],
       "塞进违规参数后应当自动展开并露出拦截文案（size 是 label 的 blocked 参数，"
       "所以 errors 应为 1），实际 %r" % at.get("after-block"))
    ck("fold_block_can_still_collapse", _fields(at, "after-collapse") == FOLDED,
       "自动展开之后用户必须还能手动收起来——实际 %r" % at.get("after-collapse"))
    # 「一有错就弹开」的照妖镜：label 这时仍然带着 1 条拦截，
    # 可整块画布上不该有任何一块处于展开态。
    ck("fold_block_not_stuck_open",
       at.get("error-count") == "1" and at.get("expanded-nodes") == "0",
       "label 仍有 %s 条拦截，画布上却还有 %s 块处于展开态"
       % (at.get("error-count"), at.get("expanded-nodes")))


def undo_checks(p, empty):
    """单步撤销：删除按钮紧挨复制、点错没有确认，误删要能救回来。"""
    at = report(p, "undo-report")
    before = _uids(at, "before-uids")
    gone, back = _uids(at, "after-del-uids"), _uids(at, "after-undo-uids")
    ck("undo_hook_ran",
       len(before) == EXPECT_WIDGETS + EXPECT_REJECTED and
       len(gone) == len(before) - 1 and len(back) == len(before),
       "撤销钩子没跑起来：before=%d after-del=%d after-undo=%d"
       % (len(before), len(gone), len(back)))
    if len(back) != len(before) or len(gone) != len(before) - 1:
        return
    victim = at.get("victim-uid", "")
    ck("undo_removes_then_restores", victim and victim not in gone and victim in back,
       "被删的积木 %r 没有原样回到数组里" % victim)
    ck("undo_restores_same_index", back == before,
       "撤销必须放回原位（前后 uid 序列应完全一致），实际 %s" % back)
    ck("undo_no_new_uid", sorted(back) == sorted(before),
       "撤销不该领新 uid——它是把原对象放回去，不是新建一块")
    ck("undo_dom_matches", _uids(at, "dom-uids") == back,
       "撤销后画布上渲染出来的 uid 顺序与数组不一致")
    ck("undo_button_enables_after_delete", at.get("enabled-after-del") == "true",
       "删过东西之后撤销按钮必须可点，实际 enabled=%s" % at.get("enabled-after-del"))
    ck("undo_button_disables_after_use", at.get("enabled-after-undo") == "false",
       "单步撤销用过一次就该失效（不做撤销栈），实际 enabled=%s"
       % at.get("enabled-after-undo"))
    # 没删过东西时按钮必须 disabled，否则点了会静默无事发生。
    m = re.search(r'<button[^>]*id="undo-del"[^>]*>', empty)
    ck("undo_button_present", m is not None, "画布上没有撤销按钮 #undo-del")
    if m:
        ck("undo_button_disabled_initially", "disabled" in m.group(0),
           "还没删过东西时撤销按钮应当是 disabled：%s" % m.group(0))


def js_body(src, header):
    """取 `header`（如 "function reorderTo"）之后按花括号配平的函数体。

    只用于静态负面检查（reorderTo 里不该出现 uid 改写）。
    不用它重演算法——重排语义由浏览器里真跑 reorderTo 的钩子判定。
    """
    i = src.find(header)
    if i < 0:
        return ""
    # 先把 /* */ 注释抹掉再切函数体。app.js 里到处是解释「为什么这么写」的
    # 长注释，其中不少直接写着被禁用的写法（比如 dupNode 那段里的
    # "copy.expanded = false"）。不抹的话，负面检查扫的是注释而不是代码——
    # 断言会因为一句解释而变红，人还得去猜是哪行代码写错了。
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    i = body.find(header)
    j = body.find("{", i + len(header))
    if i < 0 or j < 0:
        return ""
    depth = 0
    for k in range(j, len(body)):
        if body[k] == "{":
            depth += 1
        elif body[k] == "}":
            depth -= 1
            if depth == 0:
                return body[j + 1:k]
    return ""


def canvas_of(p):
    """取 #canvas 切片。

    按钮的 title 里也抄了一遍 fallback 文案、数值文案，扫整份文档的话
    「画布上写了没有」这类断言就算什么都没写也会绿（变异验证实测过）。
    """
    if '<div id="canvas"' not in p or '<div id="prop-notes"' not in p:
        return ""
    return p.split('<div id="canvas"')[1].split('<div id="prop-notes"')[0]


def report(p, rid):
    """读无头钩子吐出来的 <div id="..."> 报告，读不到就返回空 dict（判定必红）。"""
    m = re.search(r'<div id="%s"([^>]*)>' % re.escape(rid), p)
    if not m:
        return {}
    return dict(re.findall(r'data-([a-z][a-z-]*)="([^"]*)"', m.group(1)))


def _uids(at, key):
    v = at.get(key, "")
    return v.split(",") if v else []


def del_on_stale_uid_is_noop(p):
    """块已经不在数组里了，再点它那个「过期」的删除按钮，必须什么都不做。

    钉的是 delNode 的负下标守卫：idxByUid 未命中返回 -1，
    而 proposal.splice(-1, 1) 在 JS 里是合法的、会静默删掉最后一块。
    审查员指出这是一条静默的数据丢失路径（今天点不出来，拖拽排序一行就能踩到），
    补守卫还不够——这条断言必须让没守卫的写法变红。
    """
    at = report(p, "del-report")
    if not at.get("after-first") or not at.get("after-stale"):
        return False
    return int(at["after-stale"]) == int(at["after-first"])


def del_last_node(p):
    """点最后一块的删除按钮 -> 块数减一。

    基线取 after-stale（= 第一次真删之后的块数），不取 before：
    before 是 DOM 节点数、before-uids 是数组长度，数组与 DOM 一旦失步，
    拿 before 当基线会把「渲染失败」误报成「删除失败」。这里两处读数
    都来自同一次 hook 内的数组快照，基线与被测值同源。
    """
    at = report(p, "del-report")
    if not at.get("after-stale") or not at.get("after-last"):
        return False
    return int(at["after-last"]) == int(at["after-stale"]) - 1


def del_last_node_then_check_uid(p):
    """删掉中间一块后，其余积木的身份必须原封不动。

    钉的是「uid 是身份不是位置」：剩下的 uid 序列必须正好等于
    原序列去掉被点的三块（第一块 + 最后一块 + 中间一块），顺序不变、
    数量只少三。若实现改用重排后的下标重新发 uid，或者复用被删的 uid，
    这里必红。
    """
    at = report(p, "del-report")
    before, after = _uids(at, "before-uids"), _uids(at, "after-uids")
    gone = (at.get("first-uid", ""), at.get("last-uid", ""), at.get("mid-uid", ""))
    if not before or not after or not all(gone):
        return False
    if len(after) != len(before) - 3:
        return False
    if any(u not in before for u in gone) or len(set(gone)) != 3:
        return False
    if len(set(after)) != len(after):
        return False                     # 出现重复 uid = 身份被复用
    return after == [u for u in before if u not in gone]


def del_dom_uids_match_array(p):
    """删除后「渲染出来的那几块」的 uid，必须与数组里的完全一致。

    beforeUids / afterUids 都是 hook 从 proposal 数组里读的，从来没碰过 DOM——
    一个「数组删对了、但存活积木渲染出的 uid 是错的或空的」的变异体照样全绿。
    这里把 DOM 上 .pnode[data-uid] 按文档顺序抓下来，与数组逐位比对：
    少一块、错一个 uid、顺序不同，三种都抓得住。
    """
    at = report(p, "del-report")
    after, dom = _uids(at, "after-uids"), _uids(at, "dom-uids")
    if not after or not dom:
        return False
    return dom == after


def dup_last_node(p):
    at = report(p, "dup-report")
    if not at.get("before") or not at.get("after"):
        return False
    return int(at["after"]) == int(at["before"]) + 1


def dup_gets_distinct_uid(p):
    """复制的副本必须拿到全新 uid，且原块一个都不能被改写。

    同时核对 DOM：副本必须真的以新 uid 渲染出来，而不只是数组里多了条记录。
    """
    at = report(p, "dup-report")
    before, after = _uids(at, "before-uids"), _uids(at, "after-uids")
    if not before or not after:
        return False
    if len(after) != len(before) + 1:
        return False
    if after[:-1] != before:
        return False                     # 原块被改写了（顺序或身份都变了）
    if after[-1] in before or len(set(after)) != len(after):
        return False                     # 副本沿用了原 uid
    if at.get("dom-count") != str(len(after)):
        return False
    return at.get("dom-last-uid") == after[-1]


def _fb_for(rkey):
    with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
        v = json.load(fh)
    for r in v["rejected"]:
        if r["key"] == rkey:
            return r["fallback"]
    return "<missing>"


def strip_js_comments(src):
    """抹掉 JS 注释：块注释与行注释都抹。

    js_body 只抹 /* */，不抹 //。于是「函数体里有 execCommand」这类断言
    会被**行注释里的那个词**满足 —— 代码删干净了断言照样绿。
    这次真栽过：把 copyText 里的 execCommand 那一行删掉，测试仍然绿，
    因为上面两行注释里写着「execCommand 直接空转」。

    行注释只在 // 之前的引号成对时才算注释，免得把字符串里的
    "https://…" 之类从中间截断。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.split("\n"):
        cut = None
        pos = line.find("//")
        while pos >= 0:
            if line.count('"', 0, pos) % 2 == 0:
                cut = pos
                break
            nxt = line.find("//", pos + 2)
            if nxt < 0:
                break
            pos = nxt
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def task17_static_checks():
    """Task 17 静态侧：选中描边 + 自动保存 + 三种导出的契约。

    这一层只查「结构上做没做」；真正证明行为的在 select_checks /
    save_checks / export_checks 三条 DOM 腿里——静态检查看不见浏览器
    算出来的描边、也看不见 localStorage 到底存没存进去。
    """
    app = read(os.path.join(WB, "app.js"))
    html = read(os.path.join(WB, "index.html"))
    css = read(os.path.join(WB, "style.css"))
    css_scan = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    app_scan = strip_js_comments(app)
    # HTML 注释也要抹掉：导出面板那段注释里提到了被并掉的旧按钮，
    # 留着注释再扫字面量，这条断言就会永远红——它量的是界面上有没有按钮。
    html_scan = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    # ---------- 出口：四个挂载点都得在，且都在提案视图里 ----------
    for eid in ("export-panel", "export-btns", "py-out", "store-warn"):
        ck("t17_html_has_%s" % eid.replace("-", "_"), 'id="%s"' % eid in html,
           "index.html 少了 id=\"%s\"" % eid)
    ck("t17_export_panel_inside_proposal",
       re.search(r'id="view-proposal".*?id="export-panel"', html, re.S) is not None,
       "导出面板不在提案视图里")
    # 旧的那个「导出标注」按钮必须已经并掉：它导的就是方案 JSON 的同一份数据，
    # 留着两个含义重叠的按钮，用户会把标注存成一个自己认不出的文件名。
    ck("t17_no_orphan_export_button",
       'id="export"' not in html_scan and "导出标注" not in html_scan,
       "页眉还留着旧的「导出标注」按钮，与「下载方案文件（JSON）」含义重叠")

    # ---------- 描边色：只许是实测色板里那一个蓝 ----------
    used = sorted(set(re.findall(r"#[0-9a-fA-F]{3,6}\b", css_scan)))

    def bluish(h):
        if len(h) == 4:
            h = "#" + "".join(c * 2 for c in h[1:])
        r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
        return b > r + 20 and b > g + 20

    blues = [c for c in used if bluish(c)]
    ck("t17_accent_is_only_blue", blues == ["#4772b3"],
       "style.css 里蓝色不止 #4772b3 一个：%s（描边只能挑那一个）" % blues)
    m = re.search(r"--accent:\s*(#[0-9a-fA-F]{3,6})", css_scan)
    ck("t17_accent_var_value", bool(m) and m.group(1).lower() == "#4772b3",
       "--accent 应当是 #4772b3，实际 %s" % (m.group(1) if m else "<没找到>"))
    # 描边本身必须真的用那个变量，而不是在规则里又写一遍十六进制——
    # 写死的话换主题时描边会留在旧颜色上，而断言还在绿。
    sel_rule = re.search(r'\[data-pvuid\]\[data-sel="1"\]\s*\{([^}]*)\}', css_scan)
    ck("t17_outline_rule_uses_var",
       bool(sel_rule) and "var(--accent)" in sel_rule.group(1),
       "选中描边规则没有用 var(--accent)：%s" % (sel_rule.group(1) if sel_rule else "<没找到>"))
    ck("t17_outline_rule_shape",
       bool(sel_rule) and re.search(r"outline:\s*2px solid", sel_rule.group(1)) is not None,
       "描边应当是 2px solid 的 outline（不占布局，选中时别的块不会跳位）：%s"
       % (sel_rule.group(1) if sel_rule else "<没找到>"))
    ck("t17_css_uses_outline_not_border",
       bool(sel_rule) and "border" not in sel_rule.group(1),
       "描边改用 border 会占布局：%s" % (sel_rule.group(1) if sel_rule else ""))

    # ---------- 状态写在属性上，不许动 className ----------
    # 真正打标记的是 mark()，paintSelection 只负责找到该标的那些元素，
    # 所以两条一起看：只看 paintSelection 会以为它没写任何东西。
    paint = js_body(app_scan, "function paintSelection") + \
        js_body(app_scan, "function mark(e, on)")
    ck("t17_paint_uses_dataset", bool(paint) and "dataset.sel" in paint,
       "选中标记必须写 data-sel：%r" % paint[:160])
    ck("t17_paint_never_touches_class",
       bool(paint) and "className" not in paint,
       "动了 className：既有断言按 class=\"note pnode\" 的字面量查形状，"
       "加 class 会把它们整片打瞎。%r" % paint[:160])
    ck("t17_paint_clears_sel",
       bool(paint) and "delete" in paint,
       "取消选中必须真的摘掉 data-sel：留个残留属性，"
       "「两侧各剩几个标记」那几条数出来的就是假数。%r" % paint[:160])
    ck("t17_paint_covers_both_panes",
       'querySelectorAll(".pnode[data-uid]")' in paint and
       'querySelectorAll("[data-pvuid]")' in paint and
       'querySelectorAll(".pgroup[data-owner]")' in paint,
       "预览节点、右栏积木、容器的分组框三处都得跟上")
    ck("t17_pv_carries_uid_marker",
       re.search(r'd\.dataset\.pvuid\s*=\s*n\.uid', app_scan) is not None,
       "预览节点没挂 data-pvuid，就没法和右栏积木一一对应")

    # ---------- 选中：双向 + 再点一次取消 ----------
    sel = js_body(app_scan, "function selectBlock")
    ck("t17_toggle_off", bool(sel) and "null : uid" in sel,
       "再点一次必须取消选中：%r" % sel[:200])
    bind = js_body(app_scan, "function bindSelection")
    ck("t17_binds_both_panes",
       bool(bind) and bind.count("addEventListener") == 2 and
       '.closest(".pnode[data-uid]")' in bind and
       '.closest("[data-pvuid]")' in bind,
       "两个方向都得绑上：右栏 .pnode 与预览 [data-pvuid] 各一个监听。%r" % bind[:200])
    ck("t17_blank_click_clears",
       bool(bind) and "? box.dataset.uid : null" in bind and
       "? n.dataset.pvuid : null" in bind,
       "点到空白处要传 null（= 取消），不能什么都不做：%r" % bind[:240])
    ck("t17_select_ignores_buttons",
       bool(bind) and 'closest("input, textarea, button")' in bind,
       "按钮 / 输入框上的点击不该顺手改选中：会把「删这一块」变成「先选中再删」")

    # ---------- 自动保存 ----------
    ck("t17_plan_key", 'var PLAN_KEY = "uw_plan_v1"' in app_scan, "没有方案存档的键名")
    save = js_body(app_scan, "function savePlan")
    ck("t17_saveplan_guards_lsok",
       bool(save) and "if (!lsOK)" in save and "PLAN_KEY" in save,
       "savePlan 必须沿用 lsOK 降级，file:// 下不能抛：%r" % save[:200])
    pay = js_body(app_scan, "function planPayload")
    ck("t17_saveplan_saves_all_boards", "boards: boards" in pay,
       "存档必须含三个界面，只存当前界面等于把另外两个丢了")
    ck("t17_save_hangs_off_rendercanvas",
       "savePlan()" in js_body(app_scan, "function renderCanvas"),
       "自动保存没挂在 renderCanvas 上：漏挂一条路径（改元素 ID、改标注）就等于丢数据")
    # 元素 ID 与标注这两个输入框刻意不重画画布（会把输入框换掉、光标跳走），
    # 所以它们必须各自显式存一次盘，否则刷新必丢——而标注恰恰是「告诉你」那件事里
    # 唯一不可替代的部分。
    ck("t17_id_input_saves",
       "n.id = idIn.value; savePlan();" in app_scan,
       "元素 ID 输入框没有存盘")
    ck("t17_note_input_saves",
       "n.note = ta.value; savePlan();" in app_scan,
       "标注输入框没有存盘：用户写完刷新就没了")
    ck("t17_restore_on_boot",
       "restorePlan();" in js_body(app_scan, "function init"),
       "init 里没有恢复存档：不恢复就不是「刷新不丢」")
    # 存档读回来必须补齐字段：老存档少一个键就整份作废太霸道，用户攒的东西没了。
    ck("t17_normalize_node", "function normalizeNode" in app_scan,
       "没有逐块补齐字段的 normalizeNode")

    # ---------- 导出：ui.py / Markdown / JSON ----------
    ck("t17_py_func_shape",
       re.search(r'out\.push\("def draw_" \+ activeTab \+ "_content\(layout, state\):"\)',
                 app_scan) is not None,
       "ui.py 没有生成 draw_<界面>_content(layout, state) 这层壳")
    ck("t17_py_declares_unverified",
       "UNVERIFIED_NOTICE" in app_scan and "未经验证" in app_scan,
       "ui.py 没有声明「未经验证」")
    lvl = js_body(app_scan, "function pyLevel")
    ck("t17_py_comments_every_block",
       bool(lvl) and "n.id" in lvl and "pyNoteLines" in lvl and
       re.search(r'out\.push\(head \+ "  —— 工作台自动生成，未经验证"\)', app_scan) is not None,
       "每一块都要带「元素 ID + 你的标注 + 未经验证」的注释")
    # row / column 共用一条分支（同一个调用形式，差别只在 wkey），
    # 所以静态侧认这一条分支，另外几个容器是各自写死的调用名。
    ck("t17_py_translates_row_column",
       bool(lvl) and 'host + "." + n.wkey + "(" + kwc + ")"' in lvl and
       'base = (n.wkey === "row") ? "row" : "col"' in lvl,
       "row / column 没有翻成 host.row(...) / host.column(...)")
    for kind, call in (("box", '.box('), ("split", '.split('),
                       ("grid_flow", '.grid_flow('), ("panel", '.panel(')):
        ck("t17_py_translates_%s" % kind, ('host + "%s"' % call) in lvl,
           "容器 %s 没有翻成 %s" % (kind, call.strip(".(")))
    leaf = js_body(app_scan, "function pyLeaf")
    for kind, call in (("label", ".label("), ("operator", ".operator("),
                       ("prop", ".prop("), ("textbox", ".textbox(")):
        ck("t17_py_translates_%s" % kind, (call in leaf),
           "叶子 %s 没有翻成 host%s…" % (kind, call))
    ck("t17_py_translates_separator", 'host + ".separator()"' in lvl,
       "separator 没翻成代码")
    ck("t17_py_translates_scale_y", 'host + ".scale_y = "' in lvl,
       "scale_y 没翻成属性赋值")
    ck("t17_py_indents_recursion",
       bool(lvl) and "pyLevel(out, todo, used, n.uid, vn, depth + 1)" in lvl,
       "容器没有把子积木缩进一层递归下去：嵌套会平铺，树就没了")
    ck("t17_py_no_fake_codes",
       "n.downgraded" in app_scan and re.search(
           r"if \(n\.downgraded\) \{[\s\S]{0,400}?不生成代码", app_scan) is not None,
       "降级块不许生成代码：谎称它会出现，预览和代码都不诚实")
    md = js_body(app_scan, "function buildMarkdown")
    for sec in ("当前搭了什么", "你的标注原文", "降级方案", "这版还没验证过"):
        ck("t17_md_section_%s" % sec[:6], sec in md, "方案说明缺「%s」这一节" % sec)
    ck("t17_md_unverified", "还没有在真实 Blender 里验证过" in app_scan,
       "方案说明必须写明这版没在真实 Blender 里验证过")
    ck("t17_json_marked_unverified", "verified_in_blender: false" in app_scan,
       "方案 JSON 必须标 verified_in_blender=false")
    ck("t17_json_keeps_legacy_keys",
       "annotations: annotations" in app_scan and "proposal: proposal" in app_scan,
       "方案 JSON 必须仍带 annotations / proposal（既有断言按这两个字段核对导出）")

    # ---------- 剪贴板降级：三级，一级都不许少 ----------
    cp = js_body(app_scan, "function copyText")
    ck("t17_clipboard_api", bool(cp) and "navigator.clipboard" in cp,
       "没走 navigator.clipboard")
    ck("t17_clipboard_exec_fallback", bool(cp) and "execCommand" in cp,
       "file:// 下 clipboard API 多半没有，没有 execCommand 这级就彻底拿不到代码")
    ck("t17_clipboard_manual_fallback",
       bool(cp) and "select-only" in cp and re.search(r"ta\.select\(\)", cp) is not None,
       "没有「选中文本让用户 Ctrl+C」这最后一级")
    ck("t17_clipboard_swallowed",
       bool(cp) and cp.count("catch") >= 2 and "done(" in cp,
       "剪贴板失败不许抛到外面：一次「没复制上」不该让页面崩掉")
    # 自检：strip_js_comments 必须真把行注释抹掉。留着它的话，上面那条
    # 「函数体里有 execCommand」会被注释里的同一句话满足——代码删了照样绿。
    ck("t17_comment_stripper_kills_line_comments",
       "//" not in strip_js_comments("var a = 1;  // execCommand(x)\n") and
       "//" in strip_js_comments("var u = \"https://x\";"),
       "strip_js_comments 没抹掉行注释（静态断言会被注释字面量满足）")
    ck("t17_download_revokes", "revokeObjectURL" in app_scan,
       "Blob URL 不 revoke 会一直挂在文档的 URL 表上")


def select_checks(page):
    """Task 17：点积木 -> 左边预览描一圈，反之亦然。

    读数全部来自浏览器算出来的样式与几何：
      outlineColor/Width/Style —— getComputedStyle，不是我们写的选择器名。
      covered / inside          —— 被选中的容器区域里装了几块子积木、其中几块
                                  真的落在那道描边围出的矩形之内（几何判定）。
      togglePv / togglePnode    —— 再点一次之后两侧各剩几个标记。
      backPvSel / backPnodeSel  —— 改成从预览点，右栏跟没跟上。
    """
    at = report(page, "select-report")
    ck("select_hook_ran", bool(at) and at.get("sel-uid", "") not in ("", None),
       "选中钩子没跑起来：%s" % at)
    ck("select_target_is_container", at.get("target-id") == "chat.options",
       "应该选中容器 chat.options（它里面还套着子块），实际选中 %r"
       % at.get("target-id"))
    ck("select_one_each_side",
       at.get("pv-sel") == "1" and at.get("pnode-sel") == "1",
       "点一次之后两侧应各标一块：预览 %s / 画布 %s"
       % (at.get("pv-sel"), at.get("pnode-sel")))
    ck("select_group_frame_follows", at.get("pgroup-sel") == "1",
       "右栏那个容器的分组框也要跟着描：%s" % at.get("pgroup-sel"))
    # 描边色必须是实测色板里那唯一的蓝 #4772b3 = rgb(71, 114, 179)。
    ck("select_outline_color", at.get("outline-color") == "rgb(71, 114, 179)",
       "描边色应当是 #4772b3（实测的选中蓝），实际 %r" % at.get("outline-color"))
    ck("select_outline_width", at.get("outline-width") == "2px",
       "描边宽度应当是 2px，实际 %r" % at.get("outline-width"))
    ck("select_outline_solid", at.get("outline-style") == "solid",
       "描边应当是实线（虚线在这套界面里读作「可以拖进去」），实际 %r"
       % at.get("outline-style"))
    covered = int(at.get("covered", "0") or 0)
    inside = int(at.get("inside", "0") or 0)
    ck("select_container_has_children", covered >= 3,
       "选中的容器里至少装着 3 块子积木（否则「整块描边」无从谈起），实际 %d" % covered)
    ck("select_outline_covers_children", covered > 0 and inside == covered,
       "容器描边必须把 %d 块子积木全圈进去，实际只圈住 %d 块——"
       "只描标题行就是这个症状" % (covered, inside))
    ck("select_toggle_off",
       at.get("toggle-pv") == "0" and at.get("toggle-pnode") == "0",
       "再点一次应当取消选中：预览还剩 %s / 画布还剩 %s"
       % (at.get("toggle-pv"), at.get("toggle-pnode")))
    ck("select_blank_clears",
       at.get("blank-pv") == "0" and at.get("blank-sel-uid") == "",
       "点空白处应当什么都不选中：预览 %s / selUid %r"
       % (at.get("blank-pv"), at.get("blank-sel-uid")))
    ck("select_preview_to_canvas",
       at.get("back-pv-sel") == "1" and at.get("back-pnode-sel") == "1",
       "从预览点，右栏对应积木也要被选中：预览 %s / 画布 %s"
       % (at.get("back-pv-sel"), at.get("back-pnode-sel")))
    ck("select_says_it", "选中" in (at.get("status") or ""),
       "选中/取消都要说话：%r" % at.get("status"))


def save_checks(save_page, restore_page):
    """Task 17：自动保存 + 刷新不丢。

    两条腿：save_page 先存盘并把 localStorage 原样读回来逐字核对；
    restore_page 是**另一次页面加载**（同一份浏览器档案，所以 localStorage
    是通的），走的就是真实刷新那条路径。
    """
    at = report(save_page, "save-report")
    ck("save_hook_ran", bool(at),
       "存档钩子没跑起来")
    # file:// 在 Chrome 下必然存不了（SecurityError）。这种情况下不能安静地
    # 把这十几条断言蒸发掉——按既有的做法，记失败并说清是通道的问题。
    ck("save_local_storage_usable", at.get("ls-o-k") == "1",
       "file:// 下 localStorage 不可用（Chrome 会抛 SecurityError，"
       "Edge 正常）：自动保存这一整块无法验证")
    ck("save_wrote", at.get("wrote") == "1",
       "savePlan 没有真的写进 localStorage")
    blocks = int(at.get("blocks", "0") or 0)
    ck("save_roundtrip_all_blocks", int(at.get("stored", "0") or 0) == blocks and blocks > 0,
       "存了 %s 块，读回来只有 %s 块" % (at.get("blocks"), at.get("stored")))
    ck("save_keeps_nesting", int(at.get("nested", "0") or 0) > 0,
       "读回来的块全成了顶层：归属（parent）没存进去")
    ck("save_keeps_note", at.get("note") == "这句注解必须在刷新之后还在",
       "标注没存住，读回来是 %r" % at.get("note"))
    ck("save_keeps_content", at.get("content", "") not in ("", "{}"),
       "内容（按钮文字 / 占位提示之类）没存住")
    ck("save_keeps_uid_seq", int(at.get("uid-seq", "-1") or -1) >= blocks,
       "uid_seq 没跟着涨：恢复之后新积木会撞上老 uid，标注就贴错块了")

    rt = report(restore_page, "restore-report")
    ck("restore_hook_ran", bool(rt), "恢复钩子没跑起来")
    # 注意 lsOK 在 DOM 里落成 data-ls-o-k（dataset 把每个大写字母前面加短横），
    # 写成 ls-ok 会读到 None——一条恒红的假断言比没有断言更糟。
    ck("restore_ls_ok", rt.get("ls-o-k") == "1",
       "这一次连 localStorage 都读不了")
    ck("restore_brings_blocks_back",
       rt.get("restored") == at.get("blocks") and int(rt.get("restored", "0") or 0) > 0,
       "刷新之后恢复了 %s 块，存之前是 %s 块" % (rt.get("restored"), at.get("blocks")))
    ck("restore_keeps_note", rt.get("note") == "这句注解必须在刷新之后还在",
       "刷新之后标注没了：%r" % rt.get("note"))
    ck("restore_keeps_nesting",
       rt.get("nested") == at.get("nested") and int(rt.get("nested", "0") or 0) > 0,
       "刷新之后层级塌了：%s vs %s" % (rt.get("nested"), at.get("nested")))
    ck("restore_three_boards_kept",
       "detail" in rt and "settings" in rt,
       "恢复报告没报出三个界面各自的块数")
    ck("restore_says_it", "恢复" in (rt.get("status") or ""),
       "恢复之后状态条应当说清楚：%r" % rt.get("status"))


def export_checks(page, vocab):
    """Task 17：三种导出。

    报的是生成出来的**字符串**，不是「点没点过按钮」：生成器少一层缩进、
    把标注吞了，点一百次按钮也是错的。
    """
    at = report(page, "export-report")
    ck("export_hook_ran", bool(at) and int(at.get("py-lines", "0") or 0) > 20,
       "导出钩子没跑起来：%s" % at)
    ck("export_py_function",
       at.get("py-has-func") == "1",
       "ui.py 没有 def draw_chat_content(layout, state): 这层壳")
    # 页面上那段 <pre> 里必须真的有那行壳（py-head 只截了前 4 行，量不到它）。
    ck("export_py_function_visible",
       "def draw_chat_content(layout, state):" in pre_of(page),
       "页面上那段 <pre> 里没有 def draw_chat_content(layout, state):")
    # 缩进是这个生成器最要紧的形状：容器比它的直接孩子浅正好一层。
    # 查子串 "    " 没用（那对任何文件都成立），量的是两行的真实列差。
    ck("export_py_indents_one_level",
       at.get("py-has-indent") == "4" and at.get("py-indent-n", "0") == "3",
       "容器必须比它的直接孩子深正好一层（4 列）；抽了 %s 处，差值 %s"
       % (at.get("py-indent-n"), at.get("py-has-indent")))
    ck("export_py_carries_note", at.get("py-has-note") == "1",
       "ui.py 里没带上积木的标注")
    # 每一块都得声明「未经验证」，一块都不能漏。
    unv = int(at.get("py-has-unverified", "0") or 0)
    ck("export_py_unverified_every_block", unv >= 5,
       "ui.py 里只有 %d 处写了「未经验证」：每块都该有一处" % unv)
    # 数量对着示例面板的真数据算，不写死 9：示例面板一改，写死的数字就会
    # 变成一条永远红或者永远绿的假断言。
    panel = (vocab.get("example_panels") or {}).get("chat", {}).get("blocks") or []
    want_op = len([b for b in panel if b["wkey"] == "operator"])
    # TODO 一共几处：没填元素 ID 的算子 + 没填元素 ID 的 prop/textbox 属性名。
    # 文末清单标题里那一次不算进 TODO 计数。
    want_todo = len([b for b in panel
                     if b["wkey"] in ("operator", "prop", "textbox")
                     and not b.get("element_id")])
    ck("export_py_has_ops", at.get("py-has-op") == str(want_op),
       "示例面板里 %d 个 operator，ui.py 里翻出 %s 个"
       % (want_op, at.get("py-has-op")))
    ck("export_py_has_separator", at.get("py-has-sep") == "1",
       "真点一个 separator 上来，ui.py 里应当正好有 1 条 layout.separator()，"
       "实际 %s 条" % at.get("py-has-sep"))
    ck("export_py_reports_todo", at.get("py-todo") == str(want_todo),
       "应当报出 %d 处 TODO（示例面板里没填元素 ID 的算子 / 属性名），实际 %s"
       % (want_todo, at.get("py-todo")))
    # 文末清单除了「代码里的 TODO 占位」，还会列出「参数没写取值」的那几处，
    # 所以清单长度 = 占位数 + 取值缺失数。两个数都对着示例面板的真数据算。
    py_true_flags = {"align", "even_columns", "even_rows", "row_major",
                     "default_closed", "use_property_split", "translate"}
    containers = {"row", "column", "box", "split", "grid_flow", "panel"}
    want_flag = 0
    for b in panel:
        if b["wkey"] not in containers:
            continue
        for tok in re.split(r"[,，\s]+", (b.get("params") or "").strip()):
            if tok and "=" not in tok and tok not in py_true_flags:
                want_flag += 1
    ck("export_py_checklist_matches",
       at.get("py-checks") == str(want_todo + want_flag),
       "文末清单说有 %s 处（应为 %d 处占位 + %d 处取值缺失 = %d），"
       "代码里实际 %s 处 TODO"
       % (at.get("py-checks"), want_todo, want_flag, want_todo + want_flag,
          at.get("py-todo")))
    ck("export_md_is_a_doc", int(at.get("md-lines", "0") or 0) >= 60,
       "方案说明只有 %s 行：一份能据此写实施计划的文档不该这么短"
       % at.get("md-lines"))
    for k, name in (("md-has-tree", "一、当前搭了什么"), ("md-has-notes", "二、你的标注原文"),
                    ("md-has-down", "三、降级方案"), ("md-has-unverified", "四、这版还没验证过")):
        ck("export_md_%s" % k, at.get(k) == "1", "方案说明缺「%s」" % name)
    ck("export_md_keeps_note_verbatim", at.get("md-has-note-text") == "1",
       "方案说明里没有某条标注的原文（元素 ID %r 那块）："
       "「告诉你」靠的就是这一节" % at.get("md-note-id"))
    keys = (at.get("json-keys") or "").split(",")
    for want in ("annotations", "boards", "markdown", "proposal", "ui_py",
                 "verified_in_blender"):
        ck("export_json_has_%s" % want, want in keys,
           "方案 JSON 缺字段 %s（实际 %s）" % (want, keys))
    ck("export_json_three_boards", at.get("json-boards") == "3",
       "方案 JSON 应当含三个界面，实际 %s" % at.get("json-boards"))
    ck("export_json_embeds_py", at.get("json-py") == "1",
       "方案 JSON 里嵌的那份 ui.py 与面板上显示的不一致")
    ck("export_json_marked_unverified", at.get("json-verified") == "1",
       "方案 JSON 没有标 verified_in_blender=false")
    # 页面上那段 <pre> 必须真的装得下代码：用户看得见、选得中，才是最后的兜底。
    ck("export_pre_shows_code", int(at.get("pre", "0") or 0) > 200,
       "导出面板里那段 <pre> 是空的（%s 字符）" % at.get("pre"))
    # 这两条查的是 <pre> 的切片，不是整页：整页上「layout.row(align=True)」
    # 在控件架卡片里就有，<pre> 空了也照样绿。
    ck("export_pre_has_code", "layout.row(align=True" in pre_of(page),
       "页面上那段 <pre> 里没有 layout.row(align=True)：剪贴板全挂时它就是唯一的出口")
    ck("export_pre_has_warning", "未经验证" in pre_of(page),
       "页面上那段 <pre> 里没写「未经验证」")
    # 参数框里只写了个开关名（columns）时，必须保住词汇表给的默认值。
    # 写成 columns=True / columns=None 会让网格静默塌成一列，而且不报任何错。
    ck("export_bare_param_keeps_default",
       "columns=None" not in pre_of(page) and "columns=2" in pre_of(page),
       "示例面板里 grid_flow 的参数写的是裸 columns，导出时应当保留词汇表"
       "给的默认 columns=2，而不是 None 或 True")


def select_leaf_checks(page):
    """从预览点一个叶子块：描边只圈它自己那一格，右栏跟着选中。

    与 select_checks 分开是因为叶子没有子块——「整块描边」那条在容器上量，
    「只圈自己」这条得在叶子上量，两者是不同的故障。
    """
    at = report(page, "select-leaf-report")
    ck("select_leaf_hook_ran", bool(at) and at.get("target-wkey") == "textbox",
       "叶子选中钩子没跑起来：%s" % at)
    ck("select_leaf_marks_both_sides",
       at.get("pv-sel") == "1" and at.get("pnode-sel") == "1",
       "从预览点一个叶子，两侧应各标一块：预览 %s / 画布 %s"
       % (at.get("pv-sel"), at.get("pnode-sel")))
    ck("select_leaf_outline_only_itself", at.get("covered") == "0",
       "叶子块底下不该还有别的预览节点（那说明点中的不是叶子）：%s" % at.get("covered"))
    ck("select_leaf_outline_color",
       at.get("outline-color") == "rgb(71, 114, 179)" and
       at.get("outline-width") == "2px",
       "叶子描边色 / 宽度应当与容器一致：%r %r"
       % (at.get("outline-color"), at.get("outline-width")))


def pre_of(p):
    """取 #py-out 那段代码的内容切片。

    必须切片再查，不能在整份 page 上查子串：控件架的卡片上本来就印着
    「layout.row(align=True)」，整页查的话，就算 <pre> 是空的、
    那条断言照样绿 —— 这正是「变异改了断言抓不住」的那一类。
    """
    m = re.search(r'<pre id="py-out">(.*?)</pre>', p, re.S)
    return m.group(1) if m else ""


def _fb_for_blocker(rkey):
    with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
        v = json.load(fh)
    for r in v["rejected"]:
        if r["key"] == rkey:
            return r["blocker"]
    return "<missing>"


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:            # 汇总行不能被异常吞掉：rc=0 是假绿
        import traceback
        traceback.print_exc()
        ck("harness_no_exception", False, "测试自身抛异常：%r" % (exc,))
        print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
        sys.exit(1)