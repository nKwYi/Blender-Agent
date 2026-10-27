# Blender DeepSeek Agent 全量深度测评与可执行改造计划

> [!IMPORTANT]
> 本报告基于对 [`blender_deepseek_agent`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/__init__.py) 全部 10 个核心源码文件（共 **3,421 行代码**）的逐行静态审计、Blender 5.2 N-Panel 真实渲染契约核验以及多轮端到端交互实测生成。文档后半部分为**可直接勾选执行的分阶段改造清单（Executable Action Plan）**。

---

## 一、 全量测评总览与评分矩阵

| 测评维度 | 当前评分 | 核心优势 | 核心短板 / 风险点 |
| :--- | :---: | :--- | :--- |
| **1. 并发与线程安全** | **8.5 / 10** | [`worker.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/worker.py#L226-L336) 采用「后台线程负责 LLM HTTP + `Queue` 投递、`bpy.app.timers` 主线程串行消费 `bpy` 操作」的架构，严格遵守 Blender 主线程铁律。 | [`DEEPSEEK_OT_fetch_models.execute`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L766) 在主线程同步请求网络且超时设为 `cfg["timeout"]`（600秒），断网时会导致 Blender 假死 10 分钟。 |
| **2. 交互体验 (UX)** | **6.2 / 10** | 具备「先问后建 / 直接生成」双模式切换、胶囊状态栏、Blender 5.2 原生多行 `textbox` 输入框。 | 1. **追问多选题点选第1题即刻触发发送**，无法选完第2/3题再提交；<br>2. **AI 卡片充斥「伪折叠按钮」噪音**，且热更新不重载算子时按钮全部失效；<br>3. 历史记录仅显示 3 条且无翻页按钮；<br>4. 用户长消息仍在 `split` 内违规使用 `ubox.panel()`。 |
| **3. 工具与回退可靠性** | **6.5 / 10** | [`receipt.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/receipt.py#L6-L86) 对场景对象快照差异（Delta）与修改前 Undo 锚点做了账本记录。 | 1. [`DEEPSEEK_OT_undo_task`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L560) 调用了不存在的 `CONTROLLER.stop()`（实际方法名为 [`request_stop()`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/worker.py#L338)）；<br>2. 回退仅删 `Object`，遗留大量孤立 `NodeGroup`/`Material`/`Mesh` 数据块；<br>3. [`_EXEC_G`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/tools.py#L176-L202) 全局字典跨任务污染。 |
| **4. 提示词与几何节点路由** | **8.8 / 10** | [`agent.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/agent.py#L12-L90) 内置「几何节点（Geometry Nodes）三维四步决策树」与混合搭建管线规范，防报错铁律完善。 | 追问输出格式未严格限制废话段落，导致 [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L971-L1084) 需要靠复杂的正则去清洗与兜底。 |
| **5. 代码质量与可维护性** | **6.0 / 10** | [`state.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/state.py)、[`receipt.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/receipt.py)、[`ui_ids.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui_ids.py) 解耦清晰，具备 headless 渲染契约测试基础。 | 1. [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py) 单文件膨胀至 **1,826 行**，含 12+ 个未使用的 v1/v2 僵尸属性；<br>2. [`get_config()`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L190-L219) 在 `draw()` 渲染期间强写 Preferences 属性，锁死用户自定义超时设置。 |

---

## 二、 交互体验（UX）深度剖析与痛点定位

### UX-1：AI 回复卡片的「折叠按钮噪音」与热更新失效问题
- **代码定位**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1160-L1289)、[`parse_interactive_options`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L971-L1084)
- **问题复盘**：
  1. **为什么之前点击折叠按钮完全没反应？**
     当在 [`DEEPSEEK_PG_msg`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L204-L207) 新增 `show_steps`/`show_analysis` 属性并新增 [`DEEPSEEK_OT_toggle_ai_detail`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L779-L809) 算子后，若仅同步文件或仅重载模块而未触发 Blender 重新执行 `bpy.utils.unregister_class` + `register_class`，运行中的 Blender RNA 树中根本不存在该算子与布尔属性，按钮渲染出来即是无响应的死按钮。
  2. **更本质的交互痛点：「折叠按钮本身就是视觉噪音」**
     在狭窄的 3D 视口 N-Panel 侧边栏中，用户只关心两件事：**① 追问时让我快速选规格；② 建模后告诉我建了什么、耗时多少**。把 AI 的思考套话变成 `▶ 查看方案分析与说明（8项）`、`▶ 查看补充参数与技术细节`、`▶ 执行了 3 项建模操作` 等一排排折叠按钮，不仅霸占纵向空间，而且用户根本不会在主聊天流里点开阅读。
