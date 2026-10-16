# 提案视图积木化 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把提案视图从「只能追加的表单」改成「纵向积木画布」——积木可拖拽排序、可删除、可复制；空态与控件架改成拖拽语言，让第一次打开就知道怎么用。

**Architecture:** 给每个积木一个**稳定 `uid`**，DOM 定位从数组下标（`data-idx`）改为 `uid`（`data-uid`）。所有编辑操作（删除/复制/重排）只改 `proposal` 数组，然后统一走一次 `renderCanvas()`；焦点还原改为按 uid 查找。拖拽用原生 HTML5 `draggable` + `dragover` 放置指示线，不引第三方库。

**Tech Stack:** 纯前端 HTML/CSS/JS（零依赖、零构建、`file://` 直开）· 无头 Edge 驱动的既有测试设施

## Global Constraints

- **零依赖、零构建**：`ui_workbench/index.html` 必须能 `file://` 双击直开。禁止 CDN / npm / 框架 / 外部字体 / 拖拽库。
- **★ 配色只许取自 `ui_workbench/native_api.json` 的实测值**。`dev/test_workbench_data.py` 的 `colors_from_native` 每次跑测试都会扫 `style.css`，新写的 CSS 会被强制校验。**实测色板里没有红色也没有绿色**（主题里有但 Python 的 `ThemeWidgetColors` 读不到），所以「删除」这类危险操作**不能靠红色表达**，要用删除线 / 虚线框 / 明度差。
- **★ `rc=0` 是假绿**；测试脚本必须打印 `PASS <n>  FAIL <m>` 并 `sys.exit(1 if FAILS else 0)`。**异常不能吞掉汇总行。**
- **★ 断言必须非空洞**——每条关键断言补变异验证，且**变异必须直接打在被测逻辑上**，不能只做源级推断（上一轮就栽过：源级证明「源能区分」，但断言本身写成了列表成员判断，恒假且恒红）。
- **★ 改含中文的文件禁用字节级读写**；落盘自检 NUL 为 0。
- **不引入 pip 依赖。全程不开 GUI，不启动 Blender。** 无头 Edge 由测试自己拉起是允许的。
- **既有行为不许回归**：焦点保持（`captureFocus`/`restoreFocus`）、参数拦截（`checkProp` 两级判定）、9 条降级方案、`unmapped_ok` 提醒、配色规则、四条无头钩子（`#proposal-all` / `#proposal-blocked` / `#proposal-typing` / `#proposal-empty`）——全部必须继续工作。
- **文件所有权**：Task 9 = `ui_workbench/app.js`、`dev/test_proposal_vocab.py`；Task 10 = `ui_workbench/app.js`、`ui_workbench/style.css`、`dev/test_proposal_vocab.py`。**不要碰 `ui_workbench/data/` 下的任何产物**（`constraints.json` / `vocabulary.json` / `data.js` / `data/layout/` / `data/shots/`），它们是正确的。

## File Structure

| 路径 | 责任 |
|:---|:---|
| `ui_workbench/app.js` | 提案视图全部逻辑：积木数组、渲染、编辑操作、拖拽 |
| `ui_workbench/style.css` | 积木列视觉：拖拽手柄、放置指示线、编辑按钮、空态引导 |
| `dev/test_proposal_vocab.py` | 提案视图的无头 DOM 验收 + 变异验证 |

---

### Task 9: 积木稳定身份 + 删除 + 复制

**Files:**
- Modify: `ui_workbench/app.js`（`addWidget` / `addRejected` / `renderCanvas` / `captureFocus` / `restoreFocus` / `paramsInputOf`）
- Modify: `dev/test_proposal_vocab.py`

**Interfaces:**
- Produces:
  - `uidSeq` 模块级计数器 + `nextUid() -> string`（形如 `b1`、`b2`……单调递增，不复用）
  - `proposal[]` 每个条目新增 `uid` 字段
  - `moveNode(fromIdx, toIdx) -> void`、`dupNode(idx) -> void`、`delNode(idx) -> void`
  - DOM 约定：积木根元素 `class="pnode"` 且带 `data-uid`；`data-idx` **仅保留为调试用**，不再用于任何定位

- [ ] **Step 1: 写失败测试**

在 `dev/test_proposal_vocab.py` 的 `dom_checks()` 里追加（先想清楚断言要钉什么，再写）：

