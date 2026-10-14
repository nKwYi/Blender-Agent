"""自绘 UI 的 GPU 底层。

分工：
  * 显示列表（display list）—— 布局阶段产出的纯数据，只用「左上角原点」的逻辑坐标，
    既能直接绘制，也能直接做命中测试。不在绘制里做布局，否则鼠标判定无从下手。
  * Painter —— 把显示列表翻译成 gpu/batch/blf 调用。坐标在这里才翻成左下原点。

Blender 5.x 的三个硬约束（踩过才知道）：
  * gpu.matrix.load_ortho_mtx 不存在，必须手搓 2D 正交矩阵
  * gpu.state.blend_set 用 'ALPHA'，没有 'BLEND'
  * GPUShader.uniform_float_color 已改名 uniform_vector_float(location, name, v)，
    而 builtin UNIFORM_COLOR 的 uniform 名又不是 "color" —— 一律走 FLAT_COLOR + 顶点色
"""
import math

import blf
import gpu
from mathutils import Matrix

from gpu_extras.batch import batch_for_shader

FONT = 0
_SHADER = {"flat": None}       # builtin shader 的 Python 包装，缓存一次就够

# 显示列表的 op 约定（y 一律是「距离顶边」，绘制时才翻转）：
#   rect    x y w h radius color
#   border  x y w h radius width color
#   line    x1 y1 x2 y2 width color
#   text    x y s size color            y 为该行文字盒顶边
#   icon    name x y size color
#   hit     x y w h action_id
#   clip    x y w h      —— 后续 item 只在裁剪框内画（整块跳过，不做半像素裁剪）
#   unclip


# --------------------------------------------------------------------------
# 文本度量
# --------------------------------------------------------------------------
def text_width(s, size):
    """字符串像素宽。blf.dimensions 依赖当前 size，必须先设。"""
    if not s:
        return 0.0
    blf.size(FONT, size)
    w, _h = blf.dimensions(FONT, s)
    return float(w)


def _is_cjk(ch):
    o = ord(ch)
    return (0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF
            or 0x20000 <= o <= 0x2A6DF)


def wrap(s, size, max_w):
    """按像素宽度折行。中文任意断行，拉丁单词尽量不拆。"""
    if not s:
        return [""]
    out = []
    for para in s.split("\n"):
        if not para:
            out.append("")
            continue
        line = ""
        i = 0
        n = len(para)
        while i < n:
            ch = para[i]
            trial = line + ch
            if text_width(trial, size) <= max_w or not line:
                line = trial
                i += 1
                continue
            # 溢出了：在最近的拉丁词边界断，否则硬断
            if not _is_cjk(ch) and ch not in " ,.，。、：；）)】]":
                cut = line.rfind(" ")
                if cut > len(line) * 0.5:
                    out.append(line[:cut])
                    line = line[cut + 1:] + ch
                    i += 1
                    continue
            out.append(line)
            line = ch
            i += 1
        out.append(line)
    return out


def ellipsize(s, size, max_w):
    """超宽时截断并补省略号。"""
    if text_width(s, size) <= max_w:
        return s
    ell = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(s[:mid] + ell, size) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ell


_ASCENT = {}             # size -> 上伸部像素高


def _ascent(size):
    """基线到字顶的距离（像素）。

    blf 在 5.x 也没有暴露 ascent 接口（没有 blf.metrics），只能拿参考字形量：
    'H' 的大写高度在 Blender 内置字体里约等于 0.72 * size，够稳且随字号线性。
    必须自己算 —— blf.dimensions 返回的是 (宽, 高)，把宽当成 ascent 用的话
    整版文字会往上飘将近一整行（13px 字号下量到 18，用上去文字就浮了 9px）。
    """
    a = _ASCENT.get(size)
    if a is None:
        try:
            blf.size(FONT, size)
            a = float(blf.dimensions(FONT, "H")[1])
        except Exception:
            a = 0.0
        if a <= 0.0:
            a = size * 0.72
        _ASCENT[size] = a
    return a


# --------------------------------------------------------------------------
# 绘图器
# --------------------------------------------------------------------------
def _flat_shader():
    """FLAT_COLOR 只取一次。

    from_builtin 返回的是 builtin 表里的单例，但每批都调一次仍要过一遍
    Python->C 的名字查找和包装构造 —— 一帧几百批，缓存起来白赚。
    万一缓存里的包装在某个上下文里失效了，退回原来的取法，不影响正确性。
    """
    sh = _SHADER["flat"]
    if sh is None:
        sh = gpu.shader.from_builtin('FLAT_COLOR')
        _SHADER["flat"] = sh
        return sh
    try:
        _ = sh.name
    except (ReferenceError, AttributeError):
        sh = gpu.shader.from_builtin('FLAT_COLOR')
        _SHADER["flat"] = sh
    return sh


