# -*- coding: utf-8 -*-
"""自绘面板「新组件」的无头断言。

test_panel_layout.py 钉的是布局骨架（越界/命中/滚动/绘制数据形状）。
这个文件补的是后来加的那批组件级断言：思考动效、胶囊折行、渐变分带、
斜纹把手、颜色插值、输入区几何、结果键值表、忙碌判定。

只测函数，不开 GUI；全部断言都要能被变异测试打红。

已知实现缺陷走 XFAIL 通道（不是 FAIL，也不是悄悄按现状锁死）：
panel.py 归别人改，这里只登记，修好了会自动翻成 XPASS。
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda                      # noqa: E402
from blender_deepseek_agent import panel as P            # noqa: E402
from blender_deepseek_agent import theme as T            # noqa: E402
from blender_deepseek_agent import ui as U               # noqa: E402
from blender_deepseek_agent.state import Phase, Run, ToolCall, BUSY  # noqa: E402

FAILS = []
XFAILS = []
XPASSES = []
OK = [0]
SECTION = ["?"]


def sect(name):
    SECTION[0] = name


def ck(cond, msg):
    if cond:
        OK[0] += 1
    else:
        FAILS.append("[%s] %s" % (SECTION[0], msg))


def xfail(repro, msg):
    """repro=True -> 缺陷仍在（预期），repro=False -> 已被修好（XPASS）。"""
    if repro:
        XFAILS.append("[%s] %s" % (SECTION[0], msg))
    else:
        XPASSES.append("[%s] %s" % (SECTION[0], msg))


def near(a, b, eps=1e-6):
    return abs(a - b) <= eps


def close_rgb(a, b, eps=1e-6):
    return (len(a) >= 3 and len(b) >= 3
            and all(near(a[i], b[i], eps) for i in range(3)))


def close_col(a, b, eps=1e-6):
    return close_rgb(a, b, eps) and len(a) == len(b) and near(a[3], b[3], eps)


if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs", "model": "MiniMax-M3.1-Flash-Preview",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

state = bpy.context.scene.deepseek_agent
W, H = 420.0, 1756.0
state.prompt = ""
state.prompt_lines = 2
state.shown_count = 50
state.result_tab = "OBJECTS"
state.busy = False

done_run = Run("做个水杯")
done_run.phase = Phase.COMPLETED
done_run.rounds = 3
done_run.elapsed = 41.2
done_run.calls = [ToolCall("1", "get_scene_info")]
U.CONTROLLER.run = done_run

# 思考动效要干净地「出现/消失」，所以历史里不放交互卡片（卡片自带 radio 圆点）
state.history.clear()
state.notes.clear()
U.push_history(state, "你", "帮我做个水杯", run=None)
U.push_history(state, "AI", "先确认口径和材质，我这就建模。", run=None)


def build(run=None, w=W, h=H, **kw):
    c = P.Ctx(state, run, U, w, h, **kw)
    return P.build(c)


def new_b(x=20.0, w=380.0, y=0.0):
    return P.B([], x, w, y)


# ================================================================= 1. _mix / _bright
sect("mix")
A = T.hx("5c5c5c")
B = T.hx("484848")
BRIGHT = T.hx("c8c8c8")            # 0.784，×2 越界，用来验证 1.0 处的钳制

ck(close_col(P._mix(A, B, 0.0), A), "_mix(a,b,0) 不等于 a：%s" % (P._mix(A, B, 0.0),))
ck(close_col(P._mix(A, B, 1.0), B), "_mix(a,b,1) 不等于 b：%s" % (P._mix(A, B, 1.0),))
ck(P._mix(A, B, 0.0) == A, "_mix(a,b,0) 不是逐分量精确相等")
ck(close_col(P._mix(A, A, 0.5), A), "_mix 同色中点不自洽")
_m = P._mix(A, B, 0.5)
ck(near(_m[0], (A[0] + B[0]) * 0.5) and near(_m[3], A[3]),
   "_mix 中点不是算术平均：%s" % (_m,))
# 实现既不钳制也不抛错，是线性外推 —— 按实现断言（t=-1 -> 2a-b，t=2 -> 2b-a）
for _t in (-1.0, 2.0):
    _got = P._mix(A, B, _t)
    _exp = tuple(A[i] + (B[i] - A[i]) * _t for i in range(4))
    ck(close_col(_got, _exp, 1e-9),
       "_mix 在越界 t=%s 时不是线性外推：%s != %s" % (_t, _got, _exp))

sect("bright")
ck(all(near(v, 0.0) for v in P._bright(A, 0.0)[:3]), "_bright(k=0) 不是全黑")
ck(close_col(P._bright(A, 1.0), A), "_bright(k=1) 不是原色：%s" % (P._bright(A, 1.0),))
_k2 = P._bright(BRIGHT, 2.0)
ck(all(near(v, 1.0) for v in _k2[:3]), "_bright 没有钳在 1.0：%s" % (_k2,))
_k9 = P._bright(BRIGHT, 9.0)
ck(all(0.0 <= v <= 1.0 for v in _k9[:3]), "_bright 跑出 [0,1]：%s" % (_k9,))
ck(P._bright(A, 1.0)[3] == A[3] and P._bright(A, 0.0)[3] == A[3],
   "_bright 动了 alpha")
_mono = True
_prev = -1.0
for _i in range(0, 41):
    _v = P._bright(A, _i / 20.0)[0]
    if _v < _prev - 1e-12:
        _mono = False
    _prev = _v
ck(_mono, "_bright 红分量随 k 非单调")

# ================================================================= 2. _think_phase
sect("think_phase")
ck(near(P._think_phase(0.0)[0], 0.0) and near(P._think_phase(0.0)[1], 0.45),
   "t=0 不是「静止半透」：%s" % (P._think_phase(0.0),))
ck(near(P._think_phase(0.30)[0], -T.THINK_LIFT) and near(P._think_phase(0.30)[1], 1.0),
   "t=0.30 不是「抬满 + 实心」：%s" % (P._think_phase(0.30),))
ck(near(P._think_phase(1.0)[0], 0.0) and near(P._think_phase(1.0)[1], 0.45),
   "t=1.0 没回到静止半透：%s" % (P._think_phase(1.0),))

_range_ok = True
for _i in range(0, 101):
    _dy, _a = P._think_phase(_i / 100.0)
    if not (-T.THINK_LIFT - 1e-9 <= _dy <= 1e-9) or not (0.0 <= _a <= 1.0 + 1e-9):
        _range_ok = False
ck(_range_ok, "_think_phase 在 [0,1] 内跑出了 [-LIFT,0] / [0,1]")

# 分段点 0.30 / 0.60 两侧必须连续，否则动画每周期闪一下
_cont_ok = True
for _seam in (0.30, 0.60):
    _lo = P._think_phase(_seam - 1e-9)
    _hi = P._think_phase(_seam + 1e-9)
    if not (near(_lo[0], _hi[0], 1e-6) and near(_lo[1], _hi[1], 1e-6)):
        _cont_ok = False
ck(_cont_ok, "_think_phase 在 0.30/0.60 分段点不连续（动画会闪）")
ck(any(P._think_phase(_i / 100.0)[0] < -T.THINK_LIFT * 0.9 for _i in range(101)),
   "_think_phase 从没抬到 THINK_LIFT 附近，看不出抬落")

# ================================================================= 3. _thinking_msg
sect("think_msg")
think_run = Run("做个水杯")
think_run.phase = Phase.TOOL_RUNNING
think_run.elapsed = 7.4
think_run.calls = [ToolCall("1", "get_scene_info"), ToolCall("2", "execute_blender_code")]
U.CONTROLLER.run = think_run

_b = new_b()
try:
    P._thinking_msg(P.Ctx(state, think_run, U, W, H), _b, think_run)
    _no_exc = True
except Exception as e:                                        # noqa: BLE001
    _no_exc = False
    XFAILS.append("[think_msg] _thinking_msg 抛异常：%r" % (e,))
ck(_no_exc, "_thinking_msg 抛异常")

_circ = [it for it in _b.items if it[0] == "circ"]
_ring = [it for it in _b.items if it[0] == "ring"]
ck(len(_circ) == 3, "思考动效不是 3 个圆点，实际 %d" % len(_circ))
ck(len(_ring) >= 1, "思考动效缺少外圈脉冲环")
if len(_circ) == 3:
    ck(all(near(it[3], T.THINK_DOT_R) for it in _circ),
       "圆点半径不是 THINK_DOT_R：%s" % [round(it[3], 3) for it in _circ])
    ck(all(close_rgb(it[4], T.THINK_DOT) for it in _circ),
       "圆点颜色不是 THINK_DOT(#9db8d8)：%s" % [it[4] for it in _circ])
    ck(all(0.0 < it[4][3] <= 1.0 + 1e-9 for it in _circ), "圆点 alpha 越界")
    _xs = [it[1] for it in _circ]
    ck(_xs == sorted(_xs) and _xs[-1] > _xs[0], "三个圆点没有横排开：%s" % _xs)
    ck(all(near(it[1] - _xs[0], _i * (T.THINK_DOT_R * 2 + T.THINK_DOT_GAP), 1e-6)
           for _i, it in enumerate(_circ)),
       "圆点间距不是 THINK_DOT_GAP：%s" % [round(v, 2) for v in _xs])
    ck(_xs[0] >= _b.x - 0.01 and _xs[-1] + T.THINK_DOT_R <= _b.x + _b.w + 0.01,
       "圆点横向跑出内容框：%s vs [%s,%s]" % ([round(v, 1) for v in _xs], _b.x, _b.x + _b.w))
if _ring:
    ck(T.THINK_RING_R * 0.7 - 1e-6 <= _ring[0][3] <= T.THINK_RING_R * 1.25 + 1e-6,
       "脉冲环半径不在 .7~1.25 倍基准：%s" % _ring[0][3])
    ck(close_rgb(_ring[0][5], T.THINK_RING), "脉冲环颜色不是 THINK_RING：%s" % (_ring[0][5],))
    ck(0.0 <= _ring[0][5][3] <= 0.9 + 1e-6, "脉冲环 alpha 没在 .9->0 之间：%s" % _ring[0][5][3])

_th = [it for it in _b.items if it[0] in ("circ", "ring")]
_ymin = min(it[2] - (it[3] if it[0] == "circ" else 0.0) for it in _th)
_ymax = max(it[2] + (it[3] if it[0] == "circ" else it[3]) for it in _th)
ck(_ymin >= -20.0 and _ymax <= 60.0, "思考动效垂直跑出头像行：%s..%s" % (_ymin, _ymax))
ck(any("正在思考" in it[3] for it in _b.items if it[0] == "text"),
   "思考动效缺状态文案")

# 动效必须真的随 elapsed 变化（在「抬起」窗口内采样；静止窗口本来就全都一样）
def _sig_at(e):
    _bb = new_b()
    _rr = Run("x")
    _rr.phase = Phase.TOOL_RUNNING
    _rr.elapsed = e
    P._thinking_msg(P.Ctx(state, _rr, U, W, H), _bb, _rr)
    return tuple(sorted((round(it[2], 4), round(it[4][3], 4))
                        for it in _bb.items if it[0] == "circ"))


_sig = [_sig_at(_e) for _e in (0.0, 0.10, 0.20, 0.30, 0.40, 0.50)]
ck(len(set(_sig)) == len(_sig), "换 elapsed 后圆点位置/透明度不变，动效是死的：%s" % (_sig,))
_rest_cy = T.AHEAD_H * 0.5 - T.THINK_DOT_R
_rest = tuple(sorted([(round(_rest_cy, 4), round(T.THINK_DOT[3] * 0.45, 4))
                      for _i in range(3)]))
ck(_sig[0] == _rest, "静止态算错了：%s" % (_rest,))
ck(any(s != _rest for s in _sig), "静止态和抬升态长一样，动效看不出抬落：%s" % (_rest,))

sect("think_lines")
_lines = P._think_lines(think_run)
ck(isinstance(_lines, list) and len(_lines) == 3, "_think_lines 应给 3 行：%s" % (_lines,))
ck(any("2" in l and "步" in l for l in _lines), "_think_lines 没报已完成步数：%s" % (_lines,))
ck(all(isinstance(l, str) and l for l in _lines), "_think_lines 混进了空串")
_none_lines = P._think_lines(None)
ck(len(_none_lines) == 2, "_think_lines(None) 应给 2 行：%s" % (_none_lines,))
_early = Run("y")
_early.phase = Phase.PREFLIGHT
_early.elapsed = 0.0
_early.calls = []
_e_lines = P._think_lines(_early)
ck(len(_e_lines) == 2, "还没开工时不该报「已完成 0 步」：%s" % (_e_lines,))

# ---------------------------------------------------------------- BUSY 门控（端到端）
sect("busy_gate")
_busy_items = build(think_run)["items"]
ck(len([it for it in _busy_items if it[0] == "circ"]) == 3, "BUSY 时消息流里没有 3 个圆点")
ck(len([it for it in _busy_items if it[0] == "ring"]) >= 1, "BUSY 时消息流里没有脉冲环")
ck(any(it[0] == "text" and "正在思考" in it[3] for it in _busy_items),
   "BUSY 时消息流里没有思考文案")

_idle_items = build(done_run)["items"]
ck(not [it for it in _idle_items if it[0] in ("circ", "ring")],
   "非 BUSY 时仍然渲染了圆点/圆环动效")
ck(not any(it[0] == "text" and "正在思考" in it[3] for it in _idle_items),
   "非 BUSY 时仍然出现了「正在思考」文案")

state.busy = True
_state_busy_items = build(done_run)["items"]
state.busy = False
ck(any(it[0] == "text" and "正在思考" in it[3] for it in _state_busy_items),
   "state.busy=True 但 phase 不在 BUSY 时，思考动效没出现")
ck(len([it for it in build(think_run)["items"] if it[0] == "circ"]) == 3,
   "重复 build 后思考动效不稳定")

# ================================================================= 4. _chip_rows / _quick_h
sect("chips")
pills = list(U.quick_pills(state))
ck(bool(pills), "quick_pills 返回空")
_rows = {}
for _w in (240.0, 300.0, 360.0, 420.0, 520.0, 760.0):
    _rows[_w] = P._chip_rows(_w, pills)
    ck(isinstance(_rows[_w], int) and _rows[_w] >= 1, "W=%s 行数异常：%s" % (_w, _rows[_w]))
_ordered = [_rows[_w] for _w in (760.0, 520.0, 420.0, 360.0, 300.0, 240.0)]
ck(_ordered == sorted(_ordered), "胶囊行数没随 W 变小而增加：%s" % (_ordered,))
ck(_rows[760.0] == 1, "宽面板下胶囊没排成一行：%s" % (_rows,))
ck(_rows[240.0] > _rows[420.0], "窄面板下胶囊没有换行：%s" % (_rows,))
ck(P._chip_rows(W, []) == 0, "空胶囊列表应返回 0 行")
ck(P._chip_rows(W, ["只有一颗"]) == 1, "单胶囊在 W=%s 应为 1 行" % W)
for _w, _n in _rows.items():
    ck(near(P._quick_h(_w, pills), _n * T.CHIP_H + (_n - 1) * T.QUICK_ROW_GAP),
       "_quick_h 与行数脱节：W=%s 行=%s" % (_w, _n))
ck(P._quick_h(W, []) == 0.0, "空胶囊 _quick_h 应为 0")
ck(P._quick_h(240.0, pills) > P._quick_h(760.0, pills), "_quick_h 没随折行增高")

# 关键不变量：_composer 自己那套折行循环必须数出同样的行数，否则输入区高度算错。
# 宽度要覆盖到真会折行的区间（420 下四颗胶囊是一行，不覆盖就没有区分力）。
_WRAP_W = (150.0, 170.0, 200.0, 240.0, 260.0, 320.0, 420.0, 640.0)
for _w in _WRAP_W:
    _its = build(done_run, w=_w)["items"]
    _ph = set((round(it[1], 2), round(it[2], 2)) for it in _its
              if it[0] == "hit" and it[5].startswith("pill:"))
    _pr = [it for it in _its if it[0] == "rect"
           and (round(it[1], 2), round(it[2], 2)) in _ph]
    ck(len(_pr) == len(pills), "W=%s 画了 %d 颗胶囊，传入 %d 颗"
       % (_w, len(_pr), len(pills)))
    ck(len(set(round(it[2], 2) for it in _pr)) == P._chip_rows(_w, pills),
       "W=%s 实际 %d 行胶囊，_chip_rows 说 %d 行（输入区高度会算错）"
       % (_w, len(set(round(it[2], 2) for it in _pr)), P._chip_rows(_w, pills)))
    ck(all(it[1] >= -0.01 and it[1] + it[3] <= _w + 0.01 for it in _pr),
       "W=%s 胶囊横向跑出面板" % _w)
ck(any(P._chip_rows(_w, pills) > 1 for _w in _WRAP_W),
   "折行区间没覆盖到多行胶囊，这条不变量是空的")
ck(max(P._chip_rows(_w, pills) for _w in _WRAP_W)
   >= min(P._chip_rows(_w, pills) for _w in _WRAP_W),
   "多行区间没跑起来")

# ================================================================= 5. _grad
sect("grad")
_gb = new_b()
P._grad(_gb, 30.0, 100.0, 120.0, T.BTN_H, T.BTN_TOP, T.BTN_BOTTOM, 3)
_rects = [it for it in _gb.items if it[0] == "rect"]
ck(len(_rects) == 4, "_grad(3) 应产出 1 底板 + 3 色带，实际 %d" % len(_rects))
if len(_rects) == 4:
    _bands = _rects[1:]
    ck(all(near(it[1], 30.0) and near(it[3], 120.0) for it in _bands),
       "色带宽度/起点不一致：%s" % [(it[1], it[3]) for it in _bands])
    ck(all(it[2] >= 100.0 - 1e-6 and it[2] + it[4] <= 100.0 + T.BTN_H + 1e-6
           for it in _bands), "色带纵向跑出按钮框")
    ck(near(sum(it[4] for it in _bands), T.BTN_H, 1e-6),
       "色带总高 != 按钮高：%s" % sum(it[4] for it in _bands))
    _ys = [it[2] for it in _bands]
    ck(_ys == sorted(_ys), "色带不是自上而下排的：%s" % _ys)
    ck(close_col(_bands[0][6], T.BTN_TOP), "最上面一条不是 BTN_TOP：%s" % (_bands[0][6],))
    ck(close_col(_bands[-1][6], T.BTN_BOTTOM), "最下面一条不是 BTN_BOTTOM：%s" % (_bands[-1][6],))
    ck(all(_bands[i][6][c] >= _bands[i + 1][6][c] - 1e-9
           for i in range(len(_bands) - 1) for c in range(3)),
       "色带没有从上往下变暗：%s"
       % [tuple(round(v, 3) for v in bd[6][:3]) for bd in _bands])
    for _i, _it in enumerate(_bands):
        ck(close_col(_it[6], P._mix(T.BTN_TOP, T.BTN_BOTTOM, _i / 2.0)),
           "第 %d 条色带偏离线性插值" % _i)
    ck(_bands[0][5] == T.R_BTN, "最上面一条没有保留圆角")
for _n in (2, 4, 5):
    _gb2 = new_b()
    P._grad(_gb2, 0.0, 0.0, 90.0, 40.0, T.BTN_TOP, T.BTN_BOTTOM, _n)
    _rs = [it for it in _gb2.items if it[0] == "rect"]
    ck(len(_rs) == _n + 1, "_grad(n=%d) 色带数不对：%d" % (_n, len(_rs) - 1))
    ck(near(sum(it[4] for it in _rs[1:]), 40.0, 1e-6), "_grad(n=%d) 总高不对" % _n)
    ck(all(near(it[3], 90.0) for it in _rs[1:]), "_grad(n=%d) 色带宽度不齐" % _n)
    ck(close_col(_rs[1][6], T.BTN_TOP) and close_col(_rs[-1][6], T.BTN_BOTTOM),
       "_grad(n=%d) 首尾色不对" % _n)
try:
    P._grad(new_b(), 0.0, 0.0, 90.0, 40.0, T.BTN_TOP, T.BTN_BOTTOM, 1)
    _g1_ok = True
except Exception as e:                                        # noqa: BLE001
    _g1_ok = False
    _g1_err = repr(e)
ck(_g1_ok, "_grad(n=1) 抛 %s —— 单档渐变应退化成纯 bot 底板，不能除零"
   % (globals().get("_g1_err", "?"),))

# ================================================================= 6. _seg_diag
sect("seg_diag")
BOX_W, BOX_H = 40.0, 9.0
_segd = P._seg_diag(0.0, 0.0, BOX_W, BOX_H, 12.0)
ck(_segd is not None and len(_segd) == 4, "宽扁方框里 cst=12 没出线段：%s" % (_segd,))
if _segd:
    ck(near(_segd[0] + _segd[1], 12.0, 1e-6) and near(_segd[2] + _segd[3], 12.0, 1e-6),
       "线段不在 x+y=cst 上：%s" % (_segd,))
    ck(all(-0.01 <= v <= BOX_W + 0.01 for v in (_segd[0], _segd[2]))
       and all(-0.01 <= v <= BOX_H + 0.01 for v in (_segd[1], _segd[3])),
       "线段跑出方框：%s" % (_segd,))
ck(P._seg_diag(0.0, 0.0, BOX_W, BOX_H, -3.0) is None, "远在方框外的线不该出线段")
ck(P._seg_diag(0.0, 0.0, BOX_W, BOX_H, 400.0) is None, "远在方框外的线不该出线段")

# 条数 == 「有多少条 45° 线真正穿过方框」。x+y=cst 与方框 [0,W]x[0,H] 相交
# 当且仅当 0 <= cst <= W+H（早期实现只跟上下边求交，期望值被标定在 bug 上）。
# 条数 == 「有多少条 45° 线真正穿过方框」。x+y=cst 与方框 [0,W]x[0,H] 相交
# 当且仅当 0 <= cst <= W+H；但 cst=0 与 cst=W+H 只是**角点相切**，线段退化成
# 单个点，按定义就该返回 None，不计入条数。
_dens = {}
for _step in (1.0, 1.5, 2.0, 3.0, 4.0, 5.0):
    _exp = sum(1 for k in range(41) if 0.0 < k * _step < BOX_W + BOX_H)
    _got = sum(1 for k in range(41)
               if P._seg_diag(0.0, 0.0, BOX_W, BOX_H, k * _step) is not None)
    _dens[_step] = _got
    ck(_got == _exp, "斜纹密度 step=%s 时条数 %d，预期 %d" % (_step, _got, _exp))
ck(list(_dens.values()) == sorted(_dens.values(), reverse=True),
   "斜纹密度和条数不单调（步长越大条数应越少）：%s" % _dens)
ck(max(_dens.values()) > 1, "斜纹密度全塌成 1 条：%s" % _dens)

_oob = []
for _k in range(24):
    _seg = P._seg_diag(20.0, 60.0, 60.0, 69.0, 80.0 + _k * 1.3)
    if _seg and not (20.0 - .01 <= _seg[0] <= 60.0 + .01
                     and 20.0 - .01 <= _seg[2] <= 60.0 + .01
                     and 60.0 - .01 <= _seg[1] <= 69.0 + .01
                     and 60.0 - .01 <= _seg[3] <= 69.0 + .01):
        _oob.append(_seg)
ck(not _oob, "斜纹线段裁剪越界：%s" % _oob[:3])

# _seg_diag 必须同时和四条边求交：正方形方框里绝大多数 45° 线只穿过左右边，
# 只跟上下边求交会把它们全判成 None（把手斜纹就一条都画不出来）。
# cst=0 与 cst=36 是角点相切，退化成单点，按定义返回 None，不在此列。
_missing = [cst for cst in (2.0, 9.0, 27.0)
            if P._seg_diag(0.0, 0.0, 18.0, 18.0, cst) is None]
ck(not _missing,
   "_seg_diag 又退回只看上下边了：18x18 方框里 cst=%s 返回 None（应为线段）"
   % _missing)

# 把手本体：命中区贴右下角，且真的画出了斜纹
sect("grip")
_gits = build(done_run)["items"]
_grip = [it for it in _gits if it[0] == "hit" and it[5] == "grip"]
ck(bool(_grip), "输入区缺把手命中区")
if _grip:
    gx0, gy0 = _grip[0][1], _grip[0][2]
    ck(near(gx0 + T.GRIP_SIZE, W - T.COMPOSER_PAD_X, 1e-6),
       "把手没贴到右侧内边距：%s" % (_grip[0],))
    ck(gy0 + T.GRIP_SIZE <= H + 0.01, "把手跑出面板底部：%s" % (_grip[0],))
_gx, _gy = (_grip[0][1] + 6.0, _grip[0][2] + 6.0) if _grip else (0.0, 0.0)
_stripes = [it for it in _gits if it[0] == "line"
            and near(it[5], T.GRIP_STRIPE_W, 1e-9)
            and _gx - 0.01 <= min(it[1], it[3]) and max(it[1], it[3]) <= _gx + 9.01
            and _gy - 0.01 <= min(it[2], it[4]) and max(it[2], it[4]) <= _gy + 9.01]
ck(bool(_stripes), "把手 135deg 斜纹一条都没画出来（_seg_diag 裁剪失败）")

# ================================================================= 7. 输入区几何
sect("composer")
_hs = {}
for _n in (1, 2, 3, 4, 5):
    state.prompt_lines = _n
    _hs[_n] = P.composer_height(state)
ck(_hs[1] < _hs[2] < _hs[3] < _hs[4] < _hs[5],
   "composer_height 没随 prompt_lines 单调递增：%s" % _hs)
state.prompt_lines = 2
for _n in (0, 99):
    state.prompt_lines = _n
    ck(P.composer_height(state) > 0, "prompt_lines=%s 时输入区高度非法" % _n)
state.prompt_lines = 2
ck(near(P._text_h(state), max(T.TEXT_MIN_H, 2 * T.LINE_H + 10.0), 1e-6),
   "_text_h 与令牌算不一致：%s" % P._text_h(state))

_ws = []
for _w in (300.0, 380.0, 420.0, 500.0, 700.0):
    for _h in (400.0, 900.0, 1756.0):
        _rx, _ry, _rw, _rh = P.composer_text_rect(_w, _h, state, pills)
        ck(_rx >= -0.01 and _ry >= -0.01 and _rw > 0 and _rh > 0,
           "W=%s H=%s 文字框退化：%s" % (_w, _h, (_rx, _ry, _rw, _rh)))
        ck(_rx + _rw <= _w + 0.01, "W=%s 文字框横向越界" % _w)
        ck(_ry + _rh <= _h + 0.01, "H=%s 文字框纵向越界" % _h)
    _ws.append(P.composer_text_rect(_w, 1756.0, state, pills)[2])
ck(_ws == sorted(_ws) and len(set(_ws)) == len(_ws),
   "文字框宽度没随 W 变化（420 硬编码回归？）：%s" % _ws)
ck(near(_ws[0], 300.0 - (T.COMPOSER_PAD_X + 1) * 2, 1e-6)
   and near(_ws[-1], 700.0 - (T.COMPOSER_PAD_X + 1) * 2, 1e-6),
   "文字框宽度不是 W-2*(PAD_X+1)：%s" % _ws)
_ys = [P.composer_text_rect(420.0, _h, state, pills)[1] for _h in (400.0, 900.0, 1756.0)]
ck(_ys == sorted(_ys), "面板越矮文字框反而越靠上：%s" % _ys)

for _w in (300.0, 420.0, 640.0):
    for _n in (1, 3, 5):
        state.prompt_lines = _n
        _o = build(done_run, w=_w)
        _cy, _ch = _o["composer_rect"][1], _o["composer_rect"][3]
        ck(near(_ch, P.composer_height(state, pills, _w), 1e-6),
           "W=%s lines=%d 时 composer_height=%s，实际画了 %s"
           % (_w, _n, P.composer_height(state, pills, _w), _ch))
        ck(near(_cy + _ch, H, 0.5), "W=%s 输入区没钉底" % _w)
        _tr = P.composer_text_rect(_w, H, state, pills)
        ck(_tr[1] + _tr[3] <= _cy + _ch + 0.01, "文字框跑出输入区：%s" % (_tr,))
state.prompt_lines = 2
ck(len([it for it in build(done_run)["items"] if it[0] == "text"]) > 10,
   "输入区文案整体缺失")

# ================================================================= 8. _kv_list
sect("kv_list")
FLAT = [("kgrp", "geo"), ("row", "口径", "86mm"), ("row", "高度", "95mm"),
        ("row", "壁厚", "3mm"), ("kgrp", "materials"), ("row", "粗糙度", "0.42"),
        ("row", "金属度", "0.0")]
_kb = new_b(x=24.0, w=360.0)
P._kv_list(_kb, FLAT)
_ktexts = [it[3] for it in _kb.items if it[0] == "text"]
for _k in ("口径", "高度", "壁厚", "粗糙度", "金属度"):
    ck(any(_k in t for t in _ktexts), "_kv_list 漏渲染 key %r：%s" % (_k, _ktexts))
for _v in ("86mm", "95mm", "3mm", "0.42", "0.0"):
    ck(any(t == _v or t.endswith(_v) for t in _ktexts), "_kv_list 漏渲染 value %r" % _v)
for _g in ("几何参数", "材质"):
    ck(any(t == _g for t in _ktexts), "_kv_list 分组标题没画/没译：%r" % _g)
_ky = [it[2] for it in _kb.items if it[0] in ("text", "line")]
ck(_ky == sorted(_ky), "_kv_list 不是自上而下排的")
ck(all(it[1] >= _kb.x - 0.01 and it[1] <= _kb.x + _kb.w + 0.01
       for it in _kb.items if it[0] == "text"), "_kv_list 文本横向跑出内容框")
_nrows = sum(1 for f in FLAT if f[0] == "row")
ck(len([it for it in _kb.items if it[0] == "line"]) == _nrows - 1,
   "分隔线数应为行数-1（末行不画线）")
ck(_kb.y > 0, "_kv_list 没有推进 y 光标")
_empty = new_b()
P._kv_list(_empty, [])
ck(not _empty.items, "_kv_list 对空列表还在画东西")
_endgrp = new_b(x=24.0, w=360.0)
P._kv_list(_endgrp, [("row", "口径", "86mm"), ("kgrp", "geo")])
ck(any(it[0] == "text" and it[3] == "几何参数" for it in _endgrp.items),
   "_kv_list 结尾是分组时没画组标题")
_long = new_b(x=24.0, w=120.0)
P._kv_list(_long, [("row", "一个非常非常长的参数名字用来触发省略号", "值也长得离谱得很")])
_ltexts = [it[3] for it in _long.items if it[0] == "text"]
ck(all(ell.endswith("…") or ell.endswith("...") for ell in _ltexts)
   and all(len(ell) < 14 for ell in _ltexts),
   "窄内容框下 key/value 没被 ellipsize，会顶到框外：%s" % _ltexts)
ck(all(it[1] >= _long.x - 0.01 and it[1] <= _long.x + _long.w + 0.01
       for it in _long.items if it[0] == "text"), "窄框下 _kv_list 文本横向跑出")

# ================================================================= 9. _is_busy
sect("is_busy")


class _St(object):
    def __init__(self, busy):
        self.busy = busy


class _Run(object):
    def __init__(self, phase):
        self.phase = phase


ck(P._is_busy(None, _St(False)) is False, "_is_busy(None run, 不忙) 应为 False")
ck(P._is_busy(None, _St(True)) is True, "_is_busy(None run, busy=True) 应为 True")
for _ph in sorted(BUSY, key=lambda p: p.value):
    ck(P._is_busy(_Run(_ph), _St(False)) is True,
       "_is_busy(%s) 应为 True（BUSY 相位必须触发动效）" % _ph.value)
for _ph in (Phase.READY, Phase.COMPLETED, Phase.PARTIAL, Phase.FAILED, Phase.STOPPED):
    ck(P._is_busy(_Run(_ph), _St(False)) is False,
       "_is_busy(%s) 不忙时不该为 True" % _ph.value)
    ck(P._is_busy(_Run(_ph), _St(True)) is True,
       "_is_busy(%s) + state.busy=True 应为 True" % _ph.value)
ck(P._is_busy(_Run(None), _St(False)) is False, "_is_busy(phase=None) 应为 False")
for _ph in sorted(BUSY, key=lambda p: p.value):
    ck(len([it for it in build(_Run(_ph))["items"] if it[0] == "circ"]) == 3,
       "phase=%s（BUSY）时 build 没画 3 个圆点" % _ph.value)
for _ph in (Phase.COMPLETED, Phase.READY):
    ck(not [it for it in build(_Run(_ph))["items"] if it[0] == "circ"],
       "phase=%s（非 BUSY）时 build 仍然画了圆点" % _ph.value)

# ================================================================= 结果
for f in FAILS:
    print("  FAIL:", f)
for x in XFAILS:
    print("  XFAIL:", x)
for x in XPASSES:
    print("  XPASS:", x)
print("PASS %d  FAIL %d  XFAIL %d  XPASS %d"
      % (OK[0], len(FAILS), len(XFAILS), len(XPASSES)))
sys.exit(1 if FAILS else 0)
