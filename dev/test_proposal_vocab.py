# -*- coding: utf-8 -*-
"""Task 7：受限词汇表 + 提案画布的验收检查。纯标准库，不进 Blender。

用 UW_ROOT 环境变量可以把被测根目录指向任意副本（变异验证靠这个）：
    $env:UW_ROOT = 'C:\\temp\\mutated'; python dev\\test_proposal_vocab.py
不设时测仓库里的 ui_workbench。

两条腿：
  1. Python 侧查 vocabulary.json / data.js / app.js 的静态性质（schema、数量、
     逐字一致、配色铁律、无远程资源、无 NUL）。
  2. 无头 Edge 侧真渲染提案视图，核对 12 个控件与全部降级方案能不能插入、
     拦截拦不拦得住——静态检查看不到 app.js 算出来的 DOM。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("UW_ROOT") or os.path.dirname(HERE)
DEV = os.path.join(ROOT, "dev")
WB = os.path.join(ROOT, "ui_workbench")

EXPECT_WIDGETS = 12          # brief Step 2
EXPECT_REJECTED = 9          # constraints.json 里 native_ok=false 的实数（brief 写的 8 是笔误）
DEMO_PROPS = ["size", "color", "scale", "text"]   # size/color 命中 blocked，scale 不在清单，text 合法

FAILS = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def main():
    cons = json.loads(read(os.path.join(WB, "constraints.json")))
    n_no = len([e for e in cons["entries"] if not e["native_ok"]])

    ck("constraints_not_9", n_no == EXPECT_REJECTED,
       "constraints.json 里 native_ok=false 应为 %d 条，实际 %d（词汇表数量按此为准）"
       % (EXPECT_REJECTED, n_no))

    # ---------- 生成器 ----------
    sys.path.insert(0, DEV)
    import build_vocabulary as bv
    vocab = bv.build(cons)

    ck("gen_widget_count", len(vocab["widgets"]) == EXPECT_WIDGETS,
       "widgets 应为 %d，实际 %d" % (EXPECT_WIDGETS, len(vocab["widgets"])))
    ck("gen_reject_count", len(vocab["rejected"]) == EXPECT_REJECTED,
       "rejected 应为 %d，实际 %d" % (EXPECT_REJECTED, len(vocab["rejected"])))
    keys = [w["key"] for w in vocab["widgets"]]
    ck("gen_widget_keys_unique", len(set(keys)) == len(keys), "widget key 重复：%s" % keys)
    ck("gen_widget_schema", all(
        set(w) == {"key", "label", "uiloayout", "allowed_props", "blocked_props",
                   "note", "constraint_key"}
        for w in vocab["widgets"]), "widget 字段集不对")
    # docstring 承诺「只有 native_ok=true 的能力才能进词汇表」，这条断言把它钉死：
    # 声称依赖某条判定的控件，那条判定必须真的是 native_ok=true
    reg = {e["key"]: e for e in cons["entries"]}
    ck("gen_constraint_key_resolves", all(
        (w["constraint_key"] is None) or (w["constraint_key"] in reg)
        for w in vocab["widgets"]), "有 widget 指向 constraints 里不存在的判定")
    ck("gen_constraint_key_is_ok", all(
        (w["constraint_key"] is None) or reg[w["constraint_key"]]["native_ok"]
        for w in vocab["widgets"]),
       "有 widget 依赖的判定已不是 native_ok=true：%s"
       % [w["key"] for w in vocab["widgets"]
          if w["constraint_key"] and not reg[w["constraint_key"]]["native_ok"]])
    # 而且承诺必须真的被强制：把 constraints 里那条翻脸，build() 要停下来
    bad = json.loads(json.dumps(cons))
    for e in bad["entries"]:
        if e["key"] == "grid_flow":
            e["native_ok"] = False
            e["blocker"] = "翻脸了"
            e["fallback"] = "改用别的"
    try:
        bv.build(bad)
        raised = False
        why = "build() 照发不误"
    except bv.VocabularyError as exc:
        raised = True
        why = str(exc)
    ck("gen_enforces_native_ok", raised, why)
    ck("gen_props_disjoint", all(
        not (set(w["allowed_props"]) & set(w["blocked_props"])) for w in vocab["widgets"]),
        "同一控件的允许清单与拦截清单有交集")
    ck("gen_props_scope_says_subset", bool(vocab.get("props_scope")) and
       "精选子集" in vocab["props_scope"],
       "缺少「allowed_props 是精选子集不是全量 API」的说明")
    ck("gen_reject_schema", all(
        set(r) == {"key", "label", "blocker", "fallback"} for r in vocab["rejected"]),
        "rejected 字段集不对")
    ck("gen_reject_from_nofail", sorted(r["key"] for r in vocab["rejected"]) ==
       sorted(e["key"] for e in cons["entries"] if not e["native_ok"]),
       "rejected 必须与 native_ok=false 的条目一一对应")

    # 降级方案不能是空话：逐字取自 constraints.json，且提到具体手段
    src = json.dumps(cons, ensure_ascii=False)
    ck("gen_fallback_verbatim", all(r["fallback"] and r["fallback"] in src for r in vocab["rejected"]),
       "有 fallback 不是 constraints.json 的原句或为空")
    ck("gen_fallback_actionable", all(
        re.search(r"layout\.|icon=|alert|分页|折叠|active|enabled|#[0-9a-fA-F]{6}", r["fallback"])
        for r in vocab["rejected"]),
       "有 fallback 没给出可执行手段：%s" % [r["key"] for r in vocab["rejected"]
                                          if not re.search(r"layout\.|icon=|alert|分页|折叠|active|enabled|#[0-9a-fA-F]{6}", r["fallback"])])
    ck("gen_blocker_verbatim", all(r["blocker"] and r["blocker"] in src for r in vocab["rejected"]),
       "有 blocker 不是 constraints.json 的原句或为空")

    # 「可做、但词汇表没收录」的能力不许无声消失（Important 3）：
    # progress_bar 在 constraints 里 native_ok=true，却既不在 12 个控件里、
    # 也不在 rejected 里，只能靠这张表在提案视图里显式说出来。
    mapped = set(w["constraint_key"] for w in vocab["widgets"] if w["constraint_key"])
    want_unmapped = sorted(e["key"] for e in cons["entries"]
                           if e["native_ok"] and e["key"] not in mapped)
    ck("gen_unmapped_ok", sorted(u["key"] for u in vocab["unmapped_ok"]) == want_unmapped,
       "unmapped_ok 应为 %s，实际 %s"
       % (want_unmapped, [u["key"] for u in vocab["unmapped_ok"]]))
    ck("gen_unmapped_schema", all(
        set(u) == {"key", "label", "uiloayout", "evidence"} for u in vocab["unmapped_ok"]),
        "unmapped_ok 字段集不对")
    ck("gen_progress_bar_visible", "progress_bar" in want_unmapped,
       "progress_bar 是 native_ok=true 却没人映射，提案视图里会彻底消失")

    # ---------- 落盘产物 ----------
    vp = os.path.join(WB, "vocabulary.json")
    ck("vocab_file_exists", os.path.exists(vp), "缺 ui_workbench/vocabulary.json")
    if os.path.exists(vp):
        raw = open(vp, "rb").read()
        ck("vocab_nul", b"\x00" not in raw, "含 NUL 字节")
        on_disk = json.loads(raw.decode("utf-8"))
        ck("vocab_matches_generator", on_disk == vocab,
           "vocabulary.json 与 build() 输出不一致，需要重跑 dev/build_vocabulary.py")
        ck("vocab_generated_for", on_disk.get("generated_for") == cons["generated_for"],
           "generated_for 没跟着 constraints 走")

    dj = os.path.join(WB, "data", "data.js")
    ck("data_js_has_vocab", os.path.exists(dj), "缺 data/data.js")
    payload = None
    if os.path.exists(dj):
        body = read(dj)
        m = re.search(r"window\.UW_DATA\s*=\s*(\{.*\});?\s*$", body, re.S)
        if m:
            payload = json.loads(m.group(1))
        ck("data_js_vocab_key", payload is not None and "vocabulary" in payload,
           "data/data.js 里没有 vocabulary 键，重跑 python dev\\build_data_js.py")
        if payload is not None and "vocabulary" in payload:
            ck("data_js_vocab_same", payload["vocabulary"] == vocab,
               "data.js 里的 vocabulary 与 vocabulary.json 不一致")

    # ---------- 静态检查 app.js / index.html ----------
    app = read(os.path.join(WB, "app.js"))
    html = read(os.path.join(WB, "index.html"))
    raw = open(os.path.join(WB, "app.js"), "rb").read()
    ck("app_nul", b"\x00" not in raw, "app.js 含 NUL 字节")
    ck("app_no_remote", "http://" not in app and "https://" not in app,
       "app.js 引用了远程资源")
    # 配色铁律：app.js 里不允许出现字面色值（Task 6 只扫 style.css，
    # 这里补上——brief 给的示例代码里有 #e0716a 这种主题里根本没有的红）
    hexes = sorted(set(re.findall(r"#[0-9a-fA-F]{3,6}\b", re.sub(r"/\*.*?\*/", "", app, flags=re.S))))
    ck("app_no_literal_colors", not hexes, "app.js 里出现字面色值：%s" % hexes)

    for fn in ("el(\"vocab-bar\")", "el(\"canvas\")", "el(\"prop-notes\")"):
        ck("app_uses_%s" % re.sub(r"\W", "", fn), fn in app, "app.js 未挂载 %s" % fn)
    ck("app_blocked_check", "w.blocked_props.indexOf(p) >= 0" in app,
       "app.js 丢了 blocked_props 拦截")
    ck("app_allowlist_check", "w.allowed_props.indexOf(p) < 0" in app,
       "app.js 丢了允许清单之外的拦截")
    ck("app_downgraded_flag", "dataset.downgraded" in app and "downgraded: true" in app,
       "降级项没有被标记成降级")
    ck("app_export_proposal", '"proposal": proposal' in app or "proposal: proposal" in app,
       "导出按钮没有带上提案")
    ck("app_missing_vocab_msg", "vocabulary.json 缺失" in app and "build_vocabulary.py" in app,
       "缺 vocabulary.json 时没有可操作的错误提示")
    ck("html_slots", all(x in html for x in ('id="vocab-bar"', 'id="canvas"', 'id="prop-notes"')),
       "index.html 的提案视图挂载点不全")

    # ---------- Task 10：拖拽排序 ----------
    # 拖拽视觉三件套必须真的有样式，否则「有 draggable 属性但看不出来」等于没做。
    css = read(os.path.join(WB, "style.css"))
    ck("css_drop_handler", ".drop-handler" in css, "style.css 没定义拖拽手柄 .drop-handler")
    ck("css_drop_line", ".drop-line" in css, "style.css 没定义放置指示线 .drop-line")
    ck("css_dragging", ".pnode.dragging" in css, "style.css 没定义拖拽中的 .pnode.dragging")
    for ev in ("dragstart", "dragover", "drop", "dragend"):
        ck("app_drag_%s" % ev, '"%s"' % ev in app,
           "app.js 没有监听 %s（原生 draggable 四件套缺一不可）" % ev)
    # 零依赖铁律：拖拽只能用原生 draggable。
    # 匹配具体库名而不是 "dnd" 这种三字母子串——后者会误伤 bindCanvasDnd。
    ck("app_drag_no_library",
       not any(s in app.lower() for s in
               ("sortablejs", "dnd-kit", "react-dnd", "jquery-ui", "interactjs"))
       and "draggable" in app,
       "拖拽只能靠原生 draggable；app.js 里出现了拖拽库或连原生都没用")
    # reorderTo 的静态负面检查：重排只许换顺序，碰 uid 就是让标注串块。
    # 这里不重演算法（语义交给浏览器里真跑的那条），只查它有没有改写身份。
    rb = js_body(app, "function reorderTo")
    ck("app_reorder_exists", bool(rb), "app.js 里找不到 reorderTo")
    ck("app_reorder_no_uid_mint", bool(rb) and "nextUid" not in rb,
       "reorderTo 里调了 nextUid——重排绝不能重建身份")
    ck("app_reorder_no_uid_write", bool(rb) and not re.search(r"\buid\b\s*=(?!=)", rb),
       "reorderTo 里给 uid 赋值——重排绝不能改写身份")
    ck("app_undo_present", "lastDeleted" in app and "undoDelete" in app,
       "缺单步撤销（lastDeleted / undoDelete）")

    # ---------- Task 11：折叠积木 / 整块可拖 / 提案视图隐藏胶片条 ----------
    # 静态侧钉的是「谁负责」，DOM 侧钉的是「实际长什么样」，两边都要。
    # 先抹掉 CSS 注释再扫。style.css 顶上那段解释「为什么需要 !important」的
    # 注释里就写着 [hidden]{display:none} 这个字面量——不抹的话，
    # 把真规则删掉这条断言照样绿（变异验证实测过：删掉规则，142 条全过）。
    css_scan = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    ck("css_hidden_rule",
       re.search(r"\[hidden\]\s*\{[^}]*display:\s*none", css_scan) is not None,
       "style.css 必须有 [hidden]{display:none} —— .filmstrip 声明了 display:flex，"
       "会盖掉 UA 的 [hidden]{display:none}，hidden=true 就不生效")
    ck("css_pnode_grab_cursor",
       re.search(r"\.pnode\s*\{[^}]*cursor:\s*grab", css_scan) is not None,
       "整块可拖必须让光标说清楚（.pnode 上的 cursor: grab），否则用户读不出可拖")
    aw = js_body(app, "function addWidget")
    ck("app_addwidget_defaults_collapsed", bool(aw) and re.search(r"expanded\s*:\s*false", aw),
       "新建积木必须 expanded: false —— 默认不折叠的话，每块仍是 3 个常驻输入框")
    sp = js_body(app, "function setParams")
    ck("app_setparams_auto_expands",
       bool(sp) and re.search(r"errors\.length\)\s*\{\s*n\.expanded\s*=\s*true", sp),
       "拦截时必须把 n.expanded 置成 true（自动展开给你看违规在哪）")
    rb2 = js_body(app, "function dupNode")
    ck("app_dup_keeps_expanded",
       bool(rb2) and not re.search(r"\bexpanded\b\s*=(?!=)", rb2),
       "dupNode 不该复位 expanded —— 复制的是「当前这块的样子」，"
       "复制一块配好的积木不该把参数又藏回折叠态")
    # dragstart 的按钮豁免：整块可拖放开之后，这条守卫就是复制 / 删除还能不能点的命。
    ds = js_body(app, "function bindCanvasDnd")
    ck("app_dragstart_skips_buttons",
       bool(ds) and re.search(r'closest\("input,\s*textarea,\s*button"\)', ds) is not None,
       "dragstart 必须排除 button —— 不挡的话点「复制」「删除」会变成一次拖拽")
    sw = js_body(app, "function switchView")
    ck("app_switchview_hides_filmstrip",
       bool(sw) and "filmstrip" in sw,
       "胶片条归 switchView 管：提案视图下那 7 个状态按钮毫无意义，"
       "却会让人以为得先选状态才能提案")

    dom_checks()

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for p in BROWSERS:
        if p and os.path.exists(p):
            return p
    return None


def dump(exe, url, profile):
    p = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--user-data-dir=" + profile,
         "--window-size=1400,1400", "--virtual-time-budget=9000",
         "--dump-dom", url],
        capture_output=True, timeout=180)
    return p.stdout.decode("utf-8", "replace")


def dom_checks():
    exe = find_browser()
    if not exe:
        # 不能只 WARN 就 return：那样 12 条真正证明「拦截会触发」的断言会全部
        # 蒸发，而 rc 仍然是 0——这正是全局约束禁掉的假绿。默认记失败；
        # 确实没有浏览器的机器可以显式设 UW_SKIP_DOM=1 承认这一点。
        ck("dom_browser_present", os.environ.get("UW_SKIP_DOM") == "1",
           "找不到 Edge/Chrome，渲染腿整条没跑（UW_SKIP_DOM=1 可显式承认）")
        return
    url = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    profile = tempfile.mkdtemp(prefix="uw_proposal_")
    try:
        with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
            vjson = json.load(fh)
        empty = dump(exe, url + "#proposal-empty", profile)
        ck("dom_vocab_buttons", len(re.findall(r'<button data-wkey="[^"]+"', empty)) == EXPECT_WIDGETS,
           "提案视图应渲染 %d 个控件按钮，实际 %d"
           % (EXPECT_WIDGETS, len(re.findall(r'<button data-wkey="[^"]+"', empty))))
        ck("dom_reject_buttons", len(re.findall(r'<button data-rkey="[^"]+"', empty)) == EXPECT_REJECTED,
           "应渲染 %d 条降级按钮，实际 %d"
           % (EXPECT_REJECTED, len(re.findall(r'<button data-rkey="[^"]+"', empty))))
        ck("dom_empty_hint", 'id="empty-hint"' in empty, "空画布没有提示")
        hint = empty_hint_of(empty)
        ck("dom_empty_hint_teaches_drag", "拖" in hint,
           "空态引导还在教人用表单（只字未提「拖」）——"
           "用户原话是「还是有点不太会用」：%r" % hint)
        ck("dom_empty_hint_keeps_fallback", "做不到" in hint,
           "空态引导丢了「做不到」列表的指引：%r" % hint)
        ck("dom_empty_hint_keeps_scope", "顺序" in hint,
           "空态引导没说明「积木顺序 = 面板顺序」，用户不知道为什么能重排：%r" % hint)
        bar = vocab_bar_of(empty)
        ck("dom_vocab_bar_head_teaches_drag",
           "拖动换位" in "".join(re.findall(r"<b>(.*?)</b>", bar, re.S)),
           "控件架的标题没提示积木可以拖动换位：%r" % bar[:160])
        btitles = re.findall(r'<button data-wkey="[^"]*" title="([^"]*)"', bar)
        ck("dom_vocab_bar_button_title_teaches_drag",
           len(btitles) == EXPECT_WIDGETS and all("拖动换位" in t for t in btitles),
           "12 个控件按钮的 title 里，有 %d 个没说明可拖动换位（抓到 %d 个按钮）"
           % (sum(1 for t in btitles if "拖动换位" not in t), len(btitles)))
        ck("dom_empty_no_nodes", 'class="note pnode' not in empty,
           "没点任何控件就不该有提案节点")
        # 可做但没收录的能力必须在提案视图里显形（Important 3）
        ck("dom_unmapped_row", 'data-ukey="progress_bar"' in empty,
           "提案视图没有列出「可做但词汇表尚未收录」的能力")
        ck("dom_unmapped_note", "尚未收录" in empty,
           "缺少「尚未收录」的说明文案")
        ck("dom_props_scope", "精选子集" in empty,
           "没有说明 allowed_props 是精选子集，容易被当成全量 API")

        # --- Task 11-C：提案视图下的胶片条 ---
        # 必须切到「提案视图」和「镜像视图」各渲染一次来比：
        # 只看提案视图那份，删掉整行胶片条和「没藏起来」长得一模一样。
        mirror = dump(exe, url, profile)
        ptag, mtag = tag_of(empty, "filmstrip"), tag_of(mirror, "filmstrip")
        ck("filmstrip_tag_found", bool(ptag) and bool(mtag),
           "两份 dump 里都该找得到 #filmstrip，实际 %r / %r" % (ptag, mtag))
        ck("filmstrip_hidden_in_proposal", bool(ptag) and "hidden" in ptag,
           "提案视图下状态胶片条必须隐藏：那 7 个按钮切的是镜像视图的实机截图，"
           "放在提案视图上方会让人以为要先选状态：%r" % ptag)
        ck("filmstrip_visible_in_mirror", bool(mtag) and "hidden" not in mtag,
           "切回镜像视图后胶片条必须恢复：%r" % mtag)
        # 隐藏 ≠ 清空：两份 dump 里的按钮数应当一样多，变的只是 hidden。
        # 拿「同一个数互相比」而不是写死 7，镜像视图以后加减状态也不会误报。
        pbtns = len(re.findall(r"<button", filmstrip_of(empty)))
        mbtns = len(re.findall(r"<button", filmstrip_of(mirror)))
        ck("filmstrip_hidden_not_emptied",
           mbtns > 0 and pbtns == mbtns,
           "胶片条应当只是被藏起来，不是被清空：镜像 %d 个按钮 / 提案 %d 个"
           % (mbtns, pbtns))
        # 视图本体本身不许被连带藏掉：藏胶片条不能顺手把镜像视图也藏了
        mv = re.search(r'<section id="view-mirror"[^>]*>', mirror)
        ck("filmstrip_does_not_hide_mirror_view",
           mv is not None and "hidden" not in mv.group(0),
           "镜像视图本体在默认状态下必须可见：%r" % (mv.group(0) if mv else "<missing>"))

        allp = dump(exe, url + "#proposal-all", profile)
        nodes = re.findall(r'<div class="note pnode[^"]*"[^>]*>', allp)
        ck("dom_all_count", len(nodes) == EXPECT_WIDGETS + EXPECT_REJECTED,
           "点击后应有 %d 个提案节点，实际 %d" % (EXPECT_WIDGETS + EXPECT_REJECTED, len(nodes)))
        # 12 个控件全部 status=ok / errors=0 —— 这是「词汇表内全部合法」的判定
        wnodes = re.findall(r'<div class="note pnode"[^>]*data-wkey="([^"]*)" data-downgraded="0" '
                            r'data-status="([^"]*)" data-errors="([^"]*)"', allp)
        ck("dom_all_widgets_ok", len(wnodes) == EXPECT_WIDGETS and
           all(s == "ok" and e == "0" for _, s, e in wnodes),
           "词汇表内控件应全部合法，实际 %s" % [(k, s, e) for k, s, e in wnodes if s != "ok" or e != "0"])
        dnodes = re.findall(r'<div class="note pnode down"[^>]*data-wkey="__downgraded__" '
                            r'data-downgraded="1" data-status="downgraded" data-errors="0" '
                            r'data-rkey="([^"]*)"', allp)
        ck("dom_all_downgraded", len(dnodes) == EXPECT_REJECTED and
           sorted(dnodes) == sorted(r["key"] for r in vjson["rejected"]),
           "%d 条降级方案应全部插入且标记为 downgraded，实际 %s"
           % (EXPECT_REJECTED, sorted(dnodes)))
        # 每条降级方案都要把「原需求做不到 + 降级方案」两行写进画布节点里。
        # 必须只扫 #canvas：按钮的 title 里也抄了一遍 fallback 文案，
        # 扫全文档的话这条断言就算画布上什么都没写也会绿（变异验证实测过）。
        canvas = canvas_of(allp)
        ck("dom_all_canvas_found", bool(canvas.strip()), "定位不到画布区域")
        missing_fb = [k for k in dnodes if _fb_for(k) not in canvas]
        ck("dom_all_fallback_text", not missing_fb,
           "有降级方案没写进画布：%s" % missing_fb)
        missing_bl = [k for k in dnodes if _fb_for_blocker(k) not in canvas]
        ck("dom_all_blocker_text", not missing_bl,
           "有原需求理由没写进画布：%s" % missing_bl)
        ck("dom_all_strike", canvas.count('class="strike"') == EXPECT_REJECTED,
           "原需求删除线应出现 %d 次，实际 %d"
           % (EXPECT_REJECTED, canvas.count('class="strike"')))
        ck("dom_all_uilayout", canvas.count("layout.") >= EXPECT_WIDGETS,
           "12 个控件的 UILayout 调用没都渲染进画布（必须数 canvas 切片："
           "按钮 title 里也有一份，数整份文档的话这条不可证伪）")

        blk = dump(exe, url + "#proposal-blocked", profile)
        m = re.search(r'<div class="note pnode blocked"[^>]*data-wkey="label" '
                      r'data-downgraded="0" data-status="blocked" data-errors="(\d+)"', blk)
        ck("dom_block_label", m is not None,
           "label 写了违规参数后没有被标成 blocked")
        if m:
            ck("dom_block_errors", m.group(1) == "3",
               "size/color/scale/text 应产生 3 条拦截，实际 %s" % m.group(1))
        ck("dom_block_perr", blk.count('class="perr"') == 3,
           "应有 3 条拦截文案，实际 %d" % blk.count('class="perr"'))
        ck("dom_block_msg_blocked", blk.count("不被 UILayout 支持") == 2,
           "size/color 应各报一次「不被支持」，实际 %d" % blk.count("不被 UILayout 支持"))
        ck("dom_block_msg_allowlist", blk.count("不在「") == 1,
           "scale 应报一次「不在允许清单」，实际 %d" % blk.count("不在「"))
        lab = blk.split('<div class="note pnode blocked"')[-1].split("</textarea>")[0] \
            if '<div class="note pnode blocked"' in blk else ""
        chips_ok = lab.count('<span class="chip">text</span>')
        chips_bad = len(re.findall(r'<span class="chip bad">[^<]*✗</span>', lab))
        ck("dom_block_chip_ok", chips_ok == 1,
           "合法参数 text 应渲染成非 bad chip，实际 %d" % chips_ok)
        ck("dom_block_chip_bad", chips_bad == 3,
           "3 个违规参数应各渲染一个 bad chip，实际 %d" % chips_bad)
        ck("dom_block_status_span", 'data-status="blocked"' in blk and 'data-status="ok"' in blk,
           "合法与违规节点应共存：合法控件 11 个，违规 1 个")
        ck("dom_block_others_ok", len(re.findall(
            r'data-wkey="[^"]*" data-downgraded="0" data-status="ok" data-errors="0"', blk)) == 11,
           "除 label 外其余 11 个控件仍应合法")

        # --- Important 1：真 input 事件下的焦点与字符完整性 ---
        # #proposal-blocked 走的是 setParams() 直调，绕开了用户真正会走的那条路。
        # 这里派发真的 input 事件逐字符敲，模拟浏览器的真实行为：
        # 元素一旦被 renderCanvas 摘出文档，后续按键就打到 body，字符会丢。
        typ = dump(exe, url + "#proposal-typing", profile)
        rep = re.search(r'<div id="typing-report"([^>]*)>', typ)
        ck("dom_typing_report", rep is not None, "没有拿到逐字符输入报告")
        if rep:
            at = dict(re.findall(r'data-([a-z]+)="([^"]*)"', rep.group(1)))
            ck("dom_typing_no_char_lost", at.get("lost") == "0",
               "有 %s 个字符被吞掉（每敲一个键都重建画布，输入框失焦）"
               % at.get("lost"))
            ck("dom_typing_value", at.get("value") == "scale_ys",
               "输入框最终值应为 scale_ys，实际 %r" % at.get("value"))
            ck("dom_typing_focus", at.get("focused") == "true",
               "输入完焦点已丢，后续按键会打到 body")
            ck("dom_typing_caret", at.get("caret") == str(len(at.get("value", "")) // 2),
               "光标位置没还原到插入点（应在中间），实际在 %s" % at.get("caret"))
            ck("dom_typing_blocked", at.get("status") == "blocked" and at.get("errors") == "1",
               "多敲的那个 s 应被判违规，实际 status=%s errors=%s"
               % (at.get("status"), at.get("errors")))

        # --- Task 9：稳定 uid + 删除 + 复制 ---
        # 每块积木都要带身份。没有身份就没有任何东西能把「我编辑的是哪一块」
        # 这个问题问对——data-idx 是位置，删掉中间一块后面全串位。
        uids = re.findall(r'<div class="note pnode[^"]*"[^>]*data-uid="([^"]*)"', allp)
        ck("dom_uid_on_every_node", len(uids) == EXPECT_WIDGETS + EXPECT_REJECTED,
           "每块积木都要有 data-uid，实际 %d / 共 %d 块"
           % (len(uids), EXPECT_WIDGETS + EXPECT_REJECTED))
        ck("dom_uid_unique_all", bool(uids) and all(uids) and len(set(uids)) == len(uids),
           "uid 重复或为空：%s" % uids)
        # 每块一个删除、一个复制按钮。
        # 期望值写死成字面量 21，不写成 node_count()：两边同时为 0 时
        # 0 == 0 恒真，只能靠别的断言兜底——依赖别人保证非空洞等于没保证。
        cvs = canvas_of(allp)
        ck("dom_del_button_per_node", cvs.count('data-act="del"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个删除按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="del"')))
        ck("dom_dup_button_per_node", cvs.count('data-act="dup"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个复制按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="dup"')))
        ck("fold_button_per_node", cvs.count('data-act="fold"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 个展开/收起按钮，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('data-act="fold"')))

        # --- Task 11-A：默认折叠 ---
        # 12 块常驻输入框 = 1800px 的滚动，这就是它读起来还像表单的原因。
        # 这里数 canvas 切片里 data-field 的出现次数：折叠时它们一个都不该在 DOM 里。
        # 期望值写死成 0（不是 count()==count()），两边同时为 0 时那种恒真不许出现。
        ck("fold_default_no_fields_in_dom",
           cvs.count('data-field="params"') == 0 and
           cvs.count('data-field="id"') == 0 and
           cvs.count('data-field="note"') == 0 and
           cvs.count('data-expanded="1"') == 0,
           "点完控件后积木应当全是折叠的：params=%d id=%d note=%d 已展开=%d"
           % (cvs.count('data-field="params"'), cvs.count('data-field="id"'),
              cvs.count('data-field="note"'), cvs.count('data-expanded="1"')))

        # 删除：#proposal-del 里点的是画布上真实的删除按钮
        dele = dump(exe, url + "#proposal-del", profile)
        ck("dom_delete_noop_on_stale_uid", del_on_stale_uid_is_noop(dele),
           "块已经被删掉后再点它那个过期按钮，必须什么都不做——"
           "idxByUid 返回 -1，proposal.splice(-1, 1) 会静默删掉最后一块")
        ck("dom_delete_removes_one", del_last_node(dele), "删除最后一块后块数应减一")
        ck("dom_delete_no_uid_reuse", del_last_node_then_check_uid(dele),
           "删掉中间一块后，其余积木的 uid 必须原样保留（身份不等于位置）")
        ck("dom_delete_dom_uids_match", del_dom_uids_match_array(dele),
           "删除后渲染出来的存活积木 uid 必须与数组一致（否则焦点/标注会串到别的块）")

        # 复制：副本必须拿到全新 uid，否则焦点和标注会串回原块
        dupd = dump(exe, url + "#proposal-dup", profile)
        ck("dom_dup_adds_one", dup_last_node(dupd), "复制后块数应加一")
        ck("dom_dup_gets_new_uid", dup_gets_distinct_uid(dupd),
           "复制的积木必须是新 uid，否则焦点和标注会串到原块上")

        # --- Task 10：拖拽 ---
        # 每块积木都要能拖，拖拽视觉（手柄）也必须真的渲染出来。
        # 期望值写死成字面量 21，不写成 count() == count()：两边同时为 0 时
        # 恒真，只能靠别的断言兜底——依赖别人保证非空洞等于没保证。
        ck("drag_dom_draggable_nodes",
           cvs.count('draggable="true"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "应有 %d 块积木带 draggable=true，实际 %d"
           % (EXPECT_WIDGETS + EXPECT_REJECTED, cvs.count('draggable="true"')))
        ck("drag_dom_handler_per_node",
           cvs.count('class="drop-handler"') == EXPECT_WIDGETS + EXPECT_REJECTED,
           "每块积木左侧都该有一个拖拽手柄，实际 %d"
           % cvs.count('class="drop-handler"'))
        drag_checks(dump(exe, url + "#proposal-drag", profile))
        undo_checks(dump(exe, url + "#proposal-undo", profile), empty)
        fold_checks(dump(exe, url + "#proposal-fold", profile))
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def vocab_bar_of(p):
    """取 #vocab-bar 宿主的切片。

    上一版这条断言扫的是整份 dump，而空态引导的文案里就含「拖动换位」——
    把 renderVocabBar 的标题和按钮 title 全改回原文，它照样绿。
    同一个坑本文件的 canvas_of docstring 早就记过一次，这里是第二次。
    #canvas 在 index.html 里紧跟在 #vocab-bar 后面，按这对标记切最省事。
    """
    if '<div id="vocab-bar"' not in p or '<div id="canvas"' not in p:
        return ""
    return p.split('<div id="vocab-bar"')[1].split('<div id="canvas"')[0]


def empty_hint_of(p):
    """取空态引导那一句的正文。

    不做「整份文档里有没有『拖』」的判断：控件按钮的 title 里也写着拖，
    那样这条断言在引导文案一个字没改的情况下照样绿（不可证伪）。
    """
    m = re.search(r'<p id="empty-hint"[^>]*>(.*?)</p>', p, re.S)
    if not m:
        return ""
    txt = m.group(1)
    for a, b in (("&quot;", '"'), ("&#39;", "'"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&amp;", "&")):
        txt = txt.replace(a, b)
    return txt


def tag_of(p, eid):
    """取 id=`<eid>` 那个元素的起始标签（含全部属性）。

    胶片条这条断言要看的是 hidden 属性——而 hidden 是设在外层
    #filmstrip 上的，只看内层第一个 <button> 就会把「藏了」判成「没藏」。
    找不到返回空串：后续 `X in ""` 恒为 False，判定必红，不会蒙过去。
    """
    m = re.search(r'<[a-z]+[^>]*\bid="%s"[^>]*>' % re.escape(eid), p)
    return m.group(0) if m else ""


def filmstrip_of(p):
    """取 #filmstrip 的内容切片（#view-mirror 是它的下一个兄弟）。"""
    if '<div id="filmstrip"' not in p or '<section id="view-mirror"' not in p:
        return ""
    return p.split('<div id="filmstrip"')[1].split('<section id="view-mirror"')[0]


