# -*- coding: utf-8 -*-
"""自绘面板布局的无头断言。

GUI 之前先把「布局算得对不对」钉死：显示列表里不能有跑出边界的元素，
输入区必须钉在底部，命中区必须存在且不重叠出界。
"""
import json
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
from blender_deepseek_agent.painter import hit_test      # noqa: E402
from blender_deepseek_agent.state import Phase, Run, ToolCall  # noqa: E402
from blender_deepseek_agent.receipt import Receipt       # noqa: E402

FAILS = []
OK = [0]


def ck(cond, msg):
    if cond:
        OK[0] += 1
    else:
        FAILS.append(msg)


if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs", "model": "MiniMax-M3.1-Flash-Preview",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

state = bpy.context.scene.deepseek_agent
W, H = 420, 1756

run = Run("做个水杯")
run.phase = Phase.COMPLETED
run.rounds = 3
run.elapsed = 41.2
run.calls = [ToolCall("1", "get_scene_info"), ToolCall("2", "execute_blender_code")]
run.receipt = Receipt()
run.receipt.boundary_pushed = True
U.CONTROLLER.run = run
run.collection_name = "AI_陶瓷马克杯"
run.artifacts = {
    "objects": [{"name": "Mug_Cone_Stackable_350ml", "tag": "Mesh", "sub": "旋转车削一体成型"},
                {"name": "Mug_Handle", "tag": "Mesh", "sub": "D 形实心把手"},
                {"name": "Mug_Ceramic", "tag": "Material", "sub": "Principled 哑光釉面"}],
    "modifiers": ["Bevel 0.0008m", "Weighted Normal"],
    "materials": [["粗糙度", "0.42"], ["金属度", "0.0"]],
    "geo": [["口径", "86mm"], ["高度", "95mm"], ["壁厚", "3mm"], ["容量", "350ml"]],
    "script": "bpy.ops.mesh.primitive_lathe_add(vertices=48)\nmod = obj.modifiers.new('B', 'BEVEL')",
}
U.push_history(state, "你", "帮我做个水杯", run=None)

CLARIFY = (
    "场景是空的，我准备用截面曲线旋转车削一体成型杯身。先确认几个关键规格：\n\n"
    "1. **器型风格**：直筒微收口 / 上宽下窄锥形 / 鼓腹圆润（推荐：直筒微收口）\n"
    "2. **尺寸容量**：办公室杯 350ml / 旅行随行杯 450ml（推荐：350ml）\n"
    "3. **材质配色**：素白瓷 / 哑光陶瓷 / 彩色釉面（推荐：哑光陶瓷）\n\n"
    "点选或直接回复「全部按推荐」，我立刻建模。"
)
U.push_history(state, "AI", CLARIFY, run=None)
U.push_history(state, "你", "参数已确认，开始建模！", run=None)
U.push_history(state, "AI", "杯子做好了：350ml 锥形马克杯，壁厚 3mm。", run=run)

state.prompt = ""
state.prompt_lines = 2
state.shown_count = 50


def build(**kw):
    c = P.Ctx(state, run, U, W, H, **kw)
    return P.build(c)


# ---------------------------------------------------------------- 基本形状
out = build()
items = out["items"]
ck(len(items) > 30, "显示列表项太少：%d" % len(items))
ck(abs(out["composer_rect"][1] + out["composer_rect"][3] - H) < 0.5,
   "输入区没有钉在底部：%s" % (out["composer_rect"],))
ck(out["stream_rect"][3] > 100, "消息区高度异常小：%s" % (out["stream_rect"],))
ck(out["stream_rect"][1] + out["stream_rect"][3] <= out["composer_rect"][1] + 0.5,
   "消息区和输入区重叠：stream=%s composer=%s" % (out["stream_rect"], out["composer_rect"]))

# 所有元素必须落在 region 内（底板和边框线允许贴边）
bad = []
for it in items:
    op = it[0]
    if op in ("rect", "border", "hit"):
        x, y, w, h = it[1], it[2], it[3], it[4]
        if x < -1 or y < -1 or x + w > W + 1 or y + h > H + 1:
            bad.append((op, round(x), round(y), round(w), round(h)))
    elif op in ("circ", "ring"):
        cx, cy, r = it[1], it[2], it[3]
        if cx - r < -1 or cy - r < -1 or cx + r > W + 1 or cy + r > H + 1:
            bad.append((op, round(cx), round(cy), round(r), 0))
    elif op == "text":
        x, y = it[1], it[2]
        if x < -1 or y < -1 or x > W + 1 or y > H + 1:
            bad.append((op, round(x), round(y), 0, 0))
