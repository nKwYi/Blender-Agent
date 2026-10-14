# -*- coding: utf-8 -*-
"""7 个状态构造器的契约测试。

三条硬约束（与 dev/test_ids.py 同一套，来自 Global Constraints）：

1. 汇总行 `PASS <n>  FAIL <m>` 必须无条件打印。断言环节自身抛出的异常
   （缺 key、类型不对、AttributeError）只能记一条 FAIL，不能 traceback
   把汇总行吃掉——Blender 5.2.1 的 -P 脚本即使抛未捕获异常退出码也是 0。
2. 断言不能空洞。每条 cond 都来自真实求值；"某个文案没出现"这类断言必须
   由真实分支文本支撑，否则恒真。
3. 面板 draw 走真实入口 DEEPSEEK_PT_chat.draw（tabbar + draw_chat_content），
   因为 chat.* 的 5 个常驻 ID 里有 1 个（chat.tabbar）只挂在 tabbar 行上；
   只调 draw_chat_content 会少一个 ID，那是导出范围问题，不是埋点问题。
"""
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
from blender_deepseek_agent.ui_ids import (
    CHAT_TABBAR, CHAT_STREAM, CHAT_COMPOSER, CHAT_SEND, CHAT_STOP,
    CHAT_ACTION_ROW, CHAT_OPTIONS,
)
from dev.states import STATE_NAMES, REQUIRED_KEYS, build, apply_spec
from dev.layout_recorder import Recorder

FAILS = []
TOTAL = [0]

EXPECTED = ["idle", "clarify", "options", "running", "done", "partial", "failed"]

# 非 failed 状态不允许出现失败态文案；这是真实分支文本（ui.py:845-846），
# 断言非空洞：把 failed 状态混进循环里就会 FAIL。
FAILED_MARK = "任务执行中断"

# running 的忙碌文案。states.py:155 设的相位是 Phase.TOOL_RUNNING，calls 末位是
# 带 spin 的 execute_blender_code，所以命中 ui.py:136-139 的 TOOL_RUNNING 分支。
# 只断言 stop 按钮是没用的：REQUESTING 同属 BUSY（state.py:22），按钮断言在两个
# 相位下都成立，相位回退不会被发现——文案才是相位真正落到画面的证据。
BUSY_RUNNING_TEXT = "正在执行旋转车削一体化成型"
BUSY_REQUESTING_TEXT = "正在构思三维几何结构与物理尺度"


class _PanelStub(object):
    """DEEPSEEK_PT_chat.draw 只用到 self.layout，其余是类属性。"""

    def __init__(self, layout):
        self.layout = layout


def emit(name, ok, msg=""):
    TOTAL[0] += 1
    if ok:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def ck(name, cond, msg=""):
    """布尔断言；cond 的求值本身抛异常时降级成一条 FAIL。"""
    try:
        ok = bool(cond)
    except Exception as exc:
        emit(name, False, "断言求值抛异常 %s: %s" % (type(exc).__name__, exc))
        return False
    emit(name, ok, msg)
    return ok


def attempt(name, fn):
    """执行 fn()，异常降级成一条 FAIL，绝不 traceback。"""
    try:
        ok = fn()
    except Exception as exc:
        emit(name, False, "抛异常 %s: %s（%s）"
             % (type(exc).__name__, exc, traceback.format_exc().splitlines()[-3:]))
        return False
    emit(name, bool(ok), "" if ok else "断言为假")
    return bool(ok)


def all_ids(node, out=None):
    if out is None:
        out = []
    if node.get("element_id"):
        out.append(node["element_id"])
    for c in node.get("children", []):
        all_ids(c, out)
    return out


def all_texts(node):
    out = list(node.get("texts", []))
    for c in node.get("children", []):
        out.extend(all_texts(c))
    return out


