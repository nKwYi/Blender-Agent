# -*- coding: utf-8 -*-
"""自绘面板的「文案铁律 + 状态契约 + 交互语义」无头断言。

背景
----
这个文件最早是一份 MockLayout 测试，整篇断言 Blender 原生 UILayout 的
label()/operator()。N 面板改成 GPU 自绘后，原生层只剩一个输入代理框，
那套断言一条都验不到东西 —— 而且脚本还不调 sys.exit，26 条失败照样 rc=0。
现在断言对象全部换成自绘层自己的三样东西：

  * panel.build(ctx) 返回的**显示列表**（items / stream_rect / composer_rect /
    content_h / scroll_eff）
  * painter.hit_test(items, x, y) 的命中结果（action_id 字符串）
  * painter.wrap / ellipsize / text_width 三个纯函数

分工：test_panel_layout.py 钉布局骨架（越界/命中/滚动/绘制数据形状），
test_panel_widgets.py 钉组件级不变量。这个文件补的是前两个都没覆盖的
**语义**层：用户能看到的字、以及每个状态必须说的话。

只测自绘层与 state.py 的公开契约，不碰 ui.py 的内部私有函数
（那些死函数正在被并行删除，引用它们会撞车）。

已知缺陷走 XFAIL 通道：不是 FAIL，也不是悄悄按现状锁死；panel.py 归别人改，
这里只登记，修好了会自动翻成 XPASS。

用法：
    blender.exe --background --factory-startup -P dev/test_ui_v2.py
"""
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda                            # noqa: E402
from blender_deepseek_agent import panel as P                  # noqa: E402
from blender_deepseek_agent import theme as T                   # noqa: E402
from blender_deepseek_agent import ui as U                      # noqa: E402
from blender_deepseek_agent import painter as PT                # noqa: E402
from blender_deepseek_agent.state import (Phase, Err, BUSY,     # noqa: E402
                                          Run, ToolCall, guide)
from blender_deepseek_agent.receipt import Receipt             # noqa: E402

FAILS = []
XFAILS = []
XPASSES = []
OK = [0]
SECTION = ["?"]

# 硬要求：汇总行 + sys.exit，rc=0 不许当判据
SUMMARY = "PASS %d  FAIL %d  XFAIL %d  XPASS %d"


def sect(name):
    SECTION[0] = name


def ck(cond, msg):
    if cond:
        OK[0] += 1
    else:
        FAILS.append("[%s] %s" % (SECTION[0], msg))


def xfail(repro, msg):
    """repro=True -> 缺陷仍在（预期）；repro=False -> 已被修好（XPASS）。"""
    if repro:
        XFAILS.append("[%s] %s" % (SECTION[0], msg))
    else:
        XPASSES.append("[%s] %s" % (SECTION[0], msg))


def near(a, b, eps=1e-6):
    return abs(a - b) <= eps


# --------------------------------------------------------------------------
# 造数
# --------------------------------------------------------------------------
if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()
bda.config.get_config = lambda: {
    "api_key": "sk-***", "key_source": "prefs",
    "model": "MiniMax-M3.1-Flash-Preview",
    "base_url": "https://api.minimax.cn/v1", "provider": "MINIMAX",
    "timeout": 180, "max_turns": 20, "wall_budget": 600,
    "allow_arbitrary_code": True, "history_page": 3}

state = bpy.context.scene.deepseek_agent
W, H = 420.0, 1756.0
state.prompt = ""
state.prompt_lines = 2
state.shown_count = 50
state.busy = False
state.result_tab = "OBJECTS"
state.show_result_list = True
state.selected_options_json = "{}"
state.other_open_q = ""

CLARIFY = (
    "场景是空的，我准备用截面曲线旋转车削一体成型杯身。先确认几个关键规格：\n\n"
    "1. **器型风格**：直筒微收口 / 上宽下窄锥形 / 鼓腹圆润（推荐：直筒微收口）\n"
    "2. **尺寸容量**：办公室杯 350ml / 旅行随行杯 450ml（推荐：350ml）\n"
    "3. **材质配色**：素白瓷 / 哑光陶瓷 / 彩色釉面（推荐：哑光陶瓷）\n\n"
    "点选或直接回复「全部按推荐」，我立刻建模。"
)