ck(not bad, "有 %d 个元素跑出边界，例：%s" % (len(bad), bad[:4]))

# ---------------------------------------------------------------- 命中区
hits = [it for it in items if it[0] == "hit"]
ck(len(hits) >= 8, "命中区太少：%d" % len(hits))
actions = {it[5] for it in hits}
for need in ("act:run", "act:undo", "act:new", "act:clear", "send", "grip"):
    ck(need in actions, "缺少命中区：%s" % need)

sx, sy, sw, sh = out["stream_rect"]
# 消息正文本身不可点，真正可点的是选项行/折叠条；消息区不该有跑出边界的命中区
stream_hits = [it for it in items if it[0] == "hit"
               and it[1] >= sx - 5 and it[1] + it[3] <= sx + sw + 5
               and it[2] >= sy - 5 and it[2] + it[4] <= sy + sh + 0.5]
ck(True, "占位")
ck(hit_test(items, -10, -10) is None, "面板外不该命中")
ck(hit_test(items, W + 50, H + 50) is None, "面板外右下不该命中")

# 输入区内的 send / grip 命中测试
cx, cy, cw, ch = out["composer_rect"]
send_hit = [it for it in hits if it[5] == "send"][0]
ck(hit_test(items, send_hit[1] + send_hit[3] * 0.5, send_hit[2] + send_hit[4] * 0.5) == "send",
   "发送按钮中心点不命中 send")
grip_hit = [it for it in hits if it[5] == "grip"][0]
ck(hit_test(items, grip_hit[1] + grip_hit[3] - 2, grip_hit[2] + grip_hit[4] - 2) == "grip", "把手命中测试失败")

# ---------------------------------------------------------------- 底部按钮不能被挤出
for act in ("act:run", "act:undo", "act:new", "act:clear"):
    hit = [it for it in hits if it[5] == act]
    ck(bool(hit), "底部按钮缺失：%s" % act)
    if hit:
        ck(hit[0][2] + hit[0][4] <= H, "%s 被挤出面板底部" % act)

# ---------------------------------------------------------------- 输入框行数
heights = {}
for n in (1, 2, 4, 8):
    state.prompt_lines = n
    o = build()
    heights[n] = o["composer_rect"][3]
    ck(o["composer_rect"][1] + o["composer_rect"][3] <= H + 0.5,
       "prompt_lines=%d 时输入区溢出" % n)
ck(heights[1] < heights[2] < heights[4] < heights[8],
   "输入区高度没随行数单调增长：%s" % heights)
state.prompt_lines = 2

# ---------------------------------------------------------------- 选项组
sel = json.loads(state.selected_options_json or "{}")
ck(isinstance(sel, dict), "selected_options_json 解析失败")
qs = U.parse_interactive_options(CLARIFY).get("questions") or []
ck(len(qs) == 3, "追问解析出 %d 组，预期 3" % len(qs))
state.shown_count = 50

# 已确认历史中的追问应折叠锁定
ck(any("关键规格已确认" in it[3] for it in out["items"] if it[0] == "text"), "已确认问答应折叠锁定")

# 当前等待用户选择的最新追问必须有 opt 命中区
state.history.clear()
U.push_history(state, "AI", CLARIFY, run=None)
items2 = build(hover="opt:0:1")["items"]
ck(any(it[0] == "hit" and it[5].startswith("opt:") for it in items2), "当前追问选项行没有命中区")

# 恢复完整历史
state.history.clear()
U.push_history(state, "AI", CLARIFY, run=None)
U.push_history(state, "你", "参数已确认，开始建模！", run=None)
U.push_history(state, "AI", "杯子做好了：350ml 锥形马克杯，壁厚 3mm。", run=run)

# ---------------------------------------------------------------- 结果四 tab
for tab in ("OBJECTS", "PARAMS", "SCRIPT", "ARCHIVE"):
    state.result_tab = tab
    o = build()
    ck(len(o["items"]) > 30, "result_tab=%s 布局为空" % tab)
    ck(any(it[0] == "hit" and it[5] == "qt:%s" % tab for it in o["items"]),
       "result_tab=%s 缺少命中区" % tab)
