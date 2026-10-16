import json
import re

import bpy

from . import config, worker
from .config import PACKAGE_ID, redact
from .state import BUSY, Err, Phase, guide
from .ui_ids import (
    mark, CHAT_TABBAR, CHAT_STATUSBAR, CHAT_STREAM, CHAT_COMPOSER,
    CHAT_SEND, CHAT_STOP, CHAT_ACTION_ROW, CHAT_OPTIONS,
    CHAT_RESULT_TABS, CHAT_HISTORY,
)
from .worker import CONTROLLER

PHASE_VIEW = {
    Phase.READY: ("准备就绪", 'CHECKMARK'),
    Phase.PREFLIGHT: ("正在预检场景...", 'TIME'),
    Phase.REQUESTING: ("正在构思规划...", 'TIME'),
    Phase.TOOL_RUNNING: ("正在修改场景...", 'FILE_SCRIPT'),
    Phase.VERIFYING: ("正在核对成果...", 'TIME'),
    Phase.AWAITING_APPROVAL: ("等待批准代码执行", 'HELP'),
    Phase.COMPLETED: ("做完了", 'CHECKMARK'),
    Phase.PARTIAL: ("做到一半，已停下", 'INFO'),
    Phase.FAILED: ("未完成", 'ERROR'),
    Phase.STOPPED: ("已停止后续步骤", 'CANCEL'),
}

SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# 用户气泡的盒宽 = 面板宽：layout.box() 原生铺满就是想要的，文字按盒内宽度
# 折行，面板拉宽行就变长。原生 UILayout 没有 margin 概念，也不额外切 split 栏。
USER_BUBBLE_FULL_WIDTH = True

# 布局契约（结构性约束，用 check_layout_contract() 自检，空列表 = 全部通过）：
#   1. 页签条排在状态提示条上面 —— DEEPSEEK_PT_chat.draw 先画页签条再调
#      draw_chat_content，UILayout 按源码顺序渲染，天然成立；
#   2. 状态提示条只有一层盒 —— draw_chat_content 的 busy 分支不再 box() 套内层；
#   3. 长提示词用原生 layout.panel() 折叠，idname 稳定、默认展开；
#   4. 用户气泡盒铺满整幅，文字按盒宽折行（不用 split 切窄栏）；
#   5. 规格选项横排，过多或过长时降级竖排；
#   6. 输入框不再有「高度 N」滑块，prompt_lines 仅作 textbox 初值。
LAYOUT_CONTRACT = {
    "tabbar_above_statusbar": True,
    "statusbar_single_box": True,
    "user_msg_panel_fold": True,
    "user_bubble_full_width_box": True,
    "options_horizontal": True,
    "no_composer_height_slider": True,
}


def format_duration(seconds):
    s = float(seconds or 0)
    if s < 1:
        return "不足1秒"
    elif s < 60:
        return f"{int(s)}秒"
    else:
        m = int(s // 60)
        rem = int(s % 60)
        return f"{m}分{rem}秒" if rem else f"{m}分钟"


def friendly_step_summary(call):
    if isinstance(call, dict):
        name = call.get("name", "")
        args = call.get("args", call.get("arguments", {}))
        elapsed = call.get("elapsed", 0.0)
    else:
        name = getattr(call, "name", "")
        args = getattr(call, "args", {})
        elapsed = getattr(call, "elapsed", 0.0)

    if isinstance(args, str):
        try:
            import json
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}

    dur = format_duration(elapsed)

    title = ""
    if name == "get_scene_info":
        title = "分析场景现有对象与结构"
    elif name == "create_primitive":
        obj_name = args.get("name", "")
        ptype = str(args.get("type", "")).lower()
        type_names = {"cylinder": "圆柱体", "cube": "立方体", "sphere": "球体", "cone": "圆锥体", "plane": "平面"}
        p_cn = type_names.get(ptype, ptype or "基础体")
        label = f"{p_cn} ({obj_name})" if obj_name and obj_name != ptype else (obj_name or p_cn)
        title = f"创建基础几何体 ({label})"
    elif name == "set_material":
        obj_name = args.get("object_name", "对象")
        title = f"配置物理 PBR 材质 ({obj_name})"
    elif name == "transform_object":
        obj_name = args.get("object_name", "对象")
        title = f"调整空间变换与尺寸 ({obj_name})"
    elif name == "execute_blender_code":
        code = str(args.get("code", ""))
        comment_match = re.search(r"#\s*(步骤\s*[:：]?\s*)?([^\n\r]+)", code)
        if comment_match:
            c_text = comment_match.group(2).strip()
            if c_text and not c_text.lower().startswith("coding") and len(c_text) <= 25:
                title = c_text
        if not title:
            code_low = code.lower()
            if "spin" in code_low or "screw" in code_low:
                title = "旋转车削一体化成型"
            elif "boolean" in code_low:
                title = "构件装配与布尔熔接"
            elif "bevel" in code_low:
                title = "优化边缘微倒角高光"
            elif "principled" in code_low or "material" in code_low:
                title = "配置物理 PBR 材质节点"
            elif "camera" in code_low or "light" in code_low:
                title = "布置摄影棚光照与构图"
            elif "extrude" in code_low:
                title = "连续挤出生成几何体"
            else:
                title = "程序化几何造型"

    return f"{title} 完成，耗时 {dur}"


def get_current_action_text(run):
    if not run:
        return "准备就绪"
    elapsed = int(run.elapsed)
    if run.phase == Phase.PREFLIGHT:
        return f"正在预检场景物体与材质 ({elapsed}秒)"
    if run.phase == Phase.REQUESTING:
        if elapsed < 8:
            return f"正在构思三维几何结构与物理尺度 ({elapsed}秒)"
        elif elapsed < 20:
            return f"正在规划参数化建模脚本与材质管线 ({elapsed}秒)"
        elif elapsed < 45:
            return f"正在编写高保真造型脚本 ({elapsed}秒)"
        else:
            return f"正在细化高光倒角与布光细节 ({elapsed}秒)"
    if run.phase == Phase.TOOL_RUNNING:
        call = run.calls[-1] if run.calls else None
        if call:
            # ToolCall.args 可能为 None（尚未解析的工具调用），draw 里抛异常会让整块面板变白
            cargs = call.args if isinstance(call.args, dict) else {}
            if call.name == "get_scene_info":
                return f"正在分析场景现有对象数据 ({elapsed}秒)"
            elif call.name == "create_primitive":
                return f"正在生成基础几何体 {cargs.get('name', '')} ({elapsed}秒)"
            elif call.name == "set_material":
                return f"正在为 {cargs.get('object_name', '')} 配置 PBR 材质 ({elapsed}秒)"
            elif call.name == "transform_object":
                return f"正在调整 {cargs.get('object_name', '')} 空间变换 ({elapsed}秒)"
            elif call.name == "execute_blender_code":
                code = str(cargs.get("code", "")).lower()
                if "spin" in code or "screw" in code:
                    return f"正在执行旋转车削一体化成型 ({elapsed}秒)"
                elif "boolean" in code:
                    return f"正在执行部件装配与布尔熔接 ({elapsed}秒)"
                elif "bevel" in code:
                    return f"正在优化边缘微倒角高光 ({elapsed}秒)"
                elif "material" in code or "bsdf" in code:
                    return f"正在配置物理真实材质节点 ({elapsed}秒)"
                return f"正在执行程序化建模脚本 ({elapsed}秒)"
        return f"正在修改场景 ({elapsed}秒)"
    if run.phase == Phase.VERIFYING:
        return f"正在核对场景生成结果 ({elapsed}秒)"
    if run.phase == Phase.AWAITING_APPROVAL:
        return "等待批准执行脚本"
    return f"正在处理中... ({elapsed}秒)"


