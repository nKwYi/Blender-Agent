import os, sys, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U, panel as P, theme as T

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = "制作一个现代简约直排沙发"
state.prompt_lines = 2
state.history.clear()

# Hook panel._composer to render prompt text and cursor!
_orig_composer = P._composer
def prompt_composer(c, W, H):
    items, total = _orig_composer(c, W, H)
    pills = list(c.ui.quick_pills(c.state))
    tx, ty, tw, th = P.composer_text_rect(W, H, c.state, pills)
    # Append the prompt text
    b = P.B(items, tx, tw, ty, c.hover)
    if c.state.prompt:
        lines = P.wrap(c.state.prompt, T.FS, tw - T.TEXT_PAD_X * 2 - T.SEND_SIZE)
        max_lines = max(1, int(c.state.prompt_lines or 2))
        for idx, line in enumerate(lines[:max_lines]):
            b.text(tx + T.TEXT_PAD_X, ty + T.TEXT_PAD_Y + idx * T.LINE_H, line, T.FS, T.IN_TEXT)
        # Blinking cursor
        last_line = lines[:max_lines][-1] if lines else ""
        cw = P.text_width(last_line, T.FS)
        cur_x = tx + T.TEXT_PAD_X + cw + 2
        cur_y = ty + T.TEXT_PAD_Y + (len(lines[:max_lines]) - 1) * T.LINE_H
        b.line(cur_x, cur_y, cur_x, cur_y + T.FS * 1.15, 1.5, T.IN_FOCUS)
    return items, total

P._composer = prompt_composer

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

U.DEEPSEEK_PT_chat.bl_category = "Item"
try:
    bpy.utils.unregister_class(U.DEEPSEEK_PT_chat)
except Exception:
    pass
bpy.utils.register_class(U.DEEPSEEK_PT_chat)

settle = [0]
def tick():
    init_viewport()
    settle[0] += 1
    if settle[0] > 4:
        p = os.path.join(HERE, "out", "gpu_typing_result.png")
        bpy.ops.screen.screenshot(filepath=p)
        print("SAVED_GPU_TYPING_RESULT:", p)
        bpy.ops.wm.quit_blender()
        return None
    return 0.3

bpy.app.timers.register(tick, first_interval=0.5)