class Painter(object):
    def __init__(self, w, h):
        self.w = float(w)
        self.h = float(h)
        # 两个并行列表：_pos 是 (x, y)，_col 是 (r, g, b, a)。
        # 曾经把顶点压成 (x, y, color) 再用 [0::2]/[1::2] 切片，color 会变成嵌套
        # 元组，attr_fill 直接报 "must be real number, not tuple"。
        self._pos = []
        self._col = []

    # -- 状态 ---------------------------------------------------------------
    def begin(self):
        gpu.matrix.load_matrix(Matrix.Identity(4))
        m = Matrix.Identity(4)
        m[0][0] = 2.0 / self.w
        m[1][1] = 2.0 / self.h
        m[0][3] = -1.0
        m[1][3] = -1.0
        gpu.matrix.load_projection_matrix(m)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.face_culling_set('NONE')

    def _gy(self, y):
        """逻辑 y（距顶）-> GPU y（距底）。"""
        return self.h - y

    def _flush(self):
        if self._pos:
            sh = _flat_shader()
            b = batch_for_shader(sh, 'TRIS',
                                 {"pos": self._pos, "color": self._col})
            b.draw(sh)
        self._pos = []
        self._col = []

    def _poly(self, pts, color):
        """pts 是 [(x, 逻辑y), ...]，扇形三角化后压入批次。"""
        if len(pts) < 3:
            return
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        gy = [self._gy(p[1]) for p in pts]
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            self._pos.append((cx, self._gy(cy)))
            self._col.append(color)
            self._pos.append((pts[i][0], gy[i]))
            self._col.append(color)
            self._pos.append((pts[j][0], gy[j]))
            self._col.append(color)

    def _quad(self, x, y, w, h, color):
        # 两个三角形拼接成实心矩形： (0, 1, 2) 与 (0, 2, 3)
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        gy = [self._gy(p[1]) for p in pts]
        for idx in (0, 1, 2, 0, 2, 3):
            self._pos.append((pts[idx][0], gy[idx]))
            self._col.append(color)

    # -- 图元 ---------------------------------------------------------------
    def rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        self._quad(x, y, w, h, color)

    def round_rect(self, x, y, w, h, r, color, seg=6):
        """圆角矩形。r<=0 退化成直角。"""
        if w <= 0 or h <= 0:
            return
        r = min(r, w * 0.5, h * 0.5)
        if r <= 0.4:
            self.rect(x, y, w, h, color)
            return
        cx, cy = x + w * 0.5, y + h * 0.5
        # 四段角弧按轮廓顺序拼成一条闭合折线，再从形心一次扇形三角化。
        # 原来是「每段弧各自朝形心扇一次」：四片扇形只覆盖四个角，矩形中间
        # 是空的 —— r 比 w/2、h/2 小的时候中间那块的洞比整张卡片还大。
        # 圆角矩形是凸的，形心必在内部，一次扇形三角化保证铺满。
        pts = []
        for ox, oy, a0 in ((x + w - r, y + h - r, 0.0),
                           (x + r, y + h - r, math.pi * 0.5),
                           (x + r, y + r, math.pi),
                           (x + w - r, y + r, math.pi * 1.5)):
            for i in range(seg + 1):
                a = a0 + (math.pi * 0.5) * i / seg
                pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
        self._poly(pts, color)

    def border(self, x, y, w, h, r, width, color):
        """圆角描边，委派给模块级 _ring_rect（单一实现，避免两处走偏）。

        _ring_rect 定义在类体之后并不影响调用：名字是在**调用时**才去模块全局里查，
        而 render()/draw_icon() 只会在模块导入完成后才被调用，那时函数已经存在了。
        """
        _ring_rect(self, x, y, w, h, r, width, color)

    def circle(self, cx, cy, r, color, seg=16):
        pts = [(cx, cy)]
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self._poly(pts, color)

    def ring(self, cx, cy, r, width, color, seg=16):
        ro, ri = r, max(0.0, r - width)
        for i in range(seg):
            a1 = 2 * math.pi * i / seg
            a2 = 2 * math.pi * (i + 1) / seg
            self._poly([(cx, cy),
                        (cx + ro * math.cos(a1), cy + ro * math.sin(a1)),
                        (cx + ro * math.cos(a2), cy + ro * math.sin(a2)),
                        (cx + ri * math.cos(a2), cy + ri * math.sin(a2)),
                        (cx + ri * math.cos(a1), cy + ri * math.sin(a1))], color)

    def line(self, x1, y1, x2, y2, width, color):
        """有限宽度的线段（胶囊）。"""
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy)
        if d < 0.01:
            return
        nx, ny = -dy / d * width * 0.5, dx / d * width * 0.5
        self._poly([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                    (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], color)

    def polyline(self, pts, width, color):
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], width, color)

    def end(self):
        self._flush()

    # -- 文本 ---------------------------------------------------------------
    def text(self, x, y, s, size, color):
        """y 是文字盒顶边。"""
        if not s:
            return
        blf.size(FONT, size)
        blf.color(FONT, color[0], color[1], color[2], color[3])
        # y 是盒顶（逻辑坐标，距顶），_gy() 翻成 GPU 底原点后盒顶在 h - y。
        # 基线在字顶「下方」ascent 处，而底原点 Y 轴朝上，所以必须**减**。
        # 写成 + 会让全版文字上浮 2*ascent（11px 字号约 16px）——页签撞原生头、
        # 胶囊文字跑出框外、按钮文字浮在渐变之上，全是这一个符号造成的。
        blf.position(FONT, x, self._gy(y) - _ascent(size), 0)
        blf.draw(FONT, s)

    def text_vcenter(self, x, y_mid, s, size, color):
        """y_mid 是盒子的垂直中心。"""
        if not s:
            return
        self.text(x, y_mid - _ascent(size) * 0.5, s, size, color)


