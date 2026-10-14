"""自绘面板的布局构建器。

把运行态翻译成「显示列表」——一串带矩形坐标的纯数据。好处：
  * 绘制和命中测试读同一份数据，鼠标判定永远不会和画出来的东西对不上
  * 可以在无头模式里直接断言布局（见 dev/test_panel_layout.py）

坐标系统一用「左上角原点、y 向下」，翻成 GPU 左下原点是 painter 的事。
"""
import json

from . import theme as T
from .painter import text_width, wrap, ellipsize

PAD = 5.0                     # .bld-main 内边距（面板本体的留白，画的是 .bld-panel）
MARGIN = 7.0                  # .tabs/.sbar/.stream 左右外边距
STREAM_PAD = 0.0
NATIVE_W = 420.0              # runtime.native_slot() 假定的面板宽（见下面 composer_height）

# 原型 .tabs 是「AI 对话 / 设置」。但在 Blender 里，原生面板头的 bl_label 本身就是
# 「AI 对话」（DEEPSEEK_PT_chat），同一视觉行上再逐字写一遍就成了截图里那种
# 「AI 对话AI 对话」重影。取舍：**改文案，不删层** —— 这行页签是面板内唯一的视图切换
# 入口（runtime.dispatch 里 tab:0 / tab:1 直接切原生 active_panel_category），
# 删掉就没有入口了；所以首项改名「对话」，它描述的是「视图」而不是面板标题，
# 语义与原型一致，也不再和原生头逐字重复。
# 次项「设置」保留：它与它要跳过去的原生分类同名，是有用的指向，不是重影。
_TABS = [("对话", "ai"), ("设置", None)]      # 原型里「设置」是纯文字，没有图标
_QTABS = [("新增对象", "OBJECTS"), ("建模参数", "PARAMS"),
          ("执行脚本", "SCRIPT"), ("场景归档", "ARCHIVE")]
_TYPE_ICON = {"Mesh": "cube", "Material": "sphere",
              "Light": "film", "Camera": "film"}      # .orow 右侧的类型小图标

# Blender 原生面板头自己会画（DEEPSEEK_PT_chat.bl_label = "AI 对话"），这里只让出它的高度。
#
# 实测（2026-10-10）：原生面板头**包含在 region 内**。dev/out/fin2_top.png.png 宽 420
# 与 region 等宽、1:1，逐列扫描：y=0..27 是原生头底色 #383838，y=28 起才是自绘页签的
# 深色页签底(1d1d1d) —— 自绘内容「实测自 y=28 起」，正好压在原生头下沿，一像素不差。
# runtime.NATIVE_HEADER_H 原先写 26.0，与这里的 28 不一致（原生 textbox 代理框会整体
# 上移 2px），已按同一实测改成 28.0。这两个值必须一起改。
NATIVE_HEAD_H = 28.0


def _mix(a, b, t):
    """颜色插值（.btn 的 180deg 渐变分带要用）。"""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


def _bright(c, k):
    """CSS filter:brightness(k) 的近似。"""
    return (min(1.0, c[0] * k), min(1.0, c[1] * k), min(1.0, c[2] * k), c[3])


# ==========================================================================
# 布局游标
# ==========================================================================
class B(object):
    """按 y 顺序往下堆内容的极简构建器。"""

    def __init__(self, items, x, w, y=0.0, h=""):
        self.items = items
        self.x = x
        self.w = w
        self.y = y
        self.h = h            # 当前 hover 的 action_id，_btn 要用

    def rect(self, x, y, w, h, r, c):
        self.items.append(("rect", x, y, w, h, r, c))

    def border(self, x, y, w, h, r, t, c):
        self.items.append(("border", x, y, w, h, r, t, c))

    def line(self, x1, y1, x2, y2, t, c):
        self.items.append(("line", x1, y1, x2, y2, t, c))

    def text(self, x, y, s, size, c):
        if s:
            self.items.append(("text", x, y, s, size, c))

    def tcenter(self, x, y, w, h, s, size, c):
        """在 (x,y,w,h) 里水平垂直居中一段文字。"""
        tw = text_width(s, size)
        th = size * T.LH
        self.text(x + (w - tw) * 0.5, y + (h - th) * 0.5, s, size, c)

    def icon(self, name, x, y, size, c):
        self.items.append(("icon", name, x, y, size, c))

    def hit(self, x, y, w, h, action):
        self.items.append(("hit", x, y, w, h, action))

    def space(self, dy):
        self.y += dy

    def card(self, y, h, r, bg, border=None, pad=8.0):
        self.rect(self.x, y, self.w, h, r, bg)
        if border:
            self.border(self.x, y, self.w, h, r, 1.0, border)
        return self.x + pad


# ==========================================================================
# 上下文
# ==========================================================================
class Ctx(object):
    """一次布局所需的全部外部条件。"""

    def __init__(self, state, run, ui, W, H, hover="", focus=False, scroll=None,
                 settings_tab=False):
        self.state = state
        self.run = run
        self.ui = ui
        self.W = float(W)
        self.H = float(H)
        self.hover = hover or ""
        self.focus = focus
        # scroll=None 表示「自动贴底」（新消息进来就该看最新）；
        # 数值表示用户已经手动滚动，必须尊重它 —— 用 0 当哨兵会导致永远滚不回顶部。
        self.scroll = scroll
        self.settings_tab = settings_tab

    def note(self, i):
        try:
            notes = self.state.notes
            return notes[i].text if 0 <= i < len(notes) else ""
        except Exception:
            return ""

    def selected(self):
        try:
            return json.loads(self.state.selected_options_json or "{}")
        except Exception:
            return {}


# ==========================================================================
# 入口
# ==========================================================================
def build(c):
    W, H = c.W, c.H
    items = []

    items.append(("rect", 0, 0, W, H, 0, T.PANEL_BG))
    items.append(("border", 0.5, 0.5, W - 1, H - 1, T.R_PANEL, 1.0, T.PANEL_BORDER))

    y = _head(c, items)
    y = _tabs(c, items, y)
    y = _sbar(c, items, y)

    comp_items, comp_h = _composer(c, W, H)
    composer_top = H - comp_h

    stream_top = y + STREAM_PAD
    stream_h = max(40.0, composer_top - stream_top)
    content_h, scroll_eff = _stream(c, items, W, stream_top, stream_h)

    items.extend(comp_items)
    return {"items": items,
            "stream_rect": (MARGIN, stream_top, W - MARGIN * 2, stream_h),
            "composer_rect": (MARGIN, composer_top, W - MARGIN * 2, comp_h),
            "content_h": content_h,
            "scroll_eff": scroll_eff}


# --------------------------------------------------------------------------
def _head(c, items):
    """**故意什么都不画**。

    原型 .bld-head（caret + 「AI 对话」+ ···）其实就是 Blender 原生的面板头，
    Blender 自己已经画了一份。再自绘一遍会叠成「AI 对话AI 对话」这种重影。
    这里只把这段高度让出来，内容从原生面板头下方开始。
    """
    return round(NATIVE_HEAD_H * getattr(T, "UI_SCALE", 1.0), 1)