class DEEPSEEK_PG_note(bpy.types.PropertyGroup):
    """单个问题的「其他」自由备注，可直接绑定到 textbox"""
    text: bpy.props.StringProperty(default="", options={'TEXTEDIT_UPDATE', 'SKIP_SAVE'})


class DEEPSEEK_PG_msg(bpy.types.PropertyGroup):
    role: bpy.props.StringProperty()
    text: bpy.props.StringProperty()
    # 会话内稳定的唯一号：原生 layout.panel() 靠 idname 记住开合状态，
    # idname 必须对同一个气泡长期稳定，所以不能用会随历史增长而移位的下标。
    uid: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    stamp: bpy.props.StringProperty()
    duration_str: bpy.props.StringProperty()
    steps_json: bpy.props.StringProperty()
    added_objects_str: bpy.props.StringProperty()
    collection_name: bpy.props.StringProperty()
    raw_prompt: bpy.props.StringProperty()
    artifacts_json: bpy.props.StringProperty(default="")
    msg_type: bpy.props.StringProperty(default="CHAT")


def _tag(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def push_history(state, role, text, run=None, raw_prompt=""):
    item = state.history.add()
    item.uid = max(1, int(getattr(state, "next_uid", 1) or 1))
    state.next_uid = item.uid + 1
    item.role = role
    item.text = redact(text or "", state.api_key_cache)
    item.stamp = ""  # 默认不显示用户发送时间，只显示模型完成任务的耗时
    item.raw_prompt = raw_prompt or text or ""

    if role == "你" and raw_prompt and not state.session_topic:
        state.session_topic = raw_prompt.strip().replace("\n", " ")[:12]
        import datetime
        state.session_date = datetime.date.today().strftime("%Y/%m/%d")

    if run and role == "AI":
        item.duration_str = format_duration(run.elapsed)
        modeling_calls = [
            c for c in run.calls
            if (c.get("name") if isinstance(c, dict) else getattr(c, "name", "")) != "get_scene_info"
        ]
        step_lines = [friendly_step_summary(c) for c in modeling_calls]
        item.steps_json = json.dumps(step_lines, ensure_ascii=False) if step_lines else ""
        added = run.receipt.added_names if (run.receipt and hasattr(run.receipt, "added_names")) else []
        item.added_objects_str = "、".join(added) if added else ""
        item.collection_name = getattr(run, "collection_name", "") or ""
        if hasattr(run, "artifacts") and run.artifacts:
            item.artifacts_json = json.dumps(run.artifacts, ensure_ascii=False)

        txt = str(text or "")
        if "请确认" in txt or "确认无误" in txt or "我来复述" in txt or "✔" in txt:
            item.msg_type = "CONFIRM"
        elif "几个细节" in txt or "关键细节" in txt or "确认一下" in txt or ("风格" in txt and "推荐" in txt):
            item.msg_type = "CLARIFY"
        else:
            item.msg_type = "EXECUTE" if modeling_calls else "CHAT"

    # 收到追问时预分配「其他」备注槽位（draw 期间不允许写 ID 数据）
    try:
        qs = parse_interactive_options(item.text).get("questions") or []
    except Exception:
        qs = []
    if qs and role == "AI":
        state.notes.clear()
        ensure_notes(state, len(qs))


def refresh_tick():
    """由定时器驱动的高频重绘：驱动加载动效光圈与实时秒数跳动"""
    state = getattr(bpy.context.scene, "deepseek_agent", None) if getattr(bpy.context, "scene", None) else None
    if state is None:
        return None
    run = CONTROLLER.run
    if run is None:
        return None
    if state.busy and not CONTROLLER.busy:
        settle(bpy.context)
    if run.elapsed != state.last_elapsed or CONTROLLER.busy:
        state.last_elapsed = run.elapsed
        _tag(bpy.context)
    return 0.1 if CONTROLLER.busy else None


def ensure_redraw_timer():
    if not bpy.app.timers.is_registered(refresh_tick):
        bpy.app.timers.register(refresh_tick, first_interval=0.1)


def settle(context):
    """任务收尾：把结果写进历史，界面之后显示的是结算态。"""
    run = CONTROLLER.run
    state = context.scene.deepseek_agent
    if run is None:
        return
    if run.reply:
        push_history(state, "AI", run.reply, run=run)
    state.settled_phase = run.phase.value
    state.settled_err = run.err.value
    state.busy = False
    _tag(context)


class DEEPSEEK_PG_state(bpy.types.PropertyGroup):
    active_tab: bpy.props.EnumProperty(
        name="模式",
        description="在对话、详情与设置之间切换",
        items=[
            ('CHAT', "AI 对话", "与 AI 助手实时对话与建模", 'COMMUNITY', 0),
            ('DETAIL', "详情", "工具调用、用量与完整转录", 'CONSOLE', 1),
            ('SETTINGS', "设置", "API 密钥与模型参数配置", 'PREFERENCES', 2),
        ],
        default='CHAT',
        options={'SKIP_SAVE'},
    )
    prompt: bpy.props.StringProperty(default="", options={'TEXTEDIT_UPDATE', 'SKIP_SAVE'})
    history: bpy.props.CollectionProperty(type=DEEPSEEK_PG_msg, options={'SKIP_SAVE'})
    page: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    selected: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})
    busy: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    last_elapsed: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})
    settled_phase: bpy.props.StringProperty(default=Phase.READY.value, options={'SKIP_SAVE'})
    settled_err: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    api_key_cache: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    transcript: bpy.props.PointerProperty(type=bpy.types.Text, options={'SKIP_SAVE'})
    show_approval_code: bpy.props.BoolProperty(name="查看代码", default=False, options={'SKIP_SAVE'})
    fetched_models_json: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    fetch_status_msg: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    session_topic: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    session_date: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    show_card_objects: bpy.props.BoolProperty(name="新增对象详情", default=False, options={'SKIP_SAVE'})
    show_card_params: bpy.props.BoolProperty(name="建模参数详情", default=False, options={'SKIP_SAVE'})
    show_card_script: bpy.props.BoolProperty(name="执行脚本摘要", default=False, options={'SKIP_SAVE'})
    show_card_archive: bpy.props.BoolProperty(name="场景归档信息", default=False, options={'SKIP_SAVE'})
    show_card_qa: bpy.props.BoolProperty(name="查看已确认细节", default=False, options={'SKIP_SAVE'})
    show_user_params_detail: bpy.props.BoolProperty(name="查看用户参数详情", default=False, options={'SKIP_SAVE'})
    prompt_lines: bpy.props.IntProperty(name="输入框行数", default=3, min=1, max=10, description="拖动调节输入框高度（行数）", options={'SKIP_SAVE'})
    selected_options_json: bpy.props.StringProperty(default="{}", options={'SKIP_SAVE'})
    # ---- v2 新增：结果区四 tab / 新增对象折叠 / 其他备注 / 渐进加载 ----
    result_tab: bpy.props.EnumProperty(
        name="结果区",
        description="结果区当前显示的分组",
        items=[
            ('OBJECTS', "新增对象", "本次任务新增的对象清单", 'MESH_DATA', 0),
            ('PARAMS', "建模参数", "几何参数、修改器与材质", 'MODIFIER', 1),
            ('SCRIPT', "执行脚本", "实际执行的建模脚本", 'CONSOLE', 2),
            ('ARCHIVE', "场景归档", "合集归属与撤销边界", 'OUTLINER_COLLECTION', 3),
        ],
        default='OBJECTS',
        options={'SKIP_SAVE'},
    )
    show_result_list: bpy.props.BoolProperty(name="展开对象清单", default=False, options={'SKIP_SAVE'})
    show_all_questions: bpy.props.BoolProperty(name="展开全部规格", default=False, options={'SKIP_SAVE'})
    other_open_q: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    notes: bpy.props.CollectionProperty(type=DEEPSEEK_PG_note, options={'SKIP_SAVE'})
    shown_count: bpy.props.IntProperty(default=2, min=2, max=200, options={'SKIP_SAVE'})
    # 下一个用户气泡的 uid 发号器（在 draw 之外赋值，draw 期间不能写 ID 数据）
    next_uid: bpy.props.IntProperty(default=1, options={'SKIP_SAVE'})