def main():
    bda.register()
    scene = bpy.context.scene

    ck("state_names_exact", STATE_NAMES == EXPECTED,
       "状态名必须严格等于 %s，实际 %s" % (EXPECTED, STATE_NAMES))

    for name in STATE_NAMES:
        # 1) 构造器契约：键齐全 + 名字自洽
        def _keys(n=name):
            spec = build(n)
            missing = [k for k in REQUIRED_KEYS if k not in spec]
            assert not missing, "缺键 %s" % missing
            assert spec["state"] == n, "state 字段为 %r" % spec["state"]
            return True
        attempt("build_keys_%s" % name, _keys)

        spec = build(name)
        state = apply_spec(scene.deepseek_agent, spec)

        # 2) draw_chat_content 单独能画出来（brief 的原始门槛）
        def _draw_chat(s=state, sp=spec):
            rec = Recorder()
            U.draw_chat_content(rec.root, bpy.context, s, sp["run"])
            tree = rec.finish()
            assert tree.get("children") or tree.get("texts"), "树为空"
            return True
        attempt("draw_chat_content_%s" % name, _draw_chat)

        # 3) 真实面板 draw（tabbar + 内容）能画出来，且 ID >= 5
        holder = {}

        def _draw_panel(s=state, sp=spec, holder=holder):
            rec = Recorder()
            U.DEEPSEEK_PT_chat.draw(_PanelStub(rec.root), bpy.context)
            tree = rec.finish()
            ids = all_ids(tree)
            holder["ids"] = ids
            holder["tree"] = tree
            print("STATE %s ids=%d %s" % (name, len(ids), ",".join(ids)))
            return len(ids) >= 5
        ok = attempt("draw_panel_%s" % name, _draw_panel)

        ids = holder.get("ids") or []
        ck("ids_ge5_%s" % name, ok,
           "只有 %d 个带 ID 节点：%s" % (len(ids), ids))
        ck("has_content_%s" % name, bool(all_texts(holder.get("tree") or {})),
           "没有任何可见文案")

        # 4) 分支断言：每个状态都必须命中 chat.tabbar 与 4 个常驻容器之一
        ck("tabbar_%s" % name, CHAT_TABBAR in ids, "缺 tabbar，实际 %s" % ids)
        ck("core_blocks_%s" % name,
           {CHAT_STREAM, CHAT_COMPOSER, CHAT_ACTION_ROW} <= set(ids),
           "缺常驻块，实际 %s" % ids)
        # 只有 running 该出现终止按钮。依据不是"哪些状态看着在忙"，而是
        # worker 的真实相位：CONTROLLER.busy = run.phase in BUSY（worker.py:190），
        # 而模型回问/回选项都是无工具调用的回复，worker.py:65-68 直接置
        # COMPLETED，收尾 worker.py:341-342 也把 BUSY 统一映射为 COMPLETED。
        # 所以等澄清与等选规格时面板是空闲的，必须显示发送按钮。
        expect_stop = (name == "running")
        ck("send_stop_%s" % name,
           (CHAT_STOP in ids) if expect_stop else (CHAT_SEND in ids),
           "busy 分支不符：期望 %s，实际 %s"
           % ("stop" if expect_stop else "send", ids))

        # 5) 选项卡只在 options 状态出现（真实分支 ui.py:900-906）
        ck("options_%s" % name, (CHAT_OPTIONS in ids) == (name == "options"),
           "chat.options 出现与否不符合状态语义：%s" % ids)

        # 6) 失败文案只有 failed 状态允许（非空洞：把任一非 failed 状态改成
        #    FAILED 就会 FAIL）
        texts = all_texts(holder.get("tree") or {})
        ck("no_error_%s" % name,
           (any(FAILED_MARK in t for t in texts)) == (name == "failed"),
           "失败文案与状态不符：含 %s=%s"
           % (FAILED_MARK, any(FAILED_MARK in t for t in texts)))

        # 7) running 的忙碌文案必须锁在 TOOL_RUNNING 分支。
        if name == "running":
            ck("busy_text_running", BUSY_RUNNING_TEXT in texts,
               "running 没渲染出 TOOL_RUNNING 分支文案，实际 %s" % texts)
            ck("busy_not_requesting", BUSY_REQUESTING_TEXT not in texts,
               "running 渲染出 REQUESTING 文案，run.phase 被回退了：%s" % texts)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


try:
    main()
except SystemExit:
    raise
except Exception as exc:  # 汇总行是唯一判据，绝不能让异常吃掉
    emit("harness", False, "主流程抛异常 %s: %s\n%s"
         % (type(exc).__name__, exc, traceback.format_exc()))
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1)
