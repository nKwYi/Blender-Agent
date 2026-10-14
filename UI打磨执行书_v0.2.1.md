# UI 打磨执行书 v0.2.1

**任务一句话**：把 Blender 扩展 `blender_deepseek_agent` 的 AI 面板从"功能都在但看不懂"改成"三个 tab 分流 + 说日常中文 + 任务边界清晰"。
**这份文档是自包含的**：你不需要读任何前置对话。文中每条"实测"结论都给了复核方法（见 §8），不信就跑一遍。

- 工程目录：`E:\Three JS\Blender Agent`（**路径含空格，命令必须加引号**）
- 扩展源码：`blender_deepseek_agent/`；测试脚手架：`dev/`；构建产物：`dist/`
- 当前已安装版本：**0.2.0**（已 build + install 到 `user_default` 并启用）
- 目标版本：**0.2.1**

---

## 0. 环境事实（先读，能省你半天）

- Blender **5.2.1 LTS**：`D:\blender-4.5.5-windows-x64\blender5.2\blender.exe`，内嵌 CPython 3.13.13。
- 扩展装好后导入名是 `bl_ext.user_default.blender_deepseek_agent`，**不是** `blender_deepseek_agent`。`AddonPreferences.bl_idname` 必须等于 `__package__`（现在就是这么写的，**别改回字面量**，改回去偏好设置那一栏会静默失效）。
- **`--background` 下 `bpy.app.timers` 一次都不触发**（实测等 3 秒 0 次）→ 非阻塞忙态只在 GUI 成立，无头走同步路径。**别在无头里测忙态。**
- **`--factory-startup` 会禁用所有扩展**。跑 `dev/test_*.py`（源码直注）时要加它；跑真扩展或 GUI 实测时必须去掉。
- 侧栏**滚轮不滚动**（实测：200 行 label 的面板，游标在面板内、±两个方向各滚一次，画面零变化）。任何"可滚动列表"设计都是错的 → 用分页或子面板。
- `Region.width` **只读**，脚本改不了面板宽度。只能 `Panel.bl_ui_units_x` 设最小宽度，或手拖。
- **图标名写错会让整块面板从那一行起静默截断**（控制台有 TypeError，界面上只是少半截，极易误判成"没做"）。5.2 共 1033 个图标，枚举取法：
  `bpy.types.UILayout.bl_rna.functions["operator"].parameters["icon"].enum_items`
  已知**不存在**：`PREFS`（正确是 `PREFERENCES`）、`DOC`、`NETWORK`、`TOKEN`、`FILE_TEXT`。
- `UILayout.textbox(data, "prop", initial_visible_lines=3, placeholder=…)` 存在可用；但 `StringProperty` **没有** `MULTILINE` 子类型（多行控件在布局侧，不在属性侧）。
- 本机走系统代理 `HTTP(S)_PROXY=http://127.0.0.1:7890`；代理没开时 DeepSeek 请求表现为 **502**，不是连接失败——错误文案要覆盖这一类。
- 无头 EEVEE **能**渲染几何体（有物体 48 种色 / 全隐藏 1 种色）。判"图无效"要用**颜色种类数**，不要用亮度阈值。
- 服务端会在 401 错误里**回显打码后的 API Key**（`Your api key: ****r-`）→ 任何展示/落盘路径都必须过 `config.redact()`。

## 1. 现状代码地图

| 文件 | 行 | 现在是什么 |
|:---|:---|:---|
| `blender_deepseek_agent/ui.py` | `343-478` | `DEEPSEEK_PT_panel.draw()`：一屏平铺 10 个同级 `box`，无主次 |
| 同上 | `350-361` | Provider / 模型 / Key 状态常驻主面板（正常时纯属噪音） |
| 同上 | `387-409` | 错误盒：**`PARTIAL` 也走 `ebox.alert=True`**；`404-409` 的 `g["retry"]` 被**打印两遍** |
| 同上 | `412-423` | 审批门：把原始 Python 代码逐行 `label` 铺开（最多 12 行），非程序员看不懂 |
| 同上 | `437-453` | 对话分页；按钮文案"更早 / **更新**"（会被读成"刷新"）；"导出完整转录"用 `icon='ADD'`（语义错） |
| 同上 | `461-478` | 工具调用列表 + 用量 + 上下文估算，全挤在主面板 |
| `state.py` | `PHASE_VIEW` | 10 个相位文案是工程腔（"执行工具中""核对场景差异"） |
| `worker.py` | `Controller.start()` | 每次 `messages=[system, user]` 重新起步 → **多轮上下文并未接通**，`state.history` 只是显示 |
| `worker.py` | `CONTROLLER.run` | 任务结束后不清空 → 空闲面板挂着上一次的回执/工具/用量 |

