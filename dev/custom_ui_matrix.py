# -*- coding: utf-8 -*-
"""画中画：把所有 region_type x draw_type 组合一次性测一遍，看哪些真的会触发回调。

背景：probe v2 用 region_type='UI' + 'POST_PIXEL' 注册成功，但 draw_cb 被调用 0 次。
说明这两者不是有效组合。这里穷举矩阵，每个组合挂一个独立计数器，
跑几秒后统一汇报 —— 直接给出「自绘 UI 到底能不能落在 N 面板上」的判定依据。
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "matrix.txt")
lines = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


import blender_deepseek_agent as bda                      # noqa: E402
if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

import blf                                                # noqa: E402
import gpu                                                # noqa: E402
from mathutils import Matrix                              # noqa: E402
from gpu_extras.batch import batch_for_shader             # noqa: E402

REGION_TYPES = ['WINDOW', 'UI', 'TOOLS', 'UI_HEADER', 'HEADER', 'TOOL_HEADER']
DRAW_TYPES = ['PRE_VIEW', 'POST_VIEW', 'PRE_PIXEL', 'POST_PIXEL']

COUNT = {}
BOUND = {}


def make_cb(key):
    def cb():
        r = bpy.context.region_data
        COUNT[key] += 1
        if r is not None:
            BOUND[key] = "%s %dx%d" % (r.type, r.width, r.height)
        # 只在 UI 区域的 POST 阶段真的画东西，其余只计数，避免互相覆盖
        if not r or r.type != 'UI':
            return
        gpu.matrix.load_matrix(Matrix.Identity(4))
        gpu.matrix.load_projection_matrix(Matrix.Identity(4))
        gpu.state.blend_set('BLEND')
        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')
        sh = gpu.shader.from_builtin('UNIFORM_COLOR')
        verts = [(0, 0), (r.width, 0), (r.width, 8),
                 (0, 0), (r.width, 8), (0, 8)]
        b = batch_for_shader(sh, 'TRIS', {"pos": verts})
        sh.uniform_float_color("color", (1.0, 0.0, 0.8, 1.0))
        b.draw(sh)
        blf.size(0, 20)
        blf.color(0, 1, 1, 0, 1)
        blf.position(0, 14, r.height - 40, 0)
        blf.draw(0, "CUSTOM %s" % key)
    return cb


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


handles = []
area = find_v3d()
space = area.spaces.active
space.show_region_ui = True
regs = [r for r in area.regions if r.type == 'UI']

for rt in REGION_TYPES:
    for dt in DRAW_TYPES:
        key = "%s+%s" % (rt, dt)
        COUNT[key] = 0
        try:
            h = space.draw_handler_add(make_cb(key), (), rt, dt)
            handles.append(h)
            log("register OK", key)
        except Exception as e:
            log("register FAIL", key, repr(e)[:90])

log("region UI rect:", [(r.x, r.y, r.width, r.height) for r in regs])


def tick():
    a = find_v3d()
    if a:
        a.tag_redraw()
    return 0.5


n = [0]


def finish():
    n[0] += 1
    if n[0] < 8:
        return 0.5
    log("")
    log("=== 调用次数矩阵（>0 = 真的会触发） ===")
    fired = []
    for rt in REGION_TYPES:
        row = []
        for dt in DRAW_TYPES:
            key = "%s+%s" % (rt, dt)
            c = COUNT.get(key, -1)
            row.append("%s=%d" % (dt, c))
            if c > 0:
                fired.append((key, c, BOUND.get(key, "")))
        log("%-12s %s" % (rt, "  ".join(row)))
    log("")
    log("=== 可用组合 ===")
    for key, c, b in fired:
        log("  FIRED %-24s calls=%-6d %s" % (key, c, b))
    if not fired:
        log("  NONE —— 自绘 UI 路线在本机不可行")

    # 在最后一个可用组合上画一次实心色块并截图
    p = os.path.join(OUT, "matrix.png")
    bpy.ops.screen.screenshot(filepath=p)
    log("shot", p, os.path.getsize(p))
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=0.2)
bpy.app.timers.register(finish, first_interval=2.0)
log("registered")