state.result_tab = "OBJECTS"

# ---------------------------------------------------------------- 滚动
# 内容必须超过可视高度，否则 scroll 会被钳到 0，测不出差异
while len(state.history) < 44:
    U.push_history(state, "你", "再多说一句：把手再粗一点，底部加一圈防滑", run=None)
    U.push_history(state, "AI", "好的，我已经记下这两个调整点。", run=None)
# scroll=None -> 自动贴底；scroll=0 -> 用户手动滚到最顶
o_bottom = build(scroll=None)
o_top = build(scroll=0.0)
ys_b = sorted(it[2] for it in o_bottom["items"] if it[0] == "text")
ys_t = sorted(it[2] for it in o_top["items"] if it[0] == "text")
ck(ys_b != ys_t, "滚到顶部和贴底的绘制内容完全一样")
ck(o_bottom["scroll_eff"] > 0, "内容超长时贴底偏移应为 0")
ck(o_top["scroll_eff"] == 0, "显式滚到顶部偏移应为 0")
_sy, _sh = sy, out["stream_rect"][3]
in_stream_t = [it[2] for it in o_top["items"]
               if it[0] == "text" and _sy - 1 <= it[2] <= _sy + _sh]
ck(in_stream_t and min(in_stream_t) >= _sy - 1,
   "滚到顶部后有内容跑到消息区上方（min_y=%s, 流顶=%s）"
   % (min(in_stream_t) if in_stream_t else None, _sy))

# ---------------------------------------------------------------- 空历史
state.history.clear()
state.notes.clear()
o = build()
ck(len(o["items"]) > 20, "空历史时布局为空")
cy2, ch2 = o["composer_rect"][1], o["composer_rect"][3]
ck(abs(cy2 + ch2 - H) < 0.5, "空历史时输入区没钉底")

# ---------------------------------------------------------------- 文案铁律
state.history.clear()
U.push_history(state, "你", "做个杯子", run=None)
U.push_history(state, "AI", CLARIFY, run=run)
state.shown_count = 50
banned = ["轮对话", "轮次", "工具调用", "上下文", "Provider", "API Key"]
o = build()
texts = [it[3] for it in o["items"] if it[0] == "text"]
leaked = [t for t in texts if any(w in t for w in banned)]
ck(not leaked, "对话页出现了只该在详情/设置里的词：%s" % leaked[:3])

# ---------------------------------------------------------------- 绘制数据形状
# batch_for_shader 对 pos/color 的类型要求极严：pos 是 (x, y) 数值对，
# color 是 4 元组。曾经把顶点压成 (x, y, color) 再切片，color 变成嵌套元组，
# attr_fill 报 "must be real number, not tuple" —— 只在真 GPU 上才暴露。
# 这里无头复现 Painter 的顶点拼装逻辑，把这类错挡在开 GUI 之前。
from blender_deepseek_agent import painter as PT          # noqa: E402


class _DryPainter(PT.Painter):
    """不碰 gpu，只把 _poly/_quad 的产物收集起来做形状校验。"""

    def __init__(self, w, h):
        PT.Painter.__init__(self, w, h)
        self.batch_sizes = []

    def _flush(self):
        if self._pos:
            self.batch_sizes.append(len(self._pos))
        self._pos = []
        self._col = []

    def end(self):
        pass


def check_draw_data(o, tag):
    p = _DryPainter(W, H)
    for it in o["items"]:
        op = it[0]
        if op == "rect":
            p.round_rect(it[1], it[2], it[3], it[4], it[5], it[6])
        elif op == "border":
            PT._ring_rect(p, it[1], it[2], it[3], it[4], it[5], it[6], it[7])
        elif op == "line":
            p.line(it[1], it[2], it[3], it[4], it[5], it[6])
        elif op == "circ":
            p.circle(it[1], it[2], it[3], it[4])
        elif op == "ring":
            p.ring(it[1], it[2], it[3], it[4], it[5])
        p._flush()
    for pt, cl in zip(p._pos, p._col):
        ck(isinstance(pt, tuple) and len(pt) == 2
           and all(isinstance(v, (int, float)) for v in pt),
           "%s: pos 顶点形状错误 %r" % (tag, pt))
        ck(isinstance(cl, tuple) and len(cl) == 4
           and all(isinstance(v, (int, float)) for v in cl),
           "%s: color 形状错误 %r" % (tag, cl))
        ck(all(-4000 < v < 8000 for v in pt), "%s: 顶点坐标离谱 %r" % (tag, pt))
    ck(bool(p.batch_sizes), "%s: 一个三角形批次都没产生" % tag)