ART = {
    "objects": [{"name": "Mug_锥形马克杯", "tag": "Mesh", "sub": "旋转车削一体成型"},
                {"name": "Mug_Handle", "tag": "Mesh", "sub": "D 形实心把手"},
                {"name": "Mug_陶瓷", "tag": "Material", "sub": "Principled 哑光釉面"}],
    "modifiers": ["Bevel 0.0008m", "Weighted Normal"],
    "materials": [["粗糙度", "0.42"], ["金属度", "0.0"]],
    "geo": [["口径", "86mm"], ["高度", "95mm"], ["壁厚", "3mm"]],
    "script": ("bpy.ops.mesh.primitive_lathe_add(vertices=48)\n"
               "mod = obj.modifiers.new('Bevel', 'BEVEL')"),
}

PANE_NEEDLE = {"OBJECTS": "已新增", "PARAMS": "几何参数",
               "SCRIPT": "bpy.ops", "ARCHIVE": "归属合集"}
# 铁律：这些词只准出现在【详情】【设置】，对话页一个字都不能有
BANNED_CHAT = ["轮次", "轮对话", "工具调用", "上下文", "Provider", "API Key"]


def make_run(phase=Phase.COMPLETED, err=Err.NONE, pending=False):
    r = Run("做个水杯")
    r.phase = phase
    r.err = err
    r.rounds = 2
    r.elapsed = 41.2
    r.calls = [ToolCall("1", "get_scene_info"),
               ToolCall("2", "execute_blender_code")]
    r.receipt = Receipt()
    r.receipt.boundary_pushed = True     # can_undo() 的前提，否则「回退发送」是灰的
    r.collection_name = "AI_陶瓷马克杯"
    r.artifacts = ART
    r.skipped = ["把手换成 D 形"]
    if pending:
        c = ToolCall("c1", "execute_blender_code",
                     {"code": "bpy.data.objects['Mug_锥形马克杯'].scale = (1,1,2)"})
        c.approval_state = "pending"
        r.calls = [c]
    return r


run = make_run()
U.CONTROLLER.run = run


def build(r=None, **kw):
    return P.build(P.Ctx(state, r if r is not None else run, U, W, H, **kw))


def texts(o):
    return [it[3] for it in o["items"] if it[0] == "text"]


def hits(o):
    return [it for it in o["items"] if it[0] == "hit"]


def actions(o):
    return sorted(set(it[5] for it in hits(o)))


def fresh(ai=None, with_run=None):
    """把面板拨到一个干净起点：只有给定的那几条历史。"""
    state.history.clear()
    state.notes.clear()
    U.push_history(state, "你", "做个水杯", run=None)
    if ai:
        U.push_history(state, "AI", ai, run=with_run)
    U.CONTROLLER.run = run


# ================================================================= 1. 命中区词表
# runtime.dispatch() 按前缀分派 action_id，认不出来的前缀只会 return False ——
# 界面看着有按钮，点下去没反应。这里把「拼错/退化」的 id 当场挡住。
sect("action_vocab")
_KNOWN_BARE = {"send", "grip", "hover:inwrap"}
_KNOWN_ACT = {"run", "undo", "new", "clear", "confirm", "recommended",
              "approve", "toggle_code", "stop"}


def action_known(a):
    if a in _KNOWN_BARE:
        return True
    p = a.split(":")
    if p[0] == "act":
        return len(p) == 2 and p[1] in _KNOWN_ACT
    if p[0] == "tab":
        return len(p) == 2 and p[1] in ("0", "1")
    if p[0] == "qt":
        return len(p) == 2 and p[1] in PANE_NEEDLE
    if p[0] == "collapse":
        return len(p) == 2 and p[1] == "objects"
    if p[0] == "opt":
        return len(p) == 3 and all(z.isdigit() for z in p[1:])
    if p[0] in ("pill", "other"):
        return len(p) >= 2 and bool(p[1])
    return False


seen = set()
fresh(CLARIFY, run)          # 结果区/选项卡的内容都挂在 AI 消息上
for _ph in Phase:
    _r = make_run(_ph, Err.NET, pending=True)
    for _hv in ("", "grip", "send", "tab:1", "qt:SCRIPT", "collapse:objects",
                "opt:0:1", "hover:inwrap", "pill:增加倒角"):
        state.selected_options_json = json.dumps({"0": ["直筒微收口"]}) if _hv == "opt:0:1" else "{}"
        for _a in actions(build(_r, hover=_hv)):
            seen.add(_a)
            ck(action_known(_a),
               "phase=%s hover=%s 发出了 runtime 认不出的 action_id：%r"
               % (_ph.value, _hv, _a))
