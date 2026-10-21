# -*- coding: utf-8 -*-
import bpy

# Create a temporary panel and call draw
class Dummy:
    pass

class TEST_PT_split(bpy.types.Panel):
    bl_label = "Split Test"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Test"

    def draw(self, context):
        pass

bpy.utils.register_class(TEST_PT_split)

# Instantiate and check layout
# In Blender, we can test UILayout methods via an operator or a panel draw
class TEST_OT_split(bpy.types.Operator):
    bl_idname = "test.split_probe"
    bl_label = "Probe"

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        sp = self.layout.split(factor=0.2)
        print("REAL BLENDER sp:", type(sp))
        c1 = sp.column()
        print("REAL BLENDER c1:", type(c1))
        c2 = sp.column()
        print("REAL BLENDER c2:", type(c2))
        c2.label(text="In C2!")

bpy.utils.register_class(TEST_OT_split)
# Call operator invoke popup or invoke
try:
    bpy.ops.test.split_probe('INVOKE_DEFAULT')
except Exception as e:
    print("Invoke err:", e)
