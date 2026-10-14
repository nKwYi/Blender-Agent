"""变更回执与恢复能力。

三件事必须分开说，不能混成一句“可撤销”：
  1) 场景差异摘要 —— 真实统计，不是猜的
  2) Blender 全局 Undo 是否可用（且我们是否真的推了边界）
  3) 任务级回滚点 —— 当前版本没有实现，必须显示“未提供”
"""
import bpy

FIELDS = ("objects", "materials", "meshes", "vertices")


def snapshot():
    objects = bpy.context.scene.objects
    return {
        "objects": len(objects),
        "names": {o.name for o in objects},
        "materials": len(bpy.data.materials),
        "meshes": len(bpy.data.meshes),
        "vertices": sum(len(o.data.vertices) for o in objects if o.type == 'MESH'),
    }


def diff(before, after):
    lines = []
    for key in ("objects", "materials", "meshes"):
        if before[key] != after[key]:
            lines.append(f"{key}: {before[key]} → {after[key]}")
    if before["vertices"] != after["vertices"]:
        lines.append(f"顶点数: {before['vertices']:,} → {after['vertices']:,}")
    added = sorted(after["names"] - before["names"])
    removed = sorted(before["names"] - after["names"])
    if added:
        lines.append("新增物体: " + ", ".join(added[:6]) + ("…" if len(added) > 6 else ""))
    if removed:
        lines.append("移除物体: " + ", ".join(removed[:6]) + ("…" if len(removed) > 6 else ""))
    return lines


class Receipt:
    def __init__(self):
        self.before = snapshot()
        self.lines = []
        self.changed = False
        self.boundary_pushed = False
        self.undo_enabled = False

    @property
    def added_names(self):
        after = snapshot()
        return sorted(after["names"] - self.before["names"])

    def refresh(self):
        after = snapshot()
        self.lines = diff(self.before, after)
        self.changed = bool(self.lines)
        self.undo_enabled = bool(bpy.context.preferences.edit.use_global_undo)
        return self.lines

    def push_boundary(self):
        """在第一次写操作前推一个 undo 边界；实测：推了边界后 exec 写入也能被 undo 回退。"""
        if self.boundary_pushed or bpy.app.background:
            return self.boundary_pushed
        try:
            bpy.ops.ed.undo_push(message="AI 任务前")
            self.boundary_pushed = True
        except Exception:
            self.boundary_pushed = False
        return self.boundary_pushed

    def recovery_lines(self):
        """恢复能力：只报真实状态，不做无法兑现的承诺。"""
        self.refresh()
        out = []
        if not self.changed:
            out.append("场景未改变")
        if bpy.app.background:
            out.append("恢复：无头模式不提供 Undo（本次改动无法用 Ctrl+Z 退回）")
        elif self.boundary_pushed and self.undo_enabled:
            out.append("恢复：已建立 Undo 边界，可试“撤销本次任务”")
        elif self.undo_enabled:
            out.append("恢复：全局 Undo 开启，但本次未建立边界")
        else:
            out.append("恢复：全局 Undo 已关闭，改动可能无法退回")
        out.append("任务级回滚点：未提供")
        return out