for _need in ("act:run", "act:undo", "act:new", "act:clear", "send", "grip",
              "tab:0", "tab:1"):
    ck(_need in seen, "常见操作没有发出命中区：%s" % _need)
ck("act:confirm" in seen and "act:recommended" in seen,
   "选项卡没发出 act:confirm / act:recommended：%s" % sorted(seen))
ck("act:approve" in seen and "act:toggle_code" in seen,
   "审批门没发出 act:approve / act:toggle_code：%s" % sorted(seen))
ck("collapse:objects" in seen, "新增对象清单没有折叠命中区")

# ================================================================= 2. 命中回读一致
# 画出来的地方必须真的点得到：每个命中区自己的中心点回读出同一个 id。
sect("hit_roundtrip")
fresh(CLARIFY, run)
o = build()
_bad = []
for h in hits(o):
    if h[3] <= 0 or h[4] <= 0:
        _bad.append(("零尺寸", h[5]))
        continue
    # grip 的中心点被 send 故意盖住（重叠优先级是契约），单独验，见下。
    if h[5] == "grip":
        continue
    if PT.hit_test(o["items"], h[1] + h[3] * 0.5, h[2] + h[4] * 0.5) != h[5]:
        _bad.append(("中心点不回读", h[5]))
# grip 至少要有一块不与 send 重叠、能真正点到的地方，否则这个拖拽把手是死的
_g = [h for h in hits(o) if h[5] == "grip"][0]
_s = [h for h in hits(o) if h[5] == "send"][0]
_free = [(x, y) for x in (_g[1] + 1.0, _g[1] + _g[3] - 1.0)
         for y in (_g[2] + 1.0, _g[2] + _g[4] - 1.0)
         if PT.hit_test(o["items"], x, y) == "grip"]
ck(_free, "grip 被 send 完全盖住，拖拽把手点不到")
ck(not _bad, "%d 个命中区回读不一致：%s" % (len(_bad), _bad[:5]))
ck(PT.hit_test(o["items"], -10.0, -10.0) is None, "面板外不该命中")
ck(PT.hit_test(o["items"], W + 50.0, H + 50.0) is None, "面板外右下不该命中")

# send 与 grip 在右下角本来重叠，send 是主操作，必须由后绘制的那个拿到。
_overlap = not (_g[1] > _s[1] + _s[3] or _g[2] > _s[2] + _s[4]
                or _g[1] + _g[3] < _s[1] or _g[2] + _g[4] < _s[2])
ck(_overlap, "send 与 grip 不再重叠，重叠优先级这条契约已失效")
ck(PT.hit_test(o["items"], _g[1] + _g[3] * 0.5, _g[2] + _g[4] * 0.5) == "send",
   "重叠处 send 没压过 grip，主操作点不到")

# ================================================================= 3. 状态机契约
# 每个 Phase 必须落到唯一且正确的呈现：动效 / 结算卡 / 什么都不出。
sect("phase_contract")
_TERMINAL = (Phase.PARTIAL, Phase.FAILED, Phase.STOPPED)
_NO_CARD = tuple(p for p in Phase
                 if p not in _TERMINAL and p is not Phase.AWAITING_APPROVAL)
for _ph in Phase:
    _r = make_run(_ph, Err.NET, pending=True)
    _o = build(_r)
    _t = texts(_o)
    _thinking = any("正在思考" in t for t in _t)
    _card = any(t == "做到一半，已停下" or t == "已停止后续步骤"
                or "该做的事：" in t or t == "等你批准" for t in _t)
    ck((_ph in BUSY) == _thinking,
       "phase=%s（BUSY=%s）动效出现与否不对：thinking=%s"
       % (_ph.value, _ph in BUSY, _thinking))
    ck(_card == (_ph in _TERMINAL or _ph is Phase.AWAITING_APPROVAL),
       "phase=%s 结算卡出现与否不对：card=%s" % (_ph.value, _card))
    ck(len(_o["items"]) > 20, "phase=%s 渲染结果几乎是空的" % _ph.value)
