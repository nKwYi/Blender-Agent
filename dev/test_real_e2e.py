# -*- coding: utf-8 -*-
"""真实端到端链路测试：用扩展偏好里已保存的真实 Key，跑完整建模流程。

不打印 Key 本体，全程脱敏（config.redact 会兜底）。
用法：blender.exe --background --python-exit-code 1 -P dev/test_real_e2e.py
"""
import io
import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda                      # noqa: E402
from blender_deepseek_agent import config, ui as U       # noqa: E402
from blender_deepseek_agent.state import Phase            # noqa: E402
from blender_deepseek_agent.worker import CONTROLLER     # noqa: E402

OUT = os.path.join(HERE, "out")
LOGP = os.path.join(OUT, "real_e2e.txt")
lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print("[E2E]", s)
    with io.open(LOGP, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---- 绑定到真实扩展偏好（工作区源码的 __package__ 与扩展安装名不同） ----
EXT = "bl_ext.user_default.blender_deepseek_agent"
addon = bpy.context.preferences.addons.get(EXT)
if addon is None:
    log("FATAL: 扩展未启用，无法取到真实 Key")
    sys.exit(1)

# 先把偏好值拍成纯 Python 对象：之后要注销扩展类，AddonPreferences 实例会失效
import types  # noqa: E402
_src = addon.preferences
snap = types.SimpleNamespace(
    provider=_src.provider, api_key=_src.api_key, model=_src.model,
    base_url=_src.base_url, timeout=_src.timeout, max_turns=_src.max_turns,
    wall_budget=_src.wall_budget, allow_arbitrary_code=_src.allow_arbitrary_code,
    history_page=_src.history_page,
)
if not snap.api_key.strip():
    log("FATAL: 扩展偏好里没有 Key")
    sys.exit(1)
log("captured prefs: provider=%s model=%s key_len=%d"
    % (snap.provider, snap.model, len(snap.api_key)))

# Blender 启动时已自动启用扩展（装在 extensions 目录里的旧副本），
# 必须先注销那些类，再注册工作区源码，否则测的还是旧代码。
ext_mod = sys.modules.get(EXT)
if ext_mod is not None and hasattr(ext_mod, "unregister"):
    try:
        ext_mod.unregister()
        # 把 config 的偏好类补注册回去，否则 Blender 退出时再 disable 会报错
        for cls in getattr(getattr(ext_mod, "config", None), "classes", ()):
            try:
                bpy.utils.register_class(cls)
            except Exception:
                pass
        log("extension unregistered")
    except Exception as e:
        log("unregister extension failed: %s" % e)

if hasattr(bpy.types.Scene, "deepseek_agent"):
    del bpy.types.Scene.deepseek_agent
bda.register()
log("workspace addon registered")

config._prefs = lambda: snap             # 让 get_config 走到真实偏好快照
U.PACKAGE_ID = EXT                       # dispatch_run_prompt 用它读 allow_arbitrary_code

# 扩展类已注销，addons[EXT].preferences 可能读不到；确保任意 Python 被允许
try:
    bpy.context.preferences.addons[EXT].preferences.allow_arbitrary_code = True
    log("arbitrary code allowed via prefs")
except Exception as e:
    log("prefs path unavailable (%s); forcing allow_arbitrary_code in config" % e)
    _orig_get_config = config.get_config

    def _forced():
        c = _orig_get_config()
        c["allow_arbitrary_code"] = True
        return c
    config.get_config = _forced
    U.config.get_config = _forced

cfg = config.get_config()
log("provider=%s model=%s base_url=%s key_len=%d arbitrary_code=%s"
    % (cfg["provider"], cfg["model"], cfg["base_url"],
       len(cfg["api_key"]), cfg["allow_arbitrary_code"]))

state = bpy.context.scene.deepseek_agent
state.history.clear()
state.notes.clear()
state.selected_options_json = "{}"
state.shown_count = 2

# ---- 清空场景 ----
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
for coll in list(bpy.data.collections):
    bpy.data.collections.remove(coll)
log("scene cleared, objects=%d" % len(bpy.context.scene.objects))

PROMPT = "做一个简单的白色立方体，尺寸 2m，不需要材质"
log("prompt:", PROMPT)

t0 = time.time()
rc = U.dispatch_run_prompt(bpy.context, text_override=PROMPT)
dt = time.time() - t0

run = CONTROLLER.run
log("dispatch rc=%s wall=%.1fs" % (rc, dt))
log("phase=%s err=%s rounds=%s elapsed=%.1fs"
    % (run.phase, run.err, run.rounds, run.elapsed))
log("detail=%s" % config.redact(run.detail or "", cfg["api_key"]))
log("reply=%s" % config.redact(run.reply or "", cfg["api_key"])[:400])
log("tool calls:")
for c in run.calls:
    log("   - %-22s status=%-8s %s" % (c.name, c.status,
                                        config.redact(c.summary(), cfg["api_key"])[:90]))
log("usage=%s" % json.dumps(run.usage or {}, ensure_ascii=False))
log("scene objects after = %d" % len(bpy.context.scene.objects))
for o in bpy.context.scene.objects:
    log("   * %s (%s) dims=%s" % (o.name, o.type,
                                   tuple(round(v, 3) for v in o.dimensions)))
log("artifacts keys = %s" % list((run.artifacts or {}).keys()))
log("history len = %d" % len(state.history))
for m in state.history:
    log("   [%s] %s" % (m.role, config.redact(m.text, cfg["api_key"])[:160]))

ok = (run.phase == Phase.COMPLETED and len(bpy.context.scene.objects) > 0)
log("VERDICT =", "PASS" if ok else "NEEDS REVIEW")

# 落盘给 GUI 截图复用（真实数据）
io.open(os.path.join(OUT, "real_e2e_result.json"), "w", encoding="utf-8").write(
    json.dumps({
        "phase": str(run.phase), "rounds": run.rounds, "elapsed": run.elapsed,
        "objects": [o.name for o in bpy.context.scene.objects],
        "calls": [c.name for c in run.calls],
        "reply": config.redact(run.reply or "", cfg["api_key"]),
    }, ensure_ascii=False, indent=2))