**已经是对的，别动**：网络在子线程、bpy 调用全在主线程（GUI 实测心跳 753 次期间界面可响应）；undo 边界 + `ed.undo` 真能回退；错误码分型与"四要素"齐全；Key 脱敏；无头时高风险代码直接拒绝而不是放行。

## 2. 已定的四个设计决定（不要重开讨论）

1. **分流用侧栏原生 `bl_category` 三个真 tab**：`AI 对话` / `详情` / `设置`。
2. **主面板说日常中文**；`轮次 / 工具调用 / 上下文占用 / Provider / API Key` 只允许出现在【详情】【设置】。
3. **`PARTIAL`（做到一半）用中性"已做 / 未做"两栏**，只有 `FAILED` 才允许 `alert` 红。
4. **新任务覆盖上一次痕迹**：启动新任务时，上一任务的回执/工具/用量从主面板消失（对话记录保留）。

## 3. 要做的改动

### 3.1 三个面板类（`ui.py`）

| tab | 面板类 | 内容（自上而下） |
|:---|:---|:---|
| `AI 对话` | `DEEPSEEK_PT_chat` | 状态行 → 输入 `textbox` → 执行/停止 → 审批（仅需要行动时出现）→ 变更结果 → 对话记录（分页）→ 新任务 |
| `详情` | `DEEPSEEK_PT_detail` | 工具逐步记录 → 选中项返回 JSON → 本次用量 → 完整转录文本块 → 导出 |
| `设置` | `DEEPSEEK_PT_settings` | Key 状态与来源 → 模型 → 轮次上限 → 时间预算 → 任意代码策略 → 历史条数 → 打开偏好设置 |

- 三个 `bl_category` 必须互不相同。
- 每个 tab 无内容时显示一行说明（如"还没有任务记录"），不留空白面板。
- **缺 Key 时**【AI 对话】顶部保留一行红字 + 一个跳转按钮（因为它需要用户行动）；其余 Key/模型信息全部移到【设置】。
- 现有 9 个 operator 全部保留复用，不要重写逻辑；只改归属与呈现。

### 3.2 状态文案改写（`state.py:PHASE_VIEW`）

`READY 准备好了` · `PREFLIGHT 先检查了一下` · `REQUESTING 在想怎么做…` · `TOOL_RUNNING 正在改你的场景 · 第 N 步` · `VERIFYING 在核对改了什么` · `AWAITING_APPROVAL 要你确认：它想动你的场景` · `COMPLETED 做完了` · `PARTIAL 做到一半，已停下` · `FAILED 没做成` · `STOPPED 已按你说的停下`

注意：`PHASE_VIEW` 里的图标名不是 `icon=` 字面量，**门禁要单独扫它**（现有 AST 扫描已覆盖，别退回正则）。

### 3.3 部分完成两栏（不再红色）

```
做到一半，已停下
已经做了：建了 RealCube；上了红色材质
还没做：移动到 (2,0,0)
[撤销已做的]
没做完的部分，再说一句就行
```

- "已经做了"取 `run.receipt.lines`；"还没做"取 `run.skipped` + 未执行步骤（`run.pending`）。
- **不要加"继续做完"按钮**——真续跑要多轮上下文（§4），现在给了就是假承诺。
- 容器用普通 `box` + `INFO` 图标；`alert` 只留给 `FAILED`。

### 3.4 审批块改为摘要优先

第一行说"它想运行一段 Python（N 行），会改动：Cube"，代码本身折叠（子面板或"查看代码"按钮点开）。批准/拒绝两个按钮保持现状。

### 3.5 顺手修的 5 个小毛病

1. `ui.py:404-409` retry 行重复打印 → 每个错误只出**一个**首行动作 + **一行**重试语义。
2. "更早 / 更新" → **"上一页 / 下一页"**。
3. "导出完整转录"的 `icon='ADD'` → 换成语义正确的白名单图标（先过门禁）。
4. 空闲且无 run 时，主面板不得出现上次的回执/工具/用量。
5. 对话区标题写成 **`对话记录（模型只看当前这句）`** —— 多轮还没接通，先诚实标注。

## 4. 明确不做（越界即返工）