for _ph in _NO_CARD:
    _r = make_run(_ph, Err.NET)
    ck(not any("该做的事：" in t or t == "做到一半，已停下"
               or t == "已停止后续步骤"
               for t in texts(build(_r))),
       "phase=%s 不该出结算卡却出了" % _ph.value)

# ================================================================= 4. 红只留给 FAILED
sect("color_law")


def has_fail_red(o):
    return any(it[0] in ("rect", "border") and it[-1] == T.ST_FAIL_BG
               for it in o["items"])


def has_red_bar(o):
    """错误专用 3px 红条。"""
    return any(it[0] == "rect" and near(it[3], 3.0, 0.01)
               and it[-1] == T.ST_FAIL_TEXT for it in o["items"])


for _ph in Phase:
    _o = build(make_run(_ph, Err.NET, pending=True))
    ck(has_red_bar(_o) == (_ph is Phase.FAILED),
       "phase=%s 红色告警条出现与否不对（红条只属于 FAILED）" % _ph.value)
    ck(has_fail_red(_o) == (_ph is Phase.FAILED),
       "phase=%s 红色底板出现与否不对" % _ph.value)

_o = build(make_run(Phase.PARTIAL, Err.NET))
ck(any(it[0] == "rect" and it[-1] == T.ST_WARN_BG for it in _o["items"]),
   "PARTIAL 没有中性底板")
ck(not any(it[-1] in (T.ST_FAIL_BG, T.ST_FAIL_TEXT, T.ST_FAIL_BORDER)
           for it in _o["items"] if isinstance(it[-1], tuple)),
   "PARTIAL 卡片里出现了 FAILED 专属红")
_o = build(make_run(Phase.FAILED, Err.NET))
ck(any(it[-1] == T.ST_FAIL_DIM for it in _o["items"]),
   "FAILED 卡片缺少次级红字（guide 的 effect/retry 没画出来）")

# ================================================================= 5. 文案铁律：技术噪音
sect("banned_words")
for _ph in Phase:
    _r = make_run(_ph, Err.NET, pending=True)
    _leaked = [t for t in texts(build(_r)) if any(w in t for w in BANNED_CHAT)]
    # STOPPED 的结算卡原本写着「已停止后续轮次」，把「轮次」漏进了对话页；
    # 已改为「已停止后续步骤」，这里随之从 xfail 升级为常规断言防回归。
    ck(not _leaked,
       "phase=%s 对话页出现了只该在详情/设置里的词：%s" % (_ph.value, _leaked))

# ================================================================= 6. 文案铁律：每条都要说清三件事
# 发生了什么 / 现在什么样 / 下一步做什么 —— 结算卡少一段，用户就不知道该干嘛。
sect("three_parts")
_t = texts(build(make_run(Phase.PARTIAL)))
ck("做到一半，已停下" in _t, "PARTIAL 没标题：%s" % _t[4:9])
ck(any(t.startswith("还没做：") and "D 形" in t for t in _t),
   "PARTIAL 没列出「还没做」的具体步骤：%s" % _t[4:9])
ck(any("再说一句" in t for t in _t),
   "PARTIAL 结尾没告诉用户下一步该干什么：%s" % _t[4:9])
_t = texts(build(make_run(Phase.STOPPED)))
ck("已停止后续步骤" in _t, "STOPPED 没标题：%s" % _t[4:9])
ck(any("保留在场景里" in t for t in _t),
   "STOPPED 没说明现在什么样：%s" % _t[4:9])
ck(any(t.startswith("想继续") for t in _t),
   "STOPPED 没告诉用户下一步该干什么：%s" % _t[4:9])

# 「已经做了」必须报**真实**新增物体名（Receipt.added_names 是拿 before/after
# 两次场景快照做差算出来的），不能只说一句空话。
# 注意顺序：Receipt 在构造时就拍下 before 快照，所以 run 必须先建、物体后加。
_r = make_run(Phase.PARTIAL)
_o1 = _o2 = None
try:
    _o1 = bpy.data.objects.new("Mug_杯身", bpy.data.meshes.new("Mug_杯身_mesh"))
    _o2 = bpy.data.objects.new("Mug_把手", bpy.data.meshes.new("Mug_把手_mesh"))
    bpy.context.scene.collection.objects.link(_o1)
    bpy.context.scene.collection.objects.link(_o2)
    ck("Mug_杯身" in _r.receipt.added_names,
       "造数失败：Receipt.added_names 没算出新增物体：%s" % _r.receipt.added_names)
    _t = texts(build(_r))
    _added = [t for t in _t if t.startswith("已经做了：")]
    ck(bool(_added), "PARTIAL 场景真加了物体，卡片却没说已经做了什么：%s" % _t[4:9])
    ck(any("Mug_杯身" in t for t in _added),
       "PARTIAL 的「已经做了」没列出真实新增物体名：%s" % _added)
