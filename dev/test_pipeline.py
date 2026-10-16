# -*- coding: utf-8 -*-
"""ui_workbench 全链路自检：数据 -> 埋点 -> 词汇表 -> 标注 -> 导出，缺一环就红。

这个文件不做单元测试，只回答一个问题：**四份产物之间还接得上吗。**
每个测试文件单独看都是绿的，但链路可以悄悄断：

  - dev/capture_layout.py 重录了树，dev/build_data_js.py 没重跑 -> data.js 是旧的
  - ui_ids.py 加了新 ID，ui.py 忘了 mark() -> 树里根本查不到
  - constraints.json 判了一个 blocked，vocabulary.json 没收进 rejected
    -> 用户在提案画布里又把它画出来，Q2「死守原生 UILayout」当场破功
  - constraints 判了 native_ok 的能力，词汇表里没人认领 -> 15 条判定形同虚设
  - app.js 的标注键退回到只按 element_id 编号 -> 同 ID 的节点互相覆盖标注
    （options 有 3 个 chat.options；options 24 个节点里 16 个连 ID 都没有）

判定只看脚本自己打印的汇总行 `PASS n  FAIL m`，退出码只当第二道保险。

空洞断言防线：所有跨文件判定都写成纯函数（输入 -> bool），
末尾 MUTATION 段把输入改坏后要求同一个函数翻成 False——不翻就说明这条断言是空的。
尤其是 app.js 标注键那条，判定用的是**从 app.js 源码里解析出来的键公式**，
不是本文件里另抄一份，所以 app.js 改回旧写法会真的红。
"""
import copy
import json
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")

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


