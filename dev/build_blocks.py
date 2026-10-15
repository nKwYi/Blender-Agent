# -*- coding: utf-8 -*-
"""生成 ui_workbench/blocks.json —— 提案视图的「业务块」词汇表。

为什么要换掉 API 积木：用户试了很多轮还是说「不会用」。诊断结论是把
Blender 的 API 当成了他的词汇表——横排/竖排/元素 ID/参数/uiloayout/归属，
这 6 个概念比它要解决的问题还难。低代码平台不会让你想 flexbox，它给你
「客户表格」「审批表单」。所以这一轮把词汇表整个换掉：工作台的第一眼
是「这个界面由哪几块业务块组成」，UILayout 原语退到折叠的高级区。

铁律：**每块业务块都必须对应 blender_deepseek_agent/ui.py 里真实存在的代码。**
ui_py 字段就是那段代码原样抄过来的（去掉 mark() 挂 ID 的那几行——元素 ID
由导出时写成注释，不混在代码里）。导出时直接用它，不做翻译：这样导出的东西
天然和插件里的一致，不会出现「生成了但 Blender 画不出来」的代码。

文案可改，但只许改**字符串字面量的内容**：editable 里的每一项在 slots 里
对应一条 ui_py 里逐字出现的引号字符串，app.js 导出时把那个字面量换成
重新转义过的新字面量——所以用户改文案也改不坏语法（这是本脚本要守住的：
每一行的引号必须成对，见 main() 里的自检）。
"""
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI_PY = os.path.join(ROOT, "blender_deepseek_agent", "ui.py")
OUT = os.path.join(ROOT, "ui_workbench", "blocks.json")

TAB_LABELS = {"chat": "对话", "detail": "详情", "settings": "设置"}


class BlockError(Exception):
    pass


def pyq(s, fstring=False):
    """按 Python 字面量转义一个字符串。导出时也走同一套规则，两边不会打架。

    fstring=True 时补上 f 前缀：ui.py 里有些文案本来就是 f-string
    （text=f"选择: {lbl}"），照抄必须连前缀一起，否则插值就丢了。
    """
    body = '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return ("f" + body) if fstring else body


def dedent(lines):
    body = [ln for ln in lines if ln.strip()]
    if not body:
        return ""
    cut = min(len(ln) - len(ln.lstrip()) for ln in body)
    return "\n".join(ln[cut:].rstrip() for ln in lines).strip("\n")


def V(key, label, what, lines, demo=None, rewrites=None):
    """一个变体。rewrites 登记这一段里每一处「不与 ui.py 逐字相同」的行。

    为什么要这张表：块要能**独立**导出成函数里的一段，而 ui.py 里的代码
    常常挂在上一行的局部变量上（abox / cbox 都是 layout 的子盒）。
    硬抄过来就得把上一个块的变量一起拖进来，所以有几行改绑到 layout。
    改就是改——所以逐行声明，dev/test_proposal_blocks.py 的
    blocks_rewrites_declared 断言会核对：凡是没登记的差异都算编造。
    """
    return {"key": key, "label": label, "what": what,
            "ui_py": dedent(lines), "demo": demo,
            "rewrites": list(rewrites or [])}


def finalize(doc):
    """把每个块的块级 ui_py 补成默认变体那段（逐字一致，导出直接用它）。

    为什么块级还要再存一份：导出与「复制这一块」都只认块级这一个入口，
    而 variants 里那份是给变体下拉用的。两者必须逐字相同，否则同一块
    在预览和导出里会讲两个版本的故事——所以 _selfcheck 会核对它。
    """
    for b in doc["blocks"]:
        dv = [v for v in b["variants"] if v["key"] == b["default_variant"]][0]
        b["ui_py"] = dv["ui_py"]
    return doc


