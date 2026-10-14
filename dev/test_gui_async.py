"""GUI 实测：非阻塞忙态、bpy 主线程纪律、真 Undo、审批门、真实 API 端到端。

用法：blender.exe -P dev/test_gui_async.py     （不要加 --factory-startup）
结果写进 dev/out/gui_async.json
"""
import importlib
import json
import os
import threading
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
PKG = "bl_ext.user_default.blender_deepseek_agent"

m = importlib.import_module(PKG)
worker = importlib.import_module(PKG + ".worker")
config = importlib.import_module(PKG + ".config")
state = importlib.import_module(PKG + ".state")
Phase, Err = state.Phase, state.Err

MAIN = threading.get_ident()
R = {"main_thread": MAIN, "checks": [], "notes": {}}


def check(name, cond, detail=""):
    R["checks"].append({"name": name, "ok": bool(cond), "detail": str(detail)[:220]})
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else " :: " + str(detail)[:200]))


def save():
    with open(os.path.join(OUT, "gui_async.json"), "w", encoding="utf-8") as h:
        json.dump(R, h, ensure_ascii=False, indent=1)


def call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def comp(msg):
    return {"choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]}


# 记录工具执行发生在哪个线程
orig_execute = worker.Controller._execute_main
seen_threads = []


def spy_execute(self, call):
    seen_threads.append(threading.get_ident())
    return orig_execute(self, call)


worker.Controller._execute_main = spy_execute

ticks = {"n": 0}


def heartbeat():
    ticks["n"] += 1
    return 0.05


bpy.app.timers.register(heartbeat, first_interval=0.05)

CTRL = worker.CONTROLLER
SCENE = bpy.context.scene


def objs():
    return {o.name for o in bpy.context.scene.objects}


# ---------------- 步骤驱动 ----------------
STEP = {"i": 0, "t0": 0}


def fake_slow(messages, tools, **kw):
    """假装一次慢网络：在 worker 线程里睡 2.5 秒。"""
    R["notes"]["chat_thread_is_main"] = (threading.get_ident() == MAIN)
    n = sum(1 for m in messages if m.get("role") == "assistant")
    time.sleep(2.5)
    if n == 0:
        return comp({"role": "assistant", "content": None,
                     "tool_calls": [call("g1", "create_primitive", {"type": "cube", "name": "GuiAsync", "size": 1})]})
    return comp({"role": "assistant", "content": "建好了 GuiAsync"})


def fake_needs_approval(messages, tools, **kw):
    n = sum(1 for m in messages if m.get("role") == "assistant")
    if n == 0:
        return comp({"role": "assistant", "content": None,
                     "tool_calls": [call("g2", "execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (5,0,0)"})]})
    return comp({"role": "assistant", "content": "已移动"})


def start(cfg_over, prompt):
    cfg = config.get_config()
    cfg.update(cfg_over)
    return CTRL.start(prompt, cfg)


def step_async():
    STEP["t0"] = ticks["n"]
    ok = start({"chat": fake_slow, "api_key": "sk-fake", "max_turns": 3, "wall_budget": 40}, "建一个立方体")
    check("任务已启动", ok)
    return "wait_async"


def step_async_done():
    run = CTRL.run
    waited = ticks["n"] - STEP["t0"]
    R["notes"]["heartbeat_during_wait"] = waited
    check("网络等待期间主线程仍在跑（心跳 ≥10 次）", waited >= 10, f"心跳 {waited} 次")
    check("chat 跑在非主线程", R["notes"].get("chat_thread_is_main") is False)
    check("工具执行全在主线程", seen_threads and all(t == MAIN for t in seen_threads), seen_threads)
    check("GuiAsync 真的被创建", "GuiAsync" in objs(), sorted(objs()))
    check("任务态为 COMPLETED", run.phase is Phase.COMPLETED, run.phase)
    check("回执记录了真实差异", any("objects" in x for x in run.receipt.lines), run.receipt.lines)
    return "undo"


def step_undo():
    """走真按钮用的那个 operator，而不是自己拼上下文。"""
    before = "GuiAsync" in objs()
    try:
        res = bpy.ops.deepseek.undo_task()
        R["notes"]["undo_result"] = str(res)
    except Exception as error:
        R["notes"]["undo_result"] = f"{type(error).__name__}: {error}"
    check("撤销本次任务：边界真的能回退（物体消失）", before and "GuiAsync" not in objs(), R["notes"]["undo_result"])
    return "approve"


