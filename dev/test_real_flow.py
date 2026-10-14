# -*- coding: utf-8 -*-
"""真实追问链路测试：模糊需求 → 模型反问 → 解析选项 → 用户选择 → 确认 → 真正建模。

全程用扩展偏好里的真实 Key，结果脱敏落盘供 GUI 截图复用。
用法：blender.exe --background --python-exit-code 1 -P dev/test_real_flow.py
"""
import io
import json
import os
import sys
import time
import types

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
LOGP = os.path.join(OUT, "real_flow.txt")
lines = []
fails = []


def log(*a):
    s = " ".join(str(x) for x in a)
    lines.append(s)
    print("[FLOW]", s)
    with io.open(LOGP, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def check(name, cond, detail=""):
    if cond:
        log("PASS", name)
    else:
        fails.append(name)
        log("FAIL", name, "::", detail)


EXT = "bl_ext.user_default.blender_deepseek_agent"
addon = bpy.context.preferences.addons.get(EXT)
if addon is None:
    log("FATAL: 扩展未启用")
    sys.exit(1)
_s = addon.preferences
snap = types.SimpleNamespace(
    provider=_s.provider, api_key=_s.api_key, model=_s.model, base_url=_s.base_url,
    timeout=_s.timeout, max_turns=_s.max_turns, wall_budget=_s.wall_budget,
    allow_arbitrary_code=_s.allow_arbitrary_code, history_page=_s.history_page)
if not snap.api_key.strip():
    log("FATAL: 没有 Key")
    sys.exit(1)

ext_mod = sys.modules.get(EXT)
if ext_mod is not None and hasattr(ext_mod, "unregister"):
    try:
        ext_mod.unregister()
        for cls in getattr(getattr(ext_mod, "config", None), "classes", ()):
            try:
                bpy.utils.register_class(cls)
            except Exception:
                pass
    except Exception as e:
        log("unregister failed: %s" % e)
if hasattr(bpy.types.Scene, "deepseek_agent"):
    del bpy.types.Scene.deepseek_agent
bda.register()
config._prefs = lambda: snap
U.PACKAGE_ID = EXT
K = snap.api_key

state = bpy.context.scene.deepseek_agent
state.history.clear()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
for c in list(bpy.data.collections):
    bpy.data.collections.remove(c)

# ---------- 阶段 1：模糊需求，期望模型反问 ----------
P1 = "帮我做个水杯"
log("=== 阶段1 prompt:", P1)
t0 = time.time()
U.dispatch_run_prompt(bpy.context, text_override=P1)
run = CONTROLLER.run
log("phase=%s rounds=%s wall=%.1fs" % (run.phase, run.rounds, time.time() - t0))
log("reply=%s" % config.redact(run.reply or "", K)[:500])
check("阶段1 未直接建对象（应当反问）", len(bpy.context.scene.objects) == 0,
      "%d objects" % len(bpy.context.scene.objects))

ai_msgs = [m for m in state.history if m.role == "AI"]
check("历史里有 AI 回复", len(ai_msgs) >= 1, len(ai_msgs))

qtext = ai_msgs[-1].text if ai_msgs else ""
parsed = U.parse_interactive_options(qtext)
questions = parsed.get("questions", [])
log("parsed questions = %d" % len(questions))
for q in questions:
    log("   Q: %s -> %s" % (q.get("title"), [o.get("label") for o in q.get("options", [])]))
check("模型确实反问了可选项", len(questions) >= 1, qtext[:200])
check("预分配了「其他」备注槽位", len(state.notes) >= len(questions),
      "notes=%d questions=%d" % (len(state.notes), len(questions)))

# ---------- 阶段 2：模拟用户选择并确认 ----------
if questions:
    q0 = questions[0]
    opts = q0.get("options", [])
    pick = opts[0].get("value") if opts else ""
    if len(opts) > 1:
        pick = opts[1].get("value")
    log("=== 阶段2 选择:", pick)
    state.selected_options_json = json.dumps({"0": [pick]}, ensure_ascii=False)
    if len(state.notes) >= 2:
        state.notes[1].text = "杯口要能叠放"

    sent = {}
    _orig = U.dispatch_run_prompt

    def _cap(ctx, text_override=None, reporter=None):
        sent["t"] = text_override
        return _orig(ctx, text_override=text_override, reporter=reporter)

    U.dispatch_run_prompt = _cap
    try:
        # 原生 DEEPSEEK_OT_confirm_options 已随 GPU 自绘改造退役；
        # 「按用户所选提交」的活通路是 DEEPSEEK_OT_submit_selection。
        bpy.ops.deepseek.submit_selection()
    finally:
        U.dispatch_run_prompt = _orig

    built = sent.get("t", "")
    log("拼出的确认指令 = %s" % built)
    check("确认指令包含用户所选", pick in built, built[:200])
    check("确认指令包含「其他」补充", "杯口要能叠放" in built, built[:200])
    check("提交后选择被清空", state.selected_options_json == "{}", state.selected_options_json)

    run2 = CONTROLLER.run
    log("阶段2 phase=%s rounds=%s" % (run2.phase, run2.rounds))
    for c in run2.calls:
        log("   - %-22s %s" % (c.name, config.redact(c.summary(), K)[:80]))
    log("对象数 = %d" % len(bpy.context.scene.objects))
    for o in bpy.context.scene.objects:
        log("   * %s (%s) dims=%s" % (o.name, o.type,
                                       tuple(round(v, 3) for v in o.dimensions)))
    check("确认后真的建出了对象", len(bpy.context.scene.objects) > 0)
    check("阶段2 完成态", run2.phase == Phase.COMPLETED, str(run2.phase))

# ---------- 落盘真实数据，供 GUI 截图 ----------
dump = {
    "history": [{"role": m.role, "text": config.redact(m.text, K),
                 "duration_str": m.duration_str, "steps_json": m.steps_json,
                 "artifacts_json": m.artifacts_json, "collection_name": m.collection_name}
                for m in state.history],
    "selected_options_json": state.selected_options_json,
    "notes": [n.text for n in state.notes],
    "session_topic": state.session_topic,
}
io.open(os.path.join(OUT, "real_flow_data.json"), "w", encoding="utf-8").write(
    json.dumps(dump, ensure_ascii=False, indent=2))
log("VERDICT =", "PASS" if not fails else "FAIL %s" % fails)
sys.exit(1 if fails else 0)