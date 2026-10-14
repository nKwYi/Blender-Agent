# -*- coding: utf-8 -*-
import os, sys, time, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = "HELLO_BLENDER_TEXTBOX_TEST"

# Uninstall GPU draw handler so only native UI is rendered!
runtime.uninstall()

def find_v3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None

opened = [False]
settle = [0]

def tick():
    a = find_v3d()
    if not a:
        return 0.5
    a.spaces.active.show_region_ui = True
    regs = [r for r in a.regions if r.type == 'UI']
    if regs and not opened[0]:
        regs[0].active_panel_category = "AI 对话"
        if regs[0].active_panel_category == "AI 对话":
            opened[0] = True
    a.tag_redraw()
    settle[0] += 1
    if settle[0] > 4:
        p = os.path.join(HERE, "out", "native_only.png")
        bpy.ops.screen.screenshot(filepath=p)
        print("SAVED NATIVE SHOT:", p)
        bpy.ops.wm.quit_blender()
        return None
    return 0.4

bpy.app.timers.register(tick, first_interval=0.5)
