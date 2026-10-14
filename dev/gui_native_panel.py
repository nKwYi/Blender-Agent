# -*- coding: utf-8 -*-
"""真机 GUI 验收：原生 N 面板在已安装扩展下能否真的画出来。

用法（不要加 --factory-startup，要的就是用户真实的启用路径）：
    blender.exe -P dev/gui_native_panel.py

跑完不立刻退出：写 READY 后等 dev/out/gui_native_panel.stop（最长 HOLD 秒），
期间外部可以用 WGC 在不激活窗口的情况下截图，再由发起方发停止信号。
结论写 dev/out/gui_native_panel.txt。
"""
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "gui_native_panel.txt")
SHOT = os.path.join(OUT, "native_panel_builtin.png")
STOP = os.path.join(OUT, "gui_native_panel.stop")
HOLD = 40

RESULTS = []
extra = []
counts = [0, 0, 0]  # chat / detail / settings 各自被真实调用的次数

NAMES = ("DEEPSEEK_PT_chat",)


def ck(name, cond, msg=""):
    RESULTS.append(("PASS " if cond else "FAIL ") + name + ("" if cond else f" :: {msg}"))
    print("GUI " + RESULTS[-1], flush=True)


def flush(ready=False):
    fails = sum(1 for r in RESULTS if r.startswith("FAIL"))
    with open(LOG, "w", encoding="utf-8") as fh:
        if ready:
            fh.write("READY\n")
        fh.write("\n".join(RESULTS) + "\n")
        fh.write(f"TOTAL {len(RESULTS)} FAILED {fails}\n")
        fh.write("\n".join(extra) + "\n")


def find_view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                return window, area
    return None, None


def ensure_sidebar():
    window, area = find_view3d()
    if area is None:
        return None
    center = next((r for r in area.regions if r.type == 'WINDOW'), None)
    ui = next((r for r in area.regions if r.type == 'UI'), None)
    # 收起状态的 N 面板区域一直都在，只是宽度为 1；只看"存不存在"会永远不去展开它。
    if center is not None and (ui is None or ui.width <= 1):
        with bpy.context.temp_override(window=window, area=area, region=center):
            bpy.ops.screen.region_toggle(region_type='UI')
        ui = next((r for r in area.regions if r.type == 'UI'), None)
    return ui


def try_select_tab(ui_region):
    """启动初期这个属性只读，区域完成布局后才可写，所以必须每 tick 重试。"""
    window, area = find_view3d()
    if window is None or ui_region is None:
        return False, "no region"
    try:
        with bpy.context.temp_override(window=window, area=area, region=ui_region):
            ui_region.active_panel_category = "AI 对话"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)[:90]
    return getattr(ui_region, "active_panel_category", "") == "AI 对话", "ok"


def patch_registered_draws():
    """补 bpy.types 上已注册的类；补扩展包里的类不会影响真正被调用的那一个。"""
    for idx, name in enumerate(NAMES):
        cls = getattr(bpy.types, name, None)
        if cls is None:
            extra.append(f"PATCHMISS {name}")
            continue
        original = cls.draw

        def wrapper_factory(i, fn):
            def patched(self, context):
                counts[i] += 1
                return fn(self, context)
            return patched

        cls.draw = wrapper_factory(idx, original)


def main():
    mods = [a.module for a in bpy.context.preferences.addons]
    ck("扩展已启用（真实配置路径）", any(m.endswith("blender_deepseek_agent") for m in mods), str(mods))
    pkg = next((m for m in mods if m.endswith("blender_deepseek_agent")), None)
    if pkg is None:
        flush()
        return
    bda = __import__(pkg, fromlist=["ui"])
    U = bda.ui
    extra.append("PKG " + pkg)
    extra.append("FILE " + bda.__file__)

    ck("包里已无 GPU 自绘模块",
       not any(os.path.exists(os.path.join(os.path.dirname(bda.__file__), n + ".py"))
               for n in ("workspace", "runtime", "panel", "painter", "theme", "look")))
    cats = {c.bl_category for c in U.CLASSES if getattr(c, "bl_region_type", None) == 'UI'}
    ck("N 侧栏只有一个入口", cats == {"AI 对话"}, str(cats))
    ck("deepseek 算子齐全",
       all(hasattr(bpy.ops.deepseek, n) for n in
           ("run_prompt", "stop", "approve", "undo_task", "show_call", "page", "export")))

    patch_registered_draws()

    state = bpy.context.scene.deepseek_agent
    state.history.clear()
    for i in range(24):
        U.push_history(state, "你" if i % 2 == 0 else "AI",
                       f"历史消息 {i}：这条写得长一点，用来看侧栏里长中文会不会被裁掉、要不要翻页。")
    state.prompt = "创建一个红色立方体，放在 (2, 0, 0)"

    ui = ensure_sidebar()
    ck("N 侧栏 UI 区域存在", ui is not None, "region_toggle 没拿到 UI 区域")

    if os.path.exists(STOP):
        os.remove(STOP)
    bpy.app.timers.register(_tick, first_interval=0.4)


state = {"ticks": 0, "ui": None, "tab": False, "retries": 0, "last": ""}


def _tick():
    state["ticks"] += 1
    ui = state["ui"]
    if ui is None or ui.width <= 1:
        state["ui"] = ensure_sidebar()
        ui = state["ui"]
    # 写分类只是尽力而为：窗口不在前台时该属性一直只读，不能拿它当闸门，
    # 否则脚本会永远等在循环里（上一版就是这么挂掉的）。
    if not state["tab"]:
        state["tab"], state["last"] = try_select_tab(state["ui"])
        if not state["tab"]:
            state["retries"] += 1
    if counts[0] == 0 and state["ticks"] < 80:
        if state["ticks"] % 20 == 0:
            flush()
        return 0.25
    finish()


def finish():
    ck(f"对话面板真的被绘制过（重试写分类 {state['retries']} 次）", counts[0] > 0, f"draw_calls={counts[0]}")
    extra.append(f"TAB writable={state['tab']} last={state['last']}")
    extra.append(f"DRAW chat={counts[0]}")
    if state["ui"] is not None:
        extra.append(f"REGION width={state['ui'].width} height={state['ui'].height} "
                     f"cat={getattr(state['ui'], 'active_panel_category', '?')!r}")
        ck("侧栏宽度可读", state["ui"].width > 100, f"width={state['ui'].width}")
    try:
        bpy.ops.screen.screenshot(filepath=SHOT)
        ck("Blender 内置截图已落盘", os.path.exists(SHOT), SHOT)
    except Exception as exc:  # noqa: BLE001
        ck("Blender 内置截图已落盘", False, repr(exc)[:120])

    flush(ready=True)
    bpy.app.timers.register(_wait_stop, first_interval=1.0)


def _wait_stop():
    state["ticks"] += 1
    if os.path.exists(STOP):
        flush()
        bpy.ops.wm.quit_blender()
        return None
    if state["ticks"] > HOLD:
        flush()
        bpy.ops.wm.quit_blender()
        return None
    return 1.0


main()
