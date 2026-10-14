# -*- coding: utf-8 -*-
"""probe v3：把 UI region 在注册时抓进全局，绕过 context.region_data 的坑。

v2 的结论：
  - draw_type 合法值只有 POST_PIXEL / POST_VIEW / PRE_VIEW，PRE_PIXEL 不存在
  - region_type='UI' + 'POST_PIXEL' 确实会触发（实测 12 次/几秒）
  - 但 bpy.context.region_data 在这个阶段返回的是 RegionView3D（3D 视口子区域），
    既没有 .type 也没有 .width/.height —— 用它取尺寸必然 AttributeError，
    这就是 v1/v2「注册成功但画面上什么都没有」的真凶。

v3 用注册时捕获的 UI region 引用来画，并同时用两种方式取证：
  1) bpy.ops.screen.screenshot  —— 前台缓冲截图
  2) bpy.ops.render.opengl       —— OpenGL viewport 渲染
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "custom_ui_probe3.txt")
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
import traceback                                          # noqa: E402
from mathutils import Matrix                              # noqa: E402
from gpu_extras.batch import batch_for_shader             # noqa: E402

UI_REGION = [None]
CALLS = [0]
ERR = [False]


def _set_color(sh, rgba):
    """Blender 4.x 是 uniform_float_color，5.x 改成了 uniform_4fv —— 两个都试。"""
    for meth in ("uniform_float_color", "uniform_4fv"):
        fn = getattr(sh, meth, None)
        if fn is not None:
            try:
                fn("color", rgba)
                return
            except Exception:
                pass


def rect(x, y, w, h, color):
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    b = batch_for_shader(sh, 'TRIS',
                         {"pos": [(x, y), (x + w, y), (x + w, y + h),
                                  (x, y), (x + w, y + h), (x, y + h)]})
    _set_color(sh, color)
    b.draw(sh)


def round_rect(x, y, w, h, r, color, seg=6):
    import math
    verts = [(x + w * 0.5, y + h * 0.5)]
    for ox, oy, a0 in [(x + w - r, y + r, -math.pi * 0.5),
                       (x + w - r, y + h - r, 0.0),
                       (x + r, y + h - r, math.pi * 0.5),
                       (x + r, y + r, math.pi)]:
        for i in range(seg + 1):
            a = a0 + (math.pi * 0.5) * i / seg
            verts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    b = batch_for_shader(sh, 'TRIS', {"pos": verts})
    _set_color(sh, color)
    b.draw(sh)


def text(x, y, s, size, color):
    blf.size(0, size)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, s)


def draw_cb():
    try:
        _draw_inner()
    except Exception as e:
        if not ERR[0]:
            ERR[0] = repr(e)
            log("DRAW ERROR:", repr(e))
            log(traceback.format_exc())


def _draw_inner():
    r = UI_REGION[0]
    if r is None or r.width <= 0:
        return
    CALLS[0] += 1
    w, h = r.width, r.height

    gpu.matrix.load_matrix(Matrix.Identity(4))
    # >>> 关键坑 1：gpu.matrix.load_ortho_mtx 在 Blender 5.2 里不存在（AttributeError）。
    # >>> 关键坑 2：load_projection_matrix(Identity) 会把 (0,0) 映射到视口中心而非左上角，
    # >>> 像素坐标全部画到屏幕外。必须手搓 2D 正交矩阵：x/y 从左下角起算。
    m = Matrix.Identity(4)
    m[0][0] = 2.0 / float(w)
    m[1][1] = 2.0 / float(h)
    m[0][3] = -1.0
    m[1][3] = -1.0
    gpu.matrix.load_projection_matrix(m)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.face_culling_set('NONE')

    # 判定色：整块 UI region 铺满半透明品红 —— 能看见就说明自绘叠在 N 面板上了
    rect(-60, -60, w + 120, h + 120, (1.0, 0.0, 0.8, 0.55))

    # 顶部大字，避开原生面板头部
    text(16, h - 34, "CUSTOM UI OK", 22.0, (1.0, 1.0, 1.0, 1.0))
    text(16, h - 58, "UI region %dx%d  calls=%d" % (w, h, CALLS[0]), 12.0,
         (0, 0, 0, 1))

    # 底部：原型的 composer 等价物（深色容器 + 蓝边 + 内嵌发送按钮）
    bh = 86.0
    by = 10.0
    round_rect(8, by, w - 16, bh, 8.0, (0.278, 0.447, 0.702, 1.0))
    round_rect(9, by + 1, w - 18, bh - 2, 7.0, (0.114, 0.114, 0.114, 1.0))
    text(20, by + 48, "继续描述需求，或询问下一步操作…", 11.0, (0.5, 0.5, 0.5, 1))
    bx, bcy, br = w - 32, by + 18, 13.0
    round_rect(bx - br, bcy - br, br * 2, br * 2, br, (0.45, 0.45, 0.45, 1))
    rect(bx - 4, bcy - 5, 9, 10, (1, 1, 1, 1))
    for i in range(4):                       # 斜纹把手
        round_rect(w - 16 + i * 3, by + 4 + i * 3, 2, 2, 1, (0.7, 0.7, 0.7, 1))


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


HANDLER = [None]


def tick():
    a = find_v3d()
    if a is None:
        return 2.0
    sp = a.spaces.active
    sp.show_region_ui = True
    regs = [r for r in a.regions if r.type == 'UI']
    if not regs:
        return 1.0
    reg = regs[0]
    UI_REGION[0] = reg
    try:
        reg.active_panel_category = "AI 对话"
    except Exception:
        pass
    if HANDLER[0] is None:
        HANDLER[0] = sp.draw_handler_add(draw_cb, (), 'UI', 'POST_PIXEL')
        log("handler registered, UI region = %dx%d" % (reg.width, reg.height))
    a.tag_redraw()
    return 0.4


n = [0]


def finish():
    n[0] += 1
    if n[0] < 12:
        return 0.4
    a = find_v3d()
    log("draw_cb calls =", CALLS[0])
    a.tag_redraw()
    import time
    time.sleep(0.6)

    p1 = os.path.join(OUT, "probe3_screen.png")
    bpy.ops.screen.screenshot(filepath=p1)
    log("screen.screenshot ->", os.path.getsize(p1))

    # 方式二：OpenGL viewport 渲染（会把 GPU overlay 一起烘进去）
    try:
        for ar in a.regions:
            if ar.type == 'WINDOW':
                ar.tag_redraw()
        sc = bpy.context.scene
        sc.render.resolution_x = 420
        sc.render.resolution_y = 1756
        sc.render.filepath = os.path.join(OUT, "probe3_gl.png")
        sc.render.image_settings.file_format = 'PNG'
        ui = [r for r in a.regions if r.type == 'UI'][0]
        with bpy.context.temp_override(area=a, region=ui):
            bpy.ops.render.opengl(write_still=True)
        p2 = os.path.join(OUT, "probe3_gl.png")
        log("render.opengl ->", os.path.getsize(p2) if os.path.exists(p2) else "MISS")
    except Exception as e:
        log("render.opengl FAIL", repr(e)[:120])

    log("DONE")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
bpy.app.timers.register(finish, first_interval=4.0)
log("registered")