def drag_checks(p):
    """拖拽排序：语义与清理都在浏览器里真跑一遍，不在 Python 侧重演算法。

    「在 Python 侧重放 reorderTo 的语义」是靠不住的：源码能区分变体，
    断言却仍可能恒真恒假（Task 7 的 SUBSTR in texts 就栽在这儿）。
    这里直接派发真的 DragEvent，走的是用户拖鼠标时同一条代码路径。
    """
    at = report(p, "drag-report")
    before = _uids(at, "before-uids")
    after = _uids(at, "after-uids")
    after2 = _uids(at, "after-fwd-uids")
    want_n = EXPECT_WIDGETS + EXPECT_REJECTED
    ck("drag_hook_ran",
       len(before) == want_n and len(after) == want_n and len(after2) == want_n,
       "拖拽钩子没跑起来或块数不对：before=%d after=%d after2=%d"
       % (len(before), len(after), len(after2)))
    if len(before) != want_n or len(after) != want_n or len(after2) != want_n:
        return

    # 拖起过程中必须有落位指示线；不画线的话用户根本不知道会落在哪。
    ck("drag_line_shown_on_dragover", at.get("line-seen") == "1",
       "dragover 期间画布上应恰好有一条放置指示线，实际 %s" % at.get("line-seen"))
    # 语义一：把第 3 块拖到第 1 位 -> [3,1,2,4…]（往前拖）
    want = [before[2], before[0], before[1]] + before[3:]
    ck("drag_reorder_semantics", after == want,
       "从第 3 块拖到第 1 位后顺序应为 %s，实际 %s" % (want, after))
    # 语义二：再把第 1 块拖到第 4 位 -> [2,3,1,4…]（往后拖）。
    # 这一条才是 at 里那个 -1 的照妖镜：源被取出后后面的元素已经往前挪了一位，
    # 少减/多减一格都会在这里现形。只测「往前拖」的话这半边代码形同虚设。
    want2 = [after[1], after[2], after[0]] + after[3:]
    ck("drag_reorder_semantics_backward", after2 == want2,
       "把第 1 块往后拖到第 4 位后顺序应为 %s，实际 %s" % (want2, after2))
    # 身份不随位置变：uid 集合必须原样（重建 uid 的话标注会整片串块）。
    ck("drag_reorder_keeps_uid", sorted(after) == sorted(before) and sorted(after2) == sorted(before),
       "重排改写了 uid 集合：before=%d after=%d after2=%d 差集 %s"
       % (len(before), len(after), len(after2),
          sorted(set(before) ^ set(after) ^ set(after2))))
    ck("drag_reorder_dom_matches", _uids(at, "dom-uids") == after2,
       "重排后画布上渲染出来的 uid 顺序与数组不一致")
    # 落位成功那条：drop 自己就要收干净，不许指望 dragend——
    # drop 里 renderCanvas() 会把源节点摘掉，之后的 dragend 未必还冒泡得到。
    ck("drag_drop_clears_line", at.get("line-after-drop") == "0",
       "drop 之后放置指示线必须消失，实际 %s" % at.get("line-after-drop"))
    ck("drag_drop_clears_state", at.get("state-after-drop") == "null",
       "drop 之后 dragState 必须置空，实际 %s" % at.get("state-after-drop"))
    # 取消那条：拖到一半按 Esc / 丢在画布外，只有 dragend 能收尾。
    # 这三条就是「漏掉 dragend 清理」的照妖镜——漏了画布会永久卡在拖拽态。
    ck("drag_cancel_clears_line", at.get("line-after-cancel") == "0",
       "取消拖拽后放置指示线必须消失，实际 %s" % at.get("line-after-cancel"))
    ck("drag_cancel_clears_dragging", at.get("dragging-after-cancel") == "0",
       "取消拖拽后 .pnode.dragging 必须摘干净，实际还剩 %s 块"
       % at.get("dragging-after-cancel"))
    ck("drag_cancel_clears_state", at.get("state-after-cancel") == "null",
       "取消拖拽后 dragState 必须置空，实际 %s" % at.get("state-after-cancel"))
    ck("drag_cancel_keeps_order", at.get("order-after-cancel") == ",".join(before),
       "取消拖拽不许改动任何积木的顺序")

    # 整块可拖之后，按钮上按下不许触发拖拽——不然复制 / 删除就点不动了。
    ck("drag_button_press_not_drag", at.get("state-after-btn") == "null",
       "在复制按钮上按下必须被 dragstart 挡掉，实际 dragState=%s"
       % at.get("state-after-btn"))
    ck("drag_button_press_no_dragging_class",
       at.get("dragging-after-btn") == "0",
       "在按钮上按下不该给积木挂上 .dragging，实际 %s 块"
       % at.get("dragging-after-btn"))

    # reorderTo 的负 toIdx 守卫。UI 走不到这条路（dropIndexAt 只给 0..n），
    # 所以这里直接调那个被明确导出为「拖拽与测试共用」的入口。
    # 不夹紧的话 splice(-1, 0, item) 会把最后一块插回倒数第二位——
    # 顺序看上去纹丝不动，正是最难被发现的那种错。
    gb, ga = _uids(at, "guard-before-uids"), _uids(at, "guard-after-uids")
    moved = at.get("guard-moved-uid", "")
    ck("reorder_negative_to_idx_is_clamped",
       bool(gb) and len(gb) == len(ga) and bool(moved) and
       ga[0] == moved and sorted(ga) == sorted(gb),
       "reorderTo(n-1, -1) 应把最后一块移到最前（实际首位 %r，目标 %r）；"
       "长度 %d -> %d" % (ga[0] if ga else None, moved, len(gb), len(ga)))
    ck("reorder_negative_to_idx_dom_matches", _uids(at, "guard-dom-uids") == ga,
       "负 toIdx 重排后画布上渲染出来的 uid 顺序与数组不一致")


