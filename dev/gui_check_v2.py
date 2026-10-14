# -*- coding: utf-8 -*-
"""GUI 实机验证：在真实 Blender 窗口里打开 AI 对话侧栏，灌入假会话数据，
逐状态截图，确认新版布局真的画得出来（换行、框体、按钮宽度、多行输入框）。

用法：blender.exe -P dev/gui_check_v2.py     （不能用 --background）
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
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "gui_check_v2.txt")
lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print("[GUI]", s)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- 灌数据
try:
    import blender_deepseek_agent as bda
    from blender_deepseek_agent import ui as U
    from blender_deepseek_agent.state import Err, Phase, Run, ToolCall
    from blender_deepseek_agent.receipt import Receipt

    if not hasattr(bpy.types.Scene, "deepseek_agent"):
        bda.register()
        log("addon registered")
    else:
        log("addon already registered")

    state = bpy.context.scene.deepseek_agent
    _cfg = {
        "api_key": "sk-gui-mock", "key_source": "prefs", "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com", "provider": "DEEPSEEK",
        "timeout": 20, "max_turns": 4, "wall_budget": 45,
        "allow_arbitrary_code": False, "history_page": 3,
    }
    bda.config.get_config = lambda: dict(_cfg)

    state.history.clear()
    state.session_topic = "陶瓷茶杯"
    state.session_date = "2026/10/9"

    run = Run("做个陶瓷茶杯")
    run.phase = Phase.COMPLETED
    run.rounds = 2
    run.elapsed = 7.4
    run.calls = [ToolCall("1", "get_scene_info"), ToolCall("2", "create_primitive"),
                 ToolCall("3", "execute_blender_code")]
    run.receipt = Receipt()
    run.collection_name = "AI_陶瓷茶杯"
    run.artifacts = {
        "objects": [
            {"name": "Cup_Body", "tag": "Mesh", "sub": "旋转车削一次成型，32 面"},
            {"name": "Cup_Handle", "tag": "Mesh", "sub": "曲线 + 实体化"},
            {"name": "Cup_Mat", "tag": "Material", "sub": "Principled 釉面"},
        ],
        "modifiers": ["Bevel 0.002m", "Subdivision 1"],
        "materials": [["粗糙度", "0.35"], ["金属度", "0.0"]],
        "geo": [["口径", "82mm"], ["高度", "95mm"], ["壁厚", "4mm"]],
        "script": "bpy.ops.mesh.primitive_lathe_add(vertices=32)\n"
                  "mod = obj.modifiers.new('Bevel', 'BEVEL')",
    }
    bda.worker.CONTROLLER.run = run

    U.push_history(state, "你", "做一个陶瓷茶杯，口径 82mm，要能叠放")
    U.push_history(state, "AI", "好的，我先确认几个关键细节：\n"
                               "1. 杯型风格：经典直筒微收口 / 鼓腹圆润 / 手作厚壁窑变（推荐：经典直筒微收口）\n"
                               "2. 表面质感：哑光陶瓷 / 亮面釉彩 / 磨砂金属（推荐：哑光陶瓷）\n"
                               "回复这几点，我就开始车削。", run=None)
    U.push_history(state, "AI", "茶杯建好了。杯身用旋转车削一次成型，不是拼接的。",
                   run=run)
    state.prompt = "把杯口加厚一点"
    log("seeded history =", len(state.history))

except Exception:
    import traceback
    log("SEED_FAILED", traceback.format_exc())

# ---------------------------------------------------------------- 状态机
STEPS = [
    ("01_chat_full",      lambda st: None),
    ("02_options_card",   lambda st: st.__setattr__("active_tab", 'CHAT')),
    ("03_tab_params",     lambda st: setattr(st, "result_tab", 'PARAMS')),
    ("04_tab_script",     lambda st: setattr(st, "result_tab", 'SCRIPT')),
    ("05_tab_archive",    lambda st: setattr(st, "result_tab", 'ARCHIVE')),
    ("06_list_expanded",  lambda st: (setattr(st, "result_tab", 'OBJECTS'),
                                      setattr(st, "show_result_list", True))),
    ("07_other_open",     lambda st: (U.ensure_notes(st, 2),
                                      setattr(st, "other_open_q", "1"))),
    ("08_load_more",      lambda st: setattr(st, "shown_count", 8)),
    ("09_tab_detail",     lambda st: setattr(st, "active_tab", 'DETAIL')),
    ("10_tab_settings",   lambda st: setattr(st, "active_tab", 'SETTINGS')),
    ("11_back_to_chat",   lambda st: (setattr(st, "active_tab", 'CHAT'),
                                      setattr(st, "shown_count", 2),
                                      setattr(st, "other_open_q", ""),
                                      setattr(st, "show_result_list", False))),
]

_draw_count = [0]
_errs = []

# 注意：Panel.draw 在注册时已绑定到原函数，事后改类属性不影响 RNA 调用，
# 所以计数器必须挂在运行期按模块全局查找的 _draw_message 上。
_orig_msg = U._draw_message


def _counting_msg(*a, **kw):
    _draw_count[0] += 1
    return _orig_msg(*a, **kw)


U._draw_message = _counting_msg
log("counter hooked on _draw_message")

state_i = [0]
settle = [0]
_opened = [False]


def find_v3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


def open_sidebar():
    area = find_v3d()
    if area is None:
        log("NO_VIEW3D")
        return False
    sp = area.spaces.active
    sp.show_region_ui = True
    ui_regions = [r for r in area.regions if r.type == 'UI']
    if not ui_regions:
        log("NO_UI_REGION")
        return False
    reg = ui_regions[0]
    log("area", area.x, area.y, area.width, area.height,
        "| region", reg.x, reg.y, reg.width, reg.height)
    log("cats =", list(getattr(reg, "categories", [])))
    try:
        reg.active_panel_category = "AI 对话"
        log("category set ->", reg.active_panel_category)
    except Exception as e:
        log("CATEGORY_FAIL", e)
        return False
    area.tag_redraw()
    _opened[0] = True
    return True


def step():
    st = bpy.context.scene.deepseek_agent
    if not _opened[0]:
        if not open_sidebar():
            return 2.0
        return 1.5

    if settle[0] < 3:
        settle[0] += 1
        find_v3d().tag_redraw()
        return 0.5

    name, fn = STEPS[state_i[0]]
    try:
        fn(st)
    except Exception:
        log("STEP_FAIL", name)
    find_v3d().tag_redraw()
    time.sleep(0.35)
    path = os.path.join(OUT, f"v2_{name}.png")
    try:
        bpy.ops.screen.screenshot(filepath=path)
        log("shot", name, os.path.getsize(path), "bytes", "draws=", _draw_count[0])
    except Exception as e:
        log("SHOT_FAIL", name, e)

    state_i[0] += 1
    if state_i[0] >= len(STEPS):
        log("DONE draws=", _draw_count[0], "errors=", len(_errs))
        for e in _errs[:5]:
            log("DRAW_ERROR", e[-500:])
        log("SUMMARY", json.dumps({"steps": len(STEPS), "draws": _draw_count[0],
                                   "errors": len(_errs)}))
        bpy.ops.wm.quit_blender()
        return None
    settle[0] = 0
    return 0.4


bpy.app.timers.register(step, first_interval=1.0)
log("timer registered")
log("MODULE_FILE", getattr(sys.modules.get("blender_deepseek_agent"), "__file__", "?"))

# 超时兜底：40 秒后无论如何退出，避免 GUI 进程挂住
_watchdog = [0]


def watchdog():
    _watchdog[0] += 1
    if _watchdog[0] > 80:
        log("WATCHDOG_TIMEOUT draws=", _draw_count[0])
        bpy.ops.wm.quit_blender()
        return None
    return 0.5


bpy.app.timers.register(watchdog, first_interval=0.5)