- 不接多轮上下文、不加视口截图回传、不做视口 HUD、不做任务级快照列表。
- 不改 `worker.py` 的线程/队列协议。
- 不引入 pip 依赖（Blender 内嵌 Python 里装不了 `openai`，这是实测结论）。
- 不加登录/账号/云同步；不把对话挪到外部客户端。
- 不写 Blender 做不到的视觉：任意 RGB 颜色、字体、字号、圆角、阴影、渐变、动画、hover。可表达的只有 `box.alert`（红）与 `active/enabled`（灰）。

## 5. 涉及文件

`ui.py`（主要）· `state.py`（文案）· `worker.py`（仅"新任务清态"一处）· `config.py`（【设置】tab 直接 `layout.prop(prefs, …)`，无需新字段）· `dev/test_tools.py`（加"三 tab 分类互不相同"断言）· **新建 `dev/test_ui_copy.py`** · `dev/test_p0_contract.py` 与 `dev/test_loop_mock.py` 的断言随文案调整。

## 6. 验收（必须逐条交证据，不接受"应该可以"）

1. 无头基线 **105 项全绿**：`test_tools` 34 / `test_loop_mock` 20 / `test_http_errors` 10 / `test_p0_contract` 41。
2. 新增两项也必须绿：
   - 三个面板类均已注册且 `bl_category` 互不相同；
   - `dev/test_ui_copy.py`：断言【AI 对话】渲染出的文本行里**不含** `轮次`、`工具调用`、`上下文`、`Provider`、`API Key`；断言 `PARTIAL` 态的容器 `alert is False`。
3. 图标门禁 0 个非法名（`dev/test_tools.py` 里的 AST 扫描，含状态表）。
4. 版本升 **0.2.1** 并 `validate` + `build` + `install-file -r user_default -e` 成功。
5. **GUI 逐 tab 截图**（上一轮就漏了这步：只验了 operator 没看画面，结果交付了一个没人看得懂的界面）：
   - 空闲【AI 对话】：应只剩 4 块内容
   - 真跑 `创建一个红色立方体，移到 (2,0,0)`：中途一张"正在改你的场景 · 第 N 步"，结束一张"做完了"+ 变更结果
   - 把轮次上限设成 2 再跑同一条：一张"做到一半，已停下"，肉眼确认**不是红色**
   - 【详情】【设置】各一张
6. 错误回归：缺 Key / 401 / 断网 三种，首行动作按钮各自唯一且正确（`test_p0_contract` 已覆盖大部分）。

## 7. 命令速查（Git Bash）

```bash
B="/d/blender-4.5.5-windows-x64/blender5.2/blender.exe"
cd "E:/Three JS/Blender Agent"

"$B" --command extension validate "blender_deepseek_agent"
for f in test_tools test_loop_mock test_http_errors test_p0_contract test_ui_copy; do
  "$B" --background --factory-startup --python-exit-code 1 -P "dev/$f.py"   # 看 rc 与 RESULT 行
done

"$B" --command extension build --source-dir blender_deepseek_agent --output-dir dist
"$B" --command extension install-file -r user_default -e "dist/blender_deepseek_agent-0.2.1.zip"

"$B" -P dev/test_gui_async.py        # GUI 实测：不要加 --factory-startup
```

## 8. 想复核本文某条事实时

- 图标枚举 / `textbox` 参数 / `Panel.bl_options`：`"$B" --background --factory-startup --python-expr "..."` 打印 RNA。
- 侧栏滚不滚：注册一个画 200 行 label 的 Panel，开 GUI，游标停在面板内滚轮上下各一次，截图对比。
- 无头 timers 跑不跑：`bpy.app.timers.register(fn)` 后 `time.sleep(3)` 看 `fn` 计数（无头为 0）。
- undo 边界：先 `bpy.ops.ed.undo_push(message='x')` 再改数据，然后 `bpy.ops.ed.undo()`（**不要**带 window/area/region 的 `temp_override`，带上反而 `poll()` 失败）。
- 无头渲染是否有效：分别渲染"有物体"和"全部 hide_render"，比较**颜色种类数**而不是平均亮度。

---

## 9. 交付时请附一段"我哪条说错了"

本文由上一轮实现者撰写，其中的行号、基线数字（105 项）、"已实测"结论都可能已经过期或本身就是错的。**发现与代码/实机不符的地方，请在交付说明里逐条列出并改正本文**，不要静默迁就。
