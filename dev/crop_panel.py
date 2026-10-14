# -*- coding: utf-8 -*-
"""把整窗截图裁成 N 面板区域，供 ui_workbench 镜像视图使用。

纯 PIL，不进 Blender。

用法：
    python dev/crop_panel.py <src.png> <dst.png> [--scale N] [--no-auto-bottom]
    python dev/crop_panel.py <src.png> <dst.png> --box X0 Y0 X1 Y1   # 换机器时重测

------------------------------------------------------------------------
裁切几何是**本机实测写死**的，不是照抄文档旧值（brief Step 3 要求写死进脚本）。

测法与推导（Blender 5.2.1 LTS / factory startup 默认主题 / 3840x2054 窗口）：

1. 侧栏 region 来自 capture_shots.py 日志里的真实值
   `| region x=2733 y=183 w=420 h=1756`（Blender 坐标，原点在窗口左下）。
2. 截图是整窗像素，与 Blender 区域坐标 1:1（area.x+area.width = 3153，
   右侧 687px 是 Properties 编辑器；region 右边界 3153 正好对齐），
   所以只有 y 要翻转：y_img = 截图高 - (y + h)。
   → REGION_BOX = (2733, 2054-(183+1756), 3153, 2054-183) = (2733,115,3153,1871)
3. 已用该几何裁出的 idle.png 做过像素级核对：面板左边框正好落在 x=0，
   盒顶正好落在 y=0。

面板盒底边再自动收一次：region 高度 1756 是整个侧栏，面板盒只占顶部一小段，
下面全是 3D 视图网格，留着会让镜像视图里 7 张图大半是空的。

判据用面板盒左侧内边距那一列（x0+9）：从盒顶到盒底它恒为 (60,60,60)
（factory startup 默认主题的 panel 底色），盒一结束就变回侧栏底色
(63,63,63)。取该列最后一个 (60,60,60) 的行再加 PAD 像素留出底边框。
这一列是纯背景，不会被按钮/文本的像素打断——用"整行占面板底色比例"
去数行会被宽按钮行打断，把发送按钮裁掉半只（第一版就是这么翻车的）。

换 Blender 版本 / 换主题时 PANEL_BG 与 REGION_BOX 都要重测：
先看 capture_shots.py 日志的 region 值算 REGION_BOX，再按本文件头部的
判据说明重测 PANEL_BG。
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("NO_PIL")
    sys.exit(2)

# 本机实测值，推导过程见本文件头部
REGION_BOX = (2733, 115, 3153, 1871)
SHOT_SIZE = (3840, 2054)   # 预期整窗截图尺寸，不符就说明换机器/换配置了

PANEL_BG = (60, 60, 60)    # 面板盒左侧内边距列的底色（factory startup 主题）
PROBE_DX = 9                # 探测列：盒左边框往里 9px，避开抗锯齿边
PAD = 8                     # 底边框 + 投影


def detect_bottom(im, probe_x):
    """返回面板盒底边（含 PAD）的行号。找不到就返回 None。"""
    px = im.load()
    x = min(max(0, probe_x), im.width - 1)
    last = -1
    for y in range(im.height):
        if px[x, y] == PANEL_BG:
            last = y
    return None if last < 0 else min(im.height, last + 1 + PAD)


def crop(src, dst, box=None, scale=1, auto_bottom=True):
    """裁一张图并落盘；几何或检测结果不合理时报错退出，不产出安静错误的图。"""
    box = tuple(box or REGION_BOX)
    im = Image.open(src).convert("RGB")

    if (im.width, im.height) != SHOT_SIZE:
        print("CROP_BAD %s 截图 %dx%d 与实测 %dx%d 不符：换机器/换窗口了？"
              " 确认后用 --box 重测" % (src, im.width, im.height,
                                     SHOT_SIZE[0], SHOT_SIZE[1]))
        sys.exit(3)

    cx0, cy0, cx1, cy1 = (max(0, box[0]), max(0, box[1]),
                          min(im.width, box[2]), min(im.height, box[3]))
    if not (0 <= cx0 < cx1 <= im.width and 0 <= cy0 < cy1 <= im.height):
        print("CROP_BAD %s 几何 %s 越界，图像只有 %dx%d"
              % (src, box, im.width, im.height))
        sys.exit(3)

    out = im.crop((cx0, cy0, cx1, cy1))
    height = out.height
    if auto_bottom:
        bottom = detect_bottom(out, PROBE_DX)
        if bottom is None:
            print("CROP_BAD %s 探测列 x=%d 整列都不是面板底色 %s，"
                  "换主题了？换主题后要重测 PANEL_BG" % (src, PROBE_DX, PANEL_BG))
            sys.exit(3)
        # 校验：盒底必须落在 region 之内，且不能顶到 region 底（顶满说明
        # 探测列整段都是底色，几何或主题多半错了）。抄错几何要立刻炸，
        # 不能悄悄裁出一张看着没事的图。
        if not (0 < bottom < height):
            print("CROP_BAD %s 检测底部 %d 不在 (0, %d) 内，几何或主题不对"
                  % (src, bottom, height))
            sys.exit(3)
        out = out.crop((0, 0, out.width, bottom))
        height = bottom

    if scale > 1:
        out = out.resize((out.width * scale, out.height * scale), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    out.save(dst)
    print("CROP_OK %s -> %s region_box=%s out=%s"
          % (src, dst, (cx0, cy0, cx1, cy1), out.size))
    return out.size


def parse_args(argv):
    src = dst = None
    scale = 1
    auto_bottom = True
    box = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--scale":
            scale = int(argv[i + 1]); i += 2
        elif a == "--no-auto-bottom":
            auto_bottom = False; i += 1
        elif a == "--box":
            box = tuple(int(v) for v in argv[i + 1:i + 5]); i += 5
        else:
            rest.append(a); i += 1
    if len(rest) < 2:
        print(__doc__)
        sys.exit(2)
    src, dst = rest[0], rest[1]
    return src, dst, box, scale, auto_bottom


if __name__ == "__main__":
    _src, _dst, _box, _scale, _auto = parse_args(sys.argv[1:])
    crop(_src, _dst, box=_box, scale=_scale, auto_bottom=_auto)