"""GUI 自动化截图脚本：捕获复刻 Figma 样式的完整 AI 建模会话面板。
用法：blender.exe -P dev/screenshot_figma_redesign.py
"""
import os
import sys
import json
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

import blender_deepseek_agent as bda
from blender_deepseek_agent import worker as wk
from blender_deepseek_agent.state import Err, Phase, Run, ToolCall
from blender_deepseek_agent.receipt import Receipt

bda.register()

state = bpy.context.scene.deepseek_agent
bda.config.get_config = lambda: {
    "api_key": "sk-real-mock-123456",
    "key_source": "prefs",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 20,
    "max_turns": 4,
    "wall_budget": 45,
    "allow_arbitrary_code": False,
    "history_page": 6,
}

step = {"idx": 0}
steps = []


def snap(name):
    path = os.path.join(OUT, f"{name}.png")
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=path)
    print("SAVED_SCREENSHOT", name, path, os.path.exists(path))


def init_viewport():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                        space.overlay.show_overlays = False
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                ui_region = next((r for r in area.regions if r.type == 'UI'), None)
                if region and (ui_region is None or ui_region.width <= 1):
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.screen.region_toggle(region_type='UI')
                with bpy.context.temp_override(window=window, area=area):
                    try:
                        bpy.ops.screen.screen_full_area(use_hide_panels=False)
                    except Exception:
                        pass
                area.tag_redraw()


def step_0_prepare():
    init_viewport()
    # 清空变换面板绘制，让 AI 对话获得完整的垂直展示空间
    if hasattr(bpy.types, "OBJECT_PT_transform"):
        bpy.types.OBJECT_PT_transform.draw = lambda self, context: None

    # 挂载到 Item tab 便于视口直接可见
    bda.ui.DEEPSEEK_PT_chat.bl_category = "Item"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)

    state.active_tab = 'CHAT'
    state.session_topic = "红色沙发建模"
    state.session_date = "2026/10/9"
    state.prompt = ""

    # 填充多轮对话数据（完全对齐用户最新红色沙发实测场景）
    state.history.clear()

    # 第 1 轮
    u1 = state.history.add()
    u1.role = "你"
    u1.text = "在游标处创建一个红色沙发"

    a1 = state.history.add()
    a1.role = "AI"
    a1.msg_type = "CLARIFY"
    a1.duration_str = "8秒"
    a1.text = (
        "好嘞，红色沙发这个我可以做！在动手前先跟你确认几个细节：\n"
        "你确认后我就按你选的参数一次性车削出主体轮廓、熔接靠背\n"
        "扶手、再赋予 PBR 材质。\n"
        "• 1. 款式（推荐：现代简约直排三人沙发；也可选 L 型贵妃榻 / 复古拉扣布艺）\n"
        "• 2. 尺寸（推荐：三人位 2.0m × 0.9m × 高 0.82m，座高 0.42m）\n"
        "• 3. 材质（推荐：微绒 / 科技布暗红（1，0.0...面皮革 0.25 反射））\n"
        "• 4. 配套细节（要/不要：木质锥形椅脚、抱枕、坐垫分缝）"
    )

    state.show_card_objects = False
    state.show_card_params = False
    state.show_card_script = False
    state.show_card_archive = False

    bda.ui._tag(bpy.context)
    return 0.6


def step_1_capture():
    bda.ui._tag(bpy.context)
    snap("figma_redesign_full")
    return 0.4


def step_2_finish():
    # 恢复原 category
    bda.ui.DEEPSEEK_PT_chat.bl_category = "AI 对话"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)
    print("ALL_FIGMA_REDESIGN_CAPTURES_COMPLETED")
    bpy.ops.wm.quit_blender()
    return None


steps.extend([step_0_prepare, step_1_capture, step_2_finish])


def runner():
    try:
        idx = step["idx"]
        if idx >= len(steps):
            return None
        fn = steps[idx]
        delay = fn()
        step["idx"] += 1
        return delay or 0.1
    except Exception as e:
        print("RUNNER_EXCEPTION:", e)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(runner, first_interval=1.2)
