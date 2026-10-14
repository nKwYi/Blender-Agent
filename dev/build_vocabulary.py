# -*- coding: utf-8 -*-
"""从 constraints.json 生成受限词汇表。

原则：只有 native_ok=true 的能力才能进词汇表；每条 native_ok=false 的
能力都要产出一条 rejected 项，带着降级方案，提案视图据此拦截。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "ui_workbench", "constraints.json")
OUT = os.path.join(ROOT, "ui_workbench", "vocabulary.json")

WIDGETS = [
    ("row", "横排", "layout.row(align=True)", ["align"], [],
     "当前代码用量 0，成本最低的层次工具"),
    ("column", "竖排", "layout.column(align=True)", ["align"], [],
     ""),
    ("box", "内盒", "layout.box()", ["alert"], [],
     "alert 是全 UI 唯一的红，只留给 FAILED"),
    ("split", "左右分栏", "layout.split(factor=0.3)", ["factor"], [],
     "返回单个 layout，不是二元组"),
    ("grid_flow", "网格按钮", "layout.grid_flow(columns=2, even_columns=True)",
     ["columns", "even_columns", "row_major"], [], "当前已在设置页用于模型切换"),
    ("panel", "可折叠子面板", "layout.panel(idname, default_closed)",
     ["idname", "default_closed"], [],
     "消化长度的唯一手段，侧栏滚不了"),
    ("label", "文字", "layout.label(text=..., icon=...)",
     ["text", "icon"], ["size", "font", "color"],
     "没有 size/color/font 参数；层次靠 icon 和 scale_y"),
    ("operator", "按钮", "layout.operator(id, text=..., icon=...)",
     ["id", "text", "icon", "depress", "emboss"], ["color"],
     "emboss='NONE' 可去掉高光渐变"),
    ("prop", "属性行", "layout.prop(data, prop, text=...)",
     ["prop", "text"], ["color"], "配 use_property_split 得到原生两列"),
    ("textbox", "多行输入", "layout.textbox(data, 'prompt', initial_visible_lines=3)",
     ["prop", "text", "placeholder", "initial_visible_lines"], [],
     "中文 IME 只能靠原生 textbox，自绘拿不到拼音组合态"),
    ("separator", "分隔线", "layout.separator()", [], [], ""),
    ("scale_y", "留白撑高", "layout.scale_y = 1.4", ["scale_y"], [],
     "字号不可调，层次只能靠撑高和缩进"),
]


def build(constraints):
    reg = {e["key"]: e for e in constraints["entries"]}
    widgets = []
    for key, label, call, allowed, blocked, note in WIDGETS:
        widgets.append({
            "key": key, "label": label, "uiloayout": call,
            "allowed_props": allowed, "blocked_props": blocked, "note": note,
        })
    rejected = []
    for e in constraints["entries"]:
        if e["native_ok"]:
            continue
        rejected.append({
            "key": e["key"], "label": e["title"],
            "blocker": e["blocker"], "fallback": e["fallback"],
        })
    return {
        "generated_for": constraints["generated_for"],
        "widgets": widgets,
        "rejected": rejected,
    }


def main():
    with open(SRC, encoding="utf-8") as fh:
        constraints = json.load(fh)
    vocab = build(constraints)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(vocab, fh, ensure_ascii=False, indent=2)
    print("VOCAB_OK widgets=%d rejected=%d" % (len(vocab["widgets"]), len(vocab["rejected"])))
    for r in vocab["rejected"]:
        print("REJECT %-18s -> %s" % (r["key"], r["fallback"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())