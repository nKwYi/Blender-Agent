"""测试新增特性：独立合集管理、无 AI_ 前缀、父子合集结构、友好步骤耗时、撤销恢复提示词与动效组件。
"""
import sys
import os
import bpy

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

from blender_deepseek_agent.collection_mgr import extract_clean_name, organize_task_collection
from blender_deepseek_agent.ui import friendly_step_summary, format_duration, get_current_action_text, SPINNERS
from blender_deepseek_agent import state
from blender_deepseek_agent.state import Run
from blender_deepseek_agent.worker import CONTROLLER

passed = 0
failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} :: {detail}")

print("--- 开始测试命名清洗逻辑 ---")
check("提取茶杯命名", extract_clean_name("请帮我制作一个精美的白瓷茶杯") == "精美的白瓷茶杯" or extract_clean_name("制作一个白瓷茶杯") == "白瓷茶杯", extract_clean_name("制作一个白瓷茶杯"))
check("提取沙发命名", extract_clean_name("在场景中搭建一套现代双人沙发，带靠垫") == "现代双人沙发", extract_clean_name("在场景中搭建一套现代双人沙发，带靠垫"))
check("严禁包含 AI_ 前缀", not extract_clean_name("制作一个白瓷茶杯").startswith("AI_"))
check("默认回退命名", extract_clean_name("") == "三维模型")

print("--- 开始测试合集归档逻辑 (<10 物体) ---")
# 清空当前场景中所有物体与合集
bpy.ops.wm.read_factory_settings(use_empty=True)

# 创建 3 个测试物体
objs_simple = []
for i in range(3):
    mesh = bpy.data.meshes.new(f"CupPart_{i}")
    obj = bpy.data.objects.new(f"CupPart_{i}", mesh)
    bpy.context.scene.collection.objects.link(obj)
    objs_simple.append(obj.name)

col_name = organize_task_collection("请制作一个白瓷茶杯", objs_simple)
check("合集名不含 AI_ 前缀", not col_name.startswith("AI_"), col_name)
check("合集名与提取名匹配", col_name == "白瓷茶杯", col_name)
target_col = bpy.data.collections.get(col_name)
check("合集已创建并链接至场景根合集", target_col is not None and target_col.name in bpy.context.scene.collection.children)
check("所有 3 个物体已归入该合集", all(name in target_col.objects for name in objs_simple))
check("物体已从根合集解除链接", all(name not in bpy.context.scene.collection.objects for name in objs_simple))

print("--- 开始测试合集归档逻辑 (>=10 物体，双层父子结构) ---")
bpy.ops.wm.read_factory_settings(use_empty=True)
objs_complex = []
for i in range(12):
    mesh = bpy.data.meshes.new(f"VillaPart_{i}")
    obj = bpy.data.objects.new(f"VillaPart_{i}", mesh)
    bpy.context.scene.collection.objects.link(obj)
    objs_complex.append(obj.name)

complex_col_name = organize_task_collection("搭建现代化双层别墅", objs_complex)
check("父合集命名正确", complex_col_name == "现代化双层别墅", complex_col_name)
parent_col = bpy.data.collections.get(complex_col_name)
check("父合集存在", parent_col is not None)
child_names = [c.name for c in parent_col.children]
check("包含 01_主体结构 子合集", any("01_主体结构" in n for n in child_names), child_names)
check("包含 02_构件与细节 子合集", any("02_构件与细节" in n for n in child_names), child_names)

# 验证物体是否分配在子合集中
sub1 = next(c for c in parent_col.children if "01_主体结构" in c.name)
sub2 = next(c for c in parent_col.children if "02_构件与细节" in c.name)
check("前半部分分配给主体结构", len(sub1.objects) == 6)
check("后半部分分配给构件细节", len(sub2.objects) == 6)
check("物体已从根合集解除链接", all(name not in bpy.context.scene.collection.objects for name in objs_complex))

print("--- 开始测试友好耗时与步骤格式化 ---")
check("耗时格式化 - 秒", format_duration(45) == "45秒", format_duration(45))
check("耗时格式化 - 分秒", format_duration(75) == "1分15秒", format_duration(75))
check("耗时格式化 - 0秒", format_duration(0) in ("不足1秒", "0秒"), format_duration(0))

s1 = friendly_step_summary({"name": "create_primitive", "arguments": '{"type": "cylinder"}'})
check("基础模型步骤翻译", "圆柱体" in s1, s1)

s2 = friendly_step_summary({"name": "set_material", "arguments": '{"object_name": "Cup", "color": [1,0,0]}'})
check("材质赋予步骤翻译", "材质" in s2, s2)

s3 = friendly_step_summary({"name": "execute_blender_code", "arguments": '{"code": "import bpy..."}'})
check("执行代码步骤翻译", "程序化" in s3 or "精密几何" in s3 or "拓扑" in s3, s3)

