# -*- coding: utf-8 -*-
"""裁剪 N 面板区域并放大，便于逐字核对渲染文案。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

try:
    from PIL import Image
except ImportError:
    print("NO_PIL")
    sys.exit(2)

src_name = sys.argv[1]
x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6])
scale = int(sys.argv[6]) if len(sys.argv) > 6 else 2
dst_name = sys.argv[7] if len(sys.argv) > 7 else f"crop_{src_name}"

im = Image.open(os.path.join(OUT, src_name))
im = im.crop((x0, y0, x1, y1))
im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
dst = os.path.join(OUT, dst_name + ".png")
im.save(dst)
print("saved", dst, im.size)