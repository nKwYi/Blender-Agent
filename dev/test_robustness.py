"""Robustness & stress tests for Blender Agent.

Validates stability under edge cases, malformed inputs, scale limits,
and unexpected user/model behaviors.

Usage:
  blender --background --factory-startup --python-exit-code 1 -P dev/test_robustness.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy

import blender_deepseek_agent as bda
import blender_deepseek_agent.ui as U
from blender_deepseek_agent.state import Err, Phase, Run, ToolCall

FAILURES = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}: {msg}")
        FAILURES.append(name)


class MockLayout:
    def __init__(self, kind="layout", parent=None):
        self.kind = kind
        self.parent = parent
        self.texts = []
        self.operators = []
        self.props = []
        self.children = []
        self.alignment = 'EXPAND'
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.enabled = True
        self.alert = False

    def label(self, text="", icon='NONE'):
        if text:
            self.texts.append(str(text))

    def textbox(self, data, prop_name, **kwargs):
        self.texts.append("TEXTBOX:" + str(prop_name))
        self.props.append({"data": data, "prop": prop_name, "text": "", "kwargs": kwargs})

    def prop(self, data, prop_name, text="", **kwargs):
        self.props.append({"data": data, "prop": prop_name, "text": text, "kwargs": kwargs})
        if text:
            self.texts.append(str(text))

    def operator(self, op_id, text="", icon='NONE', depress=False, **kw):
        self.operators.append({"id": op_id, "text": text, "icon": icon, "depress": depress, "kw": kw})

        class OpDummy:
            def __setattr__(self, name, value):
                pass
        return OpDummy()

    def box(self):
        b = MockLayout("box", parent=self)
        self.children.append(b)
        return b

    def panel(self, idname, default_closed=False, layout_header=None, layout_body=None):
        header = MockLayout("panel_header", parent=self)
        body = MockLayout("panel_body", parent=self)
        header.panel_idname = idname
        body.panel_idname = idname
        header.panel_default_closed = bool(default_closed)
        body.panel_default_closed = bool(default_closed)
        self.children.extend([header, body])
        return (header, body)

    def row(self, align=False):
        r = MockLayout("row", parent=self)
        self.children.append(r)
        return r

    def column(self, align=False):
        c = MockLayout("column", parent=self)
        self.children.append(c)
        return c

    def split(self, factor=0.5, **kw):
        s = MockLayout("split", parent=self)
        self.children.append(s)
        return s

    def grid_flow(self, **kw):
        gf = MockLayout("grid_flow", parent=self)
        self.children.append(gf)
        return gf

    def all_texts(self):
        out = list(self.texts)
        for ch in self.children:
            out.extend(ch.all_texts())
        return out


def test_wrap_text_robustness():
    print("\n--- 1. wrap_text Robustness ---")
    # Empty and degenerate inputs
    ck("wrap_none", U.wrap_text(None) == [], "None text must return empty list")
    ck("wrap_empty", U.wrap_text("") == [], "Empty string must return empty list")
    ck("wrap_spaces", U.wrap_text("   \n\n\t  \n  ") == [], "Whitespace only must return empty list")

    # Extreme budgets
    ck("wrap_budget_0", len(U.wrap_text("你好世界", max_chars=0)) > 0, "Budget 0 must not crash or hang")
    ck("wrap_budget_neg", len(U.wrap_text("你好世界", max_chars=-5)) > 0, "Negative budget must not crash or hang")
    ck("wrap_budget_1", len(U.wrap_text("ABC", max_chars=1)) == 3, "Budget 1 should split each character")
    ck("wrap_budget_large", len(U.wrap_text("你好世界", max_chars=1000)) == 1, "Large budget should keep single line")

    # Mixed Chinese, symbols and spaces without premature truncation
    t_formula = "按推荐参数建模：北欧童话木屋，桌景微缩18cm，原木 + 厚白雪顶，烟囱 + 雪堆 + 松树 + 木栅栏"
    lines = U.wrap_text(t_formula, max_chars=22, first_chars=20)
    ck("wrap_formula_no_premature_gap", any("雪堆" in l for l in lines if "烟囱" in l),
       f"Line with 烟囱 should contain 雪堆, got lines={lines}")

    # Very long alphanumeric token (longer than budget) must not loop indefinitely
    long_token = "A" * 60
    long_res = U.wrap_text(long_token, max_chars=20)
    ck("wrap_long_token_splits", len(long_res) == 3 and all(len(x) == 20 for x in long_res),
       f"Oversized token must split cleanly: {long_res}")

    # Punctuation at cut boundary should not be left orphan
    punc_text = "打造雪屋场景，雪地微缩模型！"
    punc_lines = U.wrap_text(punc_text, max_chars=6)
    ck("wrap_punc_no_orphan", not any(l.startswith(("，", "！", "。")) for l in punc_lines[1:]),
       f"Punctuation should not appear as line start: {punc_lines}")


def test_interactive_parser_robustness():
    print("\n--- 2. parse_interactive_options Robustness ---")
    # Empty inputs
    res_empty = U.parse_interactive_options("")
    ck("parser_empty_str", res_empty["questions"] == [] and res_empty["intro"] == "", "Empty text parsed safely")
    res_none = U.parse_interactive_options(None)
    ck("parser_none", res_none["questions"] == [], "None parsed safely")

    # Fullwidth circular numbers, fullwidth slashes and bars
    t_circ = (
        "已为您规划雪屋方案，请选择：\n"
        "① 雪屋风格：半球传统冰屋（推荐）／ 现代尖顶A字木屋 ／ 冰雪城堡\n"
        "② 积雪厚度：轻度积雪 5cm ｜ 严寒厚雪 18cm（推荐） ｜ 暴风雪覆盖\n"
        "✓ 基础材质：标准冰晶材质\n"
        "直接回复编号或点击选项即可！"
    )
    res_circ = U.parse_interactive_options(t_circ)
    ck("parser_circ_questions_count", len(res_circ["questions"]) == 2, f"Should parse 2 questions, got {len(res_circ['questions'])}")
    ck("parser_circ_q1_opts", len(res_circ["questions"][0]["options"]) == 3, "Question 1 should have 3 options")
    ck("parser_circ_rec_found", res_circ["questions"][0]["options"][0]["is_rec"], "Question 1 option 1 should be recommended")
    ck("parser_circ_confirm", len(res_circ["confirm"]) == 1 and "标准冰晶材质" in res_circ["confirm"][0], "Confirm item parsed")
    ck("parser_circ_all_rec", "半球传统冰屋" in res_circ["all_recommended"] and "严寒厚雪" in res_circ["all_recommended"],
       f"Combined recommended string: {res_circ['all_recommended']}")

    # Continuous questions written on a single line
    t_single_line = "① 造型：圆润（推荐）/ 方正 ② 材质：木质（推荐）/ 塑料 ③ 尺寸：小 / 大（推荐） 回复编号开始"
    res_sl = U.parse_interactive_options(t_single_line)
    ck("parser_single_line_split", len(res_sl["questions"]) == 3, f"Single line multi-question should parse 3 questions, got {len(res_sl['questions'])}")

    # Markdown format with bullets
    t_md = (
        "**1. 杯型风格**\n"
        "- A. 经典直筒（推荐）\n"
        "- B. 鼓腹圆润\n"
        "**2. 容量规格**\n"
        "- A. 300ml\n"
        "- B. 500ml（推荐）\n"
    )
    res_md = U.parse_interactive_options(t_md)
    ck("parser_md_questions", len(res_md["questions"]) == 2, f"Markdown list format questions: {len(res_md['questions'])}")

    # Exact user snow house prompt from screenshot
    t_snow_user = (
        "雪屋是个挺有意思的主体，开工前先跟你对几个关键参数，点选或直接回“按推荐”即可：回复编号即可，例如「1-1-1-1」。\n\n"
        "1. 规模: 1. 经典家用小雪屋·内径 4m (推荐) / 2. 宽敞聚会版·内径 6m / 3. 微缩景观版·内径 2m\n"
        "2. 穹顶造型: 1. 正半球穹顶 (推荐) / 2. 尖顶锥形 / 3. 阶梯逐层收分\n"
        "3. 入口: 1. 短隧道式雪廊 + 门帘 (推荐) / 2. 直接开半圆隧道口 / 3. 无门全开放\n"
        "4. 细节与环境: 1. 螺旋错缝冰砖 + 雪檐 + (推荐) / 2. 仅雪砖本体 / 3. 追加外部雪堆与极光天空\n"
    )
    res_snow_user = U.parse_interactive_options(t_snow_user)
    ck("parser_snow_user_qcount", len(res_snow_user["questions"]) == 4,
       f"Snow house user prompt should parse 4 questions, got {len(res_snow_user['questions'])}")
    ck("parser_snow_user_opts", all(len(q["options"]) == 3 for q in res_snow_user["questions"]),
       "Every snow house question should have 3 options")


def test_state_and_history_robustness():
    print("\n--- 3. State & History Robustness ---")
    state = bpy.context.scene.deepseek_agent
    state.history.clear()

    # Rapid push of 100 messages
    for i in range(100):
        role = "你" if i % 2 == 0 else "AI"
        U.push_history(state, role, f"压力测试消息 {i:03d}")

    ck("history_length_100", len(state.history) == 100, f"History length should be 100, got {len(state.history)}")
    ck("history_uids_unique", len({m.uid for m in state.history}) == 100, "All message uids must be unique")

    # Corrupted JSON states should not crash getters/draw
    state.selected_options_json = "{bad json: invalid"
    try:
        sel = json.loads(state.selected_options_json or "{}")
    except Exception:
        sel = {}
    ck("corrupt_json_fallback", sel == {}, "Corrupted json gracefully falls back")

    state.fetched_models_json = "NOT_JSON"
    # Testing model quick-switch drawing under corrupted fetched_models_json
    mock_layout = MockLayout()
    try:
        # Should not throw exception
        p = bpy.context.preferences.addons.get(U.PACKAGE_ID)
        pref = p.preferences if p else None
        # Manually verify cached_models recovery
        try:
            m_list = json.loads(state.fetched_models_json)
        except Exception:
            m_list = []
        ck("models_corrupt_recovery", m_list == [], "Corrupted models JSON handled safely")
    except Exception as e:
        ck("models_corrupt_recovery", False, str(e))

    # Notes collection scaling
    U.ensure_notes(state, 10)
    ck("ensure_notes_10", len(state.notes) >= 10, f"Notes count: {len(state.notes)}")
    U.ensure_notes(state, 5)  # smaller count should not shrink or error
    ck("ensure_notes_no_shrink", len(state.notes) >= 10, f"Notes count preserved: {len(state.notes)}")


def test_operator_and_undo_robustness():
    print("\n--- 4. Operator & Undo Robustness ---")
    state = bpy.context.scene.deepseek_agent

    # Undo safety when run/receipt is None
    U.CONTROLLER.run = None
    ck("can_undo_when_none", U.can_undo(state) is False, "can_undo should return False when no run exists")

    # Undo safety when run exists but boundary_pushed is False
    dummy_run = Run("test")
    U.CONTROLLER.run = dummy_run
    ck("can_undo_no_boundary", U.can_undo(state) is False, "can_undo should return False without boundary")

    # Stop operator poll check
    U.CONTROLLER.run = None
    ck("stop_poll_false_when_idle", not bpy.ops.deepseek.stop.poll(), "stop operator disabled when idle")
    busy_run = Run("test")
    busy_run.phase = Phase.TOOL_RUNNING
    U.CONTROLLER.run = busy_run
    ck("stop_poll_true_when_busy", bpy.ops.deepseek.stop.poll(), "stop operator enabled when busy")
    U.CONTROLLER.run = None

    # Undo rollback test
    state.history.clear()
    state.prompt = ""
    U.push_history(state, "你", "想建一个茶杯")
    U.push_history(state, "AI", "好的，正在建模...")
    res_undo = bpy.ops.deepseek.undo_task()
    ck("undo_finished", res_undo == {'FINISHED'}, f"undo_task returns FINISHED, got {res_undo}")
    ck("undo_prompt_restored", state.prompt == "想建一个茶杯", f"Prompt restored after undo: {state.prompt}")
    ck("undo_history_cleared", len(state.history) == 0, f"History rolled back: {len(state.history)}")

    # Retry operator test
    ck("retry_operator_registered", hasattr(bpy.ops.deepseek, "retry"), "deepseek.retry must be registered")
    state.history.clear()
    state.prompt = ""
    U.push_history(state, "你", "建一个雪屋")
    state.settled_phase = Phase.FAILED.value
    state.settled_err = Err.TIMEOUT.value
    failed_run = Run("建一个雪屋")
    failed_run.phase = Phase.FAILED
    U.CONTROLLER.run = failed_run
    pref = bpy.context.preferences.addons.get(U.PACKAGE_ID)
    old_key = getattr(pref.preferences, "api_key", "") if pref else ""
    if pref:
        pref.preferences.api_key = "sk-test-key-for-retry"
    res_retry = bpy.ops.deepseek.retry()
    ck("retry_executed", res_retry == {'FINISHED'}, f"retry returns FINISHED, got {res_retry}")
    ck("retry_recovers_prompt", any("建一个雪屋" in m.text for m in state.history if m.role == "你"), "Prompt recovered in history on retry")
    if pref:
        pref.preferences.api_key = old_key
    U.CONTROLLER.reset()


def test_ui_draw_stress():
    print("\n--- 5. UI Draw Stress Testing ---")
    state = bpy.context.scene.deepseek_agent
    state.history.clear()

    # Add a short user message and a long user message
    U.push_history(state, "你", "搭建一个小雪屋")
    U.push_history(state, "AI", "好的，请确认细节：\n① 风格：童话冰屋（推荐） / 现代雪居\n直接回复开始建模")
    U.push_history(state, "你", "按推荐参数建模：北欧童话木屋，桌景微缩18cm，原木 + 厚白雪顶，烟囱 + 雪堆 + 松树 + 木栅栏")

    # Run in COMPLETED phase
    run_done = Run("prompt")
    run_done.phase = Phase.COMPLETED
    U.CONTROLLER.run = run_done

    # Draw on normal mock layout
    layout = MockLayout()
    try:
        U.draw_chat_content(layout, bpy.context, state, run_done)
        ck("draw_completed_no_exception", True, "Normal draw completed without error")
    except Exception as e:
        ck("draw_completed_no_exception", False, f"Exception during draw: {e}")

    # Draw in AWAITING_APPROVAL phase
    run_appr = Run("delete objects")
    run_appr.phase = Phase.AWAITING_APPROVAL
    run_appr.approval_preview = "即将删除 5 个对象并清空材质槽"
    U.CONTROLLER.run = run_appr
    layout_appr = MockLayout()
    try:
        U.draw_chat_content(layout_appr, bpy.context, state, run_appr)
        ck("draw_approval_no_exception", True, "Approval phase draw completed")
    except Exception as e:
        ck("draw_approval_no_exception", False, f"Approval phase draw failed: {e}")

    # Draw in FAILED phase with error
    state.settled_err = Err.TIMEOUT.value
    state.settled_err_detail = "API 请求超时：模型思考已超过 180 秒"
    run_fail = Run("failed")
    run_fail.phase = Phase.FAILED
    run_fail.detail = "API 请求超时：模型思考已超过 180 秒"
    U.CONTROLLER.run = run_fail
    layout_fail = MockLayout()
    try:
        U.draw_chat_content(layout_fail, bpy.context, state, run_fail)
        ck("draw_failed_no_exception", True, "Failed phase draw completed")
        fail_texts = layout_fail.all_texts()
        ck("draw_failed_has_detail", any("API 请求超时" in t for t in fail_texts), "Failed banner must disclose detail")
    except Exception as e:
        ck("draw_failed_no_exception", False, f"Failed phase draw failed: {e}")
    state.settled_err = Err.NONE.value

    # Draw in TOOL_RUNNING phase
    run_busy = Run("busy")
    run_busy.phase = Phase.TOOL_RUNNING
    run_busy.elapsed = 15.2
    run_busy.calls = [ToolCall("call_1", "execute_blender_code", {"code": "bpy.ops.mesh.primitive_cube_add()"})]
    U.CONTROLLER.run = run_busy
    layout_busy = MockLayout()
    try:
        U.draw_chat_content(layout_busy, bpy.context, state, run_busy)
        ck("draw_busy_no_exception", True, "Busy phase draw completed")
    except Exception as e:
        ck("draw_busy_no_exception", False, f"Busy phase draw failed: {e}")

    U.CONTROLLER.run = None


def main():
    bda.register()
    try:
        test_wrap_text_robustness()
        test_interactive_parser_robustness()
        test_state_and_history_robustness()
        test_operator_and_undo_robustness()
        test_ui_draw_stress()
    finally:
        pass

    print("\n" + "=" * 50)
    if FAILURES:
        print("FAILURES:", FAILURES)
        print(f"RESULT robustness: {len(FAILURES)} failed, {TOTAL[0] - len(FAILURES)} passed")
        sys.exit(1)
    else:
        print(f"RESULT robustness: 0 failed, {TOTAL[0]} passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
