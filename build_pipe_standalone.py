# -*- coding: utf-8 -*-
"""
独立版参数化水管系统构建脚本（严格依据《Blender 几何节点参数化水管系统技术实现方案》）
=====================================================================
从零构建单一 .blend 交付文件，不依赖任何外部资源：
  - 节点资产   GN_Procedural_Pipe（10 个面板参数 + 完整几何节点流）
  - 母版对象   Pipe_Template        90° 下水弯管（起点外螺纹公头 + 转角双承插套箍 + 终点加厚承口扩口）
  - 演示对象   Pipe_Demo_MultiTurn  多段连续 S 形/下行/转弯管网
  - 材质       PVC_White_Plastic    Principled BSDF，粗糙度 0.35
  - 摄影/照明  Pipe_Camera + Cam_Target + Key_Sun/Fill_Light/Rim_Light + 中性灰世界背景
运行：blender -b --python build_pipe_standalone.py
输出：E:\\Three JS\\Blender Agent\\GN_Procedural_Pipe.blend
"""
import bpy
import math
import os

OUT = r"E:\Three JS\Blender Agent\GN_Procedural_Pipe.blend"

# 文档规定的固定几何常量（文档 3.2 / 3.3 / 3.4）
SOCKET_SCALE   = 1.18   # 3.4 终点扩口直径 = 管径 * 1.18
TH_CORE_SCALE  = 0.95   # 3.3 螺纹段芯棒半径比例
TH_RIDGE_H     = 0.002  # 3.3 螺纹齿外凸高度 0.002m
SOCK_LIP_H     = 0.003  # 3.4 承口卷边外凸厚度 0.003m
COLLAR_LEN     = 0.025  # 3.2 套箍长度 0.025m
COLLAR_GAP     = 0.002  # 套箍口部与弯头弧线起点的重叠量
RESAMPLE_LEN   = 0.008  # 管身重采样步长（文档流程 Resample Curve）
FILLET_COUNT   = 8      # 倒角弧段细分

# =====================================================================
# 0. 全新空场景
# =====================================================================
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# =====================================================================
# 1. 材质 PVC_White_Plastic（文档 1.2-5：哑光/微光泽工程白色 PVC）
# =====================================================================
mat = bpy.data.materials.new("PVC_White_Plastic")
mat.use_nodes = True
_bsdf = mat.node_tree.nodes["Principled BSDF"]
_bsdf.inputs["Base Color"].default_value = (0.88, 0.88, 0.86, 1.0)
_bsdf.inputs["Metallic"].default_value = 0.0
_bsdf.inputs["Roughness"].default_value = 0.35
_bsdf.inputs["IOR"].default_value = 1.46
_bsdf.inputs["Specular IOR Level"].default_value = 0.5

# =====================================================================
# 2. 节点组 GN_Procedural_Pipe
# =====================================================================
ng = bpy.data.node_groups.new("GN_Procedural_Pipe", "GeometryNodeTree")
ng.interface.clear()

# ---- 2.1 接口（面板参数，名称/默认值/范围严格按文档第 4 节表格）----
def add_sock(name, stype, **kw):
    s = ng.interface.new_socket(name, in_out='INPUT', socket_type=stype)
    for k, v in kw.items():
        setattr(s, k, v)
    return s

ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
add_sock("管道外径",     'NodeSocketFloat', default_value=0.05,  min_value=0.01,  max_value=0.5)
add_sock("弯头倒角半径", 'NodeSocketFloat', default_value=0.06,  min_value=0.02,  max_value=0.3)
add_sock("转角套箍开关", 'NodeSocketBool',  default_value=True)
add_sock("套箍放大比例", 'NodeSocketFloat', default_value=1.16,  min_value=1.05,  max_value=1.4)
add_sock("螺纹段长度",   'NodeSocketFloat', default_value=0.05,  min_value=0.01,  max_value=0.2)
add_sock("螺纹齿距",     'NodeSocketFloat', default_value=0.005, min_value=0.002, max_value=0.02)
add_sock("承口扩口长度", 'NodeSocketFloat', default_value=0.045, min_value=0.01,  max_value=0.2)
add_sock("两端接头翻转", 'NodeSocketBool',  default_value=False)
add_sock("截面圆环细分", 'NodeSocketInt',   default_value=24,    min_value=8,     max_value=64)
add_sock("管道材质",     'NodeSocketMaterial', default_value=mat)
ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

# ---- 2.2 节点 ----
nodes = ng.nodes
def N(bl_id, loc):
    n = nodes.new(bl_id)
    n.location = loc
    return n
def L(o, i):
    ng.links.new(o, i)

gin  = N("NodeGroupInput",  (-2200, 0))
gout = N("NodeGroupOutput", ( 2600, 0))

# ---------- 半径换算链 ----------
r_pipe = N("ShaderNodeMath", (-2050, -300)); r_pipe.operation = 'DIVIDE'; r_pipe.inputs[1].default_value = 2.0
L(gin.outputs['管道外径'], r_pipe.inputs[0])                       # r_pipe = 外径/2