finally:
    for _o in (_o1, _o2):
        if _o is not None:
            bpy.data.objects.remove(_o, do_unlink=True)
    for _m in ("Mug_杯身_mesh", "Mug_把手_mesh"):
        if _m in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes[_m])
# 场景没动时也不能空着，要说清「改动都保留着」
_t = texts(build(make_run(Phase.PARTIAL)))
ck(any(t.startswith("已经做了：") and "保留" in t for t in _t),
   "PARTIAL 在场景无改动时没有兜底文案：%s" % _t[4:9])

# guide() 是 FAILED 的文案来源：每个错误码都必须给出完整四段，
# 且四段原样出现在卡片上 —— 少一段就是用户看不懂发生了什么。
sect("error_guide")
for _e in Err:
    _g = guide(_e)
    for _k in ("title", "effect", "action", "retry"):
        ck(bool(str(_g.get(_k, "")).strip()),
           "Err.%s 的 guide 缺 %s" % (_e.value, _k))
for _e in (Err.NET, Err.KEY_MISSING, Err.TIMEOUT, Err.INTERNAL, Err.BUDGET_ROUNDS):
    _t = texts(build(make_run(Phase.FAILED, _e)))
    _g = guide(_e)
    ck(_g["title"] in _t, "Err.%s 的 title 没出现在错误卡上：%s" % (_e.value, _t[4:9]))
    ck(("该做的事：" + _g["action"]) in _t,
       "Err.%s 没给出「该做的事」：%s" % (_e.value, _t[4:9]))
    ck(_g["effect"] in _t, "Err.%s 没说明现在到底什么情况：%s" % (_e.value, _t[4:9]))
ck(guide(Err.NET) is guide(Err.NET.value),
   "guide 对枚举和字符串值给出了不同结果")

# ================================================================= 7. 结果四 pane 互斥
sect("result_panes")
fresh(CLARIFY, run)
_seen_text = {}
for _tab, _needle in PANE_NEEDLE.items():
    state.result_tab = _tab
    _t = texts(build())
    _seen_text[_tab] = set(_t)
    ck(any(_needle in t for t in _t), "pane %s 缺少专属内容 %r" % (_tab, _needle))
    _foreign = [o for o in PANE_NEEDLE
                if o != _tab and any(PANE_NEEDLE[o] in t for t in _t)]
    ck(not _foreign, "pane %s 混进了别的 pane 的内容：%s" % (_tab, _foreign))
for _a in PANE_NEEDLE:
    for _b in PANE_NEEDLE:
        if _a >= _b:
            continue
        ck(_seen_text[_a] != _seen_text[_b],
           "pane %s 与 %s 内容完全相同，结果区 tab 没互斥" % (_a, _b))
    ck("qt:%s" % _a in actions(build()), "结果区缺 qt:%s 命中区" % _a)
# 只有当前 pane 有下划线
for _tab in PANE_NEEDLE:
    state.result_tab = _tab
    _u = [it for it in build()["items"]
          if it[0] == "rect" and it[-1] == T.QTABS_ON_LINE]
    ck(len(_u) == 1, "result_tab=%s 时选中下划线数为 %d，应为 1" % (_tab, len(_u)))
state.result_tab = "OBJECTS"

# 折叠：收起后对象清单整个消失，命中区仍在（否则点不回来）
for _flag in (True, False):
    state.show_result_list = _flag
    _t = texts(build())
    _n = sum(1 for n in ("Mug_锥形马克杯", "Mug_Handle", "Mug_陶瓷") if n in _t)
    ck(_n == (3 if _flag else 0),
       "show_result_list=%s 时对象行数为 %d" % (_flag, _n))
    ck(any(t in ("收起", "展开") for t in _t),
       "show_result_list=%s 时折叠条没有状态文案" % _flag)
    ck("collapse:objects" in actions(build()),
       "show_result_list=%s 时折叠命中区消失（点不回来）" % _flag)
