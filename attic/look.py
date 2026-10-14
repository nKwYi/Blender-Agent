"""视觉基元：颜色令牌 + GPU 图元 + 文本。

只负责"画"，不含布局与交互。坐标是 POST_PIXEL 的设备像素，原点在区域左下角。

5.2 实测：`gpu.types.GPUShader(vert, frag)` **不能实例化**（TypeError: cannot create
'GPUShader' instances），且 builtin 的 uniform 名不是 "color"。所以一律走
`gpu.shader.from_builtin('FLAT_COLOR')` + 每顶点颜色。
"""
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

# ── 令牌 ────────────────────────────────────────────────────────────────
BG        = (0.106, 0.106, 0.114, 1.0)
CARD      = (0.145, 0.145, 0.156, 1.0)
CARD_HI   = (0.180, 0.180, 0.196, 1.0)
LINE      = (0.046, 0.046, 0.050, 1.0)
ACCENT    = (0.278, 0.447, 0.702, 1.0)
OK        = (0.42, 0.72, 0.42, 1.0)
WARN      = (0.93, 0.60, 0.13, 1.0)
BAD       = (0.86, 0.40, 0.38, 1.0)
TEXT      = (0.86, 0.86, 0.86, 1.0)
TEXT_DIM  = (0.55, 0.55, 0.55, 1.0)
TEXT_ON   = (0.96, 0.96, 0.96, 1.0)

RADIUS = 6.0
FONT = 0

_CACHE = {"shader": None}
_CLIP = [None]          # (x, y, w, h) 或 None


def _shader():
    sh = _CACHE["shader"]
    if sh is not None:
        try:
            _ = sh.name
            return sh
        except (ReferenceError, AttributeError):
            pass
    sh = gpu.shader.from_builtin('FLAT_COLOR')
    _CACHE["shader"] = sh
    return sh


def _inside(x, y, w, h):
    c = _CLIP[0]
    if c is None:
        return True
    cx, cy, cw, ch = c
    return not (x + w < cx or x > cx + cw or y + h < cy or y > cy + ch)


def begin():
    """绘制批次开始前的一次性状态设置。"""
    try:
        gpu.matrix.push()
        gpu.matrix.load_matrix(Matrix.Identity(4))
        gpu.matrix.load_translation((0, 0, 0))
        gpu.state.blend_set('ALPHA')
    except Exception:
        pass


def end():
    try:
        gpu.state.blend_set(None)
        gpu.matrix.pop()
    except Exception:
        pass


def _fill(tris, color):
    if not tris:
        return
    pos = [p for tri in tris for p in tri]
    col = [color for _ in pos]
    if len(pos) < 3:
        return
    shader = _shader()
    batch_for_shader(shader, 'TRIS', {"pos": pos, "color": col}).draw(shader)


def rect(x, y, w, h, color):
    if w <= 0 or h <= 0 or not _inside(x, y, w, h):
        return
    x2, y2 = x + w, y + h
    _fill([(x, y), (x, y2), (x2, y2), (x, y), (x2, y2), (x2, y)], color)


def round_rect(x, y, w, h, color, radius=RADIUS, segments=4):
    """三块矩形 + 四个角扇形。"""
    if w <= 0 or h <= 0 or not _inside(x, y, w, h):
        return
    import math

    r = max(0.0, min(radius, w / 2.0, h / 2.0))
    if r <= 0.5:
        rect(x, y, w, h, color)
        return
    rect(x, y + r, w, h - 2 * r, color)
    rect(x + r, y, w - 2 * r, r, color)
    rect(x + r, y + h - r, w - 2 * r, r, color)
    tris = []
    for cx, cy, a0 in ((x + r, y + r, math.pi), (x + w - r, y + r, -math.pi / 2),
                       (x + w - r, y + h - r, 0.0), (x + r, y + h - r, math.pi / 2)):
        fan = [(cx, cy)]
        for i in range(segments + 1):
            ang = a0 + (math.pi / 2) * i / segments
            fan.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for i in range(1, len(fan) - 1):
            tris += [fan[0], fan[i], fan[i + 1]]
    _fill(tris, color)


def line(x1, y1, x2, y2, width, color):
    rect(min(x1, x2), min(y1, y2), abs(x2 - x1) or width, abs(y2 - y1) or width, color)


def text(x, y, body, size=12, color=TEXT):
    if not body:
        return
    if not _inside(x, y, text_width(body, size), size + 4):
        return
    blf.position(FONT, x, y, 0)
    blf.size(FONT, size)
    blf.color(FONT, *color)
    blf.draw(FONT, str(body))


def text_width(body, size=12):
    try:
        blf.size(FONT, size)
        return blf.dimensions(FONT, str(body))[0]
    except Exception:
        return len(str(body)) * size * 0.55


def clip(x, y, w, h):
    """软裁剪：越界的图元直接跳过，不依赖 gpu.clip_set。"""
    _CLIP[0] = (x, y, w, h)


def clip_reset():
    _CLIP[0] = None


def wrap(body, max_px, size=12, max_lines=6):
    """按像素宽度折行；中文没有空格，逐字切。"""
    body = str(body or "")
    out, line_s, width = [], "", 0.0
    for ch in body:
        if ch == "\n":
            out.append(line_s)
            line_s, width = "", 0.0
            continue
        cw = text_width(ch, size)
        if width + cw > max_px and line_s:
            out.append(line_s)
            line_s, width = ch, cw
        else:
            line_s += ch
            width += cw
    if line_s:
        out.append(line_s)
    if not out:
        out = [""]
    if len(out) > max_lines:
        out = out[:max_lines]
        out[-1] = out[-1][:-1] + "…"
    return out
