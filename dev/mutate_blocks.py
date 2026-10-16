# -*- coding: utf-8 -*-
"""变异验证：故意把被测逻辑打坏，看哪些断言真的变红。

为什么要这个：断言全绿有两种可能——「实现是对的」与「断言是空的」。
栽过的坑有两种：变异被别的守卫兜住（红 0 条），以及断言被注释里同一个词
满足。所以每个变异都必须**指名它应该打红哪几条**，跑完逐条对照，
对不上就说明那条断言不可证伪。

用法：
    python dev/mutate_blocks.py              # 跑全部
    $env:UW_MUT="M1,M7"; python dev\mutate_blocks.py   # 只跑其中几个

每个变异都真的把一份仓库副本打坏、在副本里跑 dev/test_proposal_blocks.py，
所以慢（一次全量约十几分钟）。最后打印 MUTATIONS_ALL_OK / MUTATIONS_HAVE_GAPS，
非零退出码表示有变异没被抓住。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEED = ["ui_workbench", "dev", "blender_deepseek_agent"]

# (名字, 目标文件, 旧文本, 新文本, 期望变红的断言前缀)
MUTS = [
    ("M1_改文案不落到导出",
     "ui_workbench/app.js",
     "    src = src.replace(s.literal, pyStrF(val, s.literal.indexOf(\"f\\\"\") === 0));",
     "    /* mutated: 不再替换 */",
     ("dom_biz_text_edit_in_export", "dom_biz_old_text_replaced")),

    ("M2_导出不再原样带走ui_py",
     "ui_workbench/app.js",
     "  var src = applyBizTexts(String(v.ui_py), b, n);",
     "  var src = \"# mutated: 改成自己编的一句\";",
     ("dom_export_carries_real_code",)),

    ("M3_业务块不走pyBizLines",
     "ui_workbench/app.js",
     "    if (n.bkey) {\n      pyBizLines(out, todo, n, ind);\n      return;\n    }",
     "    if (false) {\n      pyBizLines(out, todo, n, ind);\n      return;\n    }",
     # 故意不指望 dom_export_py_parses：业务块掉进原语那条路之后，
     # 生成出来的是 host + "" + "()" 这种**语法上仍然合法**的代码，
     # ast.parse 当然过。真正抓住它的是 dom_export_carries_real_code
     # （导出里已经没有 ui.py 那两段真实调用了）。
     ("dom_export_carries_real_code",)),

    ("M4_高级区默认展开",
     "ui_workbench/app.js",
     "  det.className = \"advanced\";",
     "  det.className = \"advanced\";\n  det.open = true;",
     ("app_advanced_collapsed_by_default", "dom_adv_collapsed_by_default")),

    ("M5_业务块上又冒出参数框",
     "ui_workbench/app.js",
     "  var idIn = document.createElement(\"input\");\n  idIn.className = \"pin\";\n  idIn.dataset.field = \"id\";",
     "  var idIn = document.createElement(\"input\");\n  idIn.className = \"pin pinp\";\n  idIn.dataset.field = \"params\";",
     ("dom_biz_no_param_box", "dom_biz_has_note_boxes")),

    ("M6_少一块业务块",
     "dev/build_blocks.py",
     "    doc = build()\n    n = _selfcheck(doc)",
     "    doc = build()\n    doc[\"blocks\"] = doc[\"blocks\"][:-1]   # mutated: 砍掉一块\n"
     "    n = _selfcheck(doc)",
     # 故意不指望 dom_shelf_has_every_block：那条比的是「控件架 vs
     # blocks.json 逐块同序」，两边一起少一块时它照样成立——它防的是
     # 界面与数据对不上，不是数据本身少了一块。少一块由块数那几条抓。
     ("blocks_count", "blocks_tab_counts", "dom_shelf_blocks_total",
      "dom_shelf_buttons", "dom_all_status_line")),

    ("M7_编造一行ui_py（既不在ui.py也没登记）",
     # 直接改 blocks.json，不改生成器：改生成器的话 build_blocks.py 自己的
     # 出处自检会先抛 BlockError、拒绝落盘，blocks.json 保持原样——
     # 那证明的是「生成器拦得住」，不是「测试里的出处核对拦得住」。
     # 这里要单独验后者，所以直接往产物里塞一行编的。
     # 注意别连引号一起匹配：ui_py 在 json 里是一整个带 \n 的字符串。
     "ui_workbench/blocks.json",
     "bbox = layout.box()",
     "bbox = layout.MUTATED()",
     ("grounded_no_undeclared_lines",)),

    ("M8_业务块可以嵌套（容器判定放行）",
     "ui_workbench/app.js",
     "function isContainer(n) {\n  // 业务块一律不是容器：它装不了东西（面板上一整块就是它自己）。\n  if (n && n.bkey) { return false; }\n  return n && !n.downgraded && CONTAINER_WKEYS.indexOf(n.wkey) >= 0;\n}",
     "function isContainer(n) {\n  return n && !n.downgraded && CONTAINER_WKEYS.indexOf(n.wkey) >= 0;\n}",
     ("app_biz_is_not_container",)),

    ("M9_业务块少一样输入（改文案）",
     "ui_workbench/app.js",
     '    inp.dataset.field = "btext";',
     '    inp.dataset.field = "btext_MUT";',
     ("dom_biz_has_text_boxes", "app_biz_has_text_slots")),

    ("M10_预览不画业务块",
     "ui_workbench/app.js",
     "  if (n.bkey) {\n    d = pvBiz(n);",
     "  if (false) {\n    d = pvBiz(n);",
     ("dom_biz_preview_nodes",)),

    # ---- Task 20：五条用户意见各自的实现 ----
    # ---- Task 21：响应式图标的取舍反过来（窄 → 只留图标）----
    ("M11_图标永远不显示",
     "ui_workbench/style.css",
     ".demo .d-ic {\n  display: inline-block;",
     ".demo .d-ic {\n  display: none;",
     ("dom_icons_wide_icon_and_text",)),

    ("M12_窄了也不藏文字",
     "ui_workbench/style.css",
     "@container uwpanel (max-width: 360px) {\n  .demo .d-tx { display: none; }",
     "@container uwpanel (max-width: 360px) {\n  .demo .d-tx { display: inline-block; }",
     ("dom_icons_narrow_icon_only",)),

    ("M12b_容器查询写成最小宽度（等于永远不触发）",
     "ui_workbench/style.css",
     "@container uwpanel (max-width: 360px) {",
     "@container uwpanel (min-width: 361px) {",
     ("dom_icons_narrow_icon_only",)),

    ("M12c_窄的时候连图标一起藏",
     "ui_workbench/style.css",
     "  .demo .d-tx { display: none; }",
     "  .demo .d-tx { display: none; }\n  .demo .d-ic { display: none; }",
     ("dom_icons_narrow_icon_only",)),

    ("M13_快捷指令退回 2x2",
     "dev/build_blocks.py",
     '                      "NORMALS_VERTEX"], cols=4)',
     '                      "NORMALS_VERTEX"], cols=2)',
     ("blocks_pills_four_in_one_row", "dom_pills_single_row")),

    ("M14_双层盒退化成一层（规格那组的内层盒不画）",
     "ui_workbench/app.js",
     "  (d.groups || []).forEach(function (g) {",
     "  /* mutated: 不画内层盒 */\n  if (false) (d.groups || []).forEach(function (g) {",
     ("dom_biz_demo_groups", "dom_questions_double_box",
      "dom_questions_intro_in_same_box", "dom_biz_demo_items")),

    ("M15_页签又写回 AI 对话",
     "dev/build_blocks.py",
     '        "demo": D("row", ["对话", "详情", "设置"],',
     '        "demo": D("row", ["AI 对话", "详情", "设置"],',
     ("blocks_tabbar_label_dropped_ai", "blocks_tabbar_items_are_short",
      "dom_tabs_dropped_ai")),

    ("M16_导出的响应式图标那段被删掉",
     "ui_workbench/app.js",
     "  if (pre && proposal.length) {",
     "  if (false && pre && proposal.length) {",
     ("dom_export_has_responsive_icons",)),

    ("M17_预览里压根不画图标角标",
     "ui_workbench/app.js",
     "  if (icon) {\n    var ic = document.createElement(\"b\");\n    ic.className = \"d-ic\";",
     "  if (false && icon) {\n    var ic = document.createElement(\"b\");\n    ic.className = \"d-ic\";",
     # 故意不指望 dom_icons_wide_icon_and_text：那条只比 shown == total，
     # 而分组标题的图标角标走的是 renderDemo 里另一条创建路径（不进
     # demoItem），所以这个变异之后 ico/text 的 total 仍不为 0，那条照样绿。
     # 抓住它的是两条逐卡点数的断言。
     ("dom_icons_rendered_per_card", "dom_icons_in_question_groups")),

    ("M18_编一个实测里没有的图标名",
     # 改产物而不是生成器：改生成器的话 _selfcheck 会先抛 BlockError、
     # 拒绝落盘，blocks.json 保持原样——那证明的是生成器拦得住，
     # 不是测试里的图标核对拦得住。
     "ui_workbench/blocks.json",
     '"CHECKBOX_DEHLT"', '"MUTATED_FAKE_ICON"',
     ("blocks_demo_icons_are_real",)),

    # ---- Task 21：一个盒 / 长消息折叠 / 输入框独占一行 ----
    ("M19_你说的话又套了两层盒",
     # 把那段「没有边框的纯文字」换回带边框的方块：DOM 层级照样只有一个
     # .d-msgtext，但屏幕上多出来第二重框。抓住它的是量 border 宽度那条。
     "ui_workbench/app.js",
     '  txt.className = "d-msgtext";',
     '  txt.className = "d-it";',
     # 故意不指望 dom_biz_demo_items：那条只数方块的**个数**（d-it +
     # d-msgtext 各算一个），把类名从 d-msgtext 换成 d-it 之后个数还是 1，
     # 它照样绿——它防的是「少画了 / 多画了」，不是「多套了一层框」。
     # 真正抓住这一条的是量 border 宽度那条断言。
     ("dom_bubble_user_one_box",)),

    ("M20_折叠态直接把全文给出来",
     "ui_workbench/app.js",
     "  var open = !!(w.node && w.node.msgOpen);",
     "  var open = true;   /* mutated: 不折了 */",
     ("dom_msg_folded_is_summary",)),

    ("M21_折叠态没有展开指示",
     "ui_workbench/app.js",
     "  box.appendChild(tg);\n  return box;\n}",
     "  /* mutated: 不画展开指示 */\n  return box;\n}",
     ("dom_msg_folded_shows_toggle",)),

    ("M22_导出丢掉积木上的展开状态",
     "ui_workbench/app.js",
     '  if (n.msgOpen) {\n    src = src.replace("open_default=False", "open_default=True");\n  }',
     "  /* mutated: 状态不带走 */",
     ("dom_msg_state_reaches_export",)),

    ("M23_导出的折叠自造成一个盒子（不用 layout.panel）",
     "ui_workbench/app.js",
     "  if (helper && proposal.length) {",
     "  if (false && helper && proposal.length) {",
     ("dom_export_has_msg_fold", "dom_msg_state_reaches_export")),

    ("M24_输入框又挤回标签那一行",
     "ui_workbench/app.js",
     '  box.appendChild(tb);\n  return box;\n}',
     '  crow.appendChild(tb);   /* mutated: 塞回同一行 */\n  return box;\n}',
     ("dom_composer_textbox_own_row",)),
]


def copy_repo(dst):
    for n in NEED:
        s = os.path.join(SRC, n)
        d = os.path.join(dst, n)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("_tmp_verify"))
        else:
            shutil.copy2(s, d)


def main():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # 只跑其中几个时用 UW_MUT 过滤，省得每次都等十分钟。
    only = [x for x in (os.environ.get("UW_MUT") or "").split(",") if x]
    muts = [m for m in MUTS if not only or m[0].startswith(tuple(only))]
    tmp = tempfile.mkdtemp(prefix="bizmut_")
    rows = []
    try:
        for name, rel, old, new, want in muts:
            root = os.path.join(tmp, re.sub(r"\W+", "_", name))
            os.makedirs(root, exist_ok=True)
            copy_repo(root)
            p = os.path.join(root, rel)
            with open(p, encoding="utf-8") as fh:
                src = fh.read()
            if old not in src:
                rows.append((name, "PATCH_FAIL", "目标文本没找到（变异没打上）", want))
                continue
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(src.replace(old, new) if rel.endswith("blocks.json")
                         else src.replace(old, new, 1))
            # 生成器改了就得把两份产物都重跑：blocks.json 变了但 data.js 没变的话，
            # 页面读的还是旧数据，DOM 那几条断言量的是上一版界面。
            if rel == "dev/build_blocks.py":
                for script in ("build_blocks.py", "build_data_js.py"):
                    subprocess.run([sys.executable, os.path.join(root, "dev", script)],
                                   cwd=root, capture_output=True, env=env)
            e2 = dict(env)
            e2["UW_ROOT"] = root
            r = subprocess.run([sys.executable, os.path.join(root, "dev", "test_proposal_blocks.py")],
                               cwd=root, capture_output=True, env=e2, timeout=2400)
            out = r.stdout.decode("utf-8", "replace")
            reds = set()
            for m in re.finditer(r"^FAIL (\w+)", out, re.M):
                reds.add(m.group(1))
            summ = re.search(r"^PASS (\d+)  FAIL (\d+)", out, re.M)
            hit = [w for w in want if w in reds]
            miss = [w for w in want if w not in reds]
            rows.append((name,
                         summ.group(0) if summ else "NO_SUMMARY",
                         "红 %d 条" % len(reds),
                         want, hit, miss,
                         sorted(reds)[:8]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n================ 变异结果 ================")
    ok = True
    for r in rows:
        name = r[0]
        summ = r[1]
        want = r[3]
        if summ in ("PATCH_FAIL", "NO_SUMMARY"):
            print("[%s] %s -- %s" % (name, summ, r[2]))
            ok = False
            continue
        if len(r) < 6:
            print("[%s] %s" % (name, summ))
            ok = False
            continue
        hit, miss, reds = r[4], r[5], r[6]
        mark = "OK " if hit and not miss else "BAD"
        if miss or not hit:
            ok = False
        print("[%s] %-28s %s | 期望红 %s | 实红前几个 %s"
              % (mark, name, summ, ",".join(want), ",".join(reds)))
        if miss:
            print("      !! 没红：%s" % ",".join(miss))
    print("==========================================")
    print("MUTATIONS_ALL_OK" if ok else "MUTATIONS_HAVE_GAPS")
    return 0 if ok else 1


sys.exit(main())