def _tabs(c, items, y):
    """原型 .tabs：2px 内边距 + 2px 间距，等分两页签。"""
    W = c.W
    tw_total = W - MARGIN * 2
    b = B(items, MARGIN, tw_total, y, c.hover)
    b.rect(b.x, y, tw_total, T.TABS_H, T.R_PANEL, T.TABS_BG)
    n = len(_TABS)
    cw = (tw_total - T.TABS_PAD * 2 - T.TABS_GAP * (n - 1)) / float(n)
    for i, (label, icon) in enumerate(_TABS):
        tx = MARGIN + T.TABS_PAD + i * (cw + T.TABS_GAP)
        hot = (c.hover == "tab:%d" % i)
        active = (i == 1) if c.settings_tab else (i == 0)
        if active:
            b.rect(tx, y + T.TABS_PAD, cw, T.TAB_H, T.R_CHIP, T.TABS_ON)
        col = T.TABS_ON_TEXT if active else (T.TAB_HOVER if hot else T.TAB_IDLE)
        tw = text_width(label, T.FS)
        if icon:
            total = tw + T.TAB_ICON + T.TABS_IGAP
            ix = tx + (cw - total) * 0.5
            b.icon(icon, ix, y + T.TABS_PAD + (T.TAB_H - T.TAB_ICON) * 0.5 - 1.5,
                   T.TAB_ICON, col)
            b.text(ix + T.TAB_ICON + T.TABS_IGAP,
                   y + T.TABS_PAD + (T.TAB_H - T.LINE_H) * 0.5, label, T.FS, col)
        else:
            b.tcenter(tx, y + T.TABS_PAD, cw, T.TAB_H, label, T.FS, col)
        b.hit(tx, y + T.TABS_PAD, cw, T.TAB_H, "tab:%d" % i)
    return y + T.TABS_H + 5


def _sbar(c, items, y):
    """原型 .sbar：标题行（图标 + 话题 + 日期）+ 一行 10px 副标题。"""
    W = c.W
    st = c.state
    b = B(items, MARGIN, W - MARGIN * 2, y, c.hover)
    b.rect(b.x, y, b.w, T.SBAR_H, T.R_CARD, T.SBAR_BG)
    b.border(b.x, y, b.w, T.SBAR_H, T.R_CARD, 1.0, T.SBAR_BORDER)
    lx = b.x + 1 + T.SBAR_PAD_X                      # 描边内侧的内容左边界
    rx = b.x + b.w - 1 - T.SBAR_PAD_X                # 内容右边界
    row1 = y + 1 + T.SBAR_PAD_Y
    b.icon("doc", lx, row1 + (T.LINE_H - 12) * 0.5, 12, T.SBAR_DIM)
    tx = lx + 12 + 6
    topic = "当前会话：" + (st.session_topic or "新任务")
    date = st.session_date or ""
    dw = text_width(date, T.FS)
    room = rx - tx - (dw + 6 if date else 0)
    b.text(tx, row1, ellipsize(topic, T.FS, max(20.0, room)), T.FS, T.SBAR_TEXT)
    if date:
        b.text(rx - dw, row1, date, T.FS, T.SBAR_DIM)
    # 文案铁律：轮次/工具调用这类词只出现在【详情】【设置】
    b.text(lx, row1 + T.LINE_H + T.SBAR_ROW_GAP,
           "正在执行" if st.busy else "可连续追问", T.FS_META, T.SBAR_DIM)
    return y + T.SBAR_H + 5


# ==========================================================================
# 输入区
# ==========================================================================
def _chip_rows(W, pills):
    """快捷胶囊折行后的行数（.quick 是 flex-wrap）。"""
    inner = W - T.COMPOSER_PAD_X * 2
    rows, cx = 0, 0.0
    for p in pills:
        w = text_width(p, T.FS_META) + T.CHIP_PAD_X * 2 + 2
        if cx > 0 and cx + w > inner:
            rows += 1
            cx = 0.0
        cx += w + T.QUICK_GAP
    return rows + 1 if pills else 0


def _quick_h(W, pills):
    n = _chip_rows(W, pills)
    return n * T.CHIP_H + (n - 1) * T.QUICK_ROW_GAP if n else 0.0


def _text_h(st):
    lines = max(T.TEXT_LINES_MIN, min(T.TEXT_LINES_MAX, int(st.prompt_lines or 2)))
    return max(T.TEXT_MIN_H, lines * T.LINE_H + 10.0)


def composer_height(st, pills=None, W=NATIVE_W):
    """输入区总高。

    pills 为 None 时按 NATIVE_W 单行估算 —— runtime.native_slot() 只拿得到
    state，调不到 ui.quick_pills()，而它硬编码的 W 就是 420（四个胶囊一行放得下）。
    """
    quick_h = _quick_h(W, pills) if pills is not None else T.CHIP_H
    busy = bool(getattr(st, "busy", False))
    btn_h = T.BTN_H if busy else (T.BTN_H * 2 + T.BTN_GAP)
    return (T.COMPOSER_BORDER_TOP + T.COMPOSER_PAD_T + quick_h + T.COMPOSER_GAP
            + _text_h(st) + T.COMPOSER_GAP + btn_h
            + T.COMPOSER_PAD_B)


def composer_text_rect(W, H, st, pills=None):
    """输入框内「文字区」的矩形。原生 textbox 代理框必须和它对齐。"""
    total = composer_height(st, pills, W)
    quick_h = _quick_h(W, pills) if pills is not None else T.CHIP_H
    top = (H - total + T.COMPOSER_BORDER_TOP + T.COMPOSER_PAD_T + quick_h
           + T.COMPOSER_GAP)
    th = _text_h(st)
    return (T.COMPOSER_PAD_X + 1, top + 1, W - (T.COMPOSER_PAD_X + 1) * 2, th - 2)


