import bpy

class ModalKeyTest(bpy.types.Operator):
    bl_idname = "wm.modal_key_test"
    bl_label = "Modal Key Test"

    def modal(self, context, event):
        if event.type == 'ESC':
            return {'CANCELLED'}
        if event.value == 'PRESS':
            print(f"EVENT: type={event.type} unicode={repr(event.unicode)} ascii={repr(event.ascii)}")
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

bpy.utils.register_class(ModalKeyTest)
print("REGISTERED ModalKeyTest")
