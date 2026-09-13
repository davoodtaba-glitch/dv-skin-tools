from bpy.types import Operator

from ..core.weights import refresh_overlay
from ..properties import _settings_from
from ..ui.color_overlay import reroll_color_seed


class SKIN_OT_randomize_colors(Operator):
    bl_idname = "skin_tools.randomize_colors"
    bl_label = "Randomize Colors"
    bl_description = "Re-roll influence display colors. Does not change weights"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and bool(obj.vertex_groups)

    def execute(self, context):
        settings = _settings_from(context)
        if settings is None:
            return {'CANCELLED'}
        reroll_color_seed(settings)
        obj = context.active_object
        if obj is not None:
            refresh_overlay(context, obj)
        self.report({'INFO'}, "Influence colors randomized")
        return {'FINISHED'}