r_collar = N("ShaderNodeMath", (-1850, -300)); r_collar.operation = 'MULTIPLY'
L(r_pipe.outputs['Value'], r_collar.inputs[0])
L(gin.outputs['套箍放大比例'], r_collar.inputs[1])                 # r_collar = r_pipe * 1.16

r_socket = N("ShaderNodeMath", (-1850, -450)); r_socket.operation = 'MULTIPLY'; r_socket.inputs[1].default_value = SOCKET_SCALE
L(r_pipe.outputs['Value'], r_socket.inputs[0])                     # r_socket = r_pipe * 1.18（文档 3.4）

r_core = N("ShaderNodeMath", (-1850, -600)); r_core.operation = 'MULTIPLY'; r_core.inputs[1].default_value = TH_CORE_SCALE
L(r_pipe.outputs['Value'], r_core.inputs[0])                       # r_core = r_pipe * 0.95

# ---------- A. 转折拐点识别（原始网格上）----------
vn = N("GeometryNodeInputMeshVertexNeighbors", (-2050, 300))
cmp_corner = N("FunctionNodeCompare", (-1850, 300))
cmp_corner.data_type = 'INT'; cmp_corner.operation = 'EQUAL'; cmp_corner.inputs['B'].default_value = 2
L(vn.outputs['Vertex Count'], cmp_corner.inputs['A'])              # 邻接边数==2 → 拐点

store_corner = N("GeometryNodeStoreNamedAttribute", (-1650, 300))
store_corner.data_type = 'INT'; store_corner.domain = 'POINT'; store_corner.inputs['Name'].default_value = "is_corner"
L(gin.outputs['Geometry'], store_corner.inputs['Geometry'])
L(cmp_corner.outputs['Result'], store_corner.inputs['Value'])
store_corner.label = "A 拐点标记"

# ---------- B. 管身：Mesh→Curve→Fillet→Resample→放样 ----------
m2c = N("GeometryNodeMeshToCurve", (-1450, 500))
L(store_corner.outputs['Geometry'], m2c.inputs['Mesh'])
m2c.label = "B 管身放样"

fillet = N("GeometryNodeFilletCurve", (-1250, 500))
fillet.inputs['Mode'].default_value = 'Poly'
fillet.inputs['Count'].default_value = FILLET_COUNT
fillet.inputs['Limit Radius'].default_value = True                # 间距不足自动钳制半径（文档 3.1）
L(m2c.outputs['Curve'], fillet.inputs['Curve'])
L(gin.outputs['弯头倒角半径'], fillet.inputs['Radius'])

resamp = N("GeometryNodeResampleCurve", (-1050, 500))
resamp.inputs['Mode'].default_value = 'Length'
resamp.inputs['Length'].default_value = RESAMPLE_LEN
L(fillet.outputs['Curve'], resamp.inputs['Curve'])

prof = N("GeometryNodeCurvePrimitiveCircle", (-1050, 300))
L(gin.outputs['截面圆环细分'], prof.inputs['Resolution'])
L(r_pipe.outputs['Value'], prof.inputs['Radius'])

body = N("GeometryNodeCurveToMesh", (-850, 500))
L(resamp.outputs['Curve'], body.inputs['Curve'])
L(prof.outputs['Curve'], body.inputs['Profile Curve'])

# ---------- C. 承插套箍组件（局部坐标：口部 Z=0 朝向 +Z/弯头，筒身向 -Z）----------
# C1 过渡锥：Z=-0.025(r_pipe) → Z=-0.019(r_collar)
cone_sh = N("GeometryNodeMeshCone", (-1700, -800))
cone_sh.fill_type = 'NONE'; cone_sh.inputs['Depth'].default_value = 0.006
L(gin.outputs['截面圆环细分'], cone_sh.inputs['Vertices'])
L(r_collar.outputs['Value'], cone_sh.inputs['Radius Top'])
L(r_pipe.outputs['Value'],   cone_sh.inputs['Radius Bottom'])
cx_sh = N("ShaderNodeCombineXYZ", (-1700, -950)); cx_sh.inputs['Z'].default_value = -0.022
tf_sh = N("GeometryNodeTransform", (-1500, -800))
L(cx_sh.outputs['Vector'], tf_sh.inputs['Translation'])
L(cone_sh.outputs['Mesh'], tf_sh.inputs['Geometry'])

# C2 套箍筒身：长 0.015，半径 r_collar，Z∈[-0.019,-0.004]
cyl_bar = N("GeometryNodeMeshCylinder", (-1700, -1100))
cyl_bar.fill_type = 'NONE'; cyl_bar.inputs['Depth'].default_value = 0.015
L(gin.outputs['截面圆环细分'], cyl_bar.inputs['Vertices'])
L(r_collar.outputs['Value'], cyl_bar.inputs['Radius'])
cx_bar = N("ShaderNodeCombineXYZ", (-1700, -1250)); cx_bar.inputs['Z'].default_value = -0.0115
tf_bar = N("GeometryNodeTransform", (-1500, -1100))
L(cx_bar.outputs['Vector'], tf_bar.inputs['Translation'])
L(cyl_bar.outputs['Mesh'], tf_bar.inputs['Geometry'])

