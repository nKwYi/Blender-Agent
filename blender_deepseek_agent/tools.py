import contextlib
import io
import math

import bpy

MAX_SCENE_OBJECTS = 50

_OPS = {
    "cube": bpy.ops.mesh.primitive_cube_add,
    "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
    "cylinder": bpy.ops.mesh.primitive_cylinder_add,
    "cone": bpy.ops.mesh.primitive_cone_add,
    "plane": bpy.ops.mesh.primitive_plane_add,
}


def _prim_kwargs(kind, size):
    """把 size 统一成“一个单位的包围盒尺寸”：5.2 上只有 cube/plane 有 size 参数。"""
    s = max(float(size), 0.001)
    if kind in ("cube", "plane"):
        return {"size": s}
    if kind == "sphere":
        return {"radius": s / 2.0}
    if kind == "cylinder":
        return {"radius": s / 2.0, "depth": s}
    return {"radius1": s / 2.0, "radius2": 0.0, "depth": s}


def _vec3(value, name):
    """容忍模型给标量、两个分量或多给分量；不合法就报可读错误。"""
    if value is None:
        return (0.0, 0.0, 0.0)
    if isinstance(value, (int, float)):
        items = [float(value)]
    else:
        try:
            items = [float(v) for v in value]
        except (TypeError, ValueError):
            raise ValueError(f"{name} 需要 2-3 个数字，收到 {value!r}")
    if len(items) == 1:
        items = items * 3
    elif len(items) == 2:
        items = items + [0.0]
    elif len(items) != 3:
        raise ValueError(f"{name} 需要 2-3 个数字，收到 {value!r}")
    return tuple(items)


def _rgba(value):
    if isinstance(value, (int, float)):
        value = [value, value, value]
    try:
        parts = [float(v) for v in value]
    except (TypeError, ValueError):
        raise ValueError(f"color 需要 3 或 4 个 0-1 的数字，收到 {value!r}")
    if len(parts) == 3:
        parts.append(1.0)
    if len(parts) != 4:
        raise ValueError(f"color 需要 3 或 4 个 0-1 的数字，收到 {value!r}")
    return tuple(min(max(v, 0.0), 1.0) for v in parts)


def _object_or_error(args):
    wanted = str(args.get("object_name", ""))
    obj = bpy.data.objects.get(wanted)
    if obj is None:
        raise LookupError(f"找不到物体 '{wanted}'，可先调用 get_scene_info 查看场景里的物体名")
    return obj


def _principled(mat):
    if mat.node_tree is None:
        mat.use_nodes = True
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def _set_input(bsdf, socket_name, value, applied, skipped):
    # 按 socket 名字取，5.2 上 Principled 的口径与 4.x 一致；缺失就跳过而不是抛
    socket = bsdf.inputs.get(socket_name)
    if socket is None:
        skipped.append(socket_name)
        return
    socket.default_value = value
    applied.append(socket_name)


def handle_create_primitive(args):
    kind = str(args.get("type", "")).lower()
    op = _OPS.get(kind)
    if op is None:
        raise ValueError(f"不支持的几何体类型 {args.get('type')!r}，可选：{', '.join(_OPS)}")
    size = float(args.get("size", 1.0))
    op(location=_vec3(args.get("location"), "location"), **_prim_kwargs(kind, size))
    obj = bpy.context.active_object
    if args.get("name"):
        obj.name = str(args["name"])
    return {
        "status": "ok",
        "object_name": obj.name,
        "object_type": obj.type,
        "size": size,
        "location": [round(v, 4) for v in obj.location],
    }