def _composer(c, W, H):
    st = c.state
    busy = bool(st.busy)
    items = []
    pills = list(c.ui.quick_pills(st))
    total = composer_height(st, pills, W)
    top = float(H) - total
    inner_w = W - T.COMPOSER_PAD_X * 2

    # 底板盖住消息流越界部分
    items.append(("rect", 0, top, W, total, 0, T.COMPOSER_BG))
    items.append(("line", 0, top, W, top, 1.0, T.COMPOSER_TOPLINE))

    b = B(items, T.COMPOSER_PAD_X, inner_w,
           top + T.COMPOSER_BORDER_TOP + T.COMPOSER_PAD_T, c.hover)

    # 快捷胶囊（放不下自动换行）
    cx = b.x
    cy = b.y
    for p in pills:
        w = text_width(p, T.FS_META) + T.CHIP_PAD_X * 2 + 2
        if cx > b.x and cx + w > b.x + inner_w:
            cx = b.x
            cy += T.CHIP_H + T.QUICK_ROW_GAP
        hot = c.hover == "pill:%s" % p
        b.rect(cx, cy, w, T.CHIP_H, T.R_CHIP, T.CHIP_HOVER if hot else T.CHIP_BG)
        b.border(cx, cy, w, T.CHIP_H, T.R_CHIP, 1.0, T.CHIP_BORDER)
        b.tcenter(cx, cy, w, T.CHIP_H, p, T.FS_META, T.CHIP_TEXT)
        b.hit(cx, cy, w, T.CHIP_H, "pill:%s" % p)
        cx += w + T.QUICK_GAP
    b.y = cy + T.CHIP_H

    # 输入容器。内部不填色：那块矩形由原生 textbox 接管（文字/光标/中文 IME），
    # 自绘层只画它外面那一圈边框，否则会把原生文字盖掉。
    b.space(T.COMPOSER_GAP)
    tx, ty, tw, th = composer_text_rect(W, H, st, pills)
    b.hit(tx - 1, ty - 1, tw + 2, th + 2, "hover:inwrap")
    b.border(tx - 1, ty - 1, tw + 2, th + 2, T.R_CARD, 1.0,
             T.IN_FOCUS if c.focus else T.IN_BORDER)
    if st.prompt:
        wrap_w = max(20.0, tw - T.TEXT_PAD_X * 2 - T.SEND_SIZE)
        p_lines = wrap(st.prompt, T.FS, wrap_w)
        for idx, ln in enumerate(p_lines):
            ly = ty + T.TEXT_PAD_Y + idx * T.LINE_H
            b.text(tx + T.TEXT_PAD_X, ly, ln, T.FS, T.IN_TEXT)
        if c.focus:
            last_idx = len(p_lines) - 1 if p_lines else 0
            last_ln = p_lines[-1] if p_lines else ""
            cx = tx + T.TEXT_PAD_X + text_width(last_ln, T.FS)
            cy = ty + T.TEXT_PAD_Y + last_idx * T.LINE_H
            b.line(cx, cy, cx, cy + T.FS * 1.15, 1.5, T.IN_FOCUS)
    else:
        b.text(tx + T.TEXT_PAD_X, ty + T.TEXT_PAD_Y, "继续描述需求，或询问下一步操作…",
               T.FS, T.IN_PH)
        if c.focus:
            cx = tx + T.TEXT_PAD_X
            cy = ty + T.TEXT_PAD_Y
            b.line(cx, cy, cx, cy + T.FS * 1.15, 1.5, T.IN_FOCUS)

    # 右下角斜纹把手（135deg 重复渐变 = 右下角一束 45° 细线）
    gx = W - T.COMPOSER_PAD_X - T.GRIP_SIZE
    gy = ty + th - T.GRIP_SIZE
    gc = T.GRIP_HOVER if c.hover == "grip" else T.GRIP
    sx0, sy0, sx1, sy1 = gx + 6, gy + 6, gx + 15, gy + 15     # .grip::after 9x9
    for k in range(5):
        seg = _seg_diag(sx0, sy0, sx1, sy1, (sx0 + sy0) + k * 2)
        if seg:
            b.line(seg[0], seg[1], seg[2], seg[3], T.GRIP_STRIPE_W, gc)
    b.hit(gx, gy, T.GRIP_SIZE, T.GRIP_SIZE, "grip")
    if c.hover in ("hover:inwrap", "grip"):
        hint = "拖我拉高"
        hw = text_width(hint, T.FS_TINY)
        b.text(W - T.COMPOSER_PAD_X - 22 - hw, ty + th - 4 - T.FS_TINY * T.LH,
               hint, T.FS_TINY, T.GRIP_HINT)

    # 内嵌发送按钮（margin:0 6px 6px 0，贴在 inwrap 内容框右下）
    sb = T.SEND_SIZE
    sbx = W - T.COMPOSER_PAD_X - 1 - T.SEND_MR - sb
    sby = ty + th - T.SEND_MR - sb
    b.rect(sbx, sby, sb, sb, T.R_SEND,
           T.SEND_HOVER if c.hover == "send" else T.SEND_BG)
    b.border(sbx, sby, sb, sb, T.R_SEND, 1.0, T.SEND_BORDER)
    b.icon("send", sbx + (sb - 13) * 0.5, sby + (sb - 13) * 0.5, 13, T.SEND_ICON)
    b.hit(sbx, sby, sb, sb, "send")

    # 底部按钮区：任务运行中隐藏四操作按钮，仅显示单条终止按钮；闲置时显示完整四按钮
    b.y = ty + th + T.COMPOSER_GAP
    half = (inner_w - T.BTN_GAP) * 0.5
    if not busy:
        _btn(b, b.x, b.y, half, "发送指令", "send", "act:run", True)
        _btn(b, b.x + half + T.BTN_GAP, b.y, half, "回退发送", "undo", "act:undo",
             c.ui.can_undo(c.state))
        b.y += T.BTN_H + T.BTN_GAP
        _btn(b, b.x, b.y, half, "新建任务", "plus", "act:new", True)
        _btn(b, b.x + half + T.BTN_GAP, b.y, half, "清空记录", "trash", "act:clear", True)
    else:
        _btn(b, b.x, b.y, inner_w, "终止任务", "trash", "act:stop", True)
    return items, total


def _seg_diag(x0, y0, x1, y1, cst):
    """把 x+y=cst 这条 45° 线裁到方框 [x0,x1]x[y0,y1] 内。

    必须同时和**四条边**求交。只跟上下边求交的话，在小方框里这条线往往从左右边
    进出，上下两个交点根本不在框内 —— 结果是把手那几条 135° 斜纹一条都画不出来。
    """
    cand = []
    for px, py in ((cst - y1, y1), (cst - y0, y0),      # 与下边 / 上边
                   (x0, cst - x0), (x1, cst - x1)):     # 与左边 / 右边
        if (x0 - 0.01 <= px <= x1 + 0.01 and y0 - 0.01 <= py <= y1 + 0.01):
            if all(abs(px - qx) > 0.01 or abs(py - qy) > 0.01 for qx, qy in cand):
                cand.append((px, py))
    if len(cand) < 2:
        return None
    (ax, ay), (bx, by) = cand[0], cand[1]
    return (ax, ay, bx, by)


def _grad(b, x, y, w, h, top, bot, n=3):
    """CSS linear-gradient(180deg, top, bot) 的近似。

    先用圆角矩形铺满（保证四角是圆的），再从上往下贴 n 条色带。
    只有整框一个半径，做不出「上圆下直」，所以带与带的交界在左右边缘会留下
    <=r 的小缺口；两端色差本来只有 8%，看不出来。
    """
    b.rect(x, y, w, h, T.R_BTN, bot)
    if n <= 1:
        return                       # 单档渐变就是纯 bot 底板；否则 i/(n-1) 会除零
    bh = h / float(n)
    for i in range(n):
        yy = y + bh * i
        hh = bh if i < n - 1 else h - bh * (n - 1)
        col = _mix(top, bot, i / float(n - 1))
        b.rect(x, yy, w, hh, T.R_BTN if i == 0 else 0, col)


