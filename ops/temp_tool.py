"""Hold Shift to temporarily activate the DV Skin brush.

While Shift is held (Weight Paint mode, brush session not running) the
DV Skin workspace tool replaces whatever 3D View tool was active, so
Shift+drag paints with the smooth brush. On release the previous tool
returns; any DV Skin session started during the hold is shut down
again, keeping "temporary" honest.
"""

import bpy
from bpy.types import Operator

from ..properties import _settings_from
from .smooth_brush import _event_over_ui

_DVSKIN_TOOL = "skin_tools.smooth_brush_tool"


class SKIN_OT_shift_temp_tool(Operator):
    bl_idname = "skin_tools.shift_temp_tool"
    bl_label = "DV Skin (hold Shift)"
    bl_description = (
        "Temporarily activate the DV Skin brush while Shift is held; "
        "release Shift to return to the previous brush"
    )
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'PAINT_WEIGHT':
            return False
        settings = _settings_from(context)
        # Never fight the running brush session: it uses Shift itself.
        if settings is not None and settings.paint_active:
            return False
        return True

    def invoke(self, context, event):
        # Don't hijack Shift typed into sidebar fields / pressed over UI.
        if _event_over_ui(context, event):
            return {'PASS_THROUGH'}
        try:
            tool = context.workspace.tools.from_space_view3d_mode(context.mode)
            self._prev_tool = tool.identifier if tool is not None else "builtin.brush"
        except Exception:
            self._prev_tool = "builtin.brush"
        self._switched = False
        if self._prev_tool != _DVSKIN_TOOL:
            try:
                bpy.ops.wm.tool_set_by_id(name=_DVSKIN_TOOL)
                self._switched = True
            except Exception:
                return {'CANCELLED'}
        try:
            context.workspace.status_text_set(
                "DV Skin temporary  |  LMB paint  |  release Shift to return"
            )
        except Exception:
            pass
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _restore(self, context):
        settings = _settings_from(context)
        if self._switched:
            if settings is not None and settings.paint_active:
                # Temporary means temporary: close any session that was
                # started while Shift was held.
                try:
                    bpy.ops.skin_tools.smooth_paint_stop()
                except Exception:
                    pass
            try:
                bpy.ops.wm.tool_set_by_id(name=self._prev_tool)
            except Exception:
                pass
            self._switched = False
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass

    def modal(self, context, event):
        if context.mode != 'PAINT_WEIGHT':
            self._restore(context)
            return {'FINISHED'}
        if event.type == 'LEFT_SHIFT' and event.value == 'RELEASE':
            self._restore(context)
            return {'FINISHED'}
        # Everything else (mouse moves, clicks that paint via the DV Skin
        # tool keymap, wheel zoom) passes through while we wait.
        return {'PASS_THROUGH'}


classes = (SKIN_OT_shift_temp_tool,)
