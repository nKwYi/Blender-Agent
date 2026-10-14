"""自绘 UI 的运行时：draw handler、鼠标/滚轮交互、原生 textbox 代理框。

职责边界：
  * 这里只负责「什么时候画、画在哪、点了怎么办」
  * 长什么样完全由 panel.py 的显示列表决定
  * 中文输入仍然走 Blender 原生 textbox —— bpy.types.Event 没有任何 IME 组合字段，
    纯自绘会看不见正在输入的拼音，所以这一小块刻意保留原生控件
"""
import bpy
import json
import time

from . import panel as P
from . import theme as T
from .painter import Painter, render, hit_test

_HANDLERS = {}          # _key(space) -> handle
_REGION = {}            # _key(space) -> UI region（draw 回调里拿不到，只能存）
_CURRENT = {}           # _key(space) -> 最近一次 build() 的结果（命中测试用）
_HLEN = {}              # _key(space) -> 上次的历史长度（用来检测新消息）
_LAST_VISIBLE = {}      # _key(space) -> 上次 Panel.draw() 执行时间戳
_ACTIVE_CATEGORY = {}   # _key(space) -> 当前活动分类名称（由 tracker 登记）
SCROLL = {}             # _key(space) -> 滚动偏移；缺省表示「贴底」
HOVER = [""]
FOCUS = [False]
_DRAG = {"mode": ""}
MODAL = {"want": False, "on": False}

# ---- 诊断：绘图回调是每帧都跑的，一旦静默就永远查不出原因 --------------
# 旧的 _ERR["logged"] 只会打第一条 traceback，之后全部吞掉，等于把线索丢了。
# 现在：前 ERR_PRINT_LIMIT 条全打（含阶段名和 _draw 里的行号），之后只计数；
# 最后一条永远留在 _ERR["last"] / _DIAG 里，脚本可以随时来取。
ERR_PRINT_LIMIT = 20
_ERR = {"count": 0, "printed": 0, "last": "", "stage": "", "logged": False}
_STAGE = {"v": "none"}           # _draw() 走到哪一步炸的
_DIAG = {"cb": 0, "ok": 0, "build": 0, "render": 0,
         "early": {}, "snap": 0}


def _bump(reason):
    """记录一次提前返回（不是异常，但也足以让画面全白）。"""
    _DIAG["early"][reason] = _DIAG["early"].get(reason, 0) + 1


def _key(space):
    """所有字典的稳定键。

    不能用 id(space)：bpy.context.space_data 每次访问都会新建一个 Python wrapper，
    实测同一 space 连续取两次 id() 就不相等。后果有两处：
      * _REGION.get(id(space)) 大部分帧拿不到 region，_draw 直接提前返回（画面全白）
      * install() 每次 Panel.draw 都会注册一个「新」handler，一个帧画 N 遍
    实测 200 帧里 _REGION 攒出 15 个键、_CURRENT 只有 1 个，就是这个原因。
    as_pointer() 是底层 RNA 指针，同一个 space 不论包装几次都是同一个值。
    """
    try:
        return space.as_pointer()
    except (AttributeError, ReferenceError):
        return id(space)


def _snapshot():
    _DIAG["snap"] += 1
    if _DIAG["snap"] != 1 and _DIAG["snap"] % 200:
        return
    from .painter import STATS
    print("[deepseek-diag] cb=%d ok=%d region_keys=%d current_keys=%d "
          "items=%d batches=%d tris=%d err=%d early=%s last_stage=%s"
          % (_DIAG["cb"], _DIAG["ok"], len(_REGION), len(_CURRENT),
             STATS["items"], STATS["batches"], STATS["tris"],
             _ERR["count"], _DIAG["early"], _STAGE["v"]))

