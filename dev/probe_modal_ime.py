import bpy

events_log = []

class ModalIMEProbe(bpy.types.Operator):
    bl_idname = "wm.modal_ime_probe"
    bl_label = "Modal IME Probe"

    def modal(self, context, event):
        if event.type == 'ESC':
            print("IME PROBE LOG:", events_log)
            return {'CANCELLED'}
        if event.value == 'PRESS':
            events_log.append({
                "type": event.type,
                "unicode": repr(event.unicode),
                "ascii": repr(event.ascii),
            })
            print(f"KEY: {event.type} u={repr(event.unicode)} a={repr(event.ascii)}")
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

bpy.utils.register_class(ModalIMEProbe)
print("REGISTERED ModalIMEProbe")
