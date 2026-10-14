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
OUT = os.path.join(ROOT, "ui_workbench", "vocabulary.json")

PROPS_SCOPE = ("allowed_props 是精选子集，不是 UILayout 的全量参数表："
               "只收录本工作台会用到的调用形式，清单外的参数会被按"
               "「自造/拼错」拦下")

# (key, label, uiloayout, allowed_props, blocked_props, note, constraint_key)
# constraint_key 为 None 表示这条控件是通用 UILayout，constraints.json 里
# 没有单列它的判定；有值则必须指向一条 native_ok=true 的判定。
WIDGETS = [
    ("row", "横排", "layout.row(align=True)",
     ["align", "heading", "heading_ctxt"], [],
     "当前代码用量 0，成本最低的层次工具", None),
    ("column", "竖排", "layout.column(align=True)",
     ["align", "heading", "heading_ctxt"], [], "", None),
    ("box", "内盒", "layout.box()", ["alert"], [],
     "alert 是全 UI 唯一的红，只留给 FAILED", None),
    ("split", "左右分栏", "layout.split(factor=0.3)",
     ["factor", "align"], [],
     "返回单个 layout，不是二元组", "two_col_split"),
    ("grid_flow", "网格按钮", "layout.grid_flow(columns=2, even_columns=True)",
     ["columns", "even_columns", "even_rows", "row_major"], [],
     "当前已在设置页用于模型切换", "grid_flow"),
    ("panel", "可折叠子面板", "layout.panel(idname, default_closed)",
     ["idname", "default_closed", "layout_header", "layout_body"], [],
     "消化长度的唯一手段，侧栏滚不了", "collapsible_panel"),
    ("label", "文字", "layout.label(text=..., icon=...)",
     ["text", "icon"], ["size", "font", "color"],
     "没有 size/color/font 参数；层次靠 icon 和 scale_y", None),
    ("operator", "按钮", "layout.operator(id, text=..., icon=...)",
     ["id", "text", "icon", "depress", "emboss"], ["color"],
     "emboss='NONE' 可去掉高光渐变", "flat_button"),
    ("prop", "属性行", "layout.prop(data, prop, text=...)",
     ["prop", "text", "icon", "expand", "slider", "placeholder"], ["color"],
     "配 use_property_split 得到原生两列", "property_split"),
    ("textbox", "多行输入", "layout.textbox(data, 'prompt', initial_visible_lines=3)",
     ["prop", "text", "placeholder", "initial_visible_lines"], [],
     "中文 IME 只能靠原生 textbox，自绘拿不到拼音组合态", None),
    ("separator", "分隔线", "layout.separator()", [], [], "", None),
    ("scale_y", "留白撑高", "layout.scale_y = 1.4", ["scale_y"], [],
     "字号不可调，层次只能靠撑高和缩进", None),
]


class VocabularyError(Exception):
    """词汇表与 constraints.json 打架了。停下来，不要带着矛盾继续生成。"""


def build(constraints):
    reg = {e["key"]: e for e in constraints["entries"]}

    widgets = []
    for key, label, call, allowed, blocked, note, ckey in WIDGETS:
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