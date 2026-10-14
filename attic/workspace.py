"""工作台：征用一个 INFO 空间当画布，坐标与命中全部自己算。

为什么不用 N 侧栏：Blender 不提供任何"原生控件画在哪"的查询，自绘皮和原生控件
对不齐是结构性的。自己占一块区域后，布局、滚动、命中都归我们，问题消失。

中文输入仍然留在侧栏原生 textbox（bpy.types.Event 无输入法组合字段，实测）。
"""
import bpy

from . import look
from .config import get_config
from .state import BUSY, Err, Phase, guide
from .worker import CONTROLLER

SPACE_TYPE = 'INFO'
_OWNED = []          # Area 不支持 id properties（5.2 实测 TypeError），只能自己记

ROW = 22
CARD_PAD = 10
GAP = 10
MARGIN = 12


class Zone:
    __slots__ = ("key", "x", "y", "w", "h", "payload")

    def __init__(self, key, x, y, w, h, payload=None):
        self.key, self.x, self.y, self.w, self.h, self.payload = key, x, y, w, h, payload

    def hit(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


def phase_line(run, busy):
    if run is None:
        return ("准备好了", look.TEXT_DIM)
    phase = run.phase
    if phase is Phase.TOOL_RUNNING:
        return (f"正在改你的场景 · 第 {len(run.calls) + 1} 步", look.WARN)
    if phase is Phase.REQUESTING:
        return ("在想怎么做…", look.WARN)
    if phase is Phase.AWAITING_APPROVAL:
        return ("要你确认：它想动你的场景", look.BAD)
    if phase is Phase.COMPLETED:
        return ("做完了", look.OK)
    if phase is Phase.PARTIAL:
        return ("做到一半，已停下", look.WARN)
    if phase is Phase.FAILED:
        return ("没做成", look.BAD)
    if phase is Phase.STOPPED:
        return ("已按你说的停下", look.WARN)
    return ("准备好了", look.TEXT_DIM)


def build(ctx):
    """产出显示列表：[(kind, data)]。绘制与命中读同一份数据。全部输入来自 ctx，不读全局。"""
    run = ctx.get("run")
    cfg = ctx["cfg"]
    items = [("header", {"model": cfg["model"], "provider": cfg["provider"],
                         "key": bool(cfg["api_key"])})]
    items.append(("status", {"line": phase_line(run, ctx["busy"]),
                             "rounds": run.rounds if run else 0,
                             "limit": run.limit if run else cfg["max_turns"],
                             "elapsed": run.elapsed if run else 0.0,
                             "busy": ctx["busy"]}))
    items.append(("prompt", ctx["prompt"]))
    items.append(("actions", None))
    if run and run.err and run.err is not Err.NONE:
        items.append(("notice", {"err": run.err, "guide": guide(run.err), "detail": run.detail}))
    if run and run.receipt and (run.receipt.lines or run.skipped):
        items.append(("receipt", {"lines": run.receipt.lines or ["场景未改变"],
                                  "skipped": list(run.skipped),
                                  "recovery": run.receipt.recovery_lines()}))
    if run and run.reply:
        items.append(("reply", run.reply))
    if run and run.calls:
        items.append(("tools", run.calls))
    if run and run.usage:
        items.append(("usage", run.usage))
    if ctx["history"]:
        items.append(("history", ctx["history"]))
    return items


ACTION_BUTTONS = (("run", "执行"), ("stop", "停止后续"), ("new", "新任务"), ("refresh", "刷新"))


def layout(items, width, height, scroll=0.0, wrap=None):
    """纯函数：喂进宽高与内容，返回 (zones, 内容总高)。不读 bpy。

    命中框和绘制框都从这里出，所以两者不可能对不上——上一版把按钮命中区
    写在 _paint 里，等于"画出来才有点击区"，那是点不中的结构性原因。
    y 先按"距顶部多少"累加，最后统一翻成底左原点并施加滚动。
    """
    wrap = wrap or look.wrap
    zones, y = [], 0.0
    inner = max(120.0, width - 2 * MARGIN)

    def push(kind, h, data=None, key=""):
        nonlocal y
        zones.append((kind, Zone(key, MARGIN, y, inner, h, data)))
        y += h

    by_kind = dict(items)
    push("header", 46, by_kind.get("header"))
    push("status", 58, by_kind.get("status"))
    push("prompt", 30 + 18 * min(3, max(1, str(by_kind.get("prompt", "")).count("\n") + 1)),
         by_kind.get("prompt"))

    bw = (inner - 3 * 8) / 4
    buttons = []
    for i, (key, label) in enumerate(ACTION_BUTTONS):
        buttons.append(Zone(key, MARGIN + i * (bw + 8), y + 4, bw, 30))
    push("actions", 40, {"buttons": buttons})

    for kind, data in items[4:]:
        if kind == "notice":
            push("notice", 58 + 18 * len(wrap(data.get("detail") or "", inner - 24, 12, 3)))
        elif kind == "receipt":
            push("receipt", 26 + 18 * (len(data["lines"]) + len(data["skipped"]) + 1))
        elif kind == "reply":
            push("reply", 26 + 18 * len(wrap(data, inner - 24, 13, 8)))
        elif kind == "tools":
            push("tools", 26 + ROW * min(len(data), 8))
        elif kind == "usage":
            push("usage", 44)
        elif kind == "history":
            push("history", 26 + ROW * min(len(data), 6))
        y += GAP

    total = y + MARGIN
    offset = height - MARGIN
    for kind, z in zones:
        z.y = offset - (z.y + z.h) + scroll
        if isinstance(z.payload, dict):
            for sub in z.payload.get("buttons", []):
                sub.y = z.y + 4
    return zones, total


def draw(width, height, scroll, ctx, wrap=None):
    items = build(ctx)
    zones, total = layout(items, width, height, scroll, wrap=wrap)
    look.begin()
    look.rect(0, 0, width, height, look.BG)
    look.clip(0, 0, width, height)
    for kind, z in zones:
        _paint(kind, z, ctx)
    look.clip_reset()
    look.end()
    hits = [z for _, z in zones]
    for _, z in zones:
        if isinstance(z.payload, dict):
            hits.extend(z.payload.get("buttons", []))
    return hits, total


def _card(z, color=look.CARD):
    look.round_rect(z.x, z.y, z.w, z.h, color)
    look.rect(z.x + 1, z.y + z.h - 1, z.w - 2, 1, look.LINE)


def _paint(kind, z, ctx):
    x, y, w, h = z.x, z.y, z.w, z.h
    tx = x + 12
    if kind == "header":
        d = z.payload or {}
        look.round_rect(x, y, w, h, look.CARD_HI)
        look.rect(x + 1, y + h - 3, w - 2, 3, look.ACCENT if d.get("key") else look.BAD)
        look.text(tx, y + 16, "Blender AI 工作台", 15, look.TEXT_ON)
        look.text(x + w - 150, y + 18, f"{d.get('provider', '')} · {d.get('model', '')}", 11, look.TEXT_DIM)
    elif kind == "status":
        d = z.payload
        text, color = d["line"]
        look.round_rect(x, y, w, h, look.CARD)
        if d["busy"]:
            import math
            import time
            ang = (time.time() * 3.0) % (2 * math.pi)
            look.rect(x + 12 + 6 * math.cos(ang), y + h / 2 - 3 + 6 * math.sin(ang), 6, 6, color)
        else:
            look.rect(x + 14, y + h / 2 - 4, 8, 8, color)
        look.text(tx + 16, y + 20, text, 14, look.TEXT_ON)
        look.text(x + w - 120, y + 22, f"{d['rounds']}/{d['limit']} · {d['elapsed']:.0f}s", 11, look.TEXT_DIM)
    elif kind == "prompt":
        look.round_rect(x, y, w, h, look.CARD_HI)
        look.text(tx, y + h - 20, "指令（在侧栏输入框里改）", 10, look.TEXT_DIM)
        look.text(tx, y + 8, (str(z.payload or "").split("\n")[0] or "（空）")[:60], 12, look.TEXT)
    elif kind == "actions":
        colors = {"run": look.ACCENT, "stop": look.BAD, "new": look.CARD_HI, "refresh": look.CARD_HI}
        labels = dict(ACTION_BUTTONS)
        for sub in (z.payload or {}).get("buttons", []):
            look.round_rect(sub.x, sub.y, sub.w, sub.h, colors.get(sub.key, look.CARD_HI))
            label = labels.get(sub.key, "")
            look.text(sub.x + sub.w / 2 - look.text_width(label, 12) / 2, sub.y + 8, label, 12, look.TEXT_ON)
    elif kind == "notice":
        d = z.payload
        look.round_rect(x, y, w, h, look.CARD)
        look.rect(x, y, 3, h, look.BAD)
        look.text(tx, y + h - 20, d["guide"]["title"], 12, look.BAD)
        look.text(tx, y + h - 38, d["guide"]["effect"], 11, look.TEXT)
        for i, line in enumerate(look.wrap(d.get("detail") or "", w - 24, 11, 3)):
            look.text(tx, y + h - 54 - i * 16, line, 11, look.TEXT_DIM)
    elif kind == "receipt":
        d = z.payload
        look.round_rect(x, y, w, h, look.CARD)
        look.text(tx, y + h - 20, "变更", 12, look.TEXT_ON)
        yy = y + h - 38
        for line in d["lines"][:5]:
            look.text(tx + 8, yy, "· " + str(line), 11, look.OK)
            yy -= 18
        for line in d["skipped"][:3]:
            look.text(tx + 8, yy, "未做：" + str(line), 11, look.WARN)
            yy -= 18
        look.text(tx + 8, yy, d["recovery"][-1] if d["recovery"] else "", 10, look.TEXT_DIM)
    elif kind == "reply":
        look.round_rect(x, y, w, h, look.CARD_HI)
        look.text(tx, y + h - 20, "AI 说", 11, look.ACCENT)
        for i, line in enumerate(look.wrap(z.payload, w - 24, 13, 8)):
            look.text(tx, y + h - 38 - i * 18, line, 13, look.TEXT)
    elif kind == "tools":
        look.round_rect(x, y, w, h, look.CARD)
        look.text(tx, y + h - 20, "步骤", 11, look.TEXT_DIM)
        for i, call in enumerate(z.payload[:8]):
            color = {"ok": look.OK, "error": look.BAD, "running": look.WARN,
                     "awaiting": look.BAD}.get(call.status, look.TEXT_DIM)
            mark = {"ok": "✓", "error": "✕"}.get(call.status, "·")
            yy = y + h - 40 - i * ROW
            look.text(tx + 4, yy, mark, 12, color)
            look.text(tx + 22, yy, call.name, 12, look.TEXT)
            look.text(tx + 190, yy, call.summary()[:44], 11, look.TEXT_DIM)
    elif kind == "usage":
        u = z.payload or {}
        look.round_rect(x, y, w, h, look.CARD)
        look.text(tx, y + h - 18, "本次用量", 11, look.TEXT_DIM)
        look.text(tx, y + 8,
                  f"输入 {u.get('prompt_tokens', '—')}（缓存 {u.get('prompt_cache_hit_tokens', 0)}） · "
                  f"输出 {u.get('completion_tokens', '—')}", 11, look.TEXT)
    elif kind == "history":
        look.round_rect(x, y, w, h, look.CARD)
        look.text(tx, y + h - 20, "对话（模型只看当前这句）", 11, look.TEXT_DIM)
        for i, item in enumerate(z.payload[-6:]):
            yy = y + h - 38 - i * ROW
            look.text(tx + 4, yy, f"{item.get('role')}：", 11, look.ACCENT)
            look.text(tx + 60, yy, str(item.get("text", ""))[:48], 11, look.TEXT)


def context_of():
    state = bpy.context.scene.deepseek_agent
    return {
        "cfg": get_config(),
        "run": CONTROLLER.run,
        "busy": CONTROLLER.busy,
        "prompt": state.prompt,
        "history": [{"role": i.role, "text": i.text} for i in state.history],
    }


# ---------------------------------------------------------------- 模态与绘制
zones_ref = {"hits": [], "scroll": 0.0, "total": 0.0}


class DEEPSEEK_WT_modal(bpy.types.Operator):
    """在工作台里点击/滚动"""
    bl_idname = "deepseek.workspace_modal"
    bl_label = "工作台"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC'}:
            return {'CANCELLED'}
        if event.type == 'WHEELUPMOUSE' or (event.type == 'MOUSEMOVE' and event.shift):
            zones_ref["scroll"] = min(zones_ref["scroll"] + 40, max(0.0, zones_ref["total"] - context.region.height))
            return {'RUNNING_MODAL'}
        if event.type == 'WHEELDOWNMOUSE':
            zones_ref["scroll"] = max(zones_ref["scroll"] - 40, 0.0)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE'} and event.value == 'PRESS':
            px, py = event.mouse_region_x, event.mouse_region_y
            for z in zones_ref["hits"]:
                if z.key and z.hit(px, py):
                    return self.dispatch(z.key, context)
        return {'RUNNING_MODAL'}

    def dispatch(self, key, context):
        if key == "run":
            bpy.ops.deepseek.run_prompt()
        elif key == "stop":
            CONTROLLER.request_stop()
        elif key == "new":
            bpy.ops.deepseek.new_task()
        elif key == "refresh":
            context.area.tag_redraw()
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


def _draw_cb():
    region = bpy.context.region
    if region is None:
        return
    hits, total = draw(region.width, region.height, zones_ref["scroll"], context_of())
    zones_ref["hits"], zones_ref["total"] = hits, total


handle = {"id": None}


def open_workspace(context):
    area = next((a for a in _OWNED if a in context.screen.areas), None)
    if area is None:
        target = context.area or context.screen.areas[0]
        with context.temp_override(area=target, region=next(r for r in target.regions if r.type == 'WINDOW')):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=0.62)
        area = context.screen.areas[-1]
        area.type = SPACE_TYPE
        _OWNED.append(area)
    install_handler()
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return {'FINISHED'}
    with context.temp_override(window=context.window, area=area, region=region):
        return bpy.ops.deepseek.workspace_modal('INVOKE_DEFAULT')


def install_handler():
    if handle["id"] is None:
        handle["id"] = bpy.types.SpaceInfo.draw_handler_add(_draw_cb, (), 'WINDOW', 'POST_PIXEL')


def remove_handler():
    if handle["id"] is not None:
        bpy.types.SpaceInfo.draw_handler_remove(handle["id"], 'WINDOW')
        handle["id"] = None
