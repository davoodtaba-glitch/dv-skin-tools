import bpy
from bpy.types import Operator

from ..properties import restore_display_state


class SKIN_OT_enter_weight_paint(Operator):
    bl_idname = "skin_tools.enter_weight_paint"
    bl_label = "Go to Weight Paint"
    bl_description = (
        "Switch the active mesh to Weight Paint mode so the DV Skin "
        "brush and transfer tools are ready to use"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode != 'PAINT_WEIGHT'

    def execute(self, context):
        obj = context.active_object
        try:
            if obj.mode == 'EDIT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        except Exception as exc:
            self.report({'ERROR'}, f"Could not enter Weight Paint: {exc}")
            return {'CANCELLED'}
        # A previous session stashed Show All Influences / Wireframe when
        # it shut down; bring the user's display state back.
        restore_display_state(context)
        return {'FINISHED'}