# C3 口部卷边珠环：Z=-0.0015，半径 r_collar，珠径 0.0015（组件总长精确 0.025：-0.025~0）
lip_sp = N("GeometryNodeCurvePrimitiveCircle", (-1700, -1400))
L(gin.outputs['截面圆环细分'], lip_sp.inputs['Resolution'])
L(r_collar.outputs['Value'], lip_sp.inputs['Radius'])
lip_pr = N("GeometryNodeCurvePrimitiveCircle", (-1700, -1550))
lip_pr.inputs['Resolution'].default_value = 8; lip_pr.inputs['Radius'].default_value = 0.0015
lip_c2m = N("GeometryNodeCurveToMesh", (-1500, -1450))
L(lip_sp.outputs['Curve'], lip_c2m.inputs['Curve'])
L(lip_pr.outputs['Curve'], lip_c2m.inputs['Profile Curve'])
cx_lip = N("ShaderNodeCombineXYZ", (-1500, -1600)); cx_lip.inputs['Z'].default_value = -0.0015
tf_lip = N("GeometryNodeTransform", (-1300, -1450))
L(cx_lip.outputs['Vector'], tf_lip.inputs['Translation'])
L(lip_c2m.outputs['Mesh'], tf_lip.inputs['Geometry'])

join_collar = N("GeometryNodeJoinGeometry", (-1100, -1100))
L(tf_sh.outputs['Geometry'],  join_collar.inputs['Geometry'])
L(tf_bar.outputs['Geometry'], join_collar.inputs['Geometry'])
L(tf_lip.outputs['Geometry'], join_collar.inputs['Geometry'])
join_collar.label = "C 套箍组件"

# ---------- D. 在拐点两侧实例化套箍 ----------
split = N("GeometryNodeSplitEdges", (-1700, 100))
L(store_corner.outputs['Geometry'], split.inputs['Mesh'])
ecurve = N("GeometryNodeMeshToCurve", (-1550, 100))
L(split.outputs['Mesh'], ecurve.inputs['Mesh'])

splen = N("GeometryNodeSplineLength", (-1550, -100))               # 场节点：逐样条长度
store_len = N("GeometryNodeStoreNamedAttribute", (-1400, 100))
store_len.data_type = 'FLOAT'; store_len.domain = 'POINT'; store_len.inputs['Name'].default_value = "edge_len"
L(ecurve.outputs['Curve'], store_len.inputs['Geometry'])
L(splen.outputs['Length'], store_len.inputs['Value'])

tan = N("GeometryNodeInputTangent", (-1400, -50))
store_tan = N("GeometryNodeStoreNamedAttribute", (-1250, 100))
store_tan.data_type = 'FLOAT_VECTOR'; store_tan.domain = 'POINT'; store_tan.inputs['Name'].default_value = "edge_tan"
L(store_len.outputs['Geometry'], store_tan.inputs['Geometry'])
L(tan.outputs['Tangent'], store_tan.inputs['Value'])

read_corner = N("GeometryNodeInputNamedAttribute", (-1250, 400))
read_corner.data_type = 'INT'; read_corner.inputs['Name'].default_value = "is_corner"
read_tan = N("GeometryNodeInputNamedAttribute", (-1250, -50))
read_tan.data_type = 'FLOAT_VECTOR'; read_tan.inputs['Name'].default_value = "edge_tan"
read_len = N("GeometryNodeInputNamedAttribute", (-1250, -200))
read_len.data_type = 'FLOAT'; read_len.inputs['Name'].default_value = "edge_len"

ep_corner = N("GeometryNodeCurveEndpointSelection", (-1250, 550))
ep_corner.inputs['Start Size'].default_value = 1
ep_corner.inputs['End Size'].default_value = 0

minlen = N("ShaderNodeMath", (-1500, -300)); minlen.operation = 'MULTIPLY'; minlen.inputs[1].default_value = 1.3
L(gin.outputs['弯头倒角半径'], minlen.inputs[0])                   # 边最短长度 = R*1.3

cmp_len = N("FunctionNodeCompare", (-1100, -250))
cmp_len.data_type = 'FLOAT'; cmp_len.operation = 'GREATER_THAN'
L(read_len.outputs['Attribute'], cmp_len.inputs['A'])
L(minlen.outputs['Value'], cmp_len.inputs['B'])

cmp_is = N("FunctionNodeCompare", (-1100, 400))
cmp_is.data_type = 'INT'; cmp_is.operation = 'EQUAL'; cmp_is.inputs['B'].default_value = 1
L(read_corner.outputs['Attribute'], cmp_is.inputs['A'])