# --------------------------------------------------------------------------
# 图标：矢量图元拼装，不依赖外部资源
# --------------------------------------------------------------------------
def draw_icon(p, name, x, y, s, color, *rest):
    """x, y = 图标盒左上角；s = 边长。

    多余的位置参数一律忽略。显示列表的 icon 约定是 (name, x, y, s, color) 五个字段，
    但调用点曾经多传了一个 it[6]，直接 IndexError 把**每一帧**画崩在第一个图标上 ——
    画面上只剩前面已经画完的面板底色。现在用 *rest 兼容多余的字段，
    宁可忽略也不让单条 item 炸掉整帧。
    """
    u = s / 24.0                      # SVG viewBox 是 24x24
    X = lambda v: x + v * u          # noqa: E731
    Y = lambda v: y + v * u          # noqa: E731
    t = max(1.0, 2.0 * u)

    if name == "caret":               # 展开三角
        p._poly([(X(12), Y(5)), (X(19), Y(12)), (X(5), Y(12))], color)
    elif name == "caret_right":
        p._poly([(X(6), Y(4)), (X(17), Y(12)), (X(6), Y(20))], color)
    elif name == "send":              # 实心纸飞机
        p._poly([(X(21), Y(3)), (X(3), Y(10.5)), (X(10), Y(13.3)),
                 (X(12.8), Y(20.3))], color)
        p._poly([(X(21), Y(3)), (X(10), Y(13.3)), (X(12.8), Y(20.3))],
                (color[0], color[1], color[2], max(0.0, color[3] * 0.55)))
    elif name == "person":            # 圆头 + 肩
        p.circle(X(12), Y(8), 4 * u, color, 14)
        p._poly([(X(4), Y(21)), (X(6.2), Y(15.4)), (X(17.8), Y(15.4)),
                 (X(20), Y(21))], color)
    elif name == "ai":                # 两个人形，和 person 区分开
        p.circle(X(9), Y(8), 3.4 * u, color, 12)
        p._poly([(X(2.5), Y(20)), (X(4.2), Y(14.4)), (X(13.8), Y(14.4)),
                 (X(15.5), Y(20))], color)
        p.circle(X(17), Y(9), 2.6 * u, color, 12)
        p._poly([(X(15.2), Y(14.8)), (X(17), Y(13.4)), (X(21.5), Y(14.4)),
                 (X(21.5), Y(20))], color)
    elif name == "undo":
        p.ring(X(12), Y(12), 8.5 * u, t, color, 20)
        p.rect(X(2.5), Y(6), 7 * u, t, color)
        p._poly([(X(3), Y(6)), (X(9), Y(3)), (X(9), Y(9))], color)
    elif name == "plus":
        p.rect(X(11) - t * 0.5, Y(4), t, 16 * u, color)
        p.rect(X(4), Y(11) - t * 0.5, 16 * u, t, color)
    elif name == "trash":
        p.rect(X(3), Y(6), 18 * u, t, color)
        p.rect(X(8), Y(3), 8 * u, t, color)
        p.polyline([(X(6), Y(9)), (X(7.2), Y(21)), (X(16.8), Y(21)), (X(18), Y(9))], t, color)
    elif name == "layers":
        p.polyline([(X(12), Y(3)), (X(21), Y(7.5)), (X(12), Y(12)), (X(3), Y(7.5)),
                    (X(12), Y(3))], t, color)
        p.polyline([(X(3), Y(12)), (X(12), Y(16.5)), (X(21), Y(12))], t, color)
        p.polyline([(X(3), Y(16.5)), (X(12), Y(21)), (X(21), Y(16.5))], t, color)
    elif name == "cube":
        p.polyline([(X(12), Y(2.5)), (X(21), Y(7)), (X(12), Y(11.5)), (X(3), Y(7)),
                    (X(12), Y(2.5))], t, color)
        p.polyline([(X(3), Y(7)), (X(3), Y(16.5))], t, color)
        p.polyline([(X(21), Y(7)), (X(21), Y(16.5))], t, color)
        p.polyline([(X(3), Y(16.5)), (X(12), Y(21)), (X(21), Y(16.5))], t, color)
    elif name == "sphere":
        p.ring(X(7), Y(15), 4.2 * u, t, color, 16)
        p.line(X(10), Y(12.5), X(19), Y(4), t, color)
        p.ring(X(19.5), Y(4), 2.4 * u, t, color, 12)
    elif name == "check":
        p.polyline([(X(20), Y(6)), (X(9), Y(17)), (X(4), Y(12))], t * 1.3, color)
    elif name == "doc":
        p.polyline([(X(14), Y(2.5)), (X(6), Y(2.5)), (X(6), Y(21.5)), (X(18), Y(21.5)),
                    (X(18), Y(8)), (X(14), Y(2.5))], t, color)
        p.polyline([(X(14), Y(2.5)), (X(14), Y(8)), (X(18), Y(8))], t, color)
    elif name == "dots":
        for vx in (7, 12, 17):
            p.circle(X(vx), Y(12), 1.7 * u, color, 10)
    elif name == "chevron":           # 折叠箭头（旋转 -90）
        p._poly([(X(5), Y(9)), (X(12), Y(16)), (X(19), Y(9))], color)
    elif name == "film":
        p.rect(X(3), Y(5), 18 * u, 14 * u, color)
    elif name == "info":
        p.circle(X(12), Y(12), 9 * u, color, 18)
    return p