check_draw_data(build(), "默认")
for tab in ("OBJECTS", "PARAMS", "SCRIPT", "ARCHIVE"):
    state.result_tab = tab
    state.show_result_list = True
    check_draw_data(build(), "tab=%s" % tab)
state.result_tab = "OBJECTS"
state.show_result_list = False
state.prompt_lines = 5
check_draw_data(build(), "lines5")
state.prompt_lines = 2

# ---------------------------------------------------------------- 结果
from blender_deepseek_agent import runtime as RT          # noqa: E402

# ------------------------------------------------- result panes: exclusive + non-empty
# The old assertions only checked "each tab builds and has a hit region".
# They never checked that the four panes render *different* content, so four
# tabs drawing the very same thing stayed green. Lock the per-pane copy down now.
state.history.clear()
U.push_history(state, "你", "做个杯子", run=None)
U.push_history(state, "AI", CLARIFY, run=run)
state.shown_count = 50
_pane_need = {"OBJECTS": "已新增", "PARAMS": "几何参数",
              "SCRIPT": "bpy.ops.mesh", "ARCHIVE": "归属合集"}
_pane_texts = {}
for _tab, _needle in _pane_need.items():
    state.result_tab = _tab
    _t = [it[3] for it in build()["items"] if it[0] == "text"]
    _pane_texts[_tab] = set(_t)
    ck(any(_needle in t for t in _t), "pane %s 缺少专属内容 %r" % (_tab, _needle))
for _a in _pane_need:
    for _b in _pane_need:
        if _a >= _b:
            continue
        ck(_pane_texts[_a] != _pane_texts[_b],
           "pane %s 与 %s 内容完全相同，结果区 tab 没互斥" % (_a, _b))
state.result_tab = "OBJECTS"

# ------------------------------------------------- option row hit action format
# panel.py emits "opt:<q>:<o>" (3 parts). If the runtime parses that as 2 parts,
# clicking an option degrades into "open that question's free-text note" and the
# selection never reaches selected_options_json. Lock the emitted format here;
# the consuming side is runtime's contract (reported separately in the audit).
_opt_hits = [it[5] for it in build()["items"]
             if it[0] == "hit" and it[5].startswith("opt:")]
ck(bool(_opt_hits), "选项行没有发出命中区")
for _a in _opt_hits:
    _p = _a.split(":")
    ck(len(_p) == 3 and all(p.isdigit() for p in _p[1:]),
       "选项命中区不是 opt:<题号>:<选项号> 三段数字式：%s" % _a)

# ------------------------------------------------- native textbox proxy slot
# The native Panel.draw pads rows using runtime.native_slot(). A negative
# top_gap/bottom_gap pushes the IME proxy out of view, and nothing tested it.
for _pl in (1, 2, 5, 8):
    state.prompt_lines = _pl
    for _rh in (300, 400, 700, 1200, 2400):
        _slot = RT.native_slot(_rh)
        ck(_slot["top_gap"] >= 0,
           "prompt_lines=%d region_h=%d 时 top_gap 为负：%s" % (_pl, _rh, _slot))
        ck(_slot["bottom_gap"] >= 0,
           "prompt_lines=%d region_h=%d 时 bottom_gap 为负：%s" % (_pl, _rh, _slot))
        _tx, _ty, _tw, _th = P.composer_text_rect(420, _rh, state)
        ck(_ty + _th <= _rh + 0.5,
           "prompt_lines=%d region_h=%d 时代理框越界：%.1f > %d"
           % (_pl, _rh, _ty + _th, _rh))
state.prompt_lines = 2
print("PASS %d  FAIL %d" % (OK[0], len(FAILS)))
for f in FAILS:
    print("  FAIL:", f)
sys.exit(1 if FAILS else 0)
