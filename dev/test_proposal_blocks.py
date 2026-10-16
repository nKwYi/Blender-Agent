# -*- coding: utf-8 -*-
"""Task 19：业务块（blocks.json）的验收检查。纯标准库，不进 Blender。

这一份与 dev/test_proposal_vocab.py 是**两套分工**，不是两份重复：
  test_proposal_vocab 盯 UILayout 原语（12 个控件、参数白名单、嵌套、降级）
  本文件盯业务块（16 块、每块的出处、变体、无嵌套、无参数框、导出原样带走）

两条腿：
  1. Python 侧查 blocks.json / data.js / app.js 的静态性质。
  2. 无头 Edge 侧真渲染提案视图，核对业务块那一层实际长什么样。

关于「不许编」：本文件**独立重算**一遍出处核对（gen_grounded_*），
而不是转述 dev/build_blocks.py 自己的 _selfcheck。生成器的自检与它的
生成器是同一份代码，一起错就会一起绿；这里从 ui.py 重新读一遍，
两边才对得上。
"""
import ast
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
UI_PY = os.path.join(ROOT, "blender_deepseek_agent", "ui.py")
UI_IDS = os.path.join(ROOT, "blender_deepseek_agent", "ui_ids.py")

EXPECT_BLOCKS = 16
EXPECT_TAB_COUNTS = {"chat": 7, "detail": 4, "settings": 5}
EXPECT_STATUS_VARIANTS = ["busy", "approve", "partial", "failed"]
# renderDemo 只画这 11 种形状；数据里出现一种它不认的，界面就是一个没样式的空盒子。
DEMO_KINDS = ["row", "col", "box", "split", "grid", "panel", "label", "btn",
              "prop", "rule", "gap", "msgtxt", "composer"]

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


def demo_item_count(demo):
    """一个图示里一共该画出几个小方块 = 顶层 items + 每组细节里的 items。

    为什么不是 len(demo["items"])：Task 20 起规格选项组是双层盒，那 9 个
    选择按钮在 groups 里。只数顶层的话里层根本没画出来也不会红。
    """
    n = len((demo or {}).get("items") or [])
    for g in ((demo or {}).get("groups") or []):
        n += len(g.get("items") or [])
    return n


def js_body(src, header):
    """截出一个 JS 函数体（含 header 那一行）。"""
    i = src.find(header)
    if i < 0:
        return ""
    j = src.find("\n}", i)
    return src[i:(j + 2 if j > 0 else len(src))]


# ---------------- 静态：数据 ----------------