# 原生 textbox 代理框的对齐基准（实测校准，2026-10-10）
#
# NATIVE_HEADER_H —— 原生面板头**是包含在这个 UI region 里的**（不是排在 region 之外），
# 所以自绘内容必须整体从它下沿开始。证据：dev/out/fin2_top.png.png 宽 420 == region 宽，
# 是唯一一张 1:1 的截图；逐列扫描得到 y=0..27 是原生面板头底色 #383838，
# y=28 起才是自绘页签的 #1d1d1d —— 28px。同时 28 == UI_UNIT_Y * 1.4 == 20 * 1.4，
# 反证这张截图的 UI 缩放正好是 1.0（下面 NATIVE_ROW_H 的取值依据也是它）。
# 原来写 26.0 是早期估值，与 panel.NATIVE_HEAD_H 的 28 不一致，会把原生代理框顶高 2px。
NATIVE_HEADER_H = 28.0
#
# NATIVE_ROW_H —— UILayout 空行（enabled=False 的空 label 行，scale_y=1）的高度，
# 即 Blender 的 UI_UNIT_Y。Blender 5.2 已不再暴露 preferences.view.ui_unit_y
# （实测 dir(preferences.view) 里没有该属性），无头模式也建不出 UILayout 去量，
# 因此取 UI_UNIT_Y @ scale 1.0 = 20.0；scale=1.0 由上面同一张 1:1 截图的
# header=28 反证。ui.py 里是符号化引用，改这里即可生效。
NATIVE_ROW_H = 20.0


# ==========================================================================
# 生命周期与可见性
# ==========================================================================
def mark_visible(space=None):
    if space is None:
        space = getattr(bpy.context, "space_data", None)
    if space is not None:
        k = _key(space)
        _LAST_VISIBLE[k] = time.time()
        _ACTIVE_CATEGORY[k] = "AI 对话"


def set_active_category(category, space=None):
    if space is None:
        space = getattr(bpy.context, "space_data", None)
    if space is not None:
        _ACTIVE_CATEGORY[_key(space)] = category


def get_tab_strip_width():
    """Blender N 面板右侧垂直分类页签条宽，标准约 21px * ui_scale。"""
    s = getattr(T, "UI_SCALE", 1.0)
    return max(24.0, round(21.0 * s))


def is_panel_visible(space, region=None):
    """判断当前 3D 视图的 AI 对话面板是否真实可见且处于活动展开态。

    1. 视图必须是 VIEW_3D，且侧栏处于展开状态 (show_region_ui)；
    2. 如果 region 具有 active_panel_category 且明确属于其他 Tab，判定为不可见；
    3. 检查是否切换到了其他分类（由 tracker 面板登记）。
    """
    if space is None or getattr(space, "type", "") != 'VIEW_3D':
        return False
    if not getattr(space, "show_region_ui", True):
        return False

    if region is not None:
        cat = getattr(region, "active_panel_category", None)
        if cat and cat not in ("AI 对话", "对话", "设置", "UNSUPPORTED", ""):
            return False

    k = _key(space)
    active_cat = _ACTIVE_CATEGORY.get(k)
    if active_cat and active_cat not in ("AI 对话", "对话", "设置"):
        return False

    # 无头测试环境下没有持续的 GUI 渲染循环，放行以保证自动化测试执行
    if getattr(bpy.app, "background", False):
        return True

    if k not in _LAST_VISIBLE:
        return False

    return True


def install(space):
    key = _key(space)
    if key in _HANDLERS:
        return
    try:
        _HANDLERS[key] = space.draw_handler_add(draw_cb, (), 'UI', 'POST_PIXEL')
    except Exception as e:
        _ERR["count"] += 1
        _ERR["last"] = "[install] %r" % (e,)
        if _ERR["printed"] < ERR_PRINT_LIMIT:
            _ERR["printed"] += 1
        print("[deepseek] 自绘 UI 注册失败:", repr(e))


def ensure_installed(context):
    """从 Panel.draw 里装 draw handler。

    不能在 draw_cb 内部装 —— 回调没注册就永远不会触发，那是鸡生蛋死锁。
    Panel.draw 每帧随面板可见而执行，是最自然的挂载点。
    """
    space = getattr(context, "space_data", None)
    if space is None or space.type != 'VIEW_3D':
        return
    region = getattr(context, "region", None)
    if region is None or region.width <= 0:
        return
    _REGION[_key(space)] = region          # 指针跨帧稳定，可以一直用
    mark_visible(space)
    install(space)
    MODAL["want"] = True