def jload(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------ 树遍历工具

def collect_ids(node, out=None):
    out = [] if out is None else out
    if node.get("element_id"):
        out.append(node["element_id"])
    for ch in node.get("children", []):
        collect_ids(ch, out)
    return out


def walk_paths(node, path, out):
    """复刻 app.js 的 DFS 下标路径：根 "0"，子节点 "0.2" 这样。"""
    out.append((node, path))
    for i, ch in enumerate(node.get("children", [])):
        walk_paths(ch, "%s.%d" % (path, i), out)
    return out


# ------------------------------------------------------------ 判定函数（纯函数）

def p_cons_entry_fields(cons):
    """blocked 的要有 blocker+fallback，可用的要有 evidence（拿什么证明能用）。"""
    for e in cons["entries"]:
        if not e.get("key") or not e.get("title") or not e.get("evidence"):
            return False
        if not e["native_ok"] and not (e.get("blocker") and e.get("fallback")):
            return False
    return True


def p_blocked_in_rejected(cons, vocab):
    """Q2/Q4：constraints 判 blocked 的，vocabulary 必须一条不落地进 rejected。"""
    blocked = {e["key"] for e in cons["entries"] if not e["native_ok"]}
    rejected = {r["key"] for r in vocab["rejected"]}
    return blocked <= rejected


def p_widget_fields(vocab):
    """控件必须带调用形式与 note，否则提案画布上无从解释「为什么这么画」。"""
    for w in vocab["widgets"]:
        if not w.get("key") or not w.get("uiloayout"):
            return False
        if "note" not in w:
            return False
        if "allowed_props" not in w or "blocked_props" not in w:
            return False
    return True


def p_widget_keys_unique(vocab):
    keys = [w["key"] for w in vocab["widgets"]]
    return len(keys) == len(set(keys))


def p_rejected_fields(vocab):
    """被拒的能力必须写清为什么拒、拿什么替代，否则等于没说。"""
    for r in vocab["rejected"]:
        if not r.get("key") or not r.get("blocker") or not r.get("fallback"):
            return False
    return True


def p_widget_constraint_links(cons, vocab):
    """widgets.constraint_key 指回 constraints 时不能指向不存在的条目。"""
    ckeys = {e["key"] for e in cons["entries"]}
    for w in vocab["widgets"]:
        ref = w.get("constraint_key")
        if ref is not None and ref not in ckeys:
            return False
    return True


def p_ok_constraints_claimed(cons, vocab):
    """constraints 判 native_ok 的能力必须被词汇表认领（widgets 或 unmapped_ok）。

    没有控件认领 = 这条可行性判定在空转：文档上「能做」，工作台里没人用。
    progress_bar 就是这种情况，它归 unmapped_ok 而不是 widgets。"""
    claimed = {w.get("constraint_key") for w in vocab["widgets"]}
    claimed |= {u.get("key") for u in vocab.get("unmapped_ok", [])}
    ok = {e["key"] for e in cons["entries"] if e["native_ok"]}
    return ok <= claimed


def p_tree_ids_registered(tree, registry):
    """Q5：树里出现的 element_id 必须都在 ui_ids.ALL_IDS 里注册过。

    没注册就意味着这个 ID 是 ui.py 里手敲的字面量，将来改名树和埋点会对不上。"""
    return set(collect_ids(tree)) <= registry


def p_dup_ids_exist(layouts):
    """真实数据里还有没有重复 element_id。规格段合并成单个盒之后没有了。

    留着是为了报告现状，不是为了守门 —— 键唯一由下面 path_in_akey 守。
    """
    for state, tree in layouts.items():
        ids = collect_ids(tree)
        if len(ids) != len(set(ids)):
            return True
    return False


def p_path_in_akey(js):
    """键公式里必须带 DFS path 那一段。

    这是标注不串台真正的护栏：两个节点哪怕 element_id 相同，只要路径不同，
    键就不同。规格段从「每个细节一个 chat.options」合并成「整段一个」之后，
    数据里不再有重复 ID，靠真实数据已经测不出任何东西 —— 真正要防的回归是
    **path 从公式里消失**，那时同 ID 的节点会立刻撞成一个标注槽。

    所以这里直接验公式里有 path，而不是等数据里出现重复。数据驱动的守门在
    数据变干净之后必然空转，公式驱动的守门不会。
    """
    tpl = js_akey_template(js)
    return bool(tpl) and "path" in tpl


def js_akey_template(js):
    """从 app.js 里取出 akey() 的键公式原文，而不是在本文件另抄一份。

    返回形如  cur + "|" + (eid || "?") + "@" + path  的字符串，取不到返回 None。
    """
    m = re.search(r"function\s+akey\s*\([^)]*\)\s*\{\s*return\s+(.*?);", js, re.S)
    return m.group(1).strip() if m else None


def _translate(tpl, state, eid, path):
    """把 akey 的键公式机械翻译成可 eval 的 Python 表达式。

    只做三处替换：cur -> 状态名，eid || "?" -> 无 ID 时的占位符，path -> DFS 路径。
    公式里出现任何别的标识符就会 NameError，判定按 False 处理（宁可红不可假绿）。
    """
    py = tpl.replace("cur", repr(state))
    py = py.replace("||", " or ")
    py = py.replace('(eid or "?")', json.dumps(eid or "?", ensure_ascii=False))
    py = re.sub(r"\bpath\b", repr(path), py)
    return py


def js_akey(tpl, state, eid, path):
    try:
        return eval(_translate(tpl, state, eid, path))  # noqa: S307 - 公式来自本仓 app.js
    except Exception:
        return None


def p_js_akeys_unique(js, layouts):
    """用 app.js 自己的键公式给每棵树的每个节点算键，全局必须唯一。

    app.js 若退回「只按 element_id 编号」，options 的 3 个 chat.options 会拿到
    同一个键，标注互相覆盖——本判定会红。这不是理论担忧，是上一次修复前的真实状态。
    """
    tpl = js_akey_template(js)
    if not tpl:
        return False
    keys = []
    for state, tree in layouts.items():
        for node, path in walk_paths(tree, "0", []):
            k = js_akey(tpl, state, node.get("element_id") or "", path)
            if k is None:
                return False
            keys.append(k)
    return len(keys) == len(set(keys))


def p_datajs_fresh(payload, cons, vocab, layouts):
    """data.js 必须和磁盘上的 JSON 一致，否则跑批器验的是上一轮的旧数据。"""
    if payload.get("constraints") != cons:
        return False
    if payload.get("vocabulary") != vocab:
        return False
    for name, tree in layouts.items():
        if payload.get("layout/" + name) != tree:
            return False
    return True


def p_datajs_cover_all(payload, states):
    if "constraints" not in payload or "vocabulary" not in payload:
        return False
    return all("layout/" + s in payload for s in states)


def p_index_wires_data(html):
    """file:// 下只能靠 <script src> 注入全局对象，且 data.js 必须排在 app.js 前面
    ——app.js 在顶层就执行 window.UW_DATA，顺序反了拿到 null。"""
    i_data = html.find('src="data/data.js"')
    i_app = html.find('src="app.js"')
    if i_data < 0 or i_app < 0:
        return False
    return i_data < i_app


def p_export_carries_annotations(js):
    """导出必须同时带走标注和提案，缺一个这轮验收的产出就丢了。"""
    m = re.search(r"var payload = \{(.*?)\};", js, re.S)
    if not m:
        return False
    body = m.group(1)
    return bool(re.search(r"annotations:\s*annotations\b", body)) and \
        bool(re.search(r"proposal:\s*proposal\b", body))


def p_shot_path_pattern(js):
    """截图是 app.js 按状态名拼路径的，磁盘上必须真有同名文件。"""
    return '"data/shots/" + name + ".png"' in js


def p_shot_ok(path):
    if not (os.path.exists(path) and os.path.getsize(path) > 1024):
        return False
    with open(path, "rb") as fh:
        return fh.read(8) == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------ 变异验证清单
# (名字, 判定函数名, 变异函数)。变异后判定必须翻成 False。

def _mut_rejected_drop(cons, vocab):
    return copy.deepcopy(cons), {**copy.deepcopy(vocab), "rejected": vocab["rejected"][1:]}


def _mut_widget_uiloayout_blank(cons, vocab):
    ws = copy.deepcopy(vocab["widgets"])
    ws[0]["uiloayout"] = ""
    return copy.deepcopy(cons), {**copy.deepcopy(vocab), "widgets": ws}


def _mut_widget_dupe(cons, vocab):
    ws = copy.deepcopy(vocab["widgets"]) + [copy.deepcopy(vocab["widgets"][0])]
    return copy.deepcopy(cons), {**copy.deepcopy(vocab), "widgets": ws}


def _mut_rejected_fallback_blank(cons, vocab):
    rs = copy.deepcopy(vocab["rejected"])
    rs[0]["fallback"] = ""
    return copy.deepcopy(cons), {**copy.deepcopy(vocab), "rejected": rs}


def _mut_dangling_link(cons, vocab):
    ws = copy.deepcopy(vocab["widgets"])
    ws[0]["constraint_key"] = "no_such_key"
    return copy.deepcopy(cons), {**copy.deepcopy(vocab), "widgets": ws}


def _mut_unclaimed_ok(cons, vocab):
    """把 progress_bar 从 unmapped_ok 里删掉，又不让任何 widget 认领它。"""
    v = copy.deepcopy(vocab)
    v["unmapped_ok"] = [u for u in v.get("unmapped_ok", []) if u.get("key") != "progress_bar"]
    return copy.deepcopy(cons), v


def _mut_cons_evidence_blank(cons, vocab):
    c = copy.deepcopy(cons)
    c["entries"][0]["evidence"] = ""
    return c, copy.deepcopy(vocab)


def _mut_new_blocked_unlisted(cons, vocab):
    """constraints 里新增一条 blocked 判定，但 vocabulary 的 rejected 没跟上。"""
    c = copy.deepcopy(cons)
    c["entries"].append({
        "key": "made_up_capability", "title": "凭空多出来的判定",
        "native_ok": False, "evidence": "x",
        "blocker": "y", "fallback": "z",
    })
    return c, copy.deepcopy(vocab)


# ------------------------------------------------------------ 主流程

def parse_state_names():
    """不能 import dev.states（它 import bpy），只能从源码里取 STATE_NAMES 字面量。"""
    src = read(os.path.join(HERE, "states.py"))
    m = re.search(r"STATE_NAMES\s*=\s*\[([^\]]*)\]", src)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def load_datajs():
    raw = read(os.path.join(WB, "data", "data.js"))
    return json.loads(raw[raw.index("{"):].rstrip().rstrip(";"))


def main():
    cons_p = os.path.join(WB, "constraints.json")
    vocab_p = os.path.join(WB, "vocabulary.json")
    html_p = os.path.join(WB, "index.html")
    app_p = os.path.join(WB, "app.js")

    for label, p in (("constraints.json", cons_p), ("vocabulary.json", vocab_p),
                     ("index.html", html_p), ("app.js", app_p)):
        ck("file_%s" % label, os.path.exists(p), "缺 %s" % p)
    if FAILS:
        return 1

    states = parse_state_names()
    ck("states_parsed", len(states) == 7,
       "STATE_NAMES 解析出 %d 个：%r" % (len(states), states))
    if len(states) != 7:
        return 1

    # 直接按文件加载 ui_ids：走包 import 会触发 blender_deepseek_agent.__init__
    # 里的 `import bpy`，而本测试是无头跑的纯 Python，Blender 里才有 bpy。
    import importlib.util
    ids_path = os.path.join(ROOT, "blender_deepseek_agent", "ui_ids.py")
    spec = importlib.util.spec_from_file_location("_uw_ui_ids", ids_path)
    ui_ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui_ids)
    registry = set(ui_ids.ALL_IDS)
    ck("ids_registry_nonempty", len(registry) >= 5, "ui_ids.ALL_IDS 只有 %d 个" % len(registry))

    cons = jload(cons_p)
    vocab = jload(vocab_p)
    html = read(html_p)
    js = read(app_p)

    # ---- 一、约束注册表 -> 词汇表
    ck("cons_entry_fields", p_cons_entry_fields(cons),
       "有条目缺 key/title/evidence，或 blocked 的缺 blocker/fallback")
    ck("blocked_in_rejected", p_blocked_in_rejected(cons, vocab),
       "blocked 未被 rejected 收编：%s" % (
           {e["key"] for e in cons["entries"] if not e["native_ok"]}
           - {r["key"] for r in vocab["rejected"]},))
    ck("widget_fields", p_widget_fields(vocab), "有控件缺 uiloayout/note/allowed_props")
    ck("widget_keys_unique", p_widget_keys_unique(vocab), "widgets 有重复 key")
    ck("rejected_fields", p_rejected_fields(vocab), "有 rejected 缺 blocker/fallback")
    ck("widget_constraint_links", p_widget_constraint_links(cons, vocab),
       "widgets.constraint_key 指向了不存在的约束条目")
    ck("ok_constraints_claimed", p_ok_constraints_claimed(cons, vocab),
       "native_ok 的能力没人认领：%s" % (
           {e["key"] for e in cons["entries"] if e["native_ok"]}
           - ({w.get("constraint_key") for w in vocab["widgets"]}
              | {u.get("key") for u in vocab.get("unmapped_ok", [])}),))

    # ---- 二、埋点 -> 布局树
    layouts = {}
    for s in states:
        p = os.path.join(WB, "data", "layout", "%s.json" % s)
        if not os.path.exists(p):
            ck("layout_present_%s" % s, False, "缺 %s" % p)
            continue
        ck("layout_present_%s" % s, True)
        layouts[s] = jload(p)

    for s in states:
        if s not in layouts:
            continue
        tree = layouts[s]
        ids = collect_ids(tree)
        ck("layout_state_field_%s" % s, tree.get("state") == s, "state 字段=%r" % tree.get("state"))
        ck("layout_ids_ge5_%s" % s, len(ids) >= 5, "只有 %d 个带 ID 节点" % len(ids))
        ck("layout_ids_registered_%s" % s, p_tree_ids_registered(tree, registry),
           "未注册的 ID：%s" % sorted(set(ids) - registry))

    ck("dup_ids_absent", not p_dup_ids_exist(layouts),
       "有状态出现了重复 element_id：%s"
       % [s for s, t in layouts.items()
          if len(collect_ids(t)) != len(set(collect_ids(t)))])
    ck("path_in_akey", p_path_in_akey(js),
       "app.js 的 akey 公式里必须有 DFS path 那一段——同 ID 的节点靠路径"
       "才不会撞成一个标注槽。公式=%r" % js_akey_template(js))
    ck("js_akeys_unique", p_js_akeys_unique(js, layouts),
       "按 app.js 的键公式算出的标注键有重复，标注会串台（键公式=%r）"
       % js_akey_template(js))

    # ---- 三、实机截图
    for s in states:
        p = os.path.join(WB, "data", "shots", "%s.png" % s)
        ck("shot_ok_%s" % s, p_shot_ok(p), "缺失、过小或不是 PNG：%s" % p)
    ck("shot_path_pattern", p_shot_path_pattern(js),
       "app.js 不再按 data/shots/<state>.png 取图")

    # ---- 四、打包器 -> data.js
    try:
        payload = load_datajs()
        ck("datajs_parses", True)
    except Exception as exc:
        ck("datajs_parses", False, "解析失败 %s: %s" % (type(exc).__name__, exc))
        payload = {}
    ck("datajs_covers_states", p_datajs_cover_all(payload, states),
       "data.js 缺状态或缺 constraints/vocabulary：%s" % sorted(payload))
    ck("datajs_fresh", p_datajs_fresh(payload, cons, vocab, layouts),
       "data.js 与磁盘 JSON 不一致（重跑 dev/build_data_js.py）")

    # ---- 五、导出链路
    ck("index_wires_data", p_index_wires_data(html),
       "index.html 没按 data.js -> app.js 的顺序引入")
    ck("export_carries_annotations", p_export_carries_annotations(js),
       "导出 payload 里没有同时带 annotations 和 proposal")

    # ---- 六、变异验证（空洞断言防线）
    muts = [
        ("cons_evidence_blank", lambda c, v: p_cons_entry_fields(c), _mut_cons_evidence_blank),
        ("new_blocked_unlisted", p_blocked_in_rejected, _mut_new_blocked_unlisted),
        ("rejected_dropped", p_blocked_in_rejected, _mut_rejected_drop),
        ("widget_uiloayout_blank", lambda c, v: p_widget_fields(v),
         _mut_widget_uiloayout_blank),
        ("widget_dupe", lambda c, v: p_widget_keys_unique(v), _mut_widget_dupe),
        ("rejected_fallback_blank", lambda c, v: p_rejected_fields(v),
         _mut_rejected_fallback_blank),
        ("dangling_constraint_link", p_widget_constraint_links, _mut_dangling_link),
        ("unclaimed_ok_constraint", p_ok_constraints_claimed, _mut_unclaimed_ok),
    ]
    for name, fn, mut in muts:
        c, v = mut(cons, vocab)
        ck("mutation_%s" % name, not fn(c, v),
           "改坏输入后判定仍为 True——这条断言是空洞的")

    # 树侧变异
    if layouts:
        any_state, any_tree = sorted(layouts.items())[0]
        fake = copy.deepcopy(any_tree)
        if fake.get("children"):
            fake["children"][0]["element_id"] = "chat.not_registered"
            ck("mutation_unregistered_id", not p_tree_ids_registered(fake, registry),
               "树里塞了未注册 ID，判定没红")
        else:
            ck("mutation_unregistered_id", False, "树没有子节点，无法做此变异")

        # app.js 的键公式退回「只按 element_id 编号」——上一次修复前的真实写法
        stale_js = re.sub(r"(function\s+akey\s*\([^)]*\)\s*\{\s*return\s+).*?;",
                          r'\1cur + "|" + (eid || "?");', js, count=1)
        ck("mutation_akey_without_path",
           (stale_js != js) and not p_js_akeys_unique(stale_js, layouts),
           "把 app.js 键公式改回不含 DFS 路径的旧写法后判定仍为 True")

    # data.js 侧变异
    bad_payload = copy.deepcopy(payload)
    bad_payload.pop("constraints", None)
    ck("mutation_datajs_stale", not p_datajs_fresh(bad_payload, cons, vocab, layouts),
       "从 payload 里删掉 constraints 后仍判定为新鲜")
    ck("mutation_datajs_coverage", not p_datajs_cover_all(bad_payload, states),
       "payload 缺状态时覆盖判定没红")

    # 导出侧变异
    bad_html = html.replace('<script src="app.js"></script>',
                            '<script src="data/data.js"></script>')
    ck("mutation_index_order", not p_index_wires_data(bad_html),
       "把 app.js 排到 data.js 前面后判定没红")
    bad_js = re.sub(r"^\s*proposal:\s*proposal\s*,?\s*$", "", js, flags=re.M)
    ck("mutation_export_payload", not p_export_carries_annotations(bad_js),
       "从导出 payload 里删掉 proposal 后判定没红")

    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:  # 汇总行绝不能被异常吃掉
        TOTAL[0] += 1
        FAILS.append("harness")
        print("FAIL harness: 主流程抛异常 %s: %s\n%s"
              % (type(exc).__name__, exc, traceback.format_exc()))
        rc = 1
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(rc)