def data_checks(doc):
    ck("blocks_count", len(doc["blocks"]) == EXPECT_BLOCKS,
       "业务块应为 %d 块，实际 %d" % (EXPECT_BLOCKS, len(doc["blocks"])))
    keys = [b["key"] for b in doc["blocks"]]
    ck("blocks_keys_unique", len(set(keys)) == len(keys), "块 key 重复：%s" % keys)

    by_tab = {}
    for b in doc["blocks"]:
        by_tab.setdefault(b["tab"], []).append(b["key"])
    ck("blocks_tab_counts",
       {k: len(v) for k, v in sorted(by_tab.items())} == EXPECT_TAB_COUNTS,
       "每个界面的块数应为 %s，实际 %s"
       % (EXPECT_TAB_COUNTS, {k: len(v) for k, v in sorted(by_tab.items())}))

    want_block = {"key", "label", "tab", "what", "variants", "default_variant",
                  "editable", "slots", "element_id", "demo", "ui_py"}
    want_var = {"key", "label", "what", "ui_py", "demo", "rewrites"}
    ck("blocks_schema",
       all(set(b) == want_block for b in doc["blocks"]),
       "块字段集不对：%s" % sorted(set(doc["blocks"][0]) ^ want_block))
    bad_v = [(b["key"], sorted(set(v))) for b in doc["blocks"]
             for v in b["variants"] if set(v) != want_var]
    ck("blocks_variant_schema", not bad_v, "变体字段集不对：%s" % bad_v[:3])

    # 每块都要说清「这是什么、什么时候出现」——这是替换掉 API 词汇表的
    # 全部意义。一句空的 what 会让用户退回猜名字。
    ck("blocks_what_says_something",
       all(len(str(b["what"])) >= 12 for b in doc["blocks"]),
       "有块的 what 太短，等于没解释：%s"
       % [(b["key"], b["what"]) for b in doc["blocks"] if len(str(b["what"])) < 12])

    # 图示：kind 必须是渲染器认识的，且给出内容（rule/gap 除外）。
    bad_kind = [(b["key"], b["demo"].get("kind")) for b in doc["blocks"]
                if b["demo"].get("kind") not in DEMO_KINDS]
    ck("blocks_demo_kinds_known", not bad_kind,
       "有块的图示形状渲染器不认识：%s（清单 %s）" % (bad_kind, DEMO_KINDS))
    no_items = [b["key"] for b in doc["blocks"]
                if b["demo"]["kind"] not in ("rule", "gap") and not b["demo"].get("items")]
    ck("blocks_demo_items_declared", not no_items,
       "这些块没有图示内容，界面上画出来是空壳：%s" % no_items)
    bad_vkind = [(b["key"], v["key"], v["demo"].get("kind"))
                 for b in doc["blocks"] for v in b["variants"]
                 if v["demo"].get("kind") not in DEMO_KINDS]
    ck("blocks_variant_demo_kinds_known", not bad_vkind,
       "有变体的图示形状渲染器不认识：%s" % bad_vkind[:3])
    ck("blocks_variant_has_demo",
       all(v.get("demo", {}).get("kind") for b in doc["blocks"] for v in b["variants"]),
       "有变体没给图示：切样式就看不出那块长什么样")

    # 状态提示条必须真有四种样式，且 failed 是其中之一（它是全 UI 唯一的报错块）。
    status = [b for b in doc["blocks"] if b["key"] == "chat_status"][0]
    ck("blocks_status_variants",
       [v["key"] for v in status["variants"]] == EXPECT_STATUS_VARIANTS,
       "状态提示条应有 %s 四种样式，实际 %s"
       % (EXPECT_STATUS_VARIANTS, [v["key"] for v in status["variants"]]))
    ck("blocks_status_default",
       status["default_variant"] == "busy",
       "状态提示条默认应是 busy，实际 %r" % status["default_variant"])
    ck("blocks_status_failed_is_alert",
       any(".alert = True" in v["ui_py"] for v in status["variants"]),
       "failed 变体应当是全 UI 唯一带 alert 的那块（红在主题里不存在，"
       "只能靠 alert=True）")
    ck("blocks_status_partial_has_two_columns",
       any("还没做：" in v["ui_py"] and "已经做了：" in v["ui_py"]
           for v in status["variants"]),
       "partial 变体应当分「已经做了 / 还没做」两栏")

    # --- 本轮那五条用户意见在数据这一层的对应物 ---
    ui_lines = read(UI_PY).split("\n")
    by_key = {b["key"]: b for b in doc["blocks"]}

    # 第 1 条：页签去掉「AI」两个字。查的是**所有**图示的条目，不只是页签条
    # 那一张卡——只查一张卡的话，别的块里留一个「AI 对话」照样绿。
    hit_ai = []
    for b in doc["blocks"]:
        demos = [b["demo"]] + [v["demo"] for v in b["variants"]]
        for d in demos:
            for t in (d.get("items") or []) + \
                    [(g.get("title") or "") for g in (d.get("groups") or [])]:
                if "AI 对话" in str(t):
                    hit_ai.append("%s:%s" % (b["key"], t))
    ck("blocks_tabbar_label_dropped_ai", not hit_ai,
       "页签上还有「AI 对话」：%s" % hit_ai[:3])
    ck("blocks_tabbar_items_are_short",
       by_key["chat_tabbar"]["demo"]["items"] == ["对话", "详情", "设置"],
       "页签条的图示应是「对话 / 详情 / 设置」，实际 %s"
       % by_key["chat_tabbar"]["demo"]["items"])

    # 第 3 条：底部常用操作一行 4 个。数据上是 cols=4 + 四个条目；
    # 真的排成一行由 DOM 那侧的 pills 读数量（数据写 4 而 CSS 没跟上会红）。
    pills = by_key["chat_pills"]["demo"]
    ck("blocks_pills_four_in_one_row",
       pills.get("cols") == 4 and len(pills.get("items") or []) == 4,
       "快捷指令应是 cols=4 的四个，实际 cols=%s items=%s"
       % (pills.get("cols"), len(pills.get("items") or [])))

    # 第 2 + 第 5 条：规格那块双层盒——外层一个盒装引子，里面每个细节
    # 自己一个盒，标题与那一串选择按钮同盒。判据落在数据形状上，
    # 「引子与按钮真的在同一个盒里」由 DOM 那侧的 qs 读数量。
    qs = by_key["chat_questions"]["demo"]
    groups = qs.get("groups") or []
    ck("blocks_questions_outer_box_holds_intro",
       qs.get("kind") == "box" and len(qs.get("items") or []) == 1,
       "规格选项组的外层应是装着引子那一段的一个盒，实际 kind=%s items=%s"
       % (qs.get("kind"), qs.get("items")))
    ck("blocks_questions_double_box",
       len(groups) == 3 and all(g.get("title") and g.get("items")
                                and g.get("item_icons") for g in groups),
       "规格选项组里应有三个各自成盒的细节（标题 + 按钮 + 图标），实际 %s"
       % [(g.get("title"), len(g.get("items") or [])) for g in groups])

    # 图示里的图标名必须是实测里真有的：ui.py 真写过的 + vocabulary.json
    # 的图标名册。这里从源文件**重新读一遍**，不复述生成器的自检。
    real = set(re.findall(r"'([A-Z][A-Z0-9_]{2,})'", "\n".join(ui_lines)))
    vocab_path = os.path.join(WB, "vocabulary.json")
    if os.path.exists(vocab_path):
        real |= set((json.loads(read(vocab_path)) or {}).get("icons") or [])
    bad_ico = []
    for b in doc["blocks"]:
        for d in [b["demo"]] + [v["demo"] for v in b["variants"]]:
            for ic in (d.get("icons") or []):
                if ic not in real:
                    bad_ico.append("%s:%s" % (b["key"], ic))
            for g in (d.get("groups") or []):
                for ic in [g.get("icon")] + list(g.get("item_icons") or []):
                    if ic and ic not in real:
                        bad_ico.append("%s:%s" % (b["key"], ic))
    ck("blocks_demo_icons_are_real", not bad_ico,
       "图示里写了实测中不存在的图标名：%s" % bad_ico[:4])
    # 图标数不许多过条目数：多一个就是画错位（角标挂到了别人的方块上）。
    over = []
    for b in doc["blocks"]:
        for d in [b["demo"]] + [v["demo"] for v in b["variants"]]:
            if len(d.get("icons") or []) > len(d.get("items") or []):
                over.append(b["key"])
            for g in (d.get("groups") or []):
                if len(g.get("item_icons") or []) > len(g.get("items") or []):
                    over.append("%s/组" % b["key"])
    ck("blocks_demo_icons_not_overflow", not over,
       "有图示的图标数多过条目数：%s" % sorted(set(over)))
    ck("blocks_demo_icons_present",
       sum(1 for b in doc["blocks"] if b["demo"].get("icons")) >= 12,
       "几乎没块带图标：响应式图标那条就没有东西可显隐（带图标的块 %d/16）"
       % sum(1 for b in doc["blocks"] if b["demo"].get("icons")))

    # 第 4 条的导出侧：新增的那段代码必须写清三件事——宽度从哪来、
    # 宽/窄各自给什么（**窄的只给图标 = 文字置空**，不是 icon='NONE'）、
    # 以及「Blender 没有媒体查询 / 松手才重绘」。
    pre = doc.get("py_preamble") or {}
    body = list(pre.get("snippet") or [])
    ck("blocks_py_preamble_declared",
       set(pre) == {"key", "why", "snippet"} and len(body) >= 6 and
       str(pre.get("why", "")).strip(),
       "响应式图标那段必须带 why 与 snippet（新增代码不能悄悄混进 ui_py）：%s"
       % sorted(pre))
    miss_phrase = [w for w in ("context.region.width", "媒体查询", "松手",
                               "_uw_wide", 'else ""', "只给图标")
                   if not any(w in ln for ln in body)]
    ck("blocks_py_preamble_says_the_truth", not miss_phrase,
       "响应式图标那段缺这些必须写明的说明：%s" % miss_phrase)
    # 口径是反的这条本身：宽的给文字，窄的置空。写成 icon='NONE' 会把按钮上
    # 唯一认得出来的标志也抹掉，那不是「窄了只给图标」，那是「窄了什么都不给」。
    ck("blocks_py_preamble_narrow_keeps_icon",
       not any("'NONE'" in ln for ln in body if not ln.lstrip().startswith("#"))
       and any('if _uw_wide else ""' in ln for ln in body),
       "响应式图标那段应当把文字置空（icon 照留），不能把 icon 置成 'NONE'：%s"
       % [ln for ln in body if not ln.lstrip().startswith("#")])
    # 它是 ui.py 之外的新增代码，所以任何一行都不许与 ui.py 逐字相同——
    # 逐字相同就说明它是抄来的，那就不该走这张表。
    ck("blocks_py_preamble_is_new_code",
       all(ln.startswith("#") or ln.strip() not in set(x.strip() for x in ui_lines)
           for ln in body),
       "py_preamble 里混进了 ui.py 逐字已有的行（等于假装新增）")
    ck("blocks_py_preamble_icons_real",
       all(ic in real for ic in re.findall(r"'([A-Z][A-Z0-9_]{2,})'",
                                           "\n".join(body))),
       "py_preamble 里有实测中不存在的图标名")

    # 第 3 条的导出侧：长消息折叠也走单立的 py_helper 表。
    # 为什么单立：块的 ui_py 只许放 ui.py 里逐字存在的代码，而 layout.panel
    # 在 ui.py 里没有。塞进去会被 grounded_no_undeclared_lines 当成编造。
    hlp = doc.get("py_helper") or {}
    hb = list(hlp.get("snippet") or [])
    ck("blocks_py_helper_declared",
       set(hlp) == {"key", "why", "snippet"} and hb and
       str(hlp.get("why", "")).strip(),
       "长消息折叠那段必须单立一张表（key/why/snippet）：%s" % sorted(hlp))
    ck("blocks_py_helper_uses_native_panel",
       any("layout.panel" in ln and "default_closed" in ln for ln in hb) and
       any("open_default" in ln for ln in hb),
       "折叠必须用 layout.panel(idname, default_closed)（真能收起、自带原生箭头），"
       "不能自造折叠控件：%s" % hb)
    miss_h = [w for w in ("侧栏", "滚动", "text[:20]")
              if not any(w in ln for ln in hb)]
    ck("blocks_py_helper_says_the_truth", not miss_h,
       "折叠那段缺这些必须写明的说明（为什么要折 / 折成什么样）：%s" % miss_h)
    ck("blocks_py_helper_is_new_code",
       all(ln.startswith("#") or ln.strip() not in set(x.strip() for x in ui_lines)
           for ln in hb),
       "py_helper 里混进了 ui.py 逐字已有的行（等于假装新增）")
    try:
        ast.parse("def _pre():\n" + "\n".join(("    " + ln) if ln.strip() else ""
                                              for ln in hb))
        ck("blocks_py_helper_parses", True, "")
    except SyntaxError as exc:
        ck("blocks_py_helper_parses", False, "折叠那段解析不过：%s" % exc.msg)

    # 第 1 条：用户自己发的那条消息**一个盒，到此为止**，而且可折叠。
    bub = [v for v in by_key["chat_bubble"]["variants"]
           if v["key"] == by_key["chat_bubble"]["default_variant"]][0]
    ck("blocks_bubble_user_is_one_box",
       bub["demo"].get("kind") == "msgtxt" and len(bub["demo"].get("items") or []) == 1
       and not bub["demo"].get("groups"),
       "你说的话应是一个盒、一条内容、不再套盒（msgtxt），实际 kind=%s items=%d"
       % (bub["demo"].get("kind"), len(bub["demo"].get("items") or [])))
    ck("blocks_bubble_user_is_long",
       len((bub["demo"].get("items") or [""])[0]) > 20,
       "你说的话给的是一条 %d 字的短消息，折不断，折叠那条就没东西可验"
       % len((bub["demo"].get("items") or [""])[0]))
    ck("blocks_bubble_user_uses_panel",
       "_uw_msg_panel(" in bub["ui_py"] and "open_default=" in bub["ui_py"],
       "你说的话导出的代码应走 _uw_msg_panel 并带上 open_default，实际 %r"
       % bub["ui_py"])
    ck("blocks_bubble_user_rewrite_from_ui_py",
       any(rw["from"] == "ubox = layout.box()" for rw in bub["rewrites"]),
       "你说的话那一行的改写必须登记它在 ui.py 里的原句 ubox = layout.box()")

    # 第 4 条：输入框独占一行（照 ui.py:947-955）。
    cmp_ = by_key["chat_composer"]["demo"]
    ck("blocks_composer_textbox_own_row",
       cmp_.get("kind") == "composer" and str(cmp_.get("textbox") or "").strip()
       and len(cmp_.get("items") or []) == 2,
       "对话输入区应是「标签 + 高度一行，输入框另起一行」，实际 kind=%s items=%s "
       "textbox=%r" % (cmp_.get("kind"), cmp_.get("items"), cmp_.get("textbox")))
    ck("blocks_composer_preview_is_not_prop",
       cmp_.get("kind") != "prop",
       "对话输入区退回 prop 就又变成三样东西挤一行了")

    # 块级 ui_py 必须与默认变体逐字一致：导出只认块级这一个入口。
    mism = [b["key"] for b in doc["blocks"]
            if b["ui_py"] != [v for v in b["variants"]
                              if v["key"] == b["default_variant"]][0]["ui_py"]]
    ck("blocks_ui_py_is_default_variant", not mism,
       "块级 ui_py 与默认变体不一致（导出会讲另一个版本的故事）：%s" % mism)

    # ui_py 必须能被 Python 解析器接受：导出的就是它，解析不过等于导出是坏的。
    bad = []
    for b in doc["blocks"]:
        for v in b["variants"]:
            src = "def _draft():\n" + "\n".join(
                ("    " + ln) if ln.strip() else ""
                for ln in v["ui_py"].split("\n"))
            try:
                ast.parse(src)
            except SyntaxError as exc:
                bad.append("%s/%s: %s" % (b["key"], v["key"], exc.msg))
    ck("blocks_ui_py_parses", not bad,
       "有块的 ui_py 解析不过：%s" % bad[:3])


