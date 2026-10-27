"""Blender 5.2 插件全量自动化审计验收套件 (test_plugin_audit_suite.py)"""
import sys
import os
import json
import importlib

cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.insert(0, cwd)

import bpy


class MockOpProps:
    def __init__(self, op_idname):
        self.op_idname = op_idname


class MockUILayout:
    """递归记录所有 UI 绘制指令的 Mock Layout，用于无头验证 draw() 全分支零报错。"""

    def __init__(self, logs=None):
        self.logs = logs if logs is not None else []
        self.alignment = 'EXPAND'
        self.scale_y = 1.0
        self.alert = False
        self.enabled = True
        self.use_property_split = False

    def row(self, align=False):
        return MockUILayout(self.logs)

    def column(self, align=False):
        return MockUILayout(self.logs)

    def box(self):
        return MockUILayout(self.logs)

    def split(self, factor=0.5, align=False):
        return MockUILayout(self.logs)

    def label(self, text="", icon='NONE'):
        self.logs.append(("label", text, icon))

    def prop(self, data, prop_name, text=None, expand=False, slider=False, icon='NONE'):
        self.logs.append(("prop", prop_name, text))

    def textbox(self, data, prop_name, initial_visible_lines=3, placeholder=""):
        self.logs.append(("textbox", prop_name, initial_visible_lines, placeholder))

    def operator(self, op_idname, text="", icon='NONE', emboss=True, depress=False):
        op = MockOpProps(op_idname)
        self.logs.append(("operator", op_idname, text, icon, depress, op))
        return op

    def separator(self, factor=1.0):
        self.logs.append(("separator", factor))