def uninstall():
    for h in _HANDLERS.values():
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'UI', 'POST_PIXEL')
        except Exception:
            pass
    _HANDLERS.clear()
    _REGION.clear()
    _CURRENT.clear()
    _HLEN.clear()
    _LAST_VISIBLE.clear()
    _ACTIVE_CATEGORY.clear()
    SCROLL.clear()
    FOCUS[0] = False
    _DRAG["mode"] = ""


def tag():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()


def active_context():
    sc = bpy.context.scene
    if sc is None:
        return None, None, None
    st = getattr(sc, "deepseek_agent", None)
    if st is None:
        return None, None, None
    from . import ui as U
    return st, U.CONTROLLER.run, U


# ==========================================================================
# 绘制
# ==========================================================================
def draw_cb():
    _DIAG["cb"] += 1
    _STAGE["v"] = "00:enter"
    try:
        _draw()
    except Exception:
        _ERR["count"] += 1
        import traceback
        tb = traceback.format_exc()
        _ERR["last"] = tb
        _ERR["stage"] = _STAGE["v"]
        if _ERR["printed"] < ERR_PRINT_LIMIT:
            _ERR["printed"] += 1
            print("[deepseek] 自绘 UI 异常 #%d，阶段=%s"
                  % (_ERR["count"], _STAGE["v"]))
            print(tb)
        elif _ERR["count"] == ERR_PRINT_LIMIT + 1:
            print("[deepseek] 自绘 UI 异常已超过 %d 条，后续只计数（当前 %d）"
                  % (ERR_PRINT_LIMIT, _ERR["count"]))
    else:
        _ERR["last"] = ""
        _DIAG["ok"] += 1
    try:
        _snapshot()
    except Exception:
        pass


def _draw():
    space = bpy.context.space_data
    _STAGE["v"] = "10:space"
    if space is None or space.type != 'VIEW_3D':
        _bump("no_space")
        return
    # 注意：POST_PIXEL 阶段 context.region_data 返回的是 RegionView3D（视口子区域），
    # 没有 .width/.height。必须用安装时记下的 UI region。
    region = _REGION.get(_key(space))
    if region is None or region.width <= 0:
        _bump("no_region")
        return

    if not is_panel_visible(space, region):
        _bump("panel_hidden")
        _CURRENT.pop(_key(space), None)
        return

    st, run, U = active_context()
    if st is None:
        _bump("no_state")
        return
    key = _key(space)
    # 新消息进来自动回到底部：历史长度一变就把滚动重置为「贴底」哨兵
    # 动态应用当前 Blender UI 缩放
    T.apply_scale()

    # 留出右侧垂直分类页签条的宽度，绝不覆盖 N 面板原生 Tab！
    tab_w = get_tab_strip_width()
    panel_w = max(100.0, float(region.width) - tab_w)

    hlen = len(st.history)
    if _HLEN.get(key) != hlen:
        _HLEN[key] = hlen
        SCROLL.pop(key, None)
    _STAGE["v"] = "20:build"
    out = P.build(P.Ctx(st, run, U, panel_w, region.height,
                        hover=HOVER[0],
                        focus=bool(FOCUS[0]),
                        scroll=SCROLL.get(key),
                        settings_tab=(st.active_tab == 'SETTINGS')))
    _CURRENT[key] = out
    _DIAG["build"] += 1
    _STAGE["v"] = "30:render"
    render(Painter(region.width, region.height), out["items"])
    _DIAG["render"] += 1
    _STAGE["v"] = "40:done"


# ==========================================================================
# 原生 textbox 代理框的对齐数据
# ==========================================================================
def _probe_state():
    sc = bpy.context.scene
    st = getattr(sc, "deepseek_agent", None) if sc else None
    if st is not None:
        return st
    class _Fake(object):
        prompt_lines = 2
    return _Fake()


def _live_region():
    """当前 UI region。native_slot 要用它取真实宽度，不再写死 420。

    生产路径是 Panel.draw 里调用的，bpy.context.region 就是 UI region；
    但从 timer 里调时它是 None，所以再从 VIEW_3D area 里兜底找一次。
    """
    r = getattr(bpy.context, "region", None)
    if r is not None and getattr(r, "width", 0) > 0:
        return r
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type != 'VIEW_3D':
                    continue
                for reg in a.regions:
                    if reg.type == 'UI' and reg.width > 0:
                        return reg
    except Exception:
        pass
    return None