def grounding_checks(doc):
    """出处核对：每段 ui_py 的每一行都必须来自 ui.py，或已登记为改写。

    这是本文件最要紧的一条。业务块的全部价值就是「导出即插件里那段现成
    的代码」；只要有一行是编的，这个价值就没了，而界面上完全看不出来。
    """
    ui_lines = read(UI_PY).split("\n")
    ui_stripped = set(ln.strip() for ln in ui_lines)
    undeclared, bad_from, dup_slot = [], [], []
    for b in doc["blocks"]:
        for v in b["variants"]:
            declared = {}
            for rw in v["rewrites"]:
                if rw["from"].strip() not in ui_stripped:
                    bad_from.append("%s/%s: %r" % (b["key"], v["key"], rw["from"]))
                if not str(rw["why"]).strip():
                    undeclared.append("%s/%s 改写没写理由" % (b["key"], v["key"]))
                declared[rw["to"].strip()] = rw
            for ln in v["ui_py"].split("\n"):
                s = ln.strip()
                if not s or s in ui_stripped:
                    continue
                if s not in declared:
                    undeclared.append("%s/%s: %r" % (b["key"], v["key"], ln))
    ck("grounded_no_undeclared_lines", not undeclared,
       "有行既不在 ui.py 里、也没登记为改写：%s" % undeclared[:5])
    ck("grounded_rewrites_come_from_ui_py", not bad_from,
       "有改写登记的原句在 ui.py 里并不存在（等于凭空造了一句再签字）：%s"
       % bad_from[:3])

    # 反向：声明了改写却根本没改，是「登记了个寂寞」，会让这张表失去意义。
    fake = []
    for b in doc["blocks"]:
        for v in b["variants"]:
            for rw in v["rewrites"]:
                if rw["to"].strip() == rw["from"].strip() and rw["from"].strip() not in \
                        [ln.strip() for ln in v["ui_py"].split("\n")]:
                    fake.append("%s/%s" % (b["key"], v["key"]))
    ck("grounded_no_noop_rewrite", not fake,
       "有改写登记的 to/from 相同，等于没改：%s" % fake[:3])

    # 元素 ID 必须是 ui_ids.py 里真有的那几个，不许自己编一个。
    ids = set(re.findall(r'=\s*"([a-z_]+\.[a-z_]+)"', read(UI_IDS)))
    used = [b["element_id"] for b in doc["blocks"] if b["element_id"]]
    ck("blocks_element_ids_real", used and all(e in ids for e in used),
       "块用到的元素 ID 不在 ui_ids.py 里：%s（真实的有 %s）"
       % ([e for e in used if e not in ids], sorted(ids)))
    ck("blocks_element_id_optional",
       any(not b["element_id"] for b in doc["blocks"]),
       "所有块都填了元素 ID——它是可选的备注名，得留几块不填来证明能空着导出")


