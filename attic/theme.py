"""自绘 UI 的设计令牌。

数值逐条对应 blender_ui_figma_prototype.html 的 CSS，1 CSS px = 1 GPU 像素。
改这里就能整体换皮，不要把颜色散落到各个组件里。
"""


def hx(s, a=1.0):
    """#rrggbb -> (r, g, b, a)，0..1 浮点。"""
    s = s.lstrip("#")
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0, a)


# ---- 面板骨架 ---------------------------------------------------------------
PANEL_BG = hx("3d3d3d")
PANEL_BORDER = hx("4a4a4a")
COMPOSER_BG = hx("3a3a3a")
COMPOSER_TOPLINE = hx("4a4a4a")

# ---- 面板头 ----------------------------------------------------------------
HEAD_TEXT = hx("e6e6e6")      # 继承 .bld 的正文色
HEAD_DOTS = hx("9a9a9a")      # .bld-head .dots

# ---- 页签 ------------------------------------------------------------------
TABS_BG = hx("1d1d1d")
TABS_ON = hx("303030")
TABS_ON_TEXT = hx("ffffff")
TAB_IDLE = hx("989898")
TAB_HOVER = hx("dcdcdc")

# ---- 会话状态栏 ------------------------------------------------------------
SBAR_BG = hx("1d1d1d")
SBAR_BORDER = hx("3d3d3d")
SBAR_TEXT = hx("e6e6e6")
SBAR_DIM = hx("8a8a8a")

# ---- 消息流滚动条（.stream::-webkit-scrollbar）---------------------------
SCROLL_THUMB = hx("545454")
SCROLL_THUMB_HOVER = hx("6a6a6a")
SCROLL_W = 8.0

# ---- 消息 ------------------------------------------------------------------
USER_BG = hx("1d1d1d")
USER_BORDER = hx("3d3d3d")
USER_META = hx("8a8a8a")
AI_HEAD = hx("cfcfcf")
AI_TEXT = hx("e6e6e6")
AI_TEXT_DIM = hx("9a9a9a")
AI_TIME = hx("7a7a7a")

# ---- 单选组 ----------------------------------------------------------------
QG_BG = hx("1d1d1d")
QG_BORDER = hx("3d3d3d")
QG_TITLE = hx("b9cfe6")
QROW_TEXT = hx("c4c4c4")
QROW_HOVER_BG = hx("262626")
QROW_HOVER_TEXT = hx("e6e6e6")
QROW_SEL_BG = hx("2c3c52")
QROW_SEL_TEXT = hx("eaf1fa")
RADIO_BORDER = hx("6a6a6a")
RADIO_BG = hx("2a2a2a")
RADIO_SEL = hx("4772b3")
RADIO_DOT = hx("ffffff")
QTAG = hx("8a8a8a")
QTAG_SEL = hx("9db8d8")

OTHER_BG = hx("181818")
OTHER_BORDER = hx("4772b3")
OTHER_PH = hx("6a6a6a")

# ---- 检查清单 --------------------------------------------------------------
CKL_BG = hx("222222")
CKL_BORDER = hx("383838")
CKL_TEXT = hx("b8cfb8")
CKL_ICON = hx("a8c8a8")

# ---- 折叠条 ----------------------------------------------------------------
COL_BAR_BG = hx("222222")
COL_BAR_BORDER = hx("383838")
COL_BAR_TEXT = hx("cfcfcf")
COL_BAR_HOVER = hx("2a2a2a")
COL_BAR_RT = hx("8a8a8a")
CARET = hx("c8c8c8")

# ---- 结果区 ----------------------------------------------------------------
QTABS_LINE = hx("4a4a4a")
QTABS_ON_LINE = hx("4772b3")
QTABS_ON_LINE_TEXT = hx("ffffff")
OROW_BORDER = hx("333333")
OROW_HOVER = hx("252525")
OROW_ICON_C = hx("c9c9c9")
OROW_NAME = hx("e8e8e8")
OROW_TYPE = hx("8a8a8a")
PROW_LINE = hx("2f2f2f")
PROW_VALUE = hx("e6e6e6")
KGRP = hx("9db8d8")
CODE_BG = hx("181818")
CODE_BORDER = hx("333333")
CODE_TEXT = hx("a8b8c8")