def step_approve():
    seen_threads.clear()
    ok = start({"chat": fake_needs_approval, "api_key": "sk-fake", "allow_arbitrary_code": False,
                "max_turns": 3, "wall_budget": 12}, "移动它")
    return "wait_approve" if ok else "real"


def step_approve_done():
    run = CTRL.run
    check("状态机真的经过 AWAITING_APPROVAL", "AWAITING_APPROVAL" in run.phases, run.phases)
    check("待批准的那一步没有被偷偷执行", any(c.approval_state == "pending" or c.approval_state == "granted"
                                          for c in run.calls), [c.approval_state for c in run.calls])
    check("等待批准期间界面仍在跑（主线程没被阻塞）", ticks["n"] > 0)
    CTRL.resolve_approval(True)
    while CTRL.busy:
        CTRL.tick()
    moved = tuple(round(v) for v in bpy.data.objects["Cube"].location)
    check("批准后代码真的执行", moved == (5, 0, 0), moved)
    check("批准后的执行仍在主线程", all(t == MAIN for t in seen_threads), seen_threads)
    return "real"


def step_real():
    cfg = config.get_config()
    if not cfg["api_key"]:
        check("真实 API 端到端（跳过：无 Key）", True, "偏好设置里没有 Key")
        return "finish"
    sc = bpy.context.scene.deepseek_agent
    sc.prompt = "创建一个红色立方体，命名为 RealCube，然后把它移到 (2, 0, 0)"
    bpy.ops.deepseek.run_prompt()
    STEP["t0"] = time.monotonic()
    return "wait_real"


def step_real_done():
    run = CTRL.run
    R["notes"]["real"] = {
        "phase": run.phase.value, "err": run.err.value, "rounds": run.rounds,
        "elapsed": run.elapsed, "usage": run.usage, "reply": run.reply[:300],
        "calls": [{"name": c.name, "status": c.status, "elapsed": c.elapsed, "summary": c.summary()} for c in run.calls],
        "receipt": run.receipt.lines if run.receipt else [],
        "recovery": run.receipt.recovery_lines() if run.receipt else [],
    }
    check("真实 API：任务完成", run.phase is Phase.COMPLETED, run.phase)
    cube = bpy.data.objects.get("RealCube") or next((o for o in bpy.context.scene.objects if o.name.startswith("RealCube")), None)
    check("真实 API：物体真的出现", cube is not None, sorted(objs()))
    if cube is not None:
        loc = tuple(round(v, 2) for v in cube.location)
        check("真实 API：多步指令都生效（位置到位）", loc == (2.0, 0.0, 0.0), loc)
        if cube.data.materials:
            bsdf = next((n for n in cube.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            col = tuple(round(v, 2) for v in bsdf.inputs["Base Color"].default_value) if bsdf else None
            check("真实 API：材质是红的", col and col[0] >= 0.8 and col[1] <= 0.2, col)
    check("真实 usage 被记录（不是估算）", bool((run.usage or {}).get("prompt_tokens")), run.usage)
    return "finish"


queue_steps = ["async", "wait_async", "undo", "approve", "wait_approve", "real", "wait_real", "finish"]
idx = {"i": 0}


def driver():
    name = queue_steps[idx["i"]]
    try:
        if name.startswith("wait_"):
            if CTRL.busy:
                return 0.1
            fn = {"wait_async": step_async_done, "wait_approve": step_approve_done,
                  "wait_real": step_real_done}[name]
            nxt = fn()
        else:
            nxt = {"async": step_async, "undo": step_undo, "approve": step_approve,
                   "real": step_real, "finish": lambda: None}[name]()
    except Exception as error:
        check(f"步骤 {name} 未抛异常", False, f"{type(error).__name__}: {error}")
        nxt = None
    if name == "finish":
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.shading.type = 'MATERIAL'
                    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                    if region:
                        with bpy.context.temp_override(window=window, area=area, region=region):
                            bpy.ops.screen.region_toggle(region_type='UI')
        R["notes"]["phases_final"] = (CTRL.run.phases if CTRL.run else [])
        save()
        failed = [c["name"] for c in R["checks"] if not c["ok"]]
        print(f"GUIRESULT failed={len(failed)} total={len(R['checks'])}")
        if failed:
            print("GUIFAILED " + ", ".join(failed))
        return None
    idx["i"] += 1
    save()
    return 0.1


bpy.app.timers.register(driver, first_interval=1.5)
print("GUIPROBE started; heartbeat", ticks["n"])
