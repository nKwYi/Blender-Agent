import bpy, os

def run():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.spaces.active.show_region_ui = True
    out = os.path.abspath("dev/out/native_sidebar.png")
    bpy.ops.screen.screenshot(filepath=out)
    bpy.ops.wm.quit_blender()

bpy.app.timers.register(run, first_interval=0.8)
