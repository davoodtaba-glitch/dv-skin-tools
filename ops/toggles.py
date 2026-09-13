"""Shortcut-friendly operators: tool start and settings toggles.

Blender's right-click "Assign Shortcut" entry only appears when
``WM_keymap_guess_opname`` resolves a keymap for the button's operator,
and that resolver matches by idname prefix (``WM_OT``, ``PAINT_OT``,
``VIEW3D_OT`` …). Custom ``skin_tools.*`` ids match nothing, so these
operators are registered under the ``paint.`` prefix
(``PAINT_OT_skin_*``) — the recognized prefix that routes assigned
shortcuts into the current editor/mode keymap (Weight Paint here).
"""

import bpy
from bpy.types import Operator

from ..properties import _settings_from


def _toggle_settings_prop(context, prop, label):
    """Flip a bool settings property; returns the new value or None."""
    settings = _settings_from(context)
    if settings is None:
        return None
    try:
        value = not bool(getattr(settings, prop))
        setattr(settings, prop, value)
    except Exception:
        return None
    return value


class SKIN_OT_start_tool(Operator):
    bl_idname = "paint.skin_start_tool"
    bl_label = "Start DV Skin"
    bl_description = (
        "Enter Weight Paint mode and activate the DV Skin smooth brush "
        "(right-click to Assign Shortcut or Add to Quick Favorites)"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and bool(obj.vertex_groups)

    def execute(self, context):
        if context.mode != 'PAINT_WEIGHT':
            obj = context.active_object
            try:
                if obj.mode == 'EDIT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            except Exception as exc:
                self.report({'ERROR'}, f"Could not enter Weight Paint: {exc}")
                return {'CANCELLED'}
        settings = _settings_from(context)
        if settings is not None and settings.paint_active:
            return {'FINISHED'}  # already running
        result = bpy.ops.skin_tools.smooth_paint(idle_start=True)
        if 'RUNNING_MODAL' not in result and 'FINISHED' not in result:
            self.report({'WARNING'}, "DV Skin brush did not start")
            return {'CANCELLED'}
        return {'FINISHED'}


class SKIN_OT_toggle_show_influences(Operator):
    bl_idname = "paint.skin_toggle_show_influences"
    bl_label = "Toggle Show All Influences"
    bl_description = (
        "Switch the multi-color Show All Influences display on or off "
        "(right-click to Assign Shortcut or Add to Quick Favorites)"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _settings_from(context) is not None

    def execute(self, context):
        value = _toggle_settings_prop(context, "show_all_influences", self.bl_label)
        if value is None:
            return {'CANCELLED'}
        return {'FINISHED'}


class SKIN_OT_toggle_xray_all(Operator):
    bl_idname = "paint.skin_toggle_xray_all"
    bl_label = "Toggle X-Ray All Bones"
    bl_description = (
        "Draw every bound bone through the mesh on or off "
        "(right-click to Assign Shortcut or Add to Quick Favorites)"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _settings_from(context) is not None

    def execute(self, context):
        value = _toggle_settings_prop(context, "bone_xray_all", self.bl_label)
        if value is None:
            return {'CANCELLED'}
        return {'FINISHED'}


class SKIN_OT_toggle_x_mirror(Operator):
    bl_idname = "paint.skin_toggle_x_mirror"
    bl_label = "Toggle Interactive Mirror Paint"
    bl_description = (
        "Interactive Mirror Paint on or off "
        "(right-click to Assign Shortcut or Add to Quick Favorites)"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _settings_from(context) is not None

    def execute(self, context):
        value = _toggle_settings_prop(context, "use_x_mirror", self.bl_label)
        if value is None:
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    SKIN_OT_start_tool,
    SKIN_OT_toggle_show_influences,
    SKIN_OT_toggle_xray_all,
    SKIN_OT_toggle_x_mirror,
)
