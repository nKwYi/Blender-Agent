# -*- coding: utf-8 -*-
"""可行性验证 v2：完全绕开 UILayout，用 gpu + blf + draw_handler 在 N 面板上画自定义控件。

v1 的三个错误（导致截图里什么都看不到）：
  1. region_type 用了 'WINDOW' —— 那是在整个 area 的 window region 上画，不是 UI region
  2. 传给 draw_handler 的 args 是 UI region，但 'WINDOW' 期望的是 window region，类型错配
  3. 没设 gpu.matrix，POST_PIXEL 的投影矩阵被 3D 视口的相机矩阵覆盖，顶点坐标全错

v2 要回答的问题只有一个：
  「自绘控件到底能不能落在 N 面板上、能不能压在 UILayout 面板上面」

判定方法：整块 region 铺满亮品红 + 大字标题。
  - 看到品红  -> 自绘可行
  - 没看到    -> 自绘不可行（这条路直接废掉）
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "custom_ui_probe2.txt")
lines = []


def log(*a):
    lines.append(" ".join(str(x) for x in a))
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


import blf                                                # noqa: E402
import gpu                                                # noqa: E402
from mathutils import Matrix                              # noqa: E402
from gpu_extras.batch import batch_for_shader             # noqa: E402

log("blf ok, gpu ok")

# ---- 0. 先枚举：哪些 Space 类型支持 draw_handler_add -------------------------
sup = []
for nm in dir(bpy.types):
    t = getattr(bpy.types, nm, None)
    if t is not None and hasattr(t, "draw_handler_add"):
        sup.append(nm)
log("spaces supporting draw_handler_add:", ",".join(sorted(sup)))

# ---- 1. 注册真实 addon，让 "AI 对话" 分类存在 --------------------------------
import blender_deepseek_agent as bda                      # noqa: E402
if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
    log("addon registered")

FONT = 0
STATE = {"region": None, "handler": None, "rect": None, "calls": 0, "w": 0, "h": 0}
MODE = ["UI"]  # 依次试 'UI' -> 'WINDOW'


def rect(x, y, w, h, color):
    """铺一个实心矩形（GPU 像素坐标，左下原点）。"""
    verts = [(x, y), (x + w, y), (x + w, y + h),
             (x, y), (x + w, y + h), (x, y + h)]
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    b = batch_for_shader(sh, 'TRIS', {"pos": verts})
    sh.uniform_float_color("color", color)
    b.draw(sh)


def round_rect(x, y, w, h, r, color, seg=6):
    """圆角矩形：四角各一段弧，中心三角扇。"""
    import math
    verts = [(x + w * 0.5, y + h * 0.5)]
    corners = [
        (x + w - r, y + r, -math.pi * 0.5),          # 右下
        (x + w - r, y + h - r, 0.0),                 # 右上
        (x + r, y + h - r, math.pi * 0.5),           # 左上
        (x + r, y + r, math.pi),                     # 左下
    ]
    for ox, oy, a0 in corners:
        for i in range(seg + 1):
            a = a0 + (math.pi * 0.5) * i / seg
            verts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    sh = gpu.shader.from_builtin('UNIFORM_COLOR')
    b = batch_for_shader(sh, 'TRIS', {"pos": verts})
    sh.uniform_float_color("color", color)
    b.draw(sh)


def text(x, y, s, size, color):
    blf.size(FONT, size)
    blf.color(FONT, *color)
    blf.position(FONT, x, y, 0)
    blf.draw(FONT, s)


def draw_cb():
    """POST_PIXEL 回调。

    关键实测结论：SpaceView3D.draw_handler_add 的回调 **不接收 region 参数**，
    当前 region 必须从 `bpy.context.region_data` 取。v2 里按 region_type='UI'
    注册成功但回调签名带 region，直接 TypeError 刷屏 —— 这就是 v1「注册成功
    却什么都看不见」的第二个隐藏原因。
    """
    region = bpy.context.region_data
    if region is None:
        return
    STATE["calls"] += 1
    STATE["w"], STATE["h"] = region.width, region.height
    w, h = region.width, region.height
    if w <= 0 or h <= 0:
        return

    # >>> 关键：v1 漏了这三行，顶点被相机矩阵吃掉，所以什么都看不见 <<<
    gpu.matrix.load_matrix(Matrix.Identity(4))
    gpu.matrix.load_projection_matrix(Matrix.Identity(4))
    gpu.state.blend_set('BLEND')
    gpu.state.depth_test_set('NONE')
    gpu.state.face_culling_set('NONE')

    # 1) 判定色：整块 region 铺满亮品红
    rect(0, 0, w, h, (1.0, 0.0, 0.8, 1.0))

    # 2) 原型等价物：深色输入容器 + 蓝色聚焦边
    bh = 92.0
    by = h - bh - 8
    round_rect(8, by, w - 16, bh, 8.0, (0.278, 0.447, 0.702, 1.0))
    round_rect(9, by + 1, w - 18, bh - 2, 7.0, (0.114, 0.114, 0.114, 1.0))
    text(18, by + 48, "继续描述需求，或询问下一步操作…", 11.0, (0.45, 0.45, 0.45, 1.0))

    # 3) 圆角发送按钮
    bx, bcy, br = w - 30, by + 18, 13.0
    round_rect(bx - br, bcy - br, br * 2, br * 2, br, (0.42, 0.42, 0.42, 1.0))
    rect(bx - 4, bcy - 5, 9, 10, (1, 1, 1, 1))

    # 4) 大字标题，方便肉眼确认
    text(20, h - 60, "CUSTOM UI OK", 26.0, (1.0, 1.0, 1.0, 1.0))
    text(20, h - 90, "region %dx%d  mode=%s" % (w, h, MODE[0]), 12.0,
         (0.0, 0.0, 0.0, 1.0))


def find_v3d():
    for w_ in bpy.context.window_manager.windows:
        for a in w_.screen.areas:
            if a.type == 'VIEW_3D':
                return a
    return None


step = [0]


def tick():
    area = find_v3d()
    if area is None:
        return 2.0
    area.spaces.active.show_region_ui = True
    regs = [r for r in area.regions if r.type == 'UI']
    if not regs:
        return 1.0
    reg = regs[0]

    # 打开侧栏并切到 "AI 对话"，首次会因未布局报 read-only，必须每 tick 重试
    try:
        reg.active_panel_category = "AI 对话"
    except Exception:
        pass

    if STATE["handler"] is None:
        try:
            STATE["handler"] = area.spaces.active.draw_handler_add(
                draw_cb, (), MODE[0], 'POST_PIXEL')
            STATE["region"] = reg
            log("handler registered mode=%s region=%dx%d" % (MODE[0], reg.width, reg.height))
        except Exception as e:
            log("register FAIL mode=%s: %r" % (MODE[0], e))

    step[0] += 1
    area.tag_redraw()
    if step[0] < 4:
        return 0.8

    # 记录 region 在窗口里的绝对矩形，供事后裁剪
    try:
        r = STATE["region"] or reg
        x, y = r.x, r.y
        log("region abs rect x=%s y=%s w=%s h=%s" % (x, y, r.width, r.height))
    except Exception as e:
        log("rect fail", e)

    p = os.path.join(OUT, "custom_ui_probe2.png")
    log("draw_cb invoked %d times, last region=%sx%s" %
        (STATE["calls"], STATE["w"], STATE["h"]))
    bpy.ops.screen.screenshot(filepath=p)
    log("shot", p, os.path.getsize(p))
    log("DONE")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
_wd = [0]


def wd():
    _wd[0] += 1
    if _wd[0] > 40:
        bpy.ops.wm.quit_blender()
        return None
    return 0.5


bpy.app.timers.register(wd, first_interval=0.5)
log("registered")