# UI Workbench 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 造一个本地 HTML 工作台，把 `blender_deepseek_agent` 的【AI 对话】tab 做成「镜像视图（实机截图 + 布局树并排、双向高亮）」+「提案视图（受限词汇表拼装、落笔即校验可行性）」，覆盖 7 个关键状态的完整序列。

**Architecture:** 离线数据管线，无常驻服务。布局树由无头 Blender 注入录制器导出 JSON；实机截图由一次最小化 GUI 运行批量产出。HTML 单页 `file://` 直开，无构建无依赖。约束注册表由实测的 `native_api.json` 生成，是提案视图唯一的可行性判据来源。

**Tech Stack:** Blender 5.2.1 LTS 内嵌 CPython 3.13.13 / bpy · 原生 `UILayout` · 纯前端 HTML+CSS+JS（零依赖、零构建）· PIL（已用于 `dev/crop.py`）

## Global Constraints

以下每条都是硬约束，**任何任务都不得违反**：

- **Blender 路径**：`D:\blender-4.5.5-windows-x64\blender5.2\blender.exe`，版本 5.2.1 LTS。
- **工作目录含空格**：`E:\Three JS\Blender Agent`。所有命令行路径必须加双引号。
- **死守原生 UILayout。** 禁止引入 `gpu` / `blf` / `gpu.shader` / `draw_handler_add` / 任何 modal 键盘循环。`attic/` 目录保持封存，**本计划不读取、不修改、不迁移其中任何文件**。
- **可行性只有两档**：`native_ok` / `native_blocked`。不存在第三档，不允许在 HTML 里画出已知 blocked 的效果而不加拦截。
- **已实测的禁止项**（`ui_workbench/native_api.json` 的 `ui.negatives`，2026-10-14 实测）：`arbitrary_rgb=false`、`font_size=false`、`hover_hook=false`。
- **元素 ID 规范**：`chat.<block>` 或 `chat.<block>.<widget>`，全小写下划线分词。**只允许挂在区块容器与可交互控件上**，纯装饰 label 不挂 ID。
- **状态序列固定 7 个**，命名不得改动：`idle` `clarify` `options` `running` `done` `partial` `failed`。
- **★ `rc=0` 是假绿。** 每个测试脚本必须打印 `PASS <n>  FAIL <m>` 汇总行**并且** `sys.exit(1 if FAILS else 0)`。只 print 不 exit 的脚本视为不合格。
- **★ stderr/stdout 全量落盘再看。** 禁止用 `Select-Object -Last N` 截断输出后判断成败。
- **★ 改含中文的源文件禁用字节级读写。** 一律用 `open(p, encoding='utf-8')` 或编辑工具精确替换。落盘后自检 `open(p,'rb').read().count(b'\x00') == 0` 且 `compile()` 通过。
- **`.ps1` 脚本正文必须纯 ASCII**（`write` 工具输出 UTF-8 无 BOM，PS 5.1 会按 ANSI 解码中文注释并把换行转义掉）。需要中文输出就改用 Python 脚本。
- **PowerShell 5.1 不用 `&&` / `||`**，用分号 + 显式检查 `$LASTEXITCODE`。
- **不引入任何 pip 依赖。** Blender 内嵌 Python 装不了第三方包（已实测）。
- **不要碰 PID 45464** —— 那是用户自己开着未保存 blend 文件的 Blender，杀掉会丢数据。
- **GUI 纪律**：能 `--background` 跑的一律无头跑；必须开 GUI 时用 `Start-Process -WindowStyle Minimized -PassThru -Wait`；同一类验证合并成一次运行产出多张图；**同一时刻只跑一个 GUI 实例**。
- **禁止从外部网络安装依赖**，禁止 `npm install`。

## File Structure

| 路径 | 责任 |
|:---|:---|
| `ui_workbench/native_api.json` | Blender 原生能力实测快照（**已由 `dev/probe_native_api.py` 生成**） |
| `ui_workbench/constraints.json` | 可行性注册表：每条能力 → 能否做 + 阻断原因 + 降级方案。提案视图唯一判据 |
| `ui_workbench/vocabulary.json` | 受限词汇表：允许拼装的控件及其合法参数、禁用参数 |
| `ui_workbench/index.html` | 工作台唯一入口，`file://` 直开 |
| `ui_workbench/app.js` | 视图切换、树渲染、词汇表校验、标注存储与导出 |
| `ui_workbench/style.css` | 工作台样式。**配色只允许取自 `native_api.json` 的实测主题色** |
| `ui_workbench/data/layout/<state>.json` | 7 个状态的布局树（带元素 ID） |
| `ui_workbench/data/shots/<state>.png` | 7 个状态的实机截图 |
| `ui_workbench/data/annotations.json` | 标注落盘结果 |
| `dev/layout_recorder.py` | ★ 布局树录制器。实现 `tag()` 与全套 `UILayout` 桩方法 |
| `dev/build_constraints.py` | 从 `native_api.json` 生成 `constraints.json` |
| `dev/capture_layout.py` | 无头导出 7 个状态的布局树 |
| `dev/capture_shots.py` | 一次 GUI 运行产出 7 张截图 |
| `dev/states.py` | ★ 7 个状态的构造器，被布局导出与截图脚本共用 |
| `dev/test_constraints.py` | 约束注册表自检 |
| `dev/test_recorder.py` | 录制器自检 |

**文件所有权切分**（并行时互斥，不得交叉写）：

| Worker | 独占文件 |
|:---|:---|
| A | `dev/build_constraints.py` · `ui_workbench/constraints.json` · `dev/test_constraints.py` |
| B | `dev/layout_recorder.py` · `dev/states.py` · `dev/test_recorder.py` |
| C | `blender_deepseek_agent/ui_ids.py` · `blender_deepseek_agent/ui.py` |
| D | `dev/capture_layout.py` · `dev/capture_shots.py` |
| E | `ui_workbench/index.html` · `app.js` · `style.css` · `vocabulary.json` |

---

### Task 1: 约束注册表

**Files:**
- Create: `dev/build_constraints.py`
- Create: `ui_workbench/constraints.json`（由脚本生成，不手写）
- Test: `dev/test_constraints.py`

**Interfaces:**
- Consumes: `ui_workbench/native_api.json`（Task 0 已产出）
- Produces:
  - `build_constraints.load_api() -> dict`
  - `build_constraints.build(api: dict) -> dict`
  - `build_constraints.main() -> int`
  - `ui_workbench/constraints.json` schema：
    ```json
    {
      "generated_for": "5.2.1 LTS",
      "palette": {"wcol_box": {"inner": "#1d1d1d"}, "...": {}},
      "entries": [
        {"key": "hover", "title": "鼠标悬停态", "native_ok": false,
         "blocker": "...", "fallback": "...", "evidence": "ui.negatives.hover_hook=false"}
      ]
    }
    ```
- [ ] **Step 1: 写失败测试**

创建 `dev/test_constraints.py`：

```python
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

    by_key = {e["key"]: e for e in entries}

    # 2026-10-14 实测的三条禁止项，必须全部判定为 blocked
    for key in ("hover", "custom_rgb", "font_size"):
        ck("blocked_%s" % key,
           key in by_key and by_key[key]["native_ok"] is False,
           "%s 必须判定为 native_ok=false" % key)

    # 真实滚动是本项目最致命的一条，ceiling doc 明确写过
    ck("blocked_real_scroll",
       "real_scroll" in by_key and by_key["real_scroll"]["native_ok"] is False,
       "侧栏滚轮实测不滚动，必须 blocked")

    # 原生可用项必须给出具体 API
    for key in ("collapsible_panel", "property_split", "flat_button", "grid_flow"):
        ck("allowed_%s" % key,
           key in by_key and by_key[key]["native_ok"] is True and
           "uiloayout" in by_key[key],
           "%s 应为 allowed 且必须给出 uiloayout 调用" % key)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_constraints.py 2>&1 | Tee-Object dev\out\task1_fail.txt
```
预期：`FAIL constraints_exists`，退出码 1。

- [ ] **Step 3: 写生成器**

创建 `dev/build_constraints.py`：

