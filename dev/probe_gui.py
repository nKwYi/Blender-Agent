"""GUI 实测探针：textbox 按键行为 / UIList 行高与滚动 / 长面板滚动 / 三档宽度 / 全局 Undo 真值。

它自己把观测结果持续写进 dev/out/uiprobe.json，所以我可以从外部按键再读回来。

用法：blender.exe -P dev/probe_gui.py
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "uiprobe.json")

import blender_deepseek_agent as bda
from blender_deepseek_agent.tools import execute_tool

bda.register()

E = {"events": [], "undo": {}, "width": {}, "timer": {"fires": 0}, "threads": {}}


def log(kind, **kw):
    E["events"].append({"t": round(time.time() % 100000, 2), "kind": kind, **kw})


def dump():
    with open(LOG, "w", encoding="utf-8") as h:
        json.dump(E, h, ensure_ascii=False, indent=1)


# ---------- 全局 Undo：无头测不了，这里补 ----------
pref = bpy.context.preferences.edit
E["undo"]["global_default"] = pref.use_global_undo
try:
    execute_tool("create_primitive", {"type": "cube", "name": "U_Ops"})
    E["undo"]["created"] = "U_Ops" in bpy.data.objects
    r = bpy.ops.ed.undo()
    E["undo"]["after_ops"] = {"result": str(r), "gone": "U_Ops" not in bpy.data.objects}
except Exception as e:
    E["undo"]["after_ops"] = f"{type(e).__name__}: {e}"

try:
    execute_tool("execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (9,9,9)"})
    r = bpy.ops.ed.undo()
    loc = tuple(round(v) for v in bpy.data.objects['Cube'].location)
    E["undo"]["after_exec_no_push"] = {"result": str(r), "location": loc, "reverted": loc == (0, 0, 0)}
except Exception as e:
    E["undo"]["after_exec_no_push"] = f"{type(e).__name__}: {e}"

try:
    execute_tool("execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (7,7,7)\nbpy.ops.ed.undo_push(message='agent')"})
    r = bpy.ops.ed.undo()
    loc = tuple(round(v) for v in bpy.data.objects['Cube'].location)
    E["undo"]["after_exec_with_push"] = {"result": str(r), "location": loc, "reverted": loc == (0, 0, 0)}
except Exception as e:
    E["undo"]["after_exec_with_push"] = f"{type(e).__name__}: {e}"

try:
    pref.use_global_undo = False
    execute_tool("create_primitive", {"type": "cube", "name": "U_Off"})
    r = bpy.ops.ed.undo()
    E["undo"]["global_off"] = {"result": str(r), "still_there": "U_Off" in bpy.data.objects}
    pref.use_global_undo = True
except Exception as e:
    E["undo"]["global_off"] = f"{type(e).__name__}: {e}"
dump()

# ---------- 探针面板 ----------
class PB_ITEM(bpy.types.PropertyGroup):
    text: bpy.props.StringProperty()


class PB_UL(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        layout.label(text=item.text[:60], icon='NONE')


class PB_PG(bpy.types.PropertyGroup):
    tb: bpy.props.StringProperty(default="")
    items: bpy.props.CollectionProperty(type=PB_ITEM)
    active: bpy.props.IntProperty()
    log: bpy.props.StringProperty(default="")


class PB_OT_enter(bpy.types.Operator):
    """probe: 记录 Enter 是否触发了绑定到 textbox 的 operator"""
    bl_idname = "pb.enter"
    bl_label = "ENTER_FIRED"
    bl_options = set()

    def execute(self, context):
        pg = context.scene.pbprobe
        log("operator_enter_fired", textbox_value=pg.tb)
        dump()
        return {'FINISHED'}


class PB_PT(bpy.types.Panel):
    bl_label = "UI PROBE"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Probe"

    def draw(self, context):
        pg = context.scene.pbprobe
        col = self.layout.column()
        col.label(text="A) textbox 三行 + placeholder")
        col.textbox(pg, "tb", initial_visible_lines=3, placeholder="在此输入：中文长文本裁切测试")
        col.operator("pb.enter", text="手动触发 operator")
        col.label(text="B) UIList 200 条（含中文长行）")
        col.template_list("PB_UL", "", pg, "items", pg, "active", rows=6)
        col.label(text=f"选中 #{pg.active}: {pg.items[pg.active].text if pg.items else ''}"[:70])
        col.label(text="C) 200 行 label（测整块面板能否滚）")
        for i in range(200):
            col.label(text=f"L{i:03d} 中文长文本裁切测试中文长文本裁切测试中文长文本裁切测试{i}")


classes = (PB_ITEM, PB_UL, PB_PG, PB_OT_enter, PB_PT)
for c in classes:
    bpy.utils.register_class(c)
bpy.types.Scene.pbprobe = bpy.props.PointerProperty(type=PB_PG)

pg = bpy.context.scene.pbprobe
pg.items.clear()
for i in range(200):
    it = pg.items.add()
    it.text = f"#{i:03d} 建一个 2 米的球放在 (3,0,1) 给它金属材质 roughness 0.2 再复制 3 个排成一排"

# ---------- 视口设置 + 侧栏展开 + 宽度尝试 ----------
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.screen.region_toggle(region_type='UI')
            ui = next((r for r in area.regions if r.type == 'UI'), None)
            if ui:
                try:
                    ui.width = 272
                    E["width"]["settable"] = True
                    E["width"]["readback"] = ui.width
                except Exception as e:
                    E["width"]["settable"] = False
                    E["width"]["err"] = f"{type(e).__name__}: {e}"

# ---------- worker 线程碰 bpy 在 GUI 下会不会炸 ----------
def bad_worker():
    try:
        for _ in range(30):
            _ = len(bpy.data.objects)
            time.sleep(0.02)
        E["threads"]["worker_read_bpy"] = "no_error"
    except Exception as e:
        E["threads"]["worker_read_bpy"] = f"{type(e).__name__}: {e}"


threading.Thread(target=bad_worker).start()


def heartbeat():
    E["timer"]["fires"] += 1
    E["timer"]["last_textbox"] = pg.tb
    E["timer"]["ui_width"] = next((r.width for a in bpy.context.window_manager.windows[0].screen.areas
                                  for r in a.regions if r.type == 'UI'), None)
    dump()
    return 0.4


bpy.app.timers.register(heartbeat, first_interval=0.4)
log("startup")
dump()
print("UIPROBE ready", LOG)
