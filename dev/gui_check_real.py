# -*- coding: utf-8 -*-
"""用真实模型抓到的追问/回复原文渲染面板，做端到端视觉确认（不联网、不用 Key）。"""
import io
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "gui_real.txt")
lines = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))
    with io.open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


import blender_deepseek_agent as bda                      # noqa: E402
from blender_deepseek_agent import ui as U               # noqa: E402
from blender_deepseek_agent.state import Phase, Run, ToolCall  # noqa: E402
from blender_deepseek_agent.receipt import Receipt       # noqa: E402

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs", "model": "MiniMax-M3.1-Flash",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

state = bpy.context.scene.deepseek_agent
state.history.clear()
state.session_topic = "陶瓷马克杯"
state.session_date = "2026/10/10"

run = Run("做个水杯")
run.phase = Phase.COMPLETED
run.rounds = 3
run.elapsed = 41.2
run.calls = [ToolCall("1", "get_scene_info"), ToolCall("2", "execute_blender_code"),
             ToolCall("3", "transform_object")]
run.receipt = Receipt()
run.collection_name = "AI_陶瓷马克杯"
run.artifacts = {
    "objects": [{"name": "Mug_Cone_Stackable_350ml", "tag": "Mesh",
                 "sub": "截面曲线旋转车削一体成型，含内腔与卷唇"},
                {"name": "Mug_Handle", "tag": "Mesh", "sub": "D 形实心把手，布尔熔接"},
                {"name": "Mug_Ceramic", "tag": "Material", "sub": "Principled 哑光釉面"}],
    "modifiers": ["Bevel 0.0008m", "Weighted Normal"],
    "materials": [["粗糙度", "0.42"], ["金属度", "0.0"]],
    "geo": [["口径", "86mm"], ["高度", "95mm"], ["壁厚", "3mm"], ["容量", "350ml"]],
    "script": "bpy.ops.mesh.primitive_lathe_add(vertices=48)\n"
              "mod = obj.modifiers.new('Bevel', 'BEVEL')",
}
bda.worker.CONTROLLER.run = run

REAL_CLARIFY = (
    "场景是空的，我准备用截面曲线旋转车削（Spin）一体成型杯身+内腔+卷唇+杯底，再布尔熔接把手，"
    "保证单网格无穿模。先确认几个关键规格：\n\n"
    "1. **器型风格**：直筒微收口 / 上宽下窄锥形 / 鼓腹圆润 / 带盖马克杯（推荐：直筒微收口，办公最通用）\n"
    "2. **尺寸容量**：办公室杯 350ml（口径 8.5cm × 高 9.5cm）/ 旅行随行杯 450ml（口径 7.5cm × 高 13cm）"
    "/ 马克杯 300ml（口径 8.8cm × 高 9.5cm）（推荐：350ml 直筒）\n"
    "3. **把手**：无把手直筒 / D 形实心把手（推荐：D 形）/ 带盖 + 吸管孔\n"
    "4. **材质配色**：素白瓷 / 哑光陶瓷 / 半透明磨砂玻璃 / 彩色釉面（推荐：哑光陶瓷）\n\n"
    "点选或直接回复\"全部按推荐\"，我立刻建模。"
)

U.push_history(state, "你", "帮我做个水杯")
U.push_history(state, "AI", REAL_CLARIFY, run=None)
state.prompt = ""
log("history seeded, notes=%d" % len(state.notes))


def find_v3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


STEPS = [("01_real_clarify", lambda st: (setattr(st, "prompt", ""),
                                         setattr(st, "prompt_lines", 2))),
         ("02_selected", lambda st: setattr(st, "selected_options_json",
                                            json.dumps({"0": ["上宽下窄锥形"],
                                                        "3": ["哑光陶瓷"]},
                                                       ensure_ascii=False))),
         ("03_other_open", lambda st: (setattr(st, "other_open_q", "2"),
                                       setattr(st, "prompt", "把手再粗一点，底部加一圈防滑"),
                                       setattr(st, "prompt_lines", 5))),
         ("04_built", lambda st: (U.push_history(
             state, "你", "参数已确认：上宽下窄锥形，补充要求：杯口要能叠放，开始建模！", run=None),
             U.push_history(state, "AI", "杯子做好了：350ml 锥形马克杯，壁厚 3mm，"
                                         "可叠放，哑光陶瓷釉面。", run=run),
             setattr(st, "selected_options_json", "{}"))),
         ("05_result_objects", lambda st: (setattr(st, "result_tab", 'OBJECTS'),
                                           setattr(st, "show_result_list", True))),
         ("06_result_params", lambda st: setattr(st, "result_tab", 'PARAMS'))]

step_i = [0]
settle = [0]
opened = [False]


def open_sidebar():
    area = find_v3d()
    if area is None:
        return False
    area.spaces.active.show_region_ui = True
    regs = [r for r in area.regions if r.type == 'UI']
    if not regs:
        return False
    # 首次设置会因 region 尚未布局而报 read-only，必须每 tick 重试直到成功
    try:
        regs[0].active_panel_category = "AI 对话"
        if regs[0].active_panel_category == "AI 对话":
            area.tag_redraw()
            opened[0] = True
            log("category set OK")
            return True
    except Exception:
        pass
    area.tag_redraw()
    return False


def step():
    st = bpy.context.scene.deepseek_agent
    if not opened[0]:
        open_sidebar()
        return 1.5
    if settle[0] < 3:
        settle[0] += 1
        find_v3d().tag_redraw()
        return 0.5
    name, fn = STEPS[step_i[0]]
    try:
        fn(st)
    except Exception as e:
        log("STEP_FAIL", name, e)
    find_v3d().tag_redraw()
    import time
    time.sleep(0.3)
    p = os.path.join(OUT, "real_%s.png" % name)
    try:
        bpy.ops.screen.screenshot(filepath=p)
        log("shot", name, os.path.getsize(p))
    except Exception as e:
        log("SHOT_FAIL", name, e)
    step_i[0] += 1
    if step_i[0] >= len(STEPS):
        log("DONE")
        bpy.ops.wm.quit_blender()
        return None
    settle[0] = 0
    return 0.4


bpy.app.timers.register(step, first_interval=1.0)
log("registered")

_wd = [0]


def wd():
    _wd[0] += 1
    if _wd[0] > 60:
        bpy.ops.wm.quit_blender()
        return None
    return 0.5


bpy.app.timers.register(wd, first_interval=0.5)