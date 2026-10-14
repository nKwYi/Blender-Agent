"""规范"必须实测"清单的无头部分：线程纪律 / 全局 Undo 真相 / 截图降级 / Key 泄漏。

用法：blender.exe --background --factory-startup --python-exit-code 1 -P dev/probe_facts.py
"""
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy

import blender_deepseek_agent as bda
from blender_deepseek_agent.tools import execute_tool

bda.register()
MAIN = threading.get_ident()
print("P1 main_thread", MAIN)

# ---------- 1. 线程 + 队列 + timers 桥接：bpy 只在主线程 ----------
box = queue.Queue()
where = {}


def worker():
    try:
        _ = bpy.context.scene.name          # 故意在 worker 里碰 bpy，看会不会炸/被记录
        where["worker_touched_bpy"] = "no_error"
    except Exception as e:
        where["worker_touched_bpy"] = f"{type(e).__name__}: {e}"
    where["worker_is_main"] = (threading.get_ident() == MAIN)
    box.put(("create", "ThreadProbe"))


created_in = {}


def poll2():
    drained = []
    while True:
        try:
            drained.append(box.get_nowait())
        except queue.Empty:
            break
    for kind, name in drained:
        execute_tool("create_primitive", {"type": "cube", "name": name})
        created_in["thread_is_main"] = (threading.get_ident() == MAIN)
        created_in["object"] = bpy.data.objects.get(name).name
    return None if drained else 0.05


t = threading.Thread(target=worker)
t.start()
bpy.app.timers.register(poll2, first_interval=0.1)
for _ in range(200):
    if created_in:
        break
    time.sleep(0.05)
t.join(timeout=2)
print("P1 worker_is_main(should be False)", where.get("worker_is_main"))
print("P1 worker_touched_bpy", where.get("worker_touched_bpy"))
print("P1 bpy_created_in_timer_on_main", created_in)
print("P1 timer_removed_after_return_none", bpy.app.timers.is_registered(poll2) is False)

# ---------- 2. 全局 Undo 的真实能力 ----------
pref = bpy.context.preferences.edit
print("P2 global_undo_default", pref.use_global_undo)

before = {o.name for o in bpy.context.scene.objects}
execute_tool("create_primitive", {"type": "cube", "name": "UndoViaOps"})
after_ops = {o.name for o in bpy.context.scene.objects} - before
try:
    res = bpy.ops.ed.undo()
    print("P2 undo_after_ops", res, "removed", "UndoViaOps" not in {o.name for o in bpy.context.scene.objects})
except Exception as e:
    print("P2 undo_after_ops ERR", type(e).__name__, e)

# exec 写入（模型最爱走的路径）：不 push undo 时能不能退
try:
    execute_tool("execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (9,9,9)"})
    r = bpy.ops.ed.undo()
    loc = tuple(round(v) for v in bpy.data.objects['Cube'].location)
    print("P2 undo_after_exec_no_push", r, "location_now", loc)
    execute_tool("execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (7,7,7)\nbpy.ops.ed.undo_push(message='agent')"})
    r = bpy.ops.ed.undo()
    print("P2 undo_after_exec_with_push", r, "location_now", tuple(round(v) for v in bpy.data.objects['Cube'].location))
except Exception as e:
    print("P2 exec ERR", type(e).__name__, e)

pref.use_global_undo = False
try:
    execute_tool("create_primitive", {"type": "cube", "name": "UndoDisabled"})
    r = bpy.ops.ed.undo()
    still = "UndoDisabled" in {o.name for o in bpy.context.scene.objects}
    print("P2 undo_with_global_off", r, "object_still_there", still)
except Exception as e:
    print("P2 undo_with_global_off ERR", type(e).__name__, e)
pref.use_global_undo = True

# ---------- 3. 无 GL 时截图降级 ----------
import os

tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(tmp, exist_ok=True)
for label, fn in (
    ("render.opengl", lambda: bpy.ops.render.opengl(write_still=True, filepath=os.path.join(tmp, "gl.png"))),
    ("screen.screenshot_area", lambda: bpy.ops.screen.screenshot_area(filepath=os.path.join(tmp, "area.png"))),
):
    try:
        r = fn()
        print("P3", label, "->", r)
    except Exception as e:
        print("P3", label, "RAISES", type(e).__name__, str(e)[:110])

fp = os.path.join(tmp, "headless_render.png")
bpy.context.scene.render.filepath = fp
bpy.context.scene.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else bpy.context.scene.render.engine
try:
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(fp, check_existing=False)
    px = list(img.pixels[0:4000])
    mean = sum(px) / len(px)
    spread = max(px) - min(px)
    print("P3 headless_render_file_exists", os.path.exists(fp), "mean", round(mean, 5), "spread", round(spread, 5),
          "=> 黑图可被检测", mean < 0.01 and spread < 0.05)
    bpy.data.images.remove(img)
except Exception as e:
    print("P3 headless_render ERR", type(e).__name__, str(e)[:120])

# ---------- 4. Key 是否泄漏进转录/日志 ----------
SENTINEL = "sk-SENTINEL-must-not-appear-42"
from blender_deepseek_agent import agent as ag

try:
    ag.chat_completion([{"role": "user", "content": "hi"}], ag.TOOLS, api_key=SENTINEL,
                       model="deepseek-flash", base_url="https://api.deepseek.com", timeout=20)
    print("P4 unexpected success")
except ag.AgentError as e:
    leaked = SENTINEL in e.message
    print("P4 error_message_leaks_key", leaked, "| msg_head", e.message[:70])
except Exception as e:
    print("P4 other", type(e).__name__, str(e)[:100])

state = bpy.context.scene.deepseek_agent
state.answer = "sample"
print("P4 state_fields_no_key", not any(SENTINEL in str(getattr(state, f, "")) for f in ("prompt", "answer", "trace")))

print("DONE facts probed")
