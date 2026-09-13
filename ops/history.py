"""One undo step per brush stroke. VertexGroup writes are only undoable
inside an operator with bl_options={'UNDO'}."""

from bpy.types import Operator

from ..core.weights import refresh_overlay, write_weights

pending = None


class SKIN_OT_history_step(Operator):
    bl_idname = "skin_tools.history_step"
    bl_label = "DV Skin"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        global pending
        data = pending
        pending = None
        if not data:
            return {'CANCELLED'}
        obj = data["obj"]
        if obj is None:
            return {'CANCELLED'}
        write_weights(
            obj,
            data["groups"],
            data["weights"],
            data["dirty"],
            previous=None,
            prune=data.get("prune", 1e-4),
            locked=data.get("locked"),
        )
        refresh_overlay(context, obj)
        return {'FINISHED'}


def commit_stroke(context, obj, group_indices, start_weights, end_weights, dirty, prune, locked):
    """Restore pre-stroke mesh, then write the result inside an UNDO operator."""
    import numpy as np
    import bpy

    global pending
    if dirty is None:
        return
    dirty = np.unique(np.asarray(dirty, dtype=np.int32))
    if dirty.size == 0:
        return
    write_weights(
        obj,
        group_indices,
        start_weights,
        dirty,
        previous=end_weights,
        prune=prune,
        locked=locked,
    )
    pending = {
        "obj": obj,
        "groups": group_indices,
        "weights": end_weights,
        "dirty": dirty,
        "prune": prune,
        "locked": locked,
    }
    try:
        bpy.ops.skin_tools.history_step()
    except Exception:
        # Fallback: write end weights directly so the stroke result is
        # preserved even if the undo step could not be created.
        write_weights(
            obj, group_indices, end_weights, dirty,
            previous=start_weights, prune=prune, locked=locked,
        )
        refresh_overlay(context, obj)