def slot_checks(doc):
    """可改文案：只许落在字符串字面量上，且一处只改一处。"""
    bad_lab, dup, missing, leaky = [], [], [], []
    for b in doc["blocks"]:
        seen = []
        for s in b["slots"]:
            # 同一个 label 可以在不同变体里各出现一次（状态提示条的
            # 「标题文字」在 approve / partial / failed 三段里各有一句），
            # 所以 editable 存的是「按次序去重后的 label」，不是逐条。
            if s["label"] not in seen:
                seen.append(s["label"])
            if not str(s["text"]).strip():
                bad_lab.append("%s/%s 文案是空的" % (b["key"], s["name"]))
            esc = str(s["text"]).replace('"', '\\"')
            if s["literal"] not in ('"%s"' % esc, 'f"%s"' % esc):
                bad_lab.append("%s/%s 字面量与文案对不上：%r vs %r"
                               % (b["key"], s["name"], s["literal"], s["text"]))
        if seen != list(b["editable"]):
            bad_lab.append("%s 的 editable 与 slots 的 label 顺序对不上：%s vs %s"
                           % (b["key"], b["editable"], seen))
        # 槽的 name 必须全块唯一：值是按 name 存的，重名会互相覆盖。
        names = [s["name"] for s in b["slots"]]
        if len(set(names)) != len(names):
            dup.append("%s: 槽 name 重复 %s" % (b["key"], names))
        # 每个槽在它出现的那些变体里都必须恰好一次：两次 = 改一处连着改两处。
        for v in b["variants"]:
            joined = v["ui_py"]
            for s in b["slots"]:
                if joined.count(s["literal"]) > 1:
                    leaky.append("%s/%s 的槽「%s」出现 %d 次"
                                 % (b["key"], v["key"], s["label"],
                                    joined.count(s["literal"])))
        # 声明了可改文案的块，至少得有一句真的出现在代码里。
        if b["slots"] and not any(
                any(s["literal"] in v["ui_py"] for s in b["slots"])
                for v in b["variants"]):
            missing.append(b["key"])
    ck("slots_editable_matches", not bad_lab, "可改文案定义有问题：%s" % bad_lab[:3])
    ck("slots_names_unique", not dup, "%s" % dup[:3])
    ck("slots_appear_at_most_once", not leaky,
       "有槽的字面量在同一段代码里出现多次（改一处会连着改两处）：%s" % leaky[:3])
    ck("slots_reach_real_code", not missing,
       "这些块声明了可改文案，但一句原文都没落在代码上：%s" % missing)
    # 反向：editable 里写了却在 slots 里找不到对应槽的 label，等于界面
    # 会给出一个改了不生效的输入框。
    ck("slots_editable_all_backed",
       all(s["label"] in b["editable"] for b in doc["blocks"] for s in b["slots"]),
       "有槽的文案名没列进 editable（界面上就没有它的输入框）")