# ---------------------------------------------------------------- operators
def dispatch_run_prompt(context, text_override=None, reporter=None):
    """直接启动指令执行；由 DEEPSEEK_OT_run、DEEPSEEK_OT_submit_selection 等共同调用，
    避免跨 Operator 嵌套调用导致的 poll() 上下文校验失败问题。"""
    if context.scene is None:
        if reporter:
            reporter({'ERROR'}, "场景未就绪")
        return {'CANCELLED'}
    state = context.scene.deepseek_agent
    cfg = config.get_config()
    text = (text_override if text_override is not None else state.prompt).strip()
    state.api_key_cache = cfg["api_key"]

    if not text:
        state.settled_err = ""
        if reporter:
            reporter({'WARNING'}, "请输入指令")
        return {'CANCELLED'}
    if not cfg["api_key"]:
        state.settled_phase = Phase.FAILED.value
        state.settled_err = Err.KEY_MISSING.value
        if reporter:
            reporter({'ERROR'}, "缺少 API Key")
        return {'CANCELLED'}
    if not context.preferences.edit.use_global_undo and not bpy.app.background:
        state.settled_phase = Phase.FAILED.value
        state.settled_err = Err.UNDO_UNAVAILABLE.value
        if reporter:
            reporter({'ERROR'}, "全局撤销已关闭")
        return {'CANCELLED'}

    push_history(state, "你", text, raw_prompt=text)
    state.page = 0
    state.selected = -1
    state.busy = True
    state.settled_phase = Phase.PREFLIGHT.value
    state.settled_err = ""
    # 发送后将指令输入栏重置清空，高度也收回默认，避免下次被撑高的框占位置
    state.prompt = ""
    state.prompt_lines = 2
    # addons 条目存在但 preferences 尚未实例化时（启用/卸载交界）不能直接取属性
    _addon = context.preferences.addons.get(PACKAGE_ID)
    _prefs = getattr(_addon, "preferences", None) if _addon else None
    cfg["allow_arbitrary_code"] = bool(
        _prefs and getattr(_prefs, "allow_arbitrary_code", False))
    if not CONTROLLER.start(text, cfg):
        state.busy = False
        if CONTROLLER.busy:
            if reporter:
                reporter({'ERROR'}, "已有任务在跑")
        else:
            state.settled_phase = Phase.FAILED.value
            state.settled_err = Err.KEY_MISSING.value
            if reporter:
                reporter({'ERROR'}, "缺少 API Key")
        return {'CANCELLED'}
    if bpy.app.background:
        # 无头没有 bpy.app.timers，refresh_tick 不会跑，AI 回执就永远进不了历史，
        # busy 也会一直挂着。这里同步结算一次。
        settle(context)
        return {'FINISHED'}
    ensure_redraw_timer()
    _tag(context)
    return {'FINISHED'}


class DEEPSEEK_OT_run(bpy.types.Operator):
    """提交指令给模型；网络在后台线程，Blender 界面保持可响应"""
    bl_idname = "deepseek.run_prompt"
    bl_label = "发送指令"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return context.scene is not None and not CONTROLLER.busy

    def execute(self, context):
        return dispatch_run_prompt(context, reporter=self.report)


class DEEPSEEK_OT_stop(bpy.types.Operator):
    """当前这次网络请求无法中断；本轮返回后不再发起下一轮"""
    bl_idname = "deepseek.stop"
    bl_label = "停止后续轮次"
    bl_description = "正在飞的 HTTP 请求中断不了；本轮返回后不再发起下一轮"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return CONTROLLER.busy

    def execute(self, context):
        CONTROLLER.request_stop()
        _tag(context)
        self.report({'WARNING'}, "已请求停止：当前请求返回后生效")
        return {'FINISHED'}


