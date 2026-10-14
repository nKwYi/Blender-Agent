import os, sys, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = "CAN_YOU_SEE_THIS_TEXT"

# Make sure GPU draw handler is NOT installed for this test
runtime.uninstall()

def find_v3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None

settle = [0]

def tick():
    a = find_v3d()
    if not a:
        return 0.5
    a.spaces.active.show_region_ui = True
    settle[0] += 1
    a.tag_redraw()
    if settle[0] > 5:
        out_p = os.path.join(HERE, "out", "probe_native_only.png")
        bpy.ops.screen.screenshot(filepath=out_p)
        print("PROBE_SAVED:", out_p)
        bpy.ops.wm.quit_blender()
        return None
    return 0.4

bpy.app.timers.register(tick, first_interval=0.5)