# 折叠 / 展开 / 拦截自动展开。
# 每个读数都是 "params/id/note/perr/expanded" 五段：前四段数的是这块积木的
# DOM 里到底有没有那几个输入框与拦截文案。数组字段对了但 DOM 没渲染的话，
# 只有这一串抓得住。
def _fields(at, key):
    v = at.get(key, "")
    return v.split("/") if v else []


FOLDED = ["0", "0", "0", "0", "0"]           # params/id/note/perr/expanded
OPENED = ["1", "1", "1", "0", "1"]           # 没写参数 -> 没有拦截文案


def fold_checks(p):
    at = report(p, "fold-report")
    ck("fold_hook_ran", bool(at.get("uid")) and bool(at.get("before")),
       "折叠钩子没跑起来：%s" % at)
    if not at.get("uid"):
        return
    ck("fold_default_collapsed", _fields(at, "before") == FOLDED,
       "新建的积木应当默认折叠（三个输入框都不在 DOM 里），实际 %r" % at.get("before"))
    ck("fold_expand_shows_fields", _fields(at, "opened") == OPENED,
       "点「展开」后参数 / 元素 ID / 备注三个输入框都该在，实际 %r" % at.get("opened"))
    ck("fold_manual_collapse", _fields(at, "recollapsed") == FOLDED,
       "再点一次「收起」应当真的折回去，实际 %r" % at.get("recollapsed"))
    ck("fold_block_auto_expands", _fields(at, "after-block") == ["1", "1", "1", "1", "1"],
       "塞进违规参数后应当自动展开并露出拦截文案（size 是 label 的 blocked 参数，"
       "所以 errors 应为 1），实际 %r" % at.get("after-block"))
    ck("fold_block_can_still_collapse", _fields(at, "after-collapse") == FOLDED,
       "自动展开之后用户必须还能手动收起来——实际 %r" % at.get("after-collapse"))
    # 「一有错就弹开」的照妖镜：label 这时仍然带着 1 条拦截，
    # 可整块画布上不该有任何一块处于展开态。
    ck("fold_block_not_stuck_open",
       at.get("error-count") == "1" and at.get("expanded-nodes") == "0",
       "label 仍有 %s 条拦截，画布上却还有 %s 块处于展开态"
       % (at.get("error-count"), at.get("expanded-nodes")))


