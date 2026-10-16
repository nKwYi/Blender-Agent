# -*- coding: utf-8 -*-
"""原生 UILayout 架构与交互无头回归测试。

验证：
1. 零 GPU POST_PIXEL 渲染，零后台模态循环；
2. DEEPSEEK_PT_chat 的 bl_category 为原生 'AI 对话'；
3. 原生 draw_chat_content 完整性：空状态、运行态、审批态、追问单选态、完成态；
4. 所有原生 Operator 正确注册并在 bpy.ops.deepseek 下可用；
5. 回退/撤销操作纯 Python 安全执行，不引发内存段错误。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import ui as U
from blender_deepseek_agent.state import Phase, Run, ToolCall
from blender_deepseek_agent.receipt import Receipt

FAILS = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}: {msg}")
        FAILS.append(name)


class MockLayout:
    def __init__(self, kind="layout", parent=None):
        self.kind = kind
        self.parent = parent
        self.texts = []
        self.operators = []
        self.props = []
        self.children = []
        self.alert = False
        self.enabled = True
        self.scale_y = 1.0
        self.scale_x = 1.0

    def label(self, text="", icon='NONE'):
        if text:
            self.texts.append(str(text))

    def textbox(self, data, prop_name, **kwargs):
        self.texts.append("TEXTBOX:" + str(prop_name))
        self.props.append({"data": data, "prop": prop_name, "text": "", "kwargs": kwargs})

    def prop(self, data, prop_name, text="", **kwargs):
        self.props.append({"data": data, "prop": prop_name, "text": text})
        if text:
            self.texts.append(str(text))

    def operator(self, op_id, text="", icon='NONE'):
        self.operators.append({"id": op_id, "text": text, "icon": icon})

        class OpDummy:
            def __setattr__(self, name, value):
                pass
        return OpDummy()

    def box(self):
        b = MockLayout("box", parent=self)
        self.children.append(b)
        return b

    def panel(self, idname, default_closed=False, layout_header=None,
              layout_body=None):
        # 真实 Blender 4.1+/5.x 的 UILayout.panel() 返回二元组 (layout_header, layout_body)
        header = MockLayout("panel_header", parent=self)
        body = MockLayout("panel_body", parent=self)
        header.panel_idname = idname
        body.panel_idname = idname
        header.panel_default_closed = bool(default_closed)
        body.panel_default_closed = bool(default_closed)
        self.children.extend([header, body])
        return (header, body)

    def row(self, align=False):
        r = MockLayout("row", parent=self)
        self.children.append(r)
        return r

    def column(self, align=False):
        c = MockLayout("column", parent=self)
        self.children.append(c)
        return c

    def split(self, factor=0.5, **kw):
        # 真实 Blender 4.x/5.x 的 UILayout.split() 返回**单个** layout，
        # 是左边那一列（宽 = factor × 内容宽）；右边那列 Python 拿不到。
        # 这里原来返回 2.8 时代的 (a, b) 元组，比真实 API 旧，会让测试跟真实
        # 行为脱节 —— ui.py 里那段 isinstance(col, tuple) 兜底就是被它逼出来的。
        # align 在 5.2 是 **bool 不是枚举**，传 'LEFT'/'RIGHT' 会 TypeError，
        # 所以这里只接受真假值。
        if isinstance(kw.get("align"), str):
            raise TypeError(
                "Function.align expected True/False or 0/1, not %r" % kw["align"])
        a = MockLayout("split", parent=self)
        self.children.append(a)
        return a

    def separator(self, factor=1.0):
        pass

    def all_texts(self):
        out = list(self.texts)
        for ch in self.children:
            out.extend(ch.all_texts())
        return out

    def all_operators(self):
        out = list(self.operators)
        for ch in self.children:
            out.extend(ch.all_operators())
        return out

    def all_props(self):
        out = list(self.props)
        for ch in self.children:
            out.extend(ch.all_props())
        return out

    def all_tokens(self):
        """按文档顺序的合并 token 流：('text', 文本) / ('prop', 属性名) / ('op', 算子名)。

        all_texts() / all_props() / all_operators() 各自维护自己的列表，是
        三条**平行**序列，互相之间比不出先后。任何「A 出现在 B 之前」而 A/B
        又不是同一种东西的断言，都必须走这个——否则两个 -1 相减恒成立，
        断言看着在验顺序、其实什么都没验。
        """
        out = [("text", t) for t in self.texts]
        out += [("prop", p["prop"]) for p in self.props]
        out += [("op", o["id"]) for o in self.operators]
        for ch in self.children:
            out.extend(ch.all_tokens())
        return out


def _all_layouts(node):
    yield node
    for ch in node.children:
        yield from _all_layouts(ch)


def host_alignment_of(node, needle):
    for t in _all_layouts(node):
        if any(needle in x for x in t.texts):
            return getattr(t, "alignment", None)
    return None


def main():
    bda.register()

    # 1. 验证零 GPU POST_PIXEL 渲染与零后台模态循环
    ck("gpu_modules_removed", not any(m.startswith("blender_deepseek_agent.") and
        m.split(".")[-1] in ("runtime", "workspace", "panel", "painter", "theme", "look")
        for m in sys.modules), "GPU 自绘模块必须已从包里移除")
    ck("no_panel_modal", not hasattr(bpy.types, "DEEPSEEK_OT_panel_modal"), "DEEPSEEK_OT_panel_modal 必须已退役注销")

    # 2. 验证原生面板分类与属性
    ck("chat_panel_registered", hasattr(bpy.types, "DEEPSEEK_PT_chat"), "DEEPSEEK_PT_chat 必须已注册")
    ck("category_is_ai_chat", U.DEEPSEEK_PT_chat.bl_category == "AI 对话", "面板分类必须为 'AI 对话'")
    ck("space_is_view_3d", U.DEEPSEEK_PT_chat.bl_space_type == "VIEW_3D", "面板空间必须为 VIEW_3D")
    ck("region_is_ui", U.DEEPSEEK_PT_chat.bl_region_type == "UI", "面板区域必须为 UI (N 面板)")

    scene = bpy.context.scene
    state = scene.deepseek_agent

    # 3. 验证空状态原生布局
    state.active_tab = "CHAT"
    state.history.clear()
    state.prompt = ""
    U.CONTROLLER.run = None

    layout_empty = MockLayout()
    U.draw_chat_content(layout_empty, bpy.context, state, None)
    all_empty_texts = layout_empty.all_texts()
    all_empty_ops = [op["id"] for op in layout_empty.all_operators()]
    all_empty_props = layout_empty.all_props()

    ck("empty_has_welcome", any("欢迎使用建模助手" in t for t in all_empty_texts), "空状态下应有欢迎引导")
    ck("welcome_has_no_brand_prefix", not any("欢迎使用 DeepSeek" in t for t in all_empty_texts),
       "品牌前缀已去掉，欢迎语不该再带 DeepSeek")
    ck("empty_has_prompt_prop", any(p["prop"] == "prompt" for p in all_empty_props), "输入框必须使用原生 StringProperty")
    ck("empty_has_send_btn", "deepseek.run_prompt" in all_empty_ops, "必须包含发送按钮 deepseek.run_prompt")

    # 4. 验证运行中状态原生布局（进度条与终止按钮）
    run_busy = Run("生成机械齿轮")
    run_busy.phase = Phase.TOOL_RUNNING
    run_busy.elapsed = 12.5
    run_busy.calls = [ToolCall("1", "execute_blender_code", {"code": "bmesh.ops.bevel"})]
    U.CONTROLLER.run = run_busy

    layout_busy = MockLayout()
    U.draw_chat_content(layout_busy, bpy.context, state, run_busy)
    all_busy_texts = layout_busy.all_texts()
    all_busy_ops = [op["id"] for op in layout_busy.all_operators()]

    ck("busy_shows_elapsed", any("12" in t for t in all_busy_texts), "运行中需展示耗时")
    ck("busy_shows_step", any("倒角" in t for t in all_busy_texts), "运行中需展示当前步骤")
    ck("busy_has_stop_btn", "deepseek.stop" in all_busy_ops, "运行中必须包含终止按钮")

    # 5. 验证审批态原生布局（批准与拒绝按钮）
    run_approve = Run("批量删除场景物体")
    run_approve.phase = Phase.AWAITING_APPROVAL
    run_approve.approval_preview = "即将清理场景中的 12 个废弃网格"
    U.CONTROLLER.run = run_approve

    layout_approve = MockLayout()
    U.draw_chat_content(layout_approve, bpy.context, state, run_approve)
    all_approve_ops = [op["id"] for op in layout_approve.all_operators()]

    ck("approve_has_approve_btn", "deepseek.approve" in all_approve_ops, "审批态需包含 deepseek.approve 按钮")
    ck("approve_has_reject_btn", "deepseek.stop" in all_approve_ops, "审批态需包含终止/拒绝按钮")

    # 6. 验证追问选项与单选交互原生布局
    run_done = Run("中式茶壶")
    run_done.phase = Phase.COMPLETED
    U.CONTROLLER.run = run_done

    state.history.clear()
    msg_ai = state.history.add()
    msg_ai.role = "AI"
    msg_ai.text = "1. 壶身器型：西施壶（圆润鼓腹，推荐） / 石瓢壶（梯形骨架）"

    layout_clarify = MockLayout()
    U.draw_chat_content(layout_clarify, bpy.context, state, run_done)
    all_clarify_ops = layout_clarify.all_operators()
    submit_ops = [op for op in all_clarify_ops if op["id"] == "deepseek.submit_selection"]

    ck("clarify_has_options", any("西施壶" in op["text"] for op in submit_ops), "选项按钮必须以原生 operator 渲染")
    ck("clarify_has_recommend_btn", any("按推荐参数开始建模" in op["text"] for op in submit_ops), "需提供快速开始建模按钮")

    # 6b. 验证圈号与全角斜杠等真实追问格式解析能力
    state.history.clear()
    msg_ai_snow = state.history.add()
    msg_ai_snow.role = "AI"
    msg_ai_snow.text = (
        "雪屋小场景，先确认几个核心细节（括号内是我的推荐）：\n"
        "① 雪屋风格：冰屋（推荐）／ 半球体+螺旋雪砖 ／ 烟囱 A 字木屋\n"
        "② 场景范围：纯雪屋（推荐）／ 加旗杆等氛围道具\n"
        "直接回复选项编号，立刻开始建模。"
    )
    layout_snow = MockLayout()
    U.draw_chat_content(layout_snow, bpy.context, state, run_done)
    snow_submit_ops = [op for op in layout_snow.all_operators() if op["id"] == "deepseek.submit_selection"]
    ck("snow_clarify_has_options", any("冰屋" in op["text"] for op in snow_submit_ops), "圈号与全角斜杠格式必须被正确解析为按钮")
    ck("snow_clarify_has_rec_btn", any("按推荐参数开始建模" in op["text"] for op in snow_submit_ops), "圈号格式下必须生成一键推荐建模按钮")

    # 7. 输入区必须在历史之前：侧栏只能整体滚动，输入框排到长历史下面就用不了
    state.history.clear()
    # 「你」的消息是偶数下标。把 22 号做成**够长**的一条：只有它折成两行以上，
    # 「首行缩进」和「每行都缩进」才区分得开。
    for i in range(24):
        if i == 22:
            U.push_history(state, "你",
                           "历史消息 22：做一个精致的中式紫砂茶杯，杯身要能看出"
                           "砂颗粒的质感，把手做成竹节形，壶嘴短一点")
        else:
            U.push_history(state, "你" if i % 2 == 0 else "AI", f"历史消息 {i}")
    layout_order = MockLayout()
    U.draw_chat_content(layout_order, bpy.context, state, run_done)
    seq = layout_order.all_texts()
    tok = layout_order.all_tokens()
    idx_input = next((n for n, (k, v) in enumerate(tok) if k == "prop" and v == "prompt"), -1)
    idx_first_hist = next((n for n, (k, v) in enumerate(tok) if k == "text" and "历史消息" in v), -1)
    ck("输入区不再有『输入建模指令:』标签行",
       not any("输入建模指令" in v for k, v in tok if k == "text"),
       "那一栏应当已删除")
    ck("输入区排在历史之后（上一条永远在输入框上面）",
       0 <= idx_first_hist < idx_input,
       f"idx_input={idx_input} idx_first_hist={idx_first_hist}")
    ck("顶部不再有『会话: xxx / 可连续追问』占位栏",
       not any("会话:" in t or "可连续追问" in t for t in seq), str(seq[:6]))

    def host_kind_of(needle):
        for t in _all_layouts(layout_order):
            if any(needle in x for x in t.texts):
                chain = []
                cur = t
                while cur is not None:
                    chain.append(cur.kind)
                    cur = getattr(cur, "parent", None)
                return chain
        return []

    # 一问一答样式（最新规范）：
    #   你说的话 -> 无框，使用 split(factor=0.20) 靠右侧排布（左侧留空 20% 缩进），文字仅首行缩进两格
    #   AI 回的话 -> 整段一个盒，且右边留一段间距
    ck("人的消息没有盒子", "box" not in host_kind_of("历史消息 22"),
       "用户消息应当无框，实际宿主链=%r" % (host_kind_of("历史消息 22"),))
    ck("人的消息靠右分栏", "split" in host_kind_of("历史消息 22"),
       "用户消息应当在 split 列里靠右排布，实际宿主链=%r" % (host_kind_of("历史消息 22"),))
    # 只有「你」说的话缩进，而且**只缩首行** —— AI 的回复不进盒也不缩进。
    # 22 号那条长指令折出来的所有行 = 从它那行到下一条历史消息之前那一段。
    # 用切片而不是按内容过滤：折行后的续行不含「历史消息」字样，按内容筛只能
    # 捞到第一行 —— 那正是上一版断言空过的原因。
    i22 = next((i for i, t in enumerate(seq) if "历史消息 22" in t), -1)
    j = next((k for k in range(i22 + 1, len(seq)) if "历史消息" in seq[k]), len(seq))
    tea_lines = seq[i22:j] if i22 >= 0 else []
    short_user = [t for t in seq if "历史消息 22" in t]
    ai_msgs = [t for t in seq if "历史消息 21" in t or "历史消息 23" in t]
    ck("长用户消息确实折成了多行（否则下面两条断言无从区分）",
       len(tea_lines) >= 2,
       "长指令应折行，实际只有 %d 行：%r" % (len(tea_lines), tea_lines))
    ck("只有首行缩进两格，续行顶格",
       bool(tea_lines) and tea_lines[0].startswith("　　")
       and all(not t.startswith("　　") for t in tea_lines[1:]),
       "首行应缩进、续行不应：%r" % (tea_lines,))
    ck("短用户消息也缩进（单行时首行就是全部）",
       bool(short_user) and all(t.startswith("　　") for t in short_user),
       "单行用户消息的首行也要缩进：%r" % (short_user,))
    ck("用户消息行右对齐贴边", host_alignment_of(layout_order, "历史消息 22") == 'RIGHT',
       "用户消息行应设置 alignment='RIGHT' 贴右排布，实际=%r" % (host_alignment_of(layout_order, "历史消息 22"),))
    t_snow = "按推荐参数建模：北欧童话木屋，桌景微缩18cm，原木 + 厚白雪顶，烟囱 + 雪堆 + 松树 + 木栅栏"
    lines_snow = U.wrap_text(t_snow, max_chars=22, first_chars=20)
    ck("符号空格不提前截断", any("雪堆" in l for l in lines_snow if "烟囱" in l),
       "烟囱行应包含雪堆，不应提前在+空格截断造成大空隙：%r" % (lines_snow,))
    ck("AI 的消息不缩进", all(not t.startswith("　　") for t in ai_msgs),
       "AI 的话不进盒也不缩进：%r" % ai_msgs)
    ck("AI 整段套一个盒", "box" in host_kind_of("历史消息 21"),
       "AI 回复应当整段一个盒，实际宿主链=%r" % (host_kind_of("历史消息 21"),))
    ck("AI 那个盒右边留了间距", "split" in host_kind_of("历史消息 21"),
       "AI 盒子应当画在 split 的列里、右侧留白，实际宿主链=%r"
       % (host_kind_of("历史消息 21"),))
    ck("AI 只有一个盒（规格区不再单独成盒）",
       host_kind_of("历史消息 21").count("box") == 1,
       "盒数应当严格是 1，实际宿主链=%r" % (host_kind_of("历史消息 21"),))
    ck("不再只靠左上角名称区分角色",
       not any(t in ("用户", "AI 助手") for t in seq), str([t for t in seq if "助手" in t or t == "用户"]))
    shown = sum(1 for t in seq if "历史消息" in t)
    page = max(1, int(U.config.get_config()["history_page"]))
    ck("历史条数跟随偏好设置（不是写死的 8）", shown == page, f"shown={shown} history_page={page}")

    # 7b) N 侧栏只允许一个入口：详情/设置靠面板内的模式切换，不再各占一个原生分类
    categories = {c.bl_category for c in U.CLASSES if getattr(c, "bl_region_type", None) == 'UI'}
    ck("N 侧栏只有一个分类", categories == {"AI 对话"}, str(categories))
    tb = [p for p in layout_order.all_props() if p.get("kwargs")]
    ck("输入框是多行 textbox", len(tb) == 1 and tb[0]["prop"] == "prompt", str(tb))
    ck("输入框行数可配置", tb and tb[0]["kwargs"].get("initial_visible_lines") == state.prompt_lines,
       str(tb[0]["kwargs"]) if tb else "no textbox")

    # 8. 验证安全回滚（不调用崩毁内存的 bpy.ops.ed.undo）
    state.prompt = ""
    res = bpy.ops.deepseek.undo_task()
    ck("undo_executes_safely", res == {'FINISHED'}, "deepseek.undo_task 执行安全返回 FINISHED")

    # 9. 总结报告
    print("")
    print("=" * 42)
    print(f"RESULT native_ui: {len(FAILS)} failed, {TOTAL[0] - len(FAILS)} passed")
    print("=" * 42)
    if FAILS:
        sys.exit(1)


if __name__ == "__main__":
    main()
