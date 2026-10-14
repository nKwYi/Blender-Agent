# -*- coding: utf-8 -*-
"""ui_ids 埋点契约：ID 常量齐全、命名合规、mark() 双向安全、ui.py 调用点无笔误。

三条硬约束（见 task-3-brief.md 与 Global Constraints）：

1. 汇总行 `PASS <n>  FAIL <m>` 必须无条件打印。断言环节自身抛出的异常
   （缺 key、类型不对、AttributeError）只能记一条 FAIL，不能 traceback
   把汇总行吃掉——Blender 的 -P 脚本抛异常时退出码仍是 0，汇总行是唯一判据。
2. 断言不能空洞。每条断言的 cond 都必须来自真实求值，
   不允许写死 True（写了就永远不可能失败）。
3. --factory-startup 下扩展包名是 blender_deepseek_agent，不是
   bl_ext.user_default.*，按后者查 preferences.addons 会直接 KeyError。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FAILS = []
TOTAL = [0]

REQUIRED = [
    "CHAT_TABBAR", "CHAT_STATUSBAR", "CHAT_STREAM", "CHAT_COMPOSER",
    "CHAT_SEND", "CHAT_STOP", "CHAT_ACTION_ROW", "CHAT_OPTIONS",
    "CHAT_RESULT_TABS", "CHAT_HISTORY",
]

UI_PY = os.path.join(ROOT, "blender_deepseek_agent", "ui.py")


def emit(name, ok, msg=""):
    TOTAL[0] += 1
    if ok:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def attempt(name, fn):
    """执行 fn()，把异常降级成一条 FAIL。

    fn() 返回真值即通过。异常一律记 FAIL 后继续，绝不让 traceback
    吃掉末尾的汇总行。
    """
    try:
        ok = fn()
    except Exception as exc:
        emit(name, False, "抛异常 %s: %s" % (type(exc).__name__, exc))
        return False
    emit(name, True if ok else False, "" if ok else "断言为假")
    return bool(ok)


def ck(name, cond, msg=""):
    """布尔断言；cond 的求值本身若抛异常同样降级成 FAIL。"""
    def _run():
        return bool(cond)
    attempt(name, _run)


class Bare:
    """没有 tag() 的对象，用来验证 mark() 的空操作分支。"""


class Tagger:
    """有 tag() 的对象，用来验证 mark() 真的把 ID 写下去了。"""

    def __init__(self):
        self.seen = []

    def tag(self, element_id):
        self.seen.append(element_id)


def check_constants(ui_ids):
    for name in REQUIRED:
        ck("const_%s" % name, hasattr(ui_ids, name), "缺少常量 %s" % name)


def check_naming(ui_ids):
    for name in REQUIRED:
        if not hasattr(ui_ids, name):
            continue
        val = getattr(ui_ids, name)
        ck("prefix_%s" % name,
           isinstance(val, str) and val.startswith("chat."),
           "ID 必须以 chat. 开头：%r" % (val,))
        ck("charset_%s" % name,
           isinstance(val, str)
           and re.fullmatch(r"chat\.[a-z0-9_]+(\.[a-z0-9_]+)*", val) is not None,
           "ID 不符合命名规范：%r" % (val,))


def check_all_ids(ui_ids):
    """ALL_IDS 必须存在，且逐字覆盖 REQUIRED —— 下游 Task 4 按它枚举。"""
    def _run():
        all_ids = ui_ids.ALL_IDS
        if not isinstance(all_ids, (list, tuple)):
            return False
        vals = [getattr(ui_ids, n) for n in REQUIRED]
        return list(all_ids) == vals
    attempt("all_ids_covers_required", _run)

    ck("all_ids_unique", len(set(ui_ids.ALL_IDS)) == len(ui_ids.ALL_IDS),
       "ALL_IDS 里有重复 ID")


def check_mark_noop():
    """mark() 挂在没有 tag() 的对象上必须是空操作，而不是 AttributeError。"""
    bare = Bare()
    try:
        rv = ui_ids.mark(bare, "chat.probe")
    except Exception as exc:
        emit("mark_is_noop_without_tag", False,
             "无 tag() 时 mark 抛异常 %s: %s" % (type(exc).__name__, exc))
        return
    emit("mark_is_noop_without_tag", True)
    ck("mark_returns_none", rv is None, "mark 应返回 None，实际 %r" % (rv,))

    # 重复挂同一个块不应报错（draw 里一个容器可能被 mark 两次）
    b2 = Bare()
    try:
        ui_ids.mark(b2, "chat.composer")
        ui_ids.mark(b2, "chat.composer")
        ok = True
    except Exception as exc:
        ok = False
        emit("mark_idempotent", False,
             "重复 mark 抛异常 %s: %s" % (type(exc).__name__, exc))
    if ok:
        emit("mark_idempotent", True)


def check_mark_writes(ui_ids):
    """mark() 在有 tag() 的对象上必须把 ID 原样传下去。

    这是整套机制的正向主干：Task 4 的布局树里 element_id 全靠它。
    """
    t = Tagger()
    ui_ids.mark(t, ui_ids.CHAT_COMPOSER)
    ck("mark_writes_tag", t.seen == [ui_ids.CHAT_COMPOSER],
       "tag 未收到 ID：%r" % (t.seen,))

    # 不得改写 ID 内容，也不得多调/少调
    t2 = Tagger()
    ui_ids.mark(t2, "chat.send_btn")
    ck("mark_single_tag_call", len(t2.seen) == 1,
       "mark 应恰好调用一次 tag()，实际 %d 次" % len(t2.seen))
    ck("mark_passes_id_verbatim", t2.seen == ["chat.send_btn"],
       "ID 被改写：%r" % (t2.seen,))


def check_ui_py_call_sites(ui_ids):
    """ui.py 里每个 mark() 的第二参数都必须是 ui_ids 里真实存在的常量。

    这是防笔误的断言：埋点写错成 CHAT_SENDBTN 之类，编译能过、
    mark() 也能跑（它是 getattr 动态取名），只有这条断言能抓住。
    """
    with open(UI_PY, encoding="utf-8") as fh:
        src = fh.read()

    sites = re.findall(r"mark\(\s*[A-Za-z_][\w.]*\s*,\s*([A-Z][A-Z0-9_]*)\s*\)", src)
    ck("ui_py_has_mark_calls", len(sites) > 0, "ui.py 里一个 mark() 都没有")
    ck("ui_py_imports_mark",
       "from .ui_ids import" in src or "from blender_deepseek_agent.ui_ids import" in src,
       "ui.py 没有 import ui_ids")

    for name in sites:
        ck("site_id_known_%s" % name, hasattr(ui_ids, name),
           "ui.py 埋点用了不存在的常量 %s" % name)

    used = sorted(set(sites))
    unused = sorted(set(REQUIRED) - set(used))
    print("INFO ui.py 已埋点 %d 处: %s" % (len(sites), ", ".join(used)))
    if unused:
        print("INFO 未被 ui.py 引用的常量: %s" % ", ".join(unused))


def main():
    # 本模块刻意不 import bpy：ui_ids 是纯 Python，可独立自检。
    # 但 bda.register() 仍跑一遍，确认加了 ui_ids import 之后扩展仍能注册。
    def _register():
        import blender_deepseek_agent as bda
        bda.register()
        return True
    attempt("addon_register", _register)

    def _load():
        global ui_ids
        from blender_deepseek_agent import ui_ids as mod
        ui_ids = mod
        ck("mark_callable", callable(ui_ids.mark), "mark 必须可调用")
        return True
    if not attempt("import_ui_ids", _load):
        print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
        sys.exit(1)

    check_constants(ui_ids)
    check_naming(ui_ids)
    check_all_ids(ui_ids)
    check_mark_noop()
    check_mark_writes(ui_ids)
    check_ui_py_call_sites(ui_ids)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


try:
    main()
except SystemExit:
    raise
except Exception as exc:
    # 兜底：即使 main 整体炸了，也必须留下可判定的汇总行。
    emit("main_crashed", False, "%s: %s" % (type(exc).__name__, exc))
    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1)