def _btn(b, x, y, w, label, icon, action, enabled=True):
    """原型 .btn：上亮下暗的垂直渐变 + 圆角描边 + hover 提亮。"""
    h = T.BTN_H
    if enabled:
        top, bot, txt = T.BTN_TOP, T.BTN_BOTTOM, T.BTN_TEXT
        if b.h == action:
            top, bot = _bright(top, T.BTN_HOVER), _bright(bot, T.BTN_HOVER)
    else:
        top = bot = T.BTN_DISABLED_BOTTOM
        txt = T.BTN_DISABLED_TEXT
    _grad(b, x, y, w, h, top, bot)
    b.border(x, y, w, h, T.R_BTN, 1.0, T.BTN_BORDER)
    tw = text_width(label, T.FS)
    if icon:
        total = tw + T.BTN_ICON + T.BTN_GAP
        ix = x + (w - total) * 0.5
        b.icon(icon, ix, y + (h - T.BTN_ICON) * 0.5, T.BTN_ICON, txt)
        b.text(ix + T.BTN_ICON + T.BTN_GAP, y + (h - T.LINE_H) * 0.5, label, T.FS, txt)
    else:
        b.tcenter(x, y, w, h, label, T.FS, txt)
    if enabled:
        b.hit(x, y, w, h, action)


# ==========================================================================
# 消息流
# ==========================================================================
def _empty_card(b):
    """空历史时的欢迎与引导卡片。"""
    pad_x = 10.0
    pad_y = 10.0
    inner_w = b.w - pad_x * 2
    title = "欢迎使用 AI 建模助手"
    hint = "在下方输入框描述你想创建的模型，或选择上方快捷标签"
    hint_lines = wrap(hint, T.FS_META, inner_w)

    icon_sz = 14.0
    title_h = T.FS * T.LH
    hint_lh = T.LINE_H_XS
    gap = 5.0

    h = pad_y * 2 + title_h + gap + len(hint_lines) * hint_lh
    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, T.SBAR_BG)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, T.SBAR_BORDER)

    ix = b.x + pad_x
    iy = y + pad_y + (title_h - icon_sz) * 0.5
    b.icon("ai", ix, iy, icon_sz, T.QG_TITLE)
    b.text(ix + icon_sz + 6.0, y + pad_y, title, T.FS, T.SBAR_TEXT)

    yy = y + pad_y + title_h + gap
    for ln in hint_lines:
        b.text(ix, yy, ln, T.FS_META, T.SBAR_DIM)
        yy += hint_lh
    b.y = y + h


def _stream(c, items, W, top, view_h):
    st = c.state
    x0 = MARGIN
    w = W - MARGIN * 2
    body = []
    b = B(body, x0, w, 0.0, c.hover)

    hist = st.history
    if not hist and not getattr(st, "busy", False) and not c.run:
        _empty_card(b)
        b.space(T.GAP)
    else:
        start = max(0, len(hist) - max(2, st.shown_count))
        for i in range(start, len(hist)):
            m = hist[i]
            if getattr(m, "role", "AI") == "你":
                _user_msg(c, b, m.text)
            else:
                _ai_msg(c, b, m, i, hist)
            b.space(T.GAP)

        if _is_busy(c.run, st):
            _thinking_msg(c, b, c.run)
            b.space(T.GAP)

        _status_card(c, b, c.run)

    content_h = max(b.y - T.GAP, 1.0)
    max_scroll = max(0.0, content_h - view_h)
    scroll = max_scroll if c.scroll is None else max(0.0, min(float(c.scroll), max_scroll))

    items.append(("clip", x0 - 4, top, w + 8, view_h))
    # 内容比可视区短时**贴底**：聊天流应该紧贴输入框上方，而不是浮在顶部
    # 留一大片空白（终端式对话的惯例）。
    slack = max(0.0, view_h - content_h)
    for it in body:
        s = list(it)
        s[2] = it[2] + top + slack - scroll
        items.append(tuple(s))
    items.append(("unclip",))

    if max_scroll > 1.0:
        _scrollbar(items, W, top, view_h, content_h, scroll)

    return content_h, scroll


def _is_busy(run, st):
    try:
        from .state import BUSY
        ph = getattr(run, "phase", None)
        return bool(getattr(st, "busy", False)) or (ph is not None and ph in BUSY)
    except Exception:
        return bool(getattr(st, "busy", False))


def _scrollbar(items, W, top, view_h, content_h, scroll):
    """原型 .stream::-webkit-scrollbar：轨道透明，只有 8px 圆角滑块。"""
    sw = T.SCROLL_W
    sx = W - MARGIN - sw
    th = max(24.0, view_h * (view_h / content_h))
    frac = scroll / max(1.0, content_h - view_h)
    ty = top + (view_h - th) * frac
    items.append(("rect", sx, ty, sw, th, sw * 0.5, T.SCROLL_THUMB))


def _think_phase(t):
    """原型 @keyframes bounce：0/60/100% 静止且半透，30% 抬起 4px 且实心。"""
    if t <= 0.30:
        return -T.THINK_LIFT * (t / 0.30), 0.45 + (1.0 - 0.45) * (t / 0.30)
    if t <= 0.60:
        k = (t - 0.30) / 0.30
        return -T.THINK_LIFT * (1.0 - k), 1.0 - 0.55 * k
    return 0.0, 0.45


def _thinking_msg(c, b, run):
    """原型 .think：三点动效挂在 AI 头像位置，外圈再套一个脉冲环。

    时钟用 run.elapsed —— runtime 忙碌时 10Hz 重绘，elapsed 每次都在走，
    所以同一个 run 换不同 elapsed 会画出不同的点位，无头也能断言。
    """
    x, y = b.x, b.y
    secs = float(getattr(run, "elapsed", 0.0) or 0.0) if run is not None else 0.0
    cx = x + T.THINK_SLOT * 0.5
    cy = y + T.AHEAD_H * 0.5
    # 脉冲外圈：scale .7 -> 1.25，透明度 .9 -> 0
    pt = (secs % T.THINK_PULSE) / T.THINK_PULSE
    b.items.append(("ring", cx, cy, T.THINK_RING_R * (0.7 + 0.55 * pt),
                    T.THINK_RING_W,
                    (T.THINK_RING[0], T.THINK_RING[1], T.THINK_RING[2],
                     T.THINK_RING[3] * 0.9 * (1.0 - pt))))
    for i in range(3):
        tt = ((secs - i * T.THINK_DELAY) % T.THINK_PERIOD) / T.THINK_PERIOD
        dy, a = _think_phase(tt)
        b.items.append(("circ", x + T.THINK_DOT_R
                        + i * (T.THINK_DOT_R * 2 + T.THINK_DOT_GAP),
                        cy - T.THINK_DOT_R - dy, T.THINK_DOT_R,
                        (T.THINK_DOT[0], T.THINK_DOT[1], T.THINK_DOT[2],
                         T.THINK_DOT[3] * a)))
    tx = x + T.THINK_SLOT + T.AMSG_ICON_GAP
    by = y + (T.AHEAD_H - T.FS_HEAD * T.LH) * 0.5
    b.text(tx, by, "AI 助手", T.FS_HEAD, T.AI_HEAD)
    b.text(tx + text_width("AI 助手", T.FS_HEAD) + 3, by, "正在思考",
           T.FS_HEAD, T.AI_TIME)
    b.y = y + T.AHEAD_H + T.AMSG_GAP
    for ln in _think_lines(run):
        b.text(b.x + 1, b.y, ellipsize(ln, T.FS_HEAD, b.w - 2), T.FS_HEAD, T.AI_TEXT_DIM)
        b.y += T.LINE_H_SM + 1


