# -*- coding: utf-8 -*-
"""从 constraints.json 生成受限词汇表。

原则：只有 native_ok=true 的能力才能进词汇表；每条 native_ok=false 的
能力都要产出一条 rejected 项，带着降级方案，提案视图据此拦截。

这两条原则是**被强制**的，不是注释里的许诺：
  * 每个 widget 用 constraint_key 声明它实现的是 constraints.json 里哪一条
    native_ok=true 能力；build() 会拿 reg 去核对，那条一旦被翻成 false
    就直接抛错停下来，而不是继续悄悄提供它。
  * 每条 native_ok=true 但没有任何 widget 映射的能力，落到 unmapped_ok 里，
    提案视图会单列一行「可做但词汇表尚未收录」。漏掉的能力不许无声消失
    （progress_bar 就是这么被逼出来的）。

注意 allowed_props 是**精选子集**，不是 UILayout 的全量参数表：它只收录
本工作台实际会用到的调用形式。清单外的参数一律按「自造/拼错」拦掉，所以
它收窄得比真实 API 保守——这是有意的，但别把它当成「UILayout 只有这些参数」。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "ui_workbench", "constraints.json")
API = os.path.join(ROOT, "ui_workbench", "native_api.json")
OUT = os.path.join(ROOT, "ui_workbench", "vocabulary.json")


def load_icon_names():
    """Blender 实测能用的图标名，从 native_api.json 的枚举项里抄。

    抄而不是手写：手写名册必然会跟真实枚举漂，而图标名写错在 Blender 里是
    直接抛异常的一类错。native_api.json 里这份枚举就是探针抓回来的 bl_icon.items
    （1033 个，icons.count 与之相符），这份文件就是名册的证据。
    """
    with open(API, encoding="utf-8") as fh:
        api = json.load(fh)
    items = api["panels"]["properties"]["bl_icon"]["items"]
    names = [str(x) for x in items]
    declared = api.get("icons", {}).get("count")
    if declared is not None and declared != len(names):
        raise VocabularyError(
            "native_api.json 自报 icons.count=%d，实际枚举 %d 个，名册不可信"
            % (declared, len(names)))
    return names

PROPS_SCOPE = ("allowed_props 是精选子集，不是 UILayout 的全量参数表："
               "只收录本工作台会用到的调用形式，清单外的参数会被按"
               "「自造/拼错」拦下")

# 「对应插件元素 ID」到底是什么。用户只看到一个 (可选) 占位符，根本不知道
# 填什么，所以在这里就把三件事讲清楚：它是什么、怎么命名、能不能留空。
ELEMENT_ID_HELP = {
    "title": "「对应插件元素 ID」是什么",
    "what": "它是这块积木在 blender_deepseek_agent/ui.py 里的稳定标记，"
            "用来把你的标注挂回代码里的那一行。",
    "naming": "命名规则：chat.<区块> 或 chat.<区块>.<控件>，全小写、下划线分隔。",
    "optional": "可以留空——留空只是没法单独标注这一块，不影响拼装。",
    "examples": ["chat.composer", "chat.send_btn"],
}

# 一键插入的示例面板。放在数据里而不是写死成 JS 字面量：重跑本脚本时它不会丢，
# 测试也能逐条核对里面的参数与元素 ID。
# element_id 一律取自已提交的 7 份布局树（ui_workbench/data/layout/*.json）；
# 两条留空是有意的——正好演示「元素 ID 可以不填」。
# content 是这块里写什么字：左边预览只认它，缺了这一栏，预览就只是一排空壳。
# 容器类控件没有 content：它们只分组，不写字。
EXAMPLE_PANEL = {
    "title": "AI 对话",
    "caption": "整根竖排把它们从上到下串起来，横排把同一组里的控件并排放。",
    "blocks": [
        {"wkey": "row", "params": "align", "element_id": "chat.tabbar",
         "note": "三个页签并排：AI 对话 / 详情 / 设置",
         "content": {"heading": "AI 对话"}},
        {"wkey": "column", "params": "align", "element_id": "chat.stream",
         "note": "整根竖排：下面每一块都落在它里面，从上到下",
         "content": {"heading": "对话记录"}},
        {"wkey": "box", "params": "", "element_id": "",
         "note": "消息流里的一条消息（元素 ID 可以留空）",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "状态行：正在改你的场景 · 第 2 步",
         "content": {"text": "正在改你的场景 · 第 2 步", "icon": "TIME"}},
        {"wkey": "column", "params": "align", "element_id": "chat.options",
         "note": "规格选项容器：一次有几项要选，就用竖排把每项串起来",
         "content": {"heading": "需要你定一下"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "三个并排的选项按钮：修改尺寸 / 更换材质 / 平滑着色",
         "content": {"heading": "修改尺寸 / 更换材质 / 平滑着色"}},
        {"wkey": "textbox", "params": "prop, initial_visible_lines",
         "element_id": "chat.composer", "note": "指令输入框，可写多行",
         "content": {"placeholder": "输入建模指令…", "lines": 3}},
        {"wkey": "row", "params": "align", "element_id": "chat.action_row",
         "note": "三个并排的操作按钮：发送指令 / 新建任务 / 清空记录",
         "content": {"heading": "操作"}},
    ],
}

# 新积木的起手内容。空按钮定不了形、也看不出这是个什么控件，所以每个有内容
# 的控件一放上来就写一句能看懂的话。容器不给起手内容（空的横排竖排本来就该
# 是空的，写死了反而不像刚放上去的）。row / column 的 heading 之所以算内容
# 而不是参数：参数框按白名单只收参数名，收不了取值，没有它就没法做页签条。
STARTER_CONTENT = {
    "label": {"text": "状态行文字", "icon": "INFO"},
    "operator": {"text": "发送指令", "icon": "PLAY"},
    "prop": {"label": "API Key", "value": "（未填）"},
    "textbox": {"placeholder": "在这里输入建模指令…", "lines": 3},
}

# (key, label, uiloayout, allowed_props, blocked_props, note, constraint_key,
#  demo, props_example, props_hint)
# constraint_key 为 None 表示这条控件是通用 UILayout，constraints.json 里
# 没有单列它的判定；有值则必须指向一条 native_ok=true 的判定。
#
# demo —— 声明式的迷你图示：只描述「长什么样」，由 app.js 画成小方块。
#         写成 HTML 字符串的话，重跑本脚本就会和控件定义脱节，而图示恰恰是
#         最容易随控件改动而失真的那部分。
# props_example —— 能直接粘进参数框、逐个合法的示例（只写参数名）。
#         参数框按逗号切词后逐个查白名单，带 '=' 或带引号会被当场拦下；
#         「示例给错了比不给更糟」，这一串必须能原样粘。
# props_hint —— 带取值的真实调用形式（给人看懂该填什么值），
#         逐条对着 native_api.json 的实测签名核过。
WIDGETS = [
    ("row", "横排", "layout.row(align=True)",
     ["align", "heading", "heading_ctxt"], [],
     "一行里并排放多个控件。横排是「并排」，竖排是「从上到下」——"
     "整个面板本身就是一根竖排。同一组控件要并排放，就用横排包住它们。", None,
     {"kind": "row", "items": ["发送指令", "停止"]},
     "align, heading",
     "layout.row(align=True, heading=\"对话\")"),
    ("column", "竖排", "layout.column(align=True)",
     ["align", "heading", "heading_ctxt"], [],
     "从上到下依次堆叠多个控件。面板从上到下的顺序，就是竖排里从上到下的顺序；"
     "整根竖排负责把页面串起来。", None,
     {"kind": "col", "items": ["消息1", "消息2", "消息3"]},
     "align, heading",
     "layout.column(align=True)"),
    ("box", "内盒", "layout.box()", ["alert"], [],
     "带边框的一块内容，把一条消息或一个提示圈起来。"
     "alert 是全 UI 唯一的红，只留给 FAILED。", None,
     {"kind": "box", "items": ["一个带边框的块"]},
     "alert",
     "box.alert = True"),
    ("split", "左右分栏", "layout.split(factor=0.3)",
     ["factor", "align"], [],
     "左右分成两栏。factor 是左栏宽度占比，0.3 就是左三右七。"
     "返回单个 layout，不是二元组。", "two_col_split",
     {"kind": "split", "factor": 0.3, "items": ["窄", "宽"]},
     "factor",
     "layout.split(factor=0.3)"),
    ("grid_flow", "网格按钮", "layout.grid_flow(columns=2, even_columns=True)",
     ["columns", "even_columns", "even_rows", "row_major"], [],
     "按钮排成网格：columns 定几列，even_columns 让每列等宽。"
     "比横排省高度，一堆同类按钮时用它。", "grid_flow",
     {"kind": "grid", "cols": 2, "items": ["改尺寸", "换材质", "加倒角", "平滑"]},
     "columns, even_columns",
     "layout.grid_flow(columns=2, even_columns=True)"),
    ("panel", "可折叠子面板", "layout.panel(idname, default_closed)",
     ["idname", "default_closed", "layout_header", "layout_body"], [],
     "一组能收起来的控件，带原生折叠箭头。侧栏滚不了，长度只能靠它消化。",
     "collapsible_panel",
     {"kind": "panel", "items": ["可折叠的一组"]},
     "idname, default_closed",
     "layout.panel(idname=\"chat.specs\", default_closed=True)"),
    ("label", "文字", "layout.label(text=..., icon=...)",
     ["text", "icon"], ["size", "font", "color"],
     "一行说明文字。字号不可调，层次只能靠 icon 和撑高做出来。", None,
     {"kind": "label", "items": ["一行文字"]},
     "text, icon",
     "layout.label(text=\"已处理完 3 项\", icon='CHECKMARK')"),
    ("operator", "按钮", "layout.operator(id, text=..., icon=...)",
     ["id", "text", "icon", "depress", "emboss"], ["color"],
     "点一下执行一条指令的按钮。id 填算子名；"
     "emboss='NONE' 可去掉高光渐变。", "flat_button",
     {"kind": "btn", "items": ["发送指令"]},
     "id, text, icon",
     "layout.operator(\"deepseek.run_prompt\", text=\"发送指令\", icon='PLAY')"),
    ("prop", "属性行", "layout.prop(data, prop, text=...)",
     ["prop", "text", "icon", "expand", "slider", "placeholder"], ["color"],
     "绑到插件设置项上的一行：左边文字，右边输入框。"
     "配 use_property_split 得到原生两列。", "property_split",
     {"kind": "prop", "items": ["API Key", "▾"]},
     "prop, text",
     "layout.prop(p, \"api_key\", text=\"API Key\")"),
    ("textbox", "多行输入", "layout.textbox(data, 'prompt', initial_visible_lines=3)",
     ["prop", "text", "placeholder", "initial_visible_lines"], [],
     "可以写多行的输入区。中文输入法只能靠原生 textbox，自绘拿不到拼音组合态。",
     None,
     {"kind": "box", "items": ["多行输入区"]},
     "prop, initial_visible_lines",
     "layout.textbox(state, \"prompt\", initial_visible_lines=3)"),
    ("separator", "分隔线", "layout.separator()", [], [],
     "一条横线，把上下两组控件分开。不带任何参数。", None,
     {"kind": "rule"},
     "",
     "layout.separator()"),
    ("scale_y", "留白撑高", "layout.scale_y = 1.4", ["scale_y"], [],
     "空出一条竖向空隙，把内容上下分开。字号不可调，层次只能靠撑高和缩进。", None,
     {"kind": "gap"},
     "scale_y",
     "row.scale_y = 1.3"),
]


class VocabularyError(Exception):
    """词汇表与 constraints.json 打架了。停下来，不要带着矛盾继续生成。"""


def build(constraints):
    reg = {e["key"]: e for e in constraints["entries"]}

    widgets = []
    for key, label, call, allowed, blocked, note, ckey, demo, ex, hint in WIDGETS:
        # 让 docstring 里那句「只有 native_ok=true 的能力才能进词汇表」成立：
        # 声称自己实现了某条判定的控件，那条判定必须真的 native_ok=true。
        # 翻脸了就抛错，让人来定——静默丢掉一个控件比停下来更坏。
        if ckey is not None:
            if ckey not in reg:
                raise VocabularyError(
                    "控件 %s 声称实现 constraints 里不存在的判定 %s" % (key, ckey))
            if not reg[ckey]["native_ok"]:
                raise VocabularyError(
                    "控件 %s 依赖的判定 %s 已是 native_ok=false："
                    "%s。要么删掉这个控件，要么把它移进 rejected 并给出降级方案"
                    % (key, ckey, reg[ckey].get("blocker", "")))
        widgets.append({
            "key": key, "label": label, "uiloayout": call,
            "allowed_props": allowed, "blocked_props": blocked, "note": note,
            "constraint_key": ckey,
            "demo": demo, "props_example": ex, "props_hint": hint,
        })

    rejected = []
    for e in constraints["entries"]:
        if e["native_ok"]:
            continue
        rejected.append({
            "key": e["key"], "label": e["title"],
            "blocker": e["blocker"], "fallback": e["fallback"],
        })

    # 可做、但词汇表还没收录的能力。单列出来，提案视图里给它一行说明，
    # 而不是让它在控件栏和降级栏里同时消失。
    mapped = set(w["constraint_key"] for w in widgets if w["constraint_key"])
    unmapped = [{"key": e["key"], "label": e["title"], "uiloayout": e["uiloayout"],
                 "evidence": e["evidence"]}
                for e in constraints["entries"]
                if e["native_ok"] and e["key"] not in mapped]

    return {
        "generated_for": constraints["generated_for"],
        "props_scope": PROPS_SCOPE,
        "widgets": widgets,
        "rejected": rejected,
        "unmapped_ok": unmapped,
        "element_id_help": ELEMENT_ID_HELP,
        "example_panel": EXAMPLE_PANEL,
        "starter_content": STARTER_CONTENT,
        "icons": load_icon_names(),
    }


def main():
    with open(SRC, encoding="utf-8") as fh:
        constraints = json.load(fh)
    try:
        vocab = build(constraints)
    except VocabularyError as exc:
        print("VOCAB_FAIL %s" % exc)
        return 1
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(vocab, fh, ensure_ascii=False, indent=2)
    print("VOCAB_OK widgets=%d rejected=%d unmapped_ok=%d"
          % (len(vocab["widgets"]), len(vocab["rejected"]), len(vocab["unmapped_ok"])))
    for r in vocab["rejected"]:
        print("REJECT %-18s -> %s" % (r["key"], r["fallback"]))
    for u in vocab["unmapped_ok"]:
        print("UNMAPPED_OK %-14s %s -> 词汇表尚未收录（落笔时拿不到）" % (u["key"], u["uiloayout"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())