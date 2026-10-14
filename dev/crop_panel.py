# -*- coding: utf-8 -*-
"""把整窗截图裁成 N 面板区域，供 ui_workbench 镜像视图使用。

纯 PIL，不进 Blender。

裁切坐标来自 Blender 真实 region 几何（capture_shots.py 日志里的
`| region x y w h`），不是照抄文档旧值。region 坐标原点在窗口左下，
PNG 原点在左上，所以 y 要翻转：y_img = 截图高 - (y + h)。

面板盒底边再自动收一次：region 高度是整个侧栏高，面板盒只占上面一小段，
下面全是 3D 视图，留着会让镜像视图里 7 张图大半是空的网格。

判据用面板盒左侧内边距那一列（x0+9）：从盒顶到盒底它恒为 (60,60,60)
（factory startup 默认主题的 panel 底色），盒一结束就变回侧栏底色
(63,63,63)。取该列最后一个 (60,60,60) 的行再加 PAD 像素留出底边框。
这一列是纯背景，不会被按钮/文本的像素打断——用"整行占面板底色比例"
去数行会被宽按钮行打断，把发送按钮裁掉半只（第一版就是这么翻车的）。

用法：
    python dev/crop_panel.py <src.png> <x0> <y0> <x1> <y1> <scale> <dst.png> [--auto-bottom]
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("NO_PIL")
    sys.exit(2)

PANEL_BG = (60, 60, 60)  # 面板盒左侧内边距列的底色（factory startup 主题）
PROBE_DX = 9            # 探测列：盒左边框往里 9px，避开抗锯齿边
PAD = 8                 # 底边框 + 投影


def trim_bottom(im, probe_x):
    """返回裁掉面板盒以下空白后的高度。probe_x = 盒内左侧内边距那一列。"""
    px = im.load()
    x = min(max(0, probe_x), im.width - 1)
    last = -1
    for y in range(im.height):
        if px[x, y] == PANEL_BG:
            last = y
    if last < 0:  # 探测列整列都不是盒底色，别乱裁，退回整块
        return im.height
    return min(im.height, last + 1 + PAD)


def main():
    src = sys.argv[1]
    x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6])
    scale = int(sys.argv[6]) if len(sys.argv) > 6 else 1
    auto_bottom = "--auto-bottom" in sys.argv[7:]
    dst = None
    for a in sys.argv[7:]:
        if not a.startswith("--"):
            dst = a
    if dst is None:
        dst = os.path.join(os.path.dirname(src),
                           os.path.splitext(os.path.basename(src))[0] + "_panel.png")

    im = Image.open(src).convert("RGB")
    box = (max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1))
    out = im.crop(box)
    if auto_bottom:
        out = out.crop((0, 0, out.width, trim_bottom(out, PROBE_DX)))
    if scale > 1:
        out = out.resize((out.width * scale, out.height * scale), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    out.save(dst)
    print("CROP %s -> %s region_box=%s out=%s" % (src, dst, box, out.size))


if __name__ == "__main__":
    main()