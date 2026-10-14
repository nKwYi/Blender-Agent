import re
import os

path = r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

# -------------------------------------------------------------------------
# 1. Add new materials (Blue-Gray Tile, Blinds, Plaques) to create_materials
# -------------------------------------------------------------------------
mat_additions = """    # 5B. Blue-Gray Mosaic Tile (Parapet top trim band)
    mat_tile_blue = bpy.data.materials.new("MAT_Tile_BlueGray")
    nodes_tb = mat_tile_blue.node_tree.nodes
    links_tb = mat_tile_blue.node_tree.links
    bsdf_tb = next(n for n in nodes_tb if n.type == "BSDF_PRINCIPLED")
    bsdf_tb.inputs["Base Color"].default_value = (0.28, 0.35, 0.42, 1.0)
    bsdf_tb.inputs["Metallic"].default_value = 0.04
    bsdf_tb.inputs["Roughness"].default_value = 0.28
    tex_tile_path = os.path.join(TEXTURES_DIR, "ceramic_tile.jpg")
    if os.path.exists(tex_tile_path):
        try:
            img_tile = bpy.data.images.load(tex_tile_path)
            tex_node = nodes_tb.new("ShaderNodeTexImage")
            tex_node.image = img_tile
            tc = nodes_tb.new("ShaderNodeTexCoord")
            mapping = nodes_tb.new("ShaderNodeMapping")
            mapping.inputs["Scale"].default_value = (14.0, 14.0, 14.0)
            links_tb.new(tc.outputs["Generated"], mapping.inputs["Vector"])
            links_tb.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])
            bump = nodes_tb.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.08
            bump.inputs["Distance"].default_value = 0.05
            links_tb.new(tex_node.outputs["Color"], bump.inputs["Height"])
            links_tb.new(bump.outputs["Normal"], bsdf_tb.inputs["Normal"])
        except Exception:
            pass
    mats["tile_blue"] = mat_tile_blue

    # 5C. Roller Blinds (Curved window interior blinds)
    mat_blinds = bpy.data.materials.new("MAT_Roller_Blinds")
    bsdf_bl = next(n for n in mat_blinds.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_bl.inputs["Base Color"].default_value = (0.75, 0.77, 0.78, 1.0)
    bsdf_bl.inputs["Roughness"].default_value = 0.55
    mats["blinds"] = mat_blinds

    # 5D. Notice Plaques
    mat_blue_plaque = bpy.data.materials.new("MAT_Plaque_Blue")
    bsdf_bp = next(n for n in mat_blue_plaque.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_bp.inputs["Base Color"].default_value = (0.06, 0.36, 0.82, 1.0)
    bsdf_bp.inputs["Roughness"].default_value = 0.25
    mats["plaque_blue"] = mat_blue_plaque

    mat_white_plaque = bpy.data.materials.new("MAT_Plaque_White")
    bsdf_wp = next(n for n in mat_white_plaque.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf_wp.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1.0)
    bsdf_wp.inputs["Roughness"].default_value = 0.30
    mats["plaque_white"] = mat_white_plaque
"""

# Insert mat additions before "return mats" in create_materials
idx_return_mats = code.find("    return mats\n\n# -------------------------------------------------------------------------")
if idx_return_mats != -1:
    code = code[:idx_return_mats] + mat_additions + "\n" + code[idx_return_mats:]
    print("Added new materials to create_materials.")
else:
    print("Could not find return mats in create_materials!")

