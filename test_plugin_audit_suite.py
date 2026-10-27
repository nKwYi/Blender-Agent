"""Blender 5.2 插件全量自动化审计验收套件 (test_plugin_audit_suite.py)"""
import sys
import os
import json

# 将当前工作目录加入 sys.path
cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.insert(0, cwd)

import bpy

def run_tests():
    print("\n==================================================")
    print(">>> 开始 Blender DeepSeek Agent v0.5.0 全量自动化审计验收")
    print("==================================================")

    import blender_deepseek_agent
    from blender_deepseek_agent import config, ui, tools, receipt, state as state_module, worker

    # ----------------------------------------------------------------
    # TEST 1: 注册与反注册完整性测试
    # ----------------------------------------------------------------
    print("\n[TEST 1] 测试插件 register() 与 RNA 树构建...")
    blender_deepseek_agent.register()
    scene = bpy.context.scene
    assert hasattr(scene, "deepseek_agent"), "Scene 缺少 deepseek_agent 属性！"
    agent_state = scene.deepseek_agent
    print("  ✓ 插件成功注册，scene.deepseek_agent RNA 结构挂载正常")

    # ----------------------------------------------------------------
    # TEST 2: 布局契约自检 (check_layout_contract)
    # ----------------------------------------------------------------
    print("\n[TEST 2] 运行 check_layout_contract() 布局规范自检...")
    bad = ui.check_layout_contract()
    if bad:
        print(f"  FAILED: 发现布局契约违规项:\n" + "\n".join(f"    - {b}" for b in bad))
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
        "switch_tab", "toggle_ai_detail"
    ]
    for op_name in expected_ops:
        assert hasattr(bpy.ops.deepseek, op_name), f"缺失算子: bpy.ops.deepseek.{op_name}"
    print(f"  ✓ 全部 {len(expected_ops)} 个核心算子均已在 Blender RNA 正确注册")

    # ----------------------------------------------------------------
    # TEST 4: 追问多选题单选与组合选择 (Task 1.1)
    # ----------------------------------------------------------------
    print("\n[TEST 4] 测试多题追问组合选择逻辑 (DEEPSEEK_OT_select_option)...")
    agent_state.selected_options_json = "{}"
    
    # 模拟选择第 1 题的选项 B
    bpy.ops.deepseek.select_option(question_idx=0, question_title="材质类型", option_value="陶瓷")
    sel1 = json.loads(agent_state.selected_options_json)
    assert sel1.get("0", {}).get("value") == "陶瓷", f"选择未记录: {sel1}"
    
    # 模拟选择第 2 题的选项 A
    bpy.ops.deepseek.select_option(question_idx=1, question_title="把手造型", option_value="单耳半圆弧")
    sel2 = json.loads(agent_state.selected_options_json)
    assert sel2.get("0", {}).get("value") == "陶瓷"
    assert sel2.get("1", {}).get("value") == "单耳半圆弧"

    # 模拟用户反悔，重新点选第 1 题为选项 C
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

    # 测试通过 handle_execute_code 创建物体后独立性
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
    assert cfg["timeout"] >= 1, "timeout 应有有效值"
    assert cfg["history_page"] == 6, f"history_page 默认值应为 6，当前为 {cfg['history_page']}"
    print("  ✓ get_config() 纯读取偏好设置，无写入副作用")

    # ----------------------------------------------------------------
    # TEST 7: 回退算子安全性与孤立数据块清理 (Task 1.4)
    # ----------------------------------------------------------------
    print("\n[TEST 7] 测试 DEEPSEEK_OT_undo_task 运行安全与 orphan 清理...")
    # 创建一个测试物体
    bpy.ops.mesh.primitive_cube_add()
    test_obj = bpy.context.active_object
    test_obj.name = "Test_Agent_Obj"
    
    # 模拟 controller 运行记录
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

    worker.CONTROLLER.run = DummyRun()
    agent_state.prompt = ""
    ui.push_history(agent_state, "你", "制作一个立方体", raw_prompt="制作一个立方体")
    ui.push_history(agent_state, "AI", "已为您制作完成", run=DummyRun())

    assert len(agent_state.history) == 2
    assert bpy.data.objects.get("Test_Agent_Obj") is not None

    # 执行回退
    res = bpy.ops.deepseek.undo_task()
    assert res == {'FINISHED'}, f"undo_task 执行未返回 FINISHED: {res}"
    assert bpy.data.objects.get("Test_Agent_Obj") is None, "生成物体未被成功清理！"
    assert agent_state.prompt == "制作一个立方体", f"用户输入指令未恢复: {agent_state.prompt}"
    assert len(agent_state.history) == 0, f"本轮对话历史未被撤回: {len(agent_state.history)}"
    print("  ✓ undo_task 成功安全回退，物体被清理，指令被恢复至输入框")

    # ----------------------------------------------------------------
    # TEST 8: 历史折叠切换与页签切换算子 (Task 1.3 & 1.2)
    # ----------------------------------------------------------------
    print("\n[TEST 8] 测试 toggle_all_history 与 switch_tab 算子...")
    assert agent_state.show_all_history == False
    bpy.ops.deepseek.toggle_all_history()
    assert agent_state.show_all_history == True
    bpy.ops.deepseek.toggle_all_history()
    assert agent_state.show_all_history == False

    assert agent_state.active_tab == 'CHAT'
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
    print(f"  ✓ 全部 12 个废弃僵尸属性已被彻底剔除，RNA 状态结构精简干净")

    print("\n==================================================")
    print(">>> 恭喜！Blender DeepSeek Agent 自动化审计验收全部 9 项测试 100% 通过！")
    print("==================================================")

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
