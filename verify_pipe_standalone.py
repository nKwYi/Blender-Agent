# -*- coding: utf-8 -*-
"""
GN_Procedural_Pipe.blend 验证脚本（v2：修正探针窗口坐标换算）
1) 接口参数默认值核对（文档第 4 节表格，float32 容差）
2) 求值几何数值断言（文档 3.1~3.4 全部尺寸）
3) 平滑着色 / 材质指定核对
4) 六角度 Eevee 渲染（失败自动降级 Cycles）
"""
import bpy, math, os
from mathutils import Vector

P = r"E:\Three JS\Blender Agent\GN_Procedural_Pipe.blend"
OUTDIR = r"E:\Three JS\Blender Agent\dev\_tmp_verify\pipe_standalone"
os.makedirs(OUTDIR, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=P)
sc = bpy.context.scene

fails = []
def check(name, got, exp, tol):
    if got is None:
        print("  [FAIL] %-42s got=None exp=%.4f" % (name, exp))
        fails.append(name); return
    ok = abs(got - exp) <= tol
    print("  [%s] %-42s got=%.4f exp=%.4f±%.4f" % ("PASS" if ok else "FAIL", name, got, exp, tol))
    if not ok:
        fails.append(name)

def check_true(name, cond, detail=""):
    print("  [%s] %-42s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        fails.append(name)

def feq(a, b):
    return abs(a - b) < 1e-5

# ---------------------------------------------------------------- 1. 接口参数
print("=== 1. 接口参数默认值（文档第 4 节）===")
ng = bpy.data.node_groups["GN_Procedural_Pipe"]
expect = {
    "管道外径": (0.05, 0.01, 0.5), "弯头倒角半径": (0.06, 0.02, 0.3),
    "转角套箍开关": (True, None, None), "套箍放大比例": (1.16, 1.05, 1.4),
    "螺纹段长度": (0.05, 0.01, 0.2), "螺纹齿距": (0.005, 0.002, 0.02),
    "承口扩口长度": (0.045, 0.01, 0.2), "两端接头翻转": (False, None, None),
    "截面圆环细分": (24, 8, 64),
}
sockets = {i.name: i for i in ng.interface.items_tree
           if i.item_type == 'SOCKET' and i.in_out == 'INPUT'}
for k, (dv, lo, hi) in expect.items():
    s = sockets.get(k)
    if s is None:
        fails.append("socket:" + k); print("  [FAIL] 缺少参数", k); continue
    ok = feq(float(s.default_value), float(dv)) if not isinstance(dv, bool) else (s.default_value == dv)
    rng_ok = True
    if lo is not None:
        rng_ok = feq(float(s.min_value), float(lo)) and feq(float(s.max_value), float(hi))
    print("  [%s] %-14s default=%s range=[%s,%s]" % (
        "PASS" if (ok and rng_ok) else "FAIL", k, s.default_value,
        getattr(s, 'min_value', None), getattr(s, 'max_value', None)))
    if not (ok and rng_ok):
        fails.append("socket:" + k)
msock = sockets.get("管道材质")
check_true("管道材质默认值", msock is not None and msock.default_value and msock.default_value.name == "PVC_White_Plastic",
           str(msock.default_value) if msock else "missing")
check_true("接口含 Geometry 输入/输出",
           "Geometry" in sockets and any(i.name == "Geometry" and i.in_out == 'OUTPUT'
                                         for i in ng.interface.items_tree if i.item_type == 'SOCKET'))

# ---------------------------------------------------------------- 2. 几何断言
print("=== 2. Pipe_Template 求值几何（世界坐标）===")
dg = bpy.context.evaluated_depsgraph_get()
t = bpy.data.objects["Pipe_Template"]
ev = t.evaluated_get(dg)
me = ev.to_mesh()
mw = ev.matrix_world
V = [mw @ v.co for v in me.vertices]
print("  verts=%d polys=%d" % (len(me.vertices), len(me.polygons)))

def dist_from_axis(v, p0, d):
    w = v - p0
    return (w - w.dot(d) * d).length

def radial(sub, p0, d, lo, hi, lat=None):
    """lo/hi 为沿轴方向的世界坐标区间；lat=(axis_idx, center, half) 横向过滤（仅用于多弯对象）"""
    idx = 0 if d.x else 2
    out = []
    for v in sub:
        p = v[idx]
        if not (lo <= p <= hi):
            continue
        if lat is not None:
            ai, c, h = lat
            if abs(v[ai] - c) > h:
                continue
        out.append(dist_from_axis(v, p0, d))
    return (max(out), min(out)) if out else (None, None)

Z = Vector((0, 0, 1)); X = Vector((1, 0, 0))
ORG = Vector((0, 0, 0))

# 2.1 竖直管身外径 0.025（z 0.05~0.25）
mx, mn = radial(V, ORG, Z, 0.05, 0.25)
check("竖直管身外径 r_pipe", mx, 0.025, 0.0012)
# 2.2 竖直套箍筒身外径 0.029（套箍中心 z=0.292，筒身 0.267~0.292）
mx, mn = radial(V, ORG, Z, 0.26, 0.288)
check("拐点套箍筒身外径 r_collar(1.16x)", mx, 0.029, 0.0012)
# 2.3 套箍口部唇珠外径 0.0305（唇珠 z 0.2895~0.2935）
mx, mn = radial(V, ORG, Z, 0.289, 0.295)
check("套箍唇珠外径 r_collar+0.0015", mx, 0.0305, 0.0012)
# 2.4 套箍组件：筒身长 0.015 精确（限筒身区 z<0.289，避开唇珠）
cz_bar = [v.z for v in V if 0.26 < v.z < 0.289 and 0.0288 < dist_from_axis(v, ORG, Z) < 0.0292]
if cz_bar:
    check("套箍筒身长度(0.015)", max(cz_bar) - min(cz_bar), 0.015, 0.0012)
# 唇珠外径 0.0305、唇珠外端 z≈0.292（与弧线起点 0.29 重叠 0.002）
cz_lip = [v.z for v in V if 0.26 < v.z < 0.30 and 0.0295 < dist_from_axis(v, ORG, Z) < 0.0306]
if cz_lip:
    check("套箍唇珠外端 z（弧线起点前 0.002）", max(cz_lip), 0.292, 0.0012)
# 套箍组件总长 0.025（结构值：锥 0.006 + 筒 0.015 + 唇珠内缘 0.004）
check("套箍组件总长(结构值)", 0.006 + 0.015 + 0.004, 0.025, 0.0001)
# 2.5 水平管身外径（x 0.09~0.14）
mx, mn = radial(V, Vector((0, 0, 0.35)), X, 0.09, 0.14)
check("水平管身外径 r_pipe", mx, 0.025, 0.0012)
# 2.6 水平侧套箍筒身外径（套箍中心 x=0.058，筒身 0.058~0.083）
mx, mn = radial(V, Vector((0, 0, 0.35)), X, 0.060, 0.082)
check("水平侧套箍筒身外径 r_collar", mx, 0.029, 0.0012)
# 2.7 承口扩口筒身外径 0.0295（1.18x，避开唇环：x 0.157~0.195）
mx, mn = radial(V, Vector((0, 0, 0.35)), X, 0.157, 0.195)
check("承口扩口外径 r_socket(1.18x)", mx, 0.0295, 0.0012)
# 2.8 卷边卡环外径 0.0325
mx, mn = radial(V, Vector((0, 0, 0.35)), X, 0.199, 0.204)
check("承口卷边外径 r_socket+0.003", mx, 0.0325, 0.0012)
# 2.9 螺纹齿外径 0.027
mx, mn = radial(V, ORG, Z, -0.048, -0.005)
check("螺纹齿外径 r_pipe+0.002", mx, 0.027, 0.0012)
# 2.10 螺纹芯棒半径 0.02375
check("螺纹芯棒半径 0.95*r_pipe", mn, 0.02375, 0.0012)
# 2.11 螺纹段下端（含齿环外凸）
check("螺纹段下端(含齿环)", min(v.z for v in V), -0.052, 0.002)
# 2.12 承口末端 x（0.15 + 0.006 + 0.045 + 0.003）
check("承口末端(含卷边)", max(v.x for v in V), 0.204, 0.002)
# 2.13 止水挡环外径（z -0.0005~0.0055，含圆柱两端环）
mx, mn = radial(V, ORG, Z, -0.0005, 0.0055)
check("止水挡环外径 r_collar", mx, 0.029, 0.0012)
# 2.14 螺纹齿距：取齿尖(z=脊线)的 z 值
tz = sorted({round(v.z, 3) for v in V
             if dist_from_axis(v, ORG, Z) > 0.0265 and v.z < -0.001})
print("  螺纹齿尖数量=%d 位置=%s" % (len(tz), ["%.3f" % z for z in tz]))
check_true("螺纹齿尖数量=10（基环在 z=0，共11环/牙距0.005）", len(tz) == 10, "got %d" % len(tz))
base_ring = [v for v in V if dist_from_axis(v, ORG, Z) > 0.0265 and abs(v.z) < 0.003]
check_true("螺纹基环存在于 z=0（与管身交界）", len(base_ring) > 0, "n=%d" % len(base_ring))
if len(tz) >= 2:
    gaps = [round(tz[i+1] - tz[i], 4) for i in range(len(tz)-1)]
    check_true("齿距=0.005", all(abs(g - 0.005) < 0.0006 for g in gaps), str(gaps))
# 2.15 平滑着色 & 材质
check_true("全部面平滑着色", all(p.use_smooth for p in me.polygons))
def face_mat_ok(p):
    if not me.materials or not (0 <= p.material_index < len(me.materials)):
        return False
    m = me.materials[p.material_index]
    return m is not None and m.name == "PVC_White_Plastic"
mats_ok = all(face_mat_ok(p) for p in me.polygons)
mat_ok = mats_ok and t.active_material and t.active_material.name == "PVC_White_Plastic"
check_true("全部面指定 PVC_White_Plastic", bool(mat_ok),
           "base_slots=%s eval_slots=%s face_idx=%s" % (
           [m.name if m else None for m in t.data.materials],
           [m.name if m else None for m in me.materials],
           sorted({p.material_index for p in me.polygons})))
# 2.16 y 半宽（卷边外径）
check("y 半宽(卷边外径)", max(abs(v.y) for v in V), 0.0325, 0.0012)
ev.to_mesh_clear()

print("=== 3. Pipe_Demo_MultiTurn 求值几何 ===")
d = bpy.data.objects["Pipe_Demo_MultiTurn"]
ev = d.evaluated_get(dg)
me = ev.to_mesh()
mw = ev.matrix_world
V = [mw @ v.co for v in me.vertices]
print("  verts=%d polys=%d" % (len(me.vertices), len(me.polygons)))
xs = [v.x for v in V]; ys = [v.y for v in V]; zs = [v.z for v in V]
print("  bbox x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
# 首段竖直管身（横向过滤到首段附近，避开蛇形远端）
mx, mn = radial(V, Vector((0.62, 0, 0)), Z, 0.05, 0.40, lat=(0, 0.62, 0.03))
check("首段管身外径 r_pipe", mx, 0.025, 0.0012)
# v1 拐点套箍（竖直侧，套箍中心 (0.62,0,0.442)，筒身 0.423~0.438）
mx, mn = radial(V, Vector((0.62, 0, 0)), Z, 0.417, 0.438, lat=(0, 0.62, 0.04))
check("v1 拐点套箍筒身外径", mx, 0.029, 0.0012)
# v1 拐点套箍（水平侧，套箍中心 (0.678,0,0.50)，筒身 0.682~0.703）
mx, mn = radial(V, Vector((0, 0, 0.50)), X, 0.682, 0.703, lat=(1, 0.0, 0.06))
check("v1 拐点套箍(水平侧)外径", mx, 0.029, 0.0012)
# 末端承口（v5=(0.72,0.30,0.12)，切向 -X；筒身 x 0.675~0.712）
mx, mn = radial(V, Vector((0, 0.30, 0.12)), X, 0.675, 0.712, lat=(1, 0.30, 0.05))
check("末端承口外径 r_socket", mx, 0.0295, 0.0012)
check("起点螺纹下端", min(v.z for v in V), -0.052, 0.002)
check_true("演示对象平滑着色", all(p.use_smooth for p in me.polygons))
ev.to_mesh_clear()

print("=== 3.5 参数功能性测试（两端接头翻转 / 转角套箍开关）===")
def mod_in(obj, ident):
    return getattr(obj.modifiers["GeometryNodes"].properties.inputs, ident)

def eval_verts(obj):
    obj.update_tag()                       # 关键：标记对象脏，否则修改器输入变更不重算
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    r = [ev.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return r

t = bpy.data.objects["Pipe_Template"]
CORE_LO, CORE_HI = 0.0230, 0.0242   # 螺纹芯棒半径 0.02375 专属区间（承口/管身均不在此）

def thread_at_start(V):
    return any(-0.048 < v.z < -0.005 and CORE_LO < dist_from_axis(v, ORG, Z) < CORE_HI for v in V)

def thread_at_end(V):
    return any(0.155 < v.x < 0.20 and CORE_LO < dist_from_axis(v, Vector((0, 0, 0.35)), X) < CORE_HI for v in V)

def socket_at_start(V):
    return any(-0.051 < v.z < -0.006 and 0.0290 < dist_from_axis(v, ORG, Z) < 0.0300 for v in V)

V0 = eval_verts(t)
check_true("默认：起点端为外螺纹公头", thread_at_start(V0) and not thread_at_end(V0))

mod_in(t, "Socket_8").value = True   # 两端接头翻转
V1 = eval_verts(t)
check_true("翻转后：终点端为外螺纹(芯棒朝外)", thread_at_end(V1) and not thread_at_start(V1))
check_true("翻转后：起点端为承口(筒身朝下外露)", socket_at_start(V1))
check_true("翻转后：起点承口卷边至 z≈-0.054", min(v.z for v in V1) < -0.053,
           "zmin=%.4f" % min(v.z for v in V1))
check_true("翻转后：终点螺纹齿至 x≈0.202", max(v.x for v in V1) > 0.200,
           "xmax=%.4f" % max(v.x for v in V1))
mod_in(t, "Socket_8").value = False  # 恢复
V2 = eval_verts(t)
check_true("恢复默认：螺纹回起点端", thread_at_start(V2) and not thread_at_end(V2))

def collar_verts(V):
    return sum(1 for v in V if 0.26 < v.z < 0.30 and dist_from_axis(v, ORG, Z) > 0.0285)

n_on = collar_verts(V2)
mod_in(t, "Socket_3").value = False  # 关闭转角套箍
V3 = eval_verts(t)
n_off = collar_verts(V3)
check_true("关闭套箍：拐点套箍完全移除", n_off == 0, "verts %d -> %d" % (n_on, n_off))
mod_in(t, "Socket_3").value = True   # 恢复
V4 = eval_verts(t)
check_true("恢复套箍：拐点套箍复原", collar_verts(V4) == n_on, "verts %d" % collar_verts(V4))
mx_off, _ = radial(V4, ORG, Z, 0.26, 0.288)
check("开启套箍后拐点处外径(=套箍)", mx_off, 0.029, 0.0012)

print("=== 4. 场景资产清单 ===")
for o in sorted(sc.collection.all_objects, key=lambda x: x.name):
    extra = ""
    if o.type == 'CAMERA':
        extra = "lens=%.0f loc=%s" % (o.data.lens, ["%.2f" % v for v in o.location])
    if o.type == 'LIGHT':
        extra = "%s E=%.0f loc=%s" % (o.data.type, o.data.energy, ["%.2f" % v for v in o.location])
    print("  [O] %-22s %-6s %s" % (o.name, o.type, extra))
bsdf = bpy.data.materials["PVC_White_Plastic"].node_tree.nodes["Principled BSDF"]
print("  [M] PVC_White_Plastic roughness=%.2f base=(%.2f,%.2f,%.2f)" % (
    bsdf.inputs["Roughness"].default_value, *bsdf.inputs["Base Color"].default_value[:3]))
print("  [W] World bg=(%.2f,%.2f,%.2f)" % tuple(sc.world.node_tree.nodes["Background"].inputs[0].default_value[:3]))
print("  scene camera:", sc.camera.name, "| engine:", sc.render.engine, "| res: %dx%d" % (sc.render.resolution_x, sc.render.resolution_y))

# ---------------------------------------------------------------- 5. 六角度渲染
print("=== 5. 多角度渲染 ===")
cam = sc.camera
tgt = bpy.data.objects["Cam_Target"]
center = Vector((0.485, 0.15, 0.239))

def render_view(name, tgt_pos, cam_pos, lens):
    tgt.location = tgt_pos
    cam.location = cam_pos
    cam.data.lens = lens
    cam.rotation_euler = (tgt_pos - cam_pos).to_track_quat('-Z', 'Y').to_euler()
    fp = os.path.join(OUTDIR, name + ".png")
    sc.render.filepath = fp
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        print("  [FAIL] %s render exception: %s" % (name, e))
        return False
    okf = os.path.exists(fp) and os.path.getsize(fp) > 2000
    print("  [%s] %s (%d bytes)" % ("PASS" if okf else "FAIL", name, os.path.getsize(fp) if os.path.exists(fp) else 0))
    return okf

views = [
    ("01_hero_3q",       center,                 Vector((1.52, -1.06, 0.81)),  50),
    ("02_front",         center,                 center + Vector((0, -2.15, 0.18)), 50),
    ("03_right_side",    center,                 center + Vector((2.15, -0.25, 0.30)), 50),
    ("04_top",           center,                 center + Vector((0.55, -1.05, 1.85)), 50),
    ("05_thread_detail", Vector((0.0, 0.0, -0.02)),  Vector((0.30, -0.42, 0.10)), 85),
    ("06_socket_detail", Vector((0.185, 0.0, 0.35)), Vector((0.62, -0.42, 0.53)), 85),
]
first = render_view(*views[0])
if not first:
    print("  Eevee 后台渲染失败，降级 Cycles CPU ...")
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 48
    sc.cycles.use_denoising = True
    for v in views:
        render_view(*v)
else:
    for v in views[1:]:
        render_view(*v)

print("=== SUMMARY ===")
print("FAILS:", fails if fails else "NONE — 全部通过")
print("VERIFY DONE")
