"""无头验证工作台排版：喂合成宽高，断言几何不变量。不开窗口、不碰 GL。

用法：blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_workspace_layout.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_deepseek_agent import workspace as W  # noqa: E402
from blender_deepseek_agent.state import Err, Phase, ToolCall  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {str(detail)[:200]}")


def fake_wrap(text, max_px, size, max_lines=6):
    """确定性折行：每 40 字一行。避免测试依赖 GL 字体度量。"""
    text = str(text or "")
    out = [text[i:i + 40] for i in range(0, len(text), 40)] or [""]
    return out[:max_lines]


class StubReceipt:
    def __init__(self, lines, skipped=()):
        self.lines = lines
        self.skipped = list(skipped)
        self.boundary_pushed = True
        self.undo_enabled = True

    def recovery_lines(self):
        return ["场景已改变", "恢复：已建立 Undo 边界", "任务级回滚点：未提供"]


class StubRun:
    def __init__(self, **kw):
        self.phase = kw.get("phase", Phase.COMPLETED)
        self.err = kw.get("err", Err.NONE)
        self.detail = kw.get("detail", "")
        self.rounds = kw.get("rounds", 3)
        self.limit = 4
        self.elapsed = kw.get("elapsed", 4.1)
        self.calls = kw.get("calls", [])
        self.usage = kw.get("usage", {"prompt_tokens": 1576, "prompt_cache_hit_tokens": 1408,
                                      "completion_tokens": 61})
        self.reply = kw.get("reply", "建了 RedCube 并上了红色材质。")
        self.skipped = kw.get("skipped", [])
        self.receipt = kw.get("receipt", StubReceipt(["objects: 3 → 4", "materials: 2 → 3"]))


def call(name, status="ok", summary="ok"):
    c = ToolCall("x", name, {})
    c.result = {"status": "ok"} if status == "ok" else {"error": "boom"}
    c.elapsed = 0.4
    return c


def ctx(run=None, prompt="创建一个红色立方体", history=None, busy=False):
    return {"cfg": {"model": "deepseek-flash", "provider": "DeepSeek", "api_key": True, "max_turns": 4},
            "run": run, "busy": busy, "prompt": prompt,
            "history": history if history is not None else []}


def zones_of(items, w, h, scroll=0.0):
    return W.layout(items, w, h, scroll, wrap=fake_wrap)


# ---------- 1. 空态 ----------
items = W.build(ctx())
zones, total = zones_of(items, 300, 900)
check("空态只有 4 块（头/状态/输入/动作）", [k for k, _ in zones] == ["header", "status", "prompt", "actions"],
      [k for k, _ in zones])
check("空态内容高度不超过一屏，无需滚动", total <= 900, total)

# ---------- 2. 不重叠 + 不越界 ----------
for width in (200, 300, 500):
    for state in ("idle", "busy", "partial", "failed", "big"):
        if state == "idle":
            c = ctx()
        elif state == "busy":
            c = ctx(StubRun(phase=Phase.TOOL_RUNNING, calls=[call("create_primitive")], usage={}), busy=True)
        elif state == "partial":
            c = ctx(StubRun(phase=Phase.PARTIAL, err=Err.BUDGET_ROUNDS, detail="x" * 300, skipped=["transform_object"]))
        elif state == "failed":
            c = ctx(StubRun(phase=Phase.FAILED, err=Err.NET, detail="连不上 DeepSeek（代理 127.0.0.1:7890）", reply=""))
        else:
            c = ctx(StubRun(reply="中" * 400, calls=[call("get_scene_info") for _ in range(12)]),
                    history=[{"role": "你", "text": "长" * 200}] * 20)
        zz, tt = zones_of(W.build(c), width, 700)
        ys = sorted((z.y, z.y + z.h, k) for k, z in zz)
        overlap = [ys[i][2] for i in range(1, len(ys)) if ys[i][0] < ys[i - 1][1] - 0.01]
        check(f"w={width} {state} 卡片不重叠", not overlap, overlap)
        out = [k for k, z in zz if z.x < 0 or z.x + z.w > width + 0.01]
        check(f"w={width} {state} 不横向溢出", not out, out)
        check(f"w={width} {state} 内容高度为正", tt > 0, tt)

# ---------- 3. 命中区与绘制区同源 ----------
items = W.build(ctx(StubRun()))
zz, _ = zones_of(items, 320, 900)
actions = next(z for k, z in zz if k == "actions")
buttons = actions.payload["buttons"]
check("按钮命中区数量 == 4", len(buttons) == 4, len(buttons))
check("每个按钮命中区都落在动作区内", all(abs(b.y - (actions.y + 4)) < 0.01 and b.x >= actions.x - 0.01
                      and b.x + b.w <= actions.x + actions.w + 0.01 for b in buttons))
check("按钮互不重叠", all(buttons[i].x + buttons[i].w <= buttons[i + 1].x + 0.01 for i in range(3)),
      [(b.x, b.x + b.w) for b in buttons])
hits = [z for _, z in zz]
for _, z in zz:
    if isinstance(z.payload, dict):
        hits.extend(z.payload.get("buttons", []))
clickable = [z.key for z in hits if z.key]
check("可点击区只有这 4 个键", sorted(clickable) == ["new", "refresh", "run", "stop"], clickable)
center = buttons[0]
check("命中测试能点中正中央", center.hit(center.x + center.w / 2, center.y + center.h / 2))
check("命中测试不会误吞相邻按钮", not buttons[0].hit(buttons[2].x + 2, buttons[2].y + 2))

# ---------- 4. 滚动 ----------
c = ctx(StubRun(reply="中" * 400, calls=[call("get_scene_info") for _ in range(12)]))
items = W.build(c)
zz, total = zones_of(items, 300, 500)
max_scroll = max(0.0, total - 500 + W.MARGIN)
check("内容超出时才允许滚动", total > 500 and max_scroll > 0, (total, max_scroll))
top_first = next(z for k, z in zz if k == "header")
zz0, _ = zones_of(items, 300, 500, 0.0)
check("scroll=0 时首块贴顶", abs(500 - W.MARGIN - top_first.y - top_first.h) < 0.01,
      (top_first.y, top_first.h))
zz1, _ = zones_of(items, 300, 500, max_scroll)
last = zz1[-1][1]
check("滚到底时末块不高于区域顶部", last.y + last.h <= 500 + 0.01, last.y + last.h)
check("滚到底时末块落在可见范围内", last.y < 500, last.y)

# ---------- 5. 长中文不撑破宽度 ----------
c = ctx(StubRun(reply="很长的中文指令" * 80))
zz, _ = zones_of(W.build(c), 200, 900)
reply = next(z for k, z in zz if k == "reply")
check("极窄 200px 下回复块宽度仍是内宽", abs(reply.w - (200 - 2 * W.MARGIN)) < 0.01, reply.w)
check("极窄下内容变高而不是变宽", reply.h > 60, reply.h)

# ---------- 6. 绘制要的数据必须真在 zone 上（_paint 拿 None 就是上一版的崩溃） ----------
REQUIRED = {"header": dict, "status": dict, "prompt": str, "actions": dict}
for width in (200, 300, 500):
    for label, c in (("idle", ctx()), ("busy", ctx(StubRun(phase=Phase.TOOL_RUNNING), busy=True)),
                     ("failed", ctx(StubRun(phase=Phase.FAILED, err=Err.NET)))):
        zz, _ = zones_of(W.build(c), width, 900)
        missing = [k for k, z in zz
                   if k in REQUIRED and not isinstance(z.payload, REQUIRED[k])]
        check(f"w={width} {label} 每块都带上了绘制所需数据", not missing, missing)
        st = next(z for k, z in zz if k == "status")
        check(f"w={width} {label} 状态块有文案和颜色",
              isinstance(st.payload.get("line"), tuple) and len(st.payload["line"]) == 2
              and isinstance(st.payload["line"][0], str), st.payload)

print(f"RESULT workspace: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