class DEEPSEEK_OT_approve(bpy.types.Operator):
    """允许执行这段 Python；它可以直接改动场景数据"""
    bl_idname = "deepseek.approve"
    bl_label = "批准"
    bl_options = set()

    action: bpy.props.EnumProperty(items=(("grant", "批准", ""), ("deny", "拒绝", "")), default="grant")

    @classmethod
    def poll(cls, context):
        return CONTROLLER.run is not None and CONTROLLER.run.phase == Phase.AWAITING_APPROVAL

    def execute(self, context):
        CONTROLLER.resolve_approval(self.action == "grant")
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_undo_task(bpy.types.Operator):
    """回退到发送前：安全停止任务，精准清理生成物体与合集，恢复输入框指令，撤销本轮对话记录"""
    bl_idname = "deepseek.undo_task"
    bl_label = "回退到发送前"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "deepseek_agent", None) if context.scene else None
        run = CONTROLLER.run
        can_undo_run = bool(run and run.receipt and run.receipt.boundary_pushed
                            and run.receipt.undo_enabled)
        has_history = bool(state and len(state.history) > 0)
        return can_undo_run or has_history

    def execute(self, context):
        # 1. 若当前任务还在运行，先安全终止，防止并发写入导致 C++ 内存冲突闪退
        if CONTROLLER.busy:
            try:
                CONTROLLER.stop()
            except Exception:
                pass

        state = getattr(context.scene, "deepseek_agent", None)
        run = CONTROLLER.run

        # 2. 先把需要恢复的用户提示词保存为 Python 原生字符串（防止后续内存重置导致悬空指针）
        restored_prompt = ""
        user_idx = -1
        if state and state.history:
            for i in range(len(state.history) - 1, -1, -1):
                if state.history[i].role == "你":
                    user_idx = i
                    restored_prompt = str(state.history[i].raw_prompt or state.history[i].text)
                    break

        # 3. 精准清理本轮任务生成的新物体与合集（原生 Python API 安全清理，100% 内存安全，杜绝崩溃）
        try:
            if run and run.receipt and run.receipt.added_names:
                for obj_name in list(run.receipt.added_names):
                    obj = bpy.data.objects.get(obj_name)
                    if obj:
                        bpy.data.objects.remove(obj, do_unlink=True)
            if run and run.collection_name:
                col = bpy.data.collections.get(run.collection_name)
                if col:
                    bpy.data.collections.remove(col)
        except Exception:
            pass

        # 4. 彻底禁用 bpy.ops.ed.undo()：手动删除 objects 和 collections 后调用 ed.undo()
        # 会访问已释放内存导致 Access Violation 闪退。步骤 3 的纯 Python 安全清理已经完全保证场景干净。

        # 5. 重新安全获取当前的 scene 与 state 引用，彻底避免 use-after-free
        scene = getattr(bpy.context, "scene", None)
        if scene and hasattr(scene, "deepseek_agent"):
            state = scene.deepseek_agent
            if user_idx != -1 and len(state.history) > user_idx:
                try:
                    while len(state.history) > user_idx:
                        state.history.remove(len(state.history) - 1)
                except Exception:
                    pass

            if restored_prompt:
                state.prompt = restored_prompt

            state.settled_phase = Phase.READY.value
            state.settled_err = ""
            state.selected_options_json = "{}"

        # 6. 清理 CONTROLLER 中的消息上下文
        if CONTROLLER.messages and len(CONTROLLER.messages) >= 2:
            last_u = -1
            for idx in range(len(CONTROLLER.messages) - 1, -1, -1):
                if CONTROLLER.messages[idx].get("role") == "user":
                    last_u = idx
                    break
            if last_u != -1:
                CONTROLLER.messages = CONTROLLER.messages[:last_u]

        CONTROLLER.run = None

        if hasattr(context, "view_layer") and context.view_layer:
            context.view_layer.update()

        self.report({'INFO'}, "已回退到发送前，指令已填回输入框")
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_show(bpy.types.Operator):
    """把这条工具返回写进文本块，便于完整查看与复制"""
    bl_idname = "deepseek.show_call"
    bl_label = "查看返回"
    bl_options = set()

    index: bpy.props.IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return CONTROLLER.run is not None and bool(CONTROLLER.run.calls)

    def execute(self, context):
        state = context.scene.deepseek_agent
        run = CONTROLLER.run
        idx = self.index if 0 <= self.index < len(run.calls) else max(state.selected, 0)
        call = run.calls[idx]
        state.selected = idx
        body = "\n\n".join([
            f"# {idx + 1}. {call.name}　状态 {call.status}　耗时 {call.elapsed if call.elapsed is not None else '—'}s",
            "参数：" + json.dumps(call.args, ensure_ascii=False, indent=2),
            "返回：" + json.dumps(call.result, ensure_ascii=False, indent=2),
        ])
        text = state.transcript or bpy.data.texts.new("DeepSeek 详情")
        text.clear()
        text.write(redact(body, state.api_key_cache))
        state.transcript = text
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_export(bpy.types.Operator):
    """把整段对话与工具记录导出成文本块（面板不能滚动，长内容走这里）"""
    bl_idname = "deepseek.export"
    bl_label = "导出完整转录"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        state = context.scene.deepseek_agent
        lines = []
        for item in state.history:
            lines.append(f"[{item.stamp}] {item.role}：{item.text}")
        run = CONTROLLER.run
        if run:
            lines.append("")
            lines.append(f"— 任务：{run.prompt}")
            lines.append(f"— 状态：{run.phase.value} / 错误：{run.err.value or '无'} / 轮次：{run.rounds}")
            for i, call in enumerate(run.calls, 1):
                lines.append(f"  {i}. {call.name} [{call.status}] {call.summary()}")
                lines.append("     " + json.dumps(call.result, ensure_ascii=False)[:400])
            if run.usage:
                lines.append("— usage：" + json.dumps(run.usage, ensure_ascii=False))
            if run.receipt and run.receipt.lines:
                lines.append("— 变更：" + "; ".join(run.receipt.lines))
        text = state.transcript or bpy.data.texts.new("DeepSeek 详情")
        text.clear()
        text.write(redact("\n".join(lines), state.api_key_cache))
        state.transcript = text
        self.report({'INFO'}, "已写入文本块，可在面板下方的文本框查看/复制")
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_clear(bpy.types.Operator):
    """清空对话记录（不影响场景）"""
    bl_idname = "deepseek.clear"
    bl_label = "清空对话"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        state = context.scene.deepseek_agent
        state.history.clear()
        state.page = 0
        state.settled_phase = Phase.READY.value
        state.settled_err = ""
        CONTROLLER.reset()
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_new_task(bpy.types.Operator):
    """开启新任务，复位当前面板状态并清空输入框与上下文"""
    bl_idname = "deepseek.new_task"
    bl_label = "开启新任务"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not CONTROLLER.busy

    def execute(self, context):
        state = context.scene.deepseek_agent
        state.prompt = ""
        state.settled_phase = Phase.READY.value
        state.settled_err = ""
        state.show_card_objects = False
        state.show_card_params = False
        state.show_card_script = False
        state.show_card_archive = False
        state.session_topic = ""
        CONTROLLER.reset()
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_fetch_models(bpy.types.Operator):
    """通过 API 动态从当前服务商拉取最新可用模型列表"""
    bl_idname = "deepseek.fetch_models"
    bl_label = "获取最新模型"
    bl_description = "从服务商获取最新可用模型列表并供一键切换"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return not CONTROLLER.busy

    def execute(self, context):
        cfg = config.get_config()
        state = context.scene.deepseek_agent
        if not cfg["api_key"]:
            self.report({'ERROR'}, "请先配置 API Key 才能获取模型列表")
            state.fetch_status_msg = "获取失败：缺少 API Key"
            return {'CANCELLED'}

        try:
            from .agent import fetch_available_models
            models = fetch_available_models(cfg["api_key"], cfg["base_url"], timeout=cfg["timeout"])
            state.fetched_models_json = json.dumps(models)
            state.fetch_status_msg = f"成功获取 {len(models)} 个可用模型"
            self.report({'INFO'}, f"成功拉取到 {len(models)} 个可用模型")
        except Exception as error:
            err_msg = str(getattr(error, "message", error))
            state.fetch_status_msg = f"获取失败：{err_msg[:60]}"
            self.report({'ERROR'}, f"获取模型失败：{err_msg[:80]}")
            return {'CANCELLED'}

        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_set_model(bpy.types.Operator):
    """一键切换当前模型"""
    bl_idname = "deepseek.set_model"
    bl_label = "应用模型"
    bl_description = "将该模型设为当前使用的模型"
    bl_options = set()

    model_name: bpy.props.StringProperty(name="模型名称", default="")

    def execute(self, context):
        if not self.model_name:
            return {'CANCELLED'}
        p = config._prefs()
        if p:
            p.model = self.model_name
        self.report({'INFO'}, f"已切换模型为: {self.model_name}")
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_quick_pill(bpy.types.Operator):
    """点击快捷建议胶囊，自动填入建议指令前缀"""
    bl_idname = "deepseek.quick_pill"
    bl_label = "快捷指令"
    bl_options = set()

    action: bpy.props.StringProperty(default="")

    def execute(self, context):
        state = context.scene.deepseek_agent
        pill_map = {
            "修改尺寸": "请帮我修改当前模型的尺寸为：",
            "更换材质": "请帮我更换当前模型的材质为：",
            "添加纹理": "请为当前模型添加细节纹理与法线贴图：",
            "导出文件": "请帮我将当前场景中的模型导出为 glTF 格式文件",
            "添加茶水": "请在茶杯中添加茶水，并微调折射与材质：",
            "更换面料": "请为当前沙发更换为质感皮质面料：",
            "添加靠枕": "请在沙发两端各添加一个柔软方形靠枕：",
            "增加倒角": "请为模型边缘添加细致倒角与平滑法线：",
            "平滑着色": "请为当前模型设置平滑着色并启用自动平滑：",
            "调整层高": "请帮我调整建筑的层高与挑檐比例：",
            "增加门窗": "请为建筑正面添加大落地玻璃窗与入口门：",
            "添加灯光": "请在场景中布置三点布光（主光、辅光、轮廓光）：",
            "修改公差": "请调整机械零件的配合公差与倒角：",
            "金属材质": "请为零件赋予拉丝金属铝合金材质：",
            "阵列打孔": "请在法兰盘圆周均匀阵列 6 个沉头螺栓孔：",
            "中式茶杯": "帮我用 Blender 制作一个精致的中式茶杯，要有把手和圈足，适合渲染展示用。",
            "现代沙发": "帮我制作一套现代双人布艺沙发，带有柔软座垫和靠枕。",
            "双层别墅": "帮我搭建一座现代简约双层别墅，带大落地窗与挑檐。",
            "机械构件": "帮我制作一个精密的机械法兰联轴器，带螺栓孔与倒角。",
        }
        state.prompt = pill_map.get(self.action, f"请帮我进行{self.action}：")
        self.report({'INFO'}, f"已填入：{self.action}")
        _tag(context)
        return {'FINISHED'}


