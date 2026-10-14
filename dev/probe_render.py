"""钉死两件事：无头 EEVEE 到底渲染不渲染几何体；无头 timers 到底跑不跑。

用法：blender.exe --background --factory-startup -P dev/probe_render.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

sc = bpy.context.scene
print("R engine", sc.render.engine, "| available", [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items])
print("R objects", [o.name for o in sc.objects], "| camera", sc.camera.name if sc.camera else None)
sc.render.resolution_x = 160
sc.render.resolution_y = 100
sc.render.film_transparent = False


def shot(tag, path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    px = list(img.pixels)
    n = len(px) // 4
    rgb = [px[i * 4 + c] for i in range(n) for c in range(3)]
    mean = sum(rgb) / len(rgb)
    print(f"R {tag}: file={os.path.exists(path)} size={img.size[0]}x{img.size[1]} "
          f"mean={mean:.4f} min={min(rgb):.3f} max={max(rgb):.3f} distinct={len({round(v, 2) for v in rgb})}")
    bpy.data.images.remove(img)
    return mean


m_all = shot("with_geometry", os.path.join(OUT, "r_all.png"))
hidden = [o for o in sc.objects]
for o in hidden:
    o.hide_render = True
m_empty = shot("all_hidden", os.path.join(OUT, "r_empty.png"))
for o in hidden:
    o.hide_render = False
print("R geometry_changes_pixels", abs(m_all - m_empty) > 0.01, f"(delta={m_all - m_empty:.4f})")

# render.opengl 的正确调用姿势（filepath 不是它的参数）
try:
    r = bpy.ops.render.opengl(write_still=True)
    print("R render_opengl", r)
except Exception as e:
    print("R render_opengl RAISES", type(e).__name__, str(e)[:120])

# 无头 timers 到底跑不跑
fired = {"n": 0}


def tick():
    fired["n"] += 1
    return 0.05


bpy.app.timers.register(tick, first_interval=0.05)
deadline = time.time() + 3.0
while time.time() < deadline and fired["n"] == 0:
    time.sleep(0.1)
print("R headless_timer_fires", fired["n"], "| registered", bpy.app.timers.is_registered(tick))
try:
    bpy.app.timers.unregister(tick)
except Exception as e:
    print("R unregister ERR", e)
