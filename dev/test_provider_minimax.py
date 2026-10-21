"""MiniMax 服务商接入与模型动态获取测试套件。

用法：
  blender.exe --background --factory-startup --python-exit-code 1 -P dev/test_provider_minimax.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy  # noqa: E402
import blender_deepseek_agent as bda  # noqa: E402
from blender_deepseek_agent import agent, config, ui  # noqa: E402
from blender_deepseek_agent.config import PROVIDERS, AgentError, redact  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} :: {detail}")


bda.register()

# ================= 1. 服务商元数据与 MiniMax 官方文档链接 =================
check("PROVIDERS 包含 DEEPSEEK 与 MINIMAX", "DEEPSEEK" in PROVIDERS and "MINIMAX" in PROVIDERS)
mm = PROVIDERS.get("MINIMAX", {})
check(
    "MiniMax 官方文档链接精确符合要求",
    mm.get("doc_url") == "https://platform.minimax.cn/docs/api-reference/api-overview",
    mm.get("doc_url"),
)
check("MiniMax 基础 Base URL 符合规范", mm.get("base_url") == "https://api.minimax.cn/v1", mm.get("base_url"))
check("MiniMax 环境变量配置为 MINIMAX_API_KEY", mm.get("key_env") == "MINIMAX_API_KEY", mm.get("key_env"))

# ================= 2. Token Plan API Key 脱敏测试 =================
token_plan_key = "sk-cp-abcd1234efgh5678ijkl"
redacted_text = redact(f"连接 MiniMax: {token_plan_key}", token_plan_key)
check("Token Plan API Key (sk-cp-...) 完全脱敏", token_plan_key not in redacted_text and "sk-***" in redacted_text, redacted_text)

# ================= 3. fetch_available_models 接口解析测试 =================
class MockResponse:
    def __init__(self, data_dict):
        self.raw = json.dumps(data_dict).encode("utf-8")

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


real_urlopen = agent.urllib.request.urlopen
try:
    # 模拟 MiniMax /v1/models 响应
    mock_models_payload = {
        "object": "list",
        "data": [
            {"id": "MiniMax-M3", "object": "model"},
            {"id": "MiniMax-M2.7", "object": "model"},
            {"id": "MiniMax-M2.5", "object": "model"},
        ],
    }
    agent.urllib.request.urlopen = lambda req, timeout=10: MockResponse(mock_models_payload)
    models = agent.fetch_available_models(api_key="sk-cp-test", base_url="https://api.minimax.cn/v1")
    check("成功解析 MiniMax 官方模型列表（含 M3.1 Flash）", "MiniMax-M3.1-Flash" in models and "MiniMax-M3" in models, models)

    # 模拟空 Key 拒绝
    try:
        agent.fetch_available_models(api_key="", base_url="https://api.minimax.cn/v1")
        check("缺少 API Key 必须抛出异常", False)
    except AgentError as err:
        check("缺少 API Key 时给出可读提示", "缺少 API Key" in err.message, err.message)
finally:
    agent.urllib.request.urlopen = real_urlopen

# ================= 4. 算子注册与调用测试 =================
check("算子 deepseek.fetch_models 已注册", hasattr(bpy.ops.deepseek, "fetch_models"))
check("算子 deepseek.set_model 已注册", hasattr(bpy.ops.deepseek, "set_model"))

state = bpy.context.scene.deepseek_agent
state.fetched_models_json = json.dumps(["MiniMax-M3", "MiniMax-M2.7"])
check("state.fetched_models_json 缓存正常", len(json.loads(state.fetched_models_json)) == 2)

# 测试 set_model 算子
bpy.ops.deepseek.set_model(model_name="MiniMax-M3")

# ================= 5. 设置 Tab 渲染测试 =================
class MockLayout:
    def __init__(self, kind="layout"):
        self.kind = kind
        self.texts = []
        self.operators = []
        self.children = []
        self.alert = False

    def label(self, text="", icon='NONE'):
        if text:
            self.texts.append(str(text))

    def prop(self, data, prop_name, text="", **kwargs):
        if text:
            self.texts.append(str(text))

    def operator(self, op_id, text="", icon='NONE', **kwargs):
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


class DummyPanel:
    def __init__(self, layout):
        self.layout = layout


mock_cfg = {
    "provider": "MINIMAX",
    "provider_name": "MiniMax",
    "doc_url": "https://platform.minimax.cn/docs/api-reference/api-overview",
    "api_key": "sk-cp-test-key",
    "key_source": "prefs",
    "model": "MiniMax-M2.7",
    "base_url": "https://api.minimax.cn/v1",
    "timeout": 20,
    "max_turns": 4,
    "wall_budget": 45,
    "allow_arbitrary_code": False,
    "history_page": 3,
}

layout_settings = MockLayout()
ui.draw_settings_content(layout_settings, mock_cfg)
all_texts = " ".join(layout_settings.all_texts())
all_ops = layout_settings.all_operators()

check("设置面板包含 MiniMax 服务商信息", "MiniMax" in all_texts, all_texts)
check("设置面板包含 Token Plan 说明", "Token Plan" in all_texts, all_texts)
check("设置面板提供文档打开按钮", any(o["id"] == "wm.url_open" for o in all_ops), all_ops)
check("设置面板提供拉取最新模型按钮", any(o["id"] == "deepseek.fetch_models" for o in all_ops), all_ops)
check("设置面板渲染模型切换按钮", any(o["id"] == "deepseek.set_model" for o in all_ops), all_ops)

print(f"\nRESULT provider_minimax: {len(failures)} failed")
if failures:
    print("FAILED " + ", ".join(failures))
    raise SystemExit(1)
