"""无头真机测试：在 Blender 5.2.1 里逐个真调 5 个工具，断言场景结果。

用法：
  blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_tools.py
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402
import mathutils  # noqa: E402

import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent.tools import execute_tool  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


def dims(obj):
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    return [round(max(c[i] for c in corners) - min(c[i] for c in corners), 5) for i in range(3)]


bda.register()

check("operator deepseek.run_prompt 已注册", hasattr(bpy.ops, "deepseek") and hasattr(bpy.ops.deepseek, "run_prompt"))
check("Scene.deepseek_agent 属性已挂载", "deepseek_agent" in bpy.types.Scene.bl_rna.properties)
check("Panel DEEPSEEK_PT_chat 已注册", bda.ui.DEEPSEEK_PT_chat.is_registered)
check("详情/设置不再各占一个原生 tab",
      not hasattr(bda.ui, "DEEPSEEK_PT_detail") and not hasattr(bda.ui, "DEEPSEEK_PT_settings"))
categories = {c.bl_category for c in bda.ui.CLASSES if getattr(c, "bl_region_type", None) == 'UI'}
check("N 侧栏只有一个入口", categories == {"AI 对话"}, categories)
check("operator deepseek.new_task 已注册", hasattr(bpy.ops, "deepseek") and hasattr(bpy.ops.deepseek, "new_task"))
check("Operator 不进重启历史", bda.ui.DEEPSEEK_OT_run.bl_options == set())

# 画一个不存在的 icon 会让整个面板静默截断，只能靠这条静态校验兜住
import ast  # noqa: E402

icons_valid = set(bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items.keys())
used_icons = set()
for module in (bda.ui, bda.config):
    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        # 1) icon='XXX' 关键字实参
        if isinstance(node, ast.keyword) and node.arg == "icon" and isinstance(node.value, ast.Constant):
            used_icons.add(node.value.value)
        # 2) PHASE_VIEW 之类的“状态 → 图标”表里的字符串
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").endswith("VIEW"):
            for elt in ast.walk(node.value):
                if isinstance(elt, ast.Tuple):
                    for item in elt.elts:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value.isupper():
                            used_icons.add(item.value)
bad_icons = sorted(used_icons - icons_valid)
check(f"面板用到的 {len(used_icons)} 个 icon 名（含状态表）在 5.2 枚举里", not bad_icons, f"不存在：{bad_icons}")
check("校验器本身有效：GUI 里实测崩掉面板的 PREFS 确实不在枚举里", "PREFS" not in icons_valid and "PREFERENCES" in icons_valid)

for kind in ("cube", "sphere", "cylinder", "cone", "plane"):
    result = execute_tool("create_primitive", {"type": kind, "name": f"T_{kind}", "size": 1.0})
    obj = bpy.data.objects.get(result.get("object_name", ""))
    check(f"create_primitive {kind} 成功", obj is not None, result)
    if obj is None:
        continue
    expected_z = 0.0 if kind == "plane" else 1.0
    actual = dims(obj)
    check(
        f"create_primitive {kind} 的 size=1 → 包围盒 1×1×{expected_z}",
        abs(actual[0] - 1.0) < 1e-4 and abs(actual[1] - 1.0) < 1e-4 and abs(actual[2] - expected_z) < 1e-4,
        f"实际 {actual}",
    )

red = execute_tool("set_material", {"object_name": "T_cube", "color": [1, 0, 0]})
check("set_material 接受三色分量并补 alpha", red.get("status") == "ok", red)
check("set_material 无缺失 socket", not red.get("inputs_missing"), red)
mat = bpy.data.materials.get(red.get("material", ""))
bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
base = tuple(round(v, 5) for v in bsdf.inputs["Base Color"].default_value)
check("Base Color 真的是红色", base == (1.0, 0.0, 0.0, 1.0), base)
check("材质已挂到物体槽位", bpy.data.objects["T_cube"].data.materials[0] is mat)

moved = execute_tool("transform_object", {"object_name": "T_sphere", "location": [2, 0, 0], "rotation": [45, 0, 0]})
sphere = bpy.data.objects["T_sphere"]
check(
    "transform_object 位移生效",
    moved.get("status") == "ok" and tuple(round(v, 4) for v in sphere.location) == (2.0, 0.0, 0.0),
    moved,
)
check(
    "transform_object 按度解释旋转（45° → π/4 弧度）",
    abs(sphere.rotation_euler.x - math.pi / 4) < 1e-6,
    sphere.rotation_euler[:],
)

info = execute_tool("get_scene_info", {})
check("get_scene_info 数量与实际一致", info["total_objects"] == len(bpy.context.scene.objects), info["total_objects"])
check("get_scene_info 标出活动物体", info["active_object"] in bpy.data.objects)
check("get_scene_info 报告红球有材质", next(o for o in info["objects"] if o["name"] == "T_cube")["has_material"])

step1 = execute_tool("execute_blender_code", {"code": "answer = 5\nprint('one')"})
check("execute_blender_code 捕获 stdout", step1.get("stdout", "").strip() == "one", step1)
check("execute_blender_code 报告新变量", "answer" in (step1.get("defined") or {}), step1)
step2 = execute_tool("execute_blender_code", {"code": "print(answer * 2)"})
check("execute_blender_code 变量跨调用常驻", step2.get("stdout", "").strip() == "10", step2)
bad = execute_tool("execute_blender_code", {"code": "1/0"})
check("execute_blender_code 异常回喂模型而不是崩", bad.get("error", "").startswith("ZeroDivisionError"), bad)

check("未知工具名返回可读错误", "Unknown tool" in execute_tool("nope", {}).get("error", ""))
check("类型不支持返回可选清单", "可选" in execute_tool("create_primitive", {"type": "torus"}).get("error", ""))
check("找不到物体返回可操作提示", "get_scene_info" in execute_tool("set_material", {"object_name": "ghost", "color": [1, 0, 0]}).get("error", ""))
check("参数不是对象时不炸", "必须是对象" in execute_tool("create_primitive", "cube").get("error", ""))
check("颜色分量不对时报错", "color" in execute_tool("set_material", {"object_name": "T_cube", "color": [1, 0, 0, 1, 0]}).get("error", ""))

snapshot = {
    "objects": [
        {
            "name": o.name,
            "type": o.type,
            "location": [round(v, 4) for v in o.location],
            "dims": dims(o),
            "material": (o.data.materials[0].name if getattr(o.data, "materials", None) else None),
        }
        for o in bpy.context.scene.objects
    ]
}
out_dir = os.path.join(HERE, "out")
os.makedirs(out_dir, exist_ok=True)
with open(os.path.join(out_dir, "tools.json"), "w", encoding="utf-8") as handle:
    json.dump(snapshot, handle, ensure_ascii=False, indent=2)
print("SCENE_DUMP " + os.path.join(out_dir, "tools.json"))

# 包内相对导入必须逐个能解析：搬走/删掉一个模块后，函数体里的**惰性 import**
# 不会让 py_compile 报错，只会在用户点到那条路径时抛 ModuleNotFoundError（真发生过）。
import ast as _ast  # noqa: E402
import pathlib as _pathlib  # noqa: E402

pkg_dir = _pathlib.Path(bda.__file__).parent
present = {p.stem for p in pkg_dir.glob("*.py")} | {p.name for p in pkg_dir.iterdir() if p.is_dir()}
dangling = []
for mod_file in sorted(pkg_dir.glob("*.py")):
    for node in _ast.walk(_ast.parse(mod_file.read_text(encoding="utf-8"))):
        if isinstance(node, _ast.ImportFrom) and node.level == 1:
            # `from .mod import name` 只有 mod 是模块；`from . import mod` 时 names 才是模块
            targets = [node.module] if node.module else [a.name for a in node.names]
            for tgt in targets:
                if tgt and tgt not in present:
                    dangling.append(f"{mod_file.name}:{node.lineno} -> .{tgt}")
check("包内相对导入没有悬空目标", not dangling, "; ".join(dangling))

print(f"RESULT tools: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
