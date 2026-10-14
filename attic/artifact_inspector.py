"""Blender 场景资产与建模参数提取器。
根据任务生成的新增对象列表，提取高精度结构化信息：
1. 对象清单（名称、类型、拓扑顶点数、所属分类 Tag）
2. 几何与修改器参数（尺寸、壁厚、修改器栈、PBR材质参数）
3. 执行代码摘要
"""
import bpy


def inspect_task_artifacts(added_names, calls=None):
    """根据新增物体与调用列表，解析生成结构化卡片数据字典"""
    objects_list = []
    modifiers_list = []
    materials_list = []
    geo_params = []
    script_snippets = []

    if not added_names:
        added_names = []

    # 1. 遍历对象提取网格、几何与材质数据
    for name in added_names:
        obj = bpy.data.objects.get(name)
        if not obj:
            continue
        obj_type = obj.type
        verts_count = 0
        tag = "Object"
        sub_desc = ""

        if obj_type == 'MESH':
            tag = "Mesh"
            if obj.data:
                try:
                    verts_count = len(obj.data.vertices)
                except Exception:
                    verts_count = 0
            # 语义化构件类型推断
            nl = name.lower()
            if "handle" in nl or "把手" in nl:
                sub_desc = f"贝塞尔把手 · 顶点 {verts_count}"
            elif "foot" in nl or "ring" in nl or "圈足" in nl or "底" in nl:
                sub_desc = f"圈足 6mm · 顶点 {verts_count}"
            elif "body" in nl or "cup" in nl or "杯" in nl or "身" in nl:
                sub_desc = f"旋转体 · 顶点 {verts_count}"
            elif "table" in nl or "desk" in nl or "桌" in nl:
                sub_desc = f"支撑基底 · 顶点 {verts_count}"
            elif "tea" in nl or "water" in nl or "茶" in nl or "水" in nl:
                sub_desc = f"流体折射体 · 顶点 {verts_count}"
            else:
                sub_desc = f"网格结构 · 顶点 {verts_count}"

            # 尺寸分析
            try:
                dim = obj.dimensions
                if dim.x > 0 or dim.y > 0 or dim.z > 0:
                    geo_params.append(("尺寸 (长×宽×高)", f"{dim.x*100:.1f} × {dim.y*100:.1f} × {dim.z*100:.1f} cm"))
            except Exception:
                pass

            # 修改器分析
            for m in obj.modifiers:
                if m.type == 'SUBSURF':
                    modifiers_list.append(f"Subdivision Surface (Catmull-Clark, Levels {getattr(m, 'render_levels', 2)})")
                elif m.type == 'SOLIDIFY':
                    th = getattr(m, 'thickness', 0.0035) * 1000
                    modifiers_list.append(f"Solidify (Thickness {th:.1f}mm, Even Thickness)")
                elif m.type == 'BOOLEAN':
                    sol = getattr(m, 'solver', 'EXACT')
                    modifiers_list.append(f"Boolean (构件熔接, {sol.capitalize()} Mode)")
                elif m.type == 'BEVEL':
                    w = getattr(m, 'width', 0.002) * 1000
                    seg = getattr(m, 'segments', 3)
                    modifiers_list.append(f"Bevel (Weight/Width {w:.1f}mm, Segments {seg})")
                else:
                    modifiers_list.append(f"{m.name} ({m.type.capitalize()})")

            # 材质分析
            for slot in obj.material_slots:
                if slot.material:
                    mat = slot.material
                    mat_entry = {
                        "name": mat.name,
                        "type": "Material",
                        "sub": "PBR 陶瓷与光泽材质" if "porcelain" in mat.name.lower() or "瓷" in mat.name else "PBR 物理材质",
                        "tag": "Material",
                    }
                    if not any(x["name"] == mat.name for x in objects_list):
                        objects_list.append(mat_entry)

                    if mat.use_nodes and mat.node_tree:
                        for node in mat.node_tree.nodes:
                            if node.type == 'BSDF_PRINCIPLED':
                                try:
                                    bc = node.inputs['Base Color'].default_value
                                    hex_col = f"#{int(bc[0]*255):02X}{int(bc[1]*255):02X}{int(bc[2]*255):02X}"
                                    materials_list.append(("Base Color", hex_col))
                                except Exception:
                                    pass
                                if 'Subsurface Weight' in node.inputs:
                                    val = node.inputs['Subsurface Weight'].default_value
                                    if val > 0:
                                        materials_list.append(("Subsurface", f"{val:.2f}"))
                                elif 'Subsurface' in node.inputs:
                                    val = node.inputs['Subsurface'].default_value
                                    if val > 0:
                                        materials_list.append(("Subsurface", f"{val:.2f}"))
                                if 'Roughness' in node.inputs:
                                    materials_list.append(("Roughness", f"{node.inputs['Roughness'].default_value:.2f}"))
                                if 'IOR' in node.inputs:
                                    materials_list.append(("IOR", f"{node.inputs['IOR'].default_value:.2f}"))
                                break

        elif obj_type == 'LIGHT':
            tag = "Light"
            sub_desc = "三点布光 · 展示用"
        elif obj_type == 'CAMERA':
            tag = "Camera"
            sub_desc = "透视构图相机"
        else:
            tag = obj_type.capitalize()
            sub_desc = f"{tag} 场景对象"

        objects_list.insert(0, {
            "name": name,
            "type": obj_type,
            "sub": sub_desc,
            "tag": tag,
        })

    # 2. 提取脚本片段
    if calls:
        for c in calls:
            args = c.args if isinstance(c.args, dict) else {}
            if c.name == "execute_blender_code" and "code" in args:
                script_snippets.append(str(args["code"]).strip())

    return {
        "objects": objects_list,
        "modifiers": list(dict.fromkeys(modifiers_list)),
        "materials": materials_list[:6],
        "geo": geo_params[:5],
        "script": "\n\n".join(script_snippets),
    }
