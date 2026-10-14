# -*- coding: utf-8 -*-
"""probe v4：A/B 对照，定位「自绘画不出来」到底是 GPU 代码问题还是 UI region 问题。

同一套绘制代码挂两个 handler：
  A) region_type='WINDOW' + 'POST_VIEW'  —— 所有 3D 覆盖层插件的标准组合
  B) region_type='UI'     + 'POST_PIXEL' —— 想要的「画在 N 面板上」

判定：
  A 出现品红、B 不出现 -> GPU 代码没问题，是 UI region 的 POST_PIXEL 阶段不产出像素
  A、B 都不出现        -> 是截图抓不到 GPU overlay（capture 问题）
  A、B 都出现          -> 两条路都可行
"""
import os
import sys
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
LOG = os.path.join(OUT, "custom_ui_probe4.txt")
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
WIN_REGION = [None]
N = {"A": 0, "B": 0}
ERR = set()
ENABLE_A = os.environ.get("PROBE_A", "0") == "1"


def _set_color(sh, rgba):
    # Blender 5.x 的 GPUShader:
    #   uniform_float_color(4.x) 已移除 -> uniform_vector_float(location, name, value)
    #   少传 location 会 TypeError，uniform 保持默认透明黑 -> 画了等于没画
    try:
        loc = sh.attr_from_name("color")
        sh.uniform_vector_float(loc, "color", tuple(rgba))
        return True
    except Exception as e:
        log("set_color(5.x) failed:", repr(e))
    for meth in ("uniform_float_color", "uniform_4fv"):
        fn = getattr(sh, meth, None)
        if fn is not None:
            try:
                fn("color", rgba)
                return True
            except Exception:
                pass
    return False


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


_DIAG = [False]


def quad(x0, y0, x1, y1, color):
    """用 2D_COLOR builtin + 逐顶点颜色画实心矩形，完全绕开 GPUShader 的 uniform API。

    Blender 5.x 的 GPUShader 把 4.x 的 uniform_float_color 换成了
    uniform_vector_float(location, name, value)，而 builtin UNIFORM_COLOR 的
    uniform 名又不是 "color"（attr_from_name 直接报 not found）——
    uniform 这条路在 5.x 上很脆。2D_COLOR + 顶点色是无依赖的稳路。
    """
    rgba = tuple(color)
    sh = gpu.shader.from_builtin('FLAT_COLOR')
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
    cols = [rgba] * 6
    b = batch_for_shader(sh, 'TRIS', {"pos": verts, "color": cols})
    b.draw(sh)
    if not _DIAG[0]:
        _DIAG[0] = True
        log("2D_COLOR draw ok; UNIFORM_COLOR uniforms probe:")
        try:
            u = gpu.shader.from_builtin('UNIFORM_COLOR')
            log("  uniform_from_name('color') =", repr(u.uniform_from_name("color")))
        except Exception as e:
            log("  probe failed:", repr(e))


def label(x, y, s, size, color):
    blf.size(0, size)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, s)


def cb_A():
    """WINDOW + POST_VIEW：画满整个窗口的品红"""
    r = WIN_REGION[0]
    if r is None or r.width <= 0:
        return
    N["A"] += 1
    try:
        setup_gpu(r.width, r.height)
        # 全窗口铺满，超出范围保证覆盖
        quad(-200, -200, r.width + 200, r.height + 200, (1.0, 0.0, 0.8, 1.0))
        label(40, r.height - 120, "A: WINDOW+POST_VIEW", 48, (0, 0, 0, 1))
    except Exception as e:
        if "A" not in ERR:
            ERR.add("A")
            log("A ERROR", repr(e), traceback.format_exc()[-400:])


def cb_B():
    """UI + POST_PIXEL：只画在侧栏 UI region 上"""
    r = UI_REGION[0]
    if r is None or r.width <= 0:
        return
    N["B"] += 1
    try:
        setup_gpu(r.width, r.height)
        quad(-200, -200, r.width + 200, r.height + 200, (1.0, 0.0, 0.8, 1.0))
        label(20, r.height - 60, "B: UI+POST_PIXEL", 26, (0, 0, 0, 1))
    except Exception as e:
        if "B" not in ERR:
            ERR.add("B")
            log("B ERROR", repr(e), traceback.format_exc()[-400:])


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
    wregs = [r for r in a.regions if r.type == 'WINDOW']
    if not uregs or not wregs:
        return 1.0
    UI_REGION[0] = uregs[0]
    WIN_REGION[0] = wregs[0]
    try:
        uregs[0].active_panel_category = "AI 对话"
    except Exception:
        pass
    if not H:
        # ENABLE_A = False -> 只挂 UI+POST_PIXEL，用来单独验证「能不能只画在 N 面板上」
        if ENABLE_A:
            H['A'] = sp.draw_handler_add(cb_A, (), 'WINDOW', 'POST_VIEW')
        H['B'] = sp.draw_handler_add(cb_B, (), 'UI', 'POST_PIXEL')
        log("A=%s B=UI+POST_PIXEL  UI=%dx%d WIN=%dx%d" % (
            bool(ENABLE_A), uregs[0].width, uregs[0].height,
            wregs[0].width, wregs[0].height))
    a.tag_redraw()
    return 0.4


n = [0]


def finish():
    n[0] += 1
    if n[0] < 12:
        return 0.4
    a = find_v3d()
    log("calls A=%d B=%d" % (N["A"], N["B"]))
    a.tag_redraw()
    # 强制带 swap 的重绘，确保 overlay 进入前台缓冲
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=3)
        log("forced DRAW_WIN_SWAP")
    except Exception as e:
        log("redraw_timer fail", repr(e))
    p = os.path.join(OUT, "probe4_screen.png")
    bpy.ops.screen.screenshot(filepath=p)
    log("shot", os.path.getsize(p))
    log("DONE")
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=1.0)
bpy.app.timers.register(finish, first_interval=4.0)
log("registered")