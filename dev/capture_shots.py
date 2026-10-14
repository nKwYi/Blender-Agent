# -*- coding: utf-8 -*-
"""一次 GUI 运行产出 7 个状态的 N 面板截图。

机制照抄 dev/gui_check_v2.py：定时器驱动状态机 + 重绘等待 + 看门狗。
不要写成同步 for 循环——面板来不及重绘，截出来会是同一张图。

必须用最小化窗口运行，不要抢用户桌面。拍完调用 wm.quit_blender 退出，
不要留下残留进程。

启动方式（必须 --factory-startup，从工作区源码注册，避免加载用户安装的
0.4.7 那份、保证截图与 ui_workbench/data/layout 同源）：

    blender.exe --factory-startup -P dev/capture_shots.py

--background 下 bpy.app.timers 一次都不触发，所以本脚本只能 GUI 模式跑。

判定依据只有日志里的 SHOTS 行：Blender 5.2.1 的 -P 脚本即使抛未捕获异常，
进程退出码仍然是 0。
"""
import bpy
import hashlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "ui_workbench", "data", "shots")
OUT_LOG = os.path.join(HERE, "out", "shots_log.txt")

_lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    _lines.append(s)
    print("[SHOTS]", s)
    sys.stdout.flush()
    try:
        with open(OUT_LOG, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_lines))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 安全网：必须排在下面那堆 import 之前注册。
# blender_deepseek_agent 和 dev.states（工作区本地模块）任何一处出错，脚本都会
# 在"还没注册任何定时器"的状态下中止——GUI 窗口开着、最小化、永远不关，
# 而退出码照样是 0，外层 Start-Process -Wait 连超时都判断不出来。
# 先挂一个兜底定时器：只要 disarm 没被解除，90 秒后无条件把进程带走。
# ---------------------------------------------------------------------------
_ARMED = [True]
SAFETY_SECONDS = 90.0  # 正常跑完约 25s，90s 是宽裕上限


def _safety_net():
    if _ARMED[0]:
        log("SAFETY_EXIT -- import 失败或中途卡死，强制退出，不留残余进程")
        sys.stdout.flush()
        os._exit(3)
    return None


bpy.app.timers.register(_safety_net, first_interval=SAFETY_SECONDS)


def bail(msg, detail=""):
    """收尾并硬退出：解除安全网、打日志、立刻走人（不等 wm.quit_blender）。"""
    log(msg, detail)
    _ARMED[0] = False
    sys.stdout.flush()
    os._exit(3)


try:
    import blender_deepseek_agent as bda
    from blender_deepseek_agent import ui as U  # noqa: F401  注册面板用
    from dev.states import STATE_NAMES, apply_spec, build
except Exception:
    bail("IMPORT_FAIL", traceback.format_exc())


# 面板 draw 期间会读配置（模型名 / Key 状态等）。GUI 里没有真实 Key，
# 用假配置顶上，避免读 keyring 把 draw 打断。机制同 gui_check_v2.py。
_CFG = {
    "api_key": "sk-shot-mock", "key_source": "prefs", "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com", "provider": "DEEPSEEK",
    "timeout": 20, "max_turns": 4, "wall_budget": 45,
    "allow_arbitrary_code": False, "history_page": 3,
}

_state = {"i": 0, "settle": 0, "watchdog": 0, "taken": [], "errs": [],
          "ar": (None, None), "opened": False, "pending": None, "tries": 0}


def find_ui_region():
    """定位 N 面板 UI region 并切到「AI 对话」分类。

    factory startup 下的默认布局没有独立的 UI area，只有 3D 视图侧栏，
    所以先打开 show_region_ui 再找 region（gui_check_v2.py:144 的做法）。

    ★ 首次尝试必然失败：region.categories 还是空表，此时
    `region.active_panel_category` 是只读的。gui_check_v2 的成功日志里就是
    第一轮 CATEGORY_FAIL、第二轮才 set 成功（dev/out/gui_check_v2.txt）。
    所以调用方必须重试，不能第一轮失败就退出。
    """
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            area.spaces.active.show_region_ui = True
            area.tag_redraw()
    bpy.context.view_layer.update()

    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            for region in area.regions:
                if region.type != 'UI' or region.width <= 200:
                    continue
                cats = list(getattr(region, "categories", []))
                try:
                    region.active_panel_category = "AI 对话"
                except Exception as exc:
                    log("CATEGORY_FAIL", "cats=%s" % cats, repr(exc))
                    continue
                area.tag_redraw()
                log("panel area", area.type, area.x, area.y, area.width, area.height,
                    "| region", region.x, region.y, region.width, region.height,
                    "| category ->", region.active_panel_category)
                return area, region
    return None, None