state.show_result_list = True

# ================================================================= 8. 选项卡语义
sect("options")
fresh(CLARIFY, run)
_parsed = U.parse_interactive_options(CLARIFY)
_qs = _parsed.get("questions") or []
ck(len(_qs) == 3, "追问解析出 %d 组，预期 3" % len(_qs))
ck(bool(_parsed.get("all_recommended")), "没有拼出「按推荐来」的一键指令")
ck("直筒微收口" in _parsed["all_recommended"]
   and "哑光陶瓷" in _parsed["all_recommended"],
   "推荐指令没带上各题推荐值：%r" % _parsed["all_recommended"])

_o = build()
_opt = [h for h in hits(_o) if h[5].startswith("opt:")]
_exp = sum(len(q["options"]) for q in _qs)
ck(len(_opt) == _exp,
   "选项行命中区 %d 个，解析出 %d 个选项" % (len(_opt), _exp))
_ids = [h[5] for h in _opt]
ck(len(set(_ids)) == len(_ids), "选项行命中区有重复 id：%s" % _ids)
for _a, _b in zip(_opt, _opt[1:]):
    ck(_a[2] + _a[4] <= _b[2] + 0.01,
       "选项行纵向重叠，点上面一行会命中下面一行：%s / %s" % (_a[5], _b[5]))
ck(PT.hit_test(_o["items"], _opt[0][1] + _opt[0][3] * 0.5,
               _opt[0][2] + _opt[0][4] * 0.5) == _opt[0][5],
   "选项行中心点不回读自己的 id")

# 选中态：只有选中那一行铺高亮底 + 圆点；hover 行只在没被选中时铺 hover 底。
_lbl = _qs[0]["options"][1]["label"]
state.selected_options_json = '{"0": ["%s"]}' % _lbl.replace('"', '\\"')
_o = build(hover="opt:0:0")
ck(sum(1 for it in _o["items"]
       if it[0] == "rect" and it[-1] == T.QROW_SEL_BG) == 1,
   "选中行没有且仅有一个高亮底：%r" % _lbl)
ck(sum(1 for it in _o["items"]
       if it[0] == "rect" and it[-1] == T.QROW_HOVER_BG) == 1,
   "hover 行没有铺 hover 底")
ck(sum(1 for it in _o["items"]
       if it[0] == "circ" and it[-1] == T.RADIO_DOT) == 1,
   "选中行没画实心圆点")
ck(any(t.startswith("已选 1 项") and _lbl in t for t in texts(_o)),
   "选中后没有回显「已选 N 项」：%s" % [t for t in texts(_o) if "选" in t])
# hover 与选中落在同一行时，选中优先，两种底色不能同时画
_o = build(hover="opt:0:1")
ck(sum(1 for it in _o["items"]
       if it[0] == "rect" and it[-1] == T.QROW_HOVER_BG) == 0,
   "hover 压在选中行上时还画了 hover 底")
state.selected_options_json = "{}"
_o = build()
ck(any("还没选" in t for t in texts(_o)),
   "未选时没有提示可以直接按推荐来：%s" % [t for t in texts(_o) if "选" in t])
ck(not any(it[0] == "rect" and it[-1] == T.QROW_SEL_BG for it in _o["items"]),
   "什么都没选却铺了选中底")

# ================================================================= 9. 滚动
sect("scroll")
fresh()
for _i in range(60):
    U.push_history(state, "你" if _i % 2 == 0 else "AI",
                   "第 %d 条消息：把手再粗一点，底部加一圈防滑" % _i, run=None)
_top = build()
_sh = _top["stream_rect"][3]
_max = max(0.0, _top["content_h"] - _sh)
ck(_max > 0, "造了 60 条历史但内容没超出可视区，滚动断言是空的")
ck(near(build(scroll=None)["scroll_eff"], _max),
   "scroll=None 没有贴底：%s vs %s" % (build(scroll=None)["scroll_eff"], _max))
ck(near(build(scroll=0.0)["scroll_eff"], 0.0), "scroll=0 没有回到顶部")
ck(near(build(scroll=-50.0)["scroll_eff"], 0.0), "负 scroll 没被钳到 0")
ck(near(build(scroll=1e9)["scroll_eff"], _max), "超界 scroll 没被钳到最大值")
ck(near(build(scroll=_max * 0.5)["scroll_eff"], _max * 0.5),
   "中间位置 scroll 没被原样尊重")