def _think_lines(run):
    """忙碌时也要说清：发生了什么 / 现在什么样 / 下一步做什么。"""
    steps = len(getattr(run, "calls", []) or []) if run is not None else 0
    secs = int(getattr(run, "elapsed", 0) or 0) if run is not None else 0
    out = ["正在规划建模步骤与参数…"]
    if steps or secs:
        out.append("已完成 %d 个步骤 · 已用 %d 秒" % (steps, secs))
    out.append("现在不用做什么，做好了会直接出现在场景里。")
    return out


def _status_card(c, b, run):
    """结算态卡片。

    铁律：PARTIAL 绝不用红色（那是「停下了但没出错」，不是失败），
    只有 FAILED 才上红。审批门必须先说清楚「要改什么」，代码默认折叠。
    """
    if run is None:
        return
    from .state import Phase, BUSY, guide

    ph = getattr(run, "phase", None)
    if ph is None:
        return
    if ph == Phase.AWAITING_APPROVAL:
        _approval_card(c, b, run)
        return
    if ph in BUSY:
        return                    # 忙碌由消息流末尾的思考动效表达（原型 .think）
    if ph == Phase.COMPLETED:
        return                                  # 成功由消息里的检查清单表达
    if ph == Phase.PARTIAL:
        _partial_card(c, b, run)
        return
    if ph == Phase.FAILED:
        _failed_card(c, b, run)
        return
    if ph == Phase.STOPPED:
        _notice_card(b, "已停止后续步骤", "已经做了的部分都保留在场景里。",
                     "想继续就在下面说一句。",
                     T.ST_WARN_BG, T.ST_WARN_BORDER, T.ST_WARN_TEXT, T.ST_WARN_DIM)


def _partial_card(c, b, run):
    """PARTIAL：中性卡，明确说清「已经做了 / 还没做」。"""
    skipped = list(getattr(run, "skipped", []) or [])
    added = list(getattr(run.receipt, "added_names", []) or []) if run.receipt else []
    done = "、".join(added[:3]) if added else "场景改动都保留着"
    todo = "；".join(str(s)[:40] for s in skipped[:3]) if skipped else "剩下的步骤还没执行"
    _notice_card(b, "做到一半，已停下", "已经做了：%s" % done,
                 "还没做：%s" % todo,
                 T.ST_WARN_BG, T.ST_WARN_BORDER, T.ST_WARN_TEXT, T.ST_WARN_DIM,
                 foot="没做完的部分，再说一句就行。")


def _failed_card(c, b, run):
    from .state import guide
    g = guide(getattr(run, "err", None))
    _notice_card(b, g.get("title", "未完成"), g.get("effect", ""),
                 "该做的事：%s" % g.get("action", ""),
                 T.ST_FAIL_BG, T.ST_FAIL_BORDER, T.ST_FAIL_TEXT, T.ST_FAIL_DIM,
                 foot=g.get("retry", ""), alert=True)


def _notice_card(b, title, l1, l2, bg, border, tcol, dim, foot="", alert=False):
    pad = 9.0                           # 1px 描边 + 8px 内边距
    inner = b.w - pad * 2
    lines = []
    for s in (l1, l2, foot):
        if s:
            lines.extend(wrap(s, T.FS_TINY, inner - 22) or [""])
    h = pad * 2 + T.FS * T.LH + 4 + len(lines) * (T.FS_TINY * T.LH + 2)
    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, bg)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, border)
    if alert:
        b.rect(b.x + 1, y + 1, 3, h - 2, 1.5, T.ST_FAIL_TEXT)   # 红条：错误专用
    b.icon("info" if alert else "check", b.x + pad, y + pad - 1, 12, tcol)
    b.text(b.x + pad + 17, y + pad - 2, title, T.FS, tcol)
    yy = y + pad + T.FS * T.LH + 4
    for i, ln in enumerate(lines):
        b.text(b.x + pad + 17, yy, ln, T.FS_TINY, dim)
        yy += T.FS_TINY * T.LH + 2
    b.y = y + h


def _approval_target(call, code):
    """审批门必须先说清「要改哪个对象」，用户才判断得了要不要批准。

    优先取参数里显式的名字；拿不到就从代码里抠 objects['X'] / context.object.name。
    """
    args = getattr(call, "args", None) or {}
    if isinstance(args, dict):
        for k in ("object_name", "name", "target", "object"):
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if code:
        import re
        m = re.search(r"""objects\[\s*['"]([^'"]+)['"]\s*\]""", code)
        if m:
            return m.group(1)
        m = re.search(r"""(?:context\.active_object|context\.object)\.name""", code)
        if m:
            return "当前选中对象"
    return ""


def _approval_card(c, b, run):
    """审批门：先讲清「想改什么」，代码默认折叠，展开才铺出来。"""
    st = c.state
    pending = [call for call in (getattr(run, "calls", []) or [])
               if getattr(call, "approval_state", None) == "pending"]
    if not pending:
        return
    call = pending[0]
    code = str(getattr(call, "raw_args", "") or "")
    if not code and isinstance(getattr(call, "args", None), dict):
        code = str(call.args.get("code") or "")
    target = _approval_target(call, code)
    pad = 9.0                           # 1px 描边 + 8px 内边距
    inner = b.w - pad * 2
    head = "它想运行一段脚本，会改动：%s" % (target or "当前选中对象")
    head_lines = wrap(head, T.FS_TINY, inner - 22)
    code_lines = (code.split("\n") if code else [])[:24] if st.show_approval_code else []
    lh = T.FS_CODE * T.CODE_LH
    h = pad * 2 + T.FS * T.LH + 4 + len(head_lines) * (T.FS_TINY * T.LH + 2)
    if code_lines:
        h += T.CODE_PAD * 2 + len(code_lines) * lh
    h += T.BTN_H + 6
    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, T.ST_APPROVE_BG)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, T.ST_APPROVE_BORDER)
    b.icon("info", b.x + pad, y + pad - 1, 12, T.ST_APPROVE_TEXT)
    b.text(b.x + pad + 17, y + pad - 2, "等你批准", T.FS, T.ST_APPROVE_TEXT)
    yy = y + pad + T.FS * T.LH + 4
    for ln in head_lines:
        b.text(b.x + pad + 17, yy, ln, T.FS_TINY, T.ST_WARN_TEXT)
        yy += T.FS_TINY * T.LH + 2
    if code_lines:
        ch = T.CODE_PAD * 2 + len(code_lines) * lh
        b.rect(b.x + pad, yy + 2, inner, ch, T.R_CARD, T.CODE_BG)
        b.border(b.x + pad, yy + 2, inner, ch, T.R_CARD, 1.0, T.CODE_BORDER)
        cy = yy + 2 + T.CODE_PAD
        for ln in code_lines:
            b.text(b.x + pad + 8, cy, ellipsize(ln, T.FS_CODE, inner - 16),
                   T.FS_CODE, T.CODE_TEXT)
            cy += lh
    y_btn = y + h - T.BTN_H - pad
    bw = (b.w - T.BTN_GAP) * 0.5
    _btn(b, b.x, y_btn, bw, "批准执行", "check", "act:approve", True)
    _btn(b, b.x + bw + T.BTN_GAP, y_btn, bw,
         "查看代码" if not st.show_approval_code else "收起代码",
         "doc", "act:toggle_code", True)
    b.hit(b.x, y, b.w, h, "act:toggle_code")
    b.y = y + h