def undo_checks(p, empty):
    """单步撤销：删除按钮紧挨复制、点错没有确认，误删要能救回来。"""
    at = report(p, "undo-report")
    before = _uids(at, "before-uids")
    gone, back = _uids(at, "after-del-uids"), _uids(at, "after-undo-uids")
    ck("undo_hook_ran",
       len(before) == EXPECT_WIDGETS + EXPECT_REJECTED and
       len(gone) == len(before) - 1 and len(back) == len(before),
       "撤销钩子没跑起来：before=%d after-del=%d after-undo=%d"
       % (len(before), len(gone), len(back)))
    if len(back) != len(before) or len(gone) != len(before) - 1:
        return
    victim = at.get("victim-uid", "")
    ck("undo_removes_then_restores", victim and victim not in gone and victim in back,
       "被删的积木 %r 没有原样回到数组里" % victim)
    ck("undo_restores_same_index", back == before,
       "撤销必须放回原位（前后 uid 序列应完全一致），实际 %s" % back)
    ck("undo_no_new_uid", sorted(back) == sorted(before),
       "撤销不该领新 uid——它是把原对象放回去，不是新建一块")
    ck("undo_dom_matches", _uids(at, "dom-uids") == back,
       "撤销后画布上渲染出来的 uid 顺序与数组不一致")
    ck("undo_button_enables_after_delete", at.get("enabled-after-del") == "true",
       "删过东西之后撤销按钮必须可点，实际 enabled=%s" % at.get("enabled-after-del"))
    ck("undo_button_disables_after_use", at.get("enabled-after-undo") == "false",
       "单步撤销用过一次就该失效（不做撤销栈），实际 enabled=%s"
       % at.get("enabled-after-undo"))
    # 没删过东西时按钮必须 disabled，否则点了会静默无事发生。
    m = re.search(r'<button[^>]*id="undo-del"[^>]*>', empty)
    ck("undo_button_present", m is not None, "画布上没有撤销按钮 #undo-del")
    if m:
        ck("undo_button_disabled_initially", "disabled" in m.group(0),
           "还没删过东西时撤销按钮应当是 disabled：%s" % m.group(0))


