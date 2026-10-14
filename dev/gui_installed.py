"""只负责把视口摆好（材质预览 + 展开侧栏），不注册任何东西：
面板必须来自已安装的扩展本身。

用法：blender.exe -P dev/gui_installed.py   （不要加 --factory-startup）
"""
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
lines = ["factory_startup=%s" % bpy.app.factory_startup]
lines.append("addon_enabled=%s" % ("bl_ext.user_default.blender_deepseek_agent" in [a.module for a in bpy.context.preferences.addons]))

for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
                    space.overlay.show_overlays = False
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    lines.append("sidebar=%s" % bpy.ops.screen.region_toggle(region_type='UI'))

out = os.path.join(HERE, "out")
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "gui_installed.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
for line in lines:
    print("INSTALLED " + line)
