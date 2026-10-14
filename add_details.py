import os

script_path = r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py"
with open(script_path, "r", encoding="utf-8") as f:
    text = f.read()

details_func = '''
# -------------------------------------------------------------------------
# Build Environmental Details (Trees, Traffic Mirrors & Road Signs)
# -------------------------------------------------------------------------
def build_environmental_details(mats):
    env_col = bpy.data.collections.new("COL_Environmental_Details")
    bpy.context.scene.collection.children.link(env_col)

    # 1. Traffic Signs Materials
    mat_orange = bpy.data.materials.new("MAT_Traffic_Orange")
    bsdf_o = next(n for n in mat_orange.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_o.inputs["Base Color"].default_value = (0.95, 0.35, 0.05, 1.0)
    bsdf_o.inputs["Roughness"].default_value = 0.25

    mat_blue_sign = bpy.data.materials.new("MAT_Traffic_Blue")
    bsdf_b = next(n for n in mat_blue_sign.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_b.inputs["Base Color"].default_value = (0.05, 0.32, 0.85, 1.0)
    bsdf_b.inputs["Roughness"].default_value = 0.30

    mat_mirror = bpy.data.materials.new("MAT_Mirror_Chrome")
    bsdf_m = next(n for n in mat_mirror.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_m.inputs["Base Color"].default_value = (0.95, 0.95, 0.95, 1.0)
    bsdf_m.inputs["Metallic"].default_value = 0.98
    bsdf_m.inputs["Roughness"].default_value = 0.05

    mat_tree_leaf = bpy.data.materials.new("MAT_Tree_Leaves")
    bsdf_tl = next(n for n in mat_tree_leaf.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_tl.inputs["Base Color"].default_value = (0.08, 0.22, 0.05, 1.0)
    bsdf_tl.inputs["Roughness"].default_value = 0.60

    mat_trunk = bpy.data.materials.new("MAT_Tree_Trunk")
    bsdf_tr = next(n for n in mat_trunk.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_tr.inputs["Base Color"].default_value = (0.22, 0.16, 0.12, 1.0)
    bsdf_tr.inputs["Roughness"].default_value = 0.85

    # 2. Convex Traffic Mirrors (Two on the central safety island)
    for xm in [-0.85, 0.85]:
        # Pole
        p = create_cylinder(f"Mirror_Pole_{xm}", loc=Vector((xm, -6.2, 0.9)), rot=(0, 0, 0), radius=0.035, depth=1.8, mat=mats["dark_steel"])
        env_col.objects.link(p); bpy.context.scene.collection.objects.unlink(p)
        # Orange housing
        h = create_cylinder(f"Mirror_Housing_{xm}", loc=Vector((xm, -6.2, 1.75)), rot=(math.radians(90), 0, 0), radius=0.34, depth=0.08, mat=mat_orange)
        env_col.objects.link(h); bpy.context.scene.collection.objects.unlink(h)
        # Chrome mirror face
        mf = create_cylinder(f"Mirror_Face_{xm}", loc=Vector((xm, -6.245, 1.75)), rot=(math.radians(90), 0, 0), radius=0.30, depth=0.02, mat=mat_mirror)
        env_col.objects.link(mf); bpy.context.scene.collection.objects.unlink(mf)

    # 3. Speed Limit Sign ("10")
    pole_s = create_cylinder("Speed_Sign_Pole", loc=Vector((2.35, -6.2, 1.0)), rot=(0, 0, 0), radius=0.035, depth=2.0, mat=mats["dark_steel"])
    env_col.objects.link(pole_s); bpy.context.scene.collection.objects.unlink(pole_s)
    # Circle plate
    plate = create_cylinder("Speed_Sign_Plate", loc=Vector((2.35, -6.2, 1.95)), rot=(math.radians(90), 0, 0), radius=0.32, depth=0.03, mat=mats["white_mark"])
    env_col.objects.link(plate); bpy.context.scene.collection.objects.unlink(plate)
    # Red ring
    ring = create_cylinder("Speed_Sign_RedRing", loc=Vector((2.35, -6.216, 1.95)), rot=(math.radians(90), 0, 0), radius=0.31, depth=0.01, mat=mat_orange)
    env_col.objects.link(ring); bpy.context.scene.collection.objects.unlink(ring)

    # 4. Blue Traffic Directional Signboard
    sign_box = create_cube("Direction_Signboard", loc=Vector((2.35, -6.2, 2.50)), dims=(0.85, 0.04, 0.55), mat=mat_blue_sign, bevel=0.015)
    env_col.objects.link(sign_box); bpy.context.scene.collection.objects.unlink(sign_box)

    # 5. Lush Background Trees (Flanking Left & Right Behind Arches)
    tree_locs = [
        # Left background grove (behind high arch)
        (-18.5, 6.0, 4.2), (-22.0, 10.0, 4.8), (-15.0, 12.0, 4.0), (-25.0, 5.0, 5.0),
        (-19.0, 16.0, 4.5), (-14.0, 18.0, 4.2), (-28.0, 12.0, 5.2),
        # Right background grove (behind low arch)
        (18.5, 6.0, 4.0), (22.0, 9.0, 4.6), (15.0, 11.0, 3.8), (25.0, 5.0, 4.8),
        (19.0, 15.0, 4.2), (14.0, 17.0, 3.9), (27.0, 11.0, 5.0),
    ]

    for idx, (tx, ty, tz) in enumerate(tree_locs):
        # Trunk
        tk = create_cylinder(f"Tree_Trunk_{idx}", loc=Vector((tx, ty, tz*0.4)), rot=(0, 0, 0), radius=0.22, depth=tz*0.8, mat=mat_trunk)
        env_col.objects.link(tk); bpy.context.scene.collection.objects.unlink(tk)
        # Foliage Canopy (Multi-spherical organic clusters)
        for sub_i, (dx, dy, dz, r) in enumerate([(0, 0, tz*0.85, tz*0.42), (0.4, -0.3, tz*0.75, tz*0.35), (-0.4, 0.3, tz*0.78, tz*0.36)]):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=16, radius=r, location=Vector((tx+dx, ty+dy, dz)))
            fol = bpy.context.object
            fol.name = f"Tree_Foliage_{idx}_{sub_i}"
            fol.data.materials.append(mat_tree_leaf)
            for f in fol.data.polygons:
                f.use_smooth = True
            env_col.objects.link(fol)
            bpy.context.scene.collection.objects.unlink(fol)
'''

# Insert before setup_lighting
idx = text.find("def setup_lighting():")
text = text[:idx] + details_func + "\n\n" + text[idx:]

# Call in main
old_main_calls = """    build_guardhouse(mats)
    build_retractable_gates(mats)"""

new_main_calls = """    build_guardhouse(mats)
    build_retractable_gates(mats)
    build_environmental_details(mats)"""

text = text.replace(old_main_calls, new_main_calls, 1)

with open(script_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Added environmental details to build_gate_gemini.py")