# -------------------------------------------------------------------------
# 2. Rewrite build_cantilever_wings:
#    - Clean rectangular end cuts (NO bevel on tips, NO cross + shape)
#    - 3 fins on the right (staggered: top longest, mid medium, bot shortest)
#    - 3 fins on the left (staggered: top shortest, mid medium, bot longest)
#    - Vertical columns on the left linking the 3 left fins
#    - Vertical panel seams
# -------------------------------------------------------------------------
new_wings_code = '''def build_cantilever_wings(mats):
    wing_col = bpy.data.collections.new("COL_Cantilever_Wings")
    bpy.context.scene.collection.children.link(wing_col)

    def create_sleek_box_fin(name, x_start, x_end, y_pos, z_pos, height=0.52, depth=0.65):
        """
        Creates a clean horizontal aluminum cantilever box beam with
        sharp, vertical rectangular 90-degree squared end cuts (matching reference photo).
        """
        length = abs(x_end - x_start)
        x_center = (x_start + x_end) * 0.5

        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=Vector((x_center, y_pos, z_pos))
        )
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = (length, depth, height)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(mats["silver"])

        # Subtle realistic edge bevel (only 12mm on boundary edges, keeping ends square)
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = 0.012
        mod.segments = 2
        mod.limit_method = "ANGLE"
        obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")

        wing_col.objects.link(obj)
        bpy.context.scene.collection.objects.unlink(obj)

        # Add vertical panel seams every 1.2m
        n_seams = int(length / 1.20)
        x_dir = 1.0 if x_end > x_start else -1.0
        for s_i in range(1, n_seams + 1):
            xs = x_start + x_dir * (s_i * 1.20)
            if abs(xs - x_end) < 0.25:
                continue
            for ys in [y_pos - depth*0.5 + 0.002, y_pos + depth*0.5 - 0.002]:
                bpy.ops.mesh.primitive_cube_add(
                    size=1.0,
                    location=Vector((xs, ys, z_pos))
                )
                sm = bpy.context.object
                sm.dimensions = (0.016, 0.02, height * 1.01)
                bpy.ops.object.transform_apply(scale=True)
                sm.data.materials.append(mats["dark_steel"])
                wing_col.objects.link(sm)
                bpy.context.scene.collection.objects.unlink(sm)

        return obj

    # -------------------------------------------------------------------------
    # RIGHT SIDE (Upper levels, above Right Low Arch)
    # Reference Photo: Exactly 3 horizontal fins!
    # Tapering from top (longest) to bottom (shortest):
    # Fin R1 (Top): longest, length = 3.80m, Z = 11.20m
    # Fin R2 (Mid): medium,  length = 2.90m, Z = 10.30m
    # Fin R3 (Bot): shortest, length = 2.00m, Z = 9.40m
    # -------------------------------------------------------------------------
    create_sleek_box_fin("Wing_Right_1_Top", x_start=0.51, x_end=4.31, y_pos=0.10, z_pos=11.20, height=0.52, depth=0.65)
    create_sleek_box_fin("Wing_Right_2_Mid", x_start=0.51, x_end=3.41, y_pos=0.10, z_pos=10.30, height=0.52, depth=0.65)
    create_sleek_box_fin("Wing_Right_3_Bot", x_start=0.51, x_end=2.51, y_pos=0.10, z_pos=9.40,  height=0.52, depth=0.65)

    # -------------------------------------------------------------------------
    # LEFT SIDE (Lower levels, below Left High Arch)
    # Reference Photo: Exactly 3 horizontal fins!
    # Tapering from top (shortest) to bottom (longest):
    # Fin L1 (Top): shortest, length = 2.20m, Z = 9.40m
    # Fin L2 (Mid): medium,  length = 3.20m, Z = 8.20m
    # Fin L3 (Bot): longest, length = 4.30m, Z = 7.10m
    # -------------------------------------------------------------------------
    create_sleek_box_fin("Wing_Left_1_Top", x_start=-0.51, x_end=-2.71, y_pos=-0.425, z_pos=9.40, height=0.52, depth=0.65)
    create_sleek_box_fin("Wing_Left_2_Mid", x_start=-0.51, x_end=-3.71, y_pos=-0.425, z_pos=8.20, height=0.52, depth=0.65)
    create_sleek_box_fin("Wing_Left_3_Bot", x_start=-0.51, x_end=-4.81, y_pos=-0.425, z_pos=7.10, height=0.52, depth=0.65)

    # -------------------------------------------------------------------------
    # Vertical Framed Columns on Left (matching reference photo)
    # Intersecting and tying the 3 left fins to the pylon structure
    # -------------------------------------------------------------------------
    # Column 2 (Middle Left)
    create_cube(
        "Pylon_Col_Left_Mid",
        loc=Vector((-1.20, -0.425, 5.60)),
        dims=(0.42, 0.58, 11.20),
        mat=mats["bronze"],
        bevel=0.03
    )
    # Column 3 (Outer Left)
    create_cube(
        "Pylon_Col_Left_Outer",
        loc=Vector((-2.05, -0.425, 5.20)),
        dims=(0.42, 0.58, 10.40),
        mat=mats["bronze"],
        bevel=0.03
    )'''

