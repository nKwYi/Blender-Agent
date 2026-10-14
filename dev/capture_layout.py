# -*- coding: utf-8 -*-
"""无头导出 7 个状态的布局树 JSON。绝不开 GUI。

导出走真实面板入口 DEEPSEEK_PT_chat.draw，而不是只调 draw_chat_content：
chat.tabbar 的埋点在 Panel.draw 里（ui.py:990），draw_chat_content 拿不到它，
导出的树就会比实机少一个区块。两者都不需要任何伪造容器。

判定依据只有自己打印的汇总行——Blender 5.2.1 的 -P 脚本即使抛未捕获异常，
进程退出码仍是 0。
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import ui as U
from dev.layout_recorder import Recorder
from dev.states import STATE_NAMES, apply_spec, build

OUT_DIR = os.path.join(ROOT, "ui_workbench", "data", "layout")

FAILS = []
TOTAL = [0]


class _PanelStub(object):
    """DEEPSEEK_PT_chat.draw 只用到 self.layout。"""

    def __init__(self, layout):
        self.layout = layout


def emit(name, ok, msg=""):
    TOTAL[0] += 1
    if ok:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def _count_ids(node):
    n = 1 if node.get("element_id") else 0
    for c in node.get("children", []):
        n += _count_ids(c)
    return n


def _ids(node, out=None):
    if out is None:
        out = []
    if node.get("element_id"):
        out.append(node["element_id"])
    for c in node.get("children", []):
        _ids(c, out)
    return out


def capture_one(name, state):
    rec = Recorder()
    U.DEEPSEEK_PT_chat.draw(_PanelStub(rec.root), bpy.context)
    tree = rec.finish()
    tree["state"] = name

    path = os.path.join(OUT_DIR, "%s.json" % name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tree, fh, ensure_ascii=False, indent=2)

    ids = _ids(tree)
    n = len(ids)
    print("WROTE %s ids=%d %s" % (name, n, ",".join(ids)))
    if n >= 5:
        emit("ids_ge5_%s" % name, True)
    else:
        emit("ids_ge5_%s" % name, False,
             "只有 %d 个带 ID 节点：%s" % (n, ids))
    return n


def main():
    bda.register()
    state = bpy.context.scene.deepseek_agent
    os.makedirs(OUT_DIR, exist_ok=True)

    written = []
    for name in STATE_NAMES:
        try:
            spec = build(name)
            apply_spec(state, spec)
            capture_one(name, state)
            written.append(name)
        except Exception as exc:
            emit("capture_%s" % name, False,
                 "抛异常 %s: %s\n%s" % (type(exc).__name__, exc,
                                       traceback.format_exc()))

    print("STATES %s" % " ".join(written))
    if len(written) == len(STATE_NAMES) and not FAILS:
        print("CAPTURE_LAYOUT_OK count=%d" % len(written))
    else:
        print("CAPTURE_LAYOUT_BAD count=%d" % len(written))
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    return 1 if FAILS else 0


try:
    rc = main()
except Exception as exc:  # 汇总行绝不能被异常吃掉
    emit("harness", False, "主流程抛异常 %s: %s\n%s"
         % (type(exc).__name__, exc, traceback.format_exc()))
    print("CAPTURE_LAYOUT_BAD count=0")
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    rc = 1
sys.exit(rc)