def static_app_checks():
    app = read(os.path.join(WB, "app.js"))
    html = read(os.path.join(WB, "index.html"))
    css = re.sub(r"/\*.*?\*/", "", read(os.path.join(WB, "style.css")), flags=re.S)

    # 控件架分两层：业务块在上，UILayout 原语在折叠的高级区。
    ck("app_has_block_shelf", 'bcards.id = "block-cards"' in app,
       "app.js 没有渲染业务块控件架")
    ck("app_has_advanced_details", '"adv-primitives"' in app and "renderPrimitives" in app,
       "app.js 没有「高级：UILayout 原语」那层")
    # 默认收起。app.js 是用 DOM API 建的 details，所以「不许有 open」得
    # 拆成两件事查：真的建了 details、真的给了那个 id、且全文件任何地方
    # 都没把它设成展开（设一次就等于前功尽弃）。
    ck("app_adv_uses_details",
       'document.createElement("details")' in app and 'det.id = "adv-primitives"' in app,
       "高级区必须真用 <details> 折叠（不是 div + CSS 假装）")
    ck("app_advanced_collapsed_by_default",
       not re.search(r"\bdet\.open\s*=", app) and not re.search(r'\.open\s*=\s*true', app),
       "高级区不许被设成展开：<details> 默认就是收起的，显式 open 就前功尽弃")
    ck("app_primitives_kept",
       js_body(app, "function renderPrimitives") and
       "demo-panel-btn" in app and "widgetCard" in js_body(app, "function renderPrimitives"),
       "原语那一层没保住（12 张卡 / 插入示例面板按钮）")

    # 业务块不可再嵌套：两处把关——容器判定与画法分派。
    isc = js_body(app, "function isContainer")
    ck("app_biz_is_not_container",
       bool(isc) and re.search(r"if \(n && n\.bkey\) \{ return false; \}", isc),
       "业务块被当成容器了：它会被装东西、也会生出子块区")
    rnode = js_body(app, "function renderNode")
    ck("app_biz_node_branch",
       bool(rnode) and "renderBizNode" in rnode,
       "renderNode 没有分派到 renderBizNode（业务块会按原语那套画）")

    # 存档往返：业务块的 bkey 不能被 normalizeNode 变成 label。
    nz = js_body(app, "function normalizeNode")
    ck("app_normalize_keeps_bkey",
       bool(nz) and "bkey" in nz and 'bkey ? "" : String(n.wkey || "label")' in nz,
       "normalizeNode 没保住 bkey（刷新之后业务块会变成一块 label，"
       "界面看着没丢，导出的代码却换了东西）")

    # 导出：业务块不做翻译，直接用 blocks.json 里那段。
    lvl = js_body(app, "function pyLevel")
    ck("app_py_biz_branch", bool(lvl) and "pyBizLines" in lvl,
       "pyLevel 没有分派到 pyBizLines")
    ck("app_py_biz_no_translate",
       "v.ui_py" in js_body(app, "function pyBizLines") and
       "applyBizTexts" in js_body(app, "function pyBizLines"),
       "业务块导出没有原样带走 blocks.json 里那段 ui_py")
    # 文案替换只能落在字面量上：applyBizTexts 必须逐字找 literal。
    at = js_body(app, "function applyBizTexts")
    ck("app_text_edit_is_literal_only",
       bool(at) and "s.literal" in at and "src.replace" in at,
       "改文案的实现不是「逐字替换那个字面量」，会改坏结构")
    ck("app_text_edit_keeps_fstring", "pyStrF" in at,
       "改文案时没保住 f 前缀（f\"选择: {lbl}\" 会变成字面花括号）")

    # 业务块不生成参数框 / 归属下拉 / 移入移出。
    bn = js_body(app, "function renderBizNode")
    ck("app_biz_no_params_box",
       bool(bn) and 'data-field = "params"' not in bn and
       'class = "pin pinp"' not in bn,
       "业务块上还有参数框（业务块没有参数）")
    ck("app_biz_no_parent_select",
       bool(bn) and 'data-field = "parent"' not in bn,
       "业务块上还有归属下拉（业务块不可再嵌套）")
    ck("app_biz_no_move_buttons",
       bool(bn) and "移入上一个容器" not in bn and "移出上一层" not in bn,
       "业务块上还有移入/移出按钮")
    ck("app_biz_has_text_slots",
       bool(bn) and 'dataset.field = "btext"' in bn and 'dataset.field = "id"' in bn,
       "业务块没有改文案 / 备注名两样输入")

    # 备注名是可选的：不填也能导出，所以默认自动生成一个。
    ck("app_note_name_auto", "autoNoteName" in app,
       "备注名没有自动生成的兜底（用户不填就该有个默认名）")
    # 方案说明里业务块不该出现「参数：（空）」这种假字段。
    ck("app_md_biz_branch", "mdBizBlock" in app,
       "方案说明没有业务块那一支（会写出「参数：（空）」这种漏填了的假字段）")

    ck("html_no_biz_mount_needed", 'id="block-cards"' not in html,
       "业务块控件架由 app.js 渲染，index.html 里不该再留一个空挂载点")

    # 图示样式：渲染器认识的每种 kind 都得有规则，否则卡片是个没样式的空盒子。
    miss = [k for k in DEMO_KINDS if ".d-%s" % k not in css]
    ck("blocks_demo_css_defined", not miss,
       "style.css 缺这些图示样式：%s" % miss)
    ck("blocks_css_bcard", ".bcard" in css and ".advanced" in css,
       "style.css 缺业务块卡片 / 高级折叠区的样式")
    # 预览里业务块有自己的容器样式（选中描边要能套得上）。
    ck("blocks_css_pvbiz", ".pv-biz" in css,
       "style.css 缺 .pv-biz（预览里业务块没有样式就是一个裸 div）")


# ---------------- DOM：真渲染 ----------------

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


def dump(exe, url, profile):
    p = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--user-data-dir=" + profile,
         "--window-size=1500,1500", "--virtual-time-budget=9000",
         "--dump-dom", url],
        capture_output=True, timeout=180)
    return p.stdout.decode("utf-8", "replace")


def attrs_of(page, rid):
    m = re.search(r'<div id="%s"([^>]*)>' % re.escape(rid), page)
    if not m:
        return None
    return dict(re.findall(r'data-([a-z\-]+)="([^"]*)"', m.group(1)))


