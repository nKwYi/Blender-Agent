"""尖峰：验证"自绘标记 + 原生控件"能不能对齐，以及 UI region 自绘到底可不可用。

只用 blf 在"我们以为的行位置"写字，截图后看它压在哪一行原生内容上 → 直接量出误差。
不画矩形，先把坐标这件事定死。

用法：blender.exe -P dev/spike_hybrid.py
"""
import json
import os
import sys

import bpy
import blf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

import blender_deepseek_agent as bda  # noqa: E402

STATE = {"rows": [], "region": None, "handlers": {}}
LINE_H = 17.0
PAD = 6.0
HEAD_H = 34.0


class SP_PG(bpy.types.PropertyGroup):
    probe: bpy.props.StringProperty(default="")


class SP_OT(bpy.types.Operator):
    bl_idname = "sp.hit"
    bl_label = "原生按钮"
    bl_options = set()

    def execute(self, context):
        self.report({'INFO'}, "原生按钮被点到了")
        return {'FINISHED'}


class SP_PT(bpy.types.Panel):
    bl_label = "HYBRID SPIKE"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Spike"

    def draw(self, context):
        layout = self.layout
        rows = []
        a = layout.box()
        a.label(text="A 状态行", icon='CHECKMARK')
        rows.append(("A", "label"))
        b = layout.box()
        b.textbox(context.scene.sp_probe, "probe", initial_visible_lines=3, placeholder="B 三行输入框")
        rows.append(("B", "textbox3"))
        b.operator("sp.hit", text="C 原生按钮：点我验证命中", icon='PLAY')
        rows.append(("C", "button"))
        d = layout.box()
        for i in range(3):
            d.label(text=f"D{i} 一行文字")
            rows.append((f"D{i}", "label"))
        STATE["rows"] = rows


def make_painter(region_type):
    def paint():
        win = bpy.context.window_manager.windows[0]
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
        if not area:
            return
        ui = next((r for r in area.regions if r.type == 'UI'), None)
        if not ui or ui.width <= 1:
            return
        STATE["region"] = {"w": ui.width, "h": ui.height, "area_h": area.height,
                           "x": ui.x, "y": ui.y, "dpi": bpy.context.preferences.system.dpi}
        y = ui.height - HEAD_H
        marks = []
        for tag, kind in STATE["rows"]:
            h = LINE_H * (4 if kind == "textbox3" else 1) + PAD * 2
            blf.position(0, 4, y - h + 4, 0)
            blf.size(0, 12)
            blf.color(0, 1, 0.4, 0, 1)
            blf.draw(0, f"[{region_type}]{tag}·{h:.0f}")
            marks.append({"tag": tag, "y_top": round(y, 1), "h": round(h, 1)})
            y -= h + 4.0
        STATE["marks"] = marks
        with open(os.path.join(OUT, "spike_%s.json" % region_type), "w", encoding="utf-8") as fh:
            json.dump(STATE, fh, ensure_ascii=False, indent=1)
    return paint


handles = []


def install():
    for rt in ('UI', 'WINDOW'):
        try:
            h = bpy.types.SpaceView3D.draw_handler_add(make_painter(rt), (), rt, 'POST_PIXEL')
            handles.append((rt, h))
            STATE["handlers"][rt] = "added"
        except Exception as error:
            STATE["handlers"][rt] = f"{type(error).__name__}: {error}"


# 1) 先开侧栏并读出当前激活的 tab 名（只读，改不了）
tab = ""
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.screen.region_toggle(region_type='UI')
            for r in area.regions:
                if r.type == 'UI' and r.active_panel_category:
                    tab = r.active_panel_category
STATE["tab"] = tab

# 2) 把探针面板挂到那个 tab 上，保证它就是显示中的一页
SP_PT.bl_category = "Spike"

bda.register()
for cls in (SP_PG, SP_OT, SP_PT):
    bpy.utils.register_class(cls)
bpy.types.Scene.sp_probe = bpy.props.PointerProperty(type=SP_PG)
install()
print("SPIKE_READY tab=%r handlers=%s" % (STATE["tab"], json.dumps(STATE["handlers"])))