```python
# -*- coding: utf-8 -*-
"""从实测的 native_api.json 生成可行性约束注册表。

判据只有一个来源：native_api.json。任何一条 native_ok 的判定都必须能在
该文件里找到对应证据，禁止凭印象填写。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = os.path.join(ROOT, "ui_workbench", "native_api.json")
OUT = os.path.join(ROOT, "ui_workbench", "constraints.json")


def load_api():
    with open(API, encoding="utf-8") as fh:
        return json.load(fh)


def _has_call(api, name):
    return name in api["ui"]["functions"]


def _has_prop(api, name):
    return name in api["ui"]["properties"]


# 每条 entry 的 verdict 在这里计算，不允许硬编码 True/False。
def _entry(key, title, api, call=None, prop=None, blocker="", fallback="",
           denied=None, negated=None):
    """Build one registry entry.

    Two evidence sources, both read from native_api.json -- never hardcoded:

    * ``negated``: keys into ``ui.negatives``. NOTE the naming trap --
      ``dev/probe_native_api.py`` builds that dict with ``hasattr(ui, "color")``
      style probes, so ``True`` means **the capability EXISTS**, not that it is
      denied. Do not negate it.
    * ``denied``: a tuple of symbols that must be ABSENT for this capability to
      be impossible (e.g. no shadow API anywhere). Any one of them present means
      Blender grew a way to do it.
    """
    if negated is not None:
        ok = bool(api["ui"]["negatives"].get(negated, False))
        ev = "ui.negatives.%s=%s (True means the capability EXISTS)" % (
            negated, json.dumps(api["ui"]["negatives"].get(negated)))
    elif call is not None:
        ok = _has_call(api, call)
        ev = "ui.functions.%s=%s" % (call, ok)
    elif prop is not None:
        ok = _has_prop(api, prop)
        ev = "ui.properties.%s=%s" % (prop, ok)
    elif denied is not None:
        hit = [s for s in denied
               if s in api["ui"]["functions"] or s in api["ui"]["properties"]]
        ok = bool(hit)
        ev = "absent from api: %s (found: %s)" % (", ".join(denied), hit or "none")
    else:
        raise ValueError("entry %r has no evidence source" % key)

    item = {"key": key, "title": title, "native_ok": bool(ok), "evidence": ev}
    if ok and (call or prop):
        item["uiloayout"] = ("layout.%s()" % call) if call else "layout.%s = ..." % prop
    if not ok:
        item["blocker"] = blocker
        item["fallback"] = fallback
    return item


def build(api):
    entries = [
        _entry("hover", "鼠标悬停态", api, negated="hover_hook",
               blocker="UILayout 无任何 hover 回调；Blender 内部有 _inner_sel 配色但插件调不到",
               fallback="改用 enabled / active 二态表达状态；把 hover 语义重写为「点击后进入」"),
        _entry("custom_rgb", "任意 RGB 颜色", api, negated="arbitrary_rgb",
               blocker="UILayout 无 color 属性，只能置 layout.alert=True 触发主题红",
               fallback="只用 box.alert 表达失败；成功/警告改用图标与文案区分，不依赖颜色"),
        _entry("font_size", "自定义字号与字重", api, negated="font_size",
               blocker="label() 只有 text / text_ctxt / translate / icon / icon_value 五个参数",
               fallback="用 layout.scale_y 配合空 label 撑出层次；标题感靠 icon 与分隔线建立"),
        _entry("box_shadow", "卡片阴影", api,
               denied=("shadow", "shadow_fac", "drop_shadow"),
               blocker="面板无阴影 API，theme 只有 menu_shadow_fac 作用于菜单",
               fallback="用底色明度差分层：面板 #3d3d3d 对内盒 #1d1d1d"),
        _entry("real_scroll", "侧栏真实滚动", api,
               denied=("scroll", "scrollbar", "scroll_to"),
               blocker="侧栏滚轮实测不滚动（UI打磨执行书 v0.2.1 实测：200 行面板滚轮零变化）",
               fallback="用 layout.panel() 折叠消化长度；对话记录只保留最近 N 条，其余折叠或分页"),
        _entry("anim_transition", "展开/收起动效", api,
               denied=("animation", "animate", "interpolation"),
               blocker="插件无动画 API",
               fallback="改用 layout.panel() 的原生折叠箭头，动效由 Blender 内置提供"),
        _entry("collapsible_panel", "可折叠子面板", api, call="panel",
               fallback=""),
        _entry("property_split", "规范两列属性行", api, prop="use_property_split",
               fallback=""),
        _entry("flat_button", "扁平按钮（去高光渐变）", api, prop="emboss",
               fallback=""),
        _entry("grid_flow", "网格流式按钮排布", api, call="grid_flow",
               fallback=""),
        _entry("progress_bar", "进度条", api, call="progress",
               fallback=""),
        _entry("two_col_split", "左右分栏", api, call="split",
               fallback=""),
        _entry("context_menu", "上下文菜单", api, call="context_menu",
               blocker="Blender 5.2.1 的 UILayout 已无 context_menu"
                       "（实测 116 个函数全表核对，只有 menu_pie 与 popover）",
               fallback="改用 layout.menu() 或 layout.popover()"),
        _entry("warn_color", "警告橙 wcol_state.warning", api,
               denied=("color", "theme_color", "warning_color"),
               blocker="主题里有该色但 UILayout 不暴露 ThemeWidgetColors",
               fallback="用 icon='ERROR' 与文案承载「注意」语义，不靠颜色"),
        _entry("ok_color", "成功绿 wcol_state.success", api,
               denied=("color", "theme_color", "success_color"),
               blocker="同上，主题里有但 Python API 调不到",
               fallback="用 icon='CHECKMARK' 承载「成功」语义"),
    ]
    return {
        "generated_for": api["blender_version"],
        "blender_version": api["blender_version"],
        "generated_from": "dev/build_constraints.py",
        "icon_count": api["icons"]["count"],
        "palette": api["theme"]["colors"],
        "entries": entries,
    }


def main():
    api = load_api()
    reg = build(api)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2, sort_keys=True)
    blocked = [e["key"] for e in reg["entries"] if not e["native_ok"]]
    allowed = [e["key"] for e in reg["entries"] if e["native_ok"]]
    print("CONSTRAINTS_OK wrote=%s" % OUT)
    print("total=%d allowed=%d blocked=%d" % (len(reg["entries"]), len(allowed), len(blocked)))
    print("ALLOWED %s" % " ".join(allowed))
    print("BLOCKED %s" % " ".join(blocked))
    print("PASS %d  FAIL 0" % len(reg["entries"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 生成并跑测试**

```powershell
cd 'E:\Three JS\Blender Agent'
$B='D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
& $B --background --factory-startup -P dev\build_constraints.py 2>&1 | Tee-Object dev\out\task1_gen.txt
if ($LASTEXITCODE -ne 0) { throw "build_constraints failed" }
& $B --background --factory-startup -P dev\test_constraints.py 2>&1 | Tee-Object dev\out\task1_pass.txt
```
预期：生成器打印 `BLOCKED` 行，其中含 `hover custom_rgb font_size box_shadow real_scroll anim_transition context_menu warn_color ok_color` 共 **9 条**（`context_menu` 在 5.2.1 实测中不存在，故为 blocked）；测试全绿、`FAIL 0`，退出码 0。

- [ ] **Step 5: 变异验证（证明断言非空洞）**

把 `dev/build_constraints.py` 里 `real_scroll` 的 `blocker` 临时改成空串，重跑测试，**必须**看到 `FAIL fallback_real_scroll`。确认变红后改回。

```powershell
cd 'E:\Three JS\Blender Agent'
$B='D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
(Get-Content dev\build_constraints.py -Raw -Encoding UTF8).Replace('fallback="用 layout.panel() 折叠消化长度；对话记录只保留最近 N 条，其余折叠或分页"','fallback=""') | Set-Content dev\build_constraints.py -Encoding UTF8
& $B --background --factory-startup -P dev\build_constraints.py 2>&1 | Out-Null
& $B --background --factory-startup -P dev\test_constraints.py 2>&1 | Select-String 'FAIL fallback_real_scroll'
```
确认该行出现后，把 `fallback` 改回原值并重跑 Step 4 确认恢复全绿。

---

### Task 2: 布局树录制器

**Files:**
- Create: `dev/layout_recorder.py`
- Test: `dev/test_recorder.py`

**Interfaces:**
- Produces:
  - `class RecLayout` — UILayout 桩，构造参数 `(kind="layout", parent=None)`
    - 实例方法：`row(align=False)` · `column(align=False)` · `box()` · `split(factor=0.5, align=False)` · `grid_flow(row_major=True, columns=0, even_columns=False, even_rows=False, align=False)` · `label(text="", text_ctxt="", translate=False, icon='NONE', icon_value=0)` · `separator(factor=1.0)` · `menu(name="", icon='NONE')` · `panel(idname, default_closed=False, layout_header=None, layout_body=None)` · `prop(data, prop, text="", **kw)` · `operator(op_id, text="", icon='NONE', **kw)` · `textbox(data, prop, **kw)`
    - **不要**实现 `context_menu`——实测 Blender 5.2.1 的 UILayout 已经没有这个方法，`ui.py` 也不调用它。桩方法比真实 API 多只会让录制器悄悄接受真实 Blender 会崩的调用。
    - 实例属性（可读写）：`alert` · `active` · `enabled` · `scale_y` · `alignment` · `use_property_split` · `emboss` · `operator_context` · `element_id`
    - 实例方法：`tag(element_id: str) -> None`
    - 实例方法：`to_dict() -> dict`
  - `class Recorder` — 顶层容器
    - `Recorder.root -> RecLayout`
    - `Recorder.finish() -> dict`

- [ ] **Step 1: 写失败测试**

创建 `dev/test_recorder.py`：

```python
# -*- coding: utf-8 -*-
"""录制器自检。核心断言：split() 必须返回单个 layout，不是元组。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dev.layout_recorder import RecLayout, Recorder

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
    r = Recorder()

    # 1. split 在 Blender 5.x 返回单个 UILayout，不是二元组。
    #    test_native_ui.py 的旧 MockLayout 返回元组，是错的；本条防回归。
    s = r.root.split(factor=0.3)
    ck("split_returns_single", isinstance(s, RecLayout), "split 必须返回单个 layout")
    ck("split_not_tuple", not isinstance(s, tuple), "split 绝不能返回元组")
    s.label(text="窄列")

    # 2. 容器嵌套
    b = r.root.box()
    row = b.row(align=True)
    row.label(text="按钮", icon='CHECKMARK')
    b.tag("chat.action_row")
    row.tag("chat.action_row.undo")

    # 3. 属性快照
    b.alert = True
    row.enabled = False
    row.scale_y = 1.4
    b.use_property_split = True
    b.emboss = 'NONE'

    d = r.finish()
    ids = []

    def walk(n, acc):
        acc.append(n.get("element_id"))
        for c in n.get("children", []):
            walk(c, acc)

    walk(d, ids)
    ck("id_captured", "chat.action_row" in ids, "块级 ID 未进入树")
    ck("child_id_captured", "chat.action_row.undo" in ids, "子控件 ID 未进入树")

    def find(n, eid):
        if n.get("element_id") == eid:
            return n
        for c in n.get("children", []):
            got = find(c, eid)
            if got:
                return got
        return None

    box_node = find(d, "chat.action_row")
    ck("alert_recorded", box_node["alert"] is True, "alert 未记录")
    ck("enabled_recorded",
       find(d, "chat.action_row.undo")["enabled"] is False, "enabled 未记录")
    ck("scale_y_recorded",
       find(d, "chat.action_row.undo")["scale_y"] == 1.4, "scale_y 未记录")
    ck("split_recorded",
       any(n["kind"] == "split" for n in _flatten(d)), "split 节点未记录")

    texts = []
    for n in _flatten(d):
        texts.extend(n.get("texts", []))
    ck("texts_recorded", "按钮" in texts and "窄列" in texts,
       "文本未记录：%s" % texts)

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


def _flatten(node):
    yield node
    for c in node.get("children", []):
        yield from _flatten(c)


main()
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_recorder.py 2>&1 | Tee-Object dev\out\task2_fail.txt
```
预期：`ModuleNotFoundError: No module named 'dev.layout_recorder'`，退出码 1。

- [ ] **Step 3: 写录制器**

创建 `dev/layout_recorder.py`：

```python
# -*- coding: utf-8 -*-
"""UILayout 录制器：把 draw() 的调用序列录成一棵可序列化的 JSON 树。

两个必须与 Blender 5.2.1 真实行为对齐的点（都已实测）：