and1 = N("FunctionNodeBooleanMath", (-950, 400)); and1.operation = 'AND'
L(cmp_is.outputs['Result'], and1.inputs[0])
L(gin.outputs['转角套箍开关'], and1.inputs[1])
and2 = N("FunctionNodeBooleanMath", (-800, 400)); and2.operation = 'AND'
L(and1.outputs['Boolean'], and2.inputs[0])
L(cmp_len.outputs['Result'], and2.inputs[1])                       # 套箍实例化选择

sw_sign = N("GeometryNodeSwitch", (-1100, 550)); sw_sign.input_type = 'FLOAT'
L(ep_corner.outputs['Selection'], sw_sign.inputs['Switch'])
sw_sign.inputs['False'].default_value = -1.0
sw_sign.inputs['True'].default_value = 1.0                        # S: 拐点在样条起点=+1，终点=-1

sub_r = N("ShaderNodeMath", (-1100, 250)); sub_r.operation = 'SUBTRACT'; sub_r.inputs[1].default_value = COLLAR_GAP
L(gin.outputs['弯头倒角半径'], sub_r.inputs[0])
mul_d = N("ShaderNodeMath", (-950, 250)); mul_d.operation = 'MULTIPLY'
L(sw_sign.outputs['Output'], mul_d.inputs[0])
L(sub_r.outputs['Value'], mul_d.inputs[1])                        # 偏移量 = S*(R-0.002)

vec_off = N("ShaderNodeVectorMath", (-800, 250)); vec_off.operation = 'SCALE'
L(read_tan.outputs['Attribute'], vec_off.inputs['Vector'])
L(mul_d.outputs['Value'], vec_off.inputs['Scale'])

setpos = N("GeometryNodeSetPosition", (-650, 150))
L(store_tan.outputs['Geometry'], setpos.inputs['Geometry'])
L(vec_off.outputs['Vector'], setpos.inputs['Offset'])
L(and2.outputs['Boolean'], setpos.inputs['Selection'])            # 仅拐点偏移到弧线切口

neg = N("ShaderNodeMath", (-950, 0)); neg.operation = 'MULTIPLY'; neg.inputs[1].default_value = -1.0
L(sw_sign.outputs['Output'], neg.inputs[0])
rotv = N("ShaderNodeVectorMath", (-800, 0)); rotv.operation = 'SCALE'
L(read_tan.outputs['Attribute'], rotv.inputs['Vector'])
L(neg.outputs['Value'], rotv.inputs['Scale'])                     # 口部朝向 = 切线 * (-S)

align = N("FunctionNodeAlignEulerToVector", (-650, 0))
align.axis = 'Z'; align.pivot_axis = 'AUTO'
L(rotv.outputs['Vector'], align.inputs['Vector'])

inst_collar = N("GeometryNodeInstanceOnPoints", (-450, 150))
L(setpos.outputs['Geometry'], inst_collar.inputs['Points'])
L(and2.outputs['Boolean'], inst_collar.inputs['Selection'])
L(join_collar.outputs['Geometry'], inst_collar.inputs['Instance'])
L(align.outputs['Rotation'], inst_collar.inputs['Rotation'])
inst_collar.label = "D 拐点套箍"

# ---------- E. 起点外螺纹公接头（局部：螺纹向 -Z 伸出，止水环 +Z 埋入管身）----------
# E1 螺纹芯棒
cyl_core = N("GeometryNodeMeshCylinder", (-1500, 900))
cyl_core.fill_type = 'NONE'
L(gin.outputs['截面圆环细分'], cyl_core.inputs['Vertices'])
L(r_core.outputs['Value'], cyl_core.inputs['Radius'])
L(gin.outputs['螺纹段长度'], cyl_core.inputs['Depth'])
hl = N("ShaderNodeMath", (-1500, 800)); hl.operation = 'MULTIPLY'; hl.inputs[1].default_value = -0.5
L(gin.outputs['螺纹段长度'], hl.inputs[0])
cx_core = N("ShaderNodeCombineXYZ", (-1500, 700))
L(hl.outputs['Value'], cx_core.inputs['Z'])                       # 芯棒 Z∈[-L,0]
tf_core = N("GeometryNodeTransform", (-1300, 900))
L(cx_core.outputs['Vector'], tf_core.inputs['Translation'])
L(cyl_core.outputs['Mesh'], tf_core.inputs['Geometry'])

