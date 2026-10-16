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
# 长消息折叠的分界：折叠态只显示前 20 字 + 省略号。
# 这一条只有一个出处：渲染侧（app.js 的 FOLD_CHARS）与导出侧（py_helper 里的
# text[:20]）必须说的是同一件事，否则预览折了、Blender 里没折。
FOLD_CHARS = 20


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


def D(kind, items, icons=None, **kw):
    """一个图示（demo）。kind + items 之外多两样，都是这一轮加的：

    icons  —— 与 items 平行的图标名。逐个对着 ui.py 里真写的 icon='XXX' 取，
              取不到的那一格就不给（列表可以比 items 短）。
              为什么要它：Blender 的按钮是「图标 + 文字」并排的，预览里只印
              文字会让用户以为界面上就该没图标。
    groups —— 内层分组，一组一个盒子（title + items）。这是「双层盒」的数据
              形态：外层是 kind 画出来的那个盒，每组细节自己再一个盒。
    """
    d = {"kind": kind, "items": list(items)}
    if icons:
        d["icons"] = list(icons)
    d.update(kw)
    return d


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

    # 面板最顶上第一块是**页签条**，状态提示条排在它下面——页签是入口，
    # 状态条是这一页当前的情况。两者的先后 append 顺序就是控件架上、
    # 预览里、以及导出的 draw_chat_content 里的先后顺序，所以这里必须
    # 页签在前。上一版反了，用户点名过。
    blocks.append({
        "key": "chat_tabbar",
        "label": "页签条",
        "tab": "chat",
        # 页签上不写「AI」两个字：面板所在的分类已经叫「AI 对话」，页签再写一遍
        # 是废话，而且用户明确要求去掉。这里写清一句实话：插件那边真正的页签
        # 文字来自 ui.py 里 active_tab 枚举的第一项（现在还是 "AI 对话"），
        # 改成「对话」是改那个字符串，本轮不许动 ui.py，所以这一处仍是原样。
        "what": "面板最顶上那三个页签（对话 / 详情 / 设置），排在状态提示条"
                "**上面**——页签是入口，状态条才是这一页现在的情况。"
                "页签上不写「AI」两个字：面板所在分类已经叫「AI 对话」，"
                "页签再写一遍是废话。插件那边同样只写「对话」"
                "（ui.py 的 active_tab 枚举第一项就是「对话」），两边一致。",
        "variants": [V("only", "三个页签", "对话 / 详情 / 设置，点哪个画哪个",
                       ["trow = layout.row(align=True)",
                        'trow.prop(state, "active_tab", expand=True)'],
                       D("row", ["对话", "详情", "设置"],
                         icons=["COMMUNITY", "CONSOLE", "PREFERENCES"]))],
        "default_variant": "only",
        "editable": [],
        "slots": [],
        "element_id": "chat.tabbar",
        "demo": D("row", ["对话", "详情", "设置"],
                  icons=["COMMUNITY", "CONSOLE", "PREFERENCES"]),
    })

    # 状态提示条：一个盒，内容直接装在里面。「正在做什么」那一格**不再**
    # 套一层小方块——上一版把它画成一个带边框的 .d-it，看着像盒里又有个盒。
    # bare=[0] 就是告诉渲染器「第 0 格是盒里的正文，不是又一个控件」。
    busy_demo = D("box", ["正在改你的场景 · 第 2 步", "终止任务"],
                  icons=["TIME", "CANCEL"], bare=[0])
    blocks.append({
        "key": "chat_status",
        "label": "状态提示条",
        "tab": "chat",
        "what": "任务在跑的时候，面板顶部那一整条，排在页签条**下面**。"
                "四种样子：正在跑、等你批准、做到一半、失败。"
                "忙碌中那一格里，「正在做什么」是盒里的正文（不再套内层小盒），"
                "右边那个才是按钮。",
        "variants": [
            V("busy", "忙碌中", "正在跑，显示当前动作 + 终止按钮", b_busy,
              busy_demo),
            V("approve", "待批准", "它想执行代码，等你点头", b_appr,
              D("box", ["它想运行一段脚本，请确认：", "批准执行", "拒绝取消"],
                icons=["QUESTION", "CHECKMARK", "CANCEL"])),
            V("partial", "做到一半", "分已做 / 未做两栏", b_part,
              D("box", ["任务做到一半：", "已经做了：", "还没做："],
                icons=["INFO", "CHECKMARK", "ERROR"])),
            V("failed", "失败", "整个界面唯一的报错块", b_fail,
              D("box", ["任务执行中断：…", "重新尝试"],
                icons=["ERROR", "FILE_REFRESH"])),
        ],
        "default_variant": "busy",
        "editable": ["终止按钮文字", "标题文字", "副标题", "按钮文字"],
        "slots": status_slots,
        "element_id": "chat.statusbar",
        "demo": busy_demo,
    })

    # 用户自己发的那条消息：ui.py:868-872 就是一个盒（ubox）+ 右对齐的文字。
    # Task 21 起这盒改成可收起的可折叠子面板——长提示词会把侧栏撑爆，而
    # Blender 侧栏不能滚动。写法是 py_helper 里那个 _uw_msg_panel，它内部
    # 用 layout.panel(idname, default_closed)，那是真能收起、带原生箭头的控件。
    user_box = ['ubox = _uw_msg_panel(layout, "chat.user_msg", item.text,'
                " open_default=True)"]
    # AI 的话：整段**一个盒**，右边留一栏空白。ui.py:1026-1029 是
    # layout.split(factor=AI_MARGIN_SPLIT) 取左边那列（实测 split 返回左边列、
    # 宽 = factor × 内容宽，右边留白；align 在 5.2 是 bool 且不影响位置），
    # 盒画在那列里 —— 规格区不再是另一个盒，盒里也不再套盒。
    ai_box = ["acol = layout.split(factor=AI_MARGIN_SPLIT)",
              "if isinstance(acol, tuple):",
              "    acol = acol[0]",
              "abox = acol.box()",
              "if item.duration_str:",
              "    arow = abox.row(align=True)",
              "    arow.alignment = 'LEFT'",
              '    arow.label(text=f"耗时 {item.duration_str}", icon=\'COMMUNITY\')',
              "if item.steps_json:",
              "    abox.label(text=%s, icon='FILE_SCRIPT')" % pyq("执行的操作："),
              "    for st in steps:",
              '        abox.label(text=f"✓ {st}")',
              "if item.added_objects_str:",
              '    abox.label(text=f"新增对象：{item.added_objects_str}", icon=\'MESH_DATA\')']
    bubble_slots = [{"name": "steps", "label": "小标题文字",
                     "text": "执行的操作：", "literal": pyq("执行的操作：")}]
    # 故意给一条**长**的：折叠这件事只有长消息才谈得上，短消息折了也没意义。
    # 20 个字是折与不折的分界（渲染侧按这条切，导出侧也按这条切）。
    # 写成带句号的两句：收起时留的是**首句摘要 + 总字数**，
    # 没有句号就切不出「首句」来，摘要那一格会退化成截前 20 个字。
    USER_MSG_LONG = ("帮我做一个马克杯。杯口直径 8 厘米、杯身高 9 厘米、"
                     "杯壁厚 3 毫米；再加一个半径 4 厘米的把手，"
                     "把手和杯身要连成一体；表面做成磨砂的。")
    bubble_demo = D("msgtxt", [USER_MSG_LONG])
    blocks.append({
        "key": "chat_bubble",
        "label": "消息气泡",
        "tab": "chat",
        "what": "对话流里的一条消息。你说的话装在盒子里——**一个盒，"
                "盒里不再套盒**，文字按盒子的宽度折行（把面板拉宽，每行的字"
                "就变多，不给气泡做窄栏也不写死宽度）。"
                "**默认展开**：折叠是给长提示词用的，不是默认藏起来——收起时"
                "只留一行标题（首句摘要 + 总字数），展开/收起按钮在右下角。"
                "Blender 侧就是 layout.panel(idname, default_closed)，"
                "idname 对同一条气泡稳定，展开/收起状态跟着积木走。"
                "AI 的话不装框，直接排在流里。",
        "variants": [
            V("user", "你说的话",
              "一个盒；默认展开，右下角一个按钮收起成一行标题",
              user_box, bubble_demo,
              rewrites=[{"from": "ubox = layout.box()",
                         "to": user_box[0],
                         "why": "ui.py:868 那个 ubox 是个铺满整幅的盒子，几百字的"
                                "提示词会把侧栏撑爆（Blender 侧栏不能滚动）。"
                                "改成 _uw_msg_panel（见 py_helper），它内部用"
                                " layout.panel(idname, default_closed)——那是真能收起、"
                                "自带原生箭头的控件。展开/收起的状态跟着积木走，"
                                "导出时把 open_default 一起带出去。"}]),
            V("ai", "AI 回答",
              "整段一个盒（耗时 / 执行步骤 / 新增对象），右边留一栏空白", ai_box,
              # 盒里那几格是**盒里的正文**（bare）：不画各自的框，
              # 整段读起来就是一个盒。inset 是右边那一栏空白。
              D("box", ["耗时 12.4s", "执行的操作：", "新增对象：马克杯"],
                icons=["COMMUNITY", "FILE_SCRIPT", "MESH_DATA"],
                bare=[0, 1, 2], inset=0.22),
              rewrites=[
                  # ui.py 里「新增对象」那一格是 abox 底下另起的一个内盒
                  # （res_box = abox.box()）。用户改成整段只有一层盒，所以并回
                  # abox 直画，去掉那个内盒。
                  {"to": 'abox.label(text=f"新增对象：{item.added_objects_str}",'
                         " icon='MESH_DATA')",
                   "from": 'res_box.label(text=f"新增对象：{item.added_objects_str}",'
                           " icon='MESH_DATA')",
                   "why": "ui.py 里 res_box = abox.box() 又开了一个内盒，"
                          "整段就成了两层框；用户要求 AI 回复只有一层盒，"
                          "所以并回 abox 直画"},
              ]),
        ],
        "default_variant": "user",
        "editable": ["小标题文字"],
        "slots": bubble_slots,
        "element_id": "chat.stream",
        "demo": bubble_demo,
    })

    # 「字少就横排」在插件那边是这么实现的：Blender 量不了文字宽度，于是按
    # 「选项个数 + 标签总字数」估算，太多太长就退回竖排（ui.py 的 too_wide）。
    # 预览这边量得到真实像素，所以判据是「一行排不排得下」——两条路同一个意图，
    # 阈值略有差别（插件 >3 个或总字数 >22，预览 >OPT_WRAP_MAX 个），
    # 差别记在这里：真要统一，改 ui.py 的 3 或改 app.js 的 OPT_WRAP_MAX 都行。
    q_lines = ["sbody = layout.box()",
               "for q_idx, q in enumerate(questions):",
               "    q_title = re.sub(r\"^\\s*\\d+\\s*[.、．)）]\\s*\",",
               "                     \"\", str(q.get('title', '')))",
               "    sbody.label(text=f\"细节 {q_idx + 1}：{q_title}\",",
               "                icon='MENU_PANEL')",
               '    opts = q.get("options", [])',
               "    orow_holder = sbody.row(align=True)",
               "    for opt in opts:",
               '        val = opt.get("value") or opt.get("label", "")',
               '        lbl = opt.get("label", val)',
               "        orow = orow_holder",
               '        btn = orow.operator("deepseek.submit_selection",',
               "                    text=%s," % pyq("选择: {lbl}", fstring=True),
               "                    icon='CHECKBOX_DEHLT')",
               '        btn.custom_prompt = f"针对「{q_title}」，我选择：{val}"',
               "",
               'rec_btn = sbody.operator("deepseek.submit_selection",',
               "                text=%s," % pyq("按推荐参数开始建模"),
               "                icon='PLAY')",
               'rec_btn.custom_prompt = info.get("all_recommended", "全部按推荐参数开始建模！")']
    q_slots = [{"name": "opt", "label": "选项按钮文字", "text": "选择: {lbl}",
                "literal": pyq("选择: {lbl}", fstring=True)},
               {"name": "rec", "label": "推荐按钮文字", "text": "按推荐参数开始建模",
                "literal": pyq("按推荐参数开始建模")}]
    q_rewrites = [
        {"to": "sbody = layout.box()",
         "from": "sbody = abox",
         "why": "ui.py 里规格段直接画在 AI 那个整段盒 abox 上（用户要求整段只"
                "一层盒，规格区是它的一部分而不是另一个盒）；独立导出这一块时"
                "abox 不在作用域，于是自己新建一个盒把整段规格装起来"},
    ]
    # 单盒：引子「需要你定一下」+ 三个细节的标题 + 每一串选择按钮 + 结语，
    # 全部装在**同一个**盒里。此前是「外盒 + 每个细节各自再一个内盒」，
    # 用户看到的是被切碎的几块，内层盒已去掉（预览侧靠 style.css 把
    # .d-group 的边框与底色撤掉，数据形状不动）。
    # 细节里的选项：**永远横排并排**。Blender 量不到文字宽度，但用户说了
    # 截断没关系、面板可以拉宽，纵向空间才是真约束——所以不再按字数退回竖排。
    q_demo = D("box", ["需要你定一下"], bare=[0], groups=[
        {"title": "细节 1：杯型风格", "icon": "MENU_PANEL",
         "items": ["直筒微收口", "鼓腹圆润", "厚壁窑变"],
         "item_icons": ["CHECKBOX_DEHLT"] * 3},
        {"title": "细节 2：容量", "icon": "MENU_PANEL",
         "items": ["350ml", "500ml", "750ml"],
         "item_icons": ["CHECKBOX_DEHLT"] * 3},
        {"title": "细节 3：材质", "icon": "MENU_PANEL",
         "items": ["陶瓷", "玻璃", "不锈钢"],
         "item_icons": ["CHECKBOX_DEHLT"] * 3},
    ])
    blocks.append({
        "key": "chat_questions",
        "label": "规格选项组",
        "tab": "chat",
        "what": "AI 反问规格时给你的一组选择。**整段装在同一个盒里**："
                "引子、每个细节的标题、那一串选择按钮、结语，全在一个盒内，"
                "不再「外盒 + 每个细节各自一个内盒」把内容切碎。"
                "标题是「细节 N：标题」——AI 给的标题常自带「1. 」这种 markdown "
                "序号，拼接前先剥掉，免得出现「细节 1：1.杯型风格」两个 1；"
                "图标用 MENU_PANEL（这一组是等你从菜单里选，分组标题），"
                "不是语义对不上的问号。选项**永远横排并排**，文字截断不退回"
                "竖排——面板可以拉宽，纵向空间才是真约束。",
        "variants": [V("only", "反问一组", "引子一句 + 三个细节（标题 + N 个横排选择按钮）",
                       q_lines, q_demo, rewrites=q_rewrites)],

        "default_variant": "only",
        "editable": ["选项按钮文字", "推荐按钮文字"],
        "slots": q_slots,
        "element_id": "chat.options",
        "demo": q_demo,
    })

    p_lines = ["pills = list(quick_pills(state))",
               "if pills:",
               "    pbox = layout.box()",
               "    if len(pills) <= 2:",
               "        pill_rows = [pbox.row(align=True)]",
               "    else:",
               "        pill_rows = [pbox.row(align=True), pbox.row(align=True)]",
               "    mid = (len(pills) + 1) // 2",
               "    for i, pill in enumerate(pills):",
               "        target_row = pill_rows[0] if (len(pills) <= 2 or i < mid) else pill_rows[1]",
               '        target_row.operator("deepseek.quick_pill", text=pill).action = pill']
    p_demo = D("grid", ["修改尺寸", "更换材质"],
               icons=["CON_SIZELIKE", "MATSHADERBALL"], cols=2)
    blocks.append({
        "key": "chat_pills",
        "label": "快捷指令网格",
        "tab": "chat",
        "what": "输入框上面那排快捷按钮，点一下等于替你把这句话打进去。"
                "只留两条（修改尺寸 / 更换材质），**并排一行**——"
                "「增加倒角」「平滑着色」两条已按用户要求去掉。",
        "variants": [V("only", "并排两条", "并排一行的两个快捷指令", p_lines, p_demo)],

        "default_variant": "only",
        "editable": [],
        "slots": [],
        "element_id": "",
        "demo": p_demo,
    })

    c_lines = ["cbox = layout.box()",
               "cbox.textbox(state, \"prompt\", initial_visible_lines=state.prompt_lines,",
               "             placeholder=%s)" % pyq("用自然语言描述要建模什么，可多行"),
               "",
               "brow = cbox.row(align=True)",
               "brow.scale_y = 1.3",
               "if not busy:",
               '    brow.operator("deepseek.run_prompt", text=%s, icon=\'PLAY\')' % pyq("发送指令"),
               "else:",
               '    brow.operator("deepseek.stop", text=%s, icon=\'CANCEL\')' % pyq("终止任务")]
    c_slots = [{"name": "ph", "label": "占位提示", "text": "用自然语言描述要建模什么，可多行",
                "literal": pyq("用自然语言描述要建模什么，可多行")},
               {"name": "send", "label": "按钮文字", "text": "发送指令",
                "literal": pyq("发送指令")}]
    # 输入区：**只有输入框 + 发送/终止**。「输入建模指令:」那一栏已按用户要求
    # 删掉——省下来的纵向空间比一个标题值钱，textbox 的 placeholder 已经
    # 说明白这里能干什么。「高度 N」滑块上一轮就删了：textbox 自带右下角
    # 拖拽角，高度照样能拖（prompt_lines 只剩当初值用）。
    # 图示里 items 那一格画的是**发送按钮**，它确实在输入框下面，
    # 所以渲染时排到 textbox 之后（trailing）。
    c_demo = D("composer", ["发送指令"], icons=["PLAY"],
               bare=[0], textbox="用自然语言描述要建模什么，可多行",
               trailing=True)
    blocks.append({
        "key": "chat_composer",
        "label": "对话输入区",
        "tab": "chat",
        "what": "面板最下面那块：**一个多行输入框 + 下面的发送/终止**，"
                "盒宽摊满。「输入建模指令:」那一栏已经删掉（placeholder 说明"
                "这里能干什么），「高度 N」滑块也没有了——高度由输入框自己的"
                "多行与右下角拖拽角决定。",
        "variants": [V("only", "输入区", "多行输入框 + 发送或终止", c_lines, c_demo)],
        "default_variant": "only",
        "editable": ["占位提示", "按钮文字"],

        "slots": c_slots,
        "element_id": "chat.composer",
        "demo": c_demo,
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
        "demo": D("row", ["新建任务", "清空记录"], icons=["ADD", "TRASH"]),
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
                       D("box", ["工具调用（4）", "1. list_scene_objects",
                                 "2. create_lathe_profile"],
                         icons=["CONSOLE", "CHECKMARK", "CHECKMARK"]))],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("box", ["工具调用（4）", "1. list_scene_objects",
                          "2. create_lathe_profile"],
                  icons=["CONSOLE", "CHECKMARK", "CHECKMARK"]),
    })
    blocks.append({
        "key": "detail_transcript", "label": "完整转录", "tab": "detail",
        "what": "整段对话原文，一个可滚动的多行框。",
        "variants": [V("only", "转录正文", "标题 + 多行正文", d_trans,
                       {"kind": "prop", "items": ["详情 / 转录内容", "（整段原文）"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("prop", ["详情 / 转录内容", "（整段原文）"], icons=["CONSOLE"]),
    })
    blocks.append({
        "key": "detail_usage", "label": "用量统计", "tab": "detail",
        "what": "这一趟花了多少 token、几轮、多久。上下文占用是本地估算，不是服务端返回的。",
        "variants": [V("only", "用量统计", "输入 / 缓存 / 输出 / 轮次耗时", d_usage,
                       {"kind": "col", "items": ["本次用量（实测）", "输入 4820 · 缓存命中 3960",
                                                 "输出 612", "轮次：3/12 · 耗时：41.2s"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("col", ["本次用量（实测）", "输入 4820 · 缓存命中 3960",
                          "输出 612", "轮次：3/12 · 耗时：41.2s"],
                  icons=["INFO", "TIME"]),
    })
    blocks.append({
        "key": "detail_export", "label": "导出转录", "tab": "detail",
        "what": "把整段转录存成一个文件的那个按钮。有记录时才出现。",
        "variants": [V("only", "导出按钮", "导出完整转录", d_export,
                       {"kind": "btn", "items": ["导出完整转录"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("btn", ["导出完整转录"], icons=["EXPORT"]),
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
        "demo": D("prop", ["服务商", "DeepSeek", "打开 DeepSeek 官方文档"],
                  icons=["PREFERENCES", "URL"]),
    })
    blocks.append({
        "key": "settings_key", "label": "API Key 配置", "tab": "settings",
        "what": "填 Key 的那一行，外加一行告诉你现在有没有生效、是从哪来的。",
        "variants": [V("only", "Key", "Key 输入框 + 生效状态", s_key,
                       {"kind": "prop", "items": ["API Key", "（未填）", "未配置 API Key"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("prop", ["API Key", "（未填）", "未配置 API Key"],
                  icons=["KEYINGSET", "ERROR"]),
    })
    blocks.append({
        "key": "settings_model", "label": "模型配置", "tab": "settings",
        "what": "当前用哪个模型，外加一个「去官网把最新列表拉回来」的按钮。",
        "variants": [V("only", "模型", "模型下拉 + 拉取按钮", s_model,
                       {"kind": "prop", "items": ["当前模型", "deepseek-chat", "获取最新模型列表"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("prop", ["当前模型", "deepseek-chat", "获取最新模型列表"],
                  icons=["PLUGIN", "FILE_REFRESH"]),
    })
    blocks.append({
        "key": "settings_model_list", "label": "模型快捷网格", "tab": "settings",
        "what": "两列的模型按钮，点一下直接切过去，当前模型那颗按钮是压下的。",
        "variants": [V("only", "模型网格", "两列并排的模型按钮", s_list,
                       {"kind": "grid", "cols": 2, "items": ["deepseek-chat", "deepseek-reasoner"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("grid", ["deepseek-chat", "deepseek-reasoner"],
                  icons=["CHECKMARK"], cols=2),
    })
    blocks.append({
        "key": "settings_advanced", "label": "高级运行参数", "tab": "settings",
        "what": "平时不用动的几个：Base URL、超时、最大轮次、时间预算、历史条数、要不要放行任意代码。",
        "variants": [V("only", "高级参数", "五个属性 + 一个开关", s_adv,
                       {"kind": "prop", "items": ["Base URL", "超时(秒) 120", "最大轮次 12",
                                                 "时间预算(秒) 300", "面板历史条数 8"]})],
        "default_variant": "only", "editable": [], "slots": [], "element_id": "",
        "demo": D("prop", ["Base URL", "超时(秒) 120", "最大轮次 12",
                           "时间预算(秒) 300", "面板历史条数 8"],
                  icons=["PREFERENCES"]),
    })

    doc = {
        "generated_for": "blender_deepseek_agent/ui.py",
        "what": ("业务块 = 插件界面里真实存在的一整块东西（状态提示条、消息气泡、"
                 "输入区…）。每一块的 ui_py 都是 ui.py 里那段代码原样抄来的，"
                 "导出时直接用它，不做翻译。"),
        "tab_labels": TAB_LABELS,
        "demo_kinds": ["row", "col", "box", "split", "grid", "panel", "label",
                       "btn", "prop", "rule", "gap", "msgtxt", "composer"],
        # 响应式图标：面板**窄了就只留图标**。这一段**不在 ui.py 里**——它是
        # 这次明确要往导出里加的一段，所以单独立一张表登记，附上「为什么不逐字
        # 来自 ui.py」的理由，而不是混进 blocks_rewrites_declared 那套里
        # （那套的前提是「每一行都能在 ui.py 里找到原句」）。
        "py_preamble": {
            "key": "responsive_icons",
            "why": "这一段是 ui.py 里没有的新增代码：响应式图标在插件里还没有"
                   "现成写法可抄，所以它不进任何块的 ui_py（那边只许放 ui.py 里"
                   "逐字存在的代码），单独立这张表随导出一起带走。",
            "snippet": [
                "# ---- 响应式图标：面板窄了就只留图标 ----",
                "# Blender 没有媒体查询，draw() 里唯一能拿到的宽度就是区域宽度，",
                "# 所以「宽 / 窄」只能自己判断：宽的给「图标 + 文字」，",
                "# 窄的只给图标（text 置空就是只剩图标，不是把 icon 置成 'NONE'——",
                "# 那会把按钮上唯一认得出来的标志也一起抹掉）。",
                "# ★ 拖动面板边框的过程中 Blender 不会实时重绘 draw()，",
                "#   松手之后才重画一次——所以这个切换是「松手即生效」，",
                "#   不是「拖动过程中实时变」。别把它当成 CSS 那种媒体查询。",
                "_uw_panel_w = bpy.context.region.width",
                "_uw_wide = _uw_panel_w >= 360",
                'TXT_SEND = "发送指令" if _uw_wide else ""',
                'TXT_STOP = "终止任务" if _uw_wide else ""',
            ],
        },
        # 第二张新增代码表：长消息折叠。跟 py_preamble 同一个道理——ui.py 里
        # 没有这段（ui.py 的 ubox 是个铺满整幅的盒子，几百字的提示词会把
        # 侧栏撑爆），所以也不能塞进块的 ui_py。
        "py_helper": {
            "key": "msg_fold",
            "why": "这一段是 ui.py 里没有的新增代码：长消息折叠在插件里还没有"
                   "现成写法可抄，所以它不进任何块的 ui_py（那边只许放 ui.py 里"
                   "逐字存在的代码），单独立这张表随导出一起带走。",
            "snippet": [
                "# ---- 长消息折叠：一条几百字的提示词不该把侧栏撑爆 ----",
                "# Blender 侧栏不能滚动，所以长消息默认只露一行摘要。",
                "# 用 layout.panel(idname, default_closed)：它是真的能收起的，",
                "# 而且自带原生三角箭头——别自己造折叠控件，造出来的那个不是",
                "# Blender 的控件，导出后也对不上任何真实 API。",
                "# open_default 是积木上「展开 / 收起」那个状态带过来的，",
                "# 不是写死的：在工作台里点开过之后导出的那一份会写成 True。",
                "# 正文左对齐，从左边起空两个字符（每行都缩进，不只第一行）：",
                "# 提示词读起来是「自己的话」，右对齐会读成倒着写。",
                "def _uw_msg_panel(layout, idname, text, open_default=False):",
                '    p = layout.panel(idname, default_closed=not open_default)',
                '    head = text[:20] + ("…" if len(text) > 20 else "")',
                "    p.label(text=head)",
                "    for ln in wrap_text(text, max_chars=18):",
                "        r = p.row()",
                "        r.alignment = 'LEFT'",
                '        r.label(text="  " + ln)',
                "    return p",
            ],
        },
        "blocks": blocks,
    }
    return finalize(doc)


def real_icon_names(ui_lines):
    """实测存在的图标名全集：ui.py 里真写过的 + vocabulary.json 的 icons 名册。

    图示里那个图标名角标必须是真名——编一个看着像的名字，比不画图标更糟：
    用户会照着它去 Blender 里找，找不到就以为工作台在骗他。
    """
    names = set(re.findall(r"'([A-Z][A-Z0-9_]{2,})'", "\n".join(ui_lines)))
    vpath = os.path.join(HERE, "..", "ui_workbench", "vocabulary.json")
    if os.path.exists(vpath):
        with open(vpath, encoding="utf-8") as fh:
            names |= set((json.load(fh) or {}).get("icons") or [])
    return names


def check_demo(demo, where, icons):
    """图示的数据形状。kind/items 之外多几样，各自都要有硬约束。"""
    if not isinstance(demo, dict) or not demo.get("kind"):
        raise BlockError("%s 的图示没有 kind" % where)
    items = demo.get("items") or []
    ics = demo.get("icons") or []
    if len(ics) > len(items):
        raise BlockError("%s 的图标数 %d 多过条目数 %d（对不上就是画错位）"
                         % (where, len(ics), len(items)))
    for ic in ics:
        if ic not in icons:
            raise BlockError("%s 用了实测里没有的图标名 %r" % (where, ic))
    # composer：输入框独占一行，ui.py:953 的 cbox.textbox 就是这样。
    # 没有 textbox 字段的话渲染器画不出那一行，预览会退回「三样挤一行」。
    if demo.get("kind") == "composer":
        if not str(demo.get("textbox") or "").strip():
            raise BlockError("%s 是 composer 却没有 textbox 字段（输入框那一行）" % where)
    if demo.get("kind") == "msgtxt":
        # 折叠只对长消息有意义：短消息折了和没折一样，这条数据就没有可验的东西。
        if len(items) != 1 or len(items[0]) <= FOLD_CHARS:
            raise BlockError(
                "%s 是 msgtxt，就得正好一条、且长过 %d 字（不然折不断，"
                "折叠那条就没东西可验）：实际 %d 条、最长 %d 字"
                % (where, FOLD_CHARS, len(items),
                   max([len(x) for x in items] or [0])))
    for gi, g in enumerate(demo.get("groups") or []):
        gw = "%s 第 %d 组" % (where, gi + 1)
        if set(g) != {"title", "icon", "items", "item_icons"}:
            raise BlockError("%s 字段集不对：%s" % (gw, sorted(g)))
        if not str(g["title"]).strip() or not (g["items"] or []):
            raise BlockError("%s 缺标题或没有内容" % gw)
        if g["icon"] not in icons:
            raise BlockError("%s 的标题图标 %r 实测里没有" % (gw, g["icon"]))
        if len(g["item_icons"]) > len(g["items"]):
            raise BlockError("%s 的图标数多过条目数" % gw)
        for ic in g["item_icons"]:
            if ic not in icons:
                raise BlockError("%s 用了实测里没有的图标名 %r" % (gw, ic))


def _check_new_code_table(tbl, where, ui_stripped, icons, must_have):
    """「ui.py 之外的新增代码」表的生成期硬门。

    每张表有自己那几条必须写明的承诺（must_have）：字段集、why、承诺的词、
    每一行都不是从 ui.py 抄来的、图标名实测存在、整段能过 ast.parse。
    """
    if set(tbl) != {"key", "why", "snippet"}:
        raise BlockError("%s 字段集不对：%s" % (where, sorted(tbl)))
    if not str(tbl.get("why", "")).strip():
        raise BlockError("%s 没写为什么它是 ui.py 之外的新增代码" % where)
    body = list(tbl.get("snippet") or [])
    for must in must_have:
        if not any(must in ln for ln in body):
            raise BlockError("%s 里必须写明「%s」（这条是用户点名的注释）"
                             % (where, must))
    for ln in body:
        if ln.startswith("#"):
            continue
        if ln.strip() in ui_stripped:
            raise BlockError("%s 的代码行 %r 与 ui.py 逐字相同，"
                             "说明这段不该进这张表" % (where, ln))
    for ic in re.findall(r"'([A-Z][A-Z0-9_]{2,})'", "\n".join(body)):
        if ic not in icons:
            raise BlockError("%s 用了实测里没有的图标名 %r" % (where, ic))
    try:
        ast.parse("def _pre():\n" + "\n".join(("    " + ln) if ln.strip() else ""
                                              for ln in body))
    except SyntaxError as exc:
        raise BlockError("%s 解析不过：%s\n%s" % (where, exc, "\n".join(body)))


def _selfcheck(doc, ui_lines=None):
    """落盘前自检：字段集、ui_py 可解析、槽位真的落在代码里、以及**出处核对**。

    这些是生成期的硬门：数据坏了就别落盘，让 build() 直接抛出去。
    """
    if ui_lines is None:
        with open(UI_PY, encoding="utf-8") as fh:
            ui_lines = fh.read().split("\n")
    ui_stripped = set(ln.strip() for ln in ui_lines)
    icons = real_icon_names(ui_lines)
    # py_preamble / py_helper：新增代码，单独立表，所以要单独核对它们各自
    # 答应过的事。两张表的承诺不一样，所以分开查——共用一条清单的话，
    # 一张表写对了就能替另一张表顶缸。
    _check_new_code_table(doc.get("py_preamble") or {}, "py_preamble", ui_stripped,
                          icons, ("context.region.width", "媒体查询", "松手",
                                  "_uw_wide", 'else ""', "只给图标"))
    _check_new_code_table(doc.get("py_helper") or {}, "py_helper", ui_stripped,
                          icons, ("layout.panel", "default_closed",
                                  "侧栏", "滚动", "open_default",
                                  "text[:%d]" % FOLD_CHARS))
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
            check_demo(v["demo"], "%s/%s 的图示" % (b["key"], v["key"]), icons)
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
        check_demo(b["demo"], "%s 的图示" % b["key"], icons)
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
