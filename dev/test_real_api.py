"""真机联调：用已装好的扩展 + 偏好设置里的真 Key，跑文档的完成标志。

用法（不要加 --factory-startup，那会禁用扩展）：
  blender.exe --background -P dev/test_real_api.py
"""
import json
import os

import bpy
import bl_ext.user_default.blender_deepseek_agent as bda
from bl_ext.user_default.blender_deepseek_agent.agent import agent_loop

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = ["创建一个红色立方体"]

report = {"blender": bpy.app.version_string, "runs": []}
failures = []

for prompt in PROMPTS:
    before = {o.name for o in bpy.context.scene.objects}
    try:
        result = agent_loop(prompt)
    except Exception as error:
        failures.append(f"{prompt}: {type(error).__name__}: {error}")
        report["runs"].append({"prompt": prompt, "error": f"{type(error).__name__}: {error}"})
        continue

    new_objects = sorted({o.name for o in bpy.context.scene.objects} - before)
    red_found = None
    for name in new_objects:
        obj = bpy.data.objects.get(name)
        if obj is None or not getattr(obj.data, "materials", None):
            continue
        mat = obj.data.materials[0]
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat and mat.node_tree else None
        if bsdf:
            color = tuple(round(v, 3) for v in bsdf.inputs["Base Color"].default_value)
            if color[0] > 0.6 and color[1] < 0.3 and color[2] < 0.3:
                red_found = {"object": name, "base_color": list(color)}

    entry = {
        "prompt": prompt,
        "reply": result["reply"],
        "rounds": result["rounds"],
        "elapsed": result["elapsed"],
        "usage": result.get("usage"),
        "calls": [{"name": c["name"], "ok": c["ok"], "result": c["result"]} for c in result["calls"]],
        "new_objects": new_objects,
        "red_cube": red_found,
    }
    report["runs"].append(entry)
    print("REAL reply=" + entry["reply"][:200])
    print("REAL rounds=%s elapsed=%s calls=%s" % (result["rounds"], result["elapsed"], [c["name"] for c in result["calls"]]))
    print("REAL usage=" + str(result.get("usage")))
    print("REAL new_objects=" + str(new_objects))
    if not all(c["ok"] for c in result["calls"]):
        failures.append(f"{prompt}: 有工具调用失败")
    if red_found is None:
        failures.append(f"{prompt}: 场景里没有出现带红色的新物体")

with open(os.path.join(HERE, "out", "real_api.json"), "w", encoding="utf-8") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)

print("REAL_RESULT failed=%d" % len(failures))
for line in failures:
    print("REAL_FAIL " + line)
if failures:
    raise SystemExit(1)
