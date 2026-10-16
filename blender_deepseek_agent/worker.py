"""任务控制器：网络在后台线程，bpy 只在主线程。

worker 线程只碰 HTTP；需要工具结果时把 ToolCall 交给主线程执行并等回填。
无头模式下没有 timers（实测：--background 下 timer 一次都不触发），退化为同步执行。
"""
import queue
import threading
import time

import bpy

from . import agent as ag
from .config import redact
from .receipt import Receipt
from .state import BUSY, Err, Phase, Run, ToolCall
from .tools import execute_tool

WRITE_TOOLS = {"create_primitive", "set_material", "transform_object", "execute_blender_code"}


def worker_loop(run, messages, cfg, request_tool, chat=None):
    """可在任意线程运行；本身不触碰 bpy。"""
    chat = chat or ag.chat_completion
    while run.rounds < run.limit:
        if run.stop_requested:
            run.phase = Phase.STOPPED
            return
        if time.monotonic() - run.started > run.wall:
            run.err = Err.BUDGET_WALL
            run.phase = Phase.PARTIAL
            return
        run.phase = Phase.REQUESTING
        attempt = 0
        completion = None
        current_timeout = cfg.get("timeout", 600)
        while attempt < 2:
            try:
                completion = chat(messages, ag.tools_for(cfg), api_key=cfg["api_key"], model=cfg["model"],
                                   base_url=cfg["base_url"], timeout=current_timeout)
                break
            except ag.AgentError as error:
                left_wall = run.wall - (time.monotonic() - run.started)
                if error.kind == "timeout" and attempt == 0 and not run.stop_requested and left_wall > 60:
                    attempt += 1
                    current_timeout = max(current_timeout, 600)
                    continue
                run.err = ag.classify(error)
                run.detail = redact(error.message, cfg["api_key"])
                run.phase = Phase.FAILED
                return

        choices = completion.get("choices")
        if not choices:
            run.err = Err.BAD_RESPONSE
            run.detail = redact(str(completion)[:300], cfg["api_key"])
            run.phase = Phase.FAILED
            return

        message = choices[0].get("message") or {}
        messages.append(message)          # 原样回传，reasoning_content 等字段保留
        run.rounds += 1
        run.usage = completion.get("usage") or run.usage

        calls = message.get("tool_calls") or []
        if not calls:
            run.reply = (message.get("content") or "").strip()
            run.phase = Phase.COMPLETED
            return

        for call_info in calls:
            if run.stop_requested:
                # 已经说停了就不再启动新动作，但要把“没做哪些”留痕
                run.skipped.append((call_info.get("function") or {}).get("name", "?"))
                run.phase = Phase.STOPPED
                return
            fn = call_info.get("function") or {}
            call = ToolCall(call_info.get("id", ""), fn.get("name", ""), raw_args=fn.get("arguments") or "{}")
            try:
                import json
                call.args = json.loads(call.raw_args)
            except ValueError as error:
                call.result = {"error": f"工具参数不是合法 JSON：{error}"}
                call.error = "bad_json"
                run.calls.append(call)
                messages.append(_tool_message(call))
                continue
            if call.name not in ag.known_tool_names():
                call.result = {"error": f"Unknown tool: {call.name}"}
                call.error = "unknown_tool"
                run.calls.append(call)
                messages.append(_tool_message(call))
                continue
            run.phase = Phase.TOOL_RUNNING
            run.calls.append(call)
            request_tool(call)
            messages.append(_tool_message(call))

    run.err = Err.BUDGET_ROUNDS
    run.phase = Phase.PARTIAL


