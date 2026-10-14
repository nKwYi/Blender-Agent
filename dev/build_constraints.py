# -*- coding: utf-8 -*-
"""从实测的 native_api.json 生成可行性约束注册表。

判据只有一个来源：native_api.json。任何一条 native_ok 的判定都必须能在
该文件里找到对应证据，禁止凭印象填写。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "ui_workbench", "native_api.json")
OUT = os.path.join(ROOT, "ui_workbench", "constraints.json")


def load_api():
    with open(API, encoding="utf-8") as fh:
        return json.load(fh)


def _has_call(api, name):
    return name in api["ui"]["functions"]


def _has_prop(api, name):
    return name in api["ui"]["properties"]


# 每条 entry 的 verdict 在这里计算，不允许硬编码 True/False。
def _entry(key, title, api, call=None, prop=None, blocker="", fallback="",
           evidence="", negated=None, denied=None):
    if negated is not None:
        # negatives[name] 为 True 表示「该能力实测存在」；本注册表三项实测均为
        # False（无任意 RGB / 无字号 / 无 hover 回调），故 ok 直接取该值。
        ok = bool(api["ui"]["negatives"].get(negated, False))
        ev = "ui.negatives.%s=%s" % (
            negated, json.dumps(api["ui"]["negatives"].get(negated)))
    elif call is not None:
        ok = _has_call(api, call)
        ev = "ui.functions.%s=%s" % (call, ok)
    elif denied is not None:
        # 该能力没有正向 API 入口：只要任一候选符号实测存在即视为可用。
        found = [s for s in denied
                 if s in api["ui"]["functions"] or s in api["ui"]["properties"]]
        ok = bool(found)
        ev = "ui 符号均不存在: %s" % " ".join(denied) if not ok else \
             "ui 符号存在: %s" % " ".join(found)
    else:
        ok = _has_prop(api, prop)
        ev = "ui.properties.%s=%s" % (prop, ok)

    item = {"key": key, "title": title, "native_ok": bool(ok), "evidence": ev}
    if ok and call:
        item["uiloayout"] = "layout.%s()" % call
    elif ok and prop:
        # 属性型能力同样要给出可执行的 uilayout 入口，供提案视图直接引用。
        item["uiloayout"] = "layout.%s" % prop
    if not ok:
        item["blocker"] = blocker
        item["fallback"] = fallback
    return item


def build(api):
    entries = [
        _entry("hover", "鼠标悬停态", api, negated="hover_hook",
               blocker="UILayout 无任何 hover 回调；Blender 内部有 _inner_sel 配色但插件调不到",
               fallback="改用 enabled / active 二态表达状态；把 hover 语义重写为「点击后进入」"),
        _entry("custom_rgb", "任意 RGB 颜色", api, negated="arbitrary_rgb",
               blocker="UILayout 无 color 属性，只能置 layout.alert=True 触发主题红",
               fallback="只用 box.alert 表达失败；成功/警告改用图标与文案区分，不依赖颜色"),
        _entry("font_size", "自定义字号与字重", api, negated="font_size",
               blocker="label() 只有 text / text_ctxt / translate / icon / icon_value 五个参数",
               fallback="用 layout.scale_y 配合空 label 撑出层次；标题感靠 icon 与分隔线建立"),
        _entry("box_shadow", "卡片阴影", api,
               denied=("shadow", "shadow_fac", "drop_shadow"),
               blocker="面板无阴影 API，theme 只有 menu_shadow_fac 作用于菜单",
               fallback="用底色明度差分层：面板 #3d3d3d 对内盒 #1d1d1d"),
        _entry("real_scroll", "侧栏真实滚动", api,
               denied=("scroll", "scrollbar", "scroll_to"),
               blocker="侧栏滚轮实测不滚动（UI打磨执行书 v0.2.1 实测：200 行面板滚轮零变化）",
               fallback="用 layout.panel() 折叠消化长度；对话记录只保留最近 N 条，其余折叠或分页"),
        _entry("anim_transition", "展开/收起动效", api,
               denied=("animation", "animate", "interpolation"),
               blocker="插件无动画 API",
               fallback="改用 layout.panel() 的原生折叠箭头，动效由 Blender 内置提供"),
        _entry("collapsible_panel", "可折叠子面板", api, call="panel",
               fallback=""),
        _entry("property_split", "规范两列属性行", api, prop="use_property_split",
               fallback=""),
        _entry("flat_button", "扁平按钮（去高光渐变）", api, prop="emboss",
               fallback=""),
        _entry("grid_flow", "网格流式按钮排布", api, call="grid_flow",
               fallback=""),
        _entry("progress_bar", "进度条", api, call="progress",
               fallback=""),
        _entry("two_col_split", "左右分栏", api, call="split",
               fallback=""),
        # 实测：116 个 UILayout 函数中已无 context_menu（5.2 移除，改由 menu_pie
        # / popover 承担右键菜单）。此处如实判 blocked，不凭 brief 印象放行。
        _entry("context_menu", "右键上下文菜单", api, call="context_menu",
               blocker="5.2.1 实测 UILayout.context_menu 已移除，116 个函数中不存在",
               fallback="改用 layout.menu_pie() 或 layout.popover() 承载右键入口"),
        _entry("warn_color", "警告橙 wcol_state.warning", api,
               denied=("color", "theme_color"),
               blocker="主题里有该色但 UILayout 不暴露 ThemeWidgetColors",
               fallback="用 icon='ERROR' 与文案承载「注意」语义，不靠颜色"),
        _entry("ok_color", "成功绿 wcol_state.success", api,
               denied=("color", "theme_color"),
               blocker="同上，主题里有但 Python API 调不到",
               fallback="用 icon='CHECKMARK' 承载「成功」语义"),
    ]
    return {
        "generated_for": api["blender_version"],
        "blender_version": api["blender_version"],
        "generated_from": "dev/build_constraints.py",
        "icon_count": api["icons"]["count"],
        "palette": api["theme"]["colors"],
        "entries": entries,
    }


def main():
    api = load_api()
    reg = build(api)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2, sort_keys=True)
    blocked = [e["key"] for e in reg["entries"] if not e["native_ok"]]
    allowed = [e["key"] for e in reg["entries"] if e["native_ok"]]
    print("CONSTRAINTS_OK wrote=%s" % OUT)
    print("total=%d allowed=%d blocked=%d" % (len(reg["entries"]), len(allowed), len(blocked)))
    print("ALLOWED %s" % " ".join(allowed))
    print("BLOCKED %s" % " ".join(blocked))
    # 汇总行必须由真实检查派生：生成器没有会失败的断言，但可以报出实际缺口，
    # 让人 grep 不到"PASS"时看到的是事实而不是硬编码的 0。
    no_ev = [e["key"] for e in reg["entries"] if not e.get("evidence")]
    incomplete = [e["key"] for e in reg["entries"]
                  if not e["native_ok"] and not (e.get("blocker") and e.get("fallback"))]
    print("ENTRIES %d  evidence_ok %d  blocked_complete %d"
          % (len(reg["entries"]), len(reg["entries"]) - len(no_ev),
             len(blocked) - len(incomplete)))
    if no_ev:
        print("MISSING_EVIDENCE %s" % " ".join(no_ev))
    if incomplete:
        print("INCOMPLETE_BLOCKED %s" % " ".join(incomplete))
    return 0


if __name__ == "__main__":
    sys.exit(main())
