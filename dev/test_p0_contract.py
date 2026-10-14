"""规范 P0 契约的无头部分：审批门 / 停止语义 / 回执诚实 / Key 不外泄 / 错误分型。

用法：blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_p0_contract.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402

import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent import agent as ag  # noqa: E402
from blender_deepseek_agent import worker as wk  # noqa: E402
from blender_deepseek_agent.config import AgentError  # noqa: E402
from blender_deepseek_agent.receipt import Receipt, diff, snapshot  # noqa: E402
from blender_deepseek_agent.state import Err, Phase  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


def call(cid, name, args):
    import json
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def completion(message, usage=None):
    payload = {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}
    if usage:
        payload["usage"] = usage
    return payload


CFG = {"api_key": "sk-contract-test-key-9988", "model": "m", "base_url": "http://x",
       "timeout": 5, "max_turns": 4, "wall_budget": 60, "allow_arbitrary_code": False, "history_page": 3}


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, tools, **kw):
        self.seen.append([dict(m) for m in messages])
        return completion(self.replies.pop(0))


bda.register()

# ---------- 1. 无头时任意 Python 必须被拒，而不是悄悄放行 ----------
chat = Scripted([
    {"role": "assistant", "content": None, "tool_calls": [call("a1", "execute_blender_code", {"code": "bpy.ops.object.delete()"})]},
    {"role": "assistant", "content": "已按你的要求跳过"},
])
res = ag.agent_loop("删掉所有东西", chat=chat, config=CFG)
check("无头 + 未授权 → 该步被拒绝", res["calls"][0]["result"].get("type") == "ApprovalDenied", res["calls"][0])
fed = [m for m in chat.seen[-1] if m.get("role") == "tool"]
check("拒绝结果回喂给模型（不是静默跳过）", fed and "拒绝" in fed[-1]["content"], fed[-1]["content"][:80] if fed else "没有 tool 消息")
check("首次错误不被“已修正”盖掉", res["error"] == Err.APPROVAL_DENIED.value, res["error"])
check("被拒的删除没有真的执行", "Cube" in bpy.data.objects)

# ---------- 2. 显式授权后允许执行 ----------
CFG_ALLOW = dict(CFG, allow_arbitrary_code=True)
chat2 = Scripted([
    {"role": "assistant", "content": None, "tool_calls": [call("a2", "execute_blender_code", {"code": "print(6*7)"})]},
    {"role": "assistant", "content": "算完了"},
])
res2 = ag.agent_loop("算个数", chat=chat2, config=CFG_ALLOW)
check("授权后 execute_blender_code 可执行", res2["calls"][0]["result"].get("stdout", "").strip() == "42", res2["calls"][0])

# ---------- 3. 停止语义：不谎称能中断正在飞的请求 ----------
ctrl = wk.Controller()
stop_seen = {}


def chatting(messages, tools, **kw):
    stop_seen["rounds_at_call"] = ctrl.run.rounds
    ctrl.request_stop()
    return completion({"role": "assistant", "content": None,
                       "tool_calls": [call("s1", "create_primitive", {"type": "cube", "name": "StopProbe"})]})


cfg_stop = dict(CFG, chat=chatting)
ctrl.start("建个立方体然后继续讲", cfg_stop)
while ctrl.tick():
    pass
run = ctrl.run
check("停止后不再进入下一轮", run.stop_requested and run.rounds == 1, (run.stop_requested, run.rounds))
check("停止态是 STOPPED 而不是伪装完成", run.phase is Phase.STOPPED, run.phase)
check("停止回复说清“不是立即中断、之后不再发起”",
      "停止" in run.reply and ("返回后" in run.reply or "没有再发起" in run.reply), run.reply)
check("说停之后不再执行新动作", not run.calls and "StopProbe" not in bpy.data.objects, [c.name for c in run.calls])
check("未执行的步骤被记成 skipped 留痕", run.skipped == ["create_primitive"], run.skipped)

# ---------- 4. 回执诚实 ----------
r = Receipt()
b = snapshot()
execute = __import__("blender_deepseek_agent.tools", fromlist=["execute_tool"]).execute_tool
execute("create_primitive", {"type": "sphere", "name": "ReceiptProbe"})
r.refresh()
check("回执给出真实差异", any("objects" in x for x in r.lines) and any("ReceiptProbe" in x for x in r.lines), r.lines)
rec = " || ".join(r.recovery_lines())
check("回执明确声明任务级回滚点未提供", "任务级回滚点：未提供" in rec, rec)
check("无头时不虚报可撤销", "无头模式不提供 Undo" in rec, rec)
check("diff 对空改动返回空列表", diff(b, b) == [], diff(b, b))

# ---------- 5. Key 不外泄 ----------
from blender_deepseek_agent.config import redact  # noqa: E402

leaky = f"DeepSeek 返回 401：bad key sk-contract-test-key-9988 已失效"
check("redact 抹掉完整 Key", "sk-contract-test-key-9988" not in redact(leaky, CFG["api_key"]), redact(leaky, CFG["api_key"]))
check("redact 抹掉任意 sk- 形态", "sk-" not in redact("key: sk-abcdefghijklmnop", "").replace("sk-***", ""))
state = bpy.context.scene.deepseek_agent
from blender_deepseek_agent.ui import push_history  # noqa: E402

state.api_key_cache = CFG["api_key"]
push_history(state, "AI", leaky)
check("写进对话历史的文本已抹 Key", all(CFG["api_key"] not in i.text for i in state.history), [i.text for i in state.history])

# ---------- 6. 错误分型映射 ----------
for status, kind, want in ((401, None, Err.KEY_INVALID), (402, None, Err.BILLING), (0, "timeout", Err.TIMEOUT),
                           (0, "unreachable", Err.NET), (500, None, Err.NET_HTTP), (200, None, Err.BAD_RESPONSE)):
    got = ag.classify(AgentError("x", status, kind))
    check(f"classify {status}/{kind} → {want.value}", got is want, got)

from blender_deepseek_agent.state import guide  # noqa: E402

for err in Err:
    if err is Err.NONE:
        continue
    g = guide(err)
    ok = all(k in g and g[k] for k in ("title", "effect", "action", "retry"))
    check(f"错误 {err.value} 四要素齐全", ok, g)
check("超时不承诺“不会重复扣费”", "不会重复计费" not in guide(Err.TIMEOUT)["retry"], guide(Err.TIMEOUT)["retry"])

# ---------- 7. 工具表只声明真存在的能力 ----------
names = {t["function"]["name"] for t in ag.tools_for(CFG)}
check("未开启的能力不出现在工具表里", names == ag.known_tool_names(), names)
check("没有把不存在的工具报给模型", "get_viewport_screenshot" not in names and "mesh_boolean" not in names)

print(f"RESULT p0: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