def compact_messages(messages, keep_recent_tail=6, max_tool_len=300):
    """对早期历史消息做自动压缩，避免超长上下文传输延迟过高。
    保留 system 消息、所有 user 提示词、所有 assistant 核心回复，以及最近 keep_recent_tail 条消息的全部细节。
    对于更早的 tool 消息，将其过长的返回压缩为精简摘要。
    """
    if not messages or len(messages) <= keep_recent_tail + 1:
        return messages

    compacted = []
    cutoff = len(messages) - keep_recent_tail

    for i, msg in enumerate(messages):
        if i == 0 or i >= cutoff:
            compacted.append(msg)
            continue

        role = msg.get("role")
        if role == "tool":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > max_tool_len:
                try:
                    import json
                    data = json.loads(content)
                    summary = {}
                    for k in ("status", "error", "created", "modified", "type"):
                        if k in data:
                            summary[k] = data[k]
                    if "summary" in data:
                        summary["summary"] = data["summary"]
                    elif "stdout" in data:
                        summary["stdout"] = str(data["stdout"])[:100] + "... [已压缩]"
                    if not summary:
                        summary = {"summary": content[:max_tool_len] + "... [已压缩]"}
                    summary["_compressed"] = True
                    compacted.append(dict(msg, content=json.dumps(summary, ensure_ascii=False)))
                    continue
                except Exception:
                    compacted.append(dict(msg, content=content[:max_tool_len] + "... [已压缩]"))
                    continue
        compacted.append(msg)
    return compacted


def ensure_tool_responses(messages):
    """确保所有 assistant tool_calls 都有配对的 tool 消息，且紧随其后，防止 API 返回 400 报错。"""
    if not messages:
        return []
    import json
    result = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        result.append(msg)
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            expected_ids = {
                tc.get("id"): (tc.get("function", {}).get("name", "tool"))
                for tc in msg["tool_calls"] if tc.get("id")
            }
            # 查看紧随其后的 tool 消息
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                cid = messages[j].get("tool_call_id")
                expected_ids.pop(cid, None)
                result.append(messages[j])
                j += 1
            # 补齐本条 assistant 遗漏的 tool 响应（必须插在紧随其后的位置，在下一条 user/assistant 之前）
            for cid, name in expected_ids.items():
                result.append({
                    "role": "tool",
                    "tool_call_id": cid,
                    "content": json.dumps({"status": "skipped", "message": f"{name} 上一轮未及完成"}, ensure_ascii=False)
                })
            i = j
        else:
            i += 1
    return result


def _tool_message(call):
    import json
    return {"role": "tool", "tool_call_id": call.call_id,
            "content": json.dumps(call.result or {"error": "no result"}, ensure_ascii=False)}


