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
        set(w) == {"key", "label", "uiloayout", "allowed_props", "blocked_props", "note"}
        for w in vocab["widgets"]), "widget 字段集不对")
    ck("gen_props_disjoint", all(
        not (set(w["allowed_props"]) & set(w["blocked_props"])) for w in vocab["widgets"]),
        "同一控件的允许清单与拦截清单有交集")
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
        print("WARN 找不到 Edge/Chrome，跳过 DOM 检查（渲染未验证）")
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

        allp = dump(exe, url + "#proposal-all", profile)
        nodes = re.findall(r'<div class="note pnode[^"]*"[^>]*>', allp)
        ck("dom_all_count", len(nodes) == EXPECT_WIDGETS + EXPECT_REJECTED,
           "点击后应有 %d 个提案节点，实际 %d" % (EXPECT_WIDGETS + EXPECT_REJECTED, len(nodes)))
        # 12 个控件全部 status=ok / errors=0 —— 这是「词汇表内全部合法」的判定
        wnodes = re.findall(r'<div class="note pnode" data-wkey="([^"]*)" data-downgraded="0" '
                            r'data-status="([^"]*)" data-errors="([^"]*)"', allp)
        ck("dom_all_widgets_ok", len(wnodes) == EXPECT_WIDGETS and
           all(s == "ok" and e == "0" for _, s, e in wnodes),
           "词汇表内控件应全部合法，实际 %s" % [(k, s, e) for k, s, e in wnodes if s != "ok" or e != "0"])
        dnodes = re.findall(r'<div class="note pnode down" data-wkey="__downgraded__" '
                            r'data-downgraded="1" data-status="downgraded" data-errors="0" '
                            r'data-rkey="([^"]*)"', allp)
        ck("dom_all_downgraded", len(dnodes) == EXPECT_REJECTED and
           sorted(dnodes) == sorted(r["key"] for r in vjson["rejected"]),
           "%d 条降级方案应全部插入且标记为 downgraded，实际 %s"
           % (EXPECT_REJECTED, sorted(dnodes)))
        # 每条降级方案都要把「原需求做不到 + 降级方案」两行写进画布节点里。
        # 必须只扫 #canvas：按钮的 title 里也抄了一遍 fallback 文案，
        # 扫全文档的话这条断言就算画布上什么都没写也会绿（变异验证实测过）。
        canvas = allp.split('<div id="canvas"')[1].split('<div id="prop-notes"')[0] \
            if '<div id="canvas"' in allp and '<div id="prop-notes"' in allp else ""
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
        ck("dom_all_uilayout", allp.count("layout.") >= EXPECT_WIDGETS,
           "12 个控件的 UILayout 调用没都渲染出来")

        blk = dump(exe, url + "#proposal-blocked", profile)
        m = re.search(r'<div class="note pnode blocked" data-wkey="label" data-downgraded="0" '
                      r'data-status="blocked" data-errors="(\d+)"', blk)
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
        lab = blk.split('<div class="note pnode blocked" data-wkey="label"')[1].split("</textarea>")[0] \
            if '<div class="note pnode blocked" data-wkey="label"' in blk else ""
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
    finally:
        shutil.rmtree(profile, ignore_errors=True)


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


try:
    main()
except Exception as exc:            # 汇总行不能被异常吞掉：rc=0 是假绿
    import traceback
    traceback.print_exc()
    ck("harness_no_exception", False, "测试自身抛异常：%r" % (exc,))
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1)