# -*- coding: utf-8 -*-
"""自绘面板的 GUI 实测：真实渲染 + 截图，逐状态确认视觉与交互。

不联网、不用 Key：历史与产物都是造出来的，布局和绘制路径是真的。
"""
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "gui_custom.txt")
lines = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


import blender_deepseek_agent as bda                      # noqa: E402
from blender_deepseek_agent import runtime                # noqa: E402
from blender_deepseek_agent import ui as U                # noqa: E402
from blender_deepseek_agent.state import Phase, Run, ToolCall  # noqa: E402
from blender_deepseek_agent.receipt import Receipt       # noqa: E402

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs", "model": "MiniMax-M3.1-Flash-Preview",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

state = bpy.context.scene.deepseek_agent
state.history.clear()
state.notes.clear()
state.session_topic = "陶瓷马克杯"
state.session_date = "2026/10/10"
state.prompt = ""
state.prompt_lines = 2
state.shown_count = 50
state.busy = False

run = Run("做个水杯")
run.phase = Phase.COMPLETED
run.rounds = 3
run.elapsed = 41.2
run.calls = [ToolCall("1", "get_scene_info"), ToolCall("2", "execute_blender_code")]
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
              "mod = obj.modifiers.new('Bevel', 'BEVEL')\n"
              "bpy.ops.object.modifier_apply(modifier='Bevel')",
}
U.CONTROLLER.run = run

CLARIFY = (
    "场景是空的，我准备用截面曲线旋转车削一体成型杯身，再布尔熔接把手。\n"
    "先确认几个关键规格：\n\n"
    "1. **器型风格**：直筒微收口 / 上宽下窄锥形 / 鼓腹圆润 / 带盖马克杯（推荐：直筒微收口）\n"
    "2. **尺寸容量**：办公室杯 350ml / 旅行随行杯 450ml / 马克杯 300ml（推荐：350ml）\n"
    "3. **材质配色**：素白瓷 / 哑光陶瓷 / 半透明磨砂玻璃（推荐：哑光陶瓷）\n\n"
    "点选或直接回复「全部按推荐」，我立刻建模。"
)

U.push_history(state, "你", "帮我做个水杯", run=None)
U.push_history(state, "AI", CLARIFY, run=None)
U.push_history(state, "你", "参数已确认：上宽下窄锥形，补充要求：杯口要能叠放，开始建模！",
               run=None)
U.push_history(state, "AI", "杯子做好了：350ml 锥形马克杯，壁厚 3mm，可叠放，哑光陶瓷釉面。",
               run=run)
log("seeded, history=%d" % len(state.history))

DRAWS = [0]
_orig = runtime.draw_cb


def hooked():
    DRAWS[0] += 1
    return _orig()


runtime.draw_cb = hooked


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


opened = [False]
rect_info = [None]


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


STEPS = [
    ("01_clarify", lambda st: (setattr(st, "result_tab", 'OBJECTS'),
                               setattr(st, "show_result_list", False))),
    ("02_selected", lambda st: setattr(st, "selected_options_json",
                                       json.dumps({"0": ["上宽下窄锥形"],
                                                   "2": ["哑光陶瓷"]},
                                                  ensure_ascii=False))),
    ("03_prompt", lambda st: setattr(st, "prompt", "把手再粗一点，底部加一圈防滑")),
    ("04_lines5", lambda st: setattr(st, "prompt_lines", 5)),
    ("05_objects", lambda st: (setattr(st, "result_tab", 'OBJECTS'),
                               setattr(st, "show_result_list", True))),
    ("06_params", lambda st: setattr(st, "result_tab", 'PARAMS')),
    ("07_script", lambda st: setattr(st, "result_tab", 'SCRIPT')),
    ("08_scroll", lambda st: None),
]

step_i = [0]
settle = [0]


def tick():
    st = bpy.context.scene.deepseek_agent
    if not opened[0]:
        open_sidebar()
        return 1.5
    a = find_v3d()
    if a is None:
        return 1.0
    if settle[0] < 4:
        settle[0] += 1
        a.tag_redraw()
        return 0.4

    name, fn = STEPS[step_i[0]]
    if name == "08_scroll":
        for k in runtime.SCROLL:
            runtime.SCROLL[k] = 900.0
    try:
        fn(st)
    except Exception as e:
        log("STEP_FAIL", name, repr(e))

    a.tag_redraw()
    time.sleep(0.45)

    # 记录 draw 出来的布局与命中区，供事后核对
    cur = list(runtime._CURRENT.values())
    if cur:
        o = cur[-1]
        rect_info[0] = (o["stream_rect"], o["composer_rect"],
                        [it[5] for it in o["items"] if it[0] == "hit"])
        log("%-12s items=%-4d stream=%s composer=%s hits=%d"
            % (name, len(o["items"]), o["stream_rect"], o["composer_rect"],
               len(rect_info[0][2])))

    p = os.path.join(OUT, "cus_%s.png" % name)
    from blender_deepseek_agent import painter as PT
    log("%-12s STATS items=%d batches=%d tris=%d ops=%s"
        % (name, PT.STATS["items"], PT.STATS["batches"], PT.STATS["tris"],
           sorted(PT.STATS["ops"].items(), key=lambda kv: -kv[1])[:8]))
    try:
        bpy.ops.screen.screenshot(filepath=p)
        log("shot", name, os.path.getsize(p))
    except Exception as e:
        log("SHOT_FAIL", name, repr(e))

    step_i[0] += 1
    if step_i[0] >= len(STEPS):
        log("draws total =", DRAWS[0])
        log("actions =", sorted(set(rect_info[0][2])) if rect_info[0] else None)
        log("DONE")
        bpy.ops.wm.quit_blender()
        return None
    settle[0] = 0
    return 0.4


bpy.app.timers.register(tick, first_interval=1.0)
_w = [0]


def wd():
    _w[0] += 1
    if _w[0] > 90:
        log("WATCHDOG timeout")
        bpy.ops.wm.quit_blender()
        return None
    return 0.5


bpy.app.timers.register(wd, first_interval=0.5)
log("registered")