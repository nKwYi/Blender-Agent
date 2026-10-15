# -*- coding: utf-8 -*-
"""从 constraints.json 生成受限词汇表。

原则：只有 native_ok=true 的能力才能进词汇表；每条 native_ok=false 的
能力都要产出一条 rejected 项，带着降级方案，提案视图据此拦截。

这两条原则是**被强制**的，不是注释里的许诺：
  * 每个 widget 用 constraint_key 声明它实现的是 constraints.json 里哪一条
    native_ok=true 能力；build() 会拿 reg 去核对，那条一旦被翻成 false
    就直接抛错停下来，而不是继续悄悄提供它。
  * 每条 native_ok=true 但没有任何 widget 映射的能力，落到 unmapped_ok 里，
    提案视图会单列一行「可做但词汇表尚未收录」。漏掉的能力不许无声消失
    （progress_bar 就是这么被逼出来的）。

注意 allowed_props 是**精选子集**，不是 UILayout 的全量参数表：它只收录
本工作台实际会用到的调用形式。清单外的参数一律按「自造/拼错」拦掉，所以
它收窄得比真实 API 保守——这是有意的，但别把它当成「UILayout 只有这些参数」。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "ui_workbench", "constraints.json")
API = os.path.join(ROOT, "ui_workbench", "native_api.json")
OUT = os.path.join(ROOT, "ui_workbench", "vocabulary.json")


def load_icon_names():
    """Blender 实测能用的图标名，从 native_api.json 的枚举项里抄。

    抄而不是手写：手写名册必然会跟真实枚举漂，而图标名写错在 Blender 里是
    直接抛异常的一类错。native_api.json 里这份枚举就是探针抓回来的 bl_icon.items
    （1033 个，icons.count 与之相符），这份文件就是名册的证据。
    """
    with open(API, encoding="utf-8") as fh:
        api = json.load(fh)
    items = api["panels"]["properties"]["bl_icon"]["items"]
    names = [str(x) for x in items]
    declared = api.get("icons", {}).get("count")
    if declared is not None and declared != len(names):
        raise VocabularyError(
            "native_api.json 自报 icons.count=%d，实际枚举 %d 个，名册不可信"
            % (declared, len(names)))
    return names

PROPS_SCOPE = ("allowed_props 是精选子集，不是 UILayout 的全量参数表："
               "只收录本工作台会用到的调用形式，清单外的参数会被按"
               "「自造/拼错」拦下")

# 「对应插件元素 ID」到底是什么。用户只看到一个 (可选) 占位符，根本不知道
# 填什么，所以在这里就把三件事讲清楚：它是什么、怎么命名、能不能留空。
ELEMENT_ID_HELP = {
    "title": "「对应插件元素 ID」是什么",
    "what": "它是这块积木在 blender_deepseek_agent/ui.py 里的稳定标记，"
            "用来把你的标注挂回代码里的那一行。",
    "naming": "命名规则：chat.<区块> 或 chat.<区块>.<控件>，全小写、下划线分隔。",
    "optional": "可以留空——留空只是没法单独标注这一块，不影响拼装。",
    "examples": ["chat.composer", "chat.send_btn"],
}

# 一键插入的示例面板。放在数据里而不是写死成 JS 字面量：重跑本脚本时它不会丢，
# 测试也能逐条核对里面的参数与元素 ID。
# element_id 取自已提交的 7 份布局树（ui_workbench/data/layout/*.json）；
# 两条留空是有意的——正好演示「元素 ID 可以不填」。
# content 是这块里写什么字：左边预览只认它，缺了这一栏，预览就只是一排空壳。
# 容器类控件（box/split/grid_flow/panel/separator/scale_y）没有 content：
# 它们只分组或占位，不写字。row / column 例外——它们带一个 heading，
# 页签条与分组标题就靠它。
#
# 嵌套关系（谁装在谁里面）不塞进块对象，而是单开一张 EXAMPLE_PANEL_PARENT_CHAT
# 下标表。原因是 test_proposal_vocab 的 example_panel_schema 断言把每块的字段集
# 钉死为 {wkey, params, element_id, note, content} 这五个；往块里加第六个字段
# 会让那条断言变红，而它不许弱化。写成平行的表，两边都不用破例。
EXAMPLE_PANEL = {
    "title": "AI 对话",
    "caption": "整根竖排把它们从上到下串起来，横排把同一组里的控件并排放。",
    "blocks": [
        # 页签条：真实面板顶上就是三个并排的页签（ui.py 里 row(align=True)
        # + prop(expand=True)）。这里用三个 operator 积木当那三个页签按钮——
        # 预览里 operator 画成一块带图标的按钮，正好对上 options.png 顶上那一行。
        {"wkey": "row", "params": "align", "element_id": "chat.tabbar",
         "note": "三个页签并排：AI 对话 / 详情 / 设置（页签条本身一个字都不写）",
         "content": {"heading": "AI 对话"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "页签按钮 · AI 对话（当前页签；块本身不装任何子块）",
         "content": {"text": "AI 对话", "icon": "USER"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "页签按钮 · 详情",
         "content": {"text": "详情", "icon": "IMAGE_DATA"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "页签按钮 · 设置",
         "content": {"text": "设置", "icon": "PREFERENCES"}},
        {"wkey": "column", "params": "align", "element_id": "chat.stream",
         "note": "整根竖排：下面每一块都落在它里面，从上到下",
         "content": {"heading": "对话记录"}},
        {"wkey": "box", "params": "", "element_id": "",
         "note": "消息流里的一条消息（元素 ID 可以留空）",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "状态行：正在改你的场景 · 第 2 步",
         "content": {"text": "正在改你的场景 · 第 2 步", "icon": "TIME"}},
        {"wkey": "column", "params": "align", "element_id": "chat.options",
         "note": "规格选项容器：一次有几项要选，就用竖排把每项串起来",
         "content": {"heading": "需要你定一下"}},
        # 真实面板里每个细节底下是一列「选择：xxx」的勾选按钮，一个选项占满
        # 一整行。ui.py 里是 for opt in ...: orow = qbox.row() —— 每选一个就
        # 新建一个横排，竖着看就是一列；options.png 里也是这样，竖排一行一个。
        # 这里原来写成横排，三个按钮并排后每条只剩三分之一宽，
        # 「选择：经典直筒微收口（推荐）」被折成两行，和真实面板对不上。
        # 勾选框是 prop(toggle=True) 画出来的，零资源下用 CHECKBOX_DEHLT 这个
        # 实测图标名示意，位置对得上 options.png 里每个按钮左边那个小方块。
        {"wkey": "column", "params": "align", "element_id": "",
         "note": "一组规格选项：竖排里一个选项占一行，按钮才够宽，长文案不折行",
         "content": {"heading": "细节 1：1.杯型风格"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "规格选项按钮（带勾选框）",
         "content": {"text": "选择：经典直筒微收口（推荐）", "icon": "CHECKBOX_DEHLT"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "规格选项按钮（带勾选框）",
         "content": {"text": "选择：鼓腹圆润", "icon": "CHECKBOX_DEHLT"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "规格选项按钮（带勾选框）",
         "content": {"text": "选择：手感厚壁窑变", "icon": "CHECKBOX_DEHLT"}},
        # 真实面板在输入框上面是 2x2 的四个并排按钮（修改尺寸 / 更换材质 /
        # 增加倒角 / 平滑着色）。columns=2 让预览真的排成两列两行。
        # 图标名逐个对着 native_api.json 的 1033 个实测名挑的：尺寸只有
        # CON_SIZELIKE（尺寸约束那个图标）语义对得上，材质是材质预览球
        # MATSHADERBALL（MATSPHERE 是「UV 球面」这个图元，不是材质），
        # 倒角是 MOD_BEVEL，平滑着色落在法线上用 NORMALS_VERTEX。
        # 挑不到语义对得上的就留空，不硬凑。
        {"wkey": "grid_flow", "params": "row_major, columns, even_columns",
         "element_id": "",
         "note": "两列并排的按钮网格：grid_flow(columns=2) 就是那个样子",
         "content": {}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "网格里的第一个按钮",
         "content": {"text": "修改尺寸", "icon": "CON_SIZELIKE"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "网格里的第二个按钮",
         "content": {"text": "更换材质", "icon": "MATSHADERBALL"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "网格里的第三个按钮",
         "content": {"text": "增加倒角", "icon": "MOD_BEVEL"}},
        {"wkey": "operator", "params": "", "element_id": "",
         "note": "网格里的第四个按钮",
         "content": {"text": "平滑着色", "icon": "NORMALS_VERTEX"}},
        {"wkey": "textbox", "params": "prop, initial_visible_lines",
         "element_id": "chat.composer", "note": "指令输入框，可写多行",
         "content": {"placeholder": "输入建模指令…", "lines": 3}},
        {"wkey": "row", "params": "align", "element_id": "chat.action_row",
         "note": "三个并排的操作按钮：发送指令 / 新建任务 / 清空记录",
         "content": {"heading": "操作"}},
    ],
}

# 块下标 -> 父块下标（"-1" 是顶层）。
# 按下标而不是按父块的 wkey：一套面板里常有多个同 wkey 的容器（对话面板里
# 既有根竖排 chat.stream，也有 chat.options 那个竖排），按 wkey 找会挂到
# 最后遇到的那个上去——挂错容器在预览里几乎看不出来，只会觉得排版怪怪的。
# 下标而不是 uid：uid 由 app.js 插入时才发，数据侧拿不到。
EXAMPLE_PANEL_PARENT_CHAT = {
    "0": -1,          # chat.tabbar 那一根横排在最上面，三个页签按钮装在它里面
    "1": 0,           # AI 对话 页签
    "2": 0,           # 详情 页签
    "3": 0,           # 设置 页签
    "4": -1,          # chat.stream 整根竖排，自己撑起这个界面
    "5": 4,           # 消息盒 -> 落在竖排里
    "6": 4,           # 状态行 -> 落在竖排里
    "7": 4,           # chat.options 规格竖排 -> 落在竖排里
    "8": 7,           # 细节 1 那一横排 -> 落在规格竖排里
    "9": 8,           # 三个规格选项按钮 -> 落在那一横排里
    "10": 8,
    "11": 8,
    "12": 4,          # 两列按钮网格 -> 落在竖排里
    "13": 12,
    "14": 12,
    "15": 12,
    "16": 12,
    "17": 4,          # 输入框 -> 落在竖排里
    "18": 4,          # 操作行 -> 落在竖排里
}

# 新积木的起手内容。空按钮定不了形、也看不出这是个什么控件，所以每个有内容
# 的控件一放上来就写一句能看懂的话。容器不给起手内容（空的横排竖排本来就该
# 是空的，写死了反而不像刚放上去的）。row / column 的 heading 之所以算内容
# 而不是参数：参数框按白名单只收参数名，收不了取值，没有它就没法做页签条。
STARTER_CONTENT = {
    "label": {"text": "状态行文字", "icon": "INFO"},
    "operator": {"text": "发送指令", "icon": "PLAY"},
    "prop": {"label": "API Key", "value": "（未填）"},
    "textbox": {"placeholder": "在这里输入建模指令…", "lines": 3},
}

# 详情界面的示例面板。结构逐段照着 blender_deepseek_agent/ui.py 的
# draw_detail_content() 抄，不凭空编：那里依次是
#   1) 工具调用 box（tbox.label 标题 + 每次调用 srow 一行）
#   2) 转录 box（box.label 标题 + box.prop(transcript)）
#   3) 用量 box（标题 + 输入/缓存、输出、轮次耗时三行 label）
#   4) 导出按钮  5) 空态提示
# box 里放的是 label 而不是给 box 本身写 heading：容器一个字都不写，
# 而 ui.py 里 title 本来也是 tbox.label(text=...) 这么写的。
EXAMPLE_PANEL_DETAIL = {
    "title": "详情",
    "caption": "工具调用 + 转录 + 本次用量，和真实面板的 draw_detail_content() 一一对应。",
    "blocks": [
        {"wkey": "column", "params": "align", "element_id": "detail.stream",
         "note": "整根竖排：下面几块都落在它里面",
         "content": {"heading": "任务详情"}},
        {"wkey": "box", "params": "", "element_id": "detail.calls",
         "note": "工具调用记录容器：标题 + 每次调用各占一行",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题（ui.py 里是 tbox.label(text=f\"工具调用（{len(run.calls)}）\")）",
         "content": {"text": "工具调用（4）", "icon": "CONSOLE"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "一次工具调用：状态图标 + 名字 + 摘要，三段并排",
         "content": {"heading": "1. list_scene_objects　球体·立方体·灯"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "再来一次调用，结构同上",
         "content": {"heading": "2. create_lathe_profile　经典直筒微收口"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "失败的一次调用（ui.py 里这类 icon 换 ERROR）",
         "content": {"heading": "3. apply_modifier　倒角参数越界"}},
        {"wkey": "box", "params": "", "element_id": "detail.transcript",
         "note": "完整转录容器（ui.py 里是 box.prop(state.transcript)）",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题",
         "content": {"text": "详情 / 转录内容", "icon": "CONSOLE"}},
        {"wkey": "prop", "params": "prop", "element_id": "",
         "note": "转录正文绑到插件属性上（可写多行）",
         "content": {"label": "转录", "value": "（在这里放完整转录）"}},
        {"wkey": "box", "params": "", "element_id": "detail.usage",
         "note": "本次用量容器：输入 / 缓存命中 / 输出 / 轮次与耗时",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题（ui.py 里 icon='INFO'）",
         "content": {"text": "本次用量（实测）", "icon": "INFO"}},
        {"wkey": "label", "params": "text", "element_id": "",
         "note": "输入 token 与缓存命中同一行（ui.py 里是一条 label 写两项）",
         "content": {"text": "输入 4820 · 缓存命中 3960"}},
        {"wkey": "label", "params": "text", "element_id": "",
         "note": "输出 token 一行",
         "content": {"text": "输出 612"}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "轮次与耗时一行（ui.py 里带 icon='TIME'）",
         "content": {"text": "轮次：3/12 · 耗时：41.2s", "icon": "TIME"}},
        {"wkey": "operator", "params": "id, text, icon", "element_id": "detail.export",
         "note": "导出完整转录（ui.py 里的 layout.operator(\"deepseek.export\")）",
         "content": {"text": "导出完整转录", "icon": "EXPORT"}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "空态：还没有任务记录时，这一行代替上面三块",
         "content": {"text": "还没有任务记录", "icon": "INFO"}},
    ],
}

EXAMPLE_PANEL_PARENT_DETAIL = {
    "0": -1,        # detail.stream 自己撑起整根竖排
    "1": 0,         # 工具调用容器
    "2": 1,         # 它的标题
    "3": 1,         # 第 1 次调用
    "4": 1,         # 第 2 次调用
    "5": 1,         # 第 3 次调用
    "6": 0,         # 转录容器
    "7": 6,         # 转录容器标题
    "8": 6,         # 转录正文
    "9": 0,         # 用量容器
    "10": 9,        # 用量容器标题
    "11": 9,        # 输入 / 缓存命中
    "12": 9,        # 输出
    "13": 9,        # 轮次与耗时
    "14": 0,        # 导出按钮
    "15": 0,        # 空态提示
}

# 设置界面的示例面板。结构照着 ui.py 的 draw_settings_content() 抄：那里开了
# use_property_split（所以属性是左右两列），依次是
#   1) 服务商 box（标题 + prop(provider) + 打开官方文档按钮）
#   2) API Key box（标题 + prop(api_key) + 生效状态一行）
#   3) 模型 box（标题 + prop(model) + 获取列表按钮 + grid_flow 预置模型按钮）
#   4) 高级运行参数 box（标题 + prop(base_url) + 两行并排属性）
#   5) 打开完整偏好设置按钮
EXAMPLE_PANEL_SETTINGS = {
    "title": "详情",
    "caption": "服务商 + API Key + 模型 + 高级参数，和真实面板的 draw_settings_content() 一一对应。",
    "blocks": [
        {"wkey": "column", "params": "align", "element_id": "settings.stream",
         "note": "整根竖排：下面几块都落在它里面",
         "content": {"heading": "设置"}},
        {"wkey": "box", "params": "", "element_id": "settings.provider",
         "note": "服务商配置容器：属性行 + 一行「打开官方文档」按钮",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题（ui.py 里 icon='PREFERENCES'）",
         "content": {"text": "服务商配置", "icon": "PREFERENCES"}},
        {"wkey": "prop", "params": "prop", "element_id": "",
         "note": "服务商下拉（ui.py 里是 prop(provider, text=\"服务商\")）",
         "content": {"label": "服务商", "value": "DeepSeek"}},
        {"wkey": "operator", "params": "id, text, icon", "element_id": "settings.doc",
         "note": "打开官方文档（wm.url_open）",
         "content": {"text": "打开 DeepSeek 官方文档", "icon": "URL"}},
        {"wkey": "box", "params": "", "element_id": "settings.key",
         "note": "API Key 配置容器：一行属性 + 一行生效状态",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题（ui.py 里 icon='KEYINGSET'）",
         "content": {"text": "API Key 配置", "icon": "KEYINGSET"}},
        {"wkey": "prop", "params": "prop", "element_id": "",
         "note": "API Key 输入（留空时 ui.py 会把这行 alert=True）",
         "content": {"label": "API Key", "value": "（未填）"}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "生效状态一行（已生效 / 未配置）",
         "content": {"text": "未配置 API Key（也可配置环境变量 DEEPSEEK_API_KEY）",
                     "icon": "ERROR"}},
        {"wkey": "box", "params": "", "element_id": "settings.model",
         "note": "模型配置容器：当前模型 + 获取列表按钮 + 两列预置模型网格",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题（ui.py 里 icon='PLUGIN'）",
         "content": {"text": "模型配置", "icon": "PLUGIN"}},
        {"wkey": "prop", "params": "prop", "element_id": "",
         "note": "当前模型（ui.py 里是 prop(model, text=\"当前模型\")）",
         "content": {"label": "当前模型", "value": "deepseek-chat"}},
        {"wkey": "operator", "params": "id, text, icon", "element_id": "settings.fetch",
         "note": "获取最新模型列表（deepseek.fetch_models）",
         "content": {"text": "获取最新模型列表", "icon": "FILE_REFRESH"}},
        {"wkey": "grid_flow", "params": "columns, even_columns, even_rows, row_major",
         "element_id": "settings.models",
         "note": "预置模型按钮：ui.py 就是 grid_flow(row_major=True, columns=2, "
                 "even_columns=True, even_rows=False)，这里照抄那个形状",
         "content": {}},
        {"wkey": "operator", "params": "id, text", "element_id": "",
         "note": "一个预置模型按钮（deepseek.set_model）",
         "content": {"text": "deepseek-chat"}},
        {"wkey": "operator", "params": "id, text", "element_id": "",
         "note": "第二个预置模型按钮，和上一个并排成两列",
         "content": {"text": "deepseek-reasoner"}},
        {"wkey": "box", "params": "", "element_id": "settings.advanced",
         "note": "高级运行参数容器：Base URL + 两行并排属性",
         "content": {}},
        {"wkey": "label", "params": "text, icon", "element_id": "",
         "note": "box 的标题",
         "content": {"text": "高级运行参数", "icon": "PREFERENCES"}},
        {"wkey": "prop", "params": "prop", "element_id": "",
         "note": "Base URL 整行一个（ui.py 里是 abox.prop(base_url)）",
         "content": {"label": "Base URL", "value": "https://api.deepseek.com"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "两个属性并排：超时(秒) + 最大轮次",
         "content": {"heading": "超时(秒)　　最大轮次"}},
        {"wkey": "row", "params": "align", "element_id": "",
         "note": "两个属性并排：时间预算(秒) + 面板历史条数",
         "content": {"heading": "时间预算(秒)　　面板历史条数"}},
        {"wkey": "operator", "params": "id, text, icon", "element_id": "settings.prefs",
         "note": "打开完整偏好设置（preferences.addon_show）",
         "content": {"text": "打开完整偏好设置", "icon": "PREFERENCES"}},
    ],
}

EXAMPLE_PANEL_PARENT_SETTINGS = {
    "0": -1,         # settings.stream 自己撑起整根竖排
    "1": 0,          # 服务商容器
    "2": 1,          # 标题
    "3": 1,          # 服务商属性行
    "4": 1,          # 打开官方文档
    "5": 0,          # API Key 容器
    "6": 5,          # 标题
    "7": 5,          # API Key 属性行
    "8": 5,          # 生效状态
    "9": 0,          # 模型容器
    "10": 9,         # 标题
    "11": 9,         # 当前模型属性行
    "12": 9,         # 获取最新模型列表
    "13": 9,         # 两列预置模型网格
    "14": 13,        # 网格里的第一个模型按钮
    "15": 13,        # 网格里的第二个模型按钮
    "16": 0,         # 高级运行参数容器
    "17": 16,        # 标题
    "18": 16,        # Base URL
    "19": 16,        # 超时 + 最大轮次（并排）
    "20": 16,        # 时间预算 + 历史条数（并排）
    "21": 0,         # 打开完整偏好设置
}

# 三个界面各一套示例面板。key 与 app.js 里的 activeTab 一致。
EXAMPLE_PANELS = {
    "chat": EXAMPLE_PANEL,
    "detail": EXAMPLE_PANEL_DETAIL,
    "settings": EXAMPLE_PANEL_SETTINGS,
}

# 每个界面的嵌套表，与 EXAMPLE_PANELS 一一对应。
EXAMPLE_PANEL_PARENTS = {
    "chat": EXAMPLE_PANEL_PARENT_CHAT,
    "detail": EXAMPLE_PANEL_PARENT_DETAIL,
    "settings": EXAMPLE_PANEL_PARENT_SETTINGS,
}

# (key, label, uiloayout, allowed_props, blocked_props, note, constraint_key,
#  demo, props_example, props_hint)
# constraint_key 为 None 表示这条控件是通用 UILayout，constraints.json 里
# 没有单列它的判定；有值则必须指向一条 native_ok=true 的判定。
#
# demo —— 声明式的迷你图示：只描述「长什么样」，由 app.js 画成小方块。
#         写成 HTML 字符串的话，重跑本脚本就会和控件定义脱节，而图示恰恰是
#         最容易随控件改动而失真的那部分。
# props_example —— 能直接粘进参数框、逐个合法的示例（只写参数名）。
#         参数框按逗号切词后逐个查白名单，带 '=' 或带引号会被当场拦下；
#         「示例给错了比不给更糟」，这一串必须能原样粘。
# props_hint —— 带取值的真实调用形式（给人看懂该填什么值），
#         逐条对着 native_api.json 的实测签名核过。
WIDGETS = [
    ("row", "横排", "layout.row(align=True)",
     ["align", "heading", "heading_ctxt"], [],
     "一行里并排放多个控件。横排是「并排」，竖排是「从上到下」——"
     "整个面板本身就是一根竖排。同一组控件要并排放，就用横排包住它们。", None,
     {"kind": "row", "items": ["发送指令", "停止"]},
     "align, heading",
     "layout.row(align=True, heading=\"对话\")"),
    ("column", "竖排", "layout.column(align=True)",
     ["align", "heading", "heading_ctxt"], [],
     "从上到下依次堆叠多个控件。面板从上到下的顺序，就是竖排里从上到下的顺序；"
     "整根竖排负责把页面串起来。", None,
     {"kind": "col", "items": ["消息1", "消息2", "消息3"]},
     "align, heading",
     "layout.column(align=True)"),
    ("box", "内盒", "layout.box()", ["alert"], [],
     "带边框的一块内容，把一条消息或一个提示圈起来。"
     "alert 是全 UI 唯一的红，只留给 FAILED。", None,
     {"kind": "box", "items": ["一个带边框的块"]},
     "alert",
     "box.alert = True"),
    ("split", "左右分栏", "layout.split(factor=0.3)",
     ["factor", "align"], [],
     "左右分成两栏。factor 是左栏宽度占比，0.3 就是左三右七。"
     "返回单个 layout，不是二元组。", "two_col_split",
     {"kind": "split", "factor": 0.3, "items": ["窄", "宽"]},
     "factor",
     "layout.split(factor=0.3)"),
    ("grid_flow", "网格按钮", "layout.grid_flow(columns=2, even_columns=True)",
     ["columns", "even_columns", "even_rows", "row_major"], [],
     "按钮排成网格：columns 定几列，even_columns 让每列等宽。"
     "比横排省高度，一堆同类按钮时用它。", "grid_flow",
     {"kind": "grid", "cols": 2, "items": ["改尺寸", "换材质", "加倒角", "平滑"]},
     "columns, even_columns",
     "layout.grid_flow(columns=2, even_columns=True)"),
    ("panel", "可折叠子面板", "layout.panel(idname, default_closed)",
     ["idname", "default_closed", "layout_header", "layout_body"], [],
     "一组能收起来的控件，带原生折叠箭头。侧栏滚不了，长度只能靠它消化。",
     "collapsible_panel",
     {"kind": "panel", "items": ["可折叠的一组"]},
     "idname, default_closed",
     "layout.panel(idname=\"chat.specs\", default_closed=True)"),
    ("label", "文字", "layout.label(text=..., icon=...)",
     ["text", "icon"], ["size", "font", "color"],
     "一行说明文字。字号不可调，层次只能靠 icon 和撑高做出来。", None,
     {"kind": "label", "items": ["一行文字"]},
     "text, icon",
     "layout.label(text=\"已处理完 3 项\", icon='CHECKMARK')"),
    ("operator", "按钮", "layout.operator(id, text=..., icon=...)",
     ["id", "text", "icon", "depress", "emboss"], ["color"],
     "点一下执行一条指令的按钮。id 填算子名；"
     "emboss='NONE' 可去掉高光渐变。", "flat_button",
     {"kind": "btn", "items": ["发送指令"]},
     "id, text, icon",
     "layout.operator(\"deepseek.run_prompt\", text=\"发送指令\", icon='PLAY')"),
    ("prop", "属性行", "layout.prop(data, prop, text=...)",
     ["prop", "text", "icon", "expand", "slider", "placeholder"], ["color"],
     "绑到插件设置项上的一行：左边文字，右边输入框。"
     "配 use_property_split 得到原生两列。", "property_split",
     {"kind": "prop", "items": ["API Key", "▾"]},
     "prop, text",
     "layout.prop(p, \"api_key\", text=\"API Key\")"),
    ("textbox", "多行输入", "layout.textbox(data, 'prompt', initial_visible_lines=3)",
     ["prop", "text", "placeholder", "initial_visible_lines"], [],
     "可以写多行的输入区。中文输入法只能靠原生 textbox，自绘拿不到拼音组合态。",
     None,
     {"kind": "box", "items": ["多行输入区"]},
     "prop, initial_visible_lines",
     "layout.textbox(state, \"prompt\", initial_visible_lines=3)"),
    ("separator", "分隔线", "layout.separator()", [], [],
     "一条横线，把上下两组控件分开。不带任何参数。", None,
     {"kind": "rule"},
     "",
     "layout.separator()"),
    ("scale_y", "留白撑高", "layout.scale_y = 1.4", ["scale_y"], [],
     "空出一条竖向空隙，把内容上下分开。字号不可调，层次只能靠撑高和缩进。", None,
     {"kind": "gap"},
     "scale_y",
     "row.scale_y = 1.3"),
]


class VocabularyError(Exception):
    """词汇表与 constraints.json 打架了。停下来，不要带着矛盾继续生成。"""


def check_example_panels(widgets):
    """三个界面的示例面板必须自洽，否则用户一点就看到违规块或一堆孤儿。

    四条硬检查：
      1) 参数必须逐个落在该控件的 allowed_props 里，且不在 blocked_props 里
         ——示例参数要是自己违规了，用户一插入就被标「违规」，工作台等于在骗人。
      2) 嵌套表的下标必须正好是 0..N-1 的完整区间，且父块的 wkey 必须真实存在。
         越界或指向不存在的块，子积木会静默留在顶层，看着像「归属没生效」。
      3) 父块必须是容器。不能往文字 / 按钮里塞东西，Blender 那边也写不出来。
      4) 一字都不写的容器不许带 content ——容器只分组，不写字。
    """
    allowed = {w["key"]: w for w in widgets}
    # 能装孩子的容器（含 row / column——它们带一个 heading，但照样是分组容器）
    containers = {"row", "column", "box", "split", "grid_flow", "panel"}
    # 一个字都不写的容器。row / column 不在此列：它们有 heading 内容字段，
    # 页签条与分组标题就靠它，与既有断言 preview_example_containers_have_no_content 同源。
    silent = {"box", "split", "grid_flow", "panel", "separator", "scale_y"}
    for tab in sorted(EXAMPLE_PANELS):
        blocks = EXAMPLE_PANELS[tab]["blocks"]
        parents = EXAMPLE_PANEL_PARENTS[tab]
        keys = [b["wkey"] for b in blocks]
        if sorted(int(k) for k in parents) != list(range(len(blocks))):
            raise VocabularyError(
                "%s 示例面板的嵌套表下标必须是 0..%d 的完整区间，实际 %s"
                % (tab, len(blocks) - 1, sorted(parents, key=int)))
        for i, b in enumerate(blocks):
            w = allowed.get(b["wkey"])
            if w is None:
                raise VocabularyError("%s 示例面板用了词汇表里没有的控件 %s"
                                      % (tab, b["wkey"]))
            for p in [x for x in re.split(r"[,，\s]+", b.get("params") or "") if x]:
                if p in w["blocked_props"]:
                    raise VocabularyError("%s 示例面板 %s 用了被拦参数 %s"
                                          % (tab, b["wkey"], p))
                if p not in w["allowed_props"]:
                    raise VocabularyError(
                        "%s 示例面板 %s 的参数 %s 不在允许清单里（可用：%s）"
                        % (tab, b["wkey"], p, ", ".join(w["allowed_props"]) or "无"))
            pw = int(parents[str(i)])
            if pw >= 0:
                if pw >= len(blocks):
                    raise VocabularyError(
                        "%s 示例面板第 %d 块的父下标 %d 越界（共 %d 块）"
                        % (tab, i, pw, len(blocks)))
                if pw == i:
                    raise VocabularyError("%s 示例面板第 %d 块把自己当成了父块"
                                          % (tab, i))
                if blocks[pw]["wkey"] not in containers:
                    raise VocabularyError(
                        "%s 示例面板第 %d 块挂在第 %d 块（%s）下面，"
                        "但那个不是容器" % (tab, i, pw, blocks[pw]["wkey"]))
            if b["wkey"] in silent and b.get("content"):
                raise VocabularyError(
                    "%s 示例面板的容器 %s 不该带 content（容器只分组，不写字）"
                    % (tab, b["wkey"]))


def build(constraints):
    reg = {e["key"]: e for e in constraints["entries"]}

    widgets = []
    for key, label, call, allowed, blocked, note, ckey, demo, ex, hint in WIDGETS:
        # 让 docstring 里那句「只有 native_ok=true 的能力才能进词汇表」成立：
        # 声称自己实现了某条判定的控件，那条判定必须真的 native_ok=true。
        # 翻脸了就抛错，让人来定——静默丢掉一个控件比停下来更坏。
        if ckey is not None:
            if ckey not in reg:
                raise VocabularyError(
                    "控件 %s 声称实现 constraints 里不存在的判定 %s" % (key, ckey))
            if not reg[ckey]["native_ok"]:
                raise VocabularyError(
                    "控件 %s 依赖的判定 %s 已是 native_ok=false："
                    "%s。要么删掉这个控件，要么把它移进 rejected 并给出降级方案"
                    % (key, ckey, reg[ckey].get("blocker", "")))
        widgets.append({
            "key": key, "label": label, "uiloayout": call,
            "allowed_props": allowed, "blocked_props": blocked, "note": note,
            "constraint_key": ckey,
            "demo": demo, "props_example": ex, "props_hint": hint,
        })

    rejected = []
    for e in constraints["entries"]:
        if e["native_ok"]:
            continue
        rejected.append({
            "key": e["key"], "label": e["title"],
            "blocker": e["blocker"], "fallback": e["fallback"],
        })

    # 可做、但词汇表还没收录的能力。单列出来，提案视图里给它一行说明，
    # 而不是让它在控件栏和降级栏里同时消失。
    mapped = set(w["constraint_key"] for w in widgets if w["constraint_key"])
    unmapped = [{"key": e["key"], "label": e["title"], "uiloayout": e["uiloayout"],
                 "evidence": e["evidence"]}
                for e in constraints["entries"]
                if e["native_ok"] and e["key"] not in mapped]

    check_example_panels(widgets)

    return {
        "generated_for": constraints["generated_for"],
        "props_scope": PROPS_SCOPE,
        "widgets": widgets,
        "rejected": rejected,
        "unmapped_ok": unmapped,
        "element_id_help": ELEMENT_ID_HELP,
        # example_panel 是「对话」那套的老键，保留：既有断言按它逐条核对块序、
        # 参数与元素 ID。example_panels 是三个界面各一套的新键。
        "example_panel": EXAMPLE_PANEL,
        "example_panels": EXAMPLE_PANELS,
        # 嵌套关系单独一张表：块下标 -> 父块 wkey（"" = 顶层）。
        "example_panel_parents": EXAMPLE_PANEL_PARENTS,
        "starter_content": STARTER_CONTENT,
        "icons": load_icon_names(),
    }


def main():
    with open(SRC, encoding="utf-8") as fh:
        constraints = json.load(fh)
    try:
        vocab = build(constraints)
    except VocabularyError as exc:
        print("VOCAB_FAIL %s" % exc)
        return 1
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(vocab, fh, ensure_ascii=False, indent=2)
    print("VOCAB_OK widgets=%d rejected=%d unmapped_ok=%d"
          % (len(vocab["widgets"]), len(vocab["rejected"]), len(vocab["unmapped_ok"])))
    for r in vocab["rejected"]:
        print("REJECT %-18s -> %s" % (r["key"], r["fallback"]))
    for u in vocab["unmapped_ok"]:
        print("UNMAPPED_OK %-14s %s -> 词汇表尚未收录（落笔时拿不到）" % (u["key"], u["uiloayout"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
