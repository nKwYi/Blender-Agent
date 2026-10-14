import os, sys, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U, panel as P

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = "CAN_YOU_SEE_THIS_NATIVE_TEXT_NOW?"
state.prompt_lines = 2
state.history.clear()

# Hook panel.build so NOTHING covers tx, ty, tw, th!
_orig_build = P.build
def hole_build(c):
    res = _orig_build(c)
    items = res["items"]
    W, H = c.W, c.H
    pills = list(c.ui.quick_pills(c.state))
    tx, ty, tw, th = P.composer_text_rect(W, H, c.state, pills)
    
    # Filter items: remove any rect that intersects with the interior of (tx, ty, tw, th)
    new_items = []
    for it in items:
        op = it[0]
        if op == "rect":
            rx, ry, rw, rh = it[1], it[2], it[3], it[4]
            # Check if this rect covers the hole (tx, ty, tw, th)
            # If it's the full-panel rect (0, 0, W, H), clip it to above composer
            if rx == 0 and ry == 0 and rw == W and rh == H:
                new_items.append(("rect", 0, 0, W, H - res["composer_rect"][3], 0, it[6]))
                continue
            # If it's the composer background, carve out the hole
            if rx == 0 and rw == W and ry >= H - res["composer_rect"][3]:
                # Slice around hole
                bg = it[6]
                if ty > ry:
                    new_items.append(("rect", 0, ry, W, ty - ry, 0, bg))
                if tx > 0:
                    new_items.append(("rect", 0, ty, tx, th, 0, bg))
                if W > tx + tw:
                    new_items.append(("rect", tx + tw, ty, W - (tx + tw), th, 0, bg))
                if H > ty + th:
                    new_items.append(("rect", 0, ty + th, W, H - (ty + th), 0, bg))
                continue
        new_items.append(it)
    res["items"] = new_items
    return res

P.build = hole_build

# Hook DEEPSEEK_PT_chat.draw to remove tail and use proper spacer
def patched_draw(self, context):
    layout = self.layout
    st = getattr(context.scene, "deepseek_agent", None)
    if st is None:
        return
    runtime.ensure_installed(context)
    region = getattr(context, "region", None)
    region_h = getattr(region, "height", 0) or 0
    slot = runtime.native_slot(region_h, getattr(region, "width", 420))
    if slot is None:
        return
    spacer = layout.row()
    spacer.enabled = False
    spacer.label(text="")
    spacer.scale_y = max(0.0, slot["top_gap"]) / runtime.NATIVE_ROW_H
    box = layout.row()
    box.scale_y = max(1.0, float(st.prompt_lines or 2)) * 1.15
    box.prop(st, "prompt", text="")

U.DEEPSEEK_PT_chat.draw = patched_draw
U.DEEPSEEK_PT_chat.bl_category = "Item"
try:
    bpy.utils.unregister_class(U.DEEPSEEK_PT_chat)
except Exception:
    pass
bpy.utils.register_class(U.DEEPSEEK_PT_chat)

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
        p = os.path.join(HERE, "out", "hole_composer_result2.png")
        bpy.ops.screen.screenshot(filepath=p)
        print("SAVED_HOLE_RESULT2:", p)
        bpy.ops.wm.quit_blender()
        return None
    return 0.3

bpy.app.timers.register(tick, first_interval=0.5)