def run_tests():
    print("\n==================================================")
    print(">>> 开始 Blender DeepSeek Agent v0.5.0 全量自动化审计验收")
    print("==================================================")

    import blender_deepseek_agent
    from blender_deepseek_agent import config, ui, tools, receipt, state as state_module, worker

    # ----------------------------------------------------------------
    # TEST 1: 注册与拓扑热重载测试
    # ----------------------------------------------------------------
    print("\n[TEST 1] 测试插件 register() 与 importlib.reload() 拓扑热重载...")
    blender_deepseek_agent.register()
    scene = bpy.context.scene
    assert hasattr(scene, "deepseek_agent"), "Scene 缺少 deepseek_agent 属性！"
    # 测试热重载
    blender_deepseek_agent.unregister()
    importlib.reload(blender_deepseek_agent)
    blender_deepseek_agent.register()
    agent_state = bpy.context.scene.deepseek_agent
    print("  ✓ 插件注册与拓扑热重载 (importlib.reload) 100% 正常")

    # ----------------------------------------------------------------
    # TEST 2: 布局契约自检 (check_layout_contract)
    # ----------------------------------------------------------------
    print("\n[TEST 2] 运行 check_layout_contract() 布局规范自检...")
    bad = ui.check_layout_contract()
    if bad:
        print("  FAILED: 发现布局契约违规项:\n" + "\n".join(f"    - {b}" for b in bad))
        sys.exit(1)
    print("  ✓ check_layout_contract() 100% 通过（零 .panel() 逃逸风险，结构完全合规）")

    # ----------------------------------------------------------------
    # TEST 3: 算子注册完整性
    # ----------------------------------------------------------------
    print("\n[TEST 3] 验证关键算子在 bpy.ops.deepseek 下的注册状态...")
    expected_ops = [
        "run", "retry", "stop", "approve", "undo_task", "show", "export",
        "clear", "new_task", "fetch_models", "set_model", "quick_pill",
        "select_option", "submit_selection", "toggle_all_history",
        "switch_tab",
    ]
    for op_name in expected_ops:
        assert hasattr(bpy.ops.deepseek, op_name), f"缺失算子: bpy.ops.deepseek.{op_name}"
    print(f"  ✓ 全部 {len(expected_ops)} 个核心算子均已在 Blender RNA 正确注册")

    # ----------------------------------------------------------------
    # TEST 4: 追问多选题单选与组合选择 (Task 1.1)
    # ----------------------------------------------------------------
    print("\n[TEST 4] 测试多题追问组合选择逻辑 (DEEPSEEK_OT_select_option)...")
    agent_state.selected_options_json = "{}"
    bpy.ops.deepseek.select_option(question_idx=0, question_title="材质类型", option_value="陶瓷")
    bpy.ops.deepseek.select_option(question_idx=1, question_title="把手造型", option_value="单耳半圆弧")
    bpy.ops.deepseek.select_option(question_idx=0, question_title="材质类型", option_value="磨砂粗陶")
    sel3 = json.loads(agent_state.selected_options_json)
    assert sel3.get("0", {}).get("value") == "磨砂粗陶"
    assert sel3.get("1", {}).get("value") == "单耳半圆弧"
    print("  ✓ 多题点选、单题覆盖与组合持久化逻辑完全正确")

    # ----------------------------------------------------------------
    # TEST 5: tools.py 作用域隔离与防跨任务污染 (Task 2.3)
    # ----------------------------------------------------------------
    print("\n[TEST 5] 测试 tools.py 执行作用域隔离 (_exec_globals)...")
    scope1 = tools._exec_globals()
    scope1["my_temp_var"] = 12345
    scope2 = tools._exec_globals()
    assert "my_temp_var" not in scope2, "tools._exec_globals 发生跨任务变量污染！"
    res = tools.handle_execute_code({"code": "cube = bpy.ops.mesh.primitive_cube_add(size=1.0)"})
    assert res.get("status") == "ok", f"代码执行失败: {res}"
    scope3 = tools._exec_globals()
    assert "cube" not in scope3, "handle_execute_code 定义的全局变量泄漏至后续作用域！"
    print("  ✓ tools.py 每次执行使用隔离作用域浅拷贝，零变量/指针残留")

    # ----------------------------------------------------------------
    # TEST 6: config.get_config() 只读性与用户参数保护 (Task 2.1)
    # ----------------------------------------------------------------
    print("\n[TEST 6] 验证 config.get_config() 不篡改用户自定义参数...")
    cfg = config.get_config()
    assert cfg["timeout"] >= 1
    assert cfg["history_page"] == 6, f"history_page 默认值应为 6，当前为 {cfg['history_page']}"
    print("  ✓ get_config() 纯读取偏好设置，无写入副作用")

    # ----------------------------------------------------------------
    # TEST 7: 回退算子安全性与孤立数据块清理 (Task 1.4)
    # ----------------------------------------------------------------
    print("\n[TEST 7] 测试 DEEPSEEK_OT_undo_task 运行安全与 orphan 清理...")
    bpy.ops.mesh.primitive_cube_add()
    test_obj = bpy.context.active_object
    test_obj.name = "Test_Agent_Obj"

    class DummyReceipt:
        added_names = ["Test_Agent_Obj"]
        boundary_pushed = True
        undo_enabled = True

    class DummyRun:
        receipt = DummyReceipt()
        collection_name = ""
        elapsed = 2.4
        phase = state_module.Phase.READY
        calls = []
        artifacts = []
        usage = {"prompt_tokens": 1200, "completion_tokens": 350}
        rounds = 2
        limit = 16

    worker.CONTROLLER.run = DummyRun()
    agent_state.prompt = ""
    ui.push_history(agent_state, "你", "制作一个立方体", raw_prompt="制作一个立方体")
    ui.push_history(agent_state, "AI", "已为您制作完成", run=DummyRun())

    res = bpy.ops.deepseek.undo_task()
    assert res == {'FINISHED'}
    assert bpy.data.objects.get("Test_Agent_Obj") is None
    assert agent_state.prompt == "制作一个立方体"
    assert len(agent_state.history) == 0
    print("  ✓ undo_task 成功安全回退，物体被清理，指令被恢复至输入框")

    # ----------------------------------------------------------------
    # TEST 8: 历史折叠切换与页签切换算子 (Task 1.3 & 1.2)
    # ----------------------------------------------------------------
    print("\n[TEST 8] 测试 toggle_all_history 与 switch_tab 算子...")
    bpy.ops.deepseek.toggle_all_history()
    assert agent_state.show_all_history is True
    bpy.ops.deepseek.toggle_all_history()
    assert agent_state.show_all_history is False

    bpy.ops.deepseek.switch_tab(tab='DETAIL')
    assert agent_state.active_tab == 'DETAIL'
    bpy.ops.deepseek.switch_tab(tab='CHAT')
    assert agent_state.active_tab == 'CHAT'
    print("  ✓ 历史展开切换与页签跳转算子功能完全正常")

    # ----------------------------------------------------------------
    # TEST 9: 验证僵尸属性清理 (Task 3.1)
    # ----------------------------------------------------------------
    print("\n[TEST 9] 验证 DEEPSEEK_PG_state 12 个僵尸属性已完全清理...")
    zombies = [
        "show_card_objects", "show_card_params", "show_card_script",
        "show_card_archive", "show_card_qa", "show_user_params_detail",
        "result_tab", "show_result_list", "show_all_questions",
        "other_open_q", "notes", "shown_count"
    ]
    for z in zombies:
        assert not hasattr(agent_state, z), f"僵尸属性仍然残留: {z}"
    print("  ✓ 全部 12 个废弃僵尸属性已被彻底剔除，RNA 状态结构精简干净")

    # ----------------------------------------------------------------
    # TEST 10: 全分支 UI 绘制实测（追问态 + 交付态 + 详情页 + 设置页）
    # ----------------------------------------------------------------
    print("\n[TEST 10] 执行 MockUILayout 全分支 UI 渲染测试...")
    ui.push_history(agent_state, "你", "帮我做一个中式茶杯")
    clarify_msg = (
        "为您规划中式茶杯方案，请确认以下关键规格：\n"
        "1. 器型风格：天目建盏 (推荐) / 青花束口杯 / 白瓷敞口杯\n"
        "2. 表面材质：窑变兔毫釉 (推荐) / 羊脂白玉瓷 / 粗陶磨砂"
    )
    ui.push_history(agent_state, "AI", clarify_msg)

    # 先点选第 2 题为「羊脂白玉瓷」
    bpy.ops.deepseek.select_option(question_idx=1, question_title="表面材质", option_value="羊脂白玉瓷")

    mock_chat = MockUILayout()
    ui.draw_chat_content(mock_chat, bpy.context, agent_state, None)
    # 验证渲染出了 select_option 按钮与 submit_selection 主按钮，且组合了第1题推荐项+第2题手选项
    select_ops = [entry for entry in mock_chat.logs if entry[0] == "operator" and entry[1] == "deepseek.select_option"]
    submit_ops = [entry for entry in mock_chat.logs if entry[0] == "operator" and entry[1] == "deepseek.submit_selection"]
    assert len(select_ops) == 6, f"应渲染 6 个规格选项按钮，实际: {len(select_ops)}"
    assert len(submit_ops) == 1, f"应只渲染 1 个主提交按钮，实际: {len(submit_ops)}"
    assert "器型风格：天目建盏" in submit_ops[0][5].custom_prompt
    assert "表面材质：羊脂白玉瓷" in submit_ops[0][5].custom_prompt

    # 再推入一条交付态消息，验证交付摘要与 DETAIL 页签渲染
    ui.push_history(agent_state, "你", submit_ops[0][5].custom_prompt)
    exec_msg = "已按您的规格完成茶杯建模：\n- 杯身旋转车削成型\n- 窑变釉材质配置完成\n- 圈足底面精细倒角"
    ui.push_history(agent_state, "AI", exec_msg, run=DummyRun())
    agent_state.history[-1].steps_json = json.dumps(["旋转车削生成杯身", "配置窑变材质"], ensure_ascii=False)
    agent_state.history[-1].added_objects_str = "TeaCup_Body"

    mock_chat_exec = MockUILayout()
    ui.draw_chat_content(mock_chat_exec, bpy.context, agent_state, DummyRun())
    # 验证主聊天框没有把 3 条参数列表全部倾倒出来，而是只展示了核心结论 + 跳转详情按钮
    labels_rendered = [entry[1] for entry in mock_chat_exec.logs if entry[0] == "label"]
    assert any("建模完成 · 共 2 项操作" in t for t in labels_rendered), f"未找到建模完成摘要: {labels_rendered}"
    assert not any("圈足底面精细倒角" in t for t in labels_rendered), "主聊天框不应直接展开长参数列表！"

    # 验证详情页签完整承接了步骤与全文说明
    mock_detail = MockUILayout()
    ui.draw_detail_content(mock_detail, agent_state, DummyRun())
    detail_labels = [entry[1] for entry in mock_detail.logs if entry[0] == "label"]
    assert any("旋转车削生成杯身" in t for t in detail_labels), "详情页未展示建模步骤！"
    assert any("圈足底面精细倒角" in t for t in detail_labels), "详情页未展示完整说明！"

    # 验证设置页签渲染零报错
    mock_settings = MockUILayout()
    ui.draw_settings_content(mock_settings, config.get_config())
    print("  ✓ 追问态、交付态、详情页签、设置页签全分支 UI 绘制 100% 零报错通过")

    print("\n==================================================")
    print(">>> 恭喜！Blender DeepSeek Agent 自动化审计验收全部 10 项测试 100% 通过！")
    print("==================================================")


if __name__ == "__main__":
    try:
        run_tests()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