# Replace build_cantilever_wings in code
idx_w_start = code.find("def build_cantilever_wings(mats):")
idx_w_end = code.find("def build_guardhouse(mats):")
if idx_w_start != -1 and idx_w_end != -1:
    code = code[:idx_w_start] + new_wings_code + "\n\n# -------------------------------------------------------------------------\n# Build Guardhouse\n# -------------------------------------------------------------------------\n" + code[idx_w_end:]
    print("Replaced build_cantilever_wings successfully.")
else:
    print("Could not find build_cantilever_wings boundaries!")

# -------------------------------------------------------------------------
# 3. Rewrite build_guardhouse:
#    - Complete detailing matching crop_guardhouse_detail.png!
#    - Two-tone ceramic mosaic tile (warm ivory body + blue-gray parapet band)
#    - Rounded parapet coping (NO protruding square mushroom roof slab!)
#    - Recessed flat roof slab inside parapet
#    - Entrance door on the left with tiled cantilever canopy & downlight
#    - 180-degree panoramic ribbon window with roller blinds (partially lowered 45%)
#    - Security plaques (blue video warning, white info, green logo)
#    - Two rooftop floodlights pointing up at the pylon
#    - White surveillance camera pole with PTZ camera and junction box
#    - Manicured green hedge wrapping around the semi-cylindrical front
# -------------------------------------------------------------------------
new_gh_code = '''def build_guardhouse(mats):
    gh_col = bpy.data.collections.new("COL_Guardhouse")
    bpy.context.scene.collection.children.link(gh_col)

    # Position: on the central island, in front of the pylon
    # Semi-cylindrical front (facing -Y), rectangular back (extending toward +Y)
    GH_X = 0.0
    GH_WIDTH = 3.80
    R_FRONT = GH_WIDTH * 0.5 # 1.90m radius
    Y_ARC_CENTER = -3.75
    Y_BACK = -0.85
    H_WALL = 2.90     # Main ivory wall body
    H_PARAPET = 3.35  # Parapet top edge (with blue-gray tile coping)
    N_ARC = 36

    # ---------------------------------------------------------------------
    # 1. Main Guardhouse Wall Body (Ivory Mosaic Tile)
    # ---------------------------------------------------------------------
    bm = bmesh.new()
    v_b, v_t = [], []
    for i in range(N_ARC + 1):
        ang = math.pi - (math.pi * i / N_ARC)
        vx = GH_X + R_FRONT * math.cos(ang)
        vy = Y_ARC_CENTER - R_FRONT * math.sin(ang)
        v_b.append(bm.verts.new(Vector((vx, vy, 0.0))))
        v_t.append(bm.verts.new(Vector((vx, vy, H_WALL))))

    v_lb = bm.verts.new(Vector((-R_FRONT, Y_BACK, 0.0)))
    v_lt = bm.verts.new(Vector((-R_FRONT, Y_BACK, H_WALL)))
    v_rb = bm.verts.new(Vector((R_FRONT, Y_BACK, 0.0)))
    v_rt = bm.verts.new(Vector((R_FRONT, Y_BACK, H_WALL)))

    for i in range(N_ARC):
        bm.faces.new([v_b[i], v_b[i+1], v_t[i+1], v_t[i]])
    bm.faces.new([v_lb, v_b[0], v_t[0], v_lt])
    bm.faces.new([v_b[-1], v_rb, v_rt, v_t[-1]])
    bm.faces.new([v_rb, v_lb, v_lt, v_rt])

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me_body = bpy.data.meshes.new("GH_Body_Mesh")
    bm.to_mesh(me_body)
    bm.free()

    gh_body = bpy.data.objects.new("Guardhouse_Main_Body", me_body)
    gh_col.objects.link(gh_body)
    gh_body.data.materials.append(mats["tile"])
    for f in gh_body.data.polygons:
        f.use_smooth = True

    # ---------------------------------------------------------------------
    # 2. Upper Parapet Coping Band (Blue-Gray Mosaic Tile Trim)
    # Seamlessly continues the cylinder wall up to H_PARAPET
    # ---------------------------------------------------------------------
    bm_p = bmesh.new()
    vp_b, vp_t = [], []
    for i in range(N_ARC + 1):
        ang = math.pi - (math.pi * i / N_ARC)
        vx = GH_X + (R_FRONT + 0.01) * math.cos(ang)
        vy = Y_ARC_CENTER - (R_FRONT + 0.01) * math.sin(ang)
        vp_b.append(bm_p.verts.new(Vector((vx, vy, H_WALL))))
        vp_t.append(bm_p.verts.new(Vector((vx, vy, H_PARAPET))))

    vp_lb = bm_p.verts.new(Vector((-R_FRONT - 0.01, Y_BACK, H_WALL)))
    vp_lt = bm_p.verts.new(Vector((-R_FRONT - 0.01, Y_BACK, H_PARAPET)))
    vp_rb = bm_p.verts.new(Vector((R_FRONT + 0.01, Y_BACK, H_WALL)))
    vp_rt = bm_p.verts.new(Vector((R_FRONT + 0.01, Y_BACK, H_PARAPET)))

    for i in range(N_ARC):
        bm_p.faces.new([vp_b[i], vp_b[i+1], vp_t[i+1], vp_t[i]])
    bm_p.faces.new([vp_lb, vp_b[0], vp_t[0], vp_lt])
    bm_p.faces.new([vp_b[-1], vp_rb, vp_rt, vp_t[-1]])
    bm_p.faces.new([vp_rb, vp_lb, vp_lt, vp_rt])

    # Parapet rounded top coping surface
    for i in range(N_ARC):
        v_in1 = bm_p.verts.new(Vector((GH_X + (R_FRONT - 0.16)*math.cos(math.pi - math.pi*i/N_ARC), Y_ARC_CENTER - (R_FRONT - 0.16)*math.sin(math.pi - math.pi*i/N_ARC), H_PARAPET)))
        v_in2 = bm_p.verts.new(Vector((GH_X + (R_FRONT - 0.16)*math.cos(math.pi - math.pi*(i+1)/N_ARC), Y_ARC_CENTER - (R_FRONT - 0.16)*math.sin(math.pi - math.pi*(i+1)/N_ARC), H_PARAPET)))
        bm_p.faces.new([vp_t[i], vp_t[i+1], v_in2, v_in1])

    bmesh.ops.recalc_face_normals(bm_p, faces=bm_p.faces)
    me_p = bpy.data.meshes.new("GH_Parapet_Mesh")
    bm_p.to_mesh(me_p)
    bm_p.free()

    gh_parapet = bpy.data.objects.new("Guardhouse_Parapet_Trim", me_p)
    gh_col.objects.link(gh_parapet)
    gh_parapet.data.materials.append(mats["tile_blue"])
    for f in gh_parapet.data.polygons:
        f.use_smooth = True

    # Recessed flat roof slab inside parapet
    roof = create_cube(
        "Guardhouse_Recessed_Roof",
        loc=Vector((GH_X, (Y_ARC_CENTER + Y_BACK)*0.5, H_PARAPET - 0.15)),
        dims=(GH_WIDTH - 0.35, abs(Y_BACK - Y_ARC_CENTER) + R_FRONT - 0.35, 0.15),
        mat=mats["dark_steel"]
    )
    gh_col.objects.link(roof)
    bpy.context.scene.collection.objects.unlink(roof)

    # ---------------------------------------------------------------------
    # 3. 180-Degree Panoramic Curved Ribbon Window & Mullions
    # ---------------------------------------------------------------------
    W_BOT = 1.05
    W_TOP = 2.25
    R_WIN = R_FRONT + 0.02

    bm_w = bmesh.new()
    vw_b, vw_t = [], []
    for i in range(N_ARC + 1):
        ang = math.pi - (math.pi * i / N_ARC)
        vx = GH_X + R_WIN * math.cos(ang)
        vy = Y_ARC_CENTER - R_WIN * math.sin(ang)
        vw_b.append(bm_w.verts.new(Vector((vx, vy, W_BOT))))
        vw_t.append(bm_w.verts.new(Vector((vx, vy, W_TOP))))

    for i in range(N_ARC):
        bm_w.faces.new([vw_b[i], vw_b[i+1], vw_t[i+1], vw_t[i]])

    bmesh.ops.recalc_face_normals(bm_w, faces=bm_w.faces)
    me_w = bpy.data.meshes.new("GH_Window_Mesh")
    bm_w.to_mesh(me_w)
    bm_w.free()

    gh_win = bpy.data.objects.new("Guardhouse_Ribbon_Window", me_w)
    gh_col.objects.link(gh_win)
    gh_win.data.materials.append(mats["glass"])
    for f in gh_win.data.polygons:
        f.use_smooth = True

    # 4. Interior Roller Blinds (Partially drawn down 45% from top)
    bm_bl = bmesh.new()
    H_BLINDS_BOT = W_TOP - (W_TOP - W_BOT) * 0.48 # Drawn down 48%
    R_BL = R_WIN - 0.02
    vbl_b, vbl_t = [], []
    for i in range(N_ARC + 1):
        ang = math.pi - (math.pi * i / N_ARC)
        vx = GH_X + R_BL * math.cos(ang)
        vy = Y_ARC_CENTER - R_BL * math.sin(ang)
        vbl_b.append(bm_bl.verts.new(Vector((vx, vy, H_BLINDS_BOT))))
        vbl_t.append(bm_bl.verts.new(Vector((vx, vy, W_TOP))))

    for i in range(N_ARC):
        bm_bl.faces.new([vbl_b[i], vbl_b[i+1], vbl_t[i+1], vbl_t[i]])

    bmesh.ops.recalc_face_normals(bm_bl, faces=bm_bl.faces)
    me_bl = bpy.data.meshes.new("GH_Blinds_Mesh")
    bm_bl.to_mesh(me_bl)
    bm_bl.free()

    gh_blinds = bpy.data.objects.new("Guardhouse_Roller_Blinds", me_bl)
    gh_col.objects.link(gh_blinds)
    gh_blinds.data.materials.append(mats["blinds"])
    for f in gh_blinds.data.polygons:
        f.use_smooth = True

    # Window Perimeter Frames & Mullions (White Fluorocarbon Aluminum)
    # Upper & lower curved sills
    for z_sill in [W_BOT - 0.02, W_TOP + 0.02]:
        bm_s = bmesh.new()
        vs1, vs2 = [], []
        for i in range(N_ARC + 1):
            ang = math.pi - (math.pi * i / N_ARC)
            vx = GH_X + (R_WIN + 0.015) * math.cos(ang)
            vy = Y_ARC_CENTER - (R_WIN + 0.015) * math.sin(ang)
            vs1.append(bm_s.verts.new(Vector((vx, vy, z_sill - 0.03))))
            vs2.append(bm_s.verts.new(Vector((vx, vy, z_sill + 0.03))))
        for i in range(N_ARC):
            bm_s.faces.new([vs1[i], vs1[i+1], vs2[i+1], vs2[i]])
        bmesh.ops.recalc_face_normals(bm_s, faces=bm_s.faces)
        me_s = bpy.data.meshes.new("GH_Sill_Mesh")
        bm_s.to_mesh(me_s)
        bm_s.free()
        sill_obj = bpy.data.objects.new(f"Guardhouse_Sill_{z_sill:.2f}", me_s)
        gh_col.objects.link(sill_obj)
        sill_obj.data.materials.append(mats["mullion"])

    # Vertical mullions every 6 subdivisions
    for i in range(0, N_ARC + 1, 6):
        ang = math.pi - (math.pi * i / N_ARC)
        vx = GH_X + (R_WIN + 0.015) * math.cos(ang)
        vy = Y_ARC_CENTER - (R_WIN + 0.015) * math.sin(ang)
        m_v = create_cube(
            f"GH_Mullion_V_{i}",
            loc=Vector((vx, vy, (W_BOT + W_TOP)*0.5)),
            dims=(0.045, 0.045, W_TOP - W_BOT),
            mat=mats["mullion"]
        )
        gh_col.objects.link(m_v)
        bpy.context.scene.collection.objects.unlink(m_v)

    # ---------------------------------------------------------------------
    # 5. Left Side Entrance Door & Cantilevered Canopy (门斗挑檐雨棚)
    # ---------------------------------------------------------------------
    # Door frame on left wall (X = -R_FRONT)
    door_y = -2.20
    door_w = 0.95
    door_h = 2.15
    door = create_cube(
        "Guardhouse_Left_Door",
        loc=Vector((-R_FRONT - 0.01, door_y, door_h * 0.5)),
        dims=(0.04, door_w, door_h),
        mat=mats["dark_steel"],
        bevel=0.01
    )
    gh_col.objects.link(door); bpy.context.scene.collection.objects.unlink(door)

    # Cantilevered Door Canopy (Tiled box with downlight)
    canopy = create_cube(
        "Guardhouse_Door_Canopy",
        loc=Vector((-R_FRONT - 0.45, door_y, 2.40)),
        dims=(0.95, 1.25, 0.12),
        mat=mats["tile"],
        bevel=0.015
    )
    gh_col.objects.link(canopy); bpy.context.scene.collection.objects.unlink(canopy)

    # Canopy downlight emitter
    canopy_light = create_cylinder(
        "Canopy_Downlight",
        loc=Vector((-R_FRONT - 0.45, door_y, 2.33)),
        rot=(0, 0, 0),
        radius=0.08,
        depth=0.02,
        mat=mats["interior_glow"]
    )
    gh_col.objects.link(canopy_light); bpy.context.scene.collection.objects.unlink(canopy_light)

    # ---------------------------------------------------------------------
    # 6. Informational Wall Plaques (监控警告牌与企业标牌)
    # ---------------------------------------------------------------------
    # Blue video surveillance notice plaque
    plaque_blue = create_cube(
        "Plaque_Video_Surveillance",
        loc=Vector((-R_FRONT - 0.025, -3.10, 1.65)),
        dims=(0.02, 0.38, 0.26),
        mat=mats["plaque_blue"]
    )
    gh_col.objects.link(plaque_blue); bpy.context.scene.collection.objects.unlink(plaque_blue)

    # White informational plaque
    plaque_white = create_cube(
        "Plaque_Info_White",
        loc=Vector((-R_FRONT - 0.025, -3.10, 1.30)),
        dims=(0.02, 0.35, 0.18),
        mat=mats["plaque_white"]
    )
    gh_col.objects.link(plaque_white); bpy.context.scene.collection.objects.unlink(plaque_white)

    # ---------------------------------------------------------------------
    # 7. Rooftop Floodlights (Pointing up at tower characters)
    # ---------------------------------------------------------------------
    for x_fl in [-0.85, 0.85]:
        fl = create_cube(
            f"GH_Rooftop_Floodlight_{x_fl}",
            loc=Vector((x_fl, Y_ARC_CENTER + 0.85, H_PARAPET + 0.12)),
            dims=(0.28, 0.22, 0.18),
            mat=mats["dark_steel"],
            bevel=0.02
        )
        fl.rotation_euler = Euler((math.radians(-32.0), 0.0, 0.0), "XYZ")
        gh_col.objects.link(fl); bpy.context.scene.collection.objects.unlink(fl)

    # ---------------------------------------------------------------------
    # 8. Guardhouse Interior Warm Glow & Officer Silhouette
    # ---------------------------------------------------------------------
    create_cylinder(
        "Guardhouse_Interior_GlowLight",
        loc=Vector((GH_X, Y_ARC_CENTER + 0.6, 2.0)),
        rot=(0, 0, 0),
        radius=0.75,
        depth=0.10,
        mat=mats["interior_glow"]
    )
    # Guard desk
    desk = create_cube(
        "Guardhouse_Interior_Desk",
        loc=Vector((GH_X, Y_ARC_CENTER + 0.45, 0.75)),
        dims=(1.80, 0.70, 0.75),
        mat=mats["dark_steel"]
    )
    gh_col.objects.link(desk); bpy.context.scene.collection.objects.unlink(desk)

    # ---------------------------------------------------------------------
    # 9. Manicured Green Hedge Shrub (Closely hugging the curved base)
    # ---------------------------------------------------------------------
    bm_hd = bmesh.new()
    R_HEDGE = R_FRONT + 0.65
    H_HEDGE = 0.88
    W_HEDGE = 0.52

    v_hd_in_b, v_hd_in_t, v_hd_out_b, v_hd_out_t = [], [], [], []
    for i in range(N_ARC + 1):
        ang = math.pi - (math.pi * i / N_ARC)
        vxi = GH_X + (R_HEDGE - W_HEDGE*0.5) * math.cos(ang)
        vyi = Y_ARC_CENTER - (R_HEDGE - W_HEDGE*0.5) * math.sin(ang)
        vxo = GH_X + (R_HEDGE + W_HEDGE*0.5) * math.cos(ang)
        vyo = Y_ARC_CENTER - (R_HEDGE + W_HEDGE*0.5) * math.sin(ang)

        v_hd_in_b.append(bm_hd.verts.new(Vector((vxi, vyi, 0.0))))
        v_hd_in_t.append(bm_hd.verts.new(Vector((vxi, vyi, H_HEDGE))))
        v_hd_out_b.append(bm_hd.verts.new(Vector((vxo, vyo, 0.0))))
        v_hd_out_t.append(bm_hd.verts.new(Vector((vxo, vyo, H_HEDGE))))

    for i in range(N_ARC):
        bm_hd.faces.new([v_hd_out_b[i], v_hd_out_b[i+1], v_hd_out_t[i+1], v_hd_out_t[i]])
        bm_hd.faces.new([v_hd_in_b[i+1], v_hd_in_b[i], v_hd_in_t[i], v_hd_in_t[i+1]])
        bm_hd.faces.new([v_hd_in_t[i], v_hd_out_t[i], v_hd_out_t[i+1], v_hd_in_t[i+1]])

    bmesh.ops.recalc_face_normals(bm_hd, faces=bm_hd.faces)
    me_hd = bpy.data.meshes.new("Hedge_Mesh")
    bm_hd.to_mesh(me_hd)
    bm_hd.free()

    hedge_obj = bpy.data.objects.new("Guardhouse_Hedge_Shrub", me_hd)
    gh_col.objects.link(hedge_obj)
    hedge_obj.data.materials.append(mats["hedge"])
    for f in hedge_obj.data.polygons:
        f.use_smooth = True'''

