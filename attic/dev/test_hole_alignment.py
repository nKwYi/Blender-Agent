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
state.prompt = "测试输入框文字_HELLO_TEST"
state.prompt_lines = 2

# Measure native slot
region_h = 1000
slot = runtime.native_slot(region_h, 420)
print("TEST SLOT:", slot)

# In DEEPSEEK_PT_chat, monkeypatch draw to remove tail and test
def patched_draw(self, context):
    layout = self.layout
    st = context.scene.deepseek_agent
    slot = runtime.native_slot(1000, 420)
    spacer = layout.row()
    spacer.enabled = False
    spacer.label(text="")
    spacer.scale_y = slot["top_gap"] / runtime.NATIVE_ROW_H
    box = layout.row()
    box.prop(st, "prompt", text="")

U.DEEPSEEK_PT_chat.draw = patched_draw
U.DEEPSEEK_PT_chat.bl_category = "AI 对话"

print("PATCHED DRAW CONFIGURED")