# ---- 输入区 ----------------------------------------------------------------
IN_BG = hx("1d1d1d")
IN_BORDER = hx("3d3d3d")
IN_FOCUS = hx("4772b3")
IN_TEXT = hx("e6e6e6")
IN_PH = hx("6a6a6a")
SEND_BG = hx("545454")
SEND_HOVER = hx("616161")
SEND_BORDER = hx("3d3d3d")
SEND_ICON = hx("ffffff")
GRIP = hx("8a8a8a")
GRIP_HOVER = hx("b9cfe6")
GRIP_HINT = hx("7a7a7a")

# ---- 底部按钮 --------------------------------------------------------------
BTN_TOP = hx("5c5c5c")
BTN_BOTTOM = hx("484848")
BTN_BORDER = hx("3d3d3d")
BTN_TEXT = hx("ffffff")
BTN_HOVER = 1.16              # CSS filter: brightness
BTN_DISABLED_TOP = hx("4a4a4a")
BTN_DISABLED_BOTTOM = hx("404040")
BTN_DISABLED_TEXT = hx("8a8a8a")

# ---- 快捷胶囊 --------------------------------------------------------------
CHIP_BG = hx("4a4a4a")
CHIP_BORDER = hx("3d3d3d")
CHIP_TEXT = hx("dcdcdc")
CHIP_HOVER = hx("565656")

# ---- 思考动效 --------------------------------------------------------------
THINK_DOT = hx("9db8d8")
THINK_RING = hx("9db8d8", 0.55)

# ---- 状态卡 ----------------------------------------------------------------
# PARTIAL 严禁标红：铁律是 alert 只留给 FAILED，所以 PARTIAL 走中性灰。
ST_WARN_BG = hx("232323")
ST_WARN_BORDER = hx("3a3a3a")
ST_WARN_TEXT = hx("d0d0d0")
ST_WARN_DIM = hx("8a8a8a")
ST_FAIL_BG = hx("33191a")
ST_FAIL_BORDER = hx("7d2b2b")
ST_FAIL_TEXT = hx("ff9a9a")
ST_FAIL_DIM = hx("d08a8a")
ST_APPROVE_BG = hx("2a2416")
ST_APPROVE_BORDER = hx("7a6428")
ST_APPROVE_TEXT = hx("e8d8a0")

# ---- 字体与度量（支持 Blender UI 缩放）-------------------------------------
def get_ui_scale():
    try:
        import bpy
        scale = getattr(bpy.context.preferences.system, "ui_scale", None)
        if scale is not None and scale > 0.05:
            return float(scale)
    except Exception:
        pass
    try:
        import bpy
        scale = getattr(bpy.context.preferences.view, "ui_scale", None)
        if scale is not None and scale > 0.05:
            return float(scale)
    except Exception:
        pass
    return 1.0


UI_SCALE = 1.0

# 模块级尺寸变量声明（先由 apply_scale(1.0) 初始化）
FS = 11.0
FS_HEAD = 10.5
FS_META = 10.0
FS_TINY = 9.5
FS_CODE = 9.5
LH = 1.5
LINE_H = 16.5
LINE_H_SM = 15.75
LINE_H_XS = 15.0
CODE_LH = 1.6

R_PANEL = 4.0
R_CARD = 4.0
R_CHIP = 3.0
R_SEND = 3.0
R_BTN = 4.0

PAD_X = 7.0
GAP = 9.0

HEAD_H = 26.5
HEAD_PAD_X = 8.0
HEAD_ICON = 11.0

TABS_H = 26.5
TABS_PAD = 2.0
TABS_GAP = 2.0
TABS_IGAP = 5.0
TAB_H = 22.5
TAB_ICON = 12.0

SBAR_H = 46.5
SBAR_PAD_X = 8.0
SBAR_PAD_Y = 6.0
SBAR_ROW_GAP = 1.0

