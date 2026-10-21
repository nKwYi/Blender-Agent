"""运行态状态机与错误分型。

8 个状态族是“界面布局复用”的分类，运行时仍保留细粒度错误码，
避免用一个笼统的 ERROR 覆盖事实。
"""
from enum import Enum


class Phase(str, Enum):
    READY = "READY"
    PREFLIGHT = "PREFLIGHT"
    REQUESTING = "REQUESTING"
    TOOL_RUNNING = "TOOL_RUNNING"
    VERIFYING = "VERIFYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


BUSY = {Phase.PREFLIGHT, Phase.REQUESTING, Phase.TOOL_RUNNING, Phase.VERIFYING, Phase.AWAITING_APPROVAL}


class Err(str, Enum):
    NONE = ""
    KEY_MISSING = "CONFIG_KEY_MISSING"
    KEY_INVALID = "AUTH_INVALID"
    BILLING = "BILLING_INSUFFICIENT"
    NET = "NET_UNREACHABLE"
    NET_HTTP = "NET_HTTP"
    TIMEOUT = "REQUEST_TIMEOUT"
    BAD_RESPONSE = "BAD_RESPONSE"
    BUDGET_ROUNDS = "BUDGET_ROUNDS"
    BUDGET_WALL = "BUDGET_WALL"
    TOOL_FAILED = "TOOL_FAILED"
    TOOL_FAILED_RECOVERED = "TOOL_FAILED_RECOVERED"
    APPROVAL_DENIED = "CODE_APPROVAL_DENIED"
    UNDO_UNAVAILABLE = "UNDO_UNAVAILABLE"
    VISION_UNAVAILABLE = "VISION_UNAVAILABLE"
    INTERNAL = "INTERNAL"


# 每种错误的：发生了什么 / 场景是否可能已变 / 唯一首选动作 / 能否安全重试
ERROR_GUIDE = {
    Err.KEY_MISSING: {
        "title": "配置错误 · 缺少 API Key",
        "effect": "未发起任何请求，场景未改变。",
        "action": "打开偏好设置填入 Key",
        "retry": "配好后重试不会重复计费（本次没发过请求）",
    },
    Err.KEY_INVALID: {
        "title": "配置错误 · Key 无效",
        "effect": "请求被服务端拒绝，场景未改变。",
        "action": "修改 Key",
        "retry": "重试同一 Key 无意义，先改配置",
    },
    Err.BILLING: {
        "title": "需外部处理 · 余额不足",
        "effect": "场景未改变。",
        "action": "充值后继续",
        "retry": "充值前重试只会再失败一次",
    },
    Err.NET: {
        "title": "可诊断 · 连不上模型服务",
        "effect": "请求可能未到达服务端；场景是否改变以工具记录为准。",
        "action": "检查网络或本机代理是否在运行",
        "retry": "可重试，但重试会产生新的请求费用",
    },
    Err.NET_HTTP: {
        "title": "请求失败",
        "effect": "本轮未取得结果；已执行过的工具不会自动回退。",
        "action": "查看下方详情后决定",
        "retry": "可重试，重试会产生新的请求费用",
    },
    Err.TIMEOUT: {
        "title": "状态待确认 · 本轮请求超时",
        "effect": "客户端没拿到响应，但这不能证明服务端没有处理请求或计费。",
        "action": "先看工具记录，再决定是否重试",
        "retry": "重试可能产生新的请求费用",
    },
    Err.BAD_RESPONSE: {
        "title": "请求失败 · 响应格式异常",
        "effect": "本轮未取得可用结果。",
        "action": "重试本轮请求",
        "retry": "可重试，会产生新的请求费用",
    },
    Err.BUDGET_ROUNDS: {
        "title": "部分完成 · 步骤太多已暂停",
        "effect": "已执行的工具已生效，未执行的步骤列在下方。",
        "action": "从断点继续",
        "retry": "继续会发起新请求",
    },
    Err.BUDGET_WALL: {
        "title": "部分完成 · 达到时间预算",
        "effect": "已执行的工具已生效，未执行的步骤列在下方。",
        "action": "从断点继续",
        "retry": "继续会发起新请求",
    },
    Err.TOOL_FAILED: {
        "title": "工具失败",
        "effect": "场景可能已部分改变，见变更回执。",
        "action": "查看失败详情",
        "retry": "同一参数重试大概率同样失败",
    },
    Err.TOOL_FAILED_RECOVERED: {
        "title": "工具失败后已自动修正",
        "effect": "首次失败与修正记录都保留在工具列表里。",
        "action": "无需处理",
        "retry": "—",
    },
    Err.APPROVAL_DENIED: {
        "title": "已拒绝 · 任意 Python 执行",
        "effect": "该步骤未执行，之前的步骤结果保留。",
        "action": "如确需执行，请重新提交并批准",
        "retry": "—",
    },
    Err.UNDO_UNAVAILABLE: {
        "title": "恢复能力不足",
        "effect": "全局撤销关闭时，AI 的改动可能无法退回。",
        "action": "打开全局撤销",
        "retry": "—",
    },
    Err.VISION_UNAVAILABLE: {
        "title": "视觉检查未执行",
        "effect": "拿不到有效视口图，模型只依据场景数据判断。",
        "action": "在 GUI 中重试或关闭“看一眼视口”",
        "retry": "—",
    },
    Err.INTERNAL: {
        "title": "未预期的错误",
        "effect": "场景状态以工具记录为准。",
        "action": "展开详情并复制给开发者",
        "retry": "可重试",
    },
}