print("--- 开始测试动效文本生成 ---")
test_run = Run("测试")
test_run.phase = state.Phase.REQUESTING
test_run.elapsed = 5.2
txt = get_current_action_text(test_run)
check("模型请求中状态文本包含秒数", "5秒" in txt, txt)
check("包含具体动作描述", "构思" in txt or "三维" in txt, txt)

print("--- 开始测试撤销回滚与提示词恢复 ---")
# 注册扩展属性
from blender_deepseek_agent.ui import register, unregister
try:
    register()
except Exception:
    pass

scene = bpy.context.scene
agent_prop = scene.deepseek_agent

# 模拟发送提示词与完成状态
fake_prompt = "请制作一个精致的马克杯"
agent_prop.prompt = "" # 用户发送后输入框被清空
CONTROLLER.run = Run(fake_prompt)
CONTROLLER.run.phase = state.Phase.COMPLETED
CONTROLLER.run.collection_name = "精致的马克杯"
# 模拟向对话流写入用户和 AI 消息
u_item = agent_prop.history.add()
u_item.role = "你"
u_item.text = fake_prompt
u_item.raw_prompt = fake_prompt

ai_item = agent_prop.history.add()
ai_item.role = "AI"
ai_item.text = "已完成创建"
ai_item.collection_name = "精致的马克杯"

check("撤销前 prompt 为空", agent_prop.prompt == "")
check("撤销前 history 包含 2 条消息", len(agent_prop.history) == 2)

# 触发撤销算子
bpy.ops.deepseek.undo_task()

check("撤销后 prompt 恢复为上一次输入的提示词", agent_prop.prompt == fake_prompt, agent_prop.prompt)
check("撤销后 history 清空了对应消息", len(agent_prop.history) == 0, len(agent_prop.history))

print("--- 开始测试资产与参数提取器 (Artifact Inspector) ---")
from blender_deepseek_agent.artifact_inspector import inspect_task_artifacts
# 创建一个带修改器与材质的测试网格
bpy.ops.wm.read_factory_settings(use_empty=True)
agent_prop = bpy.context.scene.deepseek_agent
mesh_test = bpy.data.meshes.new("Cup_Body")
obj_test = bpy.data.objects.new("Cup_Body", mesh_test)
bpy.context.scene.collection.objects.link(obj_test)

# 添加修改器
mod = obj_test.modifiers.new("Subsurf", 'SUBSURF')
mod.render_levels = 3

# 添加材质
mat_test = bpy.data.materials.new("Mat_WhitePorcelain")
mat_test.use_nodes = True
obj_test.data.materials.append(mat_test)

art_result = inspect_task_artifacts(["Cup_Body"])
check("提取到对象列表", len(art_result["objects"]) >= 1)
check("对象包含正确 Tag", art_result["objects"][0]["tag"] == "Mesh")
check("提取到修改器栈", any("Subdivision" in m for m in art_result["modifiers"]))
check("提取到材质参数", any("Base Color" in k for k, v in art_result["materials"]))

print("--- 开始测试快捷建议胶囊 (Quick Action Pills) ---")
bpy.ops.deepseek.quick_pill(action="修改尺寸")
check("快捷胶囊填入修改尺寸提示词", "修改当前模型的尺寸为" in agent_prop.prompt, agent_prop.prompt)

bpy.ops.deepseek.quick_pill(action="导出文件")
check("常驻导出胶囊填入导出提示词", "导出为 glTF" in agent_prop.prompt, agent_prop.prompt)

print("--- 结构化折叠与结果分组切换（自绘层 dispatch 通路）---")
# 原生 DEEPSEEK_OT_toggle_card / show_card_* 已在 GPU 自绘改造中退役：
# panel.py 不再读 show_card_*，折叠改由 show_result_list + "collapse:objects" 命中 id 驱动。
# 这里改为端到端走 runtime.dispatch，即自绘层真实点击走的同一条通路。
from blender_deepseek_agent import runtime as RT

check("初始状态对象清单折叠", agent_prop.show_result_list is False)
RT.dispatch(bpy.context, "collapse:objects")
check("点击展开后对象清单展开", agent_prop.show_result_list is True)
RT.dispatch(bpy.context, "collapse:objects")
check("再次点击后对象清单恢复折叠", agent_prop.show_result_list is False)

check("初始结果分组为新增对象", agent_prop.result_tab == 'OBJECTS')
RT.dispatch(bpy.context, "qt:PARAMS")
check("结果分组切到参数详情", agent_prop.result_tab == 'PARAMS')
RT.dispatch(bpy.context, "qt:OBJECTS")
check("结果分组切回新增对象", agent_prop.result_tab == 'OBJECTS')

print("--- 开始测试会话主题自适应提取 (Session Topic) ---")
from blender_deepseek_agent.ui import push_history
push_history(agent_prop, "你", "制作一个精美茶杯", raw_prompt="制作一个精美茶杯")
check("会话主题自适应提取为茶杯建模", "茶杯建模" in agent_prop.session_topic, agent_prop.session_topic)

print(f"\n==========================================")
print(f"RESULT new_features: {failed} failed, {passed} passed")
print(f"==========================================")

if failed > 0:
    sys.exit(1)