def dom_checks(doc):
    exe = find_browser()
    if not exe:
        ck("dom_browser_present", os.environ.get("UW_SKIP_DOM") == "1",
           "找不到 Edge/Chrome，业务块的渲染腿整条没跑（UW_SKIP_DOM=1 可显式承认）")
        return
    url = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    profile = tempfile.mkdtemp(prefix="uw_biz_")
    try:
        # --- 打开就是业务块控件架 ---
        empty = dump(exe, url + "#biz-empty", profile)
        ck("dom_empty_hook_ran", 'id="empty-hint"' in empty,
           "#biz-empty 没跑起来（连空画布提示都没有）")
        cards = re.findall(r'<div class="wcard bcard"[^>]*data-bcard-for="([^"]*)"', empty)
        want = [b["key"] for b in doc["blocks"]]
        ck("dom_shelf_has_every_block", cards == want,
           "控件架上的业务块应与 blocks.json 逐块同序：\n  实际 %s\n  应为 %s"
           % (cards, want))
        ck("dom_shelf_blocks_total", len(cards) == EXPECT_BLOCKS,
           "业务块卡片应为 %d 张，实际 %d" % (EXPECT_BLOCKS, len(cards)))
        ck("dom_shelf_buttons",
           len(re.findall(r'<button data-bkey="[^"]+"', empty)) == EXPECT_BLOCKS,
           "每张卡应有一个 data-bkey 插入按钮")
        # 每张卡都要有一句「这是什么」——这是换掉 API 词汇表的全部意义。
        nowhat = [k for k in want if 'data-bcard-for="%s"' % k not in empty]
        ck("dom_shelf_all_cards_present", not nowhat, "缺卡：%s" % nowhat)

        # 高级区在，但默认收起。
        det = re.search(r'<details[^>]*id="adv-primitives"[^>]*>', empty)
        ck("dom_adv_details_present", bool(det), "高级区（<details>）没渲染出来")
        ck("dom_adv_collapsed_by_default",
           bool(det) and "open" not in det.group(0),
           "高级区默认必须是收起的：%s" % (det.group(0) if det else "<missing>"))
        # 原语一块没少（折叠 ≠ 删除）。
        ck("dom_adv_primitives_kept",
           len(re.findall(r'<button data-wkey="[^"]+"', empty)) == 12,
           "高级区里应仍有 12 个 UILayout 原语按钮，实际 %d"
           % len(re.findall(r'<button data-wkey="[^"]+"', empty)))
        ck("dom_biz_blocks_not_in_canvas",
           'class="note pnode bnode' not in empty,
           "还没点任何块，画布上就不该有积木")

        # 业务块卡上的图示必须与 blocks.json 对得上（平行于原语那 5 条）。
        bdemo = {}
        for m in re.finditer(r'<div class="demo([^"]*)"([^>]*)>', empty):
            a = m.group(2)
            k = re.search(r'data-dwkey="([^"]*)"', a)
            if not k:
                continue
            bdemo[k.group(1)] = (re.search(r'data-dkind="([^"]*)"', a).group(1),
                                 m.end())
        bad_kind, bad_items, bad_grp = [], [], []
        for b in doc["blocks"]:
            got = bdemo.get(b["key"])
            if not got:
                bad_kind.append(b["key"])
                continue
            if got[0] != b["demo"]["kind"]:
                bad_kind.append("%s(%s!=%s)" % (b["key"], got[0], b["demo"]["kind"]))
        ck("dom_biz_demo_kinds", not bad_kind,
           "业务块卡上的图示形状与 blocks.json 不符：%s" % bad_kind[:4])
        for b in doc["blocks"]:
            # 切到下一张卡的起点为止。数多了就是把后面几张卡的方块算进来了。
            parts = empty.split('data-bcard-for="%s"' % b["key"])
            if len(parts) < 2:
                # 控件架上根本没有这张卡：下面那条断言会红，这里不能再抛。
                # 抛出去会把整个 main() 打断、汇总行打不出来——那正是
                # 「rc=0 / 红 0 条」那种假绿的来源。
                bad_items.append((b["key"], -1, demo_item_count(b["demo"])))
                continue
            seg = parts[1].split('data-bcard-for="')[0]
            # 最后一张卡后面就是高级区（12 张原语卡，各自也有图示），
            # 不在这里截断的话会把那 18 个小方块一起数进来。
            seg = seg.split('id="adv-primitives"')[0]
            # 条目数 = 顶层 items + 每组细节里的 items（双层盒里那层也算）。
            # 这一条从 Task 20 起改了口径：规格选项组多了一层盒子，
            # 只数顶层会把那 9 个选择按钮全漏掉，于是「里层根本没画出来」
            # 这种错照样绿。口径变了，判据没松——两边仍逐块比对确切个数。
            # Task 21 再加一处：「你说的话」那条消息是一个 .d-msgtext 而不是
            # .d-it（它不再套盒子），所以数方块时把它一并算进来，
            # 否则数据说 1 条、DOM 数出 0 条，会平白红一条。
            n = seg.count('class="d-it"') + seg.count('class="d-msgtext"')
            want = demo_item_count(b["demo"])
            if n != want:
                bad_items.append((b["key"], n, want))
            # 分组数同样逐块比：双层盒里层有几个盒必须是数据说的那个数。
            g = len(re.findall(r'class="d-group"', seg))
            ng = len((b["demo"].get("groups") or []))
            if g != ng:
                bad_grp.append((b["key"], g, ng))
        ck("dom_biz_demo_items", not bad_items,
           "业务块图示里的小方块数与数据对不上：%s" % bad_items[:4])
        ck("dom_biz_demo_groups", not bad_grp,
           "业务块图示里的内层盒子数与数据对不上：%s" % bad_grp[:4])

        # --- 插了 6 块之后的画布 ---
        rep_page = dump(exe, url + "#biz-report", profile)
        at = attrs_of(rep_page, "biz-report")
        ck("dom_report_ran", bool(at), "没拿到业务块读数报告：#biz-report 没跑起来")
        if at:
            ck("dom_biz_demo_blocks", at.get("blocks") == "6",
               "演示面板应是 6 块，实际 %s" % at.get("blocks"))
            ck("dom_biz_all_nodes_are_biz", at.get("biz-nodes") == at.get("blocks"),
               "画布上有 %s 块，其中业务块 %s 块——混进了别的东西"
               % (at.get("blocks"), at.get("biz-nodes")))
            # 「不可再嵌套」：不许有容器分组框，也不许有带 parent 的业务块。
            ck("dom_biz_no_nesting", at.get("nested") == "0" and at.get("pgroups") == "0",
               "业务块不该能嵌套：带父级的 %s 块、容器分组框 %s 个"
               % (at.get("nested"), at.get("pgroups")))
            # 「没有参数」：参数框、归属下拉、移入移出三样都不该在。
            ck("dom_biz_no_param_box", at.get("param-boxes") == "0",
               "业务块上出现了参数框 %s 个" % at.get("param-boxes"))
            ck("dom_biz_no_parent_select", at.get("parent-selects") == "0",
               "业务块上出现了归属下拉 %s 个" % at.get("parent-selects"))
            ck("dom_biz_no_move_buttons", at.get("move-btns") == "0",
               "业务块上出现了移入/移出按钮 %s 个" % at.get("move-btns"))
            # 「改文案 · 备注名 · 变体下拉」这三样必须在。
            ck("dom_biz_has_text_boxes", int(at.get("text-boxes", "0") or 0) >= 1,
               "展开后一块都没有改文案输入框")
            ck("dom_biz_has_note_boxes", int(at.get("id-boxes", "0") or 0) == 6,
               "每块都该有一个备注名输入框，实际 %s 个" % at.get("id-boxes"))
            ck("dom_biz_variant_select",
                 int(at.get("variant-selects", "0") or 0) >= 1,
               "状态提示条有四种样式，展开后必须有样式下拉，实际 %s 个"
               % at.get("variant-selects"))
            ck("dom_biz_preview_nodes", int(at.get("pv-biz", "0") or 0) == 6,
               "左边预览应画出 6 个业务块，实际 %s" % at.get("pv-biz"))
            # 拖动排序还留着（这是明确要保留的四件能力之一）。
            ck("dom_biz_drag_reorders",
               at.get("drag-changed") == "1" and at.get("drag-first-was-first") == "1",
               "拖动没换位（前后 uid 序：changed=%s first=%s）"
               % (at.get("drag-changed"), at.get("drag-first-was-first")))
            # 改文案真的落到导出的代码里，且**这一处**的旧文案少了一次。
            ck("dom_biz_text_edit_in_export", at.get("edited-in-py") == "1",
               "改了文案但导出里没有新文案（slot=%s）" % at.get("slot"))
            ck("dom_biz_old_text_replaced",
               int(at.get("old-count", "0") or 0) >= 1 and
               int(at.get("new-count", "-1") or -1) ==
               int(at.get("old-count", "0") or 0) - 1,
               "改了文案但旧文案在这一处没被换掉：改前 %s 次 / 改后 %s 次"
               % (at.get("old-count"), at.get("new-count")))

        # --- 导出必须能过 ast.parse ---
        exp_page = dump(exe, url + "#biz-export", profile)
        ea = attrs_of(exp_page, "biz-export")
        ck("dom_export_ran", bool(ea), "没拿到导出读数：#biz-export 没跑起来")
        if ea:
            src = _unescape(ea.get("py", ""))
            try:
                ast.parse(src)
                ck("dom_export_py_parses", True, "")
            except SyntaxError as exc:
                ck("dom_export_py_parses", False,
                   "导出的 ui.py 解析不过：%s（第 %s 行）\n%s"
                   % (exc.msg, exc.lineno, src.split("\n")[(exc.lineno or 1) - 1]))
            # 导出必须声明「未经验证」：草稿不是成品。
            ck("dom_export_declares_unverified", "未经验证" in src,
               "导出的 ui.py 没有声明「未经验证」")
            # 导出的必须是 ui.py 里那段原样的代码，不是重新翻译的。
            ck("dom_export_carries_real_code",
               "deepseek.submit_selection" in src and "get_current_action_text(run)" in src,
               "导出的代码里没有 ui.py 那两段真实调用（说明没原样带走）")
            ck("dom_export_has_notes",
               "未填元素 ID" not in src.split("def draw_")[0] and "工作台自动生成" in src,
               "导出的代码块没有「自动生成」的块头注释")
            ck("dom_export_todo_section", "落笔前必须人工处理的" in src,
               "导出缺文末的「必须人工处理」汇总")
            # 第 1 条（响应式图标）的导出侧：那段必须真的随导出走一段。
            # 少它一条，Blender 侧就没有「窄了只留图标」的可行写法。
            ck("dom_export_has_responsive_icons",
               "bpy.context.region.width" in src and "媒体查询" in src and
               "松手" in src and "_uw_wide" in src and
               'if _uw_wide else ""' in src,
               "导出的 ui.py 里没有那段响应式图标写法"
               "（应有 region.width / 媒体查询 / 松手 / _uw_wide / 窄时置空文字）")
            # 第 3 条（长消息折叠）的导出侧：折叠必须落在 layout.panel 上，
            # 并且 default_closed 真的跟着积木上的状态走。
            ck("dom_export_has_msg_fold",
               "layout.panel" in src and "default_closed" in src and
               "open_default=" in src,
               "导出的 ui.py 里没有那段长消息折叠写法"
               "（应有 layout.panel / default_closed / open_default=）")

        # --- 本轮五条意见在浏览器里的真形状（#biz-icons）---
        ip = dump(exe, url + "#biz-icons", profile)
        it = attrs_of(ip, "biz-icons")
        ck("dom_icons_report_ran", bool(it),
           "没拿到响应式图标的读数：#biz-icons 没跑起来")
        if it:
            # 第 4 条：默认（宽）面板下图标在，压到 280px 之后全部消失。
            # 两读都取自 getComputedStyle：宽面板下 shown 必须等于总数，
            # 窄面板下必须一个不剩，且两次量到的元素个数是同一批。
            ck("dom_icons_wide_icon_and_text",
               int(it.get("wide-ico-shown", "0")) == int(it.get("wide-ico-total", "0"))
               and int(it.get("wide-ico-total", "0")) > 0 and
               int(it.get("wide-text-shown", "0")) == int(it.get("wide-text-total", "0"))
               and int(it.get("wide-text-total", "0")) > 0,
               "默认（宽）面板下应是「图标 + 文字」：图标 %s/%s、文字 %s/%s"
               % (it.get("wide-ico-shown"), it.get("wide-ico-total"),
                  it.get("wide-text-shown"), it.get("wide-text-total")))
            ck("dom_icons_narrow_icon_only",
               it.get("narrow-text-shown") == "0" and
               int(it.get("narrow-ico-total", "0")) > 0 and
               it.get("narrow-ico-shown") == it.get("narrow-ico-total"),
               "压到 280px 后应只剩图标：图标 %s/%s、文字还有 %s/%s 个"
               % (it.get("narrow-ico-shown"), it.get("narrow-ico-total"),
                  it.get("narrow-text-shown"), it.get("narrow-text-total")))
            ck("dom_icons_same_elements_both_ways",
               it.get("narrow-ico-total") == it.get("wide-ico-total") and
               it.get("narrow-text-total") == it.get("wide-text-total"),
               "两次读的图标数 %s/%s、文字数 %s/%s 对不上"
               % (it.get("narrow-ico-total"), it.get("wide-ico-total"),
                  it.get("narrow-text-total"), it.get("wide-text-total")))
            ck("dom_icons_narrow_really_narrower",
               int(it.get("narrow-panel", "9999")) <
               int(it.get("wide-panel", "0")) and
               int(it.get("narrow-panel", "9999")) < 360,
               "窄面板那次量到的宽度不是窄的：宽 %s / 窄 %s"
               % (it.get("wide-panel"), it.get("narrow-panel")))
            # 「一共有几个图标」这条单独钉死两个具体数：页签条 3 个、快捷
            # 指令 4 个。只比 shown == total 的话，一处都不画（total=0、
            # shown=0）也会照样成立——M17 那个变异就是这么钻过去的。
            pills_ico = (it.get("pills") or "").split(":")
            ck("dom_icons_rendered_per_card",
               len(pills_ico) >= 4 and pills_ico[3] == "4",
               "快捷指令那张卡应有 4 个图标角标，读到 %s"
               % (pills_ico[3] if len(pills_ico) > 3 else "?",))
            qs_ico = (it.get("qs") or "").split(":")
            ck("dom_icons_in_question_groups",
               len(qs_ico) >= 7 and qs_ico[6] == "12",
               "规格那张卡应有 3 组 × (1 标题 + 3 按钮) = 12 个图标角标，"
               "读到 %s" % (qs_ico[6] if len(qs_ico) > 6 else "?",))
            # 第 1 条：页签上不许再有「AI」。
            ck("dom_tabs_dropped_ai", it.get("tabs") == "对话|详情|设置",
               "页签条卡片上读到的页签是：%r" % it.get("tabs"))
            # 第 3 条：四个方块同一行（distinct top == 1）。
            pills = (it.get("pills") or "").split(":")
            ck("dom_pills_single_row",
               len(pills) >= 2 and pills[0] == "4" and pills[1] == "1",
               "快捷指令应是四个排在同一行，读到 %s 个方块 / %s 行"
               % (pills[0] if pills else "?", pills[1] if len(pills) > 1 else "?"))
            # 第 2 + 第 5 条：外层一个盒（kind=box，引子是这个盒的**直接**
            # 孩子），里面三个细节各自成盒、每个盒里三个按钮——而且那几个
            # 按钮真的装在这个盒里（same），不是各画各的。
            qs = (it.get("qs") or "").split(":")
            ck("dom_questions_intro_in_same_box",
               len(qs) >= 6 and qs[0] == "box" and qs[1] == "需要你定一下"
               and qs[5] == "same",
               "规格那块外层应是一个 box，引子是它的直接孩子，选择按钮也装在"
               "同一个盒里，读到 %s" % (it.get("qs"),))
            ck("dom_questions_double_box",
               len(qs) >= 4 and qs[2] == "3" and qs[3] == "3/3/3",
               "规格那块里层应有三个盒、每个盒三个按钮，读到 %s"
               % (it.get("qs"),))
            ck("dom_questions_titles_are_details",
               len(qs) >= 5 and qs[4].startswith("细节 1：") and
               "细节 3：" in qs[4],
               "里层三个盒的标题不是「细节 N：…」，读到 %r"
               % (qs[4] if len(qs) > 4 else "",))

            # 第 2 条（一个盒，到此为止）：外层气泡盒有边框，里面那段文字
            # 没有边框，也没有内层分组盒。看的是浏览器算出来的 border 宽度，
            # 不是 DOM 层级——层级对了但画了第二个框，一样是两重盒。
            sh = (it.get("msg") or "").split(":")
            ck("dom_bubble_user_one_box",
               len(sh) >= 4 and sh[0] == "msgtxt" and sh[1] == "boxed" and
               sh[2] == "plain" and sh[3] == "0",
               "你说的话应是一个带边框的盒 + 一段没有边框的文字，读到 %r"
               % (it.get("msg"),))

            # 第 4 条（输入框独占一行）：.d-textbox 得是 .d-crow 的**兄弟**
            # 而不是孩子，宽度摊满，而且真的排在那一行的下面。
            cp = (it.get("composer") or "").split(":")
            ck("dom_composer_textbox_own_row",
               len(cp) >= 6 and cp[0] == "composer" and cp[1] == "2" and
               cp[2] == "1" and cp[3] == "sibling" and cp[4] == "ownrow",
               "输入框应独占一行（与标签那行平级、摊满宽度、在它下面），读到 %r"
               % (it.get("composer"),))

        # --- 长消息的折叠 / 展开两态（#biz-msg）---
        mp = dump(exe, url + "#biz-msg", profile)
        mt = attrs_of(mp, "biz-msg")
        ck("dom_msg_report_ran", bool(mt),
           "没拿到长消息折叠的读数：#biz-msg 没跑起来")
        if mt:
            ck("dom_msg_folded_is_summary",
               mt.get("folded-trunc") == "1" and mt.get("folded-dots") == "1"
               and len(mt.get("folded-text") or "") <= 21,
               "折叠态应只显示前 20 字 + 省略号，读到 %r"
               % mt.get("folded-text"))
            # 「这是一条长消息」要看得见：省略号之外还得有一个展开指示，
            # 而且不许只靠一个光看不知道什么意思的小三角。
            ck("dom_msg_folded_shows_toggle",
               mt.get("folded-toggle") and "展开" in mt.get("folded-toggle", ""),
               "折叠态没有看得见的展开指示：%r" % mt.get("folded-toggle"))
            ck("dom_msg_expanded_shows_all",
               mt.get("open-trunc") == "0" and mt.get("open-dots") == "0" and
               len(mt.get("open-text") or "") > 20 and
               "收起" in mt.get("open-toggle", ""),
               "展开态应显示全文并换成收起指示，读到 %r / %r"
               % (mt.get("open-text"), mt.get("open-toggle")))
            # 状态存在积木上，导出时不许丢：折着导 → open_default=False，
            # 展开着导 → open_default=True。两条都在同一次运行里量。
            ck("dom_msg_state_reaches_export",
               mt.get("py-closed") == "1" and mt.get("py-open") == "1"
               and mt.get("py-has-panel") == "1" and
               mt.get("py-has-default-closed") == "1",
               "展开/收起的状态没跟着导出走（折着 %s / 展开 %s / panel %s / "
               "default_closed %s）" % (mt.get("py-closed"), mt.get("py-open"),
                                       mt.get("py-has-panel"),
                                       mt.get("py-has-default-closed")))

        # --- 16 块全点一遍 ---
        allp = dump(exe, url + "#biz-all", profile)
        ck("dom_all_status_line", "BIZ all 块 16" in allp,
               "点满 16 块后的状态条不对（应报 BIZ all 块 16）")
        nodes = re.findall(r'<div class="note pnode bnode"[^>]*data-bkey="([^"]*)"', allp)
        ck("dom_all_every_block_insertable", len(nodes) == EXPECT_BLOCKS,
               "16 块应当全都插得进去，实际 %d 块：%s" % (len(nodes), nodes))
        ck("dom_all_advanced_still_works",
           len(re.findall(r'<button data-wkey="[^"]+"', allp)) == 12,
           "高级区的 12 个原语按钮在插完业务块之后不见了")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _unescape(s):
    """把 dataset 属性里的 HTML 转义还原回来。"""
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'")
             .replace("&amp;", "&"))


