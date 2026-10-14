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