def handle_set_material(args):
    obj = _object_or_error(args)
    if not hasattr(obj.data, "materials"):
        raise ValueError(f"{obj.name} 是 {obj.type}，不能直接赋网格材质")
    color = _rgba(args.get("color"))
    mat_name = f"MAT_{obj.name}"
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    bsdf = _principled(mat)
    if bsdf is None:
        raise ValueError(f"材质 {mat_name} 里没有 Principled BSDF 节点")

    applied, skipped = [], []
    _set_input(bsdf, "Base Color", color, applied, skipped)
    _set_input(bsdf, "Metallic", float(args.get("metallic", 0.0)), applied, skipped)
    _set_input(bsdf, "Roughness", float(args.get("roughness", 0.5)), applied, skipped)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return {
        "status": "ok",
        "object_name": obj.name,
        "material": mat.name,
        "base_color": list(color),
        "inputs_set": applied,
        "inputs_missing": skipped,
    }


def handle_transform_object(args):
    obj = _object_or_error(args)
    result = {"status": "ok", "object_name": obj.name}
    if args.get("location") is not None:
        obj.location = _vec3(args["location"], "location")
        result["location"] = [round(v, 4) for v in obj.location]
    if args.get("rotation") is not None:
        degrees = _vec3(args["rotation"], "rotation")
        obj.rotation_euler = tuple(math.radians(v) for v in degrees)
        result["rotation_degrees"] = list(degrees)
    if args.get("scale") is not None:
        obj.scale = _vec3(args["scale"], "scale")
        result["scale"] = [round(v, 4) for v in obj.scale]
    bpy.context.view_layer.update()
    return result


def handle_get_scene_info(args):
    objects = list(bpy.context.scene.objects)
    shown = objects[:MAX_SCENE_OBJECTS]
    active = bpy.context.active_object
    return {
        "total_objects": len(objects),
        "returned": len(shown),
        "truncated": len(objects) > len(shown),
        "objects": [
            {
                "name": o.name,
                "type": o.type,
                "location": [round(v, 4) for v in o.location],
                "has_material": any(s.material for s in o.material_slots),
            }
            for o in shown
        ],
        "active_object": active.name if active else None,
        "mode": bpy.context.mode,
    }


_EXEC_G = None


def _exec_globals():
    """execute_blender_code 的执行作用域。

    补上 mathutils：Blender 的文本编辑器/控制台默认预导入
    Vector / Matrix / Euler，模型（按 Blender 惯例写的脚本）会直接用
    `Vector((0,0,0))`。原先作用域只有 bpy/math/context，模型一用
    Vector 就 NameError，然后反复重试 —— 每次重试都要用户在面板里
    批一次，GUI 下会直接耗尽轮次。
    """
    global _EXEC_G
    if _EXEC_G is None:
        import mathutils
        _EXEC_G = {"bpy": bpy, "math": math, "mathutils": mathutils,
                   "Vector": mathutils.Vector, "Matrix": mathutils.Matrix,
                   "Euler": mathutils.Euler, "Quaternion": mathutils.Quaternion,
                   "context": bpy.context, "__name__": "deepseek_exec"}
    return _EXEC_G


def handle_execute_code(args):
    code = str(args.get("code", ""))
    if not code.strip():
        raise ValueError("code 为空")
    scope = _exec_globals()
    before = set(scope)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<deepseek_execute_code>", "exec"), scope)
    except Exception as error:
        return {
            "error": f"{type(error).__name__}: {error}",
            "type": type(error).__name__,
            "stdout": buffer.getvalue()[:500],
        }
    defined = {k: str(scope[k])[:80] for k in sorted(set(scope) - before)[:20]}
    return {"status": "ok", "stdout": buffer.getvalue()[:500], "defined": defined}


_HANDLERS = {
    "create_primitive": handle_create_primitive,
    "set_material": handle_set_material,
    "transform_object": handle_transform_object,
    "get_scene_info": handle_get_scene_info,
    "execute_blender_code": handle_execute_code,
}


def execute_tool(name, args):
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}", "available": sorted(_HANDLERS)}
    if not isinstance(args, dict):
        return {"error": f"工具参数必须是对象，收到 {type(args).__name__}"}
    try:
        return handler(args)
    except Exception as error:
        return {"error": str(error), "type": type(error).__name__}
