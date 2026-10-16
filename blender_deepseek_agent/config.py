import os

import bpy

# 装成扩展时 Blender 用 bl_ext.<repo>.<id> 导入本包，AddonPreferences.bl_idname 必须和它一致，
# 写死成 id 的话装进 Blender 后偏好设置那一栏会静默失效。
PACKAGE_ID = __package__ or __name__

DEFAULT_PROVIDER = "DEEPSEEK"

PROVIDERS = {
    "DEEPSEEK": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-flash",
        "doc_url": "https://api-docs.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "key_label": "DeepSeek API Key",
        "key_tip": "支持填入 DeepSeek 官方 API Key",
        "preset_models": [
            "deepseek-flash",
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    "MINIMAX": {
        "name": "MiniMax",
        "base_url": "https://api.minimax.cn/v1",
        "default_model": "MiniMax-M3.1-Flash-Preview",
        "doc_url": "https://platform.minimax.cn/docs/api-reference/api-overview",
        "key_env": "MINIMAX_API_KEY",
        "key_label": "MiniMax API Key (Token Plan)",
        "key_tip": "支持填入 MiniMax Token Plan API Key (sk-cp-... 或 sk-...)",
        "preset_models": [
            "MiniMax-M3.1-Flash-Preview",
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.5",
        ],
    },
}

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT = 600
DEFAULT_MAX_TURNS = 20
WALL_BUDGET = 1800.0

KEY_MISSING = (
    "未配置 DeepSeek API Key：编辑 → 偏好设置 → 插件 → Blender DeepSeek Agent 里填入，"
    "或设置环境变量 DEEPSEEK_API_KEY / MINIMAX_API_KEY"
)


class AgentError(Exception):
    """面向用户可读的失败原因（HTTP 状态、网络、缺 Key、超时）。"""

    def __init__(self, message, status=None, kind=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kind = kind


def redact(text, key=None):
    """Key 不允许出现在日志、转录或错误文案里。服务端有时会回显打码后的 Key，
    所以除了精确匹配，再兜一层 sk- 开头的形态。"""
    if not text:
        return text
    out = str(text)
    live = key or get_config()["api_key"]
    if live:
        out = out.replace(live, "sk-***")
        out = out.replace(live[-6:], "******")
    import re
    return re.sub(r"sk-[A-Za-z0-9\-_]{8,}", "sk-***", out)


def _on_provider_change(self, context):
    info = PROVIDERS.get(self.provider)
    if not info:
        return
    other_key = "MINIMAX" if self.provider == "DEEPSEEK" else "DEEPSEEK"
    other_info = PROVIDERS.get(other_key, {})
    if not self.base_url or self.base_url == other_info.get("base_url"):
        self.base_url = info["base_url"]
    if not self.model or self.model == other_info.get("default_model"):
        self.model = info["default_model"]


class DEEPSEEK_PT_prefs(bpy.types.AddonPreferences):
    bl_idname = PACKAGE_ID

    provider: bpy.props.EnumProperty(
        name="服务商",
        items=[
            ('DEEPSEEK', "DeepSeek", "DeepSeek 官方 API"),
            ('MINIMAX', "MiniMax", "MiniMax 官方 API（支持 Token Plan）"),
        ],
        default='DEEPSEEK',
        update=_on_provider_change,
    )
    api_key: bpy.props.StringProperty(
        name="API Key",
        subtype="PASSWORD",
        description="服务商密钥（支持 MiniMax Token Plan Key 如 sk-cp-...）。注意：明文写入 Blender 偏好设置文件",
    )
    model: bpy.props.StringProperty(
        name="模型",
        default=DEFAULT_MODEL,
        description="模型标识符，如 deepseek-flash / MiniMax-M2.7",
    )
    base_url: bpy.props.StringProperty(name="Base URL", default=DEFAULT_BASE_URL)
    timeout: bpy.props.IntProperty(
        name="单次请求超时", default=DEFAULT_TIMEOUT, min=1, max=1800,
        description="秒。针对 MiniMax / 深度思考长模型生成复杂几何脚本默认设为 600s (10分钟)",
    )
    max_turns: bpy.props.IntProperty(
        name="最大对话轮次", default=DEFAULT_MAX_TURNS, min=1, max=50,
        description="Agent Loop 里 LLM → 工具 往返的上限（超长上下文模型建议设为 16~30 轮）",
    )
    wall_budget: bpy.props.IntProperty(
        name="单次任务时间预算", default=int(WALL_BUDGET), min=10, max=3600,
        description="秒。超过后任务以“部分完成”结算，不会假装跑完",
    )
    allow_arbitrary_code: bpy.props.BoolProperty(
        name="允许任意 Python 执行", default=False,
        description="关闭时，模型请求 execute_blender_code 会先弹出代码并要求明确批准",
    )
    history_page: bpy.props.IntProperty(
        name="主面板显示条数", default=3, min=1, max=10,
        description="侧栏实测无法靠滚轮滚动，历史按页显示，更早的走翻页",
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.prop(self, "provider")
        info = PROVIDERS.get(self.provider, PROVIDERS["DEEPSEEK"])

        doc_row = box.row(align=True)
        doc_op = doc_row.operator("wm.url_open", text=f"打开 {info['name']} 官方文档", icon='URL')
        doc_op.url = info["doc_url"]

        row = box.row(align=True)
        row.alert = not self.api_key
        row.prop(self, "api_key", text="API Key")

        if self.provider == "MINIMAX":
            box.label(text="提示：MiniMax 支持填入 Token Plan API Key (sk-cp-... 或 sk-...)", icon='INFO')

        col = box.column(align=True)
        col.prop(self, "model")
        col.prop(self, "base_url")
        row = col.row(align=True)
        row.prop(self, "timeout")
        row.prop(self, "max_turns")
        row = col.row(align=True)
        row.prop(self, "wall_budget")
        row.prop(self, "history_page")
        col.prop(self, "allow_arbitrary_code")
        box.label(text="API Key 以明文存在偏好设置文件里，PASSWORD 子类型只打码显示", icon='ERROR')
        box.label(text=f"不想落盘就留空并改用环境变量 {info['key_env']}", icon='INFO')


def _prefs():
    addon = bpy.context.preferences.addons.get(PACKAGE_ID)
    return addon.preferences if addon else None


def get_config():
    """未安装为扩展时（源码直注 / 无头测试）回落到默认值。"""
    p = _prefs()
    provider = getattr(p, "provider", "DEEPSEEK") if p else "DEEPSEEK"
    info = PROVIDERS.get(provider, PROVIDERS["DEEPSEEK"])
    from_prefs = bool(p and p.api_key.strip())

    if from_prefs:
        key = p.api_key.strip()
    else:
        key = os.environ.get(info["key_env"], "").strip()
        if not key:
            key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or os.environ.get("MINIMAX_API_KEY", "").strip()

    raw_timeout = p.timeout if p else DEFAULT_TIMEOUT
    if p and raw_timeout < 600:
        try:
            p.timeout = 600
            raw_timeout = 600
        except Exception:
            raw_timeout = 600
    elif raw_timeout < 600:
        raw_timeout = 600

    raw_turns = p.max_turns if p else DEFAULT_MAX_TURNS
    if p and raw_turns < 16:
        try:
            p.max_turns = 16
            raw_turns = 16
        except Exception:
            raw_turns = 16
    elif raw_turns < 16:
        raw_turns = 16

    raw_wall = p.wall_budget if p else WALL_BUDGET
    if p and raw_wall < 1200:
        try:
            p.wall_budget = 1200
            raw_wall = 1200
        except Exception:
            raw_wall = 1200
    elif raw_wall < 1200:
        raw_wall = 1200

    return {
        "provider": provider,
        "provider_name": info["name"],
        "doc_url": info["doc_url"],
        "api_key": key,
        "key_source": "prefs" if from_prefs else ("env" if key else None),
        "model": (p.model.strip() if p and p.model.strip() else info["default_model"]),
        "base_url": (p.base_url.strip() if p and p.base_url.strip() else info["base_url"]),
        "timeout": raw_timeout,
        "max_turns": raw_turns,
        "wall_budget": raw_wall,
        "allow_arbitrary_code": bool(p.allow_arbitrary_code) if p else False,
        "history_page": p.history_page if p else 3,
    }


classes = (DEEPSEEK_PT_prefs,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
