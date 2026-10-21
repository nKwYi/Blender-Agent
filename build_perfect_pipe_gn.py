import bpy

def build_procedural_pipe_node_tree():
    nt_name = "GN_Procedural_Pipe"
    nt = bpy.data.node_groups.get(nt_name)
    if not nt:
        nt = bpy.data.node_groups.new(nt_name, "GeometryNodeTree")
    else:
        nt.nodes.clear()

    # Clear interfaces and rebuild inputs/outputs
    nt.interface.clear()
    
    # Inputs
    sock_geo = nt.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    sock_r_pipe = nt.interface.new_socket("管道外径", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_r_pipe.default_value = 0.05
    sock_r_pipe.min_value = 0.01
    sock_r_pipe.max_value = 0.5
    
    sock_r_fillet = nt.interface.new_socket("弯头倒角半径", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_r_fillet.default_value = 0.06
    sock_r_fillet.min_value = 0.01
    sock_r_fillet.max_value = 0.3
    
    sock_collar_on = nt.interface.new_socket("转角套箍开关", in_out='INPUT', socket_type='NodeSocketBool')
    sock_collar_on.default_value = True
    
    sock_collar_ratio = nt.interface.new_socket("套箍外扩比例", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_collar_ratio.default_value = 1.15
    sock_collar_ratio.min_value = 1.02
    sock_collar_ratio.max_value = 1.5
    
    sock_th_len = nt.interface.new_socket("螺纹段长度", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_th_len.default_value = 0.05
    sock_th_len.min_value = 0.01
    
    sock_th_pitch = nt.interface.new_socket("螺纹牙距", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_th_pitch.default_value = 0.005
    sock_th_pitch.min_value = 0.001
    
    sock_sock_len = nt.interface.new_socket("承口扩口长度", in_out='INPUT', socket_type='NodeSocketFloat')
    sock_sock_len.default_value = 0.045
    sock_sock_len.min_value = 0.01
    
    sock_flip = nt.interface.new_socket("端头翻转", in_out='INPUT', socket_type='NodeSocketBool')
    sock_flip.default_value = False
    
    sock_res = nt.interface.new_socket("截面细分数", in_out='INPUT', socket_type='NodeSocketInt')
    sock_res.default_value = 24
    sock_res.min_value = 8
    sock_res.max_value = 64
    
    sock_mat = nt.interface.new_socket("管道材质", in_out='INPUT', socket_type='NodeSocketMaterial')
    pvc_mat = bpy.data.materials.get("PVC_White_Plastic")
    if pvc_mat:
        sock_mat.default_value = pvc_mat

    # Outputs
    nt.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # Nodes
    node_in = nt.nodes.new("NodeGroupInput")
    node_in.location = (-1600, 0)
    node_out = nt.nodes.new("NodeGroupOutput")
    node_out.location = (2000, 0)

    # Pipe radius = 管道外径 / 2
    r_pipe_math = nt.nodes.new("ShaderNodeMath")
    r_pipe_math.operation = 'DIVIDE'
    r_pipe_math.inputs[1].default_value = 2.0
    nt.links.new(node_in.outputs['管道外径'], r_pipe_math.inputs[0])
    r_pipe_math.location = (-1400, -200)

    # Collar outer radius = r_pipe * 套箍外扩比例
    r_collar_math = nt.nodes.new("ShaderNodeMath")
    r_collar_math.operation = 'MULTIPLY'
    nt.links.new(r_pipe_math.outputs['Value'], r_collar_math.inputs[0])
    nt.links.new(node_in.outputs['套箍外扩比例'], r_collar_math.inputs[1])
    r_collar_math.location = (-1200, -200)

    # Lip outer radius = r_collar * 1.06
    r_lip_math = nt.nodes.new("ShaderNodeMath")
    r_lip_math.operation = 'MULTIPLY'
    r_lip_math.inputs[1].default_value = 1.06
    nt.links.new(r_collar_math.outputs['Value'], r_lip_math.inputs[0])
    r_lip_math.location = (-1000, -200)

    # ----------------------------------------------------
    # A. Capture Corner Topology on Original Mesh
    # ----------------------------------------------------
    v_neighbors = nt.nodes.new("GeometryNodeInputMeshVertexNeighbors")
    v_neighbors.location = (-1400, 200)

    cmp_corner = nt.nodes.new("FunctionNodeCompare")
    cmp_corner.data_type = 'INT'
    cmp_corner.operation = 'EQUAL'
    cmp_corner.inputs['B'].default_value = 2
    nt.links.new(v_neighbors.outputs['Vertex Count'], cmp_corner.inputs['A'])
    cmp_corner.location = (-1200, 200)

    store_corner = nt.nodes.new("GeometryNodeStoreNamedAttribute")
    store_corner.data_type = 'INT'
    store_corner.domain = 'POINT'
    store_corner.inputs['Name'].default_value = "is_corner"
    nt.links.new(node_in.outputs['Geometry'], store_corner.inputs['Geometry'])
    nt.links.new(cmp_corner.outputs['Result'], store_corner.inputs['Value'])
    store_corner.location = (-1000, 200)

    # ----------------------------------------------------
    # B. Continuous Curved Pipe Body
    # ----------------------------------------------------
    m2c = nt.nodes.new("GeometryNodeMeshToCurve")
    nt.links.new(store_corner.outputs['Geometry'], m2c.inputs['Mesh'])
    m2c.location = (-800, 400)

    fillet = nt.nodes.new("GeometryNodeFilletCurve")
    fillet.inputs['Mode'].default_value = 'Poly'
    fillet.inputs['Count'].default_value = 8
    nt.links.new(m2c.outputs['Curve'], fillet.inputs['Curve'])
    nt.links.new(node_in.outputs['弯头倒角半径'], fillet.inputs['Radius'])
    fillet.location = (-600, 400)

    circle_prof = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    nt.links.new(node_in.outputs['截面细分数'], circle_prof.inputs['Resolution'])
    nt.links.new(r_pipe_math.outputs['Value'], circle_prof.inputs['Radius'])
    circle_prof.location = (-600, 200)

    pipe_mesh = nt.nodes.new("GeometryNodeCurveToMesh")
    nt.links.new(fillet.outputs['Curve'], pipe_mesh.inputs['Curve'])
    nt.links.new(circle_prof.outputs['Curve'], pipe_mesh.inputs['Profile Curve'])
    pipe_mesh.location = (-400, 400)

    # ----------------------------------------------------
    # C. Build Solid Collar Instance Geometry (local Z aligned)
    #    Mouth/Lip at Z = 0 (faces the elbow)
    #    Barrel: Z in [-0.018, -0.003], Radius = r_collar
    #    Lip bead: Z in [-0.003, 0.001], Radius = r_lip
    #    Taper shoulder: Z in [-0.024, -0.018], Radius r_collar -> r_pipe
    # ----------------------------------------------------
    # 1. Bevel shoulder cone: from r_pipe (at bottom Z=-0.024) to r_collar (at top Z=-0.018)
    cone_shoulder = nt.nodes.new("GeometryNodeMeshCone")
    cone_shoulder.fill_type = 'NONE'
    cone_shoulder.inputs['Depth'].default_value = 0.006
    nt.links.new(node_in.outputs['截面细分数'], cone_shoulder.inputs['Vertices'])
    nt.links.new(r_collar_math.outputs['Value'], cone_shoulder.inputs['Radius Top'])
    nt.links.new(r_pipe_math.outputs['Value'], cone_shoulder.inputs['Radius Bottom'])
    cone_shoulder.location = (-800, -500)

    tf_shoulder = nt.nodes.new("GeometryNodeTransform")
    comb_xyz_sh = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_sh.inputs['Z'].default_value = -0.021
    nt.links.new(comb_xyz_sh.outputs['Vector'], tf_shoulder.inputs['Translation'])
    nt.links.new(cone_shoulder.outputs['Mesh'], tf_shoulder.inputs['Geometry'])
    tf_shoulder.location = (-600, -500)

    # 2. Cylindrical barrel: length 0.015, radius r_collar, center at Z = -0.0105
    cyl_barrel = nt.nodes.new("GeometryNodeMeshCylinder")
    cyl_barrel.fill_type = 'NONE'
    cyl_barrel.inputs['Depth'].default_value = 0.015
    nt.links.new(node_in.outputs['截面细分数'], cyl_barrel.inputs['Vertices'])
    nt.links.new(r_collar_math.outputs['Value'], cyl_barrel.inputs['Radius'])
    cyl_barrel.location = (-800, -700)

    tf_barrel = nt.nodes.new("GeometryNodeTransform")
    comb_xyz_ba = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_ba.inputs['Z'].default_value = -0.0105
    nt.links.new(comb_xyz_ba.outputs['Vector'], tf_barrel.inputs['Translation'])
    nt.links.new(cyl_barrel.outputs['Mesh'], tf_barrel.inputs['Geometry'])
    tf_barrel.location = (-600, -700)

    # 3. Rolled rim bead: torus ring at Z = -0.002
    circ_rim_spine = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    nt.links.new(node_in.outputs['截面细分数'], circ_rim_spine.inputs['Resolution'])
    nt.links.new(r_collar_math.outputs['Value'], circ_rim_spine.inputs['Radius'])
    circ_rim_spine.location = (-800, -900)

    circ_rim_prof = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    circ_rim_prof.inputs['Resolution'].default_value = 8
    circ_rim_prof.inputs['Radius'].default_value = 0.002
    circ_rim_prof.location = (-800, -1050)

    c2m_rim = nt.nodes.new("GeometryNodeCurveToMesh")
    nt.links.new(circ_rim_spine.outputs['Curve'], c2m_rim.inputs['Curve'])
    nt.links.new(circ_rim_prof.outputs['Curve'], c2m_rim.inputs['Profile Curve'])
    c2m_rim.location = (-600, -950)

    tf_rim = nt.nodes.new("GeometryNodeTransform")
    comb_xyz_rim = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_rim.inputs['Z'].default_value = -0.002
    nt.links.new(comb_xyz_rim.outputs['Vector'], tf_rim.inputs['Translation'])
    nt.links.new(c2m_rim.outputs['Mesh'], tf_rim.inputs['Geometry'])
    tf_rim.location = (-400, -950)

    # Join collar parts
    join_collar_geo = nt.nodes.new("GeometryNodeJoinGeometry")
    nt.links.new(tf_shoulder.outputs['Geometry'], join_collar_geo.inputs['Geometry'])
    nt.links.new(tf_barrel.outputs['Geometry'], join_collar_geo.inputs['Geometry'])
    nt.links.new(tf_rim.outputs['Geometry'], join_collar_geo.inputs['Geometry'])
    join_collar_geo.location = (-200, -700)

    # ----------------------------------------------------
    # D. Instance Collars on Split Edges
    # ----------------------------------------------------
    split_edges = nt.nodes.new("GeometryNodeSplitEdges")
    nt.links.new(store_corner.outputs['Geometry'], split_edges.inputs['Mesh'])
    split_edges.location = (-800, -100)

    edge_curves = nt.nodes.new("GeometryNodeMeshToCurve")
    nt.links.new(split_edges.outputs['Mesh'], edge_curves.inputs['Mesh'])
    edge_curves.location = (-600, -100)

    # Measure unmodified original edge length BEFORE Set Position
    spline_len_raw = nt.nodes.new("GeometryNodeSplineLength")
    spline_len_raw.location = (-600, -250)

    store_edge_len = nt.nodes.new("GeometryNodeStoreNamedAttribute")
    store_edge_len.data_type = 'FLOAT'
    store_edge_len.domain = 'POINT'
    store_edge_len.inputs['Name'].default_value = "edge_len"
    nt.links.new(edge_curves.outputs['Curve'], store_edge_len.inputs['Geometry'])
    nt.links.new(spline_len_raw.outputs['Length'], store_edge_len.inputs['Value'])
    store_edge_len.location = (-450, -100)

    # Store curve tangent on the curve points
    tan_node = nt.nodes.new("GeometryNodeInputTangent")
    store_tan = nt.nodes.new("GeometryNodeStoreNamedAttribute")
    store_tan.data_type = 'FLOAT_VECTOR'
    store_tan.domain = 'POINT'
    store_tan.inputs['Name'].default_value = "edge_tan"
    nt.links.new(store_edge_len.outputs['Geometry'], store_tan.inputs['Geometry'])
    nt.links.new(tan_node.outputs['Tangent'], store_tan.inputs['Value'])
    store_tan.location = (-300, -100)

    # Read named attributes on curve points
    read_corner = nt.nodes.new("GeometryNodeInputNamedAttribute")
    read_corner.data_type = 'INT'
    read_corner.inputs['Name'].default_value = "is_corner"
    read_corner.location = (-300, 100)

    read_tan = nt.nodes.new("GeometryNodeInputNamedAttribute")
    read_tan.data_type = 'FLOAT_VECTOR'
    read_tan.inputs['Name'].default_value = "edge_tan"
    read_tan.location = (-300, -250)

    read_edge_len = nt.nodes.new("GeometryNodeInputNamedAttribute")
    read_edge_len.data_type = 'FLOAT'
    read_edge_len.inputs['Name'].default_value = "edge_len"
    read_edge_len.location = (-300, -380)

    # Selection: Endpoint Selection (start point or end point)
    ep_start = nt.nodes.new("GeometryNodeCurveEndpointSelection")
    ep_start.inputs['Start Size'].default_value = 1
    ep_start.inputs['End Size'].default_value = 0
    ep_start.location = (-300, 250)

    # Spline length check: edge must be longer than R_fillet * 1.3
    min_len_calc = nt.nodes.new("ShaderNodeMath")
    min_len_calc.operation = 'MULTIPLY'
    min_len_calc.inputs[1].default_value = 1.3
    nt.links.new(node_in.outputs['弯头倒角半径'], min_len_calc.inputs[0])
    min_len_calc.location = (-300, -500)

    cmp_len = nt.nodes.new("FunctionNodeCompare")
    cmp_len.data_type = 'FLOAT'
    cmp_len.operation = 'GREATER_THAN'
    nt.links.new(read_edge_len.outputs['Attribute'], cmp_len.inputs['A'])
    nt.links.new(min_len_calc.outputs['Value'], cmp_len.inputs['B'])
    cmp_len.location = (-100, -400)

    # Corner check: is_corner == 1
    cmp_is_c = nt.nodes.new("FunctionNodeCompare")
    cmp_is_c.data_type = 'INT'
    cmp_is_c.operation = 'EQUAL'
    cmp_is_c.inputs['B'].default_value = 1
    nt.links.new(read_corner.outputs['Attribute'], cmp_is_c.inputs['A'])
    cmp_is_c.location = (-100, 100)

    # Combined Selection: (is_corner == 1) AND (转角套箍开关) AND (len > min_len)
    bool_and1 = nt.nodes.new("FunctionNodeBooleanMath")
    bool_and1.operation = 'AND'
    nt.links.new(cmp_is_c.outputs['Result'], bool_and1.inputs[0])
    nt.links.new(node_in.outputs['转角套箍开关'], bool_and1.inputs[1])
    bool_and1.location = (100, 100)

    bool_sel = nt.nodes.new("FunctionNodeBooleanMath")
    bool_sel.operation = 'AND'
    nt.links.new(bool_and1.outputs['Boolean'], bool_sel.inputs[0])
    nt.links.new(cmp_len.outputs['Result'], bool_sel.inputs[1])
    bool_sel.location = (250, 100)

    # Direction switch:
    # If is_start: S = +1.0
    # If not is_start: S = -1.0
    sw_sign = nt.nodes.new("GeometryNodeSwitch")
    sw_sign.input_type = 'FLOAT'
    nt.links.new(ep_start.outputs['Selection'], sw_sign.inputs['Switch'])
    sw_sign.inputs['False'].default_value = -1.0
    sw_sign.inputs['True'].default_value = 1.0
    sw_sign.location = (-100, 250)

    # Offset distance = S * (R_fillet - 0.002)
    sub_r = nt.nodes.new("ShaderNodeMath")
    sub_r.operation = 'SUBTRACT'
    sub_r.inputs[1].default_value = 0.002
    nt.links.new(node_in.outputs['弯头倒角半径'], sub_r.inputs[0])
    sub_r.location = (-100, 0)

    mul_dist = nt.nodes.new("ShaderNodeMath")
    mul_dist.operation = 'MULTIPLY'
    nt.links.new(sw_sign.outputs['Output'], mul_dist.inputs[0])
    nt.links.new(sub_r.outputs['Value'], mul_dist.inputs[1])
    mul_dist.location = (100, 0)

    # Offset vector = Tangent * mul_dist
    vec_offset = nt.nodes.new("ShaderNodeVectorMath")
    vec_offset.operation = 'SCALE'
    nt.links.new(read_tan.outputs['Attribute'], vec_offset.inputs['Vector'])
    nt.links.new(mul_dist.outputs['Value'], vec_offset.inputs['Scale'])
    vec_offset.location = (300, 0)

    # Set Position to offset points from corner vertices to collar junctions
    set_pos = nt.nodes.new("GeometryNodeSetPosition")
    nt.links.new(store_tan.outputs['Geometry'], set_pos.inputs['Geometry'])
    nt.links.new(vec_offset.outputs['Vector'], set_pos.inputs['Offset'])
    set_pos.location = (500, 0)

    # Rotation vector: Vector = Tangent * (-S)
    neg_sign = nt.nodes.new("ShaderNodeMath")
    neg_sign.operation = 'MULTIPLY'
    neg_sign.inputs[1].default_value = -1.0
    nt.links.new(sw_sign.outputs['Output'], neg_sign.inputs[0])
    neg_sign.location = (100, -200)

    rot_vec = nt.nodes.new("ShaderNodeVectorMath")
    rot_vec.operation = 'SCALE'
    nt.links.new(read_tan.outputs['Attribute'], rot_vec.inputs['Vector'])
    nt.links.new(neg_sign.outputs['Value'], rot_vec.inputs['Scale'])
    rot_vec.location = (300, -200)

    align_rot = nt.nodes.new("FunctionNodeAlignEulerToVector")
    align_rot.axis = 'Z'
    align_rot.pivot_axis = 'AUTO'
    nt.links.new(rot_vec.outputs['Vector'], align_rot.inputs['Vector'])
    align_rot.location = (500, -200)

    # Instance collars on corner points!
    inst_collars = nt.nodes.new("GeometryNodeInstanceOnPoints")
    nt.links.new(set_pos.outputs['Geometry'], inst_collars.inputs['Points'])
    nt.links.new(bool_sel.outputs['Boolean'], inst_collars.inputs['Selection'])
    nt.links.new(join_collar_geo.outputs['Geometry'], inst_collars.inputs['Instance'])
    nt.links.new(align_rot.outputs['Rotation'], inst_collars.inputs['Rotation'])
    inst_collars.location = (750, 0)

    # ----------------------------------------------------
    # E. Build Solid Male Thread & Stop Ring (Start Endpoint)
    # ----------------------------------------------------
    # Core thread cylinder: length = 螺纹段长度, radius = r_pipe * 0.95
    th_r_math = nt.nodes.new("ShaderNodeMath")
    th_r_math.operation = 'MULTIPLY'
    th_r_math.inputs[1].default_value = 0.95
    nt.links.new(r_pipe_math.outputs['Value'], th_r_math.inputs[0])
    th_r_math.location = (-1000, 800)

    cyl_th_core = nt.nodes.new("GeometryNodeMeshCylinder")
    cyl_th_core.fill_type = 'NONE'
    nt.links.new(node_in.outputs['截面细分数'], cyl_th_core.inputs['Vertices'])
    nt.links.new(th_r_math.outputs['Value'], cyl_th_core.inputs['Radius'])
    nt.links.new(node_in.outputs['螺纹段长度'], cyl_th_core.inputs['Depth'])
    cyl_th_core.location = (-800, 800)

    th_half_len = nt.nodes.new("ShaderNodeMath")
    th_half_len.operation = 'MULTIPLY'
    th_half_len.inputs[1].default_value = -0.5
    nt.links.new(node_in.outputs['螺纹段长度'], th_half_len.inputs[0])
    th_half_len.location = (-800, 650)

    comb_xyz_th = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(th_half_len.outputs['Value'], comb_xyz_th.inputs['Z'])
    comb_xyz_th.location = (-600, 650)

    tf_th_core = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(cyl_th_core.outputs['Mesh'], tf_th_core.inputs['Geometry'])
    nt.links.new(comb_xyz_th.outputs['Vector'], tf_th_core.inputs['Translation'])
    tf_th_core.location = (-400, 800)

    # Thread ridges (torus rings along line)
    th_line = nt.nodes.new("GeometryNodeCurvePrimitiveLine")
    comb_line_end = nt.nodes.new("ShaderNodeCombineXYZ")
    neg_th_len = nt.nodes.new("ShaderNodeMath")
    neg_th_len.operation = 'MULTIPLY'
    neg_th_len.inputs[1].default_value = -1.0
    nt.links.new(node_in.outputs['螺纹段长度'], neg_th_len.inputs[0])
    nt.links.new(neg_th_len.outputs['Value'], comb_line_end.inputs['Z'])
    nt.links.new(comb_line_end.outputs['Vector'], th_line.inputs['End'])
    th_line.location = (-800, 1100)

    th_resample = nt.nodes.new("GeometryNodeResampleCurve")
    th_resample.inputs['Mode'].default_value = 'Length'
    nt.links.new(th_line.outputs['Curve'], th_resample.inputs['Curve'])
    nt.links.new(node_in.outputs['螺纹牙距'], th_resample.inputs['Length'])
    th_resample.location = (-600, 1100)

    th_c2p = nt.nodes.new("GeometryNodeCurveToPoints")
    nt.links.new(th_resample.outputs['Curve'], th_c2p.inputs['Curve'])
    th_c2p.location = (-400, 1100)

    circ_th_ring_spine = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    nt.links.new(node_in.outputs['截面细分数'], circ_th_ring_spine.inputs['Resolution'])
    nt.links.new(r_pipe_math.outputs['Value'], circ_th_ring_spine.inputs['Radius'])
    circ_th_ring_spine.location = (-600, 1300)

    circ_th_ring_prof = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    circ_th_ring_prof.inputs['Resolution'].default_value = 6
    circ_th_ring_prof.inputs['Radius'].default_value = 0.0012
    circ_th_ring_prof.location = (-600, 1450)

    c2m_th_ridge = nt.nodes.new("GeometryNodeCurveToMesh")
    nt.links.new(circ_th_ring_spine.outputs['Curve'], c2m_th_ridge.inputs['Curve'])
    nt.links.new(circ_th_ring_prof.outputs['Curve'], c2m_th_ridge.inputs['Profile Curve'])
    c2m_th_ridge.location = (-400, 1300)

    inst_th_ridges = nt.nodes.new("GeometryNodeInstanceOnPoints")
    nt.links.new(th_c2p.outputs['Points'], inst_th_ridges.inputs['Points'])
    nt.links.new(c2m_th_ridge.outputs['Mesh'], inst_th_ridges.inputs['Instance'])
    inst_th_ridges.location = (-200, 1200)

    # Stop ring (flange cylinder at Z = 0)
    cyl_stop = nt.nodes.new("GeometryNodeMeshCylinder")
    cyl_stop.fill_type = 'NONE'
    cyl_stop.inputs['Depth'].default_value = 0.005
    nt.links.new(node_in.outputs['截面细分数'], cyl_stop.inputs['Vertices'])
    nt.links.new(r_collar_math.outputs['Value'], cyl_stop.inputs['Radius'])
    cyl_stop.location = (-600, 950)

    comb_xyz_stop = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_stop.inputs['Z'].default_value = 0.0025
    tf_stop = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(cyl_stop.outputs['Mesh'], tf_stop.inputs['Geometry'])
    nt.links.new(comb_xyz_stop.outputs['Vector'], tf_stop.inputs['Translation'])
    tf_stop.location = (-400, 950)

    # Stop ring beveled shoulder cone (from r_collar at Z = 0.005 down to r_pipe at Z = 0.011)
    cone_stop_sh = nt.nodes.new("GeometryNodeMeshCone")
    cone_stop_sh.fill_type = 'NONE'
    cone_stop_sh.inputs['Depth'].default_value = 0.006
    nt.links.new(node_in.outputs['截面细分数'], cone_stop_sh.inputs['Vertices'])
    nt.links.new(r_pipe_math.outputs['Value'], cone_stop_sh.inputs['Radius Top'])
    nt.links.new(r_collar_math.outputs['Value'], cone_stop_sh.inputs['Radius Bottom'])
    cone_stop_sh.location = (-600, 1600)

    comb_xyz_stop_sh = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_stop_sh.inputs['Z'].default_value = 0.008
    tf_stop_sh = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(cone_stop_sh.outputs['Mesh'], tf_stop_sh.inputs['Geometry'])
    nt.links.new(comb_xyz_stop_sh.outputs['Vector'], tf_stop_sh.inputs['Translation'])
    tf_stop_sh.location = (-400, 1600)

    join_th = nt.nodes.new("GeometryNodeJoinGeometry")
    nt.links.new(tf_th_core.outputs['Geometry'], join_th.inputs['Geometry'])
    nt.links.new(inst_th_ridges.outputs['Instances'], join_th.inputs['Geometry'])
    nt.links.new(tf_stop.outputs['Geometry'], join_th.inputs['Geometry'])
    nt.links.new(tf_stop_sh.outputs['Geometry'], join_th.inputs['Geometry'])
    join_th.location = (0, 1000)

    # ----------------------------------------------------
    # F. Build Solid Female Socket Cup & Rim (End Endpoint)
    # ----------------------------------------------------
    # 1. Bevel transition cone from r_pipe up to r_collar (depth 0.008, overlapping slightly by 2mm)
    cone_sock_sh = nt.nodes.new("GeometryNodeMeshCone")
    cone_sock_sh.fill_type = 'NONE'
    cone_sock_sh.inputs['Depth'].default_value = 0.008
    nt.links.new(node_in.outputs['截面细分数'], cone_sock_sh.inputs['Vertices'])
    nt.links.new(r_collar_math.outputs['Value'], cone_sock_sh.inputs['Radius Top'])
    nt.links.new(r_pipe_math.outputs['Value'], cone_sock_sh.inputs['Radius Bottom'])
    cone_sock_sh.location = (-600, 1800)

    comb_xyz_sk_sh = nt.nodes.new("ShaderNodeCombineXYZ")
    comb_xyz_sk_sh.inputs['Z'].default_value = 0.002 # slightly overlapping to seal seam
    tf_sock_sh = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(cone_sock_sh.outputs['Mesh'], tf_sock_sh.inputs['Geometry'])
    nt.links.new(comb_xyz_sk_sh.outputs['Vector'], tf_sock_sh.inputs['Translation'])
    tf_sock_sh.location = (-400, 1800)

    # 2. Main socket cylinder: from Z = 0.006 to Z = 0.006 + sock_len
    cyl_sock = nt.nodes.new("GeometryNodeMeshCylinder")
    cyl_sock.fill_type = 'NONE'
    nt.links.new(node_in.outputs['截面细分数'], cyl_sock.inputs['Vertices'])
    nt.links.new(r_collar_math.outputs['Value'], cyl_sock.inputs['Radius'])
    nt.links.new(node_in.outputs['承口扩口长度'], cyl_sock.inputs['Depth'])
    cyl_sock.location = (-600, 2000)

    half_sk_len = nt.nodes.new("ShaderNodeMath")
    half_sk_len.operation = 'MULTIPLY'
    half_sk_len.inputs[1].default_value = 0.5
    nt.links.new(node_in.outputs['承口扩口长度'], half_sk_len.inputs[0])
    half_sk_len.location = (-600, 2150)

    sk_z_cen = nt.nodes.new("ShaderNodeMath")
    sk_z_cen.operation = 'ADD'
    sk_z_cen.inputs[1].default_value = 0.006
    nt.links.new(half_sk_len.outputs['Value'], sk_z_cen.inputs[0])
    sk_z_cen.location = (-400, 2150)

    comb_xyz_sk = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sk_z_cen.outputs['Value'], comb_xyz_sk.inputs['Z'])
    comb_xyz_sk.location = (-200, 2150)

    tf_sock = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(cyl_sock.outputs['Mesh'], tf_sock.inputs['Geometry'])
    nt.links.new(comb_xyz_sk.outputs['Vector'], tf_sock.inputs['Translation'])
    tf_sock.location = (0, 2000)

    # 3. Rolled lip ring at the very end (Z = 0.006 + sock_len)
    circ_sk_lip_sp = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    nt.links.new(node_in.outputs['截面细分数'], circ_sk_lip_sp.inputs['Resolution'])
    nt.links.new(r_collar_math.outputs['Value'], circ_sk_lip_sp.inputs['Radius'])
    circ_sk_lip_sp.location = (-600, 2350)

    circ_sk_lip_pr = nt.nodes.new("GeometryNodeCurvePrimitiveCircle")
    circ_sk_lip_pr.inputs['Resolution'].default_value = 8
    circ_sk_lip_pr.inputs['Radius'].default_value = 0.002
    circ_sk_lip_pr.location = (-600, 2500)

    c2m_sk_lip = nt.nodes.new("GeometryNodeCurveToMesh")
    nt.links.new(circ_sk_lip_sp.outputs['Curve'], c2m_sk_lip.inputs['Curve'])
    nt.links.new(circ_sk_lip_pr.outputs['Curve'], c2m_sk_lip.inputs['Profile Curve'])
    c2m_sk_lip.location = (-400, 2400)

    sk_lip_z = nt.nodes.new("ShaderNodeMath")
    sk_lip_z.operation = 'ADD'
    sk_lip_z.inputs[1].default_value = 0.006
    nt.links.new(node_in.outputs['承口扩口长度'], sk_lip_z.inputs[0])
    sk_lip_z.location = (-200, 2400)

    comb_xyz_sk_lip = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sk_lip_z.outputs['Value'], comb_xyz_sk_lip.inputs['Z'])
    comb_xyz_sk_lip.location = (0, 2400)

    tf_sk_lip = nt.nodes.new("GeometryNodeTransform")
    nt.links.new(c2m_sk_lip.outputs['Mesh'], tf_sk_lip.inputs['Geometry'])
    nt.links.new(comb_xyz_sk_lip.outputs['Vector'], tf_sk_lip.inputs['Translation'])
    tf_sk_lip.location = (200, 2400)

    join_sock = nt.nodes.new("GeometryNodeJoinGeometry")
    nt.links.new(tf_sock_sh.outputs['Geometry'], join_sock.inputs['Geometry'])
    nt.links.new(tf_sock.outputs['Geometry'], join_sock.inputs['Geometry'])
    nt.links.new(tf_sk_lip.outputs['Geometry'], join_sock.inputs['Geometry'])
    join_sock.location = (400, 2000)

    # ----------------------------------------------------
    # G. Instance Male & Female Fittings onto Pipe Endpoints
    # ----------------------------------------------------
    ep_pipe_start = nt.nodes.new("GeometryNodeCurveEndpointSelection")
    ep_pipe_start.inputs['Start Size'].default_value = 1
    ep_pipe_start.inputs['End Size'].default_value = 0
    ep_pipe_start.location = (200, 800)

    ep_pipe_end = nt.nodes.new("GeometryNodeCurveEndpointSelection")
    ep_pipe_end.inputs['Start Size'].default_value = 0
    ep_pipe_end.inputs['End Size'].default_value = 1
    ep_pipe_end.location = (200, 1600)

    tan_fillet = nt.nodes.new("GeometryNodeInputTangent")
    align_fillet_tan = nt.nodes.new("FunctionNodeAlignEulerToVector")
    align_fillet_tan.axis = 'Z'
    align_fillet_tan.pivot_axis = 'AUTO'
    nt.links.new(tan_fillet.outputs['Tangent'], align_fillet_tan.inputs['Vector'])
    align_fillet_tan.location = (400, 1200)

    # Switch for flip ends
    sw_fit_start = nt.nodes.new("GeometryNodeSwitch")
    sw_fit_start.input_type = 'GEOMETRY'
    nt.links.new(node_in.outputs['端头翻转'], sw_fit_start.inputs['Switch'])
    nt.links.new(join_th.outputs['Geometry'], sw_fit_start.inputs['False'])
    nt.links.new(join_sock.outputs['Geometry'], sw_fit_start.inputs['True'])
    sw_fit_start.location = (400, 1000)

    sw_fit_end = nt.nodes.new("GeometryNodeSwitch")
    sw_fit_end.input_type = 'GEOMETRY'
    nt.links.new(node_in.outputs['端头翻转'], sw_fit_end.inputs['Switch'])
    nt.links.new(join_sock.outputs['Geometry'], sw_fit_end.inputs['False'])
    nt.links.new(join_th.outputs['Geometry'], sw_fit_end.inputs['True'])
    sw_fit_end.location = (600, 1600)

    # Instance at start
    inst_start = nt.nodes.new("GeometryNodeInstanceOnPoints")
    nt.links.new(fillet.outputs['Curve'], inst_start.inputs['Points'])
    nt.links.new(ep_pipe_start.outputs['Selection'], inst_start.inputs['Selection'])
    nt.links.new(sw_fit_start.outputs['Output'], inst_start.inputs['Instance'])
    nt.links.new(align_fillet_tan.outputs['Rotation'], inst_start.inputs['Rotation'])
    inst_start.location = (800, 900)

    # Instance at end
    inst_end = nt.nodes.new("GeometryNodeInstanceOnPoints")
    nt.links.new(fillet.outputs['Curve'], inst_end.inputs['Points'])
    nt.links.new(ep_pipe_end.outputs['Selection'], inst_end.inputs['Selection'])
    nt.links.new(sw_fit_end.outputs['Output'], inst_end.inputs['Instance'])
    nt.links.new(align_fillet_tan.outputs['Rotation'], inst_end.inputs['Rotation'])
    inst_end.location = (800, 1500)

    # ----------------------------------------------------
    # H. Combine Everything, Shade Smooth & Material
    # ----------------------------------------------------
    join_all = nt.nodes.new("GeometryNodeJoinGeometry")
    nt.links.new(pipe_mesh.outputs['Mesh'], join_all.inputs['Geometry'])
    nt.links.new(inst_collars.outputs['Instances'], join_all.inputs['Geometry'])
    nt.links.new(inst_start.outputs['Instances'], join_all.inputs['Geometry'])
    nt.links.new(inst_end.outputs['Instances'], join_all.inputs['Geometry'])
    join_all.location = (1100, 400)

    realize = nt.nodes.new("GeometryNodeRealizeInstances")
    nt.links.new(join_all.outputs['Geometry'], realize.inputs['Geometry'])
    realize.location = (1300, 400)

    smooth = nt.nodes.new("GeometryNodeSetShadeSmooth")
    smooth.inputs['Shade Smooth'].default_value = True
    nt.links.new(realize.outputs['Geometry'], smooth.inputs['Geometry'])
    smooth.location = (1500, 400)

    set_mat = nt.nodes.new("GeometryNodeSetMaterial")
    nt.links.new(smooth.outputs['Geometry'], set_mat.inputs['Geometry'])
    nt.links.new(node_in.outputs['管道材质'], set_mat.inputs['Material'])
    set_mat.location = (1700, 400)

    nt.links.new(set_mat.outputs['Geometry'], node_out.inputs['Geometry'])

    print("Procedural Pipe Node Tree rebuilt successfully!")

def apply_defaults_to_modifiers():
    ng = bpy.data.node_groups.get("GN_Procedural_Pipe")
    if not ng:
        return
    for name in ["Pipe_Template", "Pipe_Demo_MultiTurn"]:
        obj = bpy.data.objects.get(name)
        if obj:
            mod = obj.modifiers.get("GeometryNodes") or obj.modifiers[0]
            mod.node_group = ng
            for item in ng.interface.items_tree:
                if item.item_type == 'SOCKET' and item.in_out == 'INPUT':
                    if hasattr(item, 'default_value') and item.default_value is not None:
                        prop = getattr(mod.properties.inputs, item.identifier, None)
                        if prop and hasattr(prop, 'value'):
                            prop.value = item.default_value
            obj.data.update()

if __name__ == "__main__":
    build_procedural_pipe_node_tree()
    apply_defaults_to_modifiers()
