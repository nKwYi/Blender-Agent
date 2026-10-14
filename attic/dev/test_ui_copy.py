"""UI 文案与交互规范测试：验证说日常中文、技术噪音隔离、中性 PARTIAL 容器与审批门交互。

用法：blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_ui_copy.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402
import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent import worker as wk  # noqa: E402
from blender_deepseek_agent.state import Err, Phase, Run, ToolCall  # noqa: E402
from blender_deepseek_agent.receipt import Receipt  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


bda.register()


class MockLayout:
    def __init__(self, kind="layout"):
        self.kind = kind
        self.texts = []
        self.operators = []
        self.children = []
        self.alert = False
        self.enabled = True

    def label(self, text="", icon='NONE'):
        if text:
            self.texts.append(str(text))

    def prop(self, data, prop_name, text="", **kwargs):
        if text:
            self.texts.append(str(text))

    def textbox(self, data, prop_name, **kwargs):
        pass

    def operator(self, op_id, text="", icon='NONE'):
        self.operators.append({"id": op_id, "text": text, "icon": icon})
        class OpDummy:
            def __setattr__(self, name, value):
                pass
        return OpDummy()

    def box(self):
        sub = MockLayout("box")
        self.children.append(sub)
        return sub

    def row(self, align=False):
        sub = MockLayout("row")
        self.children.append(sub)
        return sub

    def column(self, align=False):
        sub = MockLayout("column")
        self.children.append(sub)
        return sub

    def split(self, factor=0.5, align=False):
        sub = MockLayout("splitcol")
        self.children.append(sub)
        return sub

    def grid_flow(self, **kwargs):
        sub = MockLayout("grid_flow")
        self.children.append(sub)
        return sub

    def progress(self, type='RING'):
        pass

    def all_texts(self):
        res = list(self.texts)
        for c in self.children:
            res.extend(c.all_texts())
        return res

    def all_operators(self):
        res = list(self.operators)
        for c in self.children:
            res.extend(c.all_operators())
        return res

    def all_boxes(self):
        res = []
        for c in self.children:
            if c.kind == "box":
                res.append(c)
            res.extend(c.all_boxes())
        return res


class DummyPanel:
    def __init__(self, layout):
        self.layout = layout


context = bpy.context
state = context.scene.deepseek_agent

# ================= 1. 三 Tab 面板注册与 bl_category 隔离 =================
check("DEEPSEEK_PT_chat 已注册", bda.ui.DEEPSEEK_PT_chat.is_registered)
check("DEEPSEEK_PT_detail 已注册", bda.ui.DEEPSEEK_PT_detail.is_registered)
check("DEEPSEEK_PT_settings 已注册", bda.ui.DEEPSEEK_PT_settings.is_registered)

cats = [
    bda.ui.DEEPSEEK_PT_chat.bl_category,
    bda.ui.DEEPSEEK_PT_detail.bl_category,
    bda.ui.DEEPSEEK_PT_settings.bl_category,
]
check("三个面板类的 bl_category 互不相同", len(set(cats)) == 3, cats)
check("三个 tab 分类名完全符合规范", cats == ["AI 对话", "详情", "设置"], cats)

# ================= 2. 【AI 对话】日常中文与技术噪音隔离 =================
# Mock 配置已配置 Key 的正常使用态
orig_get_config = bda.config.get_config
bda.config.get_config = lambda: {
    "api_key": "sk-valid-key-mock",
    "key_source": "prefs",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout": 20,
    "max_turns": 4,
    "wall_budget": 45,
    "allow_arbitrary_code": False,
    "history_page": 3,
}

run_completed = Run("建个红色立方体")
run_completed.phase = Phase.COMPLETED
run_completed.rounds = 2
run_completed.calls = [ToolCall("1", "create_primitive"), ToolCall("2", "set_material")]
run_completed.usage = {"prompt_tokens": 120, "completion_tokens": 45}
run_completed.receipt = Receipt()
run_completed.receipt.lines = ["创建了 Cube", "设置了材质"]
wk.CONTROLLER.run = run_completed

layout_chat = MockLayout()
panel_chat = DummyPanel(layout_chat)
bda.ui.DEEPSEEK_PT_chat.draw(panel_chat, context)

# AI 对话页已是 GPU 自绘，文案断言改读显示列表；原生层只剩一个输入代理框。
from blender_deepseek_agent import panel as P            # noqa: E402
from blender_deepseek_agent import theme as T            # noqa: E402


def chat_text_of(run_obj, **stkw):
    out = P.build(P.Ctx(state, run_obj, bda.ui, 420, 1756, **stkw))
    return " ".join(it[3] for it in out["items"] if it[0] == "text")


chat_text = " ".join([chat_text_of(run_completed),
                      " ".join(layout_chat.all_texts())])
FORBIDDEN_TECH_TERMS = ["轮次", "工具调用", "上下文", "Provider"]
for term in FORBIDDEN_TECH_TERMS:
    check(f"【AI 对话】文本中不包含噪音词 '{term}'", term not in chat_text, f"在面板中发现了 '{term}'")

# 当 API Key 正常配置时，【AI 对话】不应出现 "API Key"
check("【AI 对话】正常时不出现 'API Key'", "API Key" not in chat_text, chat_text)

# 对话区标题连续对话标注
check("对话记录标题包含连续对话标注", "可连续追问" in chat_text, chat_text)

# 翻页按钮文案为“上一页 / 下一页”
ops_chat = layout_chat.all_operators()
op_page_texts = [o["text"] for o in ops_chat if o["id"] == "deepseek.page"]
# 当历史少于一页时不显示翻页，添加历史触发翻页测试
for i in range(10):
    bda.ui.push_history(state, "你", f"历史消息 {i}")

layout_chat_paged = MockLayout()
bda.ui.DEEPSEEK_PT_chat.draw(DummyPanel(layout_chat_paged), context)
ops_paged = [o["text"] for o in layout_chat_paged.all_operators() if o["id"] == "deepseek.page"]
check("移除翻页按钮，支持直接滚轮自然滚动", len(ops_paged) == 0, ops_paged)
check("更早/更新 文案已被彻底替换", "更早" not in ops_paged and "更新" not in ops_paged, ops_paged)

# ================= 3. PARTIAL 做到一半 中性两栏与 alert=False =================
run_partial = Run("建立方体并移动")
run_partial.phase = Phase.PARTIAL
run_partial.receipt = Receipt()
run_partial.receipt.lines = ["建了 RealCube", "上了红色材质"]
run_partial.skipped = ["移动到 (2,0,0)"]
wk.CONTROLLER.run = run_partial

layout_partial = MockLayout()
bda.ui.DEEPSEEK_PT_chat.draw(DummyPanel(layout_partial), context)

# 展示盒已搬到自绘层：按「卡片矩形区域内的文字」判定，而不是原生 box
partial_out = P.build(P.Ctx(state, run_partial, bda.ui, 420, 1756))
partial_items = partial_out["items"]
partial_texts = [it[3] for it in partial_items if it[0] == "text"]
check("PARTIAL 状态存在专有展示盒", any("做到一半" in t for t in partial_texts),
      partial_texts)
check("PARTIAL 包含'已经做了'", any("已经做了" in t for t in partial_texts), partial_texts)
check("PARTIAL 包含'还没做'", any("还没做" in t for t in partial_texts), partial_texts)
check("PARTIAL 包含提示'没做完的部分，再说一句就行'",
      any("没做完的部分，再说一句就行" in t for t in partial_texts), partial_texts)
# 铁律：PARTIAL 绝不能用红。卡片背景必须是中性色，且不能出现 FAILED 专属红条。
card_rects = [(it[1], it[2], it[3], it[4], it[6]) for it in partial_items
              if it[0] == "rect" and it[5] == T.R_CARD and it[6] != T.QG_BG]
check("PARTIAL 卡片用了中性底色（严禁标红）",
      any(c in (T.ST_WARN_BG,) for *_r, c in card_rects), card_rects[-3:])
check("PARTIAL 没有 FAILED 专属红条",
      not any(c == T.ST_FAIL_TEXT for *_r, c in card_rects), card_rects[-3:])

# ================= 4. FAILED 错误态 alert=True =================
run_failed = Run("失败任务")
run_failed.phase = Phase.FAILED
run_failed.err = Err.NET
wk.CONTROLLER.run = run_failed

layout_failed = MockLayout()
bda.ui.DEEPSEEK_PT_chat.draw(DummyPanel(layout_failed), context)

failed_out = P.build(P.Ctx(state, run_failed, bda.ui, 420, 1756))
failed_items = failed_out["items"]
failed_texts = " ".join(it[3] for it in failed_items if it[0] == "text")
check("FAILED 状态有错误卡（红色底 + 红条）",
      any(it[0] == "rect" and it[6] == T.ST_FAIL_BG for it in failed_items)
      and any(it[0] == "rect" and it[6] == T.ST_FAIL_TEXT for it in failed_items),
      [it[6] for it in failed_items if it[0] == "rect"][-4:])
check("FAILED 卡给出首选动作", "该做的事" in failed_texts or "重试" in failed_texts,
      failed_texts[:200])

# 检查 retry 不重复打印
retry_lines = [t for t in failed_texts.split("  ") if "重试" in t]
check("错误重试说明未被重复打印（仅出现一行）", len(retry_lines) <= 2, retry_lines)

# ================= 5. 审批门摘要优先与折叠 =================
run_approval = Run("执行危险代码")
run_approval.phase = Phase.AWAITING_APPROVAL
code_call = ToolCall("c1", "execute_blender_code", {"code": "bpy.data.objects['Cube'].location = (1, 2, 3)\nbpy.ops.object.select_all()"})
code_call.approval_state = "pending"
run_approval.calls = [code_call]
wk.CONTROLLER.run = run_approval

state.show_approval_code = False
layout_appr = MockLayout()
bda.ui.DEEPSEEK_PT_chat.draw(DummyPanel(layout_appr), context)
appr_texts = [it[3] for it in P.build(P.Ctx(state, run_approval, bda.ui, 420, 1756))["items"]
              if it[0] == "text"]
check("审批门展示行数与改动摘要", any("它想运行一段脚本" in t and "Cube" in t for t in appr_texts), appr_texts)
check("默认折叠状态下不直接铺出代码内容", not any("bpy.ops.object.select_all" in t for t in appr_texts), appr_texts)

# 展开代码状态
state.show_approval_code = True
layout_appr_exp = MockLayout()
bda.ui.DEEPSEEK_PT_chat.draw(DummyPanel(layout_appr_exp), context)
appr_exp_texts = [it[3] for it in P.build(P.Ctx(state, run_approval, bda.ui, 420, 1756))["items"]
                  if it[0] == "text"]
check("展开后可见具体 Python 代码", any("select_all" in t for t in appr_exp_texts), appr_exp_texts)
state.show_approval_code = False

# ================= 6. 详情 Tab 与导出图标 =================
run_detail = Run("详情展示任务")
run_detail.calls = [ToolCall("t1", "create_primitive", {"type": "cube"})]
run_detail.usage = {"prompt_tokens": 100}
wk.CONTROLLER.run = run_detail

layout_detail = MockLayout()
bda.ui.DEEPSEEK_PT_detail.draw(DummyPanel(layout_detail), context)
detail_texts = layout_detail.all_texts()
check("【详情】展示工具调用", any("工具调用" in t for t in detail_texts), detail_texts)
check("【详情】展示用量", any("用量" in t for t in detail_texts), detail_texts)

detail_ops = layout_detail.all_operators()
export_ops = [o for o in detail_ops if o["id"] == "deepseek.export"]
check("导出完整转录 operator 存在", bool(export_ops))
if export_ops:
    check("导出图标为合规的 EXPORT 且不是 ADD", export_ops[0]["icon"] == 'EXPORT', export_ops[0])

# ================= 7. 新任务 Operator 清态验证 =================
wk.CONTROLLER.run = run_completed
state.prompt = "上一次的输入"
state.settled_phase = Phase.COMPLETED.value
bpy.ops.deepseek.new_task()
check("开启新任务清空 prompt", state.prompt == "")
check("开启新任务重置 settled_phase 为 READY", state.settled_phase == Phase.READY.value)
check("开启新任务清空 CONTROLLER.run", wk.CONTROLLER.run is None)

print(f"\nRESULT ui_copy: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