def native_slot(region_h, region_w=None):
    """给原生 Panel.draw 用：输入框上方/下方各要垫多少像素。"""
    if region_w is None:
        r = _live_region()
        region_w = getattr(r, "width", 0) if r is not None else 0
    try:
        W = float(region_w)
    except (TypeError, ValueError):
        W = 0.0
    if W <= 0.0:
        W = float(getattr(P, "NATIVE_W", 420.0))
    tab_w = get_tab_strip_width()
    panel_w = max(100.0, W - tab_w) if W > tab_w else W

    st = _probe_state()
    pills = None
    try:
        from . import ui as _U
        fn = getattr(_U, "quick_pills", None)
        if fn is not None and st is not None and getattr(st, "session_topic", "") is not None:
            pills = fn(st)
    except Exception:
        pills = None
    tx, ty, tw, th = P.composer_text_rect(panel_w, region_h, st, pills)
    header_h = NATIVE_HEADER_H * getattr(T, "UI_SCALE", 1.0)
    return {"top_gap": max(0.0, ty - header_h),
            "bottom_gap": max(0.0, region_h - (ty + th)),
            "w": tw}


# ==========================================================================
# 交互
# ==========================================================================
def _locate(context=None, event=None):
    """modal 事件里 context.region 才是「鼠标所在的那个 region」，
    mouse_region_x/y 相对它计算；不在 UI region 上就放弃。"""
    if context is None:
        context = bpy.context
    space = getattr(context, "space_data", None)
    region = getattr(context, "region", None)
    if space is None or space.type != 'VIEW_3D' or region is None:
        return None
    if getattr(region, "type", "") != "UI" or region.width <= 0:
        return None
    if not getattr(space, "show_region_ui", True):
        return None

    if event is None:
        return None

    mx = float(getattr(event, "mouse_region_x", 0))
    # Blender mouse_region_y 是距区域底部的像素，转为显示列表的逻辑 y（距顶部像素）
    my = float(region.height) - float(getattr(event, "mouse_region_y", 0))
    tab_w = get_tab_strip_width()
    panel_w = max(100.0, float(region.width) - tab_w)

    # 鼠标如果在右侧分类页签条上，或超出区域范围，放行给 Blender
    if mx >= panel_w or mx < 0 or my < 0 or my > float(region.height):
        return None

    return _key(space), space, mx, my


def handle_mousemove(context, event):
    loc = _locate(context, event)
    if loc is None:
        return False
    key, _sp, mx, my = loc
    out = _CURRENT.get(key)
    if out is None:
        return False
    prev = HOVER[0]
    HOVER[0] = hit_test(out["items"], mx, my) or ""
    if HOVER[0] != prev:
        tag()
    return True


def handle_wheel(context, event):
    loc = _locate(context, event)
    if loc is None:
        return False
    key, _sp, mx, my = loc
    out = _CURRENT.get(key)
    if out is None:
        return False
    sx, sy, sw, sh = out["stream_rect"]
    if not (sx - 4 <= mx <= sx + sw + 4 and sy <= my <= sy + sh):
        return False
    dy = int(getattr(event, "delta_y", 0) or 0)
    if dy == 0:
        dy = 1 if getattr(event, "mouse_y", 0) > my else -1
    # 从「当前生效值」继续滚，再写回显式偏移，从此不再自动贴底
    SCROLL[key] = max(0.0, out.get("scroll_eff", 0.0) + dy * 40.0)
    tag()
    return True


def _is_in_text_rect(key, mx, my):
    st, _run, U = active_context()
    if st is None:
        return False
    region = getattr(bpy.context, "region", None) or _REGION.get(key)
    if region is None or getattr(region, "width", 0) <= 0:
        return False
    pills = None
    try:
        fn = getattr(U, "quick_pills", None)
        if fn is not None:
            pills = list(fn(st))
    except Exception:
        pills = None
    try:
        tab_w = get_tab_strip_width()
        panel_w = max(100.0, float(region.width) - tab_w)
        tx, ty, tw, th = P.composer_text_rect(panel_w, region.height, st, pills)
        return (tx <= mx <= tx + tw and ty <= my <= ty + th)
    except Exception:
        return False