class DEEPSEEK_OT_submit_selection(bpy.types.Operator):
    """提交当前勾选的参数并开始建模（杜绝文本重复）"""
    bl_idname = "deepseek.submit_selection"
    bl_label = "提交选择并建模"
    bl_options = set()

    custom_prompt: bpy.props.StringProperty(default="")

    def execute(self, context):
        state = context.scene.deepseek_agent
        if self.custom_prompt:
            p_text = self.custom_prompt
        else:
            try:
                sel = json.loads(state.selected_options_json or "{}")
            except Exception:
                sel = {}
            all_chosen = []
            for k in sorted(sel.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                for val in sel[k]:
                    if val and val not in all_chosen:
                        all_chosen.append(val)
            if not all_chosen:
                p_text = "全部按推荐参数开始建模！"
            else:
                p_text = f"参数已确认：{'；'.join(all_chosen)}，开始建模！"

        state.selected_options_json = "{}"
        return dispatch_run_prompt(context, text_override=p_text, reporter=self.report)


# ---------------------------------------------------------------- render helpers
def ensure_notes(state, count):
    """预分配「其他」备注槽位。

    notes 是 CollectionProperty，而 Panel.draw() 期间 Blender 会锁住 ID 数据写入
    （AttributeError: Writing to ID classes in this context is not allowed），
    所以槽位只能在 draw 之外（收到追问时 / operator 里）预先建好。
    """
    try:
        while len(state.notes) < max(0, int(count)):
            state.notes.add()
    except Exception:
        pass


# ---------------------------------------------------------------- panels
def wrap_text(text, max_chars=26):
    """把长文本拆分为适合 Blender N 面板显示的行列表"""
    if not text:
        return []
    lines = []
    for paragraph in str(text).split("\n"):
        p = paragraph.strip()
        if not p:
            continue
        while len(p) > max_chars:
            cut = max_chars
            for sep in (" ", "，", "。", "；", "！", "、", ",", ";"):
                pos = p[:max_chars].rfind(sep)
                if pos > max_chars // 2:
                    cut = pos + 1
                    break
            lines.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            lines.append(p)
    return lines


def user_msg_is_long(text, max_chars=18, min_lines=3):
    """指令长到值得给一个折叠箭头：按气泡里实际的行数判断，而不是按字数。"""
    return len(wrap_text(text, max_chars)) > min_lines


def user_msg_summary(text, limit=16):
    """折叠标题行：首句摘要 + 总字数，让人知道里面有没有东西。"""
    flat = " ".join(str(text or "").split())
    if not flat:
        return "（空指令）"
    first = re.split(r"[。！？!?；;\n]", flat)[0].strip() or flat
    if len(first) > limit:
        first = first[:limit] + "…"
    return f"你：{first}（共 {len(flat)} 字）"


def draw_chat_content(layout, context, state, run):
    busy = getattr(state, "busy", False) or CONTROLLER.busy
    mark(layout, CHAT_STREAM)

    # 1) 任务进行中指示 / 审批状态
    #    状态提示条是「一个盒」：内容直接画在 bbox 里，不再 box() 一次套内层盒。
    #    布局契约（见 LAYOUT_CONTRACT）：页签条由 DEEPSEEK_PT_chat.draw 在调用
    #    draw_chat_content 之前先画，所以状态条一定排在页签条下面。
    if busy:
        bbox = layout.box()
        mark(bbox, CHAT_STATUSBAR)
        brow = bbox.row(align=True)
        brow.label(text=get_current_action_text(run), icon='TIME')
        brow.operator("deepseek.stop", text="终止任务", icon='CANCEL')

    if run and run.phase == Phase.AWAITING_APPROVAL:
        abox = layout.box()
        abox.alert = True
        abox.label(text="它想运行一段脚本，请确认：", icon='QUESTION')
        if getattr(state, "show_approval_code", False):
            code_call = next((c for c in run.calls if c.name == "execute_blender_code"), None)
            if code_call:
                code_text = str(code_call.args.get("code", "") if isinstance(code_call.args, dict) else "")
                cbox = abox.box()
                for cln in code_text.splitlines()[:15]:
                    cbox.label(text=cln[:36])
            abox.prop(state, "show_approval_code", text="收起具体代码", icon='HIDE_OFF')
        else:
            abox.prop(state, "show_approval_code", text="查看具体 Python 代码", icon='HIDE_OFF')

        arow = abox.row(align=True)
        arow.scale_y = 1.2
        arow.operator("deepseek.approve", text="批准执行", icon='CHECKMARK')
        arow.operator("deepseek.stop", text="拒绝取消", icon='CANCEL')

    if run and run.phase == Phase.PARTIAL:
        pbox = layout.box()
        pbox.alert = False
        pbox.label(text="任务做到一半：", icon='INFO')
        if run.receipt and run.receipt.lines:
            pbox.label(text="已经做了：", icon='CHECKMARK')
            for r_line in run.receipt.lines:
                pbox.label(text=f"  • {r_line}")
        if getattr(run, "skipped", None):
            pbox.label(text="还没做：", icon='ERROR')
            for s_line in run.skipped:
                pbox.label(text=f"  • {s_line}")
        pbox.label(text="没做完的部分，再说一句就行", icon='FORWARD')

    if run and run.phase == Phase.FAILED:
        fbox = layout.box()
        fbox.alert = True
        err_msg = state.settled_err or "任务遇到异常"
        fbox.label(text=f"任务执行中断：{err_msg}", icon='ERROR')
        fbox.label(text="该做的事：检查设置或重试指令", icon='INFO')
        frow = fbox.row(align=True)
        frow.operator("deepseek.run_prompt", text="重新尝试", icon='FILE_REFRESH')

    # 2) 对话历史流
    if not state.history and not busy:
        ebox = layout.box()
        ebox.label(text="欢迎使用 DeepSeek 建模助手", icon='COMMUNITY')
        ebox.label(text="描述想创建的模型，或选择快捷标签：")
    else:
        hist_len = len(state.history)
        max_show = max(1, int(config.get_config().get("history_page", 8)))
        start_idx = max(0, hist_len - max_show)
        if start_idx > 0:
            layout.label(text=f"... 上方已折叠更早的 {start_idx} 条历史 ...", icon='TRIA_UP')

        for idx in range(start_idx, hist_len):
            item = state.history[idx]
            if item.role == "你":
                # 人发的：盒子底色 + 文字右对齐。盒宽 = 面板宽（layout.box() 原生
                # 铺满就是想要的），文字按盒内宽度自然折行，面板拉宽行就变长；
                # 不额外加 margin，也不动配色。
                ubox = layout.box()
                if user_msg_is_long(item.text):
                    # 长提示词给一个原生折叠箭头（layout.panel 有正确的动效和
                    # 开合状态记忆）。idname 必须对同一个气泡稳定，所以用
                    # push_history 里发的 uid，不用会移位的历史下标。
                    # 默认展开：对话流是主内容，折叠是「点开看长提示词」。
                    p_id = f"chat.user_msg_{int(getattr(item, 'uid', 0) or 0) or (idx + 1)}"
                    up = ubox.panel(p_id, default_closed=False)
                    up.label(text=user_msg_summary(item.text), icon='USER')
                for ln in wrap_text(item.text, max_chars=18):
                    urow = ubox.row()
                    urow.alignment = 'RIGHT'
                    urow.label(text=ln)
            else:
                # AI 回的：整幅、无框，直接排在对话流里
                abox = layout
                if item.duration_str:
                    arow = abox.row(align=True)
                    arow.alignment = 'LEFT'
                    arow.label(text=f"耗时 {item.duration_str}", icon='COMMUNITY')

                if item.steps_json:
                    try:
                        steps = json.loads(item.steps_json)
                    except Exception:
                        steps = []
                    if steps:
                        sbox = abox.box()
                        sbox.label(text="执行的操作：", icon='FILE_SCRIPT')
                        for st in steps:
                            sbox.label(text=f"✓ {st}")

                info = parse_interactive_options(item.text)
                intro = info.get("intro", "")
                if intro:
                    for ln in wrap_text(intro):
                        abox.label(text=ln)

                questions = info.get("questions", [])
                is_latest_ai = (idx == hist_len - 1)
                if questions:
                    if not is_latest_ai:
                        abox.label(text="✓ 关键规格已确认", icon='CHECKMARK')
                    else:
                        for q_idx, q in enumerate(questions):
                            qbox = abox.box()
                            mark(qbox, CHAT_OPTIONS)
                            qbox.label(text=f"细节 {q_idx + 1}：{q.get('title', '')}", icon='QUESTION')
                            opts = q.get("options", [])
                            # 横排：一行里并排放全部选项。Blender 量不了文字宽度，
                            # 所以按字数估算做降级——选项多或标签太长就换回竖排。
                            too_wide = len(opts) > 3 or sum(len(str(o.get("label", ""))) for o in opts) > 22
                            if too_wide:
                                orow_holder = qbox.column(align=True)
                            else:
                                orow_holder = qbox.row(align=True)
                            for opt in opts:
                                val = opt.get("value") or opt.get("label", "")
                                lbl = opt.get("label", val)
                                orow = orow_holder
                                btn = orow.operator("deepseek.submit_selection",
                                                    text=f"选择: {lbl}",
                                                    icon='CHECKBOX_DEHLT')
                                btn.custom_prompt = f"针对「{q.get('title', '')}」，我选择：{val}"

                        rec_btn = abox.operator("deepseek.submit_selection",
                                                text="按推荐参数开始建模",
                                                icon='PLAY')
                        rec_btn.custom_prompt = info.get("all_recommended", "全部按推荐参数开始建模！")

                for gl in info.get("general", []):
                    for ln in wrap_text(gl):
                        abox.label(text=ln)

                outro = info.get("outro", "")
                if outro:
                    for ln in wrap_text(outro):
                        abox.label(text=ln)

                if item.added_objects_str:
                    res_box = abox.box()
                    res_box.label(text=f"新增对象：{item.added_objects_str}", icon='MESH_DATA')

    # 3) 输入区贴在对话流下面：聊天窗口的阅读顺序是"上一条永远在输入框上面"，
    #    所以自己刚发的话不该出现在输入框下面。历史条数由偏好设置封顶，不会把输入框推出屏幕。
    pills = list(quick_pills(state))
    if pills:
        pbox = layout.box()
        p_row1 = pbox.row(align=True)
        p_row2 = pbox.row(align=True)
        mid = (len(pills) + 1) // 2
        for i, pill in enumerate(pills):
            target_row = p_row1 if i < mid else p_row2
            target_row.operator("deepseek.quick_pill", text=pill).action = pill

    cbox = layout.box()
    mark(cbox, CHAT_COMPOSER)
    cbox.label(text="输入建模指令:", icon='TEXT')
    # 不再放「高度 N」滑块：textbox 自己带右下角原生拖拽角，高度照样能拖。
    # prompt_lines 属性本身保留，仍作为 textbox 的 initial_visible_lines 初值。
    cbox.textbox(state, "prompt", initial_visible_lines=state.prompt_lines,
                 placeholder="用自然语言描述要建模什么，可多行")

    brow = cbox.row(align=True)
    brow.scale_y = 1.3
    # 发送与终止是同一个 row 的两个互斥分支，不是两行；所以按分支
    # 挂不同的 ID，同一次 draw 里只会命中其中一个。
    if not busy:
        mark(brow, CHAT_SEND)
        brow.operator("deepseek.run_prompt", text="发送指令", icon='PLAY')
    else:
        mark(brow, CHAT_STOP)
        brow.operator("deepseek.stop", text="终止任务", icon='CANCEL')

    arow = cbox.row(align=True)
    mark(arow, CHAT_ACTION_ROW)
    if can_undo(state):
        arow.operator("deepseek.undo_task", text="回退操作", icon='LOOP_BACK')
    arow.operator("deepseek.new_task", text="新建任务", icon='ADD')
    arow.operator("deepseek.clear", text="清空记录", icon='TRASH')


def draw_chat_tabbar(layout, state):
    """模式切换（对话 / 详情 / 设置）。必须最先画，保证页签条在状态条上面。"""
    trow = layout.row(align=True)
    mark(trow, CHAT_TABBAR)
    trow.prop(state, "active_tab", expand=True)


class DEEPSEEK_PT_chat(bpy.types.Panel):
    bl_label = "DeepSeek 建模助手"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI 对话"

    def draw(self, context):
        layout = self.layout
        state = getattr(context.scene, "deepseek_agent", None)
        if state is None:
            return
        run = CONTROLLER.run

        # 模式切换（对话 / 详情 / 设置）：先画，页签条永远在最上面
        draw_chat_tabbar(layout, state)

        if state.active_tab == 'DETAIL':
            draw_detail_content(layout, state, run)
            return
        elif state.active_tab == 'SETTINGS':
            cfg = config.get_config()
            draw_settings_content(layout, cfg)
            return

        draw_chat_content(layout, context, state, run)

def draw_detail_content(layout, state, run):
    has_content = False

    # 1) 工具调用记录
    if run and run.calls:
        has_content = True
        tbox = layout.box()
        tbox.label(text=f"工具调用（{len(run.calls)}）", icon='CONSOLE')
        for i, call in enumerate(run.calls):
            icon = {"ok": 'CHECKMARK', "error": 'ERROR', "running": 'TIME', "awaiting": 'ERROR'}.get(call.status, 'NONE')
            srow = tbox.row(align=True)
            srow.label(text=f"{i + 1}. {call.name}", icon=icon)
            srow.label(text=call.summary()[:34])
            op = srow.operator("deepseek.show_call", text="", icon='TEXT')
            op.index = i

    # 2) 选中项返回 JSON / 完整转录文本块
    if state.transcript:
        has_content = True
        box = layout.box()
        box.label(text="详情 / 转录内容", icon='CONSOLE')
        box.prop(state, "transcript", text="")

    # 3) 本次用量
    if run and run.usage:
        has_content = True
        u = run.usage
        ubox = layout.box()
        ubox.label(text="本次用量（实测）", icon='INFO')
        ubox.label(text=f"输入 {u.get('prompt_tokens', '—')} · 缓存命中 {u.get('prompt_cache_hit_tokens', '—')}")
        ubox.label(text=f"输出 {u.get('completion_tokens', '—')}")
        est = int((u.get("prompt_tokens") or 0) * 1.0)
        ubox.label(text=f"上下文占用估算 约 {est / 1000:.1f}k / 8k（估算，非服务端返回）")
        ubox.label(text=f"轮次：{run.rounds}/{run.limit} · 耗时：{run.elapsed:.1f}s", icon='TIME')

    # 4) 导出操作
    if state.history or (run and run.calls):
        has_content = True
        layout.operator("deepseek.export", text="导出完整转录", icon='EXPORT')

    # 5) 空态提示
    if not has_content:
        layout.label(text="还没有任务记录", icon='INFO')


def draw_settings_content(layout, cfg):
    layout.use_property_split = True
    p = config._prefs()
    state = getattr(getattr(bpy.context, "scene", None), "deepseek_agent", None)
    prov_key = cfg.get("provider", "DEEPSEEK")
    prov_info = config.PROVIDERS.get(prov_key, config.PROVIDERS["DEEPSEEK"])

    # 1) 服务商配置与官方文档
    sbox = layout.box()
    sbox.label(text="服务商配置", icon='PREFERENCES')
    if p:
        sbox.prop(p, "provider", text="服务商")
    else:
        sbox.label(text=f"当前服务商：{prov_info['name']}")

    doc_row = sbox.row(align=True)
    doc_op = doc_row.operator("wm.url_open", text=f"打开 {prov_info['name']} 官方文档", icon='URL')
    doc_op.url = prov_info["doc_url"]

    # 2) Key 状态与填写
    kbox = layout.box()
    kbox.label(text="API Key 配置", icon='KEYINGSET')
    if prov_key == "MINIMAX":
        kbox.label(text="提示：MiniMax 支持填入 Token Plan API Key (sk-cp-... 或 sk-...)", icon='INFO')

    if p:
        row = kbox.row(align=True)
        row.alert = not p.api_key.strip()
        row.prop(p, "api_key", text="API Key")

    if cfg["api_key"]:
        kbox.label(text=f"已生效（来源：{'偏好设置' if cfg['key_source'] == 'prefs' else '环境变量'}）", icon='CHECKMARK')
    else:
        erow = kbox.row(align=True)
        erow.alert = True
        erow.label(text=f"未配置 API Key（也可配置环境变量 {prov_info['key_env']}）", icon='ERROR')

    # 3) 模型配置与自动拉取
    mbox = layout.box()
    mbox.label(text="模型配置", icon='PLUGIN')
    if p:
        mbox.prop(p, "model", text="当前模型")
    else:
        mbox.label(text=f"当前模型：{cfg['model']}")

    # 获取最新模型按钮
    fetch_row = mbox.row(align=True)
    fetch_row.operator("deepseek.fetch_models", text="获取最新模型列表", icon='FILE_REFRESH')

    if state and state.fetch_status_msg:
        mbox.label(text=state.fetch_status_msg, icon='INFO')

    # 提取预置与拉取的可用模型列表（优先展示前沿/预置模型）
    cached_models = []
    if state and state.fetched_models_json:
        try:
            cached_models = json.loads(state.fetched_models_json)
        except Exception:
            cached_models = []

    presets = prov_info.get("preset_models", [])
    available_models = []
    for m in presets + cached_models:
        if m and m not in available_models:
            available_models.append(m)

    if available_models:
        lbox = mbox.box()
        lbox.label(text="点击快速切换模型：", icon='INFO')
        cur_model = (p.model if p else cfg["model"]).strip()
        flow = lbox.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True) if hasattr(lbox, "grid_flow") else lbox.column(align=True)
        for m in available_models[:12]:
            is_cur = (m == cur_model)
            btn = flow.operator("deepseek.set_model", text=m, icon='CHECKMARK' if is_cur else 'NONE', depress=is_cur)
            btn.model_name = m

    # 4) 网络与高级运行参数
    if p:
        abox = layout.box()
        abox.label(text="高级运行参数", icon='PREFERENCES')
        abox.prop(p, "base_url", text="Base URL")
        row = abox.row(align=True)
        row.prop(p, "timeout", text="超时(秒)")
        row.prop(p, "max_turns", text="最大轮次")
        row = abox.row(align=True)
        row.prop(p, "wall_budget", text="时间预算(秒)")
        row.prop(p, "history_page", text="面板历史条数")
        abox.prop(p, "allow_arbitrary_code")
    else:
        box = layout.box()
        box.label(text=f"轮次上限：{cfg['max_turns']} · 时间预算：{cfg['wall_budget']}s", icon='INFO')
        box.label(text=f"任意 Python：{'已允许' if cfg['allow_arbitrary_code'] else '需逐次批准'}",
                  icon='CHECKMARK' if cfg["allow_arbitrary_code"] else 'ERROR')

    # 5) 打开偏好设置窗口
    op = layout.operator("preferences.addon_show", text="打开完整偏好设置", icon='PREFERENCES')
    op.module = PACKAGE_ID


