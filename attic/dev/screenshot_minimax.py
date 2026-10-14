"""GUI 自动化截图：验证 MiniMax 服务商设置与模型列表在 Blender 中的真实渲染效果。

用法：blender.exe -P dev/screenshot_minimax.py
"""
import json
import os
import sys
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

try:
    import blender_deepseek_agent as bda
    from blender_deepseek_agent import worker as wk
except Exception as e:
    print("FATAL_IMPORT_ERROR:", e)
    bpy.ops.wm.quit_blender()
    raise

bda.register()

state = bpy.context.scene.deepseek_agent
state.active_tab = 'SETTINGS'
state.fetched_models_json = json.dumps([
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.1",
])
state.fetch_status_msg = "已成功获取 6 个最新官方模型"

# 覆盖 mock 配置
bda.config.get_config = lambda: {
    "provider": "MINIMAX",
    "provider_name": "MiniMax",
    "doc_url": "https://platform.minimax.cn/docs/api-reference/api-overview",
    "api_key": "sk-cp-token-plan-demo-key-123456",
    "key_source": "prefs",
    "model": "MiniMax-M3.1-Flash-Preview",
    "base_url": "https://api.minimax.cn/v1",
    "timeout": 20,
    "max_turns": 4,
    "wall_budget": 45,
    "allow_arbitrary_code": False,
    "history_page": 3,
}

p = bda.config._prefs()
if p:
    p.provider = "MINIMAX"
    p.api_key = "sk-cp-token-plan-demo-key-123456"
    p.model = "MiniMax-M3.1-Flash-Preview"
    p.base_url = "https://api.minimax.cn/v1"

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
    bda.ui.DEEPSEEK_PT_settings.bl_category = "Item"
    bda.ui.DEEPSEEK_PT_chat.bl_category = "AI 对话"
    bda.ui.DEEPSEEK_PT_detail.bl_category = "详情"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_settings)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_settings)
    return 0.5


def step_1_capture():
    bda.ui._tag(bpy.context)
    snap("minimax_settings_gui")
    return 0.4


def step_2_finish():
    bda.ui.DEEPSEEK_PT_settings.bl_category = "设置"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_settings)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_settings)
    print("ALL_MINIMAX_CAPTURES_COMPLETED")
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
