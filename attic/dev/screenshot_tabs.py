"""GUI 自动化截图脚本：覆盖空闲、运行中、做到一半(中性两栏)、做完了、详情、设置各状态。

用法：blender.exe -P dev/screenshot_tabs.py
"""
import os
import sys
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

try:
    import blender_deepseek_agent as bda
    from blender_deepseek_agent import worker as wk
    from blender_deepseek_agent.state import Err, Phase, Run, ToolCall
    from blender_deepseek_agent.receipt import Receipt
except Exception as e:
    print("FATAL_IMPORT_ERROR:", e)
    bpy.ops.wm.quit_blender()
    raise

# 确保扩展已注册
bda.register()

state = bpy.context.scene.deepseek_agent
# 模拟已配置 Key
bda.config.get_config = lambda: {
    "api_key": "sk-real-mock-123456",
    "key_source": "prefs",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 20,
    "max_turns": 4,
    "wall_budget": 45,
    "allow_arbitrary_code": False,
    "history_page": 3,
}

step = {"idx": 0}
steps = []


def snap(name):
    path = os.path.join(OUT, f"{name}.png")
    win = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=path)
    print("SAVED_SCREENSHOT", name, path, os.path.exists(path))


def init_viewport():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                        space.overlay.show_overlays = False
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                ui_region = next((r for r in area.regions if r.type == 'UI'), None)
                if region and (ui_region is None or ui_region.width <= 1):
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.screen.region_toggle(region_type='UI')
                area.tag_redraw()


def step_0_prepare():
    init_viewport()
    return 0.5


def step_1_idle():
    # 1. 空闲态【AI 对话】：只有状态、指令输入、执行按钮、新任务
    bda.ui.DEEPSEEK_PT_chat.bl_category = "Item"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)
    
    wk.CONTROLLER.run = None
    state.settled_phase = Phase.READY.value
    state.settled_err = ""
    state.prompt = "创建一个红色立方体，移到 (2,0,0)"
    bda.ui._tag(bpy.context)
    snap("gui_1_chat_idle")
    return 0.4


def step_2_running():
    # 2. 运行中态【AI 对话】："正在改你的场景 · 第 1 步"
    run = Run("创建一个红色立方体，移到 (2,0,0)")
    run.phase = Phase.TOOL_RUNNING
    run.calls = [ToolCall("1", "create_primitive", {"type": "cube", "name": "RealCube"})]
    wk.CONTROLLER.run = run
    bda.ui._tag(bpy.context)
    snap("gui_2_chat_running")
    return 0.4


def step_3_completed():
    # 3. 完成态【AI 对话】："做完了" + 变更结果
    run = Run("创建一个红色立方体，移到 (2,0,0)")
    run.phase = Phase.COMPLETED
    run.calls = [
        ToolCall("1", "create_primitive", {"type": "cube", "name": "RealCube"}),
        ToolCall("2", "transform_object", {"object_name": "RealCube", "location": [2, 0, 0]}),
    ]
    run.receipt = Receipt()
    run.receipt.lines = ["创建了 RealCube", "移动到 (2.0, 0.0, 0.0)"]
    run.receipt.boundary_pushed = True
    run.receipt.undo_enabled = True
    wk.CONTROLLER.run = run
    bda.ui._tag(bpy.context)
    snap("gui_3_chat_completed")
    return 0.4


def step_4_partial():
    # 4. 部分完成【AI 对话】："做到一半，已停下"（中性两栏，不标红）
    run = Run("创建一个红色立方体，移到 (2,0,0)")
    run.phase = Phase.PARTIAL
    run.err = Err.BUDGET_ROUNDS
    run.calls = [ToolCall("1", "create_primitive", {"type": "cube", "name": "RealCube"})]
    run.receipt = Receipt()
    run.receipt.lines = ["建了 RealCube"]
    run.receipt.boundary_pushed = True
    run.receipt.undo_enabled = True
    run.skipped = ["移动到 (2, 0, 0)"]
    wk.CONTROLLER.run = run
    bda.ui._tag(bpy.context)
    snap("gui_4_chat_partial")
    return 0.4


def step_5_detail():
    # 5. 【详情】Tab：工具逐步记录 + 本次用量 + 导出
    bda.ui.DEEPSEEK_PT_chat.bl_category = "AI 对话"
    bda.ui.DEEPSEEK_PT_detail.bl_category = "Item"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_detail)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_detail)
    
    run = Run("复杂任务详情")
    c1 = ToolCall("1", "create_primitive", {"type": "cube", "name": "RedCube"})
    c1.result = {"object_name": "RedCube", "size": 1.0}
    c2 = ToolCall("2", "set_material", {"object_name": "RedCube", "color": [1, 0, 0]})
    c2.result = {"material": "Material_Red", "base_color": [1, 0, 0, 1]}
    run.calls = [c1, c2]
    run.usage = {"prompt_tokens": 420, "completion_tokens": 150}
    run.rounds = 2
    run.limit = 4
    run.elapsed = 3.5
    wk.CONTROLLER.run = run
    bda.ui._tag(bpy.context)
    snap("gui_5_detail")
    return 0.4


def step_6_settings():
    # 6. 【设置】Tab：Key 状态、参数调节
    bda.ui.DEEPSEEK_PT_detail.bl_category = "详情"
    bda.ui.DEEPSEEK_PT_settings.bl_category = "Item"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_detail)
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_settings)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_detail)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_settings)
    
    bda.ui._tag(bpy.context)
    snap("gui_6_settings")
    return 0.4


def step_7_finish():
    # 恢复原类 bl_category
    bda.ui.DEEPSEEK_PT_chat.bl_category = "AI 对话"
    bda.ui.DEEPSEEK_PT_detail.bl_category = "详情"
    bda.ui.DEEPSEEK_PT_settings.bl_category = "设置"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_settings)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_settings)
    print("ALL_GUI_CAPTURES_COMPLETED")
    bpy.ops.wm.quit_blender()
    return None


steps.extend([
    step_0_prepare,
    step_1_idle,
    step_2_running,
    step_3_completed,
    step_4_partial,
    step_5_detail,
    step_6_settings,
    step_7_finish,
])


def runner():
    try:
        idx = step["idx"]
        if idx >= len(steps):
            return None
        fn = steps[idx]
        delay = fn()
        step["idx"] += 1
        return delay or 0.1
    except Exception as e:
        print("RUNNER_EXCEPTION:", e)
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(runner, first_interval=1.2)
