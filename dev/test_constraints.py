# -*- coding: utf-8 -*-
"""约束注册表自检：每条能力都必须有判据、阻断原因与降级方案。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS = []
TOTAL = [0]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def main():
    path = os.path.join(ROOT, "ui_workbench", "constraints.json")
    ck("constraints_exists", os.path.exists(path), "缺少 constraints.json，先跑 build_constraints.py")
    if not os.path.exists(path):
        print("PASS 0  FAIL %d" % len(FAILS))
        sys.exit(1)

    with open(path, encoding="utf-8") as fh:
        reg = json.load(fh)
    entries = reg.get("entries", [])

    ck("has_entries", len(entries) >= 10, "条目太少：%d" % len(entries))
    for e in entries:
        key = e.get("key", "?")
        ck("key_present_%s" % key, bool(e.get("key")), "缺 key")
        ck("title_present_%s" % key, bool(e.get("title")), "缺 title")
        ck("verdict_bool_%s" % key, isinstance(e.get("native_ok"), bool),
           "native_ok 必须是布尔")
        ck("evidence_%s" % key, bool(e.get("evidence")), "缺 evidence，无法追溯")
        if e.get("native_ok") is False:
            ck("blocker_%s" % key, bool(e.get("blocker")), "blocked 项必须有 blocker")
            ck("fallback_%s" % key, bool(e.get("fallback")), "blocked 项必须有 fallback")

    # 不能裸取 e["key"]：缺 key 的条目必须已经被记录过，而不是在这里抛
    # KeyError 吞掉末尾的汇总行。重复 key 会静默折叠，必须显式断言。
    keys = [e.get("key", "") for e in entries]
    dup = sorted({k for k in keys if k and keys.count(k) > 1})
    ck("unique_keys", not dup, "重复 key: %s" % " ".join(dup))
    by_key = {e["key"]: e for e in entries if e.get("key")}

    # 2026-10-14 实测的三条禁止项，必须全部判定为 blocked
    for key in ("hover", "custom_rgb", "font_size"):
        ck("blocked_%s" % key,
           key in by_key and by_key[key]["native_ok"] is False,
           "%s 必须判定为 native_ok=false" % key)

    # 真实滚动是本项目最致命的一条，ceiling doc 明确写过
    ck("blocked_real_scroll",
       "real_scroll" in by_key and by_key["real_scroll"]["native_ok"] is False,
       "侧栏滚轮实测不滚动，必须 blocked")

    # 争议判定锁定：5.2.1 的 116 个 UILayout 函数中已无 context_menu（5.2 移除，
    # 改由 menu_pie / popover 承担）。若有人把 call 改成 menu_pie 放行，此处必须变红。
    ck("blocked_context_menu",
       "context_menu" in by_key and by_key["context_menu"]["native_ok"] is False,
       "context_menu 实测不存在，必须保持 blocked")

    # 原生可用项必须给出具体 API
    for key in ("collapsible_panel", "property_split", "flat_button", "grid_flow"):
        ck("allowed_%s" % key,
           key in by_key and by_key[key]["native_ok"] is True and
           "uiloayout" in by_key[key],
           "%s 应为 allowed 且必须给出 uiloayout 调用" % key)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
