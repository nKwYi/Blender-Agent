"""GUI 实测 v4：3D 视图 N 面板能否纵向滚动。
加入 draw() 计数器，确认 TALL 面板是否真的被渲染；分步设置分类避免 region 失效。
"""
import bpy
import os

OUT = r"E:\Three JS\Blender Agent\dev\out"
LOG = []
DRAW_CALLS = []


class TEST_PT_tall(bpy.types.Panel):
    bl_label = "TALL"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI 对话"

    def draw(self, context):
        DRAW_CALLS.append(len(self.layout))
        lay = self.layout
        for i in range(200):
            lay.label(text=f"ROW {i:03d}")


bpy.utils.register_class(TEST_PT_tall)


def find_v3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                ui = next((r for r in area.regions if r.type == 'UI'), None)
                return win, area, ui
    return None, None, None


def open_sb():
    win, area, _ = find_v3d()
    area.spaces.active.show_region_ui = True
    win.screen.update_tag()
    area.tag_redraw()
    LOG.append("sidebar opened")
    return None


def pick_cat():
    win, area, region = find_v3d()          # 重新取，避免失效引用
    LOG.append(f"region {region.width}x{region.height}, cat before = {region.active_panel_category!r}")
    try:
        region.active_panel_category = "AI 对话"
    except Exception as exc:  # noqa: BLE001
        LOG.append(f"set category raised {type(exc).__name__}: {exc}")
    win.screen.update_tag()
    area.tag_redraw()
    LOG.append(f"cat after = {region.active_panel_category!r}")
    return None


def shoot(path):
    win, area, _ = find_v3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area):
        bpy.ops.screen.screenshot(filepath=path)
    area.tag_redraw()
    return os.path.exists(path)


def diff_ratio(p1, p2):
    i1 = bpy.data.images.load(p1, check_existing=False)
    i2 = bpy.data.images.load(p2, check_existing=False)
    a, b = i1.pixels[:], i2.pixels[:]
    n = min(len(a), len(b))
    ch = sum(1 for k in range(0, n, 4)
             if abs(a[k]-b[k]) > 0.02 or abs(a[k+1]-b[k+1]) > 0.02 or abs(a[k+2]-b[k+2]) > 0.02)
    tot = n // 4
    bpy.data.images.remove(i1); bpy.data.images.remove(i2)
    return ch / tot if tot else 0.0


def before():
    win, area, region = find_v3d()
    LOG.append(f"cat at before-shot = {region.active_panel_category!r}, TALL draw_calls so far = {len(DRAW_CALLS)}")
    shoot(os.path.join(OUT, "_scroll_before.png"))
    return None


def scroll():
    win, area, region = find_v3d()
    for _ in range(3):
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
            bpy.ops.view2d.scroll_up()
    area.tag_redraw()
    LOG.append("scroll_up x3 done")
    return None


def after():
    shoot(os.path.join(OUT, "_scroll_after.png"))
    return None


def compare():
    p1 = os.path.join(OUT, "_scroll_before.png")
    p2 = os.path.join(OUT, "_scroll_after.png")
    r = diff_ratio(p1, p2) if (os.path.exists(p1) and os.path.exists(p2)) else -1.0
    LOG.append(f"TALL draw_calls total = {len(DRAW_CALLS)}")
    LOG.append(f"PIXEL_DIFF_RATIO = {r:.6f}")
    LOG.append("VERDICT = " + ("SCROLL_WORKS" if r > 0.005 else ("INCONCLUSIVE" if r < 0 else "NO_SCROLL_EFFECT")))
    with open(os.path.join(OUT, "_scroll_result.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    return None


bpy.app.timers.register(open_sb, first_interval=3.0)
bpy.app.timers.register(pick_cat, first_interval=4.2)
bpy.app.timers.register(before, first_interval=5.6)
bpy.app.timers.register(scroll, first_interval=6.6)
bpy.app.timers.register(after, first_interval=7.6)
bpy.app.timers.register(compare, first_interval=8.6)
bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=9.8)
