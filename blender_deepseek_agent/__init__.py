import sys

# 装成扩展或开发热重载时，强制按依赖拓扑重载子模块，保证新算子与属性 100% 刷新生效
if "bpy" in locals():
    import importlib
    from . import config, receipt, state, tools, worker, ui_ids, agent, ui
    for _m in (config, receipt, state, tools, worker, ui_ids, agent, ui):
        importlib.reload(_m)

from . import agent, config, receipt, state, tools, ui, ui_ids, worker  # noqa: F401


def register():
    config.register()
    ui.register()


def unregister():
    ui.unregister()
    config.unregister()


if __name__ == "__main__":
    register()