# E2 螺纹齿牙：沿线 0→-L 按齿距重采样，实例化齿环（外凸 0.002）
line = N("GeometryNodeCurvePrimitiveLine", (-1500, 1150))
neg_l = N("ShaderNodeMath", (-1500, 1300)); neg_l.operation = 'MULTIPLY'; neg_l.inputs[1].default_value = -1.0
L(gin.outputs['螺纹段长度'], neg_l.inputs[0])
end_v = N("ShaderNodeCombineXYZ", (-1500, 1050))
L(neg_l.outputs['Value'], end_v.inputs['Z'])
L(end_v.outputs['Vector'], line.inputs['End'])
res_th = N("GeometryNodeResampleCurve", (-1300, 1150))
res_th.inputs['Mode'].default_value = 'Length'
L(line.outputs['Curve'], res_th.inputs['Curve'])
L(gin.outputs['螺纹齿距'], res_th.inputs['Length'])
rsp = N("GeometryNodeCurvePrimitiveCircle", (-1100, 1300))
L(gin.outputs['截面圆环细分'], rsp.inputs['Resolution'])
L(r_pipe.outputs['Value'], rsp.inputs['Radius'])
rpr = N("GeometryNodeCurvePrimitiveCircle", (-1100, 1450))
rpr.inputs['Resolution'].default_value = 6; rpr.inputs['Radius'].default_value = TH_RIDGE_H
rc2m = N("GeometryNodeCurveToMesh", (-900, 1350))
L(rsp.outputs['Curve'], rc2m.inputs['Curve'])
L(rpr.outputs['Curve'], rc2m.inputs['Profile Curve'])
inst_ridge = N("GeometryNodeInstanceOnPoints", (-700, 1250))
L(res_th.outputs['Curve'], inst_ridge.inputs['Points'])
L(rc2m.outputs['Mesh'], inst_ridge.inputs['Instance'])

# E3 止水挡环（法兰）：Z∈[0,0.005]，半径 r_collar
cyl_stop = N("GeometryNodeMeshCylinder", (-1500, 1600))
cyl_stop.fill_type = 'NONE'; cyl_stop.inputs['Depth'].default_value = 0.005
L(gin.outputs['截面圆环细分'], cyl_stop.inputs['Vertices'])
L(r_collar.outputs['Value'], cyl_stop.inputs['Radius'])
cx_stop = N("ShaderNodeCombineXYZ", (-1500, 1700)); cx_stop.inputs['Z'].default_value = 0.0025
tf_stop = N("GeometryNodeTransform", (-1300, 1600))
L(cx_stop.outputs['Vector'], tf_stop.inputs['Translation'])
L(cyl_stop.outputs['Mesh'], tf_stop.inputs['Geometry'])

# E4 止水环收分锥：Z∈[0.005,0.011]，r_collar→r_pipe
cone_ss = N("GeometryNodeMeshCone", (-1500, 1850))
cone_ss.fill_type = 'NONE'; cone_ss.inputs['Depth'].default_value = 0.006
L(gin.outputs['截面圆环细分'], cone_ss.inputs['Vertices'])
L(r_pipe.outputs['Value'],   cone_ss.inputs['Radius Top'])
L(r_collar.outputs['Value'], cone_ss.inputs['Radius Bottom'])
cx_ss = N("ShaderNodeCombineXYZ", (-1500, 1950)); cx_ss.inputs['Z'].default_value = 0.008
tf_ss = N("GeometryNodeTransform", (-1300, 1850))
L(cx_ss.outputs['Vector'], tf_ss.inputs['Translation'])
L(cone_ss.outputs['Mesh'], tf_ss.inputs['Geometry'])

join_th = N("GeometryNodeJoinGeometry", (-500, 1200))
L(tf_core.outputs['Geometry'],    join_th.inputs['Geometry'])
L(inst_ridge.outputs['Instances'],join_th.inputs['Geometry'])
L(tf_stop.outputs['Geometry'],    join_th.inputs['Geometry'])
L(tf_ss.outputs['Geometry'],      join_th.inputs['Geometry'])
join_th.label = "E 外螺纹公接头"

# ---------- F. 终点加厚承插扩口（局部：向 +Z 伸出）----------
# F1 过渡锥：Z∈[-0.002,0.006]，r_pipe→r_socket
cone_sk = N("GeometryNodeMeshCone", (-1500, 2200))
cone_sk.fill_type = 'NONE'; cone_sk.inputs['Depth'].default_value = 0.008
L(gin.outputs['截面圆环细分'], cone_sk.inputs['Vertices'])
L(r_socket.outputs['Value'], cone_sk.inputs['Radius Top'])
L(r_pipe.outputs['Value'],   cone_sk.inputs['Radius Bottom'])
cx_sk = N("ShaderNodeCombineXYZ", (-1500, 2300)); cx_sk.inputs['Z'].default_value = 0.002
tf_sk = N("GeometryNodeTransform", (-1300, 2200))
L(cx_sk.outputs['Vector'], tf_sk.inputs['Translation'])
L(cone_sk.outputs['Mesh'], tf_sk.inputs['Geometry'])

