"""无头测试 Agent Loop：用假 LLM 回放 tool_calls，不需要 API Key。

覆盖：多轮回传格式、role=tool 的 tool_call_id 对齐、reasoning_content 原样保留、
失败参数不中断循环、轮次上限、缺 Key 报可读错误。

用法：
  blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_loop_mock.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402

import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent.agent import agent_loop  # noqa: E402
from blender_deepseek_agent.config import AgentError  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


def tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else str(arguments)},
    }


def completion(message, usage=None):
    payload = {"id": "cmpl-mock", "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}
    if usage:
        payload["usage"] = usage
    return payload


CFG = {"api_key": "sk-mock", "model": "deepseek-flash", "base_url": "https://mock", "timeout": 5, "max_turns": 4}


class ScriptedChat:
    """按脚本回答，并把每次收到的 messages 快照留下来做断言。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, tools, **kwargs):
        self.seen.append([dict(m) for m in messages])
        if not self.replies:
            raise AssertionError("假 LLM 脚本用完了，模型还在要回复")
        return completion(self.replies.pop(0))


bda.register()

# 文档 §6 步骤 1 的验收：先查场景，再建立方体，再上红色，最后文字收尾
chat = ScriptedChat([
    {"role": "assistant", "content": None, "tool_calls": [tool_call("c1", "get_scene_info", "{}")]},
    {"role": "assistant", "content": None, "tool_calls": [tool_call("c2", "create_primitive", '{"type":"cube","name":"RedCube","size":2}')]},
    {"role": "assistant", "content": None, "tool_calls": [tool_call("c3", "set_material", '{"object_name":"RedCube","color":[1,0,0]}')]},
    {"role": "assistant", "content": "已创建一个边长 2 米的红色立方体 RedCube。", "reasoning_content": "用户要红色立方体：先建 cube 再上色"},
])

result = agent_loop("创建一个红色立方体", chat=chat, config=CFG)

check("循环走满 4 轮才收尾", result["rounds"] == 4, result["rounds"])
check("最终文字回复传回 UI", "红色立方体" in result["reply"], result["reply"])
check("记录了 3 次工具调用", len(result["calls"]) == 3, result["calls"])
check("三次调用全部成功", all(c["ok"] for c in result["calls"]), result["calls"])

cube = bpy.data.objects.get("RedCube")
check("场景里真的出现了 RedCube", cube is not None)
if cube:
    lengths = [max(c[i] for c in cube.bound_box) - min(c[i] for c in cube.bound_box) for i in range(3)]
    check("size=2 的立方体是 2×2×2", all(abs(v - 2.0) < 1e-5 for v in lengths), lengths)
    bsdf = next(n for n in cube.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    check("RedCube 的材质是纯红", tuple(bsdf.inputs["Base Color"].default_value) == (1.0, 0.0, 0.0, 1.0), tuple(bsdf.inputs["Base Color"].default_value))

final_messages = chat.seen[-1]
roles = [m.get("role") for m in final_messages]
check("消息顺序为 system/user/assistant/tool…", roles[:5] == ["system", "user", "assistant", "tool", "assistant"], roles)
tool_msgs = [m for m in final_messages if m.get("role") == "tool"]
check("每个工具结果都带 tool_call_id", [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2", "c3"], tool_msgs)
check("工具结果是 JSON 字符串", all(isinstance(m["content"], str) for m in tool_msgs))
check("场景查询把物体列表回喂了模型", "total_objects" in tool_msgs[0]["content"], tool_msgs[0]["content"][:120])
check("响应没有 usage 时只是缺字段，不崩", result.get("usage") == {}, result.get("usage"))

# 完整版 §4.2 的坑：reasoning_content 必须在多轮里原样带回
chat_keeps = ScriptedChat([
    {"role": "assistant", "content": None, "reasoning_content": "我要先看场景", "tool_calls": [tool_call("r1", "get_scene_info", "{}")]},
    {"role": "assistant", "content": "看完了"},
])
agent_loop("测试", chat=chat_keeps, config=CFG)
echoed = chat_keeps.seen[-1]
asst = next(m for m in echoed if m.get("role") == "assistant")
check("assistant 的 reasoning_content 被原样回传", asst.get("reasoning_content") == "我要先看场景", list(asst))

# 模型给出非法 JSON 参数时不能中断
BAD_JSON = '{"type": "cube"'
chat_bad = ScriptedChat([
    {"role": "assistant", "content": None, "tool_calls": [tool_call("b1", "create_primitive", BAD_JSON)]},
    {"role": "assistant", "content": "参数写错了，我重来", "tool_calls": [tool_call("b2", "create_primitive", '{"type":"cube","name":"FixedCube"}')]},
    {"role": "assistant", "content": "已修正"},
])
bad_result = agent_loop("先错后对", chat=chat_bad, config=CFG)
check("非法 JSON 参数回喂为错误而非崩溃", "不是合法 JSON" in bad_result["calls"][0]["result"]["error"], bad_result["calls"][0])
check("模型据错误自我修正后成功", bad_result["calls"][1]["ok"] and bpy.data.objects.get("FixedCube") is not None, bad_result["calls"][1])

# 工具报错也回喂：文档 §5 错误恢复
chat_err = ScriptedChat([
    {"role": "assistant", "content": None, "tool_calls": [tool_call("e1", "set_material", '{"object_name":"Ghost","color":[0,1,0]}')]},
    {"role": "assistant", "content": "场景里没有 Ghost，我改成先查场景", "tool_calls": [tool_call("e2", "get_scene_info", "{}")]},
    {"role": "assistant", "content": "没找到那个物体"},
])
err_result = agent_loop("给不存在的物体上绿色", chat=chat_err, config=CFG)
check("工具失败被回喂且循环继续", err_result["calls"][0]["ok"] is False and len(err_result["calls"]) == 2, err_result["calls"])

# 一直不调工具的模型 = 1 轮就返回
chat_plain = ScriptedChat([{"role": "assistant", "content": "我只聊天不动场景"}])
plain = agent_loop("你好", chat=chat_plain, config=CFG)
check("无工具调用时一轮即返回", plain["rounds"] == 1 and plain["calls"] == [], plain)

# 上限：模型死循环调工具
class LoopChat:
    def __init__(self):
        self.n = 0

    def __call__(self, messages, tools, **kwargs):
        self.n += 1
        return completion({"role": "assistant", "content": None, "tool_calls": [tool_call(f"l{self.n}", "get_scene_info", "{}")]})


capped = agent_loop("一直查", chat=LoopChat(), config=CFG)
check("轮次上限生效", capped["rounds"] == CFG["max_turns"] and capped.get("truncated") is True, capped["rounds"])
check("超上限给出可读提示（说清到上限+可能只做了一半）",
      ("上限" in capped["reply"] or "最大" in capped["reply"]) and "一半" in capped["reply"], capped["reply"])

# 缺 Key：文档 UI 承诺的可读错误
try:
    agent_loop("创建立方体", chat=ScriptedChat([]), config={"api_key": "", "max_turns": 4})
    check("缺 Key 必须抛 AgentError", False, "没有抛异常")
except AgentError as error:
    check("缺 Key 报可读中文错误", "未配置 DeepSeek API Key" in error.message, error.message)

print(f"RESULT loop: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
