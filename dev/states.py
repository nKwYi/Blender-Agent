# -*- coding: utf-8 -*-
"""【AI 对话】tab 的 7 个关键状态构造器。

布局树导出与实机截图共用这一份定义，保证两边状态绝对一致——
这是 ui_workbench 双轨能对齐的前提。改这里必须同步两个导出脚本的预期。

字段全部按源码真实字段写，不照抄任务书草稿（草稿里有几处并不存在）：

  * Run 没有 clarify_text / options / step_text / approval_preview；
    追问与选项是走 state.history 的 AI 消息文本，由 ui.py:892 的
    parse_interactive_options() 解析出 questions。
  * settled_err 是 PropertyGroup 上的字段（ui.py:278），不是 Run 的字段；
    Run 上对应的是 err / detail（state.py:198-199）。
  * ToolCall.status 与 summary() 都是只读的（state.py:167-174，
    且 __slots__ 里没有 summary），要造"已完成/进行中"只能填 result。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_deepseek_agent.receipt import Receipt
from blender_deepseek_agent.state import Err, Phase, Run, ToolCall

STATE_NAMES = ["idle", "clarify", "options", "running", "done", "partial", "failed"]

REQUIRED_KEYS = ("state", "run", "history", "prompt", "active_tab")

PROMPT = "做一个精致的中式紫砂茶杯，杯身要能看出砂颗粒的质感"

# 追问态：自然语言问句，解析不出 questions，因此不出现选项卡
CLARIFY_REPLY = (
    "在动手之前想跟你确认一下：这只茶杯的杯壁你想要多厚？\n"
    "薄胎（约 2mm）透光但易磕，厚胎（约 6mm）手感沉稳。"
)

# 规格确认态：numbered + 斜杠分隔，parse_interactive_options 会解析出
# questions，ui.py:904-915 才会画出 chat.options 卡片与候选按钮
OPTIONS_REPLY = (
    "为了更贴近你想要的样子，先确认三个规格：\n"
    "1. 杯型风格：经典直筒微收口 / 鼓腹圆润 / 手作厚壁窑变（推荐：经典直筒微收口）\n"
    "2. 壶嘴：短嘴 / 长嘴 / 无嘴（推荐：短嘴）\n"
    "3. 把手材质：紫砂一体 / 竹节缠绕 / 无把手（推荐：竹节缠绕）\n"
    "确认无误的话，我就开始车削。"
)

# 普通对话回复：一段说明 + 执行摘要 + 新增对象，用于 done / running / partial
EXEC_REPLY = "杯身已经车削完成，我顺手把边缘的微倒角也做了，看起来更接近手工打磨的质感。"


def _receipt(lines):
    """造一个带变更摘要的回执。Receipt() 自己会 snapshot 当前场景。"""
    rc = Receipt()
    rc.lines = list(lines)
    rc.changed = bool(rc.lines)
    # 无头模式推不了 undo 边界（receipt.py:62），保持 False，
    # 于是 ui.py:1348 的 can_undo() 为假，不会画出「回退操作」。
    rc.boundary_pushed = False
    return rc


def _call(call_id, name, args, result=None, approval_state=None, elapsed=None):
    """造一次工具调用。result 决定 status：None → running，非空且无 error → ok。"""
    c = ToolCall(call_id, name, args)
    c.result = result
    c.approval_state = approval_state
    c.elapsed = elapsed
    if result is None:
        c.started = 0.0
    else:
        c.done = None
    return c


def _msg(role, text, duration="", steps=None, added="", topic=PROMPT):
    """历史条目规格。steps / added 对应 ui.py:876-933 的分支字段。"""
    import json
    return {
        "role": role,
        "text": text,
        "duration_str": duration,
        "steps_json": json.dumps(steps, ensure_ascii=False) if steps else "",
        "added_objects_str": added,
        "session_topic": topic,
    }


HIST_BASE = [
    _msg("你", PROMPT),
]

HIST_WORKED = [
    _msg("你", PROMPT),
    _msg("AI", EXEC_REPLY, duration="24秒",
         steps=["旋转车削一体化成型 完成，耗时 12秒",
                "配置物理 PBR 材质节点 完成，耗时 6秒"],
         added="Teapot"),
]


def build(state_name):
    """Return a dict describing one panel state."""
    if state_name == "idle":
        return {
            "state": state_name, "run": None, "history": [], "prompt": "",
            "active_tab": "CHAT", "busy": False, "settled_err": "",
            "settled_phase": Phase.READY.value, "session_topic": "",
            "show_approval_code": False,
        }

    if state_name == "clarify":
        # REQUESTING ∈ BUSY（state.py:22）：busy 盒子 + chat.stop 都该出现
        r = Run(PROMPT)
        r.phase = Phase.REQUESTING
        r.elapsed = 6.0
        return {
            "state": state_name, "run": r,
            "history": HIST_BASE + [_msg("AI", CLARIFY_REPLY)],
            "prompt": "", "active_tab": "CHAT", "busy": False,
            "settled_err": "", "settled_phase": Phase.READY.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    if state_name == "options":
        r = Run(PROMPT)
        r.phase = Phase.REQUESTING
        r.elapsed = 4.0
        return {
            "state": state_name, "run": r,
            "history": HIST_BASE + [_msg("AI", OPTIONS_REPLY)],
            "prompt": "", "active_tab": "CHAT", "busy": False,
            "settled_err": "", "settled_phase": Phase.READY.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    if state_name == "running":
        calls = [
            _call("1", "get_scene_info", {},
                  result={"returned": 6, "total_objects": 6}, elapsed=0.4),
            _call("2", "execute_blender_code",
                  {"code": "# 旋转车削杯身\nimport bmesh\nbmesh.ops.spin("},
                  result=None),
        ]
        r = Run(PROMPT)
        r.phase = Phase.TOOL_RUNNING
        r.calls = calls
        r.elapsed = 6.0
        r.receipt = _receipt([])
        return {
            "state": state_name, "run": r,
            "history": HIST_BASE + [_msg("AI", "我先看一下场景里现有的物体，再动手。")],
            "prompt": "", "active_tab": "CHAT", "busy": False,
            "settled_err": "", "settled_phase": Phase.READY.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    if state_name == "done":
        calls = [
            _call("1", "execute_blender_code", {"code": "# 旋转车削一体化成型"},
                  result={"stdout": "Teapot 创建完成"}, elapsed=12.0),
            _call("2", "set_material", {"object_name": "Teapot"},
                  result={"material": "Zisha", "base_color": [0.42, 0.22, 0.13]},
                  elapsed=6.0),
        ]
        r = Run(PROMPT)
        r.phase = Phase.COMPLETED
        r.calls = calls
        r.elapsed = 24.0
        r.rounds = 2
        r.reply = EXEC_REPLY
        r.collection_name = "紫砂茶具"
        r.receipt = _receipt(["新增物体: Teapot",
                              "materials: 0 → 1",
                              "顶点数: 0 → 2,048"])
        return {
            "state": state_name, "run": r, "history": HIST_WORKED,
            "prompt": "", "active_tab": "CHAT", "busy": False,
            "settled_err": "", "settled_phase": Phase.COMPLETED.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    if state_name == "partial":
        calls = [
            _call("1", "execute_blender_code", {"code": "# 旋转车削一体化成型"},
                  result={"stdout": "Teapot 杯身创建完成"}, elapsed=31.0),
            _call("2", "set_material", {"object_name": "Teapot"},
                  result={"error": "PBR 节点构建超时", "type": "Timeout"},
                  elapsed=28.0),
        ]
        r = Run(PROMPT)
        r.phase = Phase.PARTIAL
        r.calls = calls
        r.elapsed = 61.0
        r.rounds = 4
        r.reply = EXEC_REPLY
        r.err = Err.BUDGET_WALL
        r.detail = "达到时间预算 45s，剩余步骤未执行"
        r.skipped = ["上紫砂 PBR 材质", "把手与壶身布尔熔接"]
        r.receipt = _receipt(["新增物体: Teapot", "顶点数: 0 → 1,536"])
        return {
            "state": state_name, "run": r, "history": HIST_WORKED,
            "prompt": "", "active_tab": "CHAT", "busy": False,
            "settled_err": "", "settled_phase": Phase.PARTIAL.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    if state_name == "failed":
        r = Run(PROMPT)
        r.phase = Phase.FAILED
        r.elapsed = 3.4
        r.err = Err.KEY_INVALID
        r.detail = "HTTP 401 · 服务端拒绝了这个 Key"
        r.note_error(Err.KEY_INVALID, r.detail)
        r.receipt = _receipt([])
        return {
            "state": state_name, "run": r,
            "history": HIST_BASE + [_msg("AI", "我准备发起请求时被打断了。")],
            "prompt": "", "active_tab": "CHAT", "busy": False,
            # 失败文案取的是 state.settled_err，不是 run.err（ui.py:844）
            "settled_err": Err.KEY_INVALID.value,
            "settled_phase": Phase.FAILED.value,
            "session_topic": PROMPT, "show_approval_code": False,
        }

    raise ValueError("未知状态：%s" % state_name)


def apply_spec(state, spec):
    """把 spec 落到真实的 PropertyGroup 与 CONTROLLER 上，返回该 state。

    draw 期间 Blender 禁止写 ID 数据，所以所有赋值都在 draw 之前完成。

    CONTROLLER.run 必须一起设：draw_chat_content 的 busy 判定读的是
    CONTROLLER.busy（ui.py:797），Panel.draw 取的 run 也来自 CONTROLLER
    （ui.py:986），只看传进去的 run 参数会让 busy 盒子与失败盒子整块消失。
    """
    from blender_deepseek_agent.worker import CONTROLLER
    CONTROLLER.run = spec.get("run")
    state.active_tab = spec.get("active_tab", "CHAT")
    state.prompt = spec.get("prompt", "")
    state.busy = bool(spec.get("busy", False))
    state.settled_err = spec.get("settled_err", "")
    state.settled_phase = spec.get("settled_phase", Phase.READY.value)
    state.session_topic = spec.get("session_topic", "")
    state.show_approval_code = bool(spec.get("show_approval_code", False))
    state.page = 0
    state.selected = -1
    state.history.clear()
    for item in spec.get("history", []):
        entry = state.history.add()
        entry.role = item["role"]
        entry.text = item["text"]
        entry.duration_str = item.get("duration_str", "")
        entry.steps_json = item.get("steps_json", "")
        entry.added_objects_str = item.get("added_objects_str", "")
        entry.stamp = ""
        entry.raw_prompt = PROMPT
        entry.collection_name = ""
    return state
