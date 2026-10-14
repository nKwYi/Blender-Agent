import re
import bpy

valid_icons = set(bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys())

with open('blender_deepseek_agent/ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

found_icons = re.findall(r"icon=['\"]([A-Z0-9_]+)['\"]", content)
invalid = [i for i in found_icons if i not in valid_icons]
print('INVALID ICONS FOUND IN ui.py:', set(invalid))
for inv in set(invalid):
    for line_num, line in enumerate(content.splitlines(), 1):
        if f"icon='{inv}'" in line or f'icon="{inv}"' in line:
            print(f"  Line {line_num}: {line.strip()}")