- **改造标准**：
  - **主对话气泡（`CHAT` 页签）彻底零折叠按钮**：
    - **追问态（Clarify）**：仅展示 **1 句精简导语 + 问题选项按钮组 + 底部提交主按钮**，彻底丢弃「方案分析」「补充参数」等废话块。
    - **交付态（Execute）**：仅展示 **1 行完成状态与耗时（如 `已完成 · 3 步 · 4.2s`）+ 1 句核心结果摘要 + 最多 6 个新增对象胶囊标签**。
  - **所有中间步骤与完整原文统一归口至顶部 `详情 (DETAIL)` 页签**：主对话卡片底部仅提供一个轻量的 `查看执行详情 →` 跳转入口（切换 `state.ui_tab = 'DETAIL'`）。

---

### UX-2：多问题追问「点选第 1 题即刻触发建模」的严重交互缺陷
- **代码定位**：[`DEEPSEEK_PT_main.draw`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1219-L1260) 与 [`DEEPSEEK_OT_submit_selection`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L837-L866)
- **问题复盘**：
  当 AI 在「先问后建」模式下提出 2~3 个细节问题（例如：`细节1：桌面材质`、`细节2：桌腿形态`）时，[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1238-L1240) 把每个选项按钮都绑定到了立即发送算子：
  ```python
  btn = q_col.operator("deepseek.submit_selection", text=btn_txt, icon=btn_icon)
  btn.custom_prompt = f"针对「{q_title}」，我选择：{val}。其余细节请按你的推荐方案直接开始建模。"
  ```
  导致**用户刚点选「细节 1」的选项 A，插件就立刻向 LLM 发送请求开始建模了，用户根本没有机会去选「细节 2」和「细节 3」！**
  更讽刺的是，代码里明明已经写了 [`DEEPSEEK_OT_select_option`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L811-L834) 和 `state.selected_options_json` 字典存储逻辑，却在 UI 渲染时完全弃用！
- **改造标准**：
  ```mermaid
  sequenceDiagram
      participant U as 用户 (N-Panel)
      participant S as state.selected_options_json
      participant O as DEEPSEEK_OT_submit_selection
      participant W as Worker 后台线程

      Note over U,S: 渲染追问卡片时，若某题未选，默认高亮推荐项 (is_rec=True)
      U->>S: 点击「细节1 - 选项B」 (调用 deepseek.select_option)
      S-->>U: 更新 JSON 映射，按钮切换为 depress=True 高亮勾选态 (不发送请求)
      U->>S: 点击「细节2 - 选项A」 (调用 deepseek.select_option)
      S-->>U: 更新 JSON 映射，实时预览已选组合
      U->>O: 点击底部主按钮「按所选方案开始建模」
      O->>W: 汇总所有题目的选择（未手动点的取推荐项）一次性 dispatch_run_prompt
  ```

---

### UX-3：用户长提示词仍在 `split` 列内违规调用 `ubox.panel()`
- **代码定位**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1122-L1133)
- **问题复盘**：
  之前已证实 Blender 5.2 的 `UILayout.panel()` 在 `split()` 或 `box()` 内部闭合时，其 C++ 布局栈会逃逸吞噬后续所有顶层 UI 控件（导致输入框和底部按钮全部被折叠消失）。
  虽然我们在 AI 气泡中移除了 `panel()`，但**用户气泡（`USER` 分支）第 1124 行仍然保留了 `up_h, up_b = ubox.panel(p_id, default_closed=False)`**！一旦用户输入的提示词超过 3 行并手动点击了用户气泡上的折叠小箭头，整个插件下方的聊天记录与输入框依然会瞬间消失！
