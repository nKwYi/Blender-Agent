# -*- coding: utf-8 -*-
"""量出 N 面板里「固定 chrome」的精确高度（历史区 + composer + 两行底部按钮）。

做法：清空历史，只留 composer 和底部按钮，渲染不同 prompt_lines 的面板，
量出最底部按钮的 y。这样 _fit_start 里的保留高度就不是拍脑袋的常数。
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "chrome_h.txt")
lines = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


import blender_deepseek_agent as bda                      # noqa: E402
from blender_deepseek_agent import ui as U               # noqa: E402

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs", "model": "m",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

DRAWS = [0]
_orig = U._draw_message


def hooked(*a, **kw):
    DRAWS[0] += 1
    return _orig(*a, **kw)


U._draw_message = hooked


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


state = bpy.context.scene.deepseek_agent
state.history.clear()
state.prompt = "把手再粗一点，底部加一圈防滑" * 3   # 长文本撑满输入框
state.prompt_lines = 2

opened = [False]


def open_sidebar():
    area = find_v3d()
    if area is None:
        return False
    area.spaces.active.show_region_ui = True
    regs = [r for r in area.regions if r.type == 'UI']
    if not regs:
        return False
    try:
        regs[0].active_panel_category = "AI 对话"
        if regs[0].active_panel_category == "AI 对话":
            opened[0] = True
            return True
    except Exception:
        pass
    return False


phase = [0]
settle = [0]
armed = [True]


def tick():
    st = bpy.context.scene.deepseek_agent
    if not opened[0]:
        open_sidebar()
        return 1.5
    a = find_v3d()
    if settle[0] < 3:
        settle[0] += 1
        a.tag_redraw()
        return 0.5
    if phase[0] < 5:
        # 换到下一档行数：先量当前档，再前进
        import time
        time.sleep(0.4)
        p = os.path.join(OUT, "chrome_lines%d.png" % st.prompt_lines)
        bpy.ops.screen.screenshot(filepath=p)
        log("shot lines=%d -> %s" % (st.prompt_lines, p))
        phase[0] += 1
        if phase[0] < 5:
            st.prompt_lines = phase[0] + 1
        settle[0] = 0
        a.tag_redraw()
        return 0.5
    log("draws total =", DRAWS[0])
    log("DONE")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
_w = [0]


def wd():
    _w[0] += 1
    if _w[0] > 70:
        bpy.ops.wm.quit_blender()
        return None
    return 0.5


bpy.app.timers.register(wd, first_interval=0.5)
log("registered")