def main():
    bp = os.path.join(WB, "blocks.json")
    ck("blocks_file_exists", os.path.exists(bp), "缺 ui_workbench/blocks.json")
    if not os.path.exists(bp):
        print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
        sys.exit(1)

    raw = open(bp, "rb").read()
    ck("blocks_nul", b"\x00" not in raw, "含 NUL 字节，疑似字节级写坏")
    try:
        txt = raw.decode("utf-8")
        ck("blocks_utf8", True)
    except UnicodeDecodeError as exc:
        ck("blocks_utf8", False, "不是合法 UTF-8：%s" % exc)
        txt = ""
    ck("blocks_no_replacement_char", "�" not in txt, "含 U+FFFD 替换字符")
    doc = json.loads(txt)

    # 生成器与落盘产物必须一致：改了 build_blocks.py 忘了重跑，测试要红。
    sys.path.insert(0, DEV)
    import build_blocks as bb
    fresh = bb.build()
    ck("blocks_match_generator", fresh == doc,
       "blocks.json 与 build_blocks.build() 输出不一致，需要重跑 dev/build_blocks.py")

    dj = os.path.join(WB, "data", "data.js")
    ck("data_js_exists", os.path.exists(dj), "缺 data/data.js")
    if os.path.exists(dj):
        m = re.search(r"window\.UW_DATA\s*=\s*(\{.*\});?\s*$", read(dj), re.S)
        payload = json.loads(m.group(1)) if m else None
        ck("data_js_blocks_key", payload is not None and "blocks" in payload,
           "data.js 里没有 blocks 键，重跑 python dev\\build_data_js.py")
        if payload is not None and "blocks" in payload:
            ck("data_js_blocks_same", payload["blocks"] == doc,
               "data.js 里的 blocks 与 blocks.json 不一致")

    # 每一段都单独兜住异常：任何一段抛出来，剩下的断言就全蒸发了，
    # 而汇总行也跟着打不出来——rc 仍是 0，那就是全局约束里禁掉的假绿。
    # 兜住之后记一条失败，异常信息原样带进断言名，让人看得见是哪段炸了。
    for label, fn in (("data", lambda: data_checks(doc)),
                      ("grounding", lambda: grounding_checks(doc)),
                      ("slots", lambda: slot_checks(doc)),
                      ("app_static", static_app_checks),
                      ("dom", lambda: dom_checks(doc))):
        try:
            fn()
        except Exception as exc:  # 这里就是要拦住一切
            import traceback
            ck("%s_section_completed" % label, False,
               "%s 段抛异常，后面的断言没跑完：%s\n%s"
               % (label, exc, traceback.format_exc()[-600:]))

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