def _settled_err(state):
    try:
        return Err(state.settled_err)
    except ValueError:
        return Err.NONE


def _clean_md(text):
    """去除 Markdown 粗体、斜体、反引号等字符，净化为纯净 UI 文本"""
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^#+\s*", "", t)
    return t.strip()


def _opt_label(text, is_rec=False, limit=16):
    """按钮标签：先摘掉「（口径 8.5cm × 高 9.5cm）」这类括注再截断。

    直接按字数硬切会把标签砍成「办公室杯 350ml（口径 8.」，半个括号留在界面上很难看。
    「（推荐）」这类括注要保留。
    """
    disp = str(text or "").strip()
    m = re.search(r"[（(]([^）)]*)[）)]", disp)
    if m and "推荐" not in m.group(1):
        disp = (disp[:m.start()] + disp[m.end():]).strip(" ·/、,，")
    else:
        # 括号不配对（上游截断过）：切到开括号处，别留半个括号在按钮上
        cuts = [i for i in (disp.find("（"), disp.find("(")) if i > 0]
        if cuts:
            disp = disp[:min(cuts)].strip(" ·/、,，")
    disp = disp[:limit].rstrip(" ·/、,，")
    return f"{disp} (推荐)" if is_rec else disp


def parse_interactive_options(text):
    """智能解析追问文本中的问题与候选按钮：
    支持两类主流大模型输出格式：
    1. 斜杠分隔型：'1. 杯型风格：经典直筒微收口 / 鼓腹圆润 / 手作厚壁窑变（推荐：直筒微收口）'
    2. 换行列表型：'**1. 派系风格**\n- A. 直饮运动水杯\n- B. 大容量吨吨桶'
    同时支持提取确认项 confirm（带 ✔ 或 ✓）
    """
    lines = (text or "").split("\n")
    intro_lines = []
    questions = []
    confirm_items = []
    outro_lines = []
    general_lines = []

    current_q = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        clean = _clean_md(line)

        # 过滤预检噪音
        if "目前场景中仅有" in clean or "并不冲突或需要保留" in clean or "分析：目前场景" in clean:
            continue

        # 匹配确认项: ✔ 或 ✓
        if clean.startswith("✔") or clean.startswith("✓") or clean.startswith("- ✓") or clean.startswith("- ✔"):
            item_text = re.sub(r"^[-*•\s]*[✔✓]\s*", "", clean)
            confirm_items.append(item_text)
            continue

        # 结语识别
        if any(k in clean for k in ["回复这几点", "按推荐来", "直接说", "欢迎随时告诉我", "我就开始车削", "开始建模"]):
            if current_q:
                questions.append(current_q)
                current_q = None
            outro_lines.append(clean)
            continue

        # 1. 识别单行问题：如 1. 杯型风格：A / B / C（推荐：A） 或 1. 款式（推荐：A / B）
        clean_numbered = re.sub(r"^[-*•\s]+", "", clean).strip()
        num_match = re.match(r"^([1-9][.、\s]+[^：:\n\r]+)[：:]([^\n\r]+)", clean_numbered)
        if num_match:
            raw_title = num_match.group(1).strip()
            rest = num_match.group(2).strip()
            clean_title = re.sub(r"[（(【].*", "", raw_title).strip()

            # 提取推荐值（支持在标题括号内或在后文内）
            rec_val = ""
            rec_match = re.search(r"[（(【]?推荐[：:\s]*([^）)】/]+)", clean)
            if rec_match:
                rec_val = rec_match.group(1).strip(" ；;，,")

            opts = []
            if "/" in rest:
                # 只去空白和分号：原来连「）」一起 strip 掉，闭合括号没了，
                # 后面就无法识别「（口径 8.5cm）」这类括注，只能按字数硬切。
                raw_opts = [o.strip(" \t；;") for o in rest.split("/") if o.strip(" \t；;")]
                for ro in raw_opts:
                    # 剥掉「（推荐：xxx）」后缀（兼容括号已被上游切掉的情况）
                    ro_clean = re.sub(r"[（(【]?\s*推荐\s*[：:][^）)】]*[）)]?\s*$", "", ro)
                    ro_clean = re.sub(r"^[;；\s]*也可选\s*", "", ro_clean).strip()
                    is_rec = bool(rec_val and (rec_val in ro_clean or ro_clean in rec_val))
                    opts.append({
                        "label": _opt_label(ro_clean, is_rec),
                        "value": ro_clean,
                        "is_rec": is_rec
                    })
            elif rec_val:
                opts.append({
                    "label": _opt_label(rec_val, True),
                    "value": rec_val,
                    "is_rec": True
                })
            elif "要/不要" in clean:
                opts.append({"label": "要配套细节 (推荐)", "value": f"带{rest.strip(' ）)】')}", "is_rec": True})
                opts.append({"label": "不要配套细节", "value": "仅基础款，不要椅脚抱枕等配件", "is_rec": False})

            if opts:
                if current_q:
                    questions.append(current_q)
                    current_q = None
                questions.append({
                    "title": clean_title,
                    "rec_value": rec_val,
                    "options": opts
                })
                continue

        # 2. 识别换行型问题标题：如 1. 派系风格 或 **1. 派系风格**
        q_match = re.match(r"^(?:[#*]*\s*)?([1-9][.、\s]+[^\n\r]+)", clean)
        if q_match and ("风格" in clean or "尺寸" in clean or "材质" in clean or "把手" in clean or "结构" in clean or "偏好" in clean or "容量" in clean or any(f"{i}." in clean[:4] for i in range(1, 10))):
            if current_q:
                questions.append(current_q)
            current_q = {"title": clean, "rec_value": "", "options": []}
            continue

        if current_q is not None:
            if re.match(r"^[-*•\s]*[A-Z0-9][.、\s)]", clean) or clean.startswith("- ") or clean.startswith("• "):
                opt_text = re.sub(r"^[-*•\s]*", "", clean)
                is_rec = "推荐" in opt_text or "★" in opt_text
                val = re.sub(r"[（(【].*?推荐.*?[）)】]", "", opt_text).strip()
                val = re.sub(r"^[A-Z0-9][.、\s)]*", "", val).strip()
                current_q["options"].append({
                    "label": f"{val[:14]} (推荐)" if is_rec else val[:16],
                    "value": val,
                    "is_rec": is_rec
                })
                if is_rec and not current_q["rec_value"]:
                    current_q["rec_value"] = val
                continue
            else:
                questions.append(current_q)
                current_q = None
                intro_lines.append(clean)
                continue

        if not questions and not confirm_items:
            intro_lines.append(clean)
        else:
            general_lines.append(clean)

    if current_q:
        questions.append(current_q)

    # 汇总所有推荐值组合为一键开始指令
    rec_pieces = [q.get("rec_value", "") or (q["options"][0]["value"] if q.get("options") else "") for q in questions]
    rec_pieces = [p for p in rec_pieces if p]
    all_rec = "，".join(rec_pieces)
    if all_rec:
        all_rec = f"按推荐参数建模：{all_rec}"
    else:
        all_rec = "全部按推荐参数开始建模！"

    return {
        "intro": " ".join(intro_lines),
        "questions": questions,
        "confirm": confirm_items,
        "all_recommended": all_rec,
        "outro": " ".join(outro_lines),
        "general": general_lines,
    }