# F2 扩口筒身：Z∈[0.006, 0.006+L]，半径 r_socket(1.18x)
cyl_sk = N("GeometryNodeMeshCylinder", (-1500, 2450))
cyl_sk.fill_type = 'NONE'
L(gin.outputs['截面圆环细分'], cyl_sk.inputs['Vertices'])
L(r_socket.outputs['Value'], cyl_sk.inputs['Radius'])
L(gin.outputs['承口扩口长度'], cyl_sk.inputs['Depth'])
hsk = N("ShaderNodeMath", (-1500, 2600)); hsk.operation = 'MULTIPLY'; hsk.inputs[1].default_value = 0.5
L(gin.outputs['承口扩口长度'], hsk.inputs[0])
zc = N("ShaderNodeMath", (-1500, 2700)); zc.operation = 'ADD'; zc.inputs[1].default_value = 0.006
L(hsk.outputs['Value'], zc.inputs[0])
cx_sk2 = N("ShaderNodeCombineXYZ", (-1500, 2800))
L(zc.outputs['Value'], cx_sk2.inputs['Z'])
tf_sk2 = N("GeometryNodeTransform", (-1300, 2450))
L(cx_sk2.outputs['Vector'], tf_sk2.inputs['Translation'])
L(cyl_sk.outputs['Mesh'], tf_sk2.inputs['Geometry'])

# F3 卷边卡环：Z=0.006+L，半径 r_socket，外凸 0.003
lsp = N("GeometryNodeCurvePrimitiveCircle", (-1500, 2950))
L(gin.outputs['截面圆环细分'], lsp.inputs['Resolution'])
L(r_socket.outputs['Value'], lsp.inputs['Radius'])
lpr = N("GeometryNodeCurvePrimitiveCircle", (-1500, 3100))
lpr.inputs['Resolution'].default_value = 8; lpr.inputs['Radius'].default_value = SOCK_LIP_H
lc2m = N("GeometryNodeCurveToMesh", (-1300, 3000))
L(lsp.outputs['Curve'], lc2m.inputs['Curve'])
L(lpr.outputs['Curve'], lc2m.inputs['Profile Curve'])
lz = N("ShaderNodeMath", (-1500, 3200)); lz.operation = 'ADD'; lz.inputs[1].default_value = 0.006
L(gin.outputs['承口扩口长度'], lz.inputs[0])
cx_l = N("ShaderNodeCombineXYZ", (-1300, 3200))
L(lz.outputs['Value'], cx_l.inputs['Z'])
tf_lip2 = N("GeometryNodeTransform", (-1100, 3000))
L(cx_l.outputs['Vector'], tf_lip2.inputs['Translation'])
L(lc2m.outputs['Mesh'], tf_lip2.inputs['Geometry'])

join_sk = N("GeometryNodeJoinGeometry", (-900, 2600))
L(tf_sk.outputs['Geometry'],   join_sk.inputs['Geometry'])
L(tf_sk2.outputs['Geometry'],  join_sk.inputs['Geometry'])
L(tf_lip2.outputs['Geometry'], join_sk.inputs['Geometry'])
join_sk.label = "F 承插扩口接头"

# ---------- G0. 翻转专用：接头几何绕局部 X 轴旋转 180° ----------
# 公/母接头均为有方向几何（公头向局部 -Z 伸出、承口向 +Z 伸出）；
# 只有配合 180° 旋转后再对调到对侧端点，接头才能正确朝外
tf_th_rot = N("GeometryNodeTransform", (-300, 1300))
tf_th_rot.inputs['Rotation'].default_value = (math.pi, 0, 0)
L(join_th.outputs['Geometry'], tf_th_rot.inputs['Geometry'])
tf_sk_rot = N("GeometryNodeTransform", (-700, 2700))
tf_sk_rot.inputs['Rotation'].default_value = (math.pi, 0, 0)
L(join_sk.outputs['Geometry'], tf_sk_rot.inputs['Geometry'])

# ---------- G. 端头接头实例化（起点公/母 + 终点母/公，支持翻转）----------
ep_s = N("GeometryNodeCurveEndpointSelection", (-650, 700))
ep_s.inputs['Start Size'].default_value = 1; ep_s.inputs['End Size'].default_value = 0
ep_e = N("GeometryNodeCurveEndpointSelection", (-650, 900))
ep_e.inputs['Start Size'].default_value = 0; ep_e.inputs['End Size'].default_value = 1

tan_f = N("GeometryNodeInputTangent", (-650, 800))
align_f = N("FunctionNodeAlignEulerToVector", (-450, 800))
align_f.axis = 'Z'; align_f.pivot_axis = 'AUTO'
L(tan_f.outputs['Tangent'], align_f.inputs['Vector'])

sw_s = N("GeometryNodeSwitch", (-650, 550)); sw_s.input_type = 'GEOMETRY'
L(gin.outputs['两端接头翻转'], sw_s.inputs['Switch'])
L(join_th.outputs['Geometry'],  sw_s.inputs['False'])   # 默认：起点=外螺纹公头
L(tf_sk_rot.outputs['Geometry'], sw_s.inputs['True'])   # 翻转：起点=承口（已旋转朝外）
sw_e = N("GeometryNodeSwitch", (-450, 1000)); sw_e.input_type = 'GEOMETRY'
L(gin.outputs['两端接头翻转'], sw_e.inputs['Switch'])
L(join_sk.outputs['Geometry'],  sw_e.inputs['False'])   # 默认：终点=承插扩口
L(tf_th_rot.outputs['Geometry'], sw_e.inputs['True'])   # 翻转：终点=外螺纹公头（已旋转朝外）