def js_body(src, header):
    """取 `header`（如 "function reorderTo"）之后按花括号配平的函数体。

    只用于静态负面检查（reorderTo 里不该出现 uid 改写）。
    不用它重演算法——重排语义由浏览器里真跑 reorderTo 的钩子判定。
    """
    i = src.find(header)
    if i < 0:
        return ""
    # 先把 /* */ 注释抹掉再切函数体。app.js 里到处是解释「为什么这么写」的
    # 长注释，其中不少直接写着被禁用的写法（比如 dupNode 那段里的
    # "copy.expanded = false"）。不抹的话，负面检查扫的是注释而不是代码——
    # 断言会因为一句解释而变红，人还得去猜是哪行代码写错了。
    body = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    i = body.find(header)
    j = body.find("{", i + len(header))
    if i < 0 or j < 0:
        return ""
    depth = 0
    for k in range(j, len(body)):
        if body[k] == "{":
            depth += 1
        elif body[k] == "}":
            depth -= 1
            if depth == 0:
                return body[j + 1:k]
    return ""


def canvas_of(p):
    """取 #canvas 切片。

    按钮的 title 里也抄了一遍 fallback 文案、数值文案，扫整份文档的话
    「画布上写了没有」这类断言就算什么都没写也会绿（变异验证实测过）。
    """
    if '<div id="canvas"' not in p or '<div id="prop-notes"' not in p:
        return ""
    return p.split('<div id="canvas"')[1].split('<div id="prop-notes"')[0]