def _user_msg(c, b, text):
    """原型 .umsg：靠右、宽度自适应但不超过 86%。"""
    padx, pady = T.USER_PAD_X, T.USER_PAD_Y
    inside = 1 + padx                                # 描边 + padding
    max_w = b.w * T.USER_MAXW
    lines = wrap(text, T.FS, max_w - inside * 2)
    mw = text_width("用户", T.FS_META)
    meta_w = mw + T.USER_META_GAP + 11
    need = inside * 2 + max([meta_w] + [text_width(l, T.FS) for l in lines])
    w = min(max_w, max(need, inside * 2 + 40.0))
    h = 2 + pady * 2 + T.USER_META_H + T.USER_META_MB + len(lines) * T.LINE_H
    x = b.x + b.w - w                               # align-self:flex-end
    y = b.y
    b.rect(x, y, w, h, T.R_CARD, T.USER_BG)
    b.border(x, y, w, h, T.R_CARD, 1.0, T.USER_BORDER)
    mr = x + w - 1 - padx
    my = y + 1 + pady
    b.text(mr - mw, my + (T.USER_META_H - T.LINE_H_XS) * 0.5, "用户",
           T.FS_META, T.USER_META)
    b.icon("person", mr - mw - T.USER_META_GAP - 11,
           my + (T.USER_META_H - 11) * 0.5, 11, T.USER_META)
    yy = my + T.USER_META_H + T.USER_META_MB
    for ln in lines:
        b.text(x + inside, yy, ln, T.FS, T.AI_TEXT)
        yy += T.LINE_H
    b.y = y + h


def _confirmed_spec_bar(b, text="✓ 关键规格已确认"):
    """已确认/已过时追问的精简状态条。"""
    h = 24.0
    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, T.CKL_BG)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, T.CKL_BORDER)
    b.icon("check", b.x + 8.0, y + (h - T.CKL_ICON_SZ) * 0.5, T.CKL_ICON_SZ, T.CKL_ICON)
    b.text(b.x + 8.0 + T.CKL_ICON_SZ + 6.0, y + (h - T.FS * T.LH) * 0.5, text, T.FS, T.CKL_TEXT)
    b.y = y + h


def _is_question_obsolete(c, m, msg_idx=None, hist=None):
    """判断该 AI 消息中的追问是否已过时/已被用户确认。"""
    if c.hover and c.hover.startswith("opt:"):
        return False

    if hist is None:
        try:
            hist = c.state.history
        except Exception:
            hist = []

    if msg_idx is None:
        msg_idx = -1
        for j, item in enumerate(hist):
            if item == m:
                msg_idx = j
                break
        if msg_idx == -1:
            for j in range(len(hist) - 1, -1, -1):
                if hist[j] is m or getattr(hist[j], "text", None) == getattr(m, "text", None):
                    msg_idx = j
                    break

    if msg_idx == -1 or msg_idx >= len(hist):
        return False

    # 1. 检查该消息之后是否有更新的 AI 追问轮次
    for k in range(msg_idx + 1, len(hist)):
        other = hist[k]
        if getattr(other, "role", "AI") != "你":
            try:
                p = c.ui.parse_interactive_options(getattr(other, "text", "") or "")
                if p.get("questions"):
                    return True
            except Exception:
                pass

    # 2. 检查该消息之后是否有用户消息（确认选择/按推荐/后续指令），说明已被用户确认或响应
    for k in range(msg_idx + 1, len(hist)):
        if getattr(hist[k], "role", "AI") == "你":
            return True

    return False


def _ai_msg(c, b, m, msg_idx=None, hist=None):
    x = b.x
    y = b.y
    b.icon("ai", x, y + (T.AHEAD_H - T.AI_ICON) * 0.5, T.AI_ICON, T.AI_HEAD)
    tx = x + T.AI_ICON + T.AMSG_ICON_GAP
    by = y + (T.AHEAD_H - T.FS_HEAD * T.LH) * 0.5
    b.text(tx, by, "AI 助手", T.FS_HEAD, T.AI_HEAD)
    ds = getattr(m, "duration_str", "") or ""
    if ds:
        b.text(tx + text_width("AI 助手", T.FS_HEAD) + 2,
               y + (T.AHEAD_H - T.FS_META * T.LH) * 0.5, ds, T.FS_META, T.AI_TIME)
    b.y = y + T.AHEAD_H + T.AMSG_GAP

    try:
        parsed = c.ui.parse_interactive_options(getattr(m, "text", "") or "")
    except Exception:
        parsed = {"intro": m.text or "", "questions": [], "confirm": [],
                  "outro": "", "general": [], "all_recommended": ""}

    for chunk in ([parsed.get("intro") or ""] + (parsed.get("general") or [])):
        if chunk:
            _body_text(b, chunk)

    qs = parsed.get("questions") or []
    if qs:
        if _is_question_obsolete(c, m, msg_idx, hist):
            b.space(4)
            _confirmed_spec_bar(b, "✓ 关键规格已确认")
        else:
            sel = c.selected()
            for qi, q in enumerate(qs):
                b.space(4)
                _question_group(c, b, qi, q, sel)
            b.space(5)
            can_confirm = bool(sel and any(bool(v) for v in sel.values()))
            _btns_row(b, [("确认选择", "act:confirm", can_confirm, 1.3),
                          ("按推荐来", "act:recommended", True, 1.0)])
            picked = _picked(sel, qs, c)
            b.space(3)
            b.text(b.x + 1, b.y, picked, T.FS_META, T.SBAR_DIM)

    confirm = parsed.get("confirm") or []
    if confirm:
        b.space(5)
        _checklist(b, confirm)

    if parsed.get("outro"):
        b.space(3)
        _body_text(b, parsed["outro"])

    if (getattr(m, "artifacts_json", "") or "").strip():
        b.space(6)
        _result_section(c, b, m)

    b.y = max(b.y, y + T.AHEAD_H + T.AMSG_GAP)


def _body_text(b, text):
    for ln in wrap(text, T.FS, b.w - 2):
        b.text(b.x + 1, b.y, ln, T.FS, T.AI_TEXT)
        b.y += T.LINE_H


