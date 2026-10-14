# -*- coding: utf-8 -*-
"""probe v5：最终视觉验证 —— 用 GPU 自绘把原型的 composer 直接叠在原生 N 面板之上。

已实测确认的能力（Blender 5.2 / blender5.2）：
  region_type='UI' + draw_type='POST_PIXEL'  ->  绘制精确落在 N 面板 region 上
  builtin shader 名单：FLAT_COLOR / SMOOTH_COLOR / UNIFORM_COLOR（没有 2D_COLOR）
  FLAT_COLOR + 逐顶点颜色                   ->  绕开 GPUShader 的 uniform API
  2D 正交矩阵（左下原点）                   ->  还原像素坐标系
  blf 文字                                  ->  任意字号
"""
import os
import sys
import math
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "custom_ui_probe5.txt")
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

UI_REGION = [None]
N = [0]
ERR = [False]

# 原型配色
C_FOCUS = (0.278, 0.447, 0.702, 1.0)     # #4772b3 聚焦蓝边
C_INBOX = (0.114, 0.114, 0.114, 1.0)      # #1d1d1d 深色容器
C_BORDER = (0.239, 0.239, 0.239, 1.0)    # #3d3d3d 常态边框
C_TEXT = (0.72, 0.72, 0.72, 1.0)
C_PH = (0.42, 0.42, 0.42, 1.0)
C_SEND = (0.278, 0.447, 0.702, 1.0)
C_GRIP = (0.62, 0.62, 0.62, 1.0)


def setup_gpu(w, h):
    gpu.matrix.load_matrix(Matrix.Identity(4))
    m = Matrix.Identity(4)
    m[0][0] = 2.0 / float(w)
    m[1][1] = 2.0 / float(h)
    m[0][3] = -1.0
    m[1][3] = -1.0
    gpu.matrix.load_projection_matrix(m)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.face_culling_set('NONE')


def tris(pos, col):
    sh = gpu.shader.from_builtin('FLAT_COLOR')
    b = batch_for_shader(sh, 'TRIS', {"pos": pos, "color": [col] * len(pos)})
    b.draw(sh)


def box(x, y, w, h, c):
    tris([(x, y), (x + w, y), (x + w, y + h),
          (x, y), (x + w, y + h), (x, y + h)], c)


def round_box(x, y, w, h, r, c, seg=7):
    r = min(r, w * 0.5, h * 0.5)
    verts = []
    for ox, oy, a0 in [(x + w - r, y + r, -math.pi * 0.5),
                       (x + w - r, y + h - r, 0.0),
                       (x + r, y + h - r, math.pi * 0.5),
                       (x + r, y + r, math.pi)]:
        for i in range(seg + 1):
            a = a0 + (math.pi * 0.5) * i / seg
            verts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    cx, cy = x + w * 0.5, y + h * 0.5
    pos = []
    for i in range(len(verts)):
        p, q = verts[i], verts[(i + 1) % len(verts)]
        pos += [(cx, cy), p, q]
    sh = gpu.shader.from_builtin('FLAT_COLOR')
    b = batch_for_shader(sh, 'TRIS', {"pos": pos, "color": [c] * len(pos)})
    b.draw(sh)


def text(x, y, s, size, c, font=0):
    blf.size(font, size)
    blf.color(font, *c)
    blf.position(font, x, y, 0)
    blf.draw(font, s)


def draw_cb():
    try:
        _inner()
    except Exception as e:
        if not ERR[0]:
            ERR[0] = True
            log("DRAW ERROR", repr(e))
            log(traceback.format_exc()[-500:])


def _inner():
    r = UI_REGION[0]
    if r is None or r.width <= 0:
        return
    N[0] += 1
    w, h = r.width, r.height
    setup_gpu(w, h)

    # 顶部标题条，说明这是自绘层
    box(0, h - 40, w, 40, (0.10, 0.12, 0.16, 0.95))
    text(12, h - 27, "GPU 自绘层 (UI + POST_PIXEL)", 13, (0.45, 0.62, 0.86, 1))
    text(12, h - 27, "  draw #%d" % N[0], 11, (0.55, 0.55, 0.55, 1))

    # ===== 原型 composer：.inwrap =====
    cw = w - 16
    cx0, cy0, ch = 8, 16, 88
    round_box(cx0, cy0, cw, ch, 6, C_BORDER)          # 常态边框底
    round_box(cx0 + 1.5, cy0 + 1.5, cw - 3, ch - 3, 5, C_INBOX)

    # 聚焦蓝边（focus-within 等价物）—— 画在左上两角做出「正在输入」的强调
    round_box(cx0, cy0, cw, ch, 6, C_FOCUS)
    round_box(cx0 + 2, cy0 + 2, cw - 4, ch - 4, 4.5, C_INBOX)

    # placeholder
    text(cx0 + 12, cy0 + 52, "继续描述需求，或询问下一步操作…", 11, C_PH)

    # 右下角斜纹把手 .grip（18x18，nwse-resize）
    for i in range(4):
        for j in range(4 - i):
            round_box(cx0 + cw - 6 - i * 4 - j * 4, cy0 + 5 + i * 4,
                      2.4, 2.4, 1.2, C_GRIP)

    # 内嵌发送按钮 .send（26x26，圆角 3）
    s = 26.0
    bx = cx0 + cw - s - 9
    by = cy0 + ch - s - 9
    round_box(bx, by, s, s, 3, C_SEND)
    tris([(bx + 10, by + 7), (bx + 10, by + 19), (bx + 19, by + 13)],
         (1, 1, 1, 1))

    # 焦点光标，演示「文本输入也要自己做」这一点
    box(cx0 + 12, cy0 + 26, 1.2, 14, (0.85, 0.88, 0.95, 1))


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


H = {}


def tick():
    a = find_v3d()
    if a is None:
        return 2.0
    sp = a.spaces.active
    sp.show_region_ui = True
    uregs = [r for r in a.regions if r.type == 'UI']
    if not uregs:
        return 1.0
    UI_REGION[0] = uregs[0]
    try:
        uregs[0].active_panel_category = "AI 对话"
    except Exception:
        pass
    if not H:
        H['x'] = sp.draw_handler_add(draw_cb, (), 'UI', 'POST_PIXEL')
        log("handler registered UI=%dx%d" % (uregs[0].width, uregs[0].height))
    a.tag_redraw()
    return 0.4


n = [0]


def finish():
    n[0] += 1
    if n[0] < 12:
        return 0.4
    a = find_v3d()
    log("draw calls =", N[0])
    a.tag_redraw()
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=3)
    except Exception:
        pass
    p = os.path.join(OUT, "probe5_screen.png")
    bpy.ops.screen.screenshot(filepath=p)
    log("shot", os.path.getsize(p))
    log("DONE")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
bpy.app.timers.register(finish, first_interval=4.0)
log("registered")