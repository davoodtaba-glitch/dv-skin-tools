from bpy.types import Operator

from ..core.mesh_data import deform_group_indices, object_armature
from ..core.mirror import mirror_weights
from ..core.weights import refresh_overlay
from ..core.weight_undo import push_current


class SKIN_OT_mirror_weights(Operator):
    bl_idname = "skin_tools.mirror_weights"
    bl_label = "Mirror Weights"
    bl_description = (
        "Mirror skin weights across the local X axis, flipping .L/.R bone "
        "names. Pick the copy direction and pair-distance threshold below. "
        "Pairs vertices on the rest mesh, so it works even when the "
        "armature is posed and the model is not in a mirror pose"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        return object_armature(obj) is not None

    def execute(self, context):
        obj = context.active_object
        group_indices = deform_group_indices(obj)
        if not group_indices:
            self.report({'ERROR'}, "No deform vertex groups")
            return {'CANCELLED'}

        settings = getattr(context.window_manager, "skin_tools", None)
        direction = getattr(settings, "mirror_direction", 'HEAVIER') if settings else 'HEAVIER'
        threshold = float(getattr(settings, "mirror_threshold", 0.0) or 0.0) if settings else 0.0
        pattern = str(getattr(settings, "mirror_pattern", "") or "") if settings else ""

        push_current(obj, group_indices, "mirror")
        count = mirror_weights(obj, group_indices, direction=direction, threshold=threshold, pattern=pattern)
        if count == 0:
            self.report({'WARNING'}, "No mirror pairs found within the threshold or weights already symmetric")
            return {'CANCELLED'}

        refresh_overlay(context, obj)
        label = {
            'POS_TO_NEG': "+X to -X",
            'NEG_TO_POS': "-X to +X",
        }.get(direction, "heavier side")
        self.report({'INFO'}, f"Mirrored weights ({label}) on {count} vertices")
        return {'FINISHED'}