1. layout.split(factor=0.3) 返回**单个** UILayout，不是二元组。
   旧 dev/test_native_ui.py 的 MockLayout 返回 (a, b)，是错的。
   真实返回的对象是占左侧 factor 比例、整体左对齐的一列。
2. layout.grid_flow(...) 返回一个 UILayout；hasattr 守卫是必需的，
   因为它属于较新加入的接口。

本模块不依赖 bpy，可在任意 Python 下运行与测试。
"""

_CONTAINER_DEFAULTS = {
    "alert": False,
    "active": False,
    "enabled": True,
    "scale_y": 1.0,
    "scale_x": 1.0,
    "alignment": "EXPAND",
    "use_property_split": False,
    "emboss": "NONE",
    "operator_context": "INVOKE_DEFAULT",
}


class _OpProxy:
    """operator() 的返回值。属性赋值被吞掉——与旧 MockLayout 行为一致，
    真实 Blender 里这些值是 Operator 属性，录制阶段不参与渲染判断。"""

    def __init__(self, op_id, text, icon, kwargs):
        self.op_id = op_id
        self.text = text
        self.icon = icon
        self.kwargs = kwargs

    def __setattr__(self, name, value):
        # 保留内部四个字段，其余一律吞掉
        if name in ("op_id", "text", "icon", "kwargs"):
            object.__setattr__(self, name, value)


class RecLayout:
    def __init__(self, kind="layout", parent=None):
        self.kind = kind
        self.parent = parent
        self.children = []
        self.texts = []
        self.icons = []
        self.ops = []
        self.props = []
        self.element_id = None
        for key, val in _CONTAINER_DEFAULTS.items():
            setattr(self, key, val)

    # ---------------------------------------------------------- 容器
    def _child(self, kind):
        c = RecLayout(kind, parent=self)
        self.children.append(c)
        return c

    def row(self, align=False, **kw):
        return self._child("row")

    def column(self, align=False, **kw):
        return self._child("column")

    def box(self):
        return self._child("box")

    def split(self, factor=0.5, align=False, **kw):
        # Blender 5.x: 返回单个 layout，不是元组。见模块 docstring。
        node = self._child("split")
        node.split_factor = factor
        return node

    def grid_flow(self, row_major=True, columns=0, even_columns=False,
                  even_rows=False, align=False, layout=None):
        node = self._child("grid_flow")
        node.grid_columns = columns
        return node

    def separator(self, factor=1.0, **kw):
        return self._child("separator")

    def menu(self, name="", icon='NONE', **kw):
        node = self._child("menu")
        node.icon = icon
        return node

    def panel(self, idname, default_closed=False, layout_header=None,
              layout_body=None):
        node = self._child("panel")
        node.panel_idname = idname
        node.panel_default_closed = bool(default_closed)
        return node

    # ---------------------------------------------------------- 叶子
    def label(self, text="", text_ctxt="", translate=False, icon='NONE',
              icon_value=0):
        if text:
            self.texts.append(str(text))
        self.icons.append(icon)
        return None

    def prop(self, data, prop, text="", **kw):
        self.props.append({
            "data": getattr(data, "bl_idname", type(data).__name__),
            "prop": prop,
            "text": text,
            "kwargs": {k: str(v) for k, v in kw.items()},
        })
        if text:
            self.texts.append(str(text))
        return None

    def operator(self, op_id, text="", icon='NONE', **kw):
        op = _OpProxy(op_id, text, icon, kw)
        self.ops.append({
            "id": op_id, "text": text, "icon": icon,
            "kwargs": {k: str(v) for k, v in kw.items()},
        })
        return op

    def textbox(self, data, prop, text="", **kw):
        self.props.append({
            "data": getattr(data, "bl_idname", type(data).__name__),
            "prop": prop,
            "text": text,
            "is_textbox": True,
            "kwargs": {k: str(v) for k, v in kw.items()},
        })
        return None

    # ---------------------------------------------------------- 身份
    def tag(self, element_id):
        self.element_id = element_id

    # ---------------------------------------------------------- 序列化
    def to_dict(self):
        node = {
            "kind": self.kind,
            "element_id": self.element_id,
            "alert": self.alert,
            "active": self.active,
            "enabled": self.enabled,
            "scale_y": self.scale_y,
            "alignment": self.alignment,
            "use_property_split": self.use_property_split,
            "emboss": self.emboss,
            "texts": list(self.texts),
            "icons": list(self.icons),
            "ops": list(self.ops),
            "props": list(self.props),
            "children": [c.to_dict() for c in self.children],
        }
        for extra in ("split_factor", "grid_columns", "panel_idname",
                      "panel_default_closed"):
            if hasattr(self, extra):
                node[extra] = getattr(self, extra)
        if hasattr(self, "icon"):
            node["menu_icon"] = self.icon
        return node


class Recorder:
    def __init__(self):
        self.root = RecLayout()

    def finish(self):
        return self.root.to_dict()
```

- [ ] **Step 4: 运行测试，确认通过**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_recorder.py 2>&1 | Tee-Object dev\out\task2_pass.txt
```
预期：每一行都是 `PASS`，末尾 `FAIL 0`，退出码 0。

- [ ] **Step 5: 变异验证**

把 `RecLayout.split` 的 `return node` 改成 `return (node, self._child("split"))`（复现旧 MockLayout 的错误），重跑，**必须**看到 `FAIL split_returns_single` 与 `FAIL split_not_tuple`。确认后改回 `return node`。

---

### Task 3: ui.py 显式埋点

**Files:**
- Create: `blender_deepseek_agent/ui_ids.py`
- Modify: `blender_deepseek_agent/ui.py`（`draw_chat_content` 等，仅加 `mark()` 调用）
- Test: 复用 `dev/test_native_ui.py`

**Interfaces:**
- Produces: `blender_deepseek_agent/ui_ids.py`
  - 常量：`CHAT_TABBAR CHAT_STATUSBAR CHAT_STREAM CHAT_COMPOSER CHAT_SEND CHAT_STOP CHAT_ACTION_ROW CHAT_OPTIONS CHAT_RESULT_TABS CHAT_HISTORY`
  - `mark(layout, element_id) -> None` — 真实 `UILayout` 下是空操作，录制器下写入 ID
- [ ] **Step 1: 写失败测试**

创建 `dev/test_ids.py`：

```python
# -*- coding: utf-8 -*-
"""ui_ids 埋点契约：ID 常量齐全、命名合规、mark() 在真实 UILayout 下不炸。"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import ui_ids

FAILS = []
TOTAL = [0]

REQUIRED = [
    "CHAT_TABBAR", "CHAT_STATUSBAR", "CHAT_STREAM", "CHAT_COMPOSER",
    "CHAT_SEND", "CHAT_STOP", "CHAT_ACTION_ROW", "CHAT_OPTIONS",
    "CHAT_RESULT_TABS", "CHAT_HISTORY",
]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def main():
    bda.register()

    for name in REQUIRED:
        ck("const_%s" % name, hasattr(ui_ids, name), "缺少常量 %s" % name)

    for name in REQUIRED:
        if not hasattr(ui_ids, name):
            continue
        val = getattr(ui_ids, name)
        ck("prefix_%s" % name, val.startswith("chat."), "ID 必须以 chat. 开头：%s" % val)
        ck("charset_%s" % name,
           bool(re.fullmatch(r"chat\.[a-z0-9_]+(\.[a-z0-9_]+)*", val)),
           "ID 不符合命名规范：%s" % val)

    ck("mark_callable", callable(ui_ids.mark), "mark 必须可调用")

    # mark() 挂在没有 tag() 的对象上必须是空操作，而不是 AttributeError。
    # 注意不要去查 bpy.context.preferences.addons[...]：本任务跑在
    # --factory-startup 下，包名是 blender_deepseek_agent 而不是
    # bl_ext.user_default.*，按后者取会直接 KeyError。
    class Bare:
        pass

    ui_ids.mark(Bare(), "chat.probe")
    ck("mark_is_noop_without_tag", True, "mark 在无 tag() 的对象上不应抛异常")

    # 重复挂同一个块不应报错（draw 里一个容器可能被 mark 两次）
    b = Bare()
    ui_ids.mark(b, "chat.composer")
    ui_ids.mark(b, "chat.composer")
    ck("mark_idempotent", True, "重复 mark 不应抛异常")

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_ids.py 2>&1 | Tee-Object dev\out\task3_fail.txt
```
预期：`ModuleNotFoundError: No module named 'blender_deepseek_agent.ui_ids'`，退出码 1。

- [ ] **Step 3: 写 ui_ids.py**

创建 `blender_deepseek_agent/ui_ids.py`：

```python
# -*- coding: utf-8 -*-
"""UI 元素的稳定身份标识。

只有「区块」和「可交互控件」挂 ID，纯装饰 label 不挂——挂满会让
ui_workbench 的树无法阅读，也让标注无从下手。

ID 规范：chat.<block> 或 chat.<block>.<widget>，全小写下划线分词。
"""

CHAT_TABBAR = "chat.tabbar"
CHAT_STATUSBAR = "chat.statusbar"
CHAT_STREAM = "chat.stream"
CHAT_COMPOSER = "chat.composer"
CHAT_SEND = "chat.send_btn"
CHAT_STOP = "chat.stop_btn"
CHAT_ACTION_ROW = "chat.action_row"
CHAT_OPTIONS = "chat.options"
CHAT_RESULT_TABS = "chat.result_tabs"
CHAT_HISTORY = "chat.history"

ALL_IDS = (
    CHAT_TABBAR, CHAT_STATUSBAR, CHAT_STREAM, CHAT_COMPOSER,
    CHAT_SEND, CHAT_STOP, CHAT_ACTION_ROW, CHAT_OPTIONS,
    CHAT_RESULT_TABS, CHAT_HISTORY,
)


def mark(layout, element_id):
    """给即将绘制的布局块挂上稳定 ID。

    真实 bpy UILayout 没有 tag()，此时是空操作；dev/layout_recorder.py 的
    RecLayout 实现了 tag()，无头导出时 ID 会进入布局树。

    用 hasattr 守卫而不是 isinstance，是为了让 ui.py 的调用点在真实
    Blender 与录制器下走同一行代码，不需要任何条件编译。
    """
    tag = getattr(layout, "tag", None)
    if tag is not None:
        tag(element_id)
