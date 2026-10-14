# -*- coding: utf-8 -*-
"""录制器自检。核心断言：split() 必须返回单个 layout，不是元组。

每条断言都经 ck() 记录，任何环节抛异常都记为一条 FAIL 而非吞掉汇总行。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dev.layout_recorder import RecLayout, Recorder

FAILS = []
TOTAL = [0]

_MISSING = object()


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    try:
        ok = bool(cond)
    except Exception as exc:  # 断言本身炸了也不能吃掉汇总行
        ok = False
        msg = "%s (断言异常: %r)" % (msg, exc)
    if ok:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def g(node, key):
    """容错取键：node 缺失或键缺失返回哨兵，供 ck 判失败。"""
    try:
        if not isinstance(node, dict):
            return _MISSING
        return node.get(key, _MISSING)
    except Exception:
        return _MISSING


def walk(n, acc):
    acc.append(g(n, "element_id"))
    for c in (g(n, "children") or []):
        walk(c, acc)


def find(n, eid):
    if g(n, "element_id") == eid:
        return n
    for c in (g(n, "children") or []):
        got = find(c, eid)
        if got:
            return got
    return None


def _flatten(node):
    yield node
    for c in (g(node, "children") or []):
        yield from _flatten(c)


def main():
    r = Recorder()

    # 1. split 在 Blender 5.x 返回单个 UILayout，不是二元组。
    #    test_native_ui.py 的旧 MockLayout 返回元组，是错的；本条防回归。
    s = r.root.split(factor=0.3)
    ck("split_returns_single", isinstance(s, RecLayout), "split 必须返回单个 layout")
    ck("split_not_tuple", not isinstance(s, tuple), "split 绝不能返回元组")
    s.label(text="窄列")

    # 2. 容器嵌套
    b = r.root.box()
    row = b.row(align=True)
    row.label(text="按钮", icon='CHECKMARK')
    b.tag("chat.action_row")
    row.tag("chat.action_row.undo")

    # 3. 属性快照
    b.alert = True
    row.enabled = False
    row.scale_y = 1.4
    b.use_property_split = True
    b.emboss = 'NONE'

    d = r.finish()
    ids = []
    walk(d, ids)
    ck("id_captured", "chat.action_row" in ids, "块级 ID 未进入树")
    ck("child_id_captured", "chat.action_row.undo" in ids, "子控件 ID 未进入树")

    box_node = find(d, "chat.action_row")
    undo_node = find(d, "chat.action_row.undo")
    ck("box_node_found", box_node is not None, "找不到 chat.action_row 节点")
    ck("alert_recorded", g(box_node, "alert") is True, "alert 未记录")
    ck("enabled_recorded", g(undo_node, "enabled") is False, "enabled 未记录")
    ck("scale_y_recorded", g(undo_node, "scale_y") == 1.4, "scale_y 未记录")
    ck("use_property_split_recorded",
       g(box_node, "use_property_split") is True, "use_property_split 未记录")
    ck("emboss_recorded", g(box_node, "emboss") == 'NONE', "emboss 未记录")
    ck("split_recorded",
       any(g(n, "kind") == "split" for n in _flatten(d)), "split 节点未记录")
    ck("split_factor_recorded",
       any(g(n, "split_factor") == 0.3 for n in _flatten(d)),
       "split_factor=0.3 未记录")
    ck("box_child_row", g(box_node, "children") and
       any(g(c, "kind") == "row" for c in g(box_node, "children")),
       "box 下应有 row 子节点")

    texts = []
    for n in _flatten(d):
        texts.extend(n.get("texts", []))
    ck("texts_recorded", "按钮" in texts and "窄列" in texts,
       "文本未记录：%s" % texts)

    # 4. 已实测事实：5.2.1 没有 layout.context_menu，桩不能存在。
    ck("no_context_menu_stub",
       not hasattr(RecLayout, "context_menu"),
       "RecLayout 不应有 context_menu 桩（5.2.1 真实 API 已移除）")

    # 5. 序列可 JSON 化
    import json
    try:
        json.dumps(d)
        ck("json_serializable", True)
    except Exception as exc:
        ck("json_serializable", False, "finish() 不可 JSON 序列化：%r" % exc)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    traceback.print_exc()
    ck("harness", False, "测试执行中抛异常，汇总见上")
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1)