# --------------------------------------------------------------------------
# 显示列表渲染 + 命中测试
# --------------------------------------------------------------------------
STATS = {"items": 0, "ops": {}, "batches": 0, "tris": 0,
         "idx": -1, "op": "", "err": ""}


def render(painter, items):
    """把显示列表画出来。clip 用「整块跳过」实现，避免依赖各版本 scissor。"""
    STATS["idx"] = -1
    STATS["op"] = "begin"
    try:
        _render(painter, items)
    except Exception as e:
        # 记录炸在第几条 item 上，再原样抛给 runtime 的日志。
        # 只在失败路径付出代价，正常帧没有任何额外开销。
        STATS["err"] = "idx=%d op=%s: %r" % (STATS["idx"], STATS["op"], e)
        raise
    else:
        STATS["err"] = ""


def _render(painter, items):
    painter.begin()
    clip = None
    STATS["items"] = len(items)
    for i, it in enumerate(items):
        op = it[0]
        STATS["idx"] = i
        STATS["op"] = op
        STATS["ops"][op] = STATS["ops"].get(op, 0) + 1
        if op == "clip":
            clip = it[1:]
            continue
        if op == "unclip":
            clip = None
            continue
        # clip：整块跳过。不同 op 的几何字段位置不一样，必须按 op 自己算包围盒。
        # 当年把 circ/ring 也当成 (x, y, w, h) 直接取 it[1..4]，可 circ 是
        # (cx, cy, r, color)、ring 是 (cx, cy, r, width, color) —— it[4] 取到的
        # 是颜色元组，于是 y + h 变成 float + tuple，每一帧画到裁剪区里的圆就崩。
        if clip is not None:
            box = _bbox(op, it)
            if box is not None:
                x, y, w, h = box
                cx, cy, cw, ch = clip
                if x + w < cx or x > cx + cw or y + h < cy or y > cy + ch:
                    continue

        if op == "rect":
            painter.round_rect(it[1], it[2], it[3], it[4], it[5], it[6])
        elif op == "border":
            _ring_rect(painter, it[1], it[2], it[3], it[4], it[5], it[6], it[7])
        elif op == "line":
            painter.line(it[1], it[2], it[3], it[4], it[5], it[6])
        elif op == "text":
            painter.text(it[1], it[2], it[3], it[4], it[5])
        elif op == "icon":
            # 整包转发：draw_icon 对多余字段是宽容的（*rest），这里不能按位取，
            # it[6] 越界会让整帧在第一个图标处死掉。
            draw_icon(painter, *it[1:])
        elif op == "circ":
            painter.circle(it[1], it[2], it[3], it[4])
        elif op == "ring":
            painter.ring(it[1], it[2], it[3], it[4], it[5])
        STATS["batches"] += 1
        STATS["tris"] += len(painter._pos) // 3
        painter._flush()
    painter.end()