def tick():
    """每个状态走 apply -> settle -> shoot 三个阶段。

    循环结束后再截一次只会拍到最后那个状态，所以每个状态都得自己走一轮。
    """
    _state["watchdog"] += 1
    if _state["watchdog"] > 240:
        log("WATCHDOG_TIMEOUT taken=%d" % len(_state["taken"]))
        _state["errs"].append("watchdog_timeout")
        finish()
        return None

    if not _state["opened"]:
        area, region = find_ui_region()
        _state["tries"] += 1
        if area is None:
            if _state["tries"] > 24:
                log("NO_UI_REGION -- 试了 %d 次仍切不到 AI 对话分类"
                    % _state["tries"])
                _state["errs"].append("no_ui_region")
                finish()
                return None
            return 1.0
        _state["ar"] = (area, region)
        _state["opened"] = True
        return 1.0

    area, region = _state["ar"]

    if _state["settle"] < 3:
        _state["settle"] += 1
        area.tag_redraw()
        return 0.5
    _state["settle"] = 0

    pending = _state["pending"]
    if pending is None:
        if _state["i"] >= len(STATE_NAMES):
            finish()
            return None
        pending = STATE_NAMES[_state["i"]]
        _state["i"] += 1
        _state["pending"] = pending
        try:
            apply_spec(bpy.context.scene.deepseek_agent, build(pending))
            log("applied", pending)
        except Exception as exc:
            _state["errs"].append("apply %s: %r" % (pending, exc))
            log("APPLY_FAIL", pending, repr(exc))
        return 0.5

    area.tag_redraw()
    time.sleep(0.4)
    path = os.path.join(OUT_DIR, "%s_full.png" % pending)
    try:
        bpy.ops.screen.screenshot(filepath=path)
        with open(path, "rb") as fh:
            digest = hashlib.md5(fh.read()).hexdigest()
        _state["taken"].append(pending)
        log("shot", pending, os.path.getsize(path), "bytes", "md5=" + digest,
            "| region", region.x, region.y, region.width, region.height)
    except Exception as exc:
        _state["errs"].append("shot %s: %r" % (pending, exc))
        log("SHOT_FAIL", pending, repr(exc))
    _state["pending"] = None
    return 0.5


def _force_exit():
    """wm.quit_blender() 在最小化窗口的 timer 回调里实测不生效，进程会留下。
    所以收尾之后再挂一个 6 秒的硬退出兜底，绝不留残留 Blender 进程。"""
    log("FORCE_EXIT")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def finish():
    log("STATES %s" % " ".join(_state["taken"]))
    for e in _state["errs"]:
        log("ERR", e)
    if len(_state["taken"]) == len(STATE_NAMES) and not _state["errs"]:
        log("CAPTURE_SHOTS_OK count=%d" % len(_state["taken"]))
    else:
        log("CAPTURE_SHOTS_BAD count=%d" % len(_state["taken"]))
    # 正常收尾：解除安全网，再挂 6 秒硬退出兜底，最后请 Blender 自己退。
    _ARMED[0] = False
    bpy.app.timers.register(_force_exit, first_interval=6.0)
    try:
        bpy.ops.wm.quit_blender()
    except Exception as exc:
        log("QUIT_FAIL", repr(exc))


def assert_workspace_source():
    """★ 必须加载工作区源码，不能是用户安装的 0.4.7 那份。

    光 print MODULE_FILE 是不够的：不加 --factory-startup 重跑时，
    bda.register() 会被 hasattr 守卫跳过，脚本照样打出
    CAPTURE_SHOTS_OK count=7，而截图其实来自已安装副本——与
    ui_workbench/data/layout 不同源。这条约束要由代码强制，不只写在文档里。
    """
    mod = os.path.realpath(bda.__file__)
    if os.path.realpath(ROOT) not in mod:
        log("CAPTURE_SHOTS_BAD loaded_not_workspace", mod)
        bail("WORKSPACE_SOURCE_FAIL", mod)
    log("workspace source OK", mod)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_LOG), exist_ok=True)
    if not hasattr(bpy.types.Scene, "deepseek_agent"):
        bda.register()
        log("addon registered from", bda.__file__)
    else:
        log("addon already registered")
    assert_workspace_source()
    try:
        bda.config.get_config = lambda: dict(_CFG)
    except Exception as exc:
        log("CONFIG_MOCK_FAIL", repr(exc))
    log("MODULE_FILE", getattr(sys.modules.get("blender_deepseek_agent"), "__file__", "?"))
    bpy.app.timers.register(tick, first_interval=1.0)
    log("timer registered")
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # 异常发生在安全网解除之前，必须硬退出，不能只 quit_blender——
        # 实测 quit_blender 在最小化窗口的 timer 回调里可能不生效。
        bail("HARNESS_FAIL", traceback.format_exc())