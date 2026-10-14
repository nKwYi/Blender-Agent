"""实测 GUI 模式下的真实请求与计时。

用法：blender.exe -P dev/test_real_gui.py
"""
import os
import sys
import time
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib
PKG = "bl_ext.user_default.blender_deepseek_agent"
bda = importlib.import_module(PKG)
wk = importlib.import_module(PKG + ".worker")
redact = importlib.import_module(PKG + ".config").redact

try:
    bda.register()
except Exception:
    pass

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

addon = bpy.context.preferences.addons.get("bl_ext.user_default.blender_deepseek_agent")
p = addon.preferences if addon else None
print("REAL_GUI preferences:")
if p:
    p.allow_arbitrary_code = True
    print("  provider:", getattr(p, "provider", None))
    print("  model:", p.model)
    print("  base_url:", p.base_url)
    print("  timeout:", p.timeout)
    print("  wall_budget:", p.wall_budget)
    print("  key prefix:", p.api_key[:8] if p.api_key else None)

state = bpy.context.scene.deepseek_agent
state.prompt = "创建一个茶杯"

print("Triggering deepseek.run_prompt in GUI...", flush=True)
t0 = time.time()
res = bpy.ops.deepseek.run_prompt()
print("Operator result:", res, flush=True)

run = wk.CONTROLLER.run
if run:
    print("RUN RESULT:")
    print("  phase:", run.phase.value)
    print("  rounds:", run.rounds)
    print("  err:", run.err.value)
    print("  detail:", redact(run.detail, p.api_key if p else ""))
    print("  calls:", [(c.name, c.status) for c in run.calls])
    print("  reply:", run.reply[:200] if run.reply else "")
    print("  objects in scene:", [o.name for o in bpy.data.objects])
    print("Total wall clock:", round(time.time() - t0, 2), "s", flush=True)

bpy.ops.wm.quit_blender()
