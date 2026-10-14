"""GUI 验收脚手架：从源码目录直接注册，不安装、不写偏好设置、不存启动文件。

用法：blender.exe -P "E:/Three JS/Blender Agent/dev/gui_dev.py"
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402

import blender_deepseek_agent as bda  # noqa: E402

lines = []
bda.register()
lines.append(f"blender={bpy.app.version_string}")
lines.append(f"panel_registered={bda.ui.DEEPSEEK_PT_panel.is_registered}")
lines.append(f"category={bda.ui.DEEPSEEK_PT_panel.bl_category}")
lines.append(f"scene_prop={'deepseek_agent' in bpy.types.Scene.bl_rna.properties}")
lines.append(f"prompt_default={bpy.context.scene.deepseek_agent.prompt!r}")

from blender_deepseek_agent import config  # noqa: E402

cfg = config.get_config()
lines.append(f"key_configured={bool(cfg['api_key'])} source={cfg['key_source']} model={cfg['model']}")

for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
                    space.overlay.show_overlays = False
            win_region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if win_region is None:
                lines.append("找不到视口 WINDOW region")
                continue
            try:
                with bpy.context.temp_override(window=window, area=area, region=win_region):
                    state = bpy.ops.screen.region_toggle(region_type='UI')
                widths = [r.width for r in area.regions if r.type == 'UI']
                lines.append(f"region_toggle {state} UI 区域宽度={widths}")
            except Exception as error:
                lines.append(f"region_toggle 失败：{type(error).__name__}: {error}")

out = os.path.join(HERE, "out")
os.makedirs(out, exist_ok=True)


def _selftest_operator():
    """真 UI 上下文里跑一次算子，把面板状态回读进文件（无头测不到 context 相关行为）。"""
    state = bpy.context.scene.deepseek_agent
    state.prompt = "创建一个红色立方体"
    print("GUIDEV start answer=" + repr(state.answer))
    state.answer = "MANUAL-DIRECT-TEST"
    print("GUIDEV after_direct answer=" + repr(state.answer))
    try:
        result = bpy.ops.deepseek.run_prompt()
        print("GUIDEV run_prompt=" + str(result))
    except Exception as error:
        print("GUIDEV op_raised " + type(error).__name__ + ": " + str(error))
    print("GUIDEV after_op answer=" + repr(state.answer))
    with open(os.path.join(out, "operator.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            f"answer_after_op={state.answer!r}\n"
            f"trace={state.trace!r}\n"
            f"objects={sorted(o.name for o in bpy.context.scene.objects)}\n"
        )
    return None


bpy.app.timers.register(_selftest_operator, first_interval=4.0)

with open(os.path.join(out, "gui.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
for line in lines:
    print("GUIDEV " + line)