- **改造标准**：
  - 彻底删除 [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1124) 的 `ubox.panel()` 调用，并将 [`check_layout_contract()`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1804-L1807) 中的断言升级为：**严禁在 `ui.py` 任何位置调用 `.panel(`**。

---

### UX-4：历史对话只显示 3 条（1.5 轮），且无翻页/展开控件
- **代码定位**：[`config.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L135-L138)、[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1106-L1110)
- **问题复盘**：
  `history_page` 默认值仅为 `3`（即「用户问 1 句 + AI 追问 1 句 + 用户答 1 句」后，第 1 句就被隐藏了），且顶部只画了一行灰色死文字 `... 上方已折叠更早的 N 条历史 ...`，没有任何按钮可以展开查看。
- **改造标准**：
  - 将默认显示条数提升至 `6` 条（3 轮完整对话）；
  - 当存在更早历史时，将顶部的死文字替换为可点击的轻量化按钮：`↑ 展开更早的 N 条对话` / `↑ 收起早期对话`。

---

## 三、 代码质量与架构深度审计（含行号定位）

### CQ-1：[`DEEPSEEK_OT_undo_task`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L541-L630) 存在致命方法名拼写错误与数据块泄漏
1. **调用了不存在的 `CONTROLLER.stop()` 方法**：
   - 在 [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L560) 中：
     ```python
     if state.busy:
         try:
             CONTROLLER.stop()
         except Exception:
             pass
     ```
   - 核查 [`worker.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/worker.py#L226-L355) 中的 `Controller` 类，**根本没有定义 `stop()` 方法**，正确的方法名是 [`CONTROLLER.request_stop()`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/worker.py#L338)！由于被 `except Exception: pass` 静默吞掉，当任务正在运行而用户点击「回退操作」时，后台线程根本没有收到停止信号，会在回退后继续往场景里创建物体！
2. **孤立数据块（Orphan Data）泄漏**：
   - [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L579-L588) 回退时仅遍历 `run.receipt.created_objects` 删除了 `bpy.data.objects`，但 Geometry Nodes 代码创建的 `bpy.data.node_groups`、`bpy.data.materials`、`bpy.data.meshes` 全部残留在 `.blend` 文件中。应在删除对象后调用 `bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)` 或基于快照清理新增数据块。
3. **`can_undo(state)` 与 `poll()` 逻辑不一致**：
   - [`can_undo(state)`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1745-L1747) 仅在 `run.receipt.boundary_pushed` 为真时返回 `True`，导致纯对话追问轮次无法通过底部按钮撤回上一条消息。

---

### CQ-2：[`config.py:get_config()`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L190-L219) 在渲染循环中违规篡改用户配置
- **代码定位**：[`config.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L191-L218)
  ```python
  raw_timeout = int(p.timeout) if p else 600
  if p and raw_timeout < 600:
      try:
          p.timeout = 600
      except Exception:
          pass
  ```
- **严重后果**：
  1. `get_config()` 在每次 UI 面板刷新（`draw()`）时都会被调用。在 Blender 的 `draw()` 上下文中修改 RNA 属性属于违规操作。
  2. 更严重的是，[`DeepSeekPreferences`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L118-L131) 明明允许用户设置 `timeout`（`min=1, max=3600`）和 `max_turns`（`min=1, max=64`），但因为这段硬编码拦截，**用户只要在设置界面把超时改成 60 秒或把轮数改成 8 轮，下一帧 `draw()` 就会强行把它改回 600 和 16**，导致设置滑块形同虚设！
- **修复方案**：移除 `get_config()` 中所有反向写回 `p.timeout` / `p.max_turns` / `p.wall_budget` 的副作用代码，仅修改属性定义处的 `default` 默认值。

---

### CQ-3：[`DEEPSEEK_OT_fetch_models`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L745-L777) 主线程 600 秒同步阻塞风险
- **代码定位**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L766)
  ```python
  models = fetch_available_models(cfg["api_key"], cfg["base_url"], timeout=cfg["timeout"])
  ```
- **严重后果**：`cfg["timeout"]` 默认为 **600 秒**。当用户在偏好设置点击「刷新模型列表」且 API 地址填写错误或网络不通时，`urllib.request.urlopen` 会在 Blender 主线程同步阻塞整整 10 分钟，期间整个 Blender 窗口白屏未响应。
- **修复方案**：将模型列表拉取的 `timeout` 严格限制为 `min(int(cfg["timeout"]), 8)` 秒（最多 8 秒快速失败），消除长阻塞风险。

---

### CQ-4：[`tools.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/tools.py#L176-L202) 中 `_EXEC_G` 全局命名空间污染与悬空引用
- **代码定位**：[`tools.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/tools.py#L176-L209)
- **问题复盘**：
  `_exec_globals()` 返回的是同一个模块级字典 `_EXEC_G`。AI 在第 1 次任务中定义的全局变量（例如 `obj = bpy.data.objects['Cube']` 或自定义辅助函数）会一直残留在 `_EXEC_G` 中。当该物体在后续被删除或回退后，`_EXEC_G` 中仍持有指向已释放 Blender C 结构体（`StructRNA of type Object has been removed`）的悬空引用，极易引发后续脚本离奇崩溃。
- **修复方案**：每次调用 `handle_execute_code()` 时，基于基础导入模板构造独立的 `scope = dict(_BASE_EXEC_GLOBALS)` 浅拷贝字典执行 `exec(code, scope)`，杜绝跨任务残留。

---

### CQ-5：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py) 1,826 行巨石文件与 12+ 个僵尸属性清理
- **代码定位**：[`DEEPSEEK_PG_state`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L353-L378)、[`DEEPSEEK_PG_note`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L211-L213)、[`ensure_notes`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L899-L910)
- **问题复盘**：
  经过 v0.1 → v0.4 的多次迭代，`DEEPSEEK_PG_state` 中堆积了 **13 个完全不再被任何 UI 绘制代码引用的废弃属性**：
  - `show_card_objects`、`show_card_params`、`show_card_script`、`show_card_archive`、`show_card_qa`、`show_user_params_detail`
  - `result_tab`、`show_result_list`、`show_all_questions`、`other_open_q`
  - `notes` (`CollectionProperty(type=DEEPSEEK_PG_note)`)、`shown_count`、`page`
- **修复方案**：彻底清理上述僵尸 RNA 属性与 `DEEPSEEK_PG_note` 类，减轻 `Scene.deepseek_state` 序列化负担。

---

## 四、 分阶段可执行改造计划（Executable Action Plan）

### Phase 1 (P0)：核心交互重塑与致命 Bug 清零
- [ ] **Task 1.1：修复追问多选题「点选即发送」Bug，实现真正的多题组合选择**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L811-L866) 与 [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1219-L1260)
  - **执行动作**：
    1. 将追问卡片中每个选项按钮绑定的算子从 `deepseek.submit_selection` 改为 `deepseek.select_option`，传入 `question` 与 `option`；
    2. 若某题尚未在 `state.selected_options_json` 中记录，默认将 `is_rec=True`（或第 1 项）作为当前选中态，渲染 `depress=True` 高亮样式与 `CHECKBOX_HLT` 图标；
    3. 底部统一渲染 1 个主提交按钮 `按所选方案开始建模`（绑定 `deepseek.submit_selection`，自动汇总所有题目的当前选中项发送给 AI）。
- [ ] **Task 1.2：砍掉主对话流（CHAT）所有「伪折叠按钮」噪音，极简化 AI 气泡**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1160-L1289)
  - **执行动作**：
    1. 移除主对话气泡中的 `查看方案分析与说明`、`查看补充参数与技术细节`、`执行了 N 项建模操作`、`查看完整说明` 折叠按钮；
    2. **追问气泡**仅保留：1 句精炼导语 + 多题选项按钮组 + 底部「按所选方案开始建模」主按钮；
    3. **交付气泡**仅保留：顶部完成状态行（`已完成 · N 步 · X.Xs`）+ 1 句核心结果摘要 + 新增场景对象胶囊标签 + 右下角轻量跳转按钮 `查看执行详情 →`（点击切换至 `DETAIL` 页签查看完整步骤与输出）。
- [ ] **Task 1.3：根除用户气泡中的 `ubox.panel()` 折叠逃逸隐患，并提供历史记录展开按钮**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1106-L1135)、[`config.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L135-L138)
  - **执行动作**：
    1. 删除 [`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1124) 的 `ubox.panel()`，长用户消息采用纯文本折行展示；
    2. 将默认历史显示条数从 `3` 提升为 `6`，并在顶部提供 `↑ 展开全部 N 条历史记录` / `↑ 收起早期历史` 切换按钮。
- [ ] **Task 1.4：修复 `DEEPSEEK_OT_undo_task` 方法名错误与孤立数据块清理**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L541-L630)
  - **执行动作**：
    1. 将 `CONTROLLER.stop()` 修正为 `CONTROLLER.request_stop()`；
    2. 删除本次创建的 `Object` 后，调用 `bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)` 自动清理孤立的 Geometry Nodes 节点组、材质与网格数据块；
    3. 统一 `can_undo(state)` 与 `DEEPSEEK_OT_undo_task.poll()` 的判断条件，支持在追问态撤回上一轮对话并恢复输入框提示词。

### Phase 2 (P1)：代码质量与运行安全加固
- [ ] **Task 2.1：移除 `get_config()` 在 `draw()` 中的强写副作用**
  - **目标文件**：[`config.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/config.py#L190-L219)
  - **执行动作**：删除 `get_config()` 中强行覆写 `p.timeout = 600`、`p.max_turns = 16`、`p.wall_budget = 1200` 的代码，尊重用户在设置面板中调小的参数。
- [ ] **Task 2.2：限制 `fetch_models` 网络超时为 8 秒，防止主线程假死**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L766)
  - **执行动作**：将 `fetch_available_models(..., timeout=min(int(cfg["timeout"]), 8))` 超时上限锁定为 8 秒。
- [ ] **Task 2.3：隔离 `tools.py` 的代码执行命名空间 `_EXEC_G`**
  - **目标文件**：[`tools.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/tools.py#L176-L215)
  - **执行动作**：每次执行代码时基于基础环境字典生成干净副本，防止跨任务残留已删除 Blender 对象的悬空引用。

### Phase 3 (P2)：僵尸代码清理、热重载机制与自动化契约验收
- [ ] **Task 3.1：清理 `DEEPSEEK_PG_state` 中的 13 个僵尸属性与死代码**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L200-L380)、[`__init__.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/__init__.py)
  - **执行动作**：移除 `DEEPSEEK_PG_note`、`ensure_notes` 及 `show_card_*` 等 13 个未使用的属性，并在 [`__init__.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/__init__.py) 中完善模块 `importlib.reload` 支持，确保开发态重载插件时所有新算子与 RNA 属性100%重新注册。
- [ ] **Task 3.2：升级 `check_layout_contract()` 并在 Blender 5.2 无头模式下执行全量契约验收**
  - **目标文件**：[`ui.py`](file:///e:/Three%20JS/Blender%20Agent/blender_deepseek_agent/ui.py#L1799-L1826)
  - **验收命令**：
    ```powershell
    & "D:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python test_plugin_audit_suite.py
    ```
  - **验收标准**：
    1. 静态契约：`ui.py` 全文零 `.panel(` 调用、零废弃属性、零未注册算子引用；
    2. 动态契约：模拟「多题追问点选切换 → 一键汇总提交 → 几何节点建模交付 → 一键回退并清理孤立节点组」全链路断言 100% 通过；
    3. 同步更新至本机 Blender 5.2 扩展目录并推送到 GitHub `main` 分支。
