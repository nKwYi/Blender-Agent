# -*- coding: utf-8 -*-
"""扫描截图里的判定色（品红），回答「自绘到底画没画出来」。

如果全图 0 个品红像素 -> 绘制没生效（capture 或 handler 的问题）
如果全图有品红 -> 绘制生效了，只是我裁剪的坐标猜错了
"""
import os
import sys

from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
src = sys.argv[1] if len(sys.argv) > 1 else "probe3_screen.png"
im = Image.open(os.path.join(OUT, src)).convert("RGB")
W, H = im.size
px = im.load()

hits = []
for y in range(0, H, 2):
    for x in range(0, W, 2):
        r, g, b = px[x, y]
        # 品红 = 红蓝都高、绿极低
        if r > 180 and b > 140 and g < 110:
            hits.append((x, y))

print("image %dx%d  magenta samples = %d" % (W, H, len(hits)))
if hits:
    xs = [p[0] for p in hits]
    ys = [p[1] for p in hits]
    print("bbox x %d..%d  y %d..%d" % (min(xs), max(xs), min(ys), max(ys)))
    print("first 10:", hits[:10])
else:
    print("NO MAGENTA ANYWHERE -> 自绘内容没有出现在截图中")

# 顺带扫一下蓝绿色（CUSTOM UI OK 用的是青色文字可能被混色），统计高饱和像素
sat = 0
for y in range(0, H, 4):
    for x in range(0, W, 4):
        r, g, b = px[x, y]
        if max(r, g, b) - min(r, g, b) > 120:
            sat += 1
print("high-saturation samples (every 4px):", sat)