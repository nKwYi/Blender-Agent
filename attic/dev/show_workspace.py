"""启动 GUI 并打开自绘工作台，用来验证 look/workspace 这条路是否真的能出画面。

用法：blender.exe -P dev/show_workspace.py
"""
import bpy

from bl_ext.user_default.blender_deepseek_agent import runtime, workspace  # noqa: E402

try:
    runtime.uninstall()
    print("WS old GPU layer uninstalled")
except Exception as error:
    print("WS uninstall skipped", type(error).__name__, error)

window = bpy.context.window_manager.windows[0]
context = bpy.context
try:
    result = workspace.open_workspace(context)
    print("WS open_workspace ->", result)
except Exception as error:
    print("WS OPEN_FAILED", type(error).__name__, error)

area = next((a for a in window.screen.areas if a.type == 'INFO'), None)
if area:
    r = next((x for x in area.regions if x.type == 'WINDOW'), None)
    print("WS info area regions: %dx%d ui=%s" % (r.width if r else 0, r.height if r else 0,
                                                 [x.type for x in area.regions]))
import os
print("WS_PID=%d" % os.getpid())
print("WS_READY")