def guide(err):
    return ERROR_GUIDE.get(err if isinstance(err, Err) else Err(err), ERROR_GUIDE[Err.INTERNAL])


class ToolCall:
    """一次工具调用；worker 线程只负责排队，执行与回填都在主线程。"""

    __slots__ = ("call_id", "name", "args", "raw_args", "result", "done", "approved",
                 "approval_state", "started", "elapsed", "error")

    def __init__(self, call_id, name, args=None, raw_args=""):
        self.call_id = call_id
        self.name = name
        self.args = args
        self.raw_args = raw_args
        self.result = None
        self.done = None
        self.approved = None
        self.approval_state = None      # None | 'pending' | 'granted' | 'denied'
        self.started = None
        self.elapsed = None
        self.error = None

    @property
    def ok(self):
        return self.result is not None and "error" not in self.result

    @property
    def status(self):
        if self.approval_state == "pending":
            return "awaiting"
        if self.result is None:
            return "running"
        return "ok" if self.ok else "error"

    def summary(self):
        r = self.result or {}
        if "error" in r:
            return str(r["error"])[:90]
        if self.name == "create_primitive":
            return f"{r.get('object_name')} · size {r.get('size')}"
        if self.name == "set_material":
            return f"{r.get('material')} · rgb {r.get('base_color')}"
        if self.name == "transform_object":
            return f"{r.get('object_name')} → {r.get('location', r.get('rotation_degrees', r.get('scale')))}"
        if self.name == "get_scene_info":
            return f"{r.get('returned')}/{r.get('total_objects')} 物体"
        if self.name == "execute_blender_code":
            out = (r.get("stdout") or "").strip().replace("\n", " ")
            return f"stdout: {out[:60]}" if out else "无输出"
        return "ok"


class Run:
    """一次任务的完整运行态。"""

    def __init__(self, prompt, limit=4, wall=45.0):
        self.prompt = prompt
        self.phase = Phase.PREFLIGHT
        self.err = Err.NONE
        self.detail = ""
        self.rounds = 0
        self.limit = limit
        self.wall = wall
        self.started = 0.0
        self.elapsed = 0.0
        self.calls = []
        self.usage = {}
        self.reply = ""
        self.stop_requested = False
        self.receipt = None
        self.first_error = None
        self.skipped = []
        self.recovered = False
        self.phases = []
        self.collection_name = ""
        self.artifacts = {}

    def record_phase(self):
        name = self.phase.value
        if not self.phases or self.phases[-1] != name:
            self.phases.append(name)

    def note_error(self, err, detail=""):
        self.err = err
        self.detail = detail
        if self.first_error is None:
            self.first_error = (err, detail)
        recovered = any(not c.ok for c in self.calls) and all(c.ok for c in self.calls[-1:])
        if err == Err.NONE and recovered:
            self.err = Err.TOOL_FAILED_RECOVERED

    @property
    def failed_calls(self):
        return [c for c in self.calls if c.result is not None and not c.ok]

    @property
    def pending(self):
        return [c for c in self.calls if c.result is None]
