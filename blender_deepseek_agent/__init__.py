from . import agent, config, tools, ui  # noqa: F401  (agent/tools 由 ui 触发导入，这里显式列出便于排查)


def register():
    config.register()
    ui.register()


def unregister():
    ui.unregister()
    config.unregister()


if __name__ == "__main__":
    register()
