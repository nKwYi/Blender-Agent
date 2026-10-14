"""Blender 合集归档管理器。

规范：
1. 严禁加 'AI_' 等机械前缀，以实体命名（如 '白瓷茶杯', '现代双人沙发'）。
2. 当任务复杂涉及到 10 个以上物体时，自动采用双层父子合集结构（父合集为资产名，子合集按步骤或模块划分，如 '01_主体结构', '02_构件与细节'）。
3. 少于 10 个物体时直接放入单层命名合集中。
"""
import re
import bpy


def extract_clean_name(prompt, default="三维模型"):
    """从自然语言提示词中提取简洁自然的资产命名（无 AI 前缀）"""
    if not prompt:
        return default
    text = str(prompt).strip()
    # 去除起始常见祈使动词与口语
    text = re.sub(r"^(请|帮我|在场景中|请帮我|麻烦)?(生成|创建|建立|构建|制作|做一个|建一个|画一个|搭建|添加|设计)+", "", text).strip()
    # 去除后续修饰与多余标点
    text = re.sub(r"[，。！？,.!?;:：\n\r].*$", "", text).strip()
    # 去除量词，如“一个”、“一套”、“一组”、“只”
    text = re.sub(r"^(一[个套组只栋件本把面座双支瓶]|两[个套组栋件]|三[个套组]|多[个座套]|)\s*", "", text).strip()
    # 限制长度在 16 个字符以内
    clean = text[:16].strip()
    return clean if clean else default


def organize_task_collection(prompt, added_names, calls=None):
    """将新增物体自动归档到干净的独立合集中。"""
    if not added_names:
        return ""

    asset_name = extract_clean_name(prompt)
    parent_col = bpy.data.collections.get(asset_name)
    if parent_col is None:
        parent_col = bpy.data.collections.new(asset_name)
        bpy.context.scene.collection.children.link(parent_col)
    elif parent_col.name not in bpy.context.scene.collection.children.keys():
        try:
            bpy.context.scene.collection.children.link(parent_col)
        except Exception:
            pass

    count = len(added_names)
    if count < 10:
        # 简单任务 (< 10 物体)：单层归集
        for name in added_names:
            obj = bpy.data.objects.get(name)
            if obj:
                for c in list(obj.users_collection):
                    if c != parent_col:
                        try:
                            c.objects.unlink(obj)
                        except Exception:
                            pass
                if obj.name not in parent_col.objects:
                    parent_col.objects.link(obj)
    else:
        # 复杂任务 (>= 10 物体)：双层父子合集
        sub1_name = "01_主体结构"
        sub2_name = "02_构件与细节"
        sub1 = bpy.data.collections.get(f"{asset_name}_{sub1_name}") or bpy.data.collections.new(sub1_name)
        sub2 = bpy.data.collections.get(f"{asset_name}_{sub2_name}") or bpy.data.collections.new(sub2_name)
        for sub in (sub1, sub2):
            if sub.name not in parent_col.children.keys():
                parent_col.children.link(sub)

        half = count // 2
        for i, name in enumerate(added_names):
            obj = bpy.data.objects.get(name)
            if obj:
                target_sub = sub1 if i < half else sub2
                for c in list(obj.users_collection):
                    if c != target_sub:
                        try:
                            c.objects.unlink(obj)
                        except Exception:
                            pass
                if obj.name not in target_sub.objects:
                    target_sub.objects.link(obj)

    return parent_col.name