def handle_click(context, event):
    loc = _locate(context, event)
    if loc is None:
        return False
    key, _sp, mx, my = loc
    out = _CURRENT.get(key)
    if out is None:
        return False
    action = hit_test(out["items"], mx, my)

    # 点击命中了 "hover:inwrap" 或输入文本矩形区域
    in_text = (action == "hover:inwrap") or (_is_in_text_rect(key, mx, my) and action not in ("send", "grip"))
    if in_text:
        FOCUS[0] = True
        tag()
        return True

    # 点击了面板上的其他非输入区或按钮，设 FOCUS[0] = False
    FOCUS[0] = False

    if not action:
        tag()
        return False

    if action == "grip":
        begin_grip(event)
        return True

    end_grip()
    return dispatch(context, action)


def is_gripping():
    return bool(_DRAG.get("mode") == "grip")


def begin_grip(event):
    _DRAG["mode"] = "grip"
    _DRAG["y"] = getattr(event, "mouse_region_y", 0)
    _DRAG["armed"] = True


def end_grip(force=False):
    """收尾拖拽。并在 end_grip() 真正被松开或取消时重置 _DRAG["mode"] = ""。"""
    if not force and _DRAG.get("armed"):
        _DRAG["armed"] = False
        return
    _DRAG["mode"] = ""
    _DRAG["armed"] = False


def handle_grip(context, event):
    """把手拖拽：垂直位移换算成输入框行数。"""
    if not is_gripping():
        return False
    my = getattr(event, "mouse_region_y", None)
    if my is None:
        return False
    last_y = _DRAG.get("y", my)
    # my 从区域底部起算，向上拖动 my 变大，输入框行数增加
    dy = my - last_y
    step = max(10, round(12.0 * getattr(T, "UI_SCALE", 1.0)))
    if abs(dy) < step:
        return False
    _DRAG["y"] = my
    st, _r, _U = active_context()
    if st is None:
        return False
    lines = (st.prompt_lines or 2) + (1 if dy > 0 else -1)
    st.prompt_lines = max(T.TEXT_LINES_MIN, min(T.TEXT_LINES_MAX, lines))
    tag()
    return True


def handle_typing(context, event):
    """处理自绘输入框的键盘输入。"""
    st, _run, U = active_context()
    if st is None:
        return False

    if getattr(event, "value", "") == 'RELEASE':
        return False

    t = getattr(event, "type", "")
    ctrl = getattr(event, "ctrl", False)
    shift = getattr(event, "shift", False)

    if t == 'BACK_SPACE':
        st.prompt = st.prompt[:-1] if st.prompt else ""
        tag()
        return True

    if t in ('RET', 'NUMPAD_ENTER'):
        if shift or ctrl:
            st.prompt = (st.prompt or "") + "\n"
        else:
            U.dispatch_run_prompt(context)
            FOCUS[0] = False
        tag()
        return True

    if t == 'V' and ctrl:
        wm = getattr(context, "window_manager", None)
        cb = getattr(wm, "clipboard", "") or "" if wm else ""
        if cb:
            st.prompt = (st.prompt or "") + cb
        tag()
        return True

    if t == 'ESC':
        FOCUS[0] = False
        tag()
        return True

    uni = getattr(event, "unicode", "")
    if uni and uni.isprintable():
        st.prompt = (st.prompt or "") + uni
        tag()
        return True

    return False


