"""一次性脚本：把 ui.py 的会话流段替换成 v2 实现，并把新渲染函数插到面板类之前。
只做文本级拼接，替换完即可删除本脚本。"""
import io
import os

SRC = r"E:\Three JS\Blender Agent\blender_deepseek_agent\ui.py"

NEW_FUNCS = '''
def _note_for(state, q_idx):
    """保证 notes[q_idx] 存在并返回它"""
    while len(state.notes) <= q_idx:
        state.notes.add()
    return state.notes[q_idx]


def _draw_questions(layout, state, questions, wrap_w):
    """细节询问：单选行 + 「其他」就地输入 + 确认选择 / 按推荐来"""
    try:
        sel = json.loads(state.selected_options_json or "{}")
    except Exception:
        sel = {}

    for q_idx, q in enumerate(questions):
        qbox = layout.box()
        for tl in _wrap(f"{q_idx + 1} · {q.get('title', '')}", width=max(8, wrap_w - 2)):
            qbox.label(text=tl)

        chosen = sel.get(str(q_idx), [])
        for opt in q.get("options", []):
            val = opt.get("value") or opt.get("label", "")
            lbl = opt.get("label", val)
            is_sel = val in chosen
            orow = qbox.row()
            op = orow.operator("deepseek.select_option", text=lbl,
                               icon='RADIOBUT_ON' if is_sel else 'RADIOBUT_OFF',
                               depress=is_sel)
            op.q_index = q_idx
            op.option_text = val
            op.is_multi = False
            if opt.get("is_rec"):
                orow.label(text="推荐")

        key = str(q_idx)
        oth_open = state.other_open_q == key
        orow = qbox.row()
        orow.operator("deepseek.toggle_other", text="其他", icon='DOT').q_index = q_idx
        if oth_open:
            nbox = qbox.box()
            nbox.label(text=f"补充「{q.get('title', '')}」的细节：", icon='INFO')
            nbox.prop(_note_for(state, q_idx), "text", text="")
        elif len(state.notes) > q_idx and str(state.notes[q_idx].text or "").strip():
            orow.label(text=str(state.notes[q_idx].text)[:18])

    total_sel = sum(len(v) for v in sel.values() if v)
    if total_sel:
        parts = []
        for k in sorted(sel.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            if sel[k]:
                parts.append(sel[k][0])
        line = f"已选 {total_sel} 项 · " + " / ".join(parts)
    else:
        line = "还没有选择"
    layout.label(text=line, icon='INFO')

    brow = layout.row(align=True)
    brow.scale_y = 1.15
    cbtn = brow.row(align=True)
    cbtn.enabled = bool(total_sel > 0)
    cbtn.operator("deepseek.confirm_options", text="确认选择", icon='CHECKMARK')
    brow.operator("deepseek.confirm_options", text="按推荐来", icon='PLAY').use_recommended = True


def _draw_result_tabs(layout, state, item, wrap_w):
    """结果区横向四 tab（互斥），新增对象清单可再折叠"""
    try:
        art = json.loads(item.artifacts_json) if item.artifacts_json else {}
    except Exception:
        art = {}
    obj_list = art.get("objects", [])
    modifiers = art.get("modifiers", [])
    materials = art.get("materials", [])
    geo = art.get("geo", [])
    script_txt = art.get("script", "")
    if not (obj_list or modifiers or materials or geo or script_txt or item.collection_name):
        return

    tab = state.result_tab
    trow = layout.row(align=True)
    for key, text_, ico in (('OBJECTS', "新增对象", 'MESH_DATA'),
                            ('PARAMS', "参数详情", 'MODIFIER'),
                            ('SCRIPT', "脚本摘要", 'CONSOLE'),
                            ('ARCHIVE', "归档信息", 'OUTLINER_COLLECTION')):
        op = trow.operator("deepseek.result_tab", text=text_, icon=ico, depress=(tab == key))
        op.tab = key

    body = layout.box()
    if tab == 'OBJECTS':
        bhead = body.row(align=True)
        bhead.label(text=f"已新增 {len(obj_list)} 个对象", icon='MESH_DATA')
        bhead.operator("deepseek.toggle_card",
                       text="收起" if state.show_result_list else "展开",
                       icon='DISCLOSURE_TRI_DOWN' if state.show_result_list else 'DISCLOSURE_TRI_RIGHT'
                       ).card = "result_list"
        if state.show_result_list:
            for ob in obj_list:
                tag = ob.get("tag", "Object")
                oico = {'Mesh': 'MESH_DATA', 'Material': 'MATERIAL', 'Light': 'LIGHT'}.get(tag, 'OBJECT_DATA')
                r = body.row(align=True)
                r.label(text=ob.get("name", ""), icon=oico)
                r.label(text=tag)
                if ob.get("sub"):
                    body.label(text=f"  {ob['sub']}")
        else:
            body.label(text="列表已收起，点上方标题展开", icon='INFO')
    elif tab == 'PARAMS':
        if geo:
            body.label(text="几何参数", icon='SNAP_VERTEX')
            for k, v in geo:
                r = body.row(align=True)
                r.label(text=f"  {k}")
                r.label(text=v)
        if modifiers:
            body.label(text="修改器栈", icon='MODIFIER')
            for m in modifiers:
                for ln in _wrap(f"  • {m}", width=max(8, wrap_w)):
                    body.label(text=ln)
        if materials:
            body.label(text="材质参数", icon='MATERIAL')
            for k, v in materials:
                r = body.row(align=True)
                r.label(text=f"  {k}")
                r.label(text=v)
        if not (geo or modifiers or materials):
            body.label(text="本次没有记录参数", icon='INFO')
    elif tab == 'SCRIPT':
        if script_txt:
            body.label(text=f"共 {len(script_txt.splitlines())} 行", icon='CONSOLE')
            for ln in script_txt.splitlines()[:18]:
                body.label(text=ln[:wrap_w])
        else:
            body.label(text="本次没有生成脚本", icon='INFO')
    else:
        if item.collection_name:
            body.label(text=f"场景归档合集：{item.collection_name}", icon='OUTLINER_COLLECTION')
            col = bpy.data.collections.get(item.collection_name)
            if col:
                body.label(text=f"包含对象 {len(col.objects)} 个 · 子合集 {len(col.children)} 个")
        r_now = CONTROLLER.run
        if r_now:
            r = body.row(align=True)
            r.label(text="撤销边界")
            can = bool(r_now.receipt and r_now.receipt.boundary_pushed and r_now.receipt.undo_enabled)
            r.label(text="已建立 · 可回退" if can else "未建立")


def _draw_message(layout, context, state, item, run, wrap_w):
    """单条消息：用户右侧留框；AI 不加框，正文直接落在面板底色上。"""
    if item.role == "你":
        meta = layout.row(align=True)
        meta.alignment = 'RIGHT'
        meta.label(text="用户", icon='USER')
        split = layout.split(factor=0.16)
        split.column()
        ubox = split.box()
        ubox.alert = False
        is_confirm = any(item.text.startswith(p) for p in
                         ("参数已确认", "全部按推荐", "按推荐", "参数确认无误"))
        if is_confirm:
            prow = ubox.row(align=True)
            prow.label(text="参数已确认，开始建模", icon='CHECKMARK')
            prow.operator("deepseek.toggle_card",
                          text="收起详情" if state.show_user_params_detail else "查看已选参数",
                          icon='INFO').card = "user_params"
            if state.show_user_params_detail:
                ubox.separator()
                for ln in _wrap(item.text, width=max(8, wrap_w - 6)):
                    ubox.label(text=ln)
        else:
            for ln in _wrap(item.text, width=max(8, wrap_w)):
                ubox.label(text=ln)
        return

    arow = layout.row(align=True)
    arow.label(text="AI 助手", icon='COMMUNITY')
    if item.duration_str:
        arow.label(text=f"耗时 {item.duration_str}")

    if item.steps_json:
        try:
            steps = json.loads(item.steps_json)
        except Exception:
            steps = []
        if steps:
            sbox = layout.box()
            sbox.label(text="执行的操作", icon='FILE_SCRIPT')
            for st in steps:
                for st_line in _wrap(f"✓ {st}", width=max(8, wrap_w - 3)):
                    sbox.label(text=st_line)

    info = parse_interactive_options(item.text)
    for ln in _wrap(info.get("intro", ""), width=wrap_w):
        if ln:
            layout.label(text=ln)

    questions = info.get("questions", [])
    if questions:
        _draw_questions(layout, state, questions, wrap_w)

    for gl in info.get("general", []):
        for ln in _wrap(gl, width=wrap_w):
            if ln:
                layout.label(text=ln)

    for ln in _wrap(info.get("outro", ""), width=wrap_w):
        if ln:
            layout.label(text=ln)

    _draw_result_tabs(layout, state, item, wrap_w)


'''