# Replace build_guardhouse in code
idx_gh_start = code.find("def build_guardhouse(mats):")
idx_gh_end = code.find("def build_island_and_roads(mats):")
if idx_gh_start != -1 and idx_gh_end != -1:
    code = code[:idx_gh_start] + new_gh_code + "\n\n# -------------------------------------------------------------------------\n# Build Island & Roads\n# -------------------------------------------------------------------------\n" + code[idx_gh_end:]
    print("Replaced build_guardhouse successfully.")
else:
    print("Could not find build_guardhouse boundaries!")

# -------------------------------------------------------------------------
# 4. Rewrite build_environmental_details:
#    - REMOVE ALL TREES COMPLETELY (as explicitly instructed by user)
#    - Keep convex traffic mirrors
#    - Keep speed limit "10" sign & blue directional signboard
#    - Add white surveillance camera pole with PTZ camera and junction box
# -------------------------------------------------------------------------
new_env_code = '''def build_environmental_details(mats):
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

    # 2. Convex Traffic Mirrors (Two on the central safety island)
    for xm in [-0.85, 0.85]:
        p = create_cylinder(f"Mirror_Pole_{xm}", loc=Vector((xm, -6.2, 0.9)), rot=(0, 0, 0), radius=0.035, depth=1.8, mat=mats["dark_steel"])
        env_col.objects.link(p); bpy.context.scene.collection.objects.unlink(p)
        h = create_cylinder(f"Mirror_Housing_{xm}", loc=Vector((xm, -6.2, 1.75)), rot=(math.radians(90), 0, 0), radius=0.34, depth=0.08, mat=mat_orange)
        env_col.objects.link(h); bpy.context.scene.collection.objects.unlink(h)
        mf = create_cylinder(f"Mirror_Face_{xm}", loc=Vector((xm, -6.245, 1.75)), rot=(math.radians(90), 0, 0), radius=0.30, depth=0.02, mat=mat_mirror)
        env_col.objects.link(mf); bpy.context.scene.collection.objects.unlink(mf)

    # 3. Speed Limit Sign ("10") & Blue Directional Signboard
    pole_s = create_cylinder("Speed_Sign_Pole", loc=Vector((2.35, -6.2, 1.0)), rot=(0, 0, 0), radius=0.035, depth=2.0, mat=mats["dark_steel"])
    env_col.objects.link(pole_s); bpy.context.scene.collection.objects.unlink(pole_s)
    plate = create_cylinder("Speed_Sign_Plate", loc=Vector((2.35, -6.2, 1.95)), rot=(math.radians(90), 0, 0), radius=0.32, depth=0.03, mat=mats["white_mark"])
    env_col.objects.link(plate); bpy.context.scene.collection.objects.unlink(plate)
    ring = create_cylinder("Speed_Sign_RedRing", loc=Vector((2.35, -6.216, 1.95)), rot=(math.radians(90), 0, 0), radius=0.31, depth=0.01, mat=mat_orange)
    env_col.objects.link(ring); bpy.context.scene.collection.objects.unlink(ring)

    sign_box = create_cube("Direction_Signboard", loc=Vector((2.35, -6.2, 2.50)), dims=(0.85, 0.04, 0.55), mat=mat_blue_sign, bevel=0.015)
    env_col.objects.link(sign_box); bpy.context.scene.collection.objects.unlink(sign_box)

    # 4. White Surveillance Camera Pole with Junction Box & PTZ Camera
    cam_pole = create_cylinder("Surveillance_Pole", loc=Vector((1.90, -4.50, 2.80)), rot=(0, 0, 0), radius=0.06, depth=5.60, mat=mats["mullion"])
    env_col.objects.link(cam_pole); bpy.context.scene.collection.objects.unlink(cam_pole)
    cam_box = create_cube("Surveillance_Junction_Box", loc=Vector((1.90, -4.50, 3.20)), dims=(0.30, 0.22, 0.40), mat=mats["mullion"], bevel=0.02)
    env_col.objects.link(cam_box); bpy.context.scene.collection.objects.unlink(cam_box)
    cam_arm = create_cylinder("Surveillance_Camera_Arm", loc=Vector((1.90, -4.75, 4.20)), rot=(math.radians(45), 0, 0), radius=0.03, depth=0.60, mat=mats["mullion"])
    env_col.objects.link(cam_arm); bpy.context.scene.collection.objects.unlink(cam_arm)
    cam_body = create_cube("Surveillance_PTZ_Camera", loc=Vector((1.90, -4.95, 4.40)), dims=(0.18, 0.28, 0.16), mat=mats["dark_steel"], bevel=0.02)
    env_col.objects.link(cam_body); bpy.context.scene.collection.objects.unlink(cam_body)
    # NOTE: ALL TREES COMPLETELY REMOVED per user explicit instruction!'''

idx_env_start = code.find("def build_environmental_details(mats):")
idx_env_end = code.find("def setup_lighting():")
if idx_env_start != -1 and idx_env_end != -1:
    code = code[:idx_env_start] + new_env_code + "\n\n# -------------------------------------------------------------------------\n# Lighting\n# -------------------------------------------------------------------------\n" + code[idx_env_end:]
    print("Replaced build_environmental_details (trees removed) successfully.")
else:
    print("Could not find build_environmental_details boundaries!")

with open(path, "w", encoding="utf-8") as f:
    f.write(code)

print("Saved updated build_gate_gemini.py")