AHEAD_H = 15.75
AMSG_GAP = 3.0
AMSG_ICON_GAP = 5.0
AI_ICON = 12.0
USER_PAD_X = 8.0
USER_PAD_Y = 6.0
USER_META_H = 15.0
USER_META_GAP = 5.0
USER_META_MB = 2.0
USER_MAXW = 0.86

QG_PAD_X = 8.0
QG_PAD_Y = 7.0
QG_TITLE_H = 17.5
QROW_H = 21.5
QROW_GAP = 5.0
QROW_PAD_X = 4.0
QROW_IGAP = 7.0
RADIO_R = 5.5
RADIO_BW = 1.5
RADIO_DOT_R = 2.0
OTHER_ML = 18.0
OTHER_MY = 2.0
OTHER_H = 26.0

CKL_PAD_X = 8.0
CKL_PAD_Y = 6.0
CKL_GAP = 3.0
CKL_ICON_SZ = 12.0

COL_H = 26.5
COL_PAD_X = 6.0
COL_GAP = 6.0
CARET_SZ = 10.0

QTAB_H = 22.75
QTAB_PAD_Y = 5.0
QTAB_LINE = 2.0
QTAB_RULE = 1.0
PANE_PAD_T = 7.0
OROW_PAD_X = 6.0
OROW_PAD_Y = 4.0
OROW_ICON = 13.0
OROW_IGAP = 7.0
OROW_GAP = 5.0
PROW_PAD_X = 4.0
PROW_PAD_Y = 2.5
PROW_GAP = 7.0
PROW_COL1 = 0.46
PROW_KEY = hx("9a9a9a")
KGRP_MT = 5.0
KGRP_MB = 1.0
CODE_PAD = 8.0

COMPOSER_BORDER_TOP = 1.0
COMPOSER_PAD_T = 6.0
COMPOSER_PAD_X = 7.0
COMPOSER_PAD_B = 7.0
COMPOSER_GAP = 5.0
CHIP_H = 22.0
CHIP_PAD_X = 8.0
QUICK_GAP = 4.0
QUICK_ROW_GAP = 4.0
BTN_H = 28.5
BTN_ICON = 11.0
BTN_GAP = 5.0
SEND_SIZE = 26.0
SEND_MR = 6.0
GRIP_SIZE = 18.0
GRIP_STRIPE_W = 1.6
TEXT_MIN_H = 34.0
TEXT_PAD_X = 8.0
TEXT_PAD_Y = 7.0
TEXT_LINES_DEFAULT = 2
TEXT_LINES_MIN = 1
TEXT_LINES_MAX = 8

THINK_SLOT = 18.5
THINK_DOT_R = 1.75
THINK_DOT_GAP = 4.0
THINK_DELAY = 0.16
THINK_LIFT = 4.0
THINK_RING_R = 10.5
THINK_RING_W = 1.0
THINK_PERIOD = 1.25
THINK_PULSE = 1.6

NATIVE_TEXT_H = 48.0


