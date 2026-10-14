# -*- coding: utf-8 -*-
"""UILayout 录制器：把 draw() 的调用序列录成一棵可序列化的 JSON 树。

必须与 Blender 5.2.1 真实行为对齐的两点（均已实测）：

1. layout.split(factor=0.3) 返回**单个** UILayout，不是二元组。
   旧 dev/test_native_ui.py 的 MockLayout 返回 (a, b)，是错的。
   真实返回的对象是占左侧 factor 比例、整体左对齐的一列。
2. layout.context_menu 在 5.2.1 已不存在（116 个 UILayout 函数里没有，
   只有 menu_pie 和 popover）。因此本桩**故意不提供** context_menu：
   桩方法比真实 API 多，会让录制器悄悄接受真实 Blender 会崩的调用。

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

    _INTERNAL = ("op_id", "text", "icon", "kwargs")

    def __init__(self, op_id, text, icon, kwargs):
        self.op_id = op_id
        self.text = text
        self.icon = icon
        self.kwargs = kwargs

    def __setattr__(self, name, value):
        if name in self._INTERNAL:
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
        node.menu_icon = icon
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
        if text:
            self.texts.append(str(text))
        return op

    def textbox(self, data, prop, text="", **kw):
        self.props.append({
            "data": getattr(data, "bl_idname", type(data).__name__),
            "prop": prop,
            "text": text,
            "is_textbox": True,
            "kwargs": {k: str(v) for k, v in kw.items()},
        })
        if text:
            self.texts.append(str(text))
        return None

    # ---------------------------------------------------------- 身份
    def tag(self, element_id):
        """Task 3 的 mark() 靠 hasattr(layout, 'tag') 探测本录制器。"""
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
                      "panel_default_closed", "menu_icon"):
            if hasattr(self, extra):
                node[extra] = getattr(self, extra)
        return node


class Recorder:
    def __init__(self):
        self.root = RecLayout()

    def finish(self):
        return self.root.to_dict()
