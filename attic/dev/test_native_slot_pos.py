import os, sys, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U

# Ensure registered
if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = "THIS_IS_THE_PROMPT_TEXT_FOR_TESTING"
state.prompt_lines = 3

# Put panel in 'Item' category so it draws in factory startup
U.DEEPSEEK_PT_chat.bl_category = "Item"
try:
    bpy.utils.unregister_class(U.DEEPSEEK_PT_chat)
except Exception:
    pass
bpy.utils.register_class(U.DEEPSEEK_PT_chat)

# COMPLETELY PREVENT GPU draw handler and modal operator
runtime.uninstall()
runtime.ensure_installed = lambda ctx: None
U.DEEPSEEK_OT_panel_modal.ensure = lambda ctx: None

def init_viewport():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'SOLID'
                ui_region = next((r for r in area.regions if r.type == 'UI'), None)
                if ui_region is None or ui_region.width <= 1:
                    with bpy.context.temp_override(window=window, area=area):
                        bpy.ops.screen.region_toggle(region_type='UI')
                area.tag_redraw()

settle = [0]

def tick():
    init_viewport()
    settle[0] += 1
    if settle[0] > 4:
        p = os.path.join(HERE, "out", "pure_native_panel.png")
        bpy.ops.screen.screenshot(filepath=p)
        print("SAVED_PURE_NATIVE_SHOT:", p)
        bpy.ops.wm.quit_blender()
        return None
    return 0.3

bpy.app.timers.register(tick, first_interval=0.5)
