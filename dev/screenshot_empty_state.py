import os
import sys
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

import blender_deepseek_agent as bda
bda.register()

state = bpy.context.scene.deepseek_agent
state.active_tab = 'CHAT'
state.prompt = ""
state.history.clear()  # 0 轮对话空状态

# 清空变换面板绘制，让 AI 对话获得完整的垂直展示空间
if hasattr(bpy.types, "OBJECT_PT_transform"):
    bpy.types.OBJECT_PT_transform.draw = lambda self, context: None

# 挂载到 Item tab 便于视口直接可见
bda.ui.DEEPSEEK_PT_chat.bl_category = "Item"
bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)

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

def snap():
    init_viewport()
    path = os.path.join(OUT, "empty_state.png")
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=path)
    print("SAVED_EMPTY_STATE", path, os.path.exists(path))
    bpy.ops.wm.quit_blender()

bpy.app.timers.register(snap, first_interval=1.0)