NEW_STREAM = '''        # 3) 会话流：AI 不加框（直接落在面板底色），用户右侧留框。
        #    N 面板不能滚动，用「显示更早的 N 条」渐进加载代替翻页。
        total = len(state.history)
        start = max(0, total - max(2, state.shown_count))

        if start > 0:
            mrow = layout.row(align=True)
            mrow.scale_y = 0.9
            mrow.operator("deepseek.load_more",
                          text=f"显示更早的 {min(6, start)} 条对话",
                          icon='TRIA_UP')

        wrap_w = get_wrap_width(context, factor=0.92)
        for _idx in range(start, total):
            _draw_message(layout, context, state, state.history[_idx], run, wrap_w)

        # 思考动效：挂在 AI 头像位置（与 AI 消息左对齐同一行）
        if busy:
            import time
            spinner = SPINNERS[int(time.monotonic() * 8) % len(SPINNERS)]
            trow = layout.row(align=True)
            trow.label(text=f"AI 助手  {spinner}", icon='COMMUNITY')
            trow.label(text=get_current_action_text(run))
            trow.operator("deepseek.stop", text="停止", icon='CANCEL')

'''

START_MARK = "        # 3) 对话记录流（自然流式排版，支持鼠标滚轮自由上下翻滚）"
END_MARK = "        # 兜底：若未进入历史但有结算完成的临时回执（如测试 Mock）"
PANEL_MARK = "class DEEPSEEK_PT_chat(bpy.types.Panel):"

with io.open(SRC, "r", encoding="utf-8") as f:
    src = f.read()

# 1) 替换会话流段
i = src.find(START_MARK)
j = src.find(END_MARK)
if i < 0 or j < 0 or j < i:
    raise SystemExit(f"FAIL: marks not found i={i} j={j}")
src = src[:i] + NEW_STREAM + src[j:]
print("stream replaced")

# 2) 插入新渲染函数
k = src.find(PANEL_MARK)
if k < 0:
    raise SystemExit("FAIL: panel class not found")
src = src[:k] + NEW_FUNCS.lstrip("\n") + src[k:]
print("funcs inserted")

with io.open(SRC, "w", encoding="utf-8") as f:
    f.write(src)
print("written, lines =", src.count("\n") + 1)
