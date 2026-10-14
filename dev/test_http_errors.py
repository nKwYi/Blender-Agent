"""不打真 Key 也要验证网络层：拿真 DeepSeek 端点触发 401/连不上，确认报的是可读中文而不是崩栈。

用法：
  blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_http_errors.py
"""
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent import agent, config  # noqa: E402
from blender_deepseek_agent.agent import chat_completion  # noqa: E402
from blender_deepseek_agent.config import AgentError  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


bda.register()
cfg = config.get_config()
MESSAGES = [{"role": "user", "content": "hi"}]
FULL = {"api_key": "sk-x", "max_turns": 2, "timeout": 5, "base_url": cfg["base_url"], "model": cfg["model"]}

try:
    chat_completion(MESSAGES, agent.TOOLS, api_key="sk-definitely-not-a-real-key",
                    model=cfg["model"], base_url=cfg["base_url"], timeout=25)
    check("假 Key 必须被拒", False, "端点竟然接受了假 Key")
except AgentError as error:
    check("假 Key → AgentError 且状态是 401", error.status == 401, (error.status, error.message))
    check("401 带中文提示", "API Key 无效" in error.message, error.message)
    check("401 把服务端原文带上", len(error.message) > len("API Key 无效"), error.message)

try:
    chat_completion(MESSAGES, agent.TOOLS, base_url="http://127.0.0.1:9",
                    api_key="sk-x", model=cfg["model"], timeout=5)
    check("打到没人听的端口必须报错", False, "没报错")
except AgentError as error:
    check("连不上时给出可读错误（代理在中间时是 502，也是可读的）", bool(error.message), (error.status, error.message))

print("INFO proxies=" + str(urllib.request.getproxies()))

real_open = agent.urllib.request.urlopen
try:
    def refuse(*a, **k):
        raise urllib.error.URLError("模拟断网")

    agent.urllib.request.urlopen = refuse
    try:
        chat_completion(MESSAGES, agent.TOOLS, api_key="sk-x", model=cfg["model"], base_url=cfg["base_url"], timeout=5)
        check("URLError 必须转成 AgentError", False, "没报错")
    except AgentError as error:
        check("断网 → 状态 0 且提示连不上", error.status == 0 and "连不上" in error.message, (error.status, error.message))
        check("断网提示里带上代理信息（本机有代理）", ("代理" in error.message) == bool(urllib.request.getproxies()), error.message)
finally:
    agent.urllib.request.urlopen = real_open


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


real_open = agent.urllib.request.urlopen
try:
    agent.urllib.request.urlopen = lambda *a, **k: FakeResponse(b'{"id":"x"}')
    try:
        result = agent.agent_loop("测试", chat=chat_completion, config=FULL)
        check("响应没有 choices → 结构化 BAD_RESPONSE 而不是崩", result["error"] == "BAD_RESPONSE", result)
        check("BAD_RESPONSE 带上原响应片段", "id" in result["detail"], result["detail"])
        check("失败时 phase 落到 FAILED", result["phase"] == "FAILED", result["phase"])
    except AgentError as error:
        check("响应没有 choices 不该抛 AgentError 出来", False, f"抛了：{error.message}")

    agent.urllib.request.urlopen = lambda *a, **k: FakeResponse(b"not json at all")
    try:
        chat_completion(MESSAGES, agent.TOOLS, api_key="sk-x", model=cfg["model"], base_url=cfg["base_url"], timeout=5)
        check("响应体不是 JSON 必须报错", False, "没报错")
    except AgentError as error:
        check("响应体不是 JSON → 可读错误", "不是 JSON" in error.message, error.message)
finally:
    agent.urllib.request.urlopen = real_open

print(f"RESULT http: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
