# -*- coding: utf-8 -*-
import bpy

class TEST_PT_probe(bpy.types.Panel):
    bl_label = "Probe"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Test"

    def draw(self, context):
        layout = self.layout
        # Test split with two columns
        sp = layout.split(factor=0.2)
        c1 = sp.column() # empty left column (20% indent)
        c2 = sp.column() # right column (80% width)
        c2.label(text="This is right-aligned content")

        # Test row alignment
        r = layout.row()
        r.alignment = 'RIGHT'
        r.label(text="Row alignment RIGHT")

bpy.utils.register_class(TEST_PT_probe)
print("TEST_PT_probe registered successfully")