def _bbox(op, it):
    """op 在逻辑坐标里的包围盒 (x, y, w, h)；不需要裁剪的 op 返回 None。

    字段位置按显示列表约定逐个 op 来，不能想当然认为前四项就是 x y w h：
      rect   x y w h r color
      border x y w h r width color
      hit    x y w h action
      circ   cx cy r color      <- 第 4 项是颜色，不是 h
      ring   cx cy r width color
    """
    if op in ("rect", "border", "hit"):
        return (it[1], it[2], it[3], it[4])
    if op in ("circ", "ring"):
        r = it[3]
        return (it[1] - r, it[2] - r, 2.0 * r, 2.0 * r)
    return None


def _ring_rect(p, x, y, w, h, r, width, color):
    """圆角矩形描边。

    必须由「四条边 + 四个角弧」拼出来，不能先填实心再用透明色挖内芯 ——
    alpha 混合下 (0,0,0,0) 是彻底的空操作，整个矩形会保持边框色。
    """
    i = min(width, w * 0.5, h * 0.5)
    if i <= 0 or w <= 0 or h <= 0:
        return
    r = min(r, w * 0.5, h * 0.5)
    if r <= 0.4:
        p.rect(x, y, w, i, color)
        p.rect(x, y + h - i, w, i, color)
        p.rect(x, y + i, i, h - 2 * i, color)
        p.rect(x + w - i, y + i, i, h - 2 * i, color)
        return
    if i >= r:
        # 描边比圆角半径还粗：内圈半径 r-i 变负数，角弧会甩到对侧去画出一圈尖刺。
        # 这种情况下「环」已经退化成实心，直接实心圆角矩形。
        p.round_rect(x, y, w, h, r, color)
        return
    p.rect(x + r, y, w - 2 * r, i, color)                     # 上
    p.rect(x + r, y + h - i, w - 2 * r, i, color)             # 下
    p.rect(x, y + r, i, h - 2 * r, color)                     # 左
    p.rect(x + w - i, y + r, i, h - 2 * r, color)             # 右
    for cx, cy, a0 in ((x + w - r, y + h - r, 0.0),
                       (x + r, y + h - r, math.pi * 0.5),
                       (x + r, y + r, math.pi),
                       (x + w - r, y + r, math.pi * 1.5)):
        for k in range(7):
            a1 = a0 + (math.pi * 0.5) * k / 6.0
            a2 = a0 + (math.pi * 0.5) * (k + 1) / 6.0
            p._poly([(cx, cy),
                     (cx + r * math.cos(a1), cy + r * math.sin(a1)),
                     (cx + (r - i) * math.cos(a1), cy + (r - i) * math.sin(a1)),
                     (cx + (r - i) * math.cos(a2), cy + (r - i) * math.sin(a2)),
                     (cx + r * math.cos(a2), cy + r * math.sin(a2))], color)


def hit_test(items, mx, my):
    """返回命中的 action_id。倒序扫描：后绘制的在上层，先命中的是它。

    原型的把手(.grip)和发送按钮(.send)在右下角本来就有重叠，
    发送是主操作，必须由后绘制的 send 拿到。
    """
    clip = None
    order = []
    for it in items:
        op = it[0]
        if op == "clip":
            clip = it[1:]
            continue
        if op == "unclip":
            clip = None
            continue
        if op != "hit":
            continue
        x, y, w, h, action = it[1], it[2], it[3], it[4], it[5]
        if not (x <= mx <= x + w and y <= my <= y + h):
            continue
        if clip is not None:
            cx, cy, cw, ch = clip
            if not (cx <= mx <= cx + cw and cy <= my <= cy + ch):
                continue
        order.append(action)
    return order[-1] if order else None