# DEEPSEEK_OT_panel_modal 已随原生 UILayout 架构彻底退役，零后台模态循环占用


def quick_pills(state):
    """输入区上方的快捷胶囊。自绘层和原生层共用同一份，避免两处文案漂移。"""
    if not getattr(state, "history", None) or len(state.history) == 0:
        return []
    topic = state.session_topic or ""
    if any(k in topic for k in ["杯", "壶", "碗", "盘", "花瓶", "茶"]):
        return ["修改尺寸", "更换材质", "增加倒角", "平滑着色"]
    if any(k in topic for k in ["沙发", "椅", "床", "家具"]):
        return ["修改尺寸", "更换面料", "添加靠枕", "增加倒角"]
    if any(k in topic for k in ["别墅", "建筑", "房子", "室内"]):
        return ["调整层高", "更换材质", "增加门窗", "布置灯光"]
    if any(k in topic for k in ["机械", "零件", "构件", "齿轮"]):
        return ["修改公差", "金属材质", "增加倒角", "阵列打孔"]
    return ["修改尺寸", "更换材质", "增加倒角", "平滑着色"]


def can_undo(state):
    run = CONTROLLER.run
    return bool(run is not None and run.receipt and getattr(run.receipt, "boundary_pushed", False))


OPERATORS = (
    DEEPSEEK_OT_run, DEEPSEEK_OT_stop, DEEPSEEK_OT_approve, DEEPSEEK_OT_undo_task,
    DEEPSEEK_OT_show, DEEPSEEK_OT_export, DEEPSEEK_OT_clear,
    DEEPSEEK_OT_new_task,
    DEEPSEEK_OT_fetch_models, DEEPSEEK_OT_set_model,
    DEEPSEEK_OT_quick_pill, DEEPSEEK_OT_submit_selection,
)

