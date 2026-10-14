# -*- coding: utf-8 -*-
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# _CONFIRM_HEADER 已在 GPU 自绘改造中作为死代码删除（原生 UILayout 专用）。
# 本探针只保留仍然活着的 parse_interactive_options 契约检查。
from blender_deepseek_agent.ui import parse_interactive_options

TXT = "需求复述确认：\n✔ 杯型 直筒\n回复这几点。"
r = parse_interactive_options(TXT)
for k in ("intro", "general", "confirm", "outro"):
    print(k, "=", r.get(k))