class Controller:
    """单任务控制器：UI 只跟它打交道。"""

    def __init__(self):
        self.run = None
        self.messages = None
        self.cfg = None
        self.events = queue.Queue()
        self.thread = None
        self.background = False

    @property
    def busy(self):
        return bool(self.run and self.run.phase in BUSY)

    def reset(self):
        """开启新任务时彻底清空记忆与运行态"""
        self.run = None
        self.messages = None

    def start(self, prompt, cfg, is_continuation=False):
        if self.busy:
            return False
        self.events = queue.Queue()
        run = Run(prompt, limit=cfg.get("max_turns", 20), wall=cfg.get("wall_budget", 600.0))
        if not cfg.get("api_key"):
            run.phase = Phase.FAILED
            run.err = Err.KEY_MISSING
            run.receipt = Receipt()
            self.run = run
            return False
        run.started = time.monotonic()
        self.run, self.cfg = run, cfg

        # 多轮对话上下文继承与自动压缩
        if self.messages and len(self.messages) > 0:
            self.messages = ensure_tool_responses(self.messages)
            self.messages = compact_messages(self.messages)
            while self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            self.messages.append({"role": "user", "content": prompt})
        else:
            self.messages = [
                {"role": "system", "content": ag.system_prompt(cfg)},
                {"role": "user", "content": prompt},
            ]
        run.receipt = Receipt()
        self.background = bool(bpy.app.background)
        if self.background:
            # 无头没有 timers：同步跑完，bpy 本来就在“主线程”
            self.thread = None
            worker_loop(run, self.messages, cfg, self._execute_sync, chat=cfg.get("chat"))
            self._finish()
        else:
            # 泵由控制器自己注册：谁启动任务谁负责抽干队列，否则 worker 会一直等到预算耗尽
            if not bpy.app.timers.is_registered(self._pump):
                bpy.app.timers.register(self._pump, first_interval=0.1)
            self.thread = threading.Thread(target=self._threaded, name="deepseek-agent", daemon=True)
            self.thread.start()
        return True

    def _pump(self):
        return 0.1 if self.tick() else None

    # ---- worker 线程侧 ----
    def _threaded(self):
        def request_tool(call):
            call.done = threading.Event()
            self.events.put(("tool", call))
            left = self.run.wall - (time.monotonic() - self.run.started)
            if not call.done.wait(timeout=max(left, 1.0)):
                call.result = {"error": "主线程未在预算内返回结果", "type": "Timeout"}
                call.error = "main_thread_timeout"
        try:
            worker_loop(self.run, self.messages, self.cfg, request_tool, chat=self.cfg.get("chat"))
        except Exception as error:
            self.run.err = Err.INTERNAL
            self.run.detail = redact(f"{type(error).__name__}: {error}", self.cfg["api_key"])
            self.run.phase = Phase.FAILED
        finally:
            self.events.put(("finished", None))

    def _execute_sync(self, call):
        self._execute_main(call)

    # ---- 主线程侧 ----
    def tick(self):
        """由 bpy.app.timers 调用；所有 bpy 访问都在这里。返回 False 表示可以注销。"""
        if self.run is None:
            return False
        self.run.record_phase()
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "tool":
                self._execute_main(payload)
            elif kind == "finished":
                self._finish()
        self.run.elapsed = round(time.monotonic() - self.run.started, 1)
        return self.busy

    def _execute_main(self, call):
        run = self.run
        if call.name == "execute_blender_code" and not run.receipt.boundary_pushed:
            run.receipt.push_boundary()
        elif call.name in WRITE_TOOLS and not run.receipt.boundary_pushed:
            run.receipt.push_boundary()

        if (call.name == "execute_blender_code" and not self.cfg.get("allow_arbitrary_code")
                and call.approval_state is None):
            if self.background:
                # 无头没人可问：直接拒绝，而不是悄悄放行
                call.approval_state = "denied"
                call.result = {"error": "无头模式下无法取得批准，已拒绝执行任意 Python", "type": "ApprovalDenied"}
                call.error = "denied_headless"
                run.err = Err.APPROVAL_DENIED
                if call.done:
                    call.done.set()
                return
            call.approval_state = "pending"
            run.phase = Phase.AWAITING_APPROVAL
            call.done = call.done or threading.Event()
            return

        run.record_phase()
        call.started = time.monotonic()
        call.result = execute_tool(call.name, call.args)
        call.elapsed = round(time.monotonic() - call.started, 2)
        call.approval_state = "granted" if call.approval_state == "pending" else call.approval_state
        run.receipt.refresh()
        if call.done:
            call.done.set()

    def resolve_approval(self, grant):
        call = next((c for c in (self.run.calls if self.run else []) if c.approval_state == "pending"), None)
        if call is None:
            return
        if grant:
            call.approval_state = "granted"
            self.run.phase = Phase.TOOL_RUNNING
            self._execute_main(call)
        else:
            call.approval_state = "denied"
            call.result = {"error": "用户拒绝了任意 Python 代码执行", "type": "ApprovalDenied"}
            call.error = "denied"
            self.run.err = Err.APPROVAL_DENIED
            self.run.phase = Phase.TOOL_RUNNING
            if call.done:
                call.done.set()

    def request_stop(self):
        if self.run:
            self.run.stop_requested = True
            for call in self.run.calls:
                if call.approval_state == "pending":
                    self.resolve_approval(False)

    def _finish(self):
        run = self.run
        if run is None:
            return
        run.elapsed = round(time.monotonic() - run.started, 1)
        run.receipt.refresh()
        if run.phase in BUSY:
            run.phase = Phase.COMPLETED
        run.recovered = bool(run.phase is Phase.COMPLETED and run.failed_calls)
        if run.phase == Phase.FAILED and not run.detail:
            run.detail = str(run.err.value if hasattr(run.err, "value") else (run.err or "任务遇到未知异常"))
        if not run.reply:
            if run.phase is Phase.PARTIAL:
                run.reply = ("已达到本次处理的步骤或时间上限，操作可能只做了一半。"
                             "已生效的步骤见变更回执与工具列表。")
            elif run.phase is Phase.STOPPED:
                run.reply = "已按你的要求停止：当前请求返回后没有再发起新的步骤。已完成部分见工具列表。"

        self.thread = None


CONTROLLER = Controller()