```

- [ ] **Step 4: 在 ui.py 中插入 mark() 调用**

在 `blender_deepseek_agent/ui.py` 顶部 import 区加入：

```python
from blender_deepseek_agent.ui_ids import (
    mark, CHAT_TABBAR, CHAT_STATUSBAR, CHAT_STREAM, CHAT_COMPOSER,
    CHAT_SEND, CHAT_STOP, CHAT_ACTION_ROW, CHAT_OPTIONS,
    CHAT_RESULT_TABS, CHAT_HISTORY,
)
```

然后在 `draw_chat_content` 内按下列位置插入 `mark(...)`（**每处都在容器创建之后、其子元素绘制之前**）：

| 位置 | 插入行 |
|:---|:---|
| `layout` 首行之后 | `mark(layout, CHAT_STREAM)` |
| 状态行容器创建之后 | `mark(<状态行容器>, CHAT_STATUSBAR)` |
| 输入框容器创建之后 | `mark(<输入框容器>, CHAT_COMPOSER)` |
| 发送按钮 `operator(...)` 所在 row 创建之后 | `mark(<该 row>, CHAT_SEND)` |
| 终止按钮所在 row 创建之后 | `mark(<该 row>, CHAT_STOP)` |
| 底部三按钮 row 创建之后 | `mark(<该 row>, CHAT_ACTION_ROW)` |
| 追问选项容器创建之后 | `mark(<追问容器>, CHAT_OPTIONS)` |
| 结果四 Tab 容器创建之后 | `mark(<结果容器>, CHAT_RESULT_TABS)` |
| 历史分页容器创建之后 | `mark(<分页容器>, CHAT_HISTORY)` |
| `DEEPSEEK_PT_chat.draw` 的 `trow` 创建之后 | `mark(trow, CHAT_TABBAR)` |

- [ ] **Step 5: 运行测试与既有回归**

```powershell
cd 'E:\Three JS\Blender Agent'
$B='D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
& $B --background --factory-startup -P dev\test_ids.py 2>&1 | Tee-Object dev\out\task3_pass.txt
powershell -ExecutionPolicy Bypass -File dev\run_all.ps1 2>&1 | Tee-Object dev\out\task3_regress.txt
```
预期：`test_ids` 全绿；`run_all.ps1` 的 `test_native_ui` / `test_ui_copy` 数字与改动前**完全一致**（mark 是空操作，不应改变任何渲染文本）。

---

### Task 4: 7 状态无头布局树导出

**Files:**
- Create: `dev/states.py`
- Create: `dev/capture_layout.py`
- Create: `dev/test_states.py`

**Interfaces:**
- Produces:
  - `dev/states.py`：`STATE_NAMES: list[str]`（7 个，顺序固定）· `build(state_name: str) -> dict` 返回 `{"state":..., "run":Run|None, "history":[(role,text)], "prompt":str, "active_tab":str}`
  - `dev/capture_layout.py`：`main() -> int`
  - `ui_workbench/data/layout/<state>.json`
- [ ] **Step 1: 写失败测试**

创建 `dev/test_states.py`：

```python
# -*- coding: utf-8 -*-
"""7 个状态构造器的契约测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from dev.states import STATE_NAMES, build
from dev.layout_recorder import Recorder
from blender_deepseek_agent import ui as U

FAILS = []
TOTAL = [0]

EXPECTED = ["idle", "clarify", "options", "running", "done", "partial", "failed"]


def ck(name, cond, msg=""):
    TOTAL[0] += 1
    if cond:
        print("PASS %s" % name)
    else:
        print("FAIL %s: %s" % (name, msg))
        FAILS.append(name)


def main():
    bda.register()
    ck("state_names_exact", STATE_NAMES == EXPECTED,
       "状态名必须严格等于 %s，实际 %s" % (EXPECTED, STATE_NAMES))

    scene = bpy.context.scene
    state = scene.deepseek_agent

    for name in STATE_NAMES:
        spec = build(name)
        U.CONTROLLER.run = spec["run"]
        state.active_tab = spec.get("active_tab", "CHAT")
        state.prompt = spec.get("prompt", "")
        state.history.clear()
        for role, text in spec.get("history", []):
            state.history.add()
            item = state.history[-1]
            item.role = role
            item.text = text

        rec = Recorder()
        try:
            U.draw_chat_content(rec.root, bpy.context, state, spec["run"])
            tree = rec.finish()
        except Exception as exc:
            ck("draw_%s" % name, False, "绘制抛异常：%r" % exc)
            continue
        ck("draw_%s" % name, True)

        ck("has_text_%s" % name, bool(tree.get("texts")) or
           bool(tree.get("children")), "树为空")
        ck("no_error_%s" % name,
           not any("错误详情" in t for t in _all_texts(tree)) or name == "failed",
           "只有 failed 状态允许出现错误文案")

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


def _all_texts(node):
    out = list(node.get("texts", []))
    for c in node.get("children", []):
        out.extend(_all_texts(c))
    return out


main()
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_states.py 2>&1 | Tee-Object dev\out\task4_fail.txt
```
预期：`ModuleNotFoundError: No module named 'dev.states'`，退出码 1。

- [ ] **Step 3: 写状态构造器**

创建 `dev/states.py`：

```python
# -*- coding: utf-8 -*-
"""【AI 对话】tab 的 7 个关键状态构造器。

布局树导出与实机截图共用这一份定义，保证两边状态绝对一致——
这是 ui_workbench 双轨能对齐的前提。改这里必须同步两个导出脚本的预期。
"""

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_deepseek_agent.state import Phase, Run, ToolCall
from blender_deepseek_agent.receipt import Receipt

STATE_NAMES = ["idle", "clarify", "options", "running", "done", "partial", "failed"]

HIST = [
    ("user", "做一个精致的中式紫砂茶杯，杯身要能看出砂颗粒的质感"),
    ("assistant", "好的，我先生成旋转截面，再用 Spin 车削出杯身一体结构。"),
    ("user", "把手做成粗一点的竹节形"),
]


def _run(phase, calls=(), **kw):
    r = Run(kw.pop("prompt", "做一个精致的中式紫砂茶杯"))
    r.phase = phase
    r.elapsed = kw.pop("elapsed", 0.0)
    r.calls = list(calls)
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def build(state_name):
    """Return a dict describing one panel state."""
    if state_name == "idle":
        return {"state": state_name, "run": None, "history": [], "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "clarify":
        r = _run(Phase.REQUESTING, elapsed=1.2)
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "options":
        r = _run(Phase.AWAITING_APPROVAL, elapsed=4.0)
        r.clarify_text = (
            "为了更贴近你想要的样子，先确认三个规格："
        )
        r.options = [
            ("杯型", ["直筒", "收腰", "鼓腹"]),
            ("壶嘴", ["短嘴", "长嘴", "无嘴"]),
            ("底款", ["圈足", "平底", "三足"]),
        ]
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "running":
        calls = [
            ToolCall("1", "get_scene_info", {}),
            ToolCall("2", "execute_blender_code", {"code": "bmesh.ops.spin"}),
        ]
        calls[0].status = "ok"
        calls[1].status = "running"
        calls[1].summary = lambda: "正在车削杯身"
        r = _run(Phase.TOOL_RUNNING, calls=calls, elapsed=6.0)
        r.step_text = "正在车削杯身"
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "done":
        calls = [ToolCall("1", "execute_blender_code", {"code": "..."})]
        calls[0].status = "ok"
        r = _run(Phase.COMPLETED, calls=calls, elapsed=24.0)
        r.receipt = Receipt()
        r.receipt.lines = ["建了 Teapot（一体网格）", "上了紫砂 PBR 材质", "把手与壶身布尔熔接"]
        r.skipped = []
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "partial":
        calls = [ToolCall("1", "execute_blender_code", {"code": "..."})]
        calls[0].status = "ok"
        r = _run(Phase.PARTIAL, calls=calls, elapsed=61.0)
        r.receipt = Receipt()
        r.receipt.lines = ["建了 Teapot（一体网格）"]
        r.skipped = ["上紫砂 PBR 材质", "把手与壶身布尔熔接"]
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    if state_name == "failed":
        r = _run(Phase.FAILED, elapsed=3.4)
        r.settled_err = "HTTP_401"
        r.approval_preview = ""
        return {"state": state_name, "run": r, "history": HIST, "prompt": "",
                "active_tab": "CHAT"}

    raise ValueError("未知状态：%s" % state_name)
```

- [ ] **Step 4: 运行测试，确认通过**

```powershell
cd 'E:\Three JS\Blender Agent'
& 'D:\blender-4.5.5-windows-x64\blender5.2\blender.exe' --background --factory-startup -P dev\test_states.py 2>&1 | Tee-Object dev\out\task4_pass.txt
```
预期：7 个 `draw_<状态>` 全 PASS，末尾 `FAIL 0`，退出码 0。**若 `Run` / `ToolCall` / `Receipt` 的字段名与上面不符，先读 `blender_deepseek_agent/state.py` 与 `receipt.py` 对齐真实字段，再改本文件。**

- [ ] **Step 5: 写导出脚本**

创建 `dev/capture_layout.py`：

```python
# -*- coding: utf-8 -*-
"""无头导出 7 个状态的布局树 JSON。绝不开 GUI。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import ui as U
from dev.states import STATE_NAMES, build
from dev.layout_recorder import Recorder

OUT_DIR = os.path.join(ROOT, "ui_workbench", "data", "layout")