def report(p, rid):
    """读无头钩子吐出来的 <div id="..."> 报告，读不到就返回空 dict（判定必红）。"""
    m = re.search(r'<div id="%s"([^>]*)>' % re.escape(rid), p)
    if not m:
        return {}
    return dict(re.findall(r'data-([a-z][a-z-]*)="([^"]*)"', m.group(1)))


def _uids(at, key):
    v = at.get(key, "")
    return v.split(",") if v else []


def del_on_stale_uid_is_noop(p):
    """块已经不在数组里了，再点它那个「过期」的删除按钮，必须什么都不做。

    钉的是 delNode 的负下标守卫：idxByUid 未命中返回 -1，
    而 proposal.splice(-1, 1) 在 JS 里是合法的、会静默删掉最后一块。
    审查员指出这是一条静默的数据丢失路径（今天点不出来，拖拽排序一行就能踩到），
    补守卫还不够——这条断言必须让没守卫的写法变红。
    """
    at = report(p, "del-report")
    if not at.get("after-first") or not at.get("after-stale"):
        return False
    return int(at["after-stale"]) == int(at["after-first"])


def del_last_node(p):
    """点最后一块的删除按钮 -> 块数减一。

    基线取 after-stale（= 第一次真删之后的块数），不取 before：
    before 是 DOM 节点数、before-uids 是数组长度，数组与 DOM 一旦失步，
    拿 before 当基线会把「渲染失败」误报成「删除失败」。这里两处读数
    都来自同一次 hook 内的数组快照，基线与被测值同源。
    """
    at = report(p, "del-report")
    if not at.get("after-stale") or not at.get("after-last"):
        return False
    return int(at["after-last"]) == int(at["after-stale"]) - 1