inst_s = N("GeometryNodeInstanceOnPoints", (-250, 700))
L(fillet.outputs['Curve'], inst_s.inputs['Points'])
L(ep_s.outputs['Selection'], inst_s.inputs['Selection'])
L(sw_s.outputs['Output'], inst_s.inputs['Instance'])
L(align_f.outputs['Rotation'], inst_s.inputs['Rotation'])
inst_e = N("GeometryNodeInstanceOnPoints", (-250, 1000))
L(fillet.outputs['Curve'], inst_e.inputs['Points'])
L(ep_e.outputs['Selection'], inst_e.inputs['Selection'])
L(sw_e.outputs['Output'], inst_e.inputs['Instance'])
L(align_f.outputs['Rotation'], inst_e.inputs['Rotation'])
inst_s.label = "G 端头接头"

# ---------- H. 合并 → 实体化 → 平滑 → 材质 ----------
join_all = N("GeometryNodeJoinGeometry", (0, 500))
L(body.outputs['Mesh'],          join_all.inputs['Geometry'])
L(inst_collar.outputs['Instances'], join_all.inputs['Geometry'])
L(inst_s.outputs['Instances'],   join_all.inputs['Geometry'])
L(inst_e.outputs['Instances'],   join_all.inputs['Geometry'])
realize = N("GeometryNodeRealizeInstances", (200, 500))
L(join_all.outputs['Geometry'], realize.inputs['Geometry'])
smooth = N("GeometryNodeSetShadeSmooth", (400, 500))
smooth.inputs['Shade Smooth'].default_value = True
L(realize.outputs['Geometry'], smooth.inputs['Geometry'])
setmat = N("GeometryNodeSetMaterial", (600, 500))
L(smooth.outputs['Geometry'], setmat.inputs['Geometry'])
L(gin.outputs['管道材质'], setmat.inputs['Material'])
L(setmat.outputs['Geometry'], gout.inputs['Geometry'])
join_all.label = "H 合并输出"

# =====================================================================
# 3. 母版/演示对象（路径网格 + GN 修改器）
# =====================================================================
def make_pipe(name, verts, loc):
    edges = [(i, i + 1) for i in range(len(verts) - 1)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, me)
    sc.collection.objects.link(obj)
    obj.location = loc
    mod = obj.modifiers.new("GeometryNodes", 'NODES')
    mod.node_group = ng
    obj.data.materials.append(mat)   # 基体网格同步材质槽，保证对象材质列表非空
    return obj

# Pipe_Template：90° 下水弯管 —— 底部起点(外螺纹) 竖直上行 0.35m，90° 转弯水平 0.15m（终点承口）
TPL_VERTS = [(0, 0, 0), (0, 0, 0.35), (0.15, 0, 0.35)]
# Pipe_Demo_MultiTurn：多段连续 S 形/下行/转弯 —— 上 0.5 → 右 0.35 → 前 0.30 → 下 0.38 → 左 0.25
DEMO_VERTS = [(0, 0, 0), (0, 0, 0.50), (0.35, 0, 0.50), (0.35, 0.30, 0.50), (0.35, 0.30, 0.12), (0.10, 0.30, 0.12)]

t_obj = make_pipe("Pipe_Template", TPL_VERTS, (0.0, 0.0, 0.0))
d_obj = make_pipe("Pipe_Demo_MultiTurn", DEMO_VERTS, (0.62, 0.0, 0.0))

# =====================================================================
# 4. 螺纹端朝向自检：确认“外螺纹公头”落在路径首端（v0），否则翻转网格顶点序
# =====================================================================
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()

def thread_at_first_vertex(obj, verts):
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    zmin = min((mw @ v.co).z for v in me.vertices)
    zmax = max((mw @ v.co).z for v in me.vertices)
    ev.to_mesh_clear()
    # 螺纹芯棒+齿环自起点沿切向外伸 0.05m：首端在最低点时即螺纹在下
    v0z = verts[0][2] + obj.location[2]
    return zmin < v0z - 0.03, zmin, zmax

ok_t, zmin_t, zmax_t = thread_at_first_vertex(t_obj, TPL_VERTS)
if not ok_t:
    # Mesh to Curve 样条方向与预期相反 → 反转顶点序（几何不变，仅翻转首尾）
    rev = list(reversed(TPL_VERTS))
    t_obj.data.from_pydata(rev, [(i, i + 1) for i in range(len(rev) - 1)], [])
    bpy.context.view_layer.update()
    ok_t, zmin_t, zmax_t = thread_at_first_vertex(t_obj, rev)
    print("[fix] Pipe_Template 顶点序已反转以校正螺纹端朝向 -> ok:", ok_t)

