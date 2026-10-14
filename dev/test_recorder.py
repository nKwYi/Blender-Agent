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
    for c in gl(n, "children"):
        walk(c, acc)


def find(n, eid):
    if g(n, "element_id") == eid:
        return n
    for c in gl(n, "children"):
        got = find(c, eid)
        if got:
            return got
    return None


def find_op(node, op_id):
    """在整棵树里按 operator id 找 ops 条目。"""
    for n in _flatten(node):
        for o in gl(n, "ops"):
            if g(o, "id") == op_id:
                return o
    return None


def gl(node, key):
    """容错取列表字段：键缺失或类型不对时返回空列表。

    不能用 `g(...) or []`——缺键时 g 返回哨兵对象（truthy），
    迭代它会抛 TypeError，把一条断言变成 harness 崩溃。
    """
    v = g(node, key)
    return v if isinstance(v, list) else []


def gd(node, key):
    """容错取 dict 字段：键缺失或类型不对时返回空 dict（同 gl 的理由）。"""
    v = g(node, key)
    return v if isinstance(v, dict) else {}


def _raises(fn):
    """fn 是否抛 AttributeError（用于验证真实 Blender 语义被保留）。"""
    try:
        fn()
    except AttributeError:
        return True
    except Exception:
        return False
    return False


def _flatten(node):
    yield node
    for c in gl(node, "children"):
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
    # 必须赋非默认值：_CONTAINER_DEFAULTS["emboss"] 就是 "NONE"，
    # 赋 'NONE' 的断言任何未实现 emboss 的实现都能通过（空洞断言）。
    b.emboss = 'EMBOSS'

    # 3b. operator 返回值的属性赋值必须被记录且可回读。
    #     真实调用点：op.module = PACKAGE_ID（ui.py:1130）、op.index = i（ui.py:1003）。
    op = b.operator("preferences.addon_show", text="打开完整偏好设置",
                    icon='PREFERENCES')
    op.module = "blender_deepseek_agent"
    op.index = 7
    ck("op_attr_readback", getattr(op, "module", None) == "blender_deepseek_agent",
       "op.module 回读失败：%r" % (getattr(op, "module", "<缺失>"),))
    ck("op_attr_readback_int", getattr(op, "index", None) == 7,
       "op.index 回读失败：%r" % (getattr(op, "index", "<缺失>"),))
    ck("op_unset_attr_raises",
       _raises(lambda: getattr(op, "never_assigned")),
       "未赋值的 Operator 属性应抛 AttributeError，与真实 Blender 一致")

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
    ck("emboss_recorded", g(box_node, "emboss") == 'EMBOSS', "emboss 未记录")
    ck("split_recorded",
       any(g(n, "kind") == "split" for n in _flatten(d)), "split 节点未记录")
    ck("split_factor_recorded",
       any(g(n, "split_factor") == 0.3 for n in _flatten(d)),
       "split_factor=0.3 未记录")
    ck("box_child_row", any(g(c, "kind") == "row" for c in gl(box_node, "children")),
       "box 下应有 row 子节点")

    texts = []
    for n in _flatten(d):
        texts.extend(gl(n, "texts"))
    ck("texts_recorded", "按钮" in texts and "窄列" in texts,
       "文本未记录：%s" % texts)
    # Minor 5：operator()/textbox() 把 text 并入 texts 是 brief 之外的行为，
    # 既然保留就必须有断言兜住，否则是无测试的行为。
    ck("op_text_recorded", "打开完整偏好设置" in texts,
       "operator 的 text 未并入 texts：%s" % texts)

    # 3c. operator 属性赋值必须出现在树的 ops 条目里，且值不做 str() 化。
    ops = []
    for n in _flatten(d):
        ops.extend(gl(n, "ops"))
    addon_op = next((o for o in ops if g(o, "id") == "preferences.addon_show"), None)
    ck("op_in_tree", addon_op is not None, "树中找不到 preferences.addon_show")
    assigned = gd(addon_op, "assigned")
    ck("op_module_in_tree",
       assigned.get("module") == "blender_deepseek_agent",
       "op.module 未进入 ops 条目：%r" % (assigned,))
    ck("op_index_not_stringified", assigned.get("index") == 7,
       "op.index 应保留原类型 int：%r" % (type(assigned.get("index")).__name__,))

    # 3d. finish() 后再赋值不得污染已导出的树（assigned 必须是快照）。
    op.module = "CHANGED_AFTER_FINISH"
    ck("tree_is_snapshot",
       gd(find_op(d, "preferences.addon_show"), "assigned").get("module")
       == "blender_deepseek_agent",
       "finish() 之后再赋值污染了已导出的树")

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