def _checklist(b, items):
    """原型 .ckl：字号继承 .bld 的 11px（不是 9.5），勾 12px，行距 3。"""
    lh = T.FS * T.LH
    px, py = T.CKL_PAD_X, T.CKL_PAD_Y
    inner = b.w - 2 * (1 + px)
    h = 2 + py * 2 + len(items) * lh + (len(items) - 1) * T.CKL_GAP
    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, T.CKL_BG)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, T.CKL_BORDER)
    yy = y + 1 + py
    for it in items:
        b.icon("check", b.x + 1 + px, yy + 1, T.CKL_ICON_SZ, T.CKL_ICON)
        for k, ln in enumerate(wrap(it, T.FS, inner - T.CKL_ICON_SZ - 6)):
            b.text(b.x + 1 + px + T.CKL_ICON_SZ + 6, yy + k * lh, ln, T.FS, T.CKL_TEXT)
        yy += lh + T.CKL_GAP
    b.y = y + h


def _btns_row(b, specs):
    """原型 .btns：按 flex 权重分宽（确认选择 1.3，按推荐来 1）。"""
    gap = T.BTN_GAP
    total = sum(sp[3] for sp in specs)
    avail = b.w - gap * (len(specs) - 1)
    x = b.x
    for label, action, enabled, wgt in specs:
        w = avail * wgt / total
        _btn(b, x, b.y, w, label, None, action, enabled)
        x += w + gap
    b.y += T.BTN_H


def _picked(sel, qs, c):
    names = []
    for qi, q in enumerate(qs):
        v = sel.get(str(qi))
        if isinstance(v, list) and v:
            names.append(" / ".join(v))
    if not names:
        return "还没选，直接按推荐来也行"
    return "已选 %d 项 · %s" % (len(names), ellipsize(" / ".join(names), T.FS_META,
                                                  b_w(c) - 20))


def b_w(c):
    return c.W - MARGIN * 2


# --------------------------------------------------------------------------
def _question_group(c, b, qi, q, sel):
    """原型 .qg/.qrow：单选组。选中/悬停高亮只占内容盒，不越出卡片内边距。"""
    st = c.state
    px, py = T.QG_PAD_X, T.QG_PAD_Y
    ix = b.x + 1 + px                               # 内容盒左边界
    inner = b.w - 2 * (1 + px)
    title = q.get("title") or q.get("question") or ""
    title = ellipsize(str(title), T.FS, inner - 40)
    opts = q.get("options") or []
    cur = sel.get(str(qi))

    rows = []
    for oi, o in enumerate(opts):
        val = o.get("label") or o.get("value") or ""
        rec = bool(o.get("rec")) or "推荐" in str(o.get("value", ""))
        rows.append((val, rec, str(oi)))
    other_open = (st.other_open_q == str(qi))
    n = len(rows)
    h = 2 + py * 2 + T.QG_TITLE_H + n * T.QROW_H + (n - 1) * T.QROW_GAP
    if other_open:
        h += T.OTHER_MY * 2 + T.OTHER_H

    y = b.y
    b.rect(b.x, y, b.w, h, T.R_CARD, T.QG_BG)
    b.border(b.x, y, b.w, h, T.R_CARD, 1.0, T.QG_BORDER)
    b.text(ix, y + 1 + py, "%d · %s" % (qi + 1, title), T.FS, T.QG_TITLE)
    yy = y + 1 + py + T.QG_TITLE_H

    for val, rec, oi in rows:
        selected = (isinstance(cur, list) and val in cur)
        hot = (c.hover == "opt:%d:%s" % (qi, oi))
        if selected:
            b.rect(ix, yy, inner, T.QROW_H, T.R_CHIP, T.QROW_SEL_BG)
        elif hot:
            b.rect(ix, yy, inner, T.QROW_H, T.R_CHIP, T.QROW_HOVER_BG)
        tc = T.QROW_SEL_TEXT if selected else (T.QROW_HOVER_TEXT if hot else T.QROW_TEXT)
        _radio(b, ix + T.QROW_PAD_X + T.RADIO_R, yy + T.QROW_H * 0.5, selected)
        lx = ix + T.QROW_PAD_X + T.RADIO_R * 2 + T.QROW_IGAP
        tag_w = text_width("推荐", T.FS_TINY) if rec else 0.0
        avail = (ix + inner - T.QROW_PAD_X - tag_w - (6 if rec else 0)) - lx
        b.text(lx, yy + (T.QROW_H - T.LINE_H) * 0.5,
               ellipsize(val, T.FS, max(10.0, avail)), T.FS, tc)
        if rec:
            b.text(ix + inner - T.QROW_PAD_X - tag_w,
                   yy + (T.QROW_H - T.FS_TINY * T.LH) * 0.5, "推荐", T.FS_TINY,
                   T.QTAG_SEL if selected else T.QTAG)
        b.hit(ix, yy, inner, T.QROW_H, "opt:%d:%s" % (qi, oi))
        yy += T.QROW_H + T.QROW_GAP

    if other_open:
        oy = yy + T.OTHER_MY
        ox, ow = ix + T.OTHER_ML, inner - T.OTHER_ML
        b.rect(ox, oy, ow, T.OTHER_H, T.R_CHIP, T.OTHER_BG)
        b.border(ox, oy, ow, T.OTHER_H, T.R_CHIP, 1.0, T.OTHER_BORDER)
        b.text(ox + 7, oy + (T.OTHER_H - T.LINE_H) * 0.5,
               ellipsize("补充说明写在下方输入框", T.FS, ow - 14), T.FS, T.OTHER_PH)
    b.y = y + h


def _radio(b, cx, cy, selected):
    r = T.RADIO_R
    b.items.append(("circ", cx, cy, r, T.RADIO_SEL if selected else T.RADIO_BG))
    b.items.append(("ring", cx, cy, r, T.RADIO_BW, T.RADIO_SEL if selected else T.RADIO_BORDER))
    if selected:
        b.items.append(("circ", cx, cy, T.RADIO_DOT_R, T.RADIO_DOT))