ok_d, zmin_d, zmax_d = thread_at_first_vertex(d_obj, DEMO_VERTS)
if not ok_d:
    rev = list(reversed(DEMO_VERTS))
    d_obj.data.from_pydata(rev, [(i, i + 1) for i in range(len(rev) - 1)], [])
    bpy.context.view_layer.update()
    ok_d, zmin_d, zmax_d = thread_at_first_vertex(d_obj, rev)
    print("[fix] Pipe_Demo_MultiTurn 顶点序已反转以校正螺纹端朝向 -> ok:", ok_d)

print("[check] Pipe_Template        z-range: %.3f .. %.3f  (期望 -0.052..0.383)" % (zmin_t, zmax_t))
print("[check] Pipe_Demo_MultiTurn  z-range: %.3f .. %.3f" % (zmin_d, zmax_d))

# =====================================================================
# 5. 场景包围盒 → 摄影机/目标/灯光自动构图
# =====================================================================
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
mn = [1e9] * 3
mx = [-1e9] * 3
for o in (t_obj, d_obj):
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    mw = ev.matrix_world
    for v in me.vertices:
        w = mw @ v.co
        for i in range(3):
            mn[i] = min(mn[i], w[i])
            mx[i] = max(mx[i], w[i])
    ev.to_mesh_clear()
center = [(mn[i] + mx[i]) / 2 for i in range(3)]
size = [mx[i] - mn[i] for i in range(3)]
print("[frame] bbox min=%s max=%s size=%s" % (
    ["%.3f" % v for v in mn], ["%.3f" % v for v in mx], ["%.3f" % v for v in size]))

# 世界背景：中性灰（契合参考图背景，便于 1:1 比对）
w = bpy.data.worlds.new("World")
sc.world = w
w.use_nodes = True
bg = w.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.72, 0.73, 0.75, 1.0)
bg.inputs[1].default_value = 0.45   # 压低环境天光，保留聚光塑形（避免白色管体被洗白）

# 目标空对象
tgt = bpy.data.objects.new("Cam_Target", None)
sc.collection.objects.link(tgt)
tgt.location = center

# 摄影机（50mm，3/4 视角，按包围盒自动适配距离）
cam_d = bpy.data.cameras.new("Pipe_Camera")
cam_d.lens = 50.0
cam_d.sensor_fit = 'AUTO'
cam = bpy.data.objects.new("Pipe_Camera", cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
tc = cam.constraints.new('TRACK_TO')
tc.target = tgt
tc.track_axis = 'TRACK_NEGATIVE_Z'
tc.up_axis = 'UP_Y'

lens = 50.0
hfov = 2 * math.atan(18.0 / lens)                      # 横向 36mm 传感器
vfov = 2 * math.atan((36.0 * (900.0 / 1200.0) / 2) / lens)
dist = max(size[0] * 1.18 / (2 * math.tan(hfov / 2)),
           size[1] * 1.30 / (2 * math.tan(vfov / 2)))
from mathutils import Vector
cdir = Vector((0.62, -0.72, 0.34)).normalized()
cam.location = Vector(center) + cdir * dist
print("[frame] camera dist=%.2f pos=%s" % (dist, ["%.2f" % v for v in cam.location]))

# 三点照明
def track_to(obj):
    c = obj.constraints.new('TRACK_TO')
    c.target = tgt
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'

sun = bpy.data.objects.new("Key_Sun", bpy.data.lights.new("Key_Sun", 'SUN'))
sun.data.energy = 4.5
sun.rotation_euler = Vector((-0.45, 0.50, -0.74)).to_track_quat('-Z', 'Y').to_euler()
sc.collection.objects.link(sun)

fill = bpy.data.objects.new("Fill_Light", bpy.data.lights.new("Fill_Light", 'AREA'))
fill.data.energy = 60.0
fill.data.shape = 'DISK'
fill.data.size = 1.5
fill.location = Vector(center) + Vector((-1.0, 0.9, 0.7))
track_to(fill)
sc.collection.objects.link(fill)

rim = bpy.data.objects.new("Rim_Light", bpy.data.lights.new("Rim_Light", 'AREA'))
rim.data.energy = 90.0
rim.data.shape = 'DISK'
rim.data.size = 1.2
rim.location = Vector(center) + Vector((0.2, 1.2, 1.0))
track_to(rim)
sc.collection.objects.link(rim)

# =====================================================================
# 6. 渲染设置（Eevee，交给用户本机 GPU 交互预览）
# =====================================================================
for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES'):
    try:
        sc.render.engine = eng
        break
    except Exception:
        continue
sc.render.resolution_x = 1200
sc.render.resolution_y = 900
sc.render.image_settings.file_format = 'PNG'
sc.view_settings.view_transform = 'Standard'
try:
    sc.eevee.taa_render_samples = 64
except Exception:
    pass
try:
    sc.eevee.use_gtao = True
except Exception:
    pass
sc.render.filepath = os.path.join(os.path.dirname(OUT), "_pipe_renders", "render_")
os.makedirs(os.path.dirname(sc.render.filepath), exist_ok=True)

# =====================================================================
# 7. 保存
# =====================================================================
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED:", OUT, "size:", os.path.getsize(OUT))
print("BUILD DONE")