def apply_scale(s=None):
    """根据当前 Blender 的 UI 缩放比例重设所有尺寸令牌。"""
    global UI_SCALE
    global FS, FS_HEAD, FS_META, FS_TINY, FS_CODE, LH, LINE_H, LINE_H_SM, LINE_H_XS, CODE_LH
    global R_PANEL, R_CARD, R_CHIP, R_SEND, R_BTN, PAD_X, GAP
    global HEAD_H, HEAD_PAD_X, HEAD_ICON, TABS_H, TABS_PAD, TABS_GAP, TABS_IGAP, TAB_H, TAB_ICON
    global SBAR_H, SBAR_PAD_X, SBAR_PAD_Y, SBAR_ROW_GAP
    global AHEAD_H, AMSG_GAP, AMSG_ICON_GAP, AI_ICON, USER_PAD_X, USER_PAD_Y, USER_META_H, USER_META_GAP, USER_META_MB, USER_MAXW
    global QG_PAD_X, QG_PAD_Y, QG_TITLE_H, QROW_H, QROW_GAP, QROW_PAD_X, QROW_IGAP, RADIO_R, RADIO_BW, RADIO_DOT_R, OTHER_ML, OTHER_MY, OTHER_H
    global CKL_PAD_X, CKL_PAD_Y, CKL_GAP, CKL_ICON_SZ, COL_H, COL_PAD_X, COL_GAP, CARET_SZ
    global QTAB_H, QTAB_PAD_Y, QTAB_LINE, QTAB_RULE, PANE_PAD_T, OROW_PAD_X, OROW_PAD_Y, OROW_ICON, OROW_IGAP, OROW_GAP
    global PROW_PAD_X, PROW_PAD_Y, PROW_GAP, PROW_COL1, PROW_KEY, KGRP_MT, KGRP_MB, CODE_PAD
    global COMPOSER_BORDER_TOP, COMPOSER_PAD_T, COMPOSER_PAD_X, COMPOSER_PAD_B, COMPOSER_GAP
    global CHIP_H, CHIP_PAD_X, QUICK_GAP, QUICK_ROW_GAP, BTN_H, BTN_ICON, BTN_GAP
    global SEND_SIZE, SEND_MR, GRIP_SIZE, GRIP_STRIPE_W, TEXT_MIN_H, TEXT_PAD_X, TEXT_PAD_Y
    global TEXT_LINES_DEFAULT, TEXT_LINES_MIN, TEXT_LINES_MAX
    global THINK_SLOT, THINK_DOT_R, THINK_DOT_GAP, THINK_DELAY, THINK_LIFT, THINK_RING_R, THINK_RING_W, THINK_PERIOD, THINK_PULSE
    global NATIVE_TEXT_H

    if s is None:
        s = get_ui_scale()
    s = float(s)
    if s <= 0.0:
        s = 1.0
    UI_SCALE = s

    # 基准字号与尺寸（在 1.0x 缩放下保持基准测试 100% 吻合；高分屏下乘上 s）
    b_fs = 12.0 if s > 1.05 else 11.0
    b_head = 11.5 if s > 1.05 else 10.5
    b_meta = 11.0 if s > 1.05 else 10.0
    b_tiny = 10.0 if s > 1.05 else 9.5
    b_code = 10.5 if s > 1.05 else 9.5

    FS = round(b_fs * s, 1)
    FS_HEAD = round(b_head * s, 1)
    FS_META = round(b_meta * s, 1)
    FS_TINY = round(b_tiny * s, 1)
    FS_CODE = round(b_code * s, 1)
    LH = 1.5
    LINE_H = FS * LH
    LINE_H_SM = FS_HEAD * LH
    LINE_H_XS = FS_META * LH
    CODE_LH = 1.6

    R_PANEL = round(4.0 * s, 1)
    R_CARD = round(4.0 * s, 1)
    R_CHIP = round(3.0 * s, 1)
    R_SEND = round(3.0 * s, 1)
    R_BTN = round(4.0 * s, 1)

    PAD_X = round(7.0 * s, 1)
    GAP = round(9.0 * s, 1)

    HEAD_H = round(26.5 * s, 1)
    HEAD_PAD_X = round(8.0 * s, 1)
    HEAD_ICON = round(11.0 * s, 1)

    TABS_H = round(26.5 * s, 1)
    TABS_PAD = round(2.0 * s, 1)
    TABS_GAP = round(2.0 * s, 1)
    TABS_IGAP = round(5.0 * s, 1)
    TAB_H = round(22.5 * s, 1)
    TAB_ICON = round(12.0 * s, 1)

    SBAR_H = round(46.5 * s, 1)
    SBAR_PAD_X = round(8.0 * s, 1)
    SBAR_PAD_Y = round(6.0 * s, 1)
    SBAR_ROW_GAP = round(1.0 * s, 1)

    AHEAD_H = LINE_H_SM
    AMSG_GAP = round(3.0 * s, 1)
    AMSG_ICON_GAP = round(5.0 * s, 1)
    AI_ICON = round(12.0 * s, 1)
    USER_PAD_X = round(8.0 * s, 1)
    USER_PAD_Y = round(6.0 * s, 1)
    USER_META_H = round(15.0 * s, 1)
    USER_META_GAP = round(5.0 * s, 1)
    USER_META_MB = round(2.0 * s, 1)
    USER_MAXW = 0.86

    QG_PAD_X = round(8.0 * s, 1)
    QG_PAD_Y = round(7.0 * s, 1)
    QG_TITLE_H = LINE_H + round(1.0 * s, 1)
    QROW_H = round(21.5 * s, 1)
    QROW_GAP = round(5.0 * s, 1)
    QROW_PAD_X = round(4.0 * s, 1)
    QROW_IGAP = round(7.0 * s, 1)
    RADIO_R = round(5.5 * s, 1)
    RADIO_BW = round(1.5 * s, 1)
    RADIO_DOT_R = round(2.0 * s, 1)
    OTHER_ML = round(18.0 * s, 1)
    OTHER_MY = round(2.0 * s, 1)
    OTHER_H = round(26.0 * s, 1)

    CKL_PAD_X = round(8.0 * s, 1)
    CKL_PAD_Y = round(6.0 * s, 1)
    CKL_GAP = round(3.0 * s, 1)
    CKL_ICON_SZ = round(12.0 * s, 1)

    COL_H = round(26.5 * s, 1)
    COL_PAD_X = round(6.0 * s, 1)
    COL_GAP = round(6.0 * s, 1)
    CARET_SZ = round(10.0 * s, 1)

    QTAB_H = round(22.75 * s, 1)
    QTAB_PAD_Y = round(5.0 * s, 1)
    QTAB_LINE = round(2.0 * s, 1)
    QTAB_RULE = round(1.0 * s, 1)
    PANE_PAD_T = round(7.0 * s, 1)
    OROW_PAD_X = round(6.0 * s, 1)
    OROW_PAD_Y = round(4.0 * s, 1)
    OROW_ICON = round(13.0 * s, 1)
    OROW_IGAP = round(7.0 * s, 1)
    OROW_GAP = round(5.0 * s, 1)
    PROW_PAD_X = round(4.0 * s, 1)
    PROW_PAD_Y = round(2.5 * s, 1)
    PROW_GAP = round(7.0 * s, 1)
    PROW_COL1 = 0.46
    KGRP_MT = round(5.0 * s, 1)
    KGRP_MB = round(1.0 * s, 1)
    CODE_PAD = round(8.0 * s, 1)

    COMPOSER_BORDER_TOP = round(1.0 * s, 1)
    COMPOSER_PAD_T = round(6.0 * s, 1)
    COMPOSER_PAD_X = round(7.0 * s, 1)
    COMPOSER_PAD_B = round(7.0 * s, 1)
    COMPOSER_GAP = round(5.0 * s, 1)
    CHIP_H = round(22.0 * s, 1)
    CHIP_PAD_X = round(8.0 * s, 1)
    QUICK_GAP = round(4.0 * s, 1)
    QUICK_ROW_GAP = round(4.0 * s, 1)
    BTN_H = round(28.5 * s, 1)
    BTN_ICON = round(11.0 * s, 1)
    BTN_GAP = round(5.0 * s, 1)
    SEND_SIZE = round(26.0 * s, 1)
    SEND_MR = round(6.0 * s, 1)
    GRIP_SIZE = round(18.0 * s, 1)
    GRIP_STRIPE_W = round(1.6 * s, 1)
    TEXT_MIN_H = round(34.0 * s, 1)
    TEXT_PAD_X = round(8.0 * s, 1)
    TEXT_PAD_Y = round(7.0 * s, 1)
    TEXT_LINES_DEFAULT = 2
    TEXT_LINES_MIN = 1
    TEXT_LINES_MAX = 8

    THINK_SLOT = round(18.5 * s, 1)
    THINK_DOT_R = round(1.75 * s, 1)
    THINK_DOT_GAP = round(4.0 * s, 1)
    THINK_DELAY = 0.16
    THINK_LIFT = round(4.0 * s, 1)
    THINK_RING_R = round(10.5 * s, 1)
    THINK_RING_W = round(1.0 * s, 1)
    THINK_PERIOD = 1.25
    THINK_PULSE = 1.6

    NATIVE_TEXT_H = TEXT_MIN_H + 2 * TEXT_PAD_Y


# 初始化应用默认缩放
apply_scale(1.0)