# --------------------------------------------------------------------------
def _result_section(c, b, m):
    st = c.state
    try:
        art = json.loads(m.artifacts_json or "{}")
    except Exception:
        art = {}
    y = b.y

    # 四 tab：等分，5px 上内边距，2px 下边框，选中项蓝下划线
    cw = b.w * 0.25
    for i, (label, key) in enumerate(_QTABS):
        tx = b.x + i * cw
        active = (st.result_tab == key)
        hot = (c.hover == "qt:%s" % key)
        col = T.QTABS_ON_LINE_TEXT if active else (T.TAB_HOVER if hot else T.TAB_IDLE)
        tw = text_width(label, T.FS_HEAD)
        b.text(tx + (cw - tw) * 0.5, y + T.QTAB_PAD_Y,
               ellipsize(label, T.FS_HEAD, cw - 4), T.FS_HEAD, col)
        if active:
            b.rect(tx, y + T.QTAB_H - T.QTAB_LINE, cw, T.QTAB_LINE, 0,
                   T.QTABS_ON_LINE)
        b.hit(tx, y, cw, T.QTAB_H, "qt:%s" % key)
    b.line(b.x, y + T.QTAB_H, b.x + b.w, y + T.QTAB_H, T.QTAB_RULE, T.QTABS_LINE)
    b.y = y + T.QTAB_H + T.QTAB_RULE
    b.space(T.PANE_PAD_T)

    pane = st.result_tab
    if pane == 'OBJECTS':
        objs = art.get("objects") or []
        bar_h = T.COL_H
        b.rect(b.x, b.y, b.w, bar_h, T.R_CARD, T.COL_BAR_BG)
        b.border(b.x, b.y, b.w, bar_h, T.R_CARD, 1.0, T.COL_BAR_BORDER)
        # 展开朝下、收起朝右（原型 .collapsebar .caret 旋转 -90deg）
        b.icon("caret" if st.show_result_list else "caret_right",
               b.x + 1 + T.COL_PAD_X, b.y + (bar_h - T.CARET_SZ) * 0.5,
               T.CARET_SZ, T.CARET)
        label = "已新增 %d 个对象" % len(objs)
        b.text(b.x + 1 + T.COL_PAD_X + T.CARET_SZ + T.COL_GAP,
               b.y + (bar_h - T.LINE_H) * 0.5, label, T.FS, T.COL_BAR_TEXT)
        rt = "收起" if st.show_result_list else "展开"
        rw = text_width(rt, T.FS_META)
        b.text(b.x + b.w - 1 - T.COL_PAD_X - rw,
               b.y + (bar_h - T.FS_META * T.LH) * 0.5, rt, T.FS_META, T.COL_BAR_RT)
        b.hit(b.x, b.y, b.w, bar_h, "collapse:objects")
        b.y += bar_h + T.OROW_GAP
        if st.show_result_list:
            for k, o in enumerate(objs):
                _object_row(c, b, o)
                if k < len(objs) - 1:
                    b.space(T.OROW_GAP)
    elif pane == 'PARAMS':
        flat = []
        for key in ("geo", "modifiers", "materials"):
            rows = art.get(key)
            if not rows:
                continue
            flat.append(("kgrp", key))
            if isinstance(rows[0], (list, tuple)):
                flat.extend(("row", r[0], r[1]) for r in rows)
            elif key == "modifiers":
                flat.extend(("row", str(r), "") for r in rows)
            else:
                flat.extend(("row", r[0], r[1]) for r in rows)
        _kv_list(b, flat)
    elif pane == 'SCRIPT':
        code = art.get("script") or ""
        all_lines = (code.split("\n") if code else [])
        lines = all_lines[:24]
        lh = T.FS_CODE * T.CODE_LH
        head = "共 %d 行 · 已脱敏" % len(all_lines)
        if len(all_lines) > len(lines):
            head = "共 %d 行 · 只显示前 %d 行" % (len(all_lines), len(lines))
        b.text(b.x + 1, b.y, head, T.FS_META, T.SBAR_DIM)
        b.y += T.FS_META * T.LH + 2
        h = 2 + T.CODE_PAD * 2 + len(lines) * lh
        b.rect(b.x, b.y, b.w, h, T.R_CARD, T.CODE_BG)
        b.border(b.x, b.y, b.w, h, T.R_CARD, 1.0, T.CODE_BORDER)
        yy = b.y + 1 + T.CODE_PAD
        for ln in lines:
            b.text(b.x + 8, yy, ellipsize(ln, T.FS_CODE, b.w - 16), T.FS_CODE, T.CODE_TEXT)
            yy += lh
        b.y += h
    else:
        rows = [("归属合集", getattr(m, "collection_name", "") or "—")]
        if getattr(m, "added_objects_str", ""):
            rows.append(("新增对象", m.added_objects_str))
        _kv_list(b, [("row", k, v) for k, v in rows])


def _kv_list(b, flat):
    """带分组的键值列表（.kgrp + .prow），最后一行不画分隔线。"""
    last = len(flat) - 1
    for i, it in enumerate(flat):
        if it[0] == "kgrp":
            if i > 0:
                b.space(T.KGRP_MT - T.KGRP_MB)
            b.text(b.x, b.y, _GROUP_CN.get(it[1], it[1]), T.FS_HEAD, T.KGRP)
            b.y += T.FS_HEAD * T.LH + T.KGRP_MB
        else:
            _param_row(b, it[1], it[2], last=(i == last))


_GROUP_CN = {"geo": "几何参数", "modifiers": "修改器", "materials": "材质"}


def _object_row(c, b, o):
    """原型 .orow：只有 1px 描边，没有底色（底色是 :hover 才加的）。"""
    tag = o.get("tag", "")
    sub = o.get("sub", "")
    h = 2 + T.OROW_PAD_Y * 2 + T.LINE_H + T.FS_META * T.LH
    y = b.y
    b.border(b.x, y, b.w, h, T.R_CHIP, 1.0, T.OROW_BORDER)
    ix = b.x + 1 + T.OROW_PAD_X
    rx = b.x + b.w - 1 - T.OROW_PAD_X
    ty = 11
    tw = text_width(tag, T.FS_META)
    tyw = (tw + 4 + 11) if tag else 0.0
    b.icon(_TYPE_ICON.get(tag, "cube"), ix, y + (h - T.OROW_ICON) * 0.5,
           T.OROW_ICON, T.OROW_ICON_C)
    if tag:
        b.icon(_TYPE_ICON.get(tag, "cube"), rx - tw, y + (h - 11) * 0.5, 11,
               T.OROW_TYPE)
        b.text(rx - tyw, y + (h - T.FS_META * T.LH) * 0.5, tag, T.FS_META, T.OROW_TYPE)
    nx = ix + T.OROW_ICON + T.OROW_IGAP
    nm = o.get("name", "")
    b.text(nx, y + 1 + T.OROW_PAD_Y,
           ellipsize(nm, T.FS, rx - tyw - 6 - nx), T.FS, T.OROW_NAME)
    if sub:
        b.text(nx, y + 1 + T.OROW_PAD_Y + T.LINE_H,
               ellipsize(sub, T.FS_META, rx - nx), T.FS_META, T.OROW_TYPE)
    b.y = y + h


def _param_row(b, k, v, last=False):
    """原型 .prow：46% / 1fr 两列栅格，值右对齐，末行无分隔线。"""
    v = str(v or "")
    y = b.y
    px = T.PROW_PAD_X
    inner = b.w - px * 2
    c1 = inner * T.PROW_COL1
    vx = b.x + px + c1 + T.PROW_GAP
    vw = inner - c1 - T.PROW_GAP
    ty = y + T.PROW_PAD_Y
    b.text(b.x + px, ty, ellipsize(str(k), T.FS, c1), T.FS, T.PROW_KEY)
    v = ellipsize(v, T.FS, vw)
    b.text(vx + vw - text_width(v, T.FS), ty, v, T.FS, T.PROW_VALUE)
    h = T.PROW_PAD_Y * 2 + T.LINE_H
    if not last:
        b.line(b.x, y + h, b.x + b.w, y + h, 1.0, T.PROW_LINE)
    b.y = y + h