def del_last_node_then_check_uid(p):
    """删掉中间一块后，其余积木的身份必须原封不动。

    钉的是「uid 是身份不是位置」：剩下的 uid 序列必须正好等于
    原序列去掉被点的三块（第一块 + 最后一块 + 中间一块），顺序不变、
    数量只少三。若实现改用重排后的下标重新发 uid，或者复用被删的 uid，
    这里必红。
    """
    at = report(p, "del-report")
    before, after = _uids(at, "before-uids"), _uids(at, "after-uids")
    gone = (at.get("first-uid", ""), at.get("last-uid", ""), at.get("mid-uid", ""))
    if not before or not after or not all(gone):
        return False
    if len(after) != len(before) - 3:
        return False
    if any(u not in before for u in gone) or len(set(gone)) != 3:
        return False
    if len(set(after)) != len(after):
        return False                     # 出现重复 uid = 身份被复用
    return after == [u for u in before if u not in gone]


def del_dom_uids_match_array(p):
    """删除后「渲染出来的那几块」的 uid，必须与数组里的完全一致。

    beforeUids / afterUids 都是 hook 从 proposal 数组里读的，从来没碰过 DOM——
    一个「数组删对了、但存活积木渲染出的 uid 是错的或空的」的变异体照样全绿。
    这里把 DOM 上 .pnode[data-uid] 按文档顺序抓下来，与数组逐位比对：
    少一块、错一个 uid、顺序不同，三种都抓得住。
    """
    at = report(p, "del-report")
    after, dom = _uids(at, "after-uids"), _uids(at, "dom-uids")
    if not after or not dom:
        return False
    return dom == after