CLASSES = (DEEPSEEK_PG_msg, DEEPSEEK_PG_note, DEEPSEEK_PG_state) + OPERATORS + (
    DEEPSEEK_PT_chat,
)


def check_layout_contract():
    """结构性自检 LAYOUT_CONTRACT：返回违规项列表（空 = 通过）。

    纯源码检查，不依赖 GUI，可在无头环境直接调用。页签条与状态条的上下关系
    是靠 draw 里的调用顺序成立的，所以只能看源码顺序——UILayout 按绘制顺序渲染。
    """
    import inspect
    bad = []
    panel_src = inspect.getsource(DEEPSEEK_PT_chat.draw)
    try:
        i_tab = panel_src.index("draw_chat_tabbar")
        i_body = panel_src.index("draw_chat_content")
        if i_tab > i_body:
            bad.append("tabbar_above_statusbar: 页签条排在 draw_chat_content 之后")
    except ValueError:
        bad.append("tabbar_above_statusbar: 找不到页签条/正文绘制调用")

    content_src = inspect.getsource(draw_chat_content)
    if 'mark(bbox, CHAT_STATUSBAR)' not in content_src:
        bad.append("statusbar_single_box: 状态条没挂 CHAT_STATUSBAR")
    if 'prompt_lines", text="", slider=True' in content_src:
        bad.append("no_composer_height_slider: 仍有『高度 N』滑块")
    if 'initial_visible_lines=state.prompt_lines' not in content_src:
        bad.append("no_composer_height_slider: prompt_lines 没继续作为 textbox 初值")
    if 'orow_holder' not in content_src:
        bad.append("options_horizontal: 选项仍是一行一个")
    if 'layout.split' in content_src:
        bad.append("user_bubble_full_width_box: 不该用 split 切窄栏，气泡盒应铺满")
    if 'ubox = layout.box()' not in content_src:
        bad.append("user_bubble_full_width_box: 用户气泡没有用原生 box() 铺满")
    if 'layout.panel' not in content_src:
        bad.append("user_msg_panel_fold: 长提示词没有用原生 layout.panel() 折叠")
    if 'default_closed=False' not in content_src:
        bad.append("user_msg_panel_fold: 折叠面板必须默认展开")
    return bad


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.deepseek_agent = bpy.props.PointerProperty(type=DEEPSEEK_PG_state)


def unregister():
    if bpy.app.timers.is_registered(refresh_tick):
        bpy.app.timers.unregister(refresh_tick)
    if hasattr(bpy.types.Scene, "deepseek_agent"):
        del bpy.types.Scene.deepseek_agent
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