for _s in (None, 0.0, 137.0, 1e9):
    ck(near(build(scroll=_s)["content_h"], _top["content_h"]),
       "content_h 随 scroll=%s 变了（滚动不该改内容高度）" % _s)
# 滚动条滑块位置必须跟 scroll 走；内容装得下时不该画滑块。
_SX = W - P.MARGIN - T.SCROLL_W


def thumb_y(o):
    _t = [it for it in o["items"]
          if it[0] == "rect" and near(it[1], _SX, 0.01)]
    return _t[0][2] if _t else None


_ys = [thumb_y(build(scroll=_s)) for _s in (0.0, _max * 0.25, _max * 0.5, _max)]
ck(all(y is not None for y in _ys), "内容超长却没画滚动条滑块")
ck(_ys == sorted(_ys) and len(set(_ys)) == len(_ys),
   "滑块位置没随滚动单调变化：%s" % [round(y, 1) if y else None for y in _ys])
ck(near(thumb_y(build(scroll=None)), _ys[-1]),
   "贴底时的滑块位置不等于最大滚动位置")
fresh()
ck(thumb_y(build()) is None, "内容装得下却画了滚动条")

# 消息区整体被 clip 包住，命中区不许越出裁剪框（否则点到空白处会误触）
fresh()
for _i in range(60):
    U.push_history(state, "你" if _i % 2 == 0 else "AI", "第 %d 条" % _i, run=None)
_o = build(scroll=0.0)
_ops = [it[0] for it in _o["items"]]
ck("clip" in _ops and "unclip" in _ops and _ops.index("clip") < _ops.index("unclip"),
   "消息区没有 clip/unclip 包住，滚动越界会画到输入区上面")
_clip = [it for it in _o["items"] if it[0] == "clip"][0]
_esc = [h[5] for h in hits(_o)
        if _ops.index("clip") < _o["items"].index(h) < _ops.index("unclip")
        and not (_clip[1] <= h[1] and _clip[2] <= h[2]
                 and h[1] + h[3] <= _clip[1] + _clip[3] + 0.5
                 and h[2] + h[4] <= _clip[2] + _clip[4] + 0.5)]
ck(not _esc, "有 %d 个命中区越出了消息区裁剪框：%s" % (len(_esc), _esc[:5]))
# 短内容贴底（紧贴输入框），不浮在顶部留一大片空白
fresh(ai="好的。")
_o = build()
_ys = [it[2] for it in _o["items"] if it[0] == "text" and it[1] < 300]
ck(_ys and max(_ys) > _o["stream_rect"][1] + _o["stream_rect"][3] - 260,
   "内容装得下时没有贴到输入区上方：%s" % [round(y, 1) for y in _ys])

# ================================================================= 10. 耗时贴在 AI 头像行
sect("avatar")
fresh()
_r2 = make_run(Phase.COMPLETED)
_r2.elapsed = 7.4
_r2.receipt = Receipt()
U.push_history(state, "你", "做一个陶瓷茶杯", run=None)
U.push_history(state, "AI", "好的，我先确认几个细节。", run=_r2)
_o = P.build(P.Ctx(state, _r2, U, W, H))
_t = [it for it in _o["items"]
      if it[0] == "text" and it[3] in ("AI 助手", "7秒")]
ck(len(_t) == 2, "AI 行没有同时画出「AI 助手」和耗时：%s"
   % [(x[3], round(x[2], 1)) for x in _t])
if len(_t) == 2:
    _nm = [x for x in _t if x[3] == "AI 助手"][0]
    _du = [x for x in _t if x[3] == "7秒"][0]
    ck(abs(_nm[2] - _du[2]) < T.LINE_H,
       "耗时没和助手名排在同一行：y=%s vs %s" % (round(_nm[2], 1), round(_du[2], 1)))
    ck(_du[1] >= _nm[1] + PT.text_width("AI 助手", T.FS_HEAD),
       "耗时压到了助手名头上")

# ================================================================= 11. 底部按钮文案
sect("buttons")
fresh()
_t = texts(build())
for _want in ("发送指令", "回退发送", "新建任务", "清空记录"):
    ck(_want in _t, "底部按钮文案缺失：%s（实有 %s）"
       % (_want, [x for x in _t if x in ("发送指令", "回退发送", "新建任务", "清空记录")]))
