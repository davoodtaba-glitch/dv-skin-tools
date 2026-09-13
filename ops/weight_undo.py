from bpy.types import Operator

from ..core import weight_undo


class SKIN_OT_weight_undo(Operator):
    bl_idname = "skin_tools.weight_undo"
    bl_label = "Undo DV Skin"
    bl_description = "Undo the last DV Skin stroke, flood, or bind. Overlay stays on"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return weight_undo.can_undo()

    def execute(self, context):
        if not weight_undo.undo(context):
            return {'CANCELLED'}
        self.report({'INFO'}, "Undo DV Skin")
        return {'FINISHED'}


class SKIN_OT_weight_redo(Operator):
    bl_idname = "skin_tools.weight_redo"
    bl_label = "Redo DV Skin"
    bl_description = "Redo the last undone DV Skin edit. Overlay stays on"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return weight_undo.can_redo()

    def execute(self, context):
        if not weight_undo.redo(context):
            return {'CANCELLED'}
        self.report({'INFO'}, "Redo DV Skin")
        return {'FINISHED'}
