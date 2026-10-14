import bpy

def run():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.spaces.active.show_region_ui = True
                for r in a.regions:
                    if r.type == 'UI':
                        print("UI Region: x=%d, y=%d, w=%d, h=%d, view2d=(%f,%f,%f,%f)" % (
                            r.x, r.y, r.width, r.height,
                            r.view2d.region_to_view(0, 0)[0], r.view2d.region_to_view(0, 0)[1],
                            r.view2d.region_to_view(r.width, r.height)[0], r.view2d.region_to_view(r.width, r.height)[1]
                        ))
    bpy.ops.wm.quit_blender()

bpy.app.timers.register(run, first_interval=0.5)