for _dead in ("回退到发送前", "开启新任务", "更多", "确认"):
    ck(_dead not in _t, "已废弃的按钮文案又回来了：%s" % _dead)

# ================================================================= 12. painter 纯函数
sect("text_metrics")
ck(near(PT.text_width("", 12), 0.0), "空串宽度应为 0")
ck(PT.text_width("字", 24) > PT.text_width("字", 12), "字号变大宽度没变大")
_prev, _mono = -1.0, True
for _n in range(0, 12):
    _w = PT.text_width("字" * _n, 12)
    if _w < _prev:
        _mono = False
    _prev = _w
ck(_mono, "文本宽度随长度非单调")
ck(PT.text_width("中文abc", 12) > PT.text_width("abc", 12),
   "中文字宽没比同长拉丁串宽（_is_cjk 判定可能坏了）")

# wrap 不得丢字，也不得超宽
for _s in ("这是一段很长的中文文案用来测试折行",
           "latin words only here to test boundary behaviour",
           "中文 mixed with latin words 混排 数字 12345"):
    for _mw in (30.0, 40.0, 90.0, 200.0):
        _ls = PT.wrap(_s, 12, _mw)
        ck(bool(_ls) and all(isinstance(l, str) for l in _ls),
           "wrap 返回了非法结构：%r" % _ls)
        ck("".join(ch for l in _ls for ch in l if not ch.isspace())
           == "".join(ch for ch in _s if not ch.isspace()),
           "wrap 在 max_w=%s 时把内容折丢了：%r" % (_mw, _ls))
        _over = [l for l in _ls if PT.text_width(l, 12) > _mw]
        ck(not _over, "wrap 在 max_w=%s 时排出了超宽行：%r" % (_mw, _over))
ck(PT.wrap("a\nb\n\nc", 12, 400.0) == ["a", "b", "", "c"],
   "wrap 没保留原文的换行/空行：%r" % PT.wrap("a\nb\n\nc", 12, 400.0))
ck(PT.wrap("", 12, 100.0) == [""], "wrap('') 应返回 ['']")
# 单字就比 max_w 宽时只能溢出那一行，绝不能死循环或整段消失
ck(PT.wrap("超", 12, 3.0) == ["超"], "wrap 连单字都吞了：%r" % PT.wrap("超", 12, 3.0))
# max_w 越大行数不能变多
_cnt = [len(PT.wrap("中文混排 latin words 测试 12345", 12, m))
        for m in (40.0, 120.0, 400.0)]
ck(_cnt == sorted(_cnt, reverse=True), "max_w 变大反而行数变多：%s" % _cnt)

# ellipsize：截断后必须放得下，放得下就别截
_s = "一个非常非常长的参数名字用来触发省略号 with latin tail"
ck(PT.ellipsize("短", 12, 400.0) == "短", "放得下的串被截断了")
for _mw in (10.0, 30.0, 60.0, 200.0):
    _e = PT.ellipsize(_s, 12, _mw)
    ck(_e.endswith("…"), "ellipsize 没补省略号：%r" % _e)
    ck(_s.startswith(_e[:-1]), "ellipsize 不是原串的前缀：%r" % _e)
    ck(PT.text_width(_e, 12) <= max(_mw, PT.text_width("…", 12)),
       "ellipsize 结果仍超宽：%r @ %s" % (_e, _mw))
ck(PT.ellipsize(_s, 12, 10.0) == "…",
   "max_w 极小时没退化成单个省略号：%r" % PT.ellipsize(_s, 12, 10.0))
# 留得越多截得越狠，单调
_short = [PT.ellipsize(_s, 12, m) for m in (40.0, 80.0, 160.0, 400.0)]
ck([len(x) for x in _short] == sorted(len(x) for x in _short),
   "ellipsize 长度没随 max_w 单调变化：%s" % [len(x) for x in _short])

# ================================================================= 结果
for _f in FAILS:
    print("  FAIL:", _f)
for _x in XFAILS:
    print("  XFAIL:", _x)
for _p in XPASSES:
    print("  XPASS:", _p)
print(SUMMARY % (OK[0], len(FAILS), len(XFAILS), len(XPASSES)))
sys.exit(1 if FAILS else 0)
