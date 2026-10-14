import bpy

def run():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                sp = a.spaces.active
                print("SpaceView3D properties:")
                for k in dir(sp):
                    if 'category' in k or 'panel' in k or 'tab' in k or 'sidebar' in k:
                        print("  ", k, getattr(sp, k, None))
                for r in a.regions:
                    if r.type == 'UI':
                        print("Region UI properties:")
                        for k in dir(r):
                            if 'category' in k or 'panel' in k or 'tab' in k:
                                print("  ", k, getattr(r, k, None))
    bpy.ops.wm.quit_blender()

bpy.app.timers.register(run, first_interval=0.5)