```python
    # --- 删除 ---
    dom_del_button = slices(p, "canvas").count('data-act="del"')
    ck("dom_del_button_per_node", dom_del_button == node_count(p, "canvas"),
       "每个积木都要有一个删除按钮，实际 %d / 共 %d 块" % (dom_del_button, node_count(p, "canvas")))
    # 点最后一个积木的删除 -> 少一块
    ck("dom_delete_removes_one", del_last_node(p) is True, "删除后块数应减一")
    ck("dom_delete_no_uid_reuse", del_last_node_then_check_uid(p) is True,
       "删掉中间一块后，后面的积木 uid 不能被重排挤掉")
    # --- 复制 ---
    ck("dom_dup_button_per_node", slices(p, "canvas").count('data-act="dup"') == node_count(p, "canvas"),
       "每个积木都要有一个复制按钮")
    ck("dom_dup_adds_one", dup_last_node(p) is True, "复制后块数应加一")
    ck("dom_dup_gets_new_uid", dup_gets_distinct_uid(p) is True,
       "复制的积木必须是新 uid，否则焦点和标注会串到原块上")
```

> `p` 是 headless `--dump-dom` 得到的文本；上面这些 helper 你需要自己按现有 `slices()` 的写法实现。若某些断言必须靠 DOM 结构而非文本才能判定，说明该断言选错了层——换断言，不要放宽。

- [ ] **Step 2: 运行测试，确认失败**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\test_proposal_vocab.py
```
预期：新增断言 FAIL，退出码非 0。**看汇总行，不要只看退出码。**

- [ ] **Step 3: 给积木加稳定 uid**

在 `ui_workbench/app.js` 模块顶部加：

```javascript
var uidSeq = 0;

function nextUid() {
  uidSeq += 1;
  return "b" + uidSeq;
}
```

`addWidget` 与 `addRejected` 各自 `push` 的对象里加 `uid: nextUid(),`。**注意 `addRejected` 也要加**——降级项同样是积木，同样会被删除和排序。

- [ ] **Step 4: 定位从 idx 改为 uid**

三处，全部改成按 `data-uid` 查：

- `captureFocus()` — 返回 `{uid, field, start, end}`；查找改为 `host.querySelector('.pnode[data-uid="' + af.dataset.uid + '"]')`；对应 input 上的 `dataset.uid` 由渲染时写入。
- `restoreFocus()` — 同上，用 `keep.uid`。
- `paramsInputOf(wkey)` — 先按 `wkey` 在数组里找到下标 `i`，再取 `proposal[i].uid`，用 `[data-uid="..."] [data-field="params"]` 查。

渲染时给每个 input 写 `data-uid`；`.pnode` 根元素写 `data-uid`；**`data-idx` 保留但仅作调试**。

- [ ] **Step 5: 加删除与复制**

```javascript
function delNode(idx) {
  proposal.splice(idx, 1);
  renderCanvas();
}

function dupNode(idx) {
  var src = proposal[idx];
  var copy = {};
  for (var k in src) { if (src.hasOwnProperty(k)) { copy[k] = src[k]; } }
  copy.uid = nextUid();          // 新块必须是新身份，否则焦点/标注会串到原块
  proposal.splice(idx + 1, 0, copy);
  renderCanvas();
}
```

在 `renderCanvas()` 的每块积木里加两个按钮：`data-act="del"` 与 `data-act="dup"`。**不要用红色表示删除**（实测色板里没有红）——用删除线标题 + 虚线框，和 `renderRejected` 已有的表达保持一致。复制按钮沿用普通按钮样式。

- [ ] **Step 6: 变异验证**

- 变异 1：把 `copy.uid = nextUid()` 改成 `copy.uid = src.uid` → `dom_dup_gets_distinct_uid` 必须红
- 变异 2：把 `delNode` 里的 `splice(idx, 1)` 改成 `splice(idx + 1, 1)` → `dom_delete_removes_one` 必须红
- 变异 3：把 `captureFocus` 的 `data-uid` 改回 `data-idx` → **打字测试必须红**（`dom_typing_*` 那组；这条证明身份切换真的生效了）

- [ ] **Step 7: 跑全部套件并提交**

```powershell
cd 'E:\Three JS\Blender Agent'
python dev\test_proposal_vocab.py
python dev\test_workbench_data.py
python dev\test_pipeline.py
powershell -ExecutionPolicy Bypass -File dev\run_all.ps1
```
四条都要 `FAIL 0`、退出码 0。

---

### Task 10: 拖拽排序 + 空态引导

**Files:**
- Modify: `ui_workbench/app.js`（`renderCanvas`）
- Modify: `ui_workbench/style.css`
- Modify: `dev/test_proposal_vocab.py`

**Interfaces:**
- Produces:
  - `dragState` 模块级：`{uid: string|null, fromIdx: int|null}`
  - DOM 约定：每块积木根元素 `draggable="true"`；列容器 `#canvas` 监听 `dragover` / `drop`；放置指示线用一个独立元素 `.drop-line`
  - `reorderTo(fromIdx, toIdx) -> void` — 纯数据操作，供拖拽与测试共用

