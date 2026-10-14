# -*- coding: utf-8 -*-
"""实测 5.2 的 UILayout.split() 到底把内容放在哪一侧——无头 Mock 会给假答案。

用法：blender.exe -P dev/probe_split_gui.py
截图 dev/out/probe_split.png；等 dev/out/probe_split.stop 后自行退出。
"""
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SHOT = os.path.join(OUT, "probe_split.png")
STOP = os.path.join(OUT, "probe_split.stop")
LOG = os.path.join(OUT, "probe_split.txt")

lines = []


def probe_draw(self, context):
    lay = self.layout
    lay.label(text="V1 row.alignment=RIGHT + box")
    r1 = lay.row()
    r1.alignment = 'RIGHT'
    r1.box().label(text="V1")

    lay.label(text="V2 column.alignment=RIGHT + box")
    c2 = lay.column()
    c2.alignment = 'RIGHT'
    b2 = c2.box()
    b2.label(text="V2 这是一句人说的话")
    b2.label(text="第二行")

    lay.label(text="V3 split(0.35) 后在返回值里放 box")
    a3 = lay.split(factor=0.35)
    a3.box().label(text="V3")

    lay.label(text="V4 split 返回值的类型/长度")
    probe = lay.split(factor=0.5)
    lay.label(text="type=" + type(probe).__name__)
    lay.label(text="hasattr_second=" + str(hasattr(probe, "box")))

    lay.label(text="V5 box 内 row.alignment=RIGHT")
    b5 = lay.box()
    r5 = b5.row()
    r5.alignment = 'RIGHT'
    r5.label(text="V5")


def find_view3d():
    for w in bpy.context.window_manager.windows:
        for area in w.screen.areas:
            if area.type == 'VIEW_3D':
                return w, area
    return None, None


def ensure_sidebar():
    w, area = find_view3d()
    if area is None:
        return None
    center = next((r for r in area.regions if r.type == 'WINDOW'), None)
    ui = next((r for r in area.regions if r.type == 'UI'), None)
    if center is not None and (ui is None or ui.width <= 1):
        with bpy.context.temp_override(window=w, area=area, region=center):
            bpy.ops.screen.region_toggle(region_type='UI')
        ui = next((r for r in area.regions if r.type == 'UI'), None)
    return ui


st = {"ticks": 0, "ui": None, "tab": False, "orig": None}


def tick():
    st["ticks"] += 1
    if st["ui"] is None:
        st["ui"] = ensure_sidebar()
    if not st["tab"] and st["ui"] is not None:
        w, area = find_view3d()
        try:
            with bpy.context.temp_override(window=w, area=area, region=st["ui"]):
                st["ui"].active_panel_category = "AI 对话"
            st["tab"] = st["ui"].active_panel_category == "AI 对话"
        except Exception:  # noqa: BLE001
            pass
    if st["tab"] and st["orig"] is None:
        cls = bpy.types.DEEPSEEK_PT_chat
        st["orig"] = cls.draw
        cls.draw = probe_draw
    if st["ticks"] < 30:
        return 0.25
    finish()


def finish():
    try:
        bpy.ops.screen.screenshot(filepath=SHOT)
    except Exception as exc:  # noqa: BLE001
        lines.append("SHOT_ERR " + repr(exc)[:120])
    lines.append("TAB " + str(st["tab"]))
    with open(LOG, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("PROBE_DONE", flush=True)
    bpy.app.timers.register(wait_stop, first_interval=1.0)


def wait_stop():
    st["ticks"] += 1
    if os.path.exists(STOP) or st["ticks"] > 90:
        if st["orig"] is not None:
            bpy.types.DEEPSEEK_PT_chat.draw = st["orig"]
        bpy.ops.wm.quit_blender()
        return None
    return 1.0


if os.path.exists(STOP):
    os.remove(STOP)
bpy.app.timers.register(tick, first_interval=0.4)
