import bpy
from bpy.types import Operator

from ..core.copy_skin import copy_skin_weights_multi
from ..properties import _settings_from


class SKIN_OT_remove_empty_groups(Operator):
    bl_idname = "skin_tools.remove_empty_groups"
    bl_label = "Remove Empty Groups"
    bl_description = (
        "Delete vertex groups that have no weights assigned on this mesh "
        "(works in Object Mode and Weight Paint)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and bool(obj.vertex_groups)

    def execute(self, context):
        obj = context.active_object
        used = set()
        for vert in obj.data.vertices:
            for elem in vert.groups:
                if elem.weight > 0.0:
                    used.add(elem.group)
        empty = [
            vg for vg in obj.vertex_groups
            if vg.index not in used and not vg.lock_weight
        ]
        if not empty:
            self.report({'INFO'}, "No empty vertex groups")
            return {'FINISHED'}
        # Snapshot the full group state so Ctrl+Z restores the deletion.
        from ..core.weight_undo import push_groups

        push_groups(obj, "groups")
        for vg in empty:
            obj.vertex_groups.remove(vg)
        self.report({'INFO'}, f"Removed {len(empty)} empty vertex groups")
        return {'FINISHED'}


class SKIN_OT_copy_skin_weights(Operator):
    bl_idname = "skin_tools.copy_skin_weights"
    bl_label = "Copy Skin Weights"
    bl_description = (
        "Copy skin weights from the source mesh(es) to the active mesh "
        "(Maya-style: closest point on surface, influence association, "
        "normalize). Sources: the picked Source mesh, or — with Use "
        "Selected as Sources — every other selected mesh, each "
        "contributing at the vertices nearest to it (a belt can follow "
        "both a shirt and the pants). Respects the vertex paint mask "
        "and locked groups"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        settings = _settings_from(context)
        if settings is None:
            return False
        if getattr(settings, "copy_use_selected_sources", False):
            return len(context.selected_objects) >= 2
        return settings.copy_skin_source is not None

    def execute(self, context):
        obj = context.active_object
        settings = _settings_from(context)
        if getattr(settings, "copy_use_selected_sources", False):
            sel = [
                o for o in context.selected_objects
                if o != obj and o.type == 'MESH'
            ]
            if not sel:
                self.report({'ERROR'}, "Select the source meshes plus the target")
                return {'CANCELLED'}
            srcs = sel
        else:
            if settings.copy_skin_source is None:
                self.report({'ERROR'}, "Pick a source mesh first")
                return {'CANCELLED'}
            srcs = [settings.copy_skin_source]
        if obj in srcs:
            self.report({'ERROR'}, "Source and target must be different meshes")
            return {'CANCELLED'}
        try:
            written = copy_skin_weights_multi(
                context,
                srcs,
                obj,
                surface=settings.copy_skin_surface,
                assoc=settings.copy_skin_assoc,
                normalize=settings.copy_skin_normalize,
            )
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        names = ", ".join(s.name for s in srcs)
        self.report({'INFO'}, f"Copied skin weights to {written} vertices from {names}")
        return {'FINISHED'}