- [ ] **Step 1: 写失败测试**

```python
    ck("dom_draggable_nodes", slices(p, "canvas").count('draggable="true"') == node_count(p, "canvas"),
       "每块积木都要能拖")
    ck("dom_drop_line_present", 'class="drop-line"' in p, "缺少放置指示线元素")
    # 纯数据层的重排，验证语义而不是模拟鼠标
    ck("dom_reorder_semantics", reorder_check(p) is True,
       "从第 3 块拖到第 1 位后，顺序必须是 [3,1,2] 且 uid 全部保留")
    # 拖拽不得让 uid 变化——否则标注会串
    ck("dom_reorder_keeps_uid", reorder_keeps_uid(p) is True, "重排不能改写任何 uid")
```

`reorder_check` / `reorder_keeps_uid` 需要在 Python 侧重演一次 `reorderTo` 的语义（从 `app.js` 源码取算法，和 `test_pipeline.py` 里已有的做法一致）。**若你认为某条断言无法脱离浏览器判定，改断言，不要标成 SKIP。**

- [ ] **Step 2: 运行测试，确认失败**

- [ ] **Step 3: 实现 `reorderTo`**

```javascript
/* 把 fromIdx 移到 toIdx。toIdx 是「放在删除源之后」的目标位置，
   语义与 UIList/Array.splice 的常见用法一致，先取出再插入。 */
function reorderTo(fromIdx, toIdx) {
  if (fromIdx === toIdx || fromIdx < 0 || fromIdx >= proposal.length) { return; }
  var item = proposal.splice(fromIdx, 1)[0];
  var at = toIdx > fromIdx ? toIdx - 1 : toIdx;
  proposal.splice(at, 0, item);
  renderCanvas();
}
```

**只动数组顺序，绝不重建 uid。** 这是标注不串的前提。

- [ ] **Step 4: 拖拽交互**

- 每块 `.pnode` 设 `draggable="true"`
- `dragstart` 记 `{uid, fromIdx}`，给该块加一个 `.dragging` 类（半透明）
- 列上 `dragover` 时 `preventDefault()`，计算插入位置并移动 `.drop-line` 到对应位置
- `drop` 时调用 `reorderTo`，并清掉指示线
- `dragend` 无论成败都要清干净：`dragState = null`、移除 `.dragging`、移除 `.drop-line`。**漏掉这一步会让画布卡在拖拽态**，这是最容易出的 bug。

用原生 `dragstart` / `dragover` / `drop` / `dragend`，**不要引拖拽库**（违反零依赖约束）。

- [ ] **Step 5: 样式**

新增 `.drop-handler`（积木左侧的拖拽手柄）、`.drop-line`（放置指示线）、`.pnode.dragging`。**所有颜色取自 `native_api.json` 实测值**，`style.css` 顶部已有完整清单与来源注释，照它取。

- [ ] **Step 6: 空态改成拖拽语言**

现在的空态写的是「从上面挑控件开始拼装」——它在教人用表单。改成同时讲清两条路径，并点明积木可以拖：

```javascript
p.textContent = "把左边的控件拖进来，或者直接点它。" +
  "积木从上到下的顺序，就是插件里面板从上到下的顺序——可以随时拖动换位、" +
  "复制一块、或删掉重来。搭好后切回镜像视图，对着真实截图比。";
```

控件架（`renderVocabBar`）的按钮加一句提示，同样说明「可拖可点」。

- [ ] **Step 7: 变异验证**

- 变异 1：`reorderTo` 里 `at` 的计算去掉 `-1` → `dom_reorder_semantics` 必须红
- 变异 2：`reorderTo` 改成重建 uid → `dom_reorder_keeps_uid` 必须红
- 变异 3：删掉 `dragend` 的清理 → 至少一条断言必须红（若没有，说明这条断言没钉住东西，补上）

- [ ] **Step 8: 跑全部套件并提交**

四条命令同 Task 9 Step 7。

---

## Self-Review

**覆盖对照**：删除 ✓（Task 9）· 复制 ✓（Task 9）· 拖拽排序 ✓（Task 10）· 纵向积木列 ✓（形态已如此，本轮改造的是它的编辑能力与表达）· 可发现性 ✓（Task 10 Step 6）· 嵌套 / 实时预览 / 代码导出 —— 用户明确不做，不在计划内。

**已知不覆盖**：拖拽在触屏设备上的表现。HTML5 draggable 在触屏上不可靠，本计划只保证鼠标。若日后需要触屏，得另做长按方案。