def dup_last_node(p):
    at = report(p, "dup-report")
    if not at.get("before") or not at.get("after"):
        return False
    return int(at["after"]) == int(at["before"]) + 1


def dup_gets_distinct_uid(p):
    """复制的副本必须拿到全新 uid，且原块一个都不能被改写。

    同时核对 DOM：副本必须真的以新 uid 渲染出来，而不只是数组里多了条记录。
    """
    at = report(p, "dup-report")
    before, after = _uids(at, "before-uids"), _uids(at, "after-uids")
    if not before or not after:
        return False
    if len(after) != len(before) + 1:
        return False
    if after[:-1] != before:
        return False                     # 原块被改写了（顺序或身份都变了）
    if after[-1] in before or len(set(after)) != len(after):
        return False                     # 副本沿用了原 uid
    if at.get("dom-count") != str(len(after)):
        return False
    return at.get("dom-last-uid") == after[-1]


def _fb_for(rkey):
    with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
        v = json.load(fh)
    for r in v["rejected"]:
        if r["key"] == rkey:
            return r["fallback"]
    return "<missing>"


def _fb_for_blocker(rkey):
    with open(os.path.join(WB, "vocabulary.json"), encoding="utf-8") as fh:
        v = json.load(fh)
    for r in v["rejected"]:
        if r["key"] == rkey:
            return r["blocker"]
    return "<missing>"


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:            # 汇总行不能被异常吞掉：rc=0 是假绿
        import traceback
        traceback.print_exc()
        ck("harness_no_exception", False, "测试自身抛异常：%r" % (exc,))
        print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
        sys.exit(1)