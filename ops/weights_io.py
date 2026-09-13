"""Export / import per-vertex skin weight data (JSON file)."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..core.weights_io import export_skin_weights, import_skin_weights


class SKIN_OT_export_skin_weights(Operator, ExportHelper):
    """Save this mesh's skin weights as per-vertex JSON data."""

    bl_idname = "skin_tools.export_skin_weights"
    bl_label = "Export Skin Weights"
    bl_description = (
        "Write every vertex group's per-vertex weights to a JSON file. "
        "Groups are stored by name, weights per vertex index — usable as "
        "a backup or to transfer onto a mesh with matching vertex order"
    )
    bl_options = {'REGISTER'}

    filename_ext = ".json"
    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and bool(obj.vertex_groups)

    def execute(self, context):
        obj = context.active_object
        try:
            stats = export_skin_weights(obj, self.filepath)
        except (RuntimeError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Exported {stats['vertices']} vertices / {stats['groups']} groups",
        )
        return {'FINISHED'}


class SKIN_OT_import_skin_weights(Operator, ImportHelper):
    """Load per-vertex skin weight data onto the active mesh."""

    bl_idname = "skin_tools.import_skin_weights"
    bl_label = "Import Skin Weights"
    bl_description = (
        "Read a DV Skin per-vertex weights JSON file onto the active "
        "mesh. Groups are matched by name (missing ones are created), "
        "locked groups are protected, weights land per vertex index. "
        "Works in Object Mode and Weight Paint"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"
    filter_glob: StringProperty(
        default="*.json",
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        try:
            stats = import_skin_weights(context, obj, self.filepath)
        except (RuntimeError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if stats["mesh_vertices"] != stats["file_vertices"]:
            if stats.get("method") == "closest_vertex":
                self.report(
                    {'INFO'},
                    f"Vertex count differs (mesh {stats['mesh_vertices']} vs file "
                    f"{stats['file_vertices']}) — matched by closest vertex",
                )
            else:
                self.report(
                    {'WARNING'},
                    f"Vertex count differs (mesh {stats['mesh_vertices']} vs file "
                    f"{stats['file_vertices']}) — imported by index up to the smaller count",
                )
        self.report(
            {'INFO'},
            f"Imported weights onto {stats['vertices']} vertices / "
            f"{stats['groups']} groups",
        )
        return {'FINISHED'}