def dispatch(context, action):
    st, run, U = active_context()
    if st is None:
        return False
    parts = action.split(":")

    if parts[0] == "act":
        op = parts[1]
        if op == "run":
            FOCUS[0] = False
            U.dispatch_run_prompt(context)
        elif op == "undo":
            bpy.ops.deepseek.undo_task()
        elif op == "new":
            bpy.ops.deepseek.new_task()
        elif op == "clear":
            bpy.ops.deepseek.clear()
        elif op == "confirm":
            bpy.ops.deepseek.submit_selection()
        elif op == "approve":
            bpy.ops.deepseek.approve()
        elif op == "toggle_code":
            st.show_approval_code = not st.show_approval_code
        elif op == "stop":
            try:
                bpy.ops.deepseek.stop()
            except Exception:
                if hasattr(U, "CONTROLLER"):
                    U.CONTROLLER.request_stop()
        elif op == "recommended":
            text = U.parse_interactive_options(_last_ai_text(st)).get("all_recommended", "")
            U.dispatch_run_prompt(context, text_override=text)
        tag()
        return True

    if parts[0] == "pill":
        bpy.ops.deepseek.quick_pill(action=":".join(parts[1:]))
        tag()
        return True

    if parts[0] == "send":
        FOCUS[0] = False
        U.dispatch_run_prompt(context)
        tag()
        return True

    if parts[0] == "tab":
        try:
            context.region.active_panel_category = "设置" if parts[1] == "1" else "AI 对话"
        except Exception:
            pass
        if parts[1] == "1":
            st.active_tab = 'SETTINGS'
        else:
            st.active_tab = 'CHAT'
        tag()
        return True

    if parts[0] == "qt":
        st.result_tab = parts[1]
        tag()
        return True

    if parts[0] == "collapse":
        st.show_result_list = not st.show_result_list
        tag()
        return True

    if parts[0] == "opt":
        return _dispatch_option(st, U, parts)

    if parts[0] == "other":
        key = parts[1] if len(parts) > 1 else ""
        st.other_open_q = "" if st.other_open_q == key else key
        tag()
        return True

    if parts[0] == "grip":
        return True

    return False


def _option_label(st, U, qi, oi):
    """opt:<题号>:<选项号> 指向的选项文案。

    panel.py 的 qi 是**每条 AI 消息内部**的题号（对它 parse_interactive_options
    出来的 questions 列表做 enumerate），消息本身不在 id 里，所以倒着翻历史，
    取第一条题号够用的 AI 消息。

    取值口径必须和 panel.py 的 _question_group 一模一样：
    o.get("label") or o.get("value") or ""。两边差一个字，选中态就对不上，
    画面不会高亮。
    """
    for i in range(len(st.history) - 1, -1, -1):
        m = st.history[i]
        if getattr(m, "role", "") == "你":
            continue
        try:
            qs = (U.parse_interactive_options(getattr(m, "text", "") or "")
                  .get("questions") or [])
        except Exception:
            continue
        if qi >= len(qs):
            continue
        opts = qs[qi].get("options") or []
        if oi >= len(opts):
            continue
        o = opts[oi]
        val = o.get("label") or o.get("value") or ""
        if val:
            return str(val)
    return ""


def _dispatch_option(st, U, parts):
    """单选语义，和原生 DEEPSEEK_OT_select_option(is_multi=False) 对齐。

    曾经这里只取 parts[1]，把 "opt:0:1" 当成两段：题号 0 丢了，选项号 1 被
    当成题号去切 other_open_q —— 结果是点任何选项都只是开「其他」框，
    selected_options_json 永远是 {}，确认选择只能退化成「全部按推荐」。
    """
    try:
        qi = int(parts[1])
        oi = int(parts[2])
    except (IndexError, ValueError):
        return False
    label = _option_label(st, U, qi, oi)
    if not label:
        return False
    key = str(qi)
    try:
        sel = json.loads(st.selected_options_json or "{}")
    except Exception:
        sel = {}
    if not isinstance(sel, dict):
        sel = {}
    cur = sel.get(key)
    cur = cur if isinstance(cur, list) else []
    if cur == [label]:
        sel[key] = []            # 再点已选中的那一条 = 取消
    else:
        sel[key] = [label]       # 单选：换一条就是替换，不追加
    st.selected_options_json = json.dumps(sel, ensure_ascii=False)
    tag()
    return True


def _last_ai_text(st):
    for i in range(len(st.history) - 1, -1, -1):
        if st.history[i].role != "你":
            return st.history[i].text
    return ""