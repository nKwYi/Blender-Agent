# -*- coding: utf-8 -*-
"""用真实模型输出回放解析器，核对选项标签是否还有半个括号 / 脏文本。"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402
import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent import ui as U  # noqa: E402

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

REAL = (
    "场景是空的，我准备用截面曲线旋转车削（Spin）一体成型杯身+内腔+卷唇+杯底，再布尔熔接把手，"
    "保证单网格无穿模。先确认几个关键规格：\n\n"
    "1. **器型风格**：直筒微收口 / 上宽下窄锥形 / 鼓腹圆润 / 带盖马克杯（推荐：直筒微收口，办公最通用）\n"
    "2. **尺寸容量**：办公室杯 350ml（口径 8.5cm × 高 9.5cm）/ 旅行随行杯 450ml（口径 7.5cm × 高 13cm）"
    "/ 马克杯 300ml（口径 8.8cm × 高 9.5cm）（推荐：350ml 直筒）\n"
    "3. **把手**：无把手直筒 / D 形实心把手（推荐：D 形）/ 带盖 + 吸管孔\n"
    "4. **材质配色**：素白瓷 / 哑光陶瓷 / 半透明磨砂玻璃 / 彩色釉面（推荐：哑光陶瓷）\n\n"
    "点选或直接回复\"全部按推荐\"，我立刻建模。"
)

r = U.parse_interactive_options(REAL)
bad = []
for q in r.get("questions", []):
    print("Q:", q.get("title"))
    for o in q.get("options", []):
        lb = o.get("label", "")
        print("   -", lb)
        for o_ch, c_ch in (("（", "）"), ("(", ")")):
            if lb.count(o_ch) != lb.count(c_ch):
                bad.append((lb, "括号不配对"))
        if lb.rstrip().endswith(("（", "(")):
            bad.append((lb, "以开括号结尾"))
        if "推荐：" in lb:
            bad.append((lb, "混入推荐说明"))
print("BROKEN_LABELS:", bad)
print("RESULT:", "PASS" if not bad else "FAIL")