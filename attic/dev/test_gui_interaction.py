"""GUI 交互与命中测试断言：_locate 坐标映射、tab strip 避让放行、按钮点击派发、输入焦点与打字。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bpy
import blender_deepseek_agent as bda
from blender_deepseek_agent import runtime, ui as U, panel as P, theme as T

if not hasattr(bpy.types.Scene, "deepseek_agent"):
    bda.register()

state = bpy.context.scene.deepseek_agent
state.prompt = ""
state.history.clear()

passed = 0
failed = 0

def check(condition, desc):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {desc}")
    else:
        failed += 1
        print(f"  [FAIL] {desc}")

print("=== RUNNING GUI INTERACTION TESTS ===")

# 1. 模拟 Area, Space, Region
class MockSpace:
    type = 'VIEW_3D'
    show_region_ui = True
    def as_pointer(self):
        return 99999

class MockRegion:
    type = 'UI'
    width = 420
    height = 900
    active_panel_category = 'UNSUPPORTED'

class MockContext:
    space_data = MockSpace()
    region = MockRegion()
    scene = bpy.context.scene
    window_manager = bpy.context.window_manager

class MockEvent:
    def __init__(self, x, y, ev_type='LEFTMOUSEPRESS', val='PRESS', uni=''):
        self.mouse_region_x = x
        self.mouse_region_y = y
        self.mouse_y = y
        self.type = ev_type
        self.value = val
        self.unicode = uni
        self.ctrl = False
        self.shift = False

ctx = MockContext()
sp = ctx.space_data
rg = ctx.region
key = runtime._key(sp)

runtime._REGION[key] = rg
runtime.mark_visible(sp)

# 确保布局已构建
tab_w = runtime.get_tab_strip_width()
panel_w = max(100.0, float(rg.width) - tab_w)
out = P.build(P.Ctx(state, None, U, panel_w, rg.height))
runtime._CURRENT[key] = out

# --- 测试 1: _locate 坐标映射与边界 ---
ev_normal = MockEvent(50, 850) # 距底 850，距顶 900 - 850 = 50
loc = runtime._locate(ctx, ev_normal)
check(loc is not None, "正常区域内 _locate 返回非空")
if loc:
    k, s, mx, my = loc
    check(mx == 50.0 and my == 50.0, f"坐标正确换算 (mx={mx}, my={my}, 预期 50.0, 50.0)")

# --- 测试 2: 右侧页签条避让 ---
ev_tabstrip = MockEvent(panel_w + 5, 500)
loc_tab = runtime._locate(ctx, ev_tabstrip)
check(loc_tab is None, "落在右侧 Tab Strip 上必须返回 None 予以放行给 Blender")

# --- 测试 3: 超出边界放行 ---
ev_left = MockEvent(-10, 500)
check(runtime._locate(ctx, ev_left) is None, "超出左边界返回 None")

ev_top = MockEvent(50, 950) # 距底 950 > 900
check(runtime._locate(ctx, ev_top) is None, "超出顶边界返回 None")

# --- 测试 4: 点击页签切换 ---
tab_items = [it for it in out["items"] if it[0] == "hit" and str(it[5]).startswith("tab:")]
check(len(tab_items) >= 2, f"找到页签命中项（数量 {len(tab_items)}）")

# 点击设置页签
tab_set = tab_items[1]
tx = tab_set[1] + tab_set[3] * 0.5
ty_logic = tab_set[2] + tab_set[4] * 0.5
# 换算回 mouse_region_y (距底)
ty_mouse = rg.height - ty_logic

ev_click_tab1 = MockEvent(tx, ty_mouse)
ret = runtime.handle_click(ctx, ev_click_tab1)
check(ret is True, "点击设置页签 handle_click 返回 True")
check(state.active_tab == 'SETTINGS', f"active_tab 切换为 SETTINGS（实际: {state.active_tab}）")

# 点击对话页签
tab_chat = tab_items[0]
cx = tab_chat[1] + tab_chat[3] * 0.5
cy_logic = tab_chat[2] + tab_chat[4] * 0.5
cy_mouse = rg.height - cy_logic

ev_click_tab0 = MockEvent(cx, cy_mouse)
ret = runtime.handle_click(ctx, ev_click_tab0)
check(ret is True, "点击对话页签 handle_click 返回 True")
check(state.active_tab == 'CHAT', f"active_tab 切换回 CHAT（实际: {state.active_tab}）")

# --- 测试 5: 点击输入框聚焦 ---
inwrap_items = [it for it in out["items"] if it[0] == "hit" and it[5] == "hover:inwrap"]
check(len(inwrap_items) == 1, "找到输入框命中项")
if inwrap_items:
    iw = inwrap_items[0]
    ix = iw[1] + iw[3] * 0.5
    iy_logic = iw[2] + iw[4] * 0.5
    iy_mouse = rg.height - iy_logic
    runtime.FOCUS[0] = False
    ev_click_in = MockEvent(ix, iy_mouse)
    ret_in = runtime.handle_click(ctx, ev_click_in)
    check(ret_in is True, "点击输入框 handle_click 返回 True")
    check(runtime.FOCUS[0] is True, "点击输入框激活 FOCUS[0] == True")

# --- 测试 6: 键盘打字 ---
ev_key_a = MockEvent(0, 0, ev_type='A', val='PRESS', uni='A')
ret_type = runtime.handle_typing(ctx, ev_key_a)
check(ret_type is True, "输入字符 'A' handle_typing 返回 True")
check(state.prompt == "A", f"prompt 变为 'A'（实际: {repr(state.prompt)}）")

ev_key_b = MockEvent(0, 0, ev_type='B', val='PRESS', uni='B')
runtime.handle_typing(ctx, ev_key_b)
check(state.prompt == "AB", f"追加字符 'B' prompt 变为 'AB'（实际: {repr(state.prompt)}）")

ev_back = MockEvent(0, 0, ev_type='BACK_SPACE', val='PRESS')
runtime.handle_typing(ctx, ev_back)
check(state.prompt == "A", f"退格后 prompt 变为 'A'（实际: {repr(state.prompt)}）")

ev_esc = MockEvent(0, 0, ev_type='ESC', val='PRESS')
runtime.handle_typing(ctx, ev_esc)
check(runtime.FOCUS[0] is False, "按 ESC 释放焦点 FOCUS[0] == False")

# --- 测试 7: 点击按钮清空记录 ---
btn_clear = [it for it in out["items"] if it[0] == "hit" and it[5] == "act:clear"]
check(len(btn_clear) == 1, "找到清空记录按钮命中项")
if btn_clear:
    bc = btn_clear[0]
    bx = bc[1] + bc[3] * 0.5
    by_logic = bc[2] + bc[4] * 0.5
    by_mouse = rg.height - by_logic
    state.prompt = "测试文本"
    ev_clear = MockEvent(bx, by_mouse)
    ret_clear = runtime.handle_click(ctx, ev_clear)
    check(ret_clear is True, "点击清空记录按钮 handle_click 返回 True")

# --- 测试 8: tracker 面板切换分类 ---
runtime.set_active_category("Tool", sp)
check(runtime.is_panel_visible(sp, rg) is False, "切换为 Tool 分类后 is_panel_visible 返回 False")
runtime.set_active_category("AI 对话", sp)
check(runtime.is_panel_visible(sp, rg) is True, "切换回 AI 对话分类后 is_panel_visible 返回 True")

print(f"\nRESULT gui_interaction: {failed} failed, {passed} passed")
if failed > 0:
    sys.exit(1)