# --------------------------------------------------------------------------
# 16 块业务块。每一段 ui_py 后面括注的是它在 blender_deepseek_agent/ui.py
# 里的出处（行号随 ui.py 改动会漂，dev/test_proposal_blocks.py 的
# blocks_grounded_in_ui_py 断言会逐字回查 ui.py，漂了就红）。
# --------------------------------------------------------------------------
def build():
    blocks = []

    # ---- 对话 tab（7 块）------------------------------------------------
    b_busy = ["bbox = layout.box()",
              "brow = bbox.row(align=True)",
              "brow.label(text=get_current_action_text(run), icon='TIME')",
              "brow.operator(\"deepseek.stop\", text=%s, icon='CANCEL')" % pyq("终止任务")]

    b_appr = ["abox = layout.box()",
              "abox.alert = True",
              "abox.label(text=%s, icon='QUESTION')" % pyq("它想运行一段脚本，请确认："),
              'if getattr(state, "show_approval_code", False):',
              '    code_call = next((c for c in run.calls if c.name == "execute_blender_code"), None)',
              "    if code_call:",
              '        code_text = str(code_call.args.get("code", "") if isinstance(code_call.args, dict) else "")',
              "        cbox = abox.box()",
              '        for cln in code_text.splitlines()[:15]:',
              "            cbox.label(text=cln[:36])",
              '    abox.prop(state, "show_approval_code", text="收起具体代码", icon=\'HIDE_OFF\')',
              "else:",
              '    abox.prop(state, "show_approval_code", text="查看具体 Python 代码", icon=\'HIDE_OFF\')',
              "",
              "arow = abox.row(align=True)",
              "arow.scale_y = 1.2",
              'arow.operator("deepseek.approve", text=%s, icon=\'CHECKMARK\')' % pyq("批准执行"),
              'arow.operator("deepseek.stop", text=%s, icon=\'CANCEL\')' % pyq("拒绝取消")]

    b_part = ["pbox = layout.box()",
              "pbox.alert = False",
              "pbox.label(text=%s, icon='INFO')" % pyq("任务做到一半："),
              "if run.receipt and run.receipt.lines:",
              "    pbox.label(text=%s, icon='CHECKMARK')" % pyq("已经做了："),
              "    for r_line in run.receipt.lines:",
              '        pbox.label(text=f"  • {r_line}")',
              'if getattr(run, "skipped", None):',
              "    pbox.label(text=%s, icon='ERROR')" % pyq("还没做："),
              "    for s_line in run.skipped:",
              '        pbox.label(text=f"  • {s_line}")',
              "pbox.label(text=%s, icon='FORWARD')" % pyq("没做完的部分，再说一句就行")]

    b_fail = ["fbox = layout.box()",
              "fbox.alert = True",
              'err_msg = state.settled_err or %s' % pyq("任务遇到异常"),
              'fbox.label(text=f"任务执行中断：{err_msg}", icon=\'ERROR\')',
              "fbox.label(text=%s, icon='INFO')" % pyq("该做的事：检查设置或重试指令"),
              "frow = fbox.row(align=True)",
              'frow.operator("deepseek.run_prompt", text=%s, icon=\'FILE_REFRESH\')' % pyq("重新尝试")]

    status_slots = [
        {"name": "btn", "label": "终止按钮文字", "text": "终止任务",
         "literal": pyq("终止任务")},
        {"name": "title", "label": "标题文字", "text": "它想运行一段脚本，请确认：",
         "literal": pyq("它想运行一段脚本，请确认：")},
        {"name": "done", "label": "标题文字", "text": "已经做了：",
         "literal": pyq("已经做了：")},
        {"name": "todo", "label": "副标题", "text": "还没做：",
         "literal": pyq("还没做：")},
        {"name": "hint", "label": "副标题", "text": "没做完的部分，再说一句就行",
         "literal": pyq("没做完的部分，再说一句就行")},
        {"name": "err", "label": "标题文字", "text": "任务遇到异常",
         "literal": pyq("任务遇到异常")},
        {"name": "advice", "label": "副标题", "text": "该做的事：检查设置或重试指令",
         "literal": pyq("该做的事：检查设置或重试指令")},
        {"name": "retry", "label": "按钮文字", "text": "重新尝试",
         "literal": pyq("重新尝试")},
    ]
    # 一个块的 slots 是这个块「全部可改文案」的目录，不是每个变体都全带：
    # 状态提示条的四个变体各有各的字面量，busy 里根本没有「已经做了：」。
    # 「这个变体里哪些槽可改」由 _selfcheck 逐变体数出来核对。

    blocks.append({
        "key": "chat_status",
        "label": "状态提示条",
        "tab": "chat",
        "what": "任务在跑的时候，面板顶部那一整条。四种样子：正在跑、等你批准、做到一半、失败。",
        "variants": [
            V("busy", "忙碌中", "正在跑，显示当前动作 + 终止按钮", b_busy,
              {"kind": "box", "items": ["正在改你的场景 · 第 2 步", "终止任务"]}),
            V("approve", "待批准", "它想执行代码，等你点头", b_appr,
              {"kind": "box", "items": ["它想运行一段脚本，请确认：", "批准执行", "拒绝取消"]}),
            V("partial", "做到一半", "分已做 / 未做两栏", b_part,
              {"kind": "box", "items": ["任务做到一半：", "已经做了：", "还没做："]}),
            V("failed", "失败", "整个界面唯一的报错块", b_fail,
              {"kind": "box", "items": ["任务执行中断：…", "重新尝试"]}),
        ],
        "default_variant": "busy",
        "editable": ["终止按钮文字", "标题文字", "副标题", "按钮文字"],
        "slots": status_slots,
        "element_id": "chat.statusbar",
        "demo": {"kind": "box", "items": ["正在改你的场景 · 第 2 步", "终止任务"]},
    })

    blocks.append({
        "key": "chat_tabbar",
        "label": "页签条",
        "tab": "chat",
        "what": "面板最顶上那三个页签（对话 / 详情 / 设置）。插件里是真实面板的一部分。",
        "variants": [V("only", "三个页签", "对话 / 详情 / 设置，点哪个画哪个",
                       ["trow = layout.row(align=True)",
                        'trow.prop(state, "active_tab", expand=True)'],
                       {"kind": "row", "items": ["AI 对话", "详情", "设置"]})],
        "default_variant": "only",
        "editable": [],
        "slots": [],
        "element_id": "chat.tabbar",
        "demo": {"kind": "row", "items": ["AI 对话", "详情", "设置"]},
    })

    user_box = ["ubox = layout.box()",
                "for ln in wrap_text(item.text, max_chars=18):",
                "    urow = ubox.row()",
                "    urow.alignment = 'RIGHT'",
                "    urow.label(text=ln)"]
    ai_box = ["if item.duration_str:",
              "    arow = layout.row(align=True)",
              "    arow.alignment = 'LEFT'",
              '    arow.label(text=f"耗时 {item.duration_str}", icon=\'COMMUNITY\')',
              "if item.steps_json:",
              "    sbox = layout.box()",
              "    sbox.label(text=%s, icon='FILE_SCRIPT')" % pyq("执行的操作："),
              "    for st in steps:",
              '        sbox.label(text=f"✓ {st}")',
              "if item.added_objects_str:",
              "    res_box = layout.box()",
              '    res_box.label(text=f"新增对象：{item.added_objects_str}", icon=\'MESH_DATA\')']
    bubble_slots = [{"name": "steps", "label": "小标题文字",
                     "text": "执行的操作：", "literal": pyq("执行的操作：")}]
    blocks.append({
        "key": "chat_bubble",
        "label": "消息气泡",
        "tab": "chat",
        "what": "对话流里的一条消息。你说的话装在盒子里右对齐，AI 的话不装框，直接排在流里。",
        "variants": [
            V("user", "你说的话", "装在盒子里、文字右对齐", user_box,
              {"kind": "box", "items": ["帮我做一个马克杯"]}),
            V("ai", "AI 回答", "不装框，带耗时 / 执行步骤 / 新增对象", ai_box,
              {"kind": "col", "items": ["耗时 12.4s", "执行的操作：", "新增对象：马克杯"]},
              rewrites=[
                  {"to": "arow = layout.row(align=True)",
                   "from": "arow = abox.row(align=True)",
                   "why": "ui.py 里 abox 就是 layout（AI 气泡不装框）；"
                          "独立导出时 abox 不在作用域，改绑 layout"},
                  {"to": "res_box = layout.box()",
                   "from": "res_box = abox.box()",
                   "why": "同上：新增对象那个盒子改绑 layout"},
              ]),
        ],
        "default_variant": "user",
        "editable": ["小标题文字"],
        "slots": bubble_slots,
        "element_id": "chat.stream",
        "demo": {"kind": "box", "items": ["帮我做一个马克杯"]},
    })

    q_lines = ["for q_idx, q in enumerate(questions):",
               "    qbox = layout.box()",
               '    qbox.label(text=f"细节 {q_idx + 1}：{q.get(\'title\', \'\')}", icon=\'QUESTION\')',
               '    for opt in q.get("options", []):',
               '        val = opt.get("value") or opt.get("label", "")',
               '        lbl = opt.get("label", val)',
               "        orow = qbox.row()",
               '        btn = orow.operator("deepseek.submit_selection",',
               "                            text=%s," % pyq("选择: {lbl}", fstring=True),
               "                            icon='CHECKBOX_DEHLT')",
               '        btn.custom_prompt = f"针对「{q.get(\'title\', \'\')}」，我选择：{val}"',
               "",
               'rec_btn = layout.operator("deepseek.submit_selection",',
               "                        text=%s," % pyq("按推荐参数开始建模"),
               "                        icon='PLAY')",
               'rec_btn.custom_prompt = info.get("all_recommended", "全部按推荐参数开始建模！")']
    q_slots = [{"name": "opt", "label": "选项按钮文字", "text": "选择: {lbl}",
                "literal": pyq("选择: {lbl}", fstring=True)},
               {"name": "rec", "label": "推荐按钮文字", "text": "按推荐参数开始建模",
                "literal": pyq("按推荐参数开始建模")}]
    q_rewrites = [
        {"to": "qbox = layout.box()", "from": "qbox = abox.box()",
         "why": "ui.py 里这一组挂在对话流 abox（就是 layout）里；独立导出改绑 layout"},
        {"to": "text=f\"选择: {lbl}\",",
         "from": "text=f\"选择: {lbl}\",",
         "why": "同一句，只是为了缩进对齐到 orow.operator 的续行而重折"},
        {"to": "rec_btn = layout.operator(\"deepseek.submit_selection\",",
         "from": "rec_btn = abox.operator(\"deepseek.submit_selection\",",
         "why": "同上：abox 就是 layout，独立导出改绑 layout"},
        {"to": "text=\"按推荐参数开始建模\",",
         "from": "text=\"按推荐参数开始建模\",",
         "why": "同一句，只是为了缩进对齐到 rec_btn.operator 的续行而重折"},
    ]
    blocks.append({
        "key": "chat_questions",
        "label": "规格选项组",
        "tab": "chat",
        "what": "AI 反问规格时给你的一组选择：一项一个盒，底下每个选项一个按钮，一个选项占满一整行。",
        "variants": [V("only", "反问一组", "细节 N + N 个选择按钮 + 一个全按推荐",
                       q_lines,
                       {"kind": "col", "items": ["细节 1：杯型风格", "细节 2：容量", "细节 3：材质"]},
                       rewrites=q_rewrites)],
        "default_variant": "only",
        "editable": ["选项按钮文字", "推荐按钮文字"],
        "slots": q_slots,
        "element_id": "chat.options",
        "demo": {"kind": "col", "items": ["细节 1：杯型风格", "细节 2：容量", "细节 3：材质"]},
    })

    p_lines = ["pills = list(quick_pills(state))",
               "if pills:",
               "    pbox = layout.box()",
               "    p_row1 = pbox.row(align=True)",
               "    p_row2 = pbox.row(align=True)",
               "    mid = (len(pills) + 1) // 2",
               "    for i, pill in enumerate(pills):",
               "        target_row = p_row1 if i < mid else p_row2",
               '        target_row.operator("deepseek.quick_pill", text=pill).action = pill']
    blocks.append({
        "key": "chat_pills",
        "label": "快捷指令网格",
        "tab": "chat",
        "what": "输入框上面那两行快捷按钮，点一下等于替你把这句话打进去。",
        "variants": [V("only", "两行按钮", "两行并排的快捷指令", p_lines,
                       {"kind": "grid", "cols": 2,
                        "items": ["修改尺寸", "更换材质", "增加倒角", "平滑着色"]})],
        "default_variant": "only",
        "editable": [],
        "slots": [],
        "element_id": "",
        "demo": {"kind": "grid", "cols": 2,
                 "items": ["修改尺寸", "更换材质", "增加倒角", "平滑着色"]},
    })

    c_lines = ["cbox = layout.box()",
               "crow = cbox.row(align=True)",
               'crow.label(text=%s, icon=\'TEXT\')' % pyq("输入建模指令:"),
               "crow.prop(state, \"prompt_lines\", text=\"\", slider=True)",
               'cbox.textbox(state, "prompt", initial_visible_lines=state.prompt_lines,',
               "             placeholder=%s)" % pyq("用自然语言描述要建模什么，可多行"),
               "",
               "brow = cbox.row(align=True)",
               "brow.scale_y = 1.3",
               "if not busy:",
               '    brow.operator("deepseek.run_prompt", text=%s, icon=\'PLAY\')' % pyq("发送指令"),
               "else:",
               '    brow.operator("deepseek.stop", text=%s, icon=\'CANCEL\')' % pyq("终止任务")]
    c_slots = [{"name": "label", "label": "标签文字", "text": "输入建模指令:",
                "literal": pyq("输入建模指令:")},
               {"name": "ph", "label": "占位提示", "text": "用自然语言描述要建模什么，可多行",
                "literal": pyq("用自然语言描述要建模什么，可多行")},
               {"name": "send", "label": "按钮文字", "text": "发送指令",
                "literal": pyq("发送指令")}]
    blocks.append({
        "key": "chat_composer",
        "label": "对话输入区",
        "tab": "chat",
        "what": "面板最下面那块：一句提示 + 可拖高度的输入框 + 发送/终止。",
        "variants": [V("only", "输入区", "多行输入框 + 发送或终止", c_lines,
                       {"kind": "prop", "items": ["输入建模指令:", "高度 3",
                                                 "用自然语言描述要建模什么，可多行"]})],
        "default_variant": "only",
        "editable": ["标签文字", "占位提示", "按钮文字"],
        "slots": c_slots,
        "element_id": "chat.composer",
        "demo": {"kind": "prop",
                 "items": ["输入建模指令:", "高度 3", "用自然语言描述要建模什么，可多行"]},
    })

    a_lines = ["arow = layout.row(align=True)",
               "if can_undo(state):",
               '    arow.operator("deepseek.undo_task", text=%s, icon=\'LOOP_BACK\')' % pyq("回退操作"),
               'arow.operator("deepseek.new_task", text=%s, icon=\'ADD\')' % pyq("新建任务"),
               'arow.operator("deepseek.clear", text=%s, icon=\'TRASH\')' % pyq("清空记录")]
    a_rewrites = [{"to": "arow = layout.row(align=True)",
                   "from": "arow = cbox.row(align=True)",
                   "why": "ui.py 里这一行挂在输入区的 cbox 里；操作行单独成块，"
                          "上一块的盒子不该被拖进来"}]
    a_slots = [{"name": "new", "label": "按钮文字", "text": "新建任务",
                "literal": pyq("新建任务")},
               {"name": "clear", "label": "按钮文字", "text": "清空记录",
                "literal": pyq("清空记录")}]
    blocks.append({
        "key": "chat_actions",
        "label": "底部操作行",
        "tab": "chat",
        "what": "输入区下面那一行按钮：回退（能回退时才出现）/ 新建任务 / 清空记录。",
        "variants": [V("only", "操作行", "三个并排的按钮", a_lines,
                       {"kind": "row", "items": ["新建任务", "清空记录"]},
                       rewrites=a_rewrites)],
        "default_variant": "only",
        "editable": ["按钮文字"],
        "slots": a_slots,
        "element_id": "chat.action_row",
        "demo": {"kind": "row", "items": ["新建任务", "清空记录"]},
    })

    # ---- 详情 tab（4 块）------------------------------------------------
    d_calls = ["tbox = layout.box()",
               'tbox.label(text=f"工具调用（{len(run.calls)}）", icon=\'CONSOLE\')',
               "for i, call in enumerate(run.calls):",
               "    icon = {\"ok\": 'CHECKMARK', \"error\": 'ERROR', "
               "\"running\": 'TIME', \"awaiting\": 'ERROR'}.get(call.status, 'NONE')",
               "    srow = tbox.row(align=True)",
               '    srow.label(text=f"{i + 1}. {call.name}", icon=icon)',
               "    srow.label(text=call.summary()[:34])",
               '    op = srow.operator("deepseek.show_call", text="", icon=\'TEXT\')',
               "    op.index = i"]
    d_trans = ["box = layout.box()",
               'box.label(text=%s, icon=\'CONSOLE\')' % pyq("详情 / 转录内容"),
               'box.prop(state, "transcript", text="")']
    d_usage = ["ubox = layout.box()",
               'ubox.label(text=%s, icon=\'INFO\')' % pyq("本次用量（实测）"),
               "u = run.usage",
               "ubox.label(text=f\"输入 {u.get('prompt_tokens', '—')} · "
               "缓存命中 {u.get('prompt_cache_hit_tokens', '—')}\")",
               "ubox.label(text=f\"输出 {u.get('completion_tokens', '—')}\")",
               "est = int((u.get(\"prompt_tokens\") or 0) * 1.0)",
               "ubox.label(text=f\"上下文占用估算 约 {est / 1000:.1f}k / 8k（估算，非服务端返回）\")",
               "ubox.label(text=f\"轮次：{run.rounds}/{run.limit} · 耗时：{run.elapsed:.1f}s\", icon='TIME')"]
    d_export = ['if state.history or (run and run.calls):',
                '    layout.operator("deepseek.export", text=%s, icon=\'EXPORT\')' % pyq("导出完整转录")]
    blocks.append({
        "key": "detail_calls", "label": "工具调用记录", "tab": "detail",
        "what": "这一趟任务调了哪些工具，一次一行，点一行看那次调用的详情。",
        "variants": [V("only", "调用列表", "标题 + 每次调用一行",
                       d_calls,
                       {"kind": "box", "items": ["工具调用（4）", "1. list_scene_objects", "2. create_lathe_profile"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "box", "items": ["工具调用（4）", "1. list_scene_objects",
                                          "2. create_lathe_profile"]},
    })
    blocks.append({
        "key": "detail_transcript", "label": "完整转录", "tab": "detail",
        "what": "整段对话原文，一个可滚动的多行框。",
        "variants": [V("only", "转录正文", "标题 + 多行正文", d_trans,
                       {"kind": "prop", "items": ["详情 / 转录内容", "（整段原文）"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "prop", "items": ["详情 / 转录内容", "（整段原文）"]},
    })
    blocks.append({
        "key": "detail_usage", "label": "用量统计", "tab": "detail",
        "what": "这一趟花了多少 token、几轮、多久。上下文占用是本地估算，不是服务端返回的。",
        "variants": [V("only", "用量统计", "输入 / 缓存 / 输出 / 轮次耗时", d_usage,
                       {"kind": "col", "items": ["本次用量（实测）", "输入 4820 · 缓存命中 3960",
                                                 "输出 612", "轮次：3/12 · 耗时：41.2s"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "col", "items": ["本次用量（实测）", "输入 4820 · 缓存命中 3960",
                                          "输出 612", "轮次：3/12 · 耗时：41.2s"]},
    })
    blocks.append({
        "key": "detail_export", "label": "导出转录", "tab": "detail",
        "what": "把整段转录存成一个文件的那个按钮。有记录时才出现。",
        "variants": [V("only", "导出按钮", "导出完整转录", d_export,
                       {"kind": "btn", "items": ["导出完整转录"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "btn", "items": ["导出完整转录"]},
    })

    # ---- 设置 tab（5 块）------------------------------------------------
    s_prov = ["sbox = layout.box()",
              "sbox.label(text=%s, icon='PREFERENCES')" % pyq("服务商配置"),
              "if p:",
              '    sbox.prop(p, "provider", text="服务商")',
              "else:",
              "    sbox.label(text=f\"当前服务商：{prov_info['name']}\")",
              "",
              "doc_row = sbox.row(align=True)",
              "doc_op = doc_row.operator(\"wm.url_open\", "
              'text=f"打开 {prov_info[\'name\']} 官方文档", icon=\'URL\')',
              'doc_op.url = prov_info["doc_url"]']
    s_key = ["kbox = layout.box()",
             "kbox.label(text=%s, icon='KEYINGSET')" % pyq("API Key 配置"),
             "if p:",
             "    row = kbox.row(align=True)",
             "    row.alert = not p.api_key.strip()",
             '    row.prop(p, "api_key", text="API Key")',
             "if cfg[\"api_key\"]:",
             "    kbox.label(text=f\"已生效（来源：{'偏好设置' if cfg['key_source'] == 'prefs' else '环境变量'}）\", icon='CHECKMARK')",
             "else:",
             "    erow = kbox.row(align=True)",
             "    erow.alert = True",
             '    erow.label(text=f"未配置 API Key（也可配置环境变量 {prov_info[\'key_env\']}）", icon=\'ERROR\')']
    s_model = ["mbox = layout.box()",
               "mbox.label(text=%s, icon='PLUGIN')" % pyq("模型配置"),
               "if p:",
               '    mbox.prop(p, "model", text="当前模型")',
               "else:",
               '    mbox.label(text=f"当前模型：{cfg[\'model\']}")',
               "",
               "fetch_row = mbox.row(align=True)",
               'fetch_row.operator("deepseek.fetch_models", text=%s, icon=\'FILE_REFRESH\')' % pyq("获取最新模型列表")]
    s_list = ["if available_models:",
              "    lbox = mbox.box()",
              '    lbox.label(text=%s, icon=\'INFO\')' % pyq("点击快速切换模型："),
              '    cur_model = (p.model if p else cfg["model"]).strip()',
              '    flow = lbox.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False, align=True) '
              'if hasattr(lbox, "grid_flow") else lbox.column(align=True)',
              "    for m in available_models[:12]:",
              "        is_cur = (m == cur_model)",
              "        btn = flow.operator(\"deepseek.set_model\", text=m, "
              "icon='CHECKMARK' if is_cur else 'NONE', depress=is_cur)",
              "        btn.model_name = m"]
    s_adv = ["abox = layout.box()",
             "abox.label(text=%s, icon='PREFERENCES')" % pyq("高级运行参数"),
             'abox.prop(p, "base_url", text="Base URL")',
             "row = abox.row(align=True)",
             'row.prop(p, "timeout", text="超时(秒)")',
             'row.prop(p, "max_turns", text="最大轮次")',
             "row = abox.row(align=True)",
             'row.prop(p, "wall_budget", text="时间预算(秒)")',
             'row.prop(p, "history_page", text="面板历史条数")',
             'abox.prop(p, "allow_arbitrary_code")']
    blocks.append({
        "key": "settings_provider", "label": "服务商配置", "tab": "settings",
        "what": "用哪家（DeepSeek / MiniMax），外加一个跳官方文档的按钮。",
        "variants": [V("only", "服务商", "服务商下拉 + 官方文档按钮", s_prov,
                       {"kind": "prop", "items": ["服务商", "DeepSeek", "打开 DeepSeek 官方文档"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "prop", "items": ["服务商", "DeepSeek", "打开 DeepSeek 官方文档"]},
    })
    blocks.append({
        "key": "settings_key", "label": "API Key 配置", "tab": "settings",
        "what": "填 Key 的那一行，外加一行告诉你现在有没有生效、是从哪来的。",
        "variants": [V("only", "Key", "Key 输入框 + 生效状态", s_key,
                       {"kind": "prop", "items": ["API Key", "（未填）", "未配置 API Key"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "prop", "items": ["API Key", "（未填）", "未配置 API Key"]},
    })
    blocks.append({
        "key": "settings_model", "label": "模型配置", "tab": "settings",
        "what": "当前用哪个模型，外加一个「去官网把最新列表拉回来」的按钮。",
        "variants": [V("only", "模型", "模型下拉 + 拉取按钮", s_model,
                       {"kind": "prop", "items": ["当前模型", "deepseek-chat", "获取最新模型列表"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "prop", "items": ["当前模型", "deepseek-chat", "获取最新模型列表"]},
    })
    blocks.append({
        "key": "settings_model_list", "label": "模型快捷网格", "tab": "settings",
        "what": "两列的模型按钮，点一下直接切过去，当前模型那颗按钮是压下的。",
        "variants": [V("only", "模型网格", "两列并排的模型按钮", s_list,
                       {"kind": "grid", "cols": 2, "items": ["deepseek-chat", "deepseek-reasoner"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "grid", "cols": 2, "items": ["deepseek-chat", "deepseek-reasoner"]},
    })
    blocks.append({
        "key": "settings_advanced", "label": "高级运行参数", "tab": "settings",
        "what": "平时不用动的几个：Base URL、超时、最大轮次、时间预算、历史条数、要不要放行任意代码。",
        "variants": [V("only", "高级参数", "五个属性 + 一个开关", s_adv,
                       {"kind": "prop", "items": ["Base URL", "超时(秒) 120", "最大轮次 12",
                                                 "时间预算(秒) 300", "面板历史条数 8"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": {"kind": "prop", "items": ["Base URL", "超时(秒) 120", "最大轮次 12",
                                           "时间预算(秒) 300", "面板历史条数 8"]},
    })

    doc = {
        "generated_for": "blender_deepseek_agent/ui.py",
        "what": ("业务块 = 插件界面里真实存在的一整块东西（状态提示条、消息气泡、"
                 "输入区…）。每一块的 ui_py 都是 ui.py 里那段代码原样抄来的，"
                 "导出时直接用它，不做翻译。"),
        "tab_labels": TAB_LABELS,
        "demo_kinds": ["row", "col", "box", "split", "grid", "panel", "label",
                       "btn", "prop", "rule", "gap"],
        "blocks": blocks,
    }
    return finalize(doc)


def _selfcheck(doc, ui_lines=None):
    """落盘前自检：字段集、ui_py 可解析、槽位真的落在代码里、以及**出处核对**。

    这些是生成期的硬门：数据坏了就别落盘，让 build() 直接抛出去。
    """
    if ui_lines is None:
        with open(UI_PY, encoding="utf-8") as fh:
            ui_lines = fh.read().split("\n")
    ui_stripped = set(ln.strip() for ln in ui_lines)
    want_block = {"key", "label", "tab", "what", "variants", "default_variant",
                  "editable", "slots", "element_id", "demo", "ui_py"}
    want_var = {"key", "label", "what", "ui_py", "demo", "rewrites"}
    want_slot = {"name", "label", "text", "literal"}
    keys = []
    for b in doc["blocks"]:
        if set(b) != want_block:
            raise BlockError("%s 字段集不对：%s" % (b.get("key"), sorted(b)))
        keys.append(b["key"])
        if b["tab"] not in TAB_LABELS:
            raise BlockError("%s 的 tab 不认识：%r" % (b["key"], b["tab"]))
        vk = [v["key"] for v in b["variants"]]
        if b["default_variant"] not in vk:
            raise BlockError("%s 的 default_variant 不在 variants 里：%r"
                             % (b["key"], b["default_variant"]))
        seen_lab = []
        for s in b["slots"]:
            if s["label"] not in seen_lab:
                seen_lab.append(s["label"])
        if seen_lab != list(b["editable"]):
            raise BlockError("%s 的 editable 应是 slots 里按次序去重后的文案名：%s，实际 %s"
                             % (b["key"], seen_lab, b["editable"]))
        if len(set(s["name"] for s in b["slots"])) != len(b["slots"]):
            raise BlockError("%s 的槽 name 重复（值按 name 存，重名会互相覆盖）" % b["key"])
        for s in b["slots"]:
            if set(s) != want_slot:
                raise BlockError("%s 的槽字段集不对：%s" % (b["key"], sorted(s)))
        for v in b["variants"]:
            if set(v) != want_var:
                raise BlockError("%s/%s 变体字段集不对：%s"
                                 % (b["key"], v["key"], sorted(v)))
            # 按导出成型的样子解析：包在一层 def 里、每行缩进 4 列。
            # 单独 parse 一段带缩进的字符串必然 IndentationError，而导出产物
            # 恰恰是「def + 缩进 4 列」，所以这里必须照那个形状核才对得准。
            src = "def _draft():\n" + "\n".join(
                ("    " + ln) if ln.strip() else "" for ln in v["ui_py"].split("\n"))
            try:
                ast.parse(src)
            except SyntaxError as exc:
                raise BlockError("%s/%s 的 ui_py 解析不过：%s\n%s"
                                 % (b["key"], v["key"], exc, v["ui_py"]))
            if b["slots"]:
                joined = "\n".join(v["ui_py"].split("\n"))
                present = [s["label"] for s in b["slots"]
                           if s["literal"] in joined]
                if present:
                    # 这个变体带可改文案，就必须每个槽都真的落在代码里一次
                    for s in b["slots"]:
                        if joined.count(s["literal"]) > 1:
                            raise BlockError(
                                "%s/%s 里槽「%s」的字面量出现 %d 次"
                                % (b["key"], v["key"], s["label"],
                                   joined.count(s["literal"])))
            if not (v["demo"] or {}).get("kind"):
                raise BlockError("%s/%s 的变体没有图示" % (b["key"], v["key"]))
            # --- 出处核对：这一段的每一行都必须来自 ui.py ---
            # 没在 ui.py 里逐字找到的行，只许是 rewrites 里登记过的那几行；
            # 登记项还必须给出它在 ui.py 里的原句（否则等于凭空写了一句再
            # 自己签字说「这是改的」）。
            for rw in v["rewrites"]:
                if set(rw) != {"to", "from", "why"}:
                    raise BlockError("%s/%s 的 rewrite 字段集不对：%s"
                                     % (b["key"], v["key"], sorted(rw)))
                if rw["from"].strip() not in ui_stripped:
                    raise BlockError("%s/%s 声明的改写原句「%s」在 ui.py 里不存在"
                                     % (b["key"], v["key"], rw["from"]))
                if not rw["why"].strip():
                    raise BlockError("%s/%s 的改写没写为什么" % (b["key"], v["key"]))
            declared = set(rw["to"].strip() for rw in v["rewrites"])
            for ln in v["ui_py"].split("\n"):
                if not ln.strip() or ln.strip() in ui_stripped:
                    continue
                if ln.strip() not in declared:
                    raise BlockError(
                        "%s/%s 有一行既不在 ui.py 里、也没登记为改写：%r"
                        % (b["key"], v["key"], ln))
        # 块级：至少有一段代码真的带着可改文案，否则 editable 是挂着好看的。
        joined_all = "\n".join(v["ui_py"] for v in b["variants"])
        if b["slots"] and not any(s["literal"] in joined_all for s in b["slots"]):
            raise BlockError("%s 声明了可改文案，但没有一个槽的原文出现在代码里" % b["key"])
        # 默认变体必须在 variants 里，且块级 ui_py 与它逐字一致（导出直接用它）。
        dv = [v for v in b["variants"] if v["key"] == b["default_variant"]][0]
        if b.get("ui_py") != dv["ui_py"]:
            raise BlockError("%s 的块级 ui_py 与默认变体不一致" % b["key"])
        if not (b["demo"] or {}).get("kind"):
            raise BlockError("%s 没有图示" % b["key"])
    if len(set(keys)) != len(keys):
        raise BlockError("block key 重复：%s" % keys)
    return len(keys)


def main():
    doc = build()
    n = _selfcheck(doc)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    # 落盘自检：中文文件不许带 NUL / U+FFFD
    with open(OUT, "rb") as fh:
        raw = fh.read()
    if b"\x00" in raw:
        print("BLOCKS_NUL")
        return 1
    txt = raw.decode("utf-8")
    if "\ufffd" in txt:
        print("BLOCKS_REPLACEMENT_CHAR")
        return 1
    back = json.loads(txt)
    if back != doc:
        print("BLOCKS_ROUNDTRIP_MISMATCH")
        return 1
    by_tab = {}
    for b in back["blocks"]:
        by_tab[b["tab"]] = by_tab.get(b["tab"], 0) + 1
    print("BLOCKS_OK blocks=%d variants=%d tabs=%s"
          % (n, sum(len(b["variants"]) for b in back["blocks"]),
             " ".join("%s=%d" % (k, by_tab.get(k, 0))
                      for k in ("chat", "detail", "settings"))))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BlockError as exc:
        sys.stderr.write("BLOCKS_ERROR %s\n" % exc)
        sys.exit(1)
