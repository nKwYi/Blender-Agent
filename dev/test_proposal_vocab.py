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
        ck("dom_empty_no_nodes", 'class="note pnode' not in empty,
           "没点任何控件就不该有提案节点")
        # 可做但没收录的能力必须在提案视图里显形（Important 3）
        ck("dom_unmapped_row", 'data-ukey="progress_bar"' in empty,
           "提案视图没有列出「可做但词汇表尚未收录」的能力")
        ck("dom_unmapped_note", "尚未收录" in empty,
           "缺少「尚未收录」的说明文案")
        ck("dom_props_scope", "精选子集" in empty,
           "没有说明 allowed_props 是精选子集，容易被当成全量 API")

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
    finally:
        shutil.rmtree(profile, ignore_errors=True)


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