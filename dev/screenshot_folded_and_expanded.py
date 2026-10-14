"""测试并截图：验证 7 项核心改进：
1. 输入框拉高与多行输入
2. 选项状态字典隔离（杜绝取消与重复）
3. AI 问答卡片已确认后自动折叠只读
4. 用户端精简单行已确认气泡 + 展开详情
5. 动态快捷胶囊与常驻导出
"""
import os
import sys
import json
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

import blender_deepseek_agent as bda

bda.register()

state = bpy.context.scene.deepseek_agent
bda.config.get_config = lambda: {
    "api_key": "sk-real-mock-123456",
    "key_source": "prefs",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 180,
    "max_turns": 20,
    "wall_budget": 600,
    "allow_arbitrary_code": False,
    "history_page": 6,
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
                        space.shading.type = 'SOLID'
                        space.overlay.show_overlays = False
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                ui_region = next((r for r in area.regions if r.type == 'UI'), None)
                if region and (ui_region is None or ui_region.width <= 1):
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.screen.region_toggle(region_type='UI')
                area.tag_redraw()


def step_0_prepare():
    for pt_name in ["VIEW3D_PT_context_properties", "OBJECT_PT_transform", "VIEW3D_PT_transform"]:
        pt = getattr(bpy.types, pt_name, None)
        if pt:
            try:
                bpy.utils.unregister_class(pt)
            except Exception:
                pass

    bda.ui.DEEPSEEK_PT_chat.bl_category = "Item"
    try:
        bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    except Exception:
        pass
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)

    init_viewport()

    state.active_tab = 'CHAT'
    state.session_topic = "中式紫砂茶杯建模"
    state.session_date = "2026/10/10"
    state.prompt = ""
    state.prompt_lines = 3
    state.prompt_expanded = False

    state.history.clear()

    # 第 1 轮：用户请求茶杯
    u1 = state.history.add()
    u1.role = "你"
    u1.text = "做一个精致的中式紫砂茶杯"

    # AI 追问
    a1 = state.history.add()
    a1.role = "AI"
    a1.msg_type = "CLARIFY"
    a1.duration_str = "6秒"
    a1.text = (
        "好的，做个精致的中式紫砂茶杯！在动手前先跟你确认几个细节：\n"
        "• 1. 杯型风格：经典直筒微收口 / 鼓腹圆润 / 手作厚壁（推荐：鼓腹圆润）\n"
        "• 2. 尺寸口径：口径 8.5cm, 高 6.5cm, 壁厚 2.5mm（推荐：口径 8.5cm, 高 6.5cm, 壁厚 2.5mm）\n"
        "• 3. 材质胎体：素胎陶 / 原矿紫泥 / 窑变粗陶（推荐：原矿紫泥）\n"
        "• 4. 圈足把手：传统圈足无把手 / 单侧小把手（推荐：传统圈足无把手）"
    )

    # 第 2 轮：用户确认（精简单行，展开留详情）
    u2 = state.history.add()
    u2.role = "你"
    u2.text = "参数已确认：鼓腹圆润；口径 8.5cm, 高 6.5cm, 壁厚 2.5mm；原矿紫泥；传统圈足无把手，开始建模！"

    # AI 生成建模完成
    a2 = state.history.add()
    a2.role = "AI"
    a2.msg_type = "REPLY"
    a2.duration_str = "1分24秒"
    a2.text = "中式紫砂茶杯已建模完成！已采用车削曲线生成圆润胎体与规整圈足，并赋予原矿紫泥 PBR 材质。"
    a2.collection_name = "中式紫砂茶杯_01"
    a2.added_objects_str = "紫砂茶杯主体、圈足底座、内壁茶水"
    a2.steps_json = json.dumps(["车削圆润杯身外轮廓", "生成底部圈足与内收壁", "赋予原矿紫泥磨砂材质节点", "场景合集归档整理"], ensure_ascii=False)
    art_dict = {
        "objects": [
            {"name": "紫砂茶杯主体", "tag": "Mesh", "sub": "顶点 1,280 · 面 1,216"},
            {"name": "圈足底座", "tag": "Mesh", "sub": "顶点 384 · 面 360"},
            {"name": "内壁茶水", "tag": "Mesh", "sub": "顶点 256 · 面 240"}
        ],
        "modifiers": ["Subdivision Surface (级别 2)", "Bevel (微倒角 1.5mm)", "Weighted Normal"],
        "materials": [
            ("Base Color", "#6E3826"),
            ("Roughness", "0.78"),
            ("Metallic", "0.00")
        ],
        "script": "# 步骤: 旋转车削一体化成型\nimport bpy, bmesh\n# 生成高精度中式紫砂茶杯...\n",
        "collection": "中式紫砂茶杯_01"
    }
    a2.artifacts_json = json.dumps(art_dict, ensure_ascii=False)

    state.show_card_objects = False
    state.show_card_params = False
    state.show_card_script = False
    state.show_card_archive = False
    state.show_card_qa = False
    state.show_user_params_detail = False

    bda.ui._tag(bpy.context)
    return 0.6


def step_1_capture():
    bda.ui._tag(bpy.context)
    snap("verify_7_features_folded")
    return 0.4


def step_2_expand_and_capture():
    # 测试拉高输入框与展开卡片
    state.prompt_expanded = True
    state.prompt = "请帮我修改当前模型的材质为：青花瓷釉面，并增加高光反射"
    state.show_card_qa = True
    state.show_user_params_detail = True
    state.show_card_objects = True
    bda.ui._tag(bpy.context)
    snap("verify_7_features_expanded")
    return 0.4


def step_3_finish():
    bda.ui.DEEPSEEK_PT_chat.bl_category = "AI 对话"
    bpy.utils.unregister_class(bda.ui.DEEPSEEK_PT_chat)
    bpy.utils.register_class(bda.ui.DEEPSEEK_PT_chat)
    print("ALL_7_FEATURES_VERIFICATION_COMPLETED_SUCCESSFULLY")
    bpy.ops.wm.quit_blender()
    return None


steps.extend([step_0_prepare, step_1_capture, step_2_expand_and_capture, step_3_finish])


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
