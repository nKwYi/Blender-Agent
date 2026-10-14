with open(r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update Seams
old_seams_loop = """        for y_seam, y_sgn in [(y_front - 0.005, -1.0), (y_back + 0.005, 1.0)]:
            # Upper seam line
            p_up = pos + normal * UPPER_OFFSET
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector((p_up.x, y_seam, p_up.z)))
            sm = bpy.context.object
            sm.dimensions = (0.022, 0.06, UPPER_HEIGHT * 1.02)
            sm.rotation_euler = Euler((0.0, -angle_z, 0.0), "XYZ")
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            sm.data.materials.append(mats["dark_steel"])
            seams_col.objects.link(sm)
            bpy.context.scene.collection.objects.unlink(sm)

            # Lower seam line
            p_lo = pos + normal * LOWER_OFFSET
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector((p_lo.x, y_seam, p_lo.z)))
            sm2 = bpy.context.object
            sm2.dimensions = (0.022, 0.06, LOWER_HEIGHT * 1.02)
            sm2.rotation_euler = Euler((0.0, -angle_z, 0.0), "XYZ")
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            sm2.data.materials.append(mats["dark_steel"])
            seams_col.objects.link(sm2)
            bpy.context.scene.collection.objects.unlink(sm2)"""

new_seams_loop = """        for y_seam, y_sgn in [(y_front + 0.002, -1.0), (y_back - 0.002, 1.0)]:
            # Upper seam line (flush dark shadow joint)
            p_up = pos + normal * UPPER_OFFSET
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector((p_up.x, y_seam, p_up.z)))
            sm = bpy.context.object
            sm.dimensions = (0.016, 0.025, UPPER_HEIGHT * 1.01)
            sm.rotation_euler = Euler((0.0, -angle_z, 0.0), "XYZ")
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            sm.data.materials.append(mats["dark_steel"])
            seams_col.objects.link(sm)
            bpy.context.scene.collection.objects.unlink(sm)

            # Lower seam line
            p_lo = pos + normal * LOWER_OFFSET
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=Vector((p_lo.x, y_seam, p_lo.z)))
            sm2 = bpy.context.object
            sm2.dimensions = (0.016, 0.025, LOWER_HEIGHT * 1.01)
            sm2.rotation_euler = Euler((0.0, -angle_z, 0.0), "XYZ")
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            sm2.data.materials.append(mats["dark_steel"])
            seams_col.objects.link(sm2)
            bpy.context.scene.collection.objects.unlink(sm2)"""

if old_seams_loop in text:
    text = text.replace(old_seams_loop, new_seams_loop, 1)
    print("Replaced seams loop successfully.")
else:
    print("Seams loop not found!")

# 2. Update Cantilever Wings: 2 on right, 3 on left
old_wings = """    # 1. High Level Fins (Extending RIGHT from pylon at Y ~ +0.30m to match High Arch depth)
    # Tier 1 (Top Right): Z = 11.0m, length = 3.6m
    create_chamfered_fin(
        "Wing_Top_Right",
        loc=Vector((0.51 + 1.80, 0.30, 11.0)),
        dims=(3.6, 1.10, 0.76),
        mat=mats["silver"],
        chamfer_dir="RIGHT"
    )
    # Tier 2 (Upper-Middle Right): Z = 9.7m, length = 2.6m
    create_chamfered_fin(
        "Wing_UpperMid_Right",
        loc=Vector((0.51 + 1.30, 0.30, 9.7)),
        dims=(2.6, 1.10, 0.60),
        mat=mats["silver"],
        chamfer_dir="RIGHT"
    )

    # 2. Low Level Fins (Extending LEFT from pylon at Y ~ -0.45m to match Low Arch depth)
    # Tier 3 (Lower-Middle Left): Z = 7.85m, length = 4.2m
    create_chamfered_fin(
        "Wing_LowerMid_Left",
        loc=Vector((-0.51 - 2.10, -0.45, 7.85)),
        dims=(4.2, 1.10, 0.76),
        mat=mats["silver"],
        chamfer_dir="LEFT"
    )
    # Tier 4 (Bottom Left): Z = 6.6m, length = 5.6m
    create_chamfered_fin(
        "Wing_Bottom_Left",
        loc=Vector((-0.51 - 2.80, -0.45, 6.6)),
        dims=(5.6, 1.10, 0.60),
        mat=mats["silver"],
        chamfer_dir="LEFT"
    )"""

new_wings = """    # 1. High Level Fins (Extending RIGHT from pylon at Y ~ +0.30m to balance High Left Arch)
    # Tier 1 (Top Right): Z = 11.0m, length = 3.6m
    create_chamfered_fin(
        "Wing_Top_Right",
        loc=Vector((0.51 + 1.80, 0.30, 11.0)),
        dims=(3.6, 0.95, 0.72),
        mat=mats["silver"],
        chamfer_dir="RIGHT"
    )
    # Tier 2 (Upper-Middle Right): Z = 9.7m, length = 2.6m
    create_chamfered_fin(
        "Wing_UpperMid_Right",
        loc=Vector((0.51 + 1.30, 0.30, 9.7)),
        dims=(2.6, 0.95, 0.58),
        mat=mats["silver"],
        chamfer_dir="RIGHT"
    )

    # 2. Low Level Fins (Extending LEFT from pylon at Y ~ -0.45m to balance Low Right Arch)
    # Matching original photo: 3 horizontal fins protruding to the left
    # Tier 3A (Middle-High Left): Z = 8.85m, length = 3.2m
    create_chamfered_fin(
        "Wing_Mid_Left",
        loc=Vector((-0.51 - 1.60, -0.45, 8.85)),
        dims=(3.2, 0.95, 0.58),
        mat=mats["silver"],
        chamfer_dir="LEFT"
    )
    # Tier 3B (Lower-Middle Left): Z = 7.70m, length = 4.6m
    create_chamfered_fin(
        "Wing_LowerMid_Left",
        loc=Vector((-0.51 - 2.30, -0.45, 7.70)),
        dims=(4.6, 0.95, 0.70),
        mat=mats["silver"],
        chamfer_dir="LEFT"
    )
    # Tier 3C (Bottom Left): Z = 6.45m, length = 6.0m
    create_chamfered_fin(
        "Wing_Bottom_Left",
        loc=Vector((-0.51 - 3.00, -0.45, 6.45)),
        dims=(6.0, 0.95, 0.58),
        mat=mats["silver"],
        chamfer_dir="LEFT"
    )"""

if old_wings in text:
    text = text.replace(old_wings, new_wings, 1)
    print("Replaced wings successfully.")
else:
    print("Wings not found!")

with open(r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Done updating build_gate_gemini.py")