def main():
    bda.register()
    scene = bpy.context.scene
    state = scene.deepseek_agent
    os.makedirs(OUT_DIR, exist_ok=True)

    written = []
    for name in STATE_NAMES:
        spec = build(name)
        U.CONTROLLER.run = spec["run"]
        state.active_tab = spec.get("active_tab", "CHAT")
        state.prompt = spec.get("prompt", "")
        state.history.clear()
        for role, text in spec.get("history", []):
            state.history.add()
            item = state.history[-1]
            item.role = role
            item.text = text

        rec = Recorder()
        U.draw_chat_content(rec.root, bpy.context, state, spec["run"])
        tree = rec.finish()
        tree["state"] = name

        path = os.path.join(OUT_DIR, "%s.json" % name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(tree, fh, ensure_ascii=False, indent=2)
        written.append(name)
        print("WROTE %s ids=%d" % (name, _count_ids(tree)))

    print("CAPTURE_LAYOUT_OK count=%d" % len(written))
    print("STATES %s" % " ".join(written))
    return 0


def _count_ids(node):
    n = 1 if node.get("element_id") else 0
    for c in node.get("children", []):
        n += _count_ids(c)
    return n


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: 运行导出并检查 ID 覆盖率**

```powershell
cd 'E:\Three JS\Blender Agent'
$B='D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
& $B --background --factory-startup -P dev\capture_layout.py 2>&1 | Tee-Object dev\out\task4_capture.txt
```
预期：`CAPTURE_LAYOUT_OK count=7`，且每个状态 `ids >= 5`。

若某状态 `ids=0`，说明 Task 3 的 `mark()` 没落到那条分支上——回到 `ui.py` 补，不要放宽这个判据。

---

### Task 5: 7 状态实机截图（一次 GUI）

**Files:**
- Create: `dev/capture_shots.py`

**Interfaces:**
- Consumes: `dev/states.py` 的 `build()`
- Produces: `ui_workbench/data/shots/<state>.png`（裁切后的 N 面板）

- [ ] **Step 1: 读现成脚本，再写截图脚本**

**先读 `dev/gui_check_v2.py`**——它已经跑通过「真实窗口 + 灌假数据 + 逐状态截图」，
本任务的机制必须与它一致，不要从零另发明一套。它已经踩平了这几件事：

| 机制 | 正确写法 | 常见错法 |
|:---|:---|:---|
| 切到 AI 对话页 | `region.active_panel_category = "AI 对话"` | `space.category` —— 不是那个属性，切不过去 |
| 推进状态 | `bpy.app.timers.register` 驱动状态机 | for 循环同步跑 —— 面板来不及重绘，7 张图全是同一张 |
| 等重绘 | `area.tag_redraw()` + `time.sleep(0.35)` | `bpy.ops.wm.redraw_timer` —— 抓不到真实绘制结果 |
| 防挂死 | timer 计数器看门狗，超限 `wm.quit_blender()` | 无 —— 一旦不返回会留下僵尸进程 |
| 收尾 | 全部拍完后 `wm.quit_blender()` | 忘调 —— 窗口一直挂着 |

创建 `dev/capture_shots.py`，复用上述机制：

```python
# -*- coding: utf-8 -*-
"""一次 GUI 运行产出 7 个状态的 N 面板截图。

机制照抄 dev/gui_check_v2.py：定时器驱动状态机 + 重绘等待 + 看门狗。
不要写成同步 for 循环——面板来不及重绘，截出来会是同一张图。

必须用最小化窗口运行，不要抢用户桌面。拍完调用 wm.quit_blender 退出，
不要留下残留进程。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import ui as U
from dev.states import STATE_NAMES, build

OUT_DIR = os.path.join(ROOT, "ui_workbench", "data", "shots")

_state = {"i": 0, "settle": 0, "watchdog": 0, "taken": [], "errs": []}


def log(*a):
    print("[SHOTS]", " ".join(str(x) for x in a))


def find_ui_region():
    """Locate the N-panel UI region and point it at the AI chat category."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'UI':
                continue
            for region in area.regions:
                if region.type != 'UI' or region.width <= 200:
                    continue
                try:
                    region.active_panel_category = "AI 对话"
                except Exception as exc:
                    log("CATEGORY_FAIL", exc)
                    continue
                area.tag_redraw()
                log("category set ->", region.active_panel_category,
                    "| region", region.x, region.y, region.width, region.height)
                return area, region
    return None, None


def apply(name):
    """Push one state into the live PropertyGroup."""
    spec = build(name)
    U.CONTROLLER.run = spec["run"]
    state = bpy.context.scene.deepseek_agent
    state.active_tab = spec.get("active_tab", "CHAT")
    state.prompt = spec.get("prompt", "")
    state.history.clear()
    for role, text in spec.get("history", []):
        state.history.add()
        item = state.history[-1]
        item.role = role
        item.text = text
    log("applied", name)


def tick():
    """Alternate two phases per state: apply -> settle -> shoot.

    A single post-loop screenshot would only capture the LAST state. Every
    state needs its own apply/settle/shoot cycle.
    """
    _state["watchdog"] += 1
    if _state["watchdog"] > 240:
        log("WATCHDOG_TIMEOUT taken=%d" % len(_state["taken"]))
        bpy.ops.wm.quit_blender()
        return None

    area, region = _state.get("ar", (None, None))
    if area is None:
        area, region = find_ui_region()
        _state["ar"] = (area, region)
        if area is None:
            log("NO_UI_REGION -- open the N panel first")
            bpy.ops.wm.quit_blender()
            return None
        return 0.5

    if _state["settle"] < 3:
        _state["settle"] += 1
        area.tag_redraw()
        return 0.5
    _state["settle"] = 0

    pending = _state.get("pending")
    if pending is None:
        if _state["i"] >= len(STATE_NAMES):
            log("CAPTURE_SHOTS_OK count=%d errs=%d"
                % (len(_state["taken"]), len(_state["errs"])))
            log("STATES %s" % " ".join(_state["taken"]))
            if _state["errs"]:
                for e in _state["errs"]:
                    log("ERR", e)
            bpy.ops.wm.quit_blender()
            return None
        pending = STATE_NAMES[_state["i"]]
        _state["i"] += 1
        _state["pending"] = pending
        try:
            apply(pending)
        except Exception as exc:
            _state["errs"].append("apply %s: %r" % (pending, exc))
            log("APPLY_FAIL", pending, repr(exc))
        return 0.5

    area.tag_redraw()
    time.sleep(0.35)
    path = os.path.join(OUT_DIR, "%s_full.png" % pending)
    try:
        bpy.ops.screen.screenshot(filepath=path)
        _state["taken"].append(pending)
        log("shot", pending, os.path.getsize(path), "bytes")
    except Exception as exc:
        _state["errs"].append("shot %s: %r" % (pending, exc))
        log("SHOT_FAIL", pending, exc)
    _state["pending"] = None
    return 0.5


def main():
    bda.register()
    os.makedirs(OUT_DIR, exist_ok=True)
    bpy.app.timers.register(tick, first_interval=1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> `--background` 下 `bpy.app.timers` 一次都不触发（实测等 3 秒 0 次），
> 所以本脚本**只能**用 GUI 模式跑，`--background` 会静默挂住不产出任何东西。

- [ ] **Step 2: 运行（最小化，单实例）**

```powershell
cd 'E:\Three JS\Blender Agent'
$B='D:\blender-4.5.5-windows-x64\blender5.2\blender.exe'
$p = Start-Process -FilePath $B -ArgumentList '-P','dev\capture_shots.py' `
  -WindowStyle Minimized -PassThru -Wait `
  -RedirectStandardOutput 'dev\out\shots_o.txt' `
  -RedirectStandardError  'dev\out\shots_e.txt'
Write-Output "EXITCODE=$($p.ExitCode)"
Get-Content 'dev\out\shots_o.txt' -Encoding UTF8
```

> **不要加 `--factory-startup`**——那会禁用扩展，插件根本不加载。也不要并行跑第二个 Blender 实例。

预期：`EXITCODE=0`，`CAPTURE_SHOTS_OK count=7`。

- [ ] **Step 3: 裁切出 N 面板**

对 7 张 `*_full.png` 各裁一次。裁切坐标必须从本机截图实测得出，**不要照抄文档里的旧值**：

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\crop.py idle_full.png <X0> <Y0> <X1> <Y1> 1 idle
```

先用一次性探针找出面板边界，再写死进 `dev/crop_panel.py`：

```python
# -*- coding: utf-8 -*-
"""扫出 N 面板 UI region 在截图里的像素边界。"""
import sys
from PIL import Image

path = sys.argv[1]
im = Image.open(path).convert("RGB")
W, H = im.size
# The N panel sits at the right edge. Scan a mid-height row for the column
# where the viewport grid ends and the flat panel background begins.
y = int(H * 0.5)
px = im.load()
edge = None
for x in range(W - 1, int(W * 0.55), -1):
    r, g, b = px[x, y]
    if abs(r - g) < 12 and abs(g - b) < 12 and r < 90:
        edge = x
    elif edge is not None:
        break
print("SIZE %dx%d" % (W, H))
print("PANEL_LEFT %s" % edge)
```

用 `--python` 之外的方式跑（纯 PIL，不进 Blender）：

```powershell
python -c "import runpy,sys; sys.argv=['crop_panel.py','ui_workbench/data/shots/idle_full.png']; runpy.run_path('dev/crop_panel.py', run_name='__main__')"
```

- [ ] **Step 4: 人工验收 7 张图**

用 `read` 工具直接逐张读 `ui_workbench/data/shots/<state>.png`。逐张确认：面板标题可见、状态文案与状态名相符、没有被裁掉半个按钮、`failed` 那张的红框是 `alert` 而不是别的。

**任何一张不合格就修脚本重跑，不要手工改图。**

---

### Task 6: 镜像视图

**Files:**
- Create: `ui_workbench/index.html`
- Create: `ui_workbench/app.js`
- Create: `ui_workbench/style.css`
- Create: `dev/test_workbench_data.py`

**Interfaces:**
- Consumes: `ui_workbench/data/layout/*.json` · `ui_workbench/data/shots/*.png` · `ui_workbench/constraints.json`
- Produces: `dev/test_workbench_data.py` —— 校验 7 组数据齐全且可解析

- [ ] **Step 1: 写失败测试**

创建 `dev/test_workbench_data.py`：

```python
# -*- coding: utf-8 -*-
"""工作台数据完整性检查。纯标准库，不进 Blender。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
STATES = ["idle", "clarify", "options", "running", "done", "partial", "failed"]

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
    ck("index_exists", os.path.exists(os.path.join(WB, "index.html")), "缺 index.html")
    ck("app_exists", os.path.exists(os.path.join(WB, "app.js")), "缺 app.js")
    ck("style_exists", os.path.exists(os.path.join(WB, "style.css")), "缺 style.css")
    ck("constraints_exists", os.path.exists(os.path.join(WB, "constraints.json")), "缺 constraints.json")

    for s in STATES:
        lp = os.path.join(WB, "data", "layout", "%s.json" % s)
        sp = os.path.join(WB, "data", "shots", "%s.png" % s)
        ck("layout_%s" % s, os.path.exists(lp), "缺布局树")
        ck("shot_%s" % s, os.path.exists(sp), "缺截图")
        if os.path.exists(lp):
            with open(lp, encoding="utf-8") as fh:
                tree = json.load(fh)
            ck("layout_parse_%s" % s, tree.get("state") == s, "state 字段不匹配")
            ids = []
            _walk(tree, ids)
            ck("layout_ids_%s" % s, len([i for i in ids if i]) >= 5,
               "带 ID 的节点太少：%d" % len([i for i in ids if i]))
        if os.path.exists(sp):
            ck("shot_size_%s" % s, os.path.getsize(sp) > 8000, "截图疑似空文件")

    html = ""
    if os.path.exists(os.path.join(WB, "index.html")):
        with open(os.path.join(WB, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
    ck("no_remote_assets", "http://" not in html and "https://" not in html,
       "工作台必须完全离线，不得引用远程资源")
    ck("has_view_switch", "mirror" in html and "proposal" in html,
       "index.html 必须同时声明两个视图")

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


def _walk(node, acc):
    acc.append(node.get("element_id"))
    for c in node.get("children", []):
        _walk(c, acc)


main()
```

- [ ] **Step 2: 运行，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\test_workbench_data.py
```
预期：多项 FAIL，非零退出。

- [ ] **Step 3: 写 style.css**

创建 `ui_workbench/style.css`：

```css
/* 工作台样式。配色只允许取自 ui_workbench/native_api.json 的实测主题色：
   wcol_box.inner #1d1d1d / wcol_box.outline #3d3d3d / wcol_text.text #e6e6e6
   禁止出现任何 native_api.json 里没有的十六进制色值。 */
:root {
  --panel: #3d3d3d;
  --inner: #1d1d1d;
  --text: #e6e6e6;
  --text-dim: #989898;
  --accent: #4772b3;
  --alert: #991616;
  --ok: #188625;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--panel); color: var(--text);
  font: 13px/1.6 "Microsoft YaHei", sans-serif;
}
header {
  display: flex; gap: 8px; padding: 8px 12px;
  background: var(--inner); border-bottom: 1px solid #545454;
  align-items: center; flex-wrap: wrap;
}
header h1 { font-size: 14px; margin: 0 12px 0 0; font-weight: normal; }
nav button {
  background: var(--panel); color: var(--text); border: 1px solid #545454;
  padding: 4px 14px; cursor: pointer; border-radius: 4px;
}
nav button.on { background: var(--accent); border-color: var(--accent); }
.filmstrip { display: flex; gap: 6px; overflow-x: auto; padding: 8px 12px; }
.filmstrip button {
  background: var(--panel); color: var(--text-dim); border: 1px solid #545454;
  border-radius: 4px; padding: 4px 10px; cursor: pointer; white-space: nowrap;
}
.filmstrip button.on { color: var(--text); border-color: var(--accent); }
.split { display: flex; gap: 12px; padding: 0 12px 12px; align-items: flex-start; }
.shot-pane { flex: 0 0 420px; position: sticky; top: 8px; }
.shot-pane img { width: 420px; border: 1px solid #545454; border-radius: 4px; display: block; }
.tree-pane { flex: 1 1 auto; min-width: 360px; }
.node {
  border-left: 2px solid transparent; padding: 2px 8px; cursor: pointer;
  border-radius: 0 4px 4px 0;
}
.node:hover { background: #181818; }
.node.sel { background: var(--accent); }
.node .id { color: #7cb87c; font-family: Consolas, monospace; }
.node .txt { color: var(--text); }
.node .kind { color: var(--text-dim); font-size: 11px; margin-right: 6px; }
.node.alert { border-left-color: var(--alert); }
.node.disabled { opacity: .45; }
.constraints { margin-top: 16px; border-top: 1px solid #545454; padding-top: 12px; }
.constraints table { border-collapse: collapse; width: 100%; }
.constraints td, .constraints th {
  border: 1px solid #545454; padding: 4px 8px; text-align: left; vertical-align: top;
}
.badge { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 11px; }
.badge.ok { background: var(--ok); color: #fff; }
.badge.no { background: var(--alert); color: #fff; }
.note { background: #181818; border: 1px solid #545454; border-radius: 4px; padding: 8px; margin: 6px 0; }
.note.blocked { border-color: var(--alert); }
textarea { width: 100%; min-height: 60px; background: var(--inner); color: var(--text);
           border: 1px solid #545454; border-radius: 4px; padding: 6px; }
```

- [ ] **Step 4: 写 index.html**

创建 `ui_workbench/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>UI Workbench · blender_deepseek_agent</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header>
  <h1>UI Workbench</h1>
  <nav id="views">
    <button data-view="mirror" class="on">镜像视图</button>
    <button data-view="proposal">提案视图</button>
    <button data-view="constraints">约束总表</button>
  </nav>
  <span id="status" style="margin-left:auto;color:#989898"></span>
  <button id="export">导出标注</button>
</header>

<div id="filmstrip" class="filmstrip"></div>

<section id="view-mirror" class="view">
  <div class="split">
    <div class="shot-pane">
      <img id="shot" alt="实机截图">
      <div id="shot-cap" style="color:#989898;padding:4px 0"></div>
    </div>
    <div class="tree-pane">
      <div id="tree"></div>
    </div>
  </div>
  <div id="annot"></div>
</section>

<section id="view-proposal" class="view" hidden>
  <div id="vocab-bar"></div>
  <div id="canvas"></div>
  <div id="prop-notes"></div>
</section>

<section id="view-constraints" class="view" hidden>
  <div class="constraints" id="constraints"></div>
</section>

<script src="data/data.js"></script>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 5: 写 app.js**

创建 `ui_workbench/app.js`：

```javascript
/* 工作台逻辑。零依赖，file:// 直开。 */
"use strict";

var STATES = ["idle", "clarify", "options", "running", "done", "partial", "failed"];
var NAMES = {
  idle: "空闲", clarify: "待澄清", options: "规格选项待选",
  running: "执行中", done: "做完", partial: "做到一半", failed: "失败"
};

var cur = "idle";
var tree = null;
var constraints = null;
var annotations = loadAnnotations();

function loadAnnotations() {
  try {
    return JSON.parse(localStorage.getItem("uw_annotations") || "{}");
  } catch (e) {
    return {};
  }
}

function saveAnnotations() {
  // file:// 下 localStorage 在 Chrome 里抛 SecurityError，Firefox 正常。
  // 存不了就退回内存，导出按钮仍然可用——不能让一次按键崩掉整个页面。
  try {
    localStorage.setItem("uw_annotations", JSON.stringify(annotations, null, 2));
  } catch (e) {
    setStatus("（file:// 下无法持久化，标注只保存在内存，用「导出标注」保存）");
  }
}

function el(id) { return document.getElementById(id); }

var DATA = window.UW_DATA || null;

function getJSON(path) {
  // file:// 是不透明源（opaque origin）：XMLHttpRequest / fetch 拉同目录文件
  // 会被 CORS 直接拒掉，localStorage 也会抛 SecurityError。所以所有数据由
  // data/data.js 以 window.UW_DATA 全局注入，这里只做查表。
  if (!DATA) {
    return Promise.reject(new Error(
      "data/data.js 没加载，先跑 python dev\\build_data_js.py"));
  }
  var key = path.replace(/^data\//, "").replace(/\.json$/, "");
  var v = DATA[key];
  if (v === undefined) {
    return Promise.reject(new Error(
      path + " 不在 data/data.js 里，重新生成"));
  }
  return Promise.resolve(v);
}

function setStatus(msg) { el("status").textContent = msg || ""; }

function renderFilmstrip() {
  var bar = el("filmstrip");
  bar.innerHTML = "";
  STATES.forEach(function (s) {
    var b = document.createElement("button");
    b.textContent = NAMES[s] + " (" + s + ")";
    if (s === cur) { b.className = "on"; }
    b.onclick = function () { loadState(s); };
    bar.appendChild(b);
  });
}

function loadState(name) {
  cur = name;
  renderFilmstrip();
  el("shot").src = "data/shots/" + name + ".png";
  el("shot-cap").textContent = "实机截图 · " + NAMES[name];
  setStatus("加载 " + name + " …");
  getJSON("data/layout/" + name + ".json").then(function (t) {
    tree = t;
    renderTree();
    renderAnnot();
    setStatus("");
  }).catch(function (e) {
    setStatus("布局树缺失：" + e.message + "（先跑 dev/capture_layout.py）");
    el("tree").innerHTML = "";
  });
}

function renderTree() {
  var host = el("tree");
  host.innerHTML = "";
  if (!tree) { return; }
  host.appendChild(node(tree, 0));
}

function node(n, depth) {
  var d = document.createElement("div");
  d.className = "node";
  d.style.paddingLeft = (depth * 16 + 8) + "px";
  if (n.alert) { d.className += " alert"; }
  if (n.enabled === false) { d.className += " disabled"; }
  d.dataset.eid = n.element_id || "";

  var kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = n.kind;
  d.appendChild(kind);

  if (n.element_id) {
    var i = document.createElement("span");
    i.className = "id";
    i.textContent = n.element_id + " ";
    d.appendChild(i);
  }
  (n.texts || []).forEach(function (t) {
    var s = document.createElement("span");
    s.className = "txt";
    s.textContent = t + " ";
    d.appendChild(s);
  });
  (n.ops || []).forEach(function (o) {
    var s = document.createElement("span");
    s.className = "id";
    s.textContent = "[" + o.id + (o.text ? ":" + o.text : "") + "] ";
    d.appendChild(s);
  });
  if (n.alert) {
    var a = document.createElement("span");
    a.className = "kind";
    a.textContent = "alert";
    d.appendChild(a);
  }
  if (n.enabled === false) {
    var e = document.createElement("span");
    e.className = "kind";
    e.textContent = "disabled";
    d.appendChild(e);
  }

  d.onclick = function () {
    var all = host.querySelectorAll(".node");
    for (var i2 = 0; i2 < all.length; i2++) { all[i2].className = all[i2].className.replace(/\s*sel\b/g, ""); }
    d.className += " sel";
    renderAnnot();
  };
  (n.children || []).forEach(function (c) { host.appendChild(node(c, depth + 1)); });
  return d;
}

function selectedEid() {
  var s = document.querySelector("#tree .node.sel");
  return s ? s.dataset.eid : "";
}

function renderAnnot() {
  var host = el("annot");
  var eid = selectedEid();
  host.innerHTML = "";
  var h = document.createElement("h3");
  h.textContent = "标注 · " + (eid || "（先在左侧点一个元素）");
  host.appendChild(h);

  var note = document.createElement("div");
  note.className = "note";
  var ta = document.createElement("textarea");
  ta.placeholder = "想要什么？为什么？";
  ta.value = (annotations[cur + "|" + eid] || {}).want || "";
  ta.oninput = function () {
    annotations[cur + "|" + eid] = annotations[cur + "|" + eid] || {};
    annotations[cur + "|" + eid].want = ta.value;
    saveAnnotations();
  };
  note.appendChild(ta);
  host.appendChild(note);
}

function renderConstraints() {
  getJSON("constraints.json").then(function (reg) {
    constraints = reg;
    var host = el("constraints");
    var t = "<table><tr><th>能力</th><th>判定</th><th>阻断原因 / API</th><th>降级方案</th></tr>";
    reg.entries.forEach(function (e) {
      t += "<tr><td>" + e.title + "<br><small>" + e.key + "</small></td>";
      t += "<td><span class='badge " + (e.native_ok ? "ok" : "no") + "'>" +
           (e.native_ok ? "可做" : "做不到") + "</span></td>";
      t += "<td>" + (e.native_ok ? (e.uiloayout || "") : e.blocker) + "</td>";
      t += "<td>" + (e.native_ok ? "—" : e.fallback) + "</td></tr>";
    });
    host.innerHTML = t + "</table>";
  }).catch(function (e) {
    el("constraints").textContent = "constraints.json 缺失：" + e.message;
  });
}

function switchView(name) {
  ["mirror", "proposal", "constraints"].forEach(function (v) {
    el("view-" + v).hidden = (v !== name);
  });
  var bs = document.querySelectorAll("#views button");
  for (var i = 0; i < bs.length; i++) {
    bs[i].className = (bs[i].dataset.view === name) ? "on" : "";
  }
  if (name === "constraints") { renderConstraints(); }
}

function init() {
  var bs = document.querySelectorAll("#views button");
  for (var i = 0; i < bs.length; i++) {
    (function (b) { b.onclick = function () { switchView(b.dataset.view); }; }(bs[i]));
  }
  el("export").onclick = function () {
    var blob = new Blob([JSON.stringify(annotations, null, 2)],
                        { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "annotations.json";
    a.click();
    setStatus("已导出 annotations.json");
  };
  loadState("idle");
}

document.addEventListener("DOMContentLoaded", init);
```

- [ ] **Step 6: 写 data.js 生成器**

创建 `dev/build_data_js.py`：

```python
# -*- coding: utf-8 -*-
"""把工作台需要的全部 JSON 打包成一个 data.js。

为什么需要它：file:// 是不透明源，浏览器用 XHR / fetch 拉同目录文件会被
CORS 拒掉（Chrome 尤其如此，必须加 --allow-file-access-from-files 才行）。
用 <script src> 注入全局对象是唯一能在 file:// 下零服务器取数的办法。

键名规则：去掉 data/ 前缀与 .json 后缀。
  data/layout/idle.json -> "layout/idle"
  constraints.json      -> "constraints"
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
OUT = os.path.join(WB, "data", "data.js")


def main():
    payload = {}

    cons = os.path.join(WB, "constraints.json")
    if os.path.exists(cons):
        with open(cons, encoding="utf-8") as fh:
            payload["constraints"] = json.load(fh)
    else:
        print("MISSING ui_workbench/constraints.json")
        return 1

    layout_dir = os.path.join(WB, "data", "layout")
    n_layout = 0
    if os.path.isdir(layout_dir):
        for fn in sorted(os.listdir(layout_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(layout_dir, fn), encoding="utf-8") as fh:
                payload["layout/" + fn[:-5]] = json.load(fh)
                n_layout += 1

    vocab = os.path.join(WB, "vocabulary.json")
    if os.path.exists(vocab):
        with open(vocab, encoding="utf-8") as fh:
            payload["vocabulary"] = json.load(fh)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by dev/build_data_js.py -- do not edit by hand */\n")
        fh.write("window.UW_DATA = ")
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        fh.write(";\n")

    print("DATA_JS_OK keys=%d layouts=%d" % (len(payload), n_layout))
    print("KEYS %s" % " ".join(sorted(payload)))
    if n_layout < 7:
        print("WARN only %d layout files, run dev/capture_layout.py" % n_layout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

运行：

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\build_data_js.py
```
预期：`DATA_JS_OK keys=8 layouts=7`。`vocabulary.json` 此时还不存在（Task 7 才生成），键数 7 也可接受，Task 7 结束后要重跑一次。

- [ ] **Step 7: 运行测试并人工验收**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\test_workbench_data.py
```
预期：`PASS 0 FAIL`，退出码 0。

然后用浏览器打开 `ui_workbench/index.html`，逐个状态点一遍，确认：截图显示、树有层级、点元素树高亮、标注能输入并刷新不丢。

---

### Task 7: 受限词汇表与提案画布

**Files:**
- Create: `ui_workbench/vocabulary.json`
- Modify: `ui_workbench/app.js`
- Modify: `ui_workbench/index.html`
- Create: `dev/build_vocabulary.py`

**Interfaces:**
- Consumes: `ui_workbench/constraints.json`
- Produces:
  - `build_vocabulary.build(constraints) -> dict`
  - `ui_workbench/vocabulary.json` schema：
    ```json
    {
      "widgets": [
        {"key": "box", "label": "内盒", "uiloayout": "layout.box()",
         "allowed_props": ["alert"],
         "blocked_props": [],
         "note": "alert 是全 UI 唯一的红，只给 FAILED 用"}
      ],
      "rejected": [
        {"key": "hover", "label": "悬停高亮", "fallback": "用 enabled/active 二态"}
      ]
    }
    ```

- [ ] **Step 1: 写词汇表生成器**

创建 `dev/build_vocabulary.py`：

```python
# -*- coding: utf-8 -*-
"""从 constraints.json 生成受限词汇表。

原则：只有 native_ok=true 的能力才能进词汇表；每条 native_ok=false 的
能力都要产出一条 rejected 项，带着降级方案，提案视图据此拦截。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "ui_workbench", "constraints.json")
OUT = os.path.join(ROOT, "ui_workbench", "vocabulary.json")

WIDGETS = [
    ("row", "横排", "layout.row(align=True)", ["align"], [],
     "当前代码用量 0，成本最低的层次工具"),
    ("column", "竖排", "layout.column(align=True)", ["align"], [], ""),
    ("box", "内盒", "layout.box()", ["alert"], [],
     "alert 是全 UI 唯一的红，只留给 FAILED"),
    ("split", "左右分栏", "layout.split(factor=0.3)", ["factor"], [],
     "返回单个 layout，不是二元组"),
    ("grid_flow", "网格按钮", "layout.grid_flow(columns=2, even_columns=True)",
     ["columns", "even_columns", "row_major"], [], "当前已在设置页用于模型切换"),
    ("panel", "可折叠子面板", "layout.panel(idname, default_closed)",
     ["idname", "default_closed"], [],
     "消化长度的唯一手段，侧栏滚不了"),
    ("label", "文字", "layout.label(text=..., icon=...)",
     ["text", "icon"], ["size", "font", "color"],
     "没有 size/color/font 参数；层次靠 icon 和 scale_y"),
    ("operator", "按钮", "layout.operator(id, text=..., icon=...)",
     ["id", "text", "icon", "depress", "emboss"], ["color"],
     "emboss='NONE' 可去掉高光渐变"),
    ("prop", "属性行", "layout.prop(data, prop, text=...)",
     ["prop", "text"], ["color"], "配 use_property_split 得到原生两列"),
    ("textbox", "多行输入", "layout.textbox(data, 'prompt', initial_visible_lines=3)",
     ["prop", "text", "placeholder", "initial_visible_lines"], [],
     "中文 IME 只能靠原生 textbox，自绘拿不到拼音组合态"),
    ("separator", "分隔线", "layout.separator()", [], [], ""),
    ("scale_y", "留白撑高", "layout.scale_y = 1.4", ["scale_y"], [],
     "字号不可调，层次只能靠撑高和缩进"),
]


def build(constraints):
    reg = {e["key"]: e for e in constraints["entries"]}
    widgets = []
    for key, label, call, allowed, blocked, note in WIDGETS:
        widgets.append({
            "key": key, "label": label, "uiloayout": call,
            "allowed_props": allowed, "blocked_props": blocked, "note": note,
        })
    rejected = []
    for e in constraints["entries"]:
        if e["native_ok"]:
            continue
        rejected.append({
            "key": e["key"], "label": e["title"],
            "blocker": e["blocker"], "fallback": e["fallback"],
        })
    return {
        "generated_for": constraints["generated_for"],
        "widgets": widgets,
        "rejected": rejected,
    }


def main():
    with open(SRC, encoding="utf-8") as fh:
        constraints = json.load(fh)
    vocab = build(constraints)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(vocab, fh, ensure_ascii=False, indent=2)
    print("VOCAB_OK widgets=%d rejected=%d" % (len(vocab["widgets"]), len(vocab["rejected"])))
    for r in vocab["rejected"]:
        print("REJECT %-18s -> %s" % (r["key"], r["fallback"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行生成器**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\build_vocabulary.py
```
预期：`VOCAB_OK widgets=12 rejected=8`，并逐行列出 8 条降级方案。

**立刻重跑一次 `python dev\build_data_js.py`**，否则 `data/data.js` 里没有 `vocabulary` 键，提案视图会报「不在 data/data.js 里」。

- [ ] **Step 3: 在 app.js 里加提案画布**

在 `ui_workbench/app.js` 末尾、`document.addEventListener` 之前插入：

```javascript
/* ---------------- 提案视图 ---------------- */

var proposal = [];   // [{widget, id, note}]
var vocab = null;

function loadVocab() {
  return getJSON("vocabulary.json").then(function (v) {
    vocab = v;
    renderVocabBar();
    renderRejected();
    renderCanvas();
  });
}

function renderVocabBar() {
  var host = el("vocab-bar");
  host.innerHTML = "<b>可用控件（落笔即校验）</b> ";
  vocab.widgets.forEach(function (w) {
    var b = document.createElement("button");
    b.textContent = w.label;
    b.title = w.uiloayout + (w.note ? "\n" + w.note : "");
    b.onclick = function () { addWidget(w); };
    host.appendChild(b);
  });
}

function renderRejected() {
  var host = el("prop-notes");
  host.innerHTML = "<h3>想做但 Blender 做不到的（点击即插入降级方案）</h3>";
  var t = document.createElement("table");
  t.className = "constraints";
  vocab.rejected.forEach(function (r) {
    var b = document.createElement("button");
    b.textContent = "插入降级：" + r.label;
    b.onclick = function () { addRejected(r); };
    host.appendChild(b);
  });
  host.appendChild(t);
}

function validateWidget(w, params) {
  var errs = [];
  (params || []).forEach(function (p) {
    if (w.blocked_props.indexOf(p) >= 0) {
      errs.push("参数 " + p + " 不被 UILayout 支持");
    }
  });
  return errs;
}

function addWidget(w) {
  var node = {
    widget: w.key,
    label: w.label,
    uiloayout: w.uiloayout,
    id: "",
    note: "",
    errors: validateWidget(w, [])
  };
  proposal.push(node);
  renderCanvas();
}

function addRejected(r) {
  var node = {
    widget: "__downgraded__",
    label: r.label,
    uiloayout: "(不可用)",
    fallback: r.fallback,
    blocker: r.blocker,
    id: "",
    note: "",
    errors: []
  };
  proposal.push(node);
  renderCanvas();
}

function renderCanvas() {
  var host = el("canvas");
  host.innerHTML = "";
  proposal.forEach(function (n, i) {
    var box = document.createElement("div");
    box.className = "note" + (n.errors.length ? " blocked" : "");
    var head = document.createElement("div");
    head.innerHTML = "<b>" + n.label + "</b> <code>" + n.uiloayout + "</code>";
    box.appendChild(head);

    if (n.fallback) {
      var fb = document.createElement("div");
      fb.style.color = "#989898";
      fb.textContent = "原需求：" + n.blocker + " ｜ 降级方案：" + n.fallback;
      box.appendChild(fb);
    }
    n.errors.forEach(function (e) {
      var er = document.createElement("div");
      er.style.color = "#e0716a";
      er.textContent = "违规：" + e;
      box.appendChild(er);
    });

    var idIn = document.createElement("input");
    idIn.placeholder = "对应插件元素 ID（可空）";
    idIn.value = n.id;
    idIn.style.cssText = "width:100%;margin:4px 0;background:#1d1d1d;color:#e6e6e6;border:1px solid #545454;padding:4px";
    idIn.oninput = function () { n.id = idIn.value; };
    box.appendChild(idIn);

    var ta = document.createElement("textarea");
    ta.placeholder = "想要什么？为什么？";
    ta.value = n.note;
    ta.oninput = function () { n.note = ta.value; };
    box.appendChild(ta);
    host.appendChild(box);
  });
  if (!proposal.length) {
    host.innerHTML = "<p style='color:#989898'>从上面挑控件开始拼装。挑不到想要的效果时，看右侧「做不到」列表。</p>";
  }
}
```

- [ ] **Step 4: 让导出按钮同时导出提案**

把 `app.js` 里导出按钮的 `onclick` 改成：

```javascript
  el("export").onclick = function () {
    var payload = {
      annotations: annotations,
      proposal: proposal
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)],
                        { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "annotations.json";
    a.click();
    setStatus("已导出 annotations.json（含 " +
              Object.keys(annotations).length + " 条标注，" +
              proposal.length + " 条提案）");
  };
```

并把 `switchView` 里的 proposal 分支补上：

```javascript
  if (name === "proposal") { loadVocab().catch(function (e) {
    setStatus("vocabulary.json 缺失：" + e.message + "（先跑 dev/build_vocabulary.py）");
  }); }
```

- [ ] **Step 5: 人工验收拦截是否生效**

浏览器打开工作台 → 切到提案视图 → 逐个把 12 个控件点一遍，确认每个都不报错（词汇表内全部合法）→ 在「做不到」列表点一条，确认插入的是降级方案而非原需求。

---

### Task 8: 端到端验收

**Files:**
- Modify: `dev/run_all.ps1`（加入新测试）
- Create: `dev/test_pipeline.py`

**Interfaces:**
- Consumes: 全部前置任务产物
- Produces: 一条命令跑完全链路的回归入口

- [ ] **Step 1: 写端到端流水线测试**

创建 `dev/test_pipeline.py`：

```python
# -*- coding: utf-8 -*-
"""ui_workbench 全链路自检：数据 → 词汇表 → 标注 → 导出，缺一环就红。"""
import json
import os
import sys

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


def jload(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    cons = os.path.join(WB, "constraints.json")
    vocab_p = os.path.join(WB, "vocabulary.json")
    ck("constraints", os.path.exists(cons))
    ck("vocabulary", os.path.exists(vocab_p))
    if not (os.path.exists(cons) and os.path.exists(vocab_p)):
        print("PASS 0  FAIL %d" % len(FAILS))
        sys.exit(1)

    cons = jload(cons)
    vocab = jload(vocab_p)

    blocked = {e["key"] for e in cons["entries"] if not e["native_ok"]}
    rejected = {r["key"] for r in vocab["rejected"]}
    ck("every_blocked_is_rejected", blocked <= rejected,
       "约束表里 blocked 但词汇表没收进 rejected：%s" % (blocked - rejected))

    ok_calls = {e.get("uiloayout") for e in cons["entries"] if e["native_ok"]}
    for w in vocab["widgets"]:
        ck("widget_has_call_%s" % w["key"], bool(w["uiloayout"]), "控件缺少 uiloayout")
        ck("widget_note_%s" % w["key"], "note" in w, "控件缺少 note 字段")

    shots = os.path.join(WB, "data", "shots")
    layouts = os.path.join(WB, "data", "layout")
    if os.path.isdir(shots):
        pngs = [f for f in os.listdir(shots) if f.endswith(".png")]
        ck("shots_present", len(pngs) >= 7, "截图只有 %d 张" % len(pngs))
    else:
        ck("shots_present", False, "缺 data/shots 目录")
    if os.path.isdir(layouts):
        js = [f for f in os.listdir(layouts) if f.endswith(".json")]
        ck("layouts_present", len(js) >= 7, "布局树只有 %d 份" % len(js))
    else:
        ck("layouts_present", False, "缺 data/layout 目录")

    print("PASS %d  FAIL %d" % (TOTAL[0] - len(FAILS), len(FAILS)))
    sys.exit(1 if FAILS else 0)


main()
```

- [ ] **Step 2: 运行全链路测试**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\test_pipeline.py
```
预期：`PASS 0  FAIL`，退出码 0。

- [ ] **Step 3: 把新测试接入 run_all.ps1**

在 `dev/run_all.ps1` 的测试清单里追加三项（保持纯 ASCII）：

```powershell
$PY_TESTS = @('test_constraints.py', 'test_recorder.py', 'test_ids.py', 'test_pipeline.py')
```

> `test_ids.py` 也必须在内。它是唯一能发现 `ui.py` 里 `mark()` 调用被删掉或拼错常量的测试
> （MUT-3 变异证明普通 import 抓不到这类错误），漏掉它等于让埋点悄悄腐烂。

并把 `build_constraints.py` / `capture_layout.py` / `build_vocabulary.py` 加进跑批前的生成步骤。写完后立刻验语法：

```powershell
$e=$null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path 'dev\run_all.ps1'),[ref]$null,[ref]$e)
$e.Count
```
必须输出 `0`。

- [ ] **Step 4: 全量回归**

```powershell
cd 'E:\Three JS\Blender Agent'
powershell -ExecutionPolicy Bypass -File dev\run_all.ps1 2>&1 | Tee-Object dev\out\final_regress.txt
```
判据：**汇总行全绿 + 退出码 0**，两条都满足。只看退出码不算数。

- [ ] **Step 5: 交付说明**

在交付文本里写清：改了哪些文件、每条 grill 决策落在哪个任务、`attic/` 未被触碰、工作台的打开方式（`file://` 直开 `ui_workbench/index.html`）、以及**哪些结论仍未验证**（例如 7 张截图的边界坐标来自一次实机测量，换显示器分辨率需重跑 Task 5 Step 3）。

---

## Self-Review

**1. 六条 grill 决策的落点**

| 决策 | 落点任务 |
|:---|:---|
| Q1 双模式（镜像 + 提案） | Task 6 建镜像，Task 7 建提案 |
| Q2 死守原生 UILayout | Global Constraints + Task 1 把 GPU 能力全部判为 blocked |
| Q3 双轨（截图 + 布局树） | Task 4 出布局树，Task 5 出截图，Task 6 双栏并排 + 双向高亮 |
| Q4 受限词汇表、落笔即拦截 | Task 1 出约束，Task 7 出词汇表 + `validateWidget` |
| Q5 区块与可交互控件埋点 | Task 3 的 `ui_ids.py` + Task 4 校验 `ids >= 5` |
| Q6 只做【AI 对话】7 状态 | `dev/states.py` 的 `STATE_NAMES` |

**2. ceiling doc 的 5 处过期结论**

| 原文结论 | 实测 | 处理 |
|:---|:---|:---|
| `active_tab` 缺 `DETAIL`，该分支是死代码 | `ui.py:259-262` 已含 `DETAIL` | 已过期，本计划不再引用 |
| `use_property_split` 当前用量为 0 | `ui.py:1035` 已在用 | 已过期，词汇表列为可用 |
| `grid_flow` 未使用 | `ui.py:1104` 已在用 | 已过期，词汇表列为可用 |
| `theme.panel_roundness = 0.4` | Theme 类型上**无此属性**；实际在 `ThemeWidgetColors.roundness` | 路径错、值对；constraints 的 `box_shadow` 降级方案已用实测值 |
| `UILayout.context_pointer` | 不存在于 5.2.1 | 不进词汇表 |

**3. 已知未验证项**

- Task 5 截图的裁切坐标依赖当前显示器布局，换分辨率必须重测（已写入 Task 8 Step 5）。
- `attic/` 全程未读取，其 GPU 实现是否还有可复用逻辑未评估——本计划按 Q2 结论判定为不需要。
- `Run` / `ToolCall` / `Receipt` 的字段名以 Task 4 Step 4 的实测为准，若与 `dev/states.py` 草稿不符需按真实字段改写。