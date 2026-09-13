from bpy.types import WorkSpaceTool
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d

from ..properties import _settings_from
from . import overlay
from .panel import _draw_settings


class SKIN_TL_smooth_brush(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'PAINT_WEIGHT'
    bl_idname = "skin_tools.smooth_brush_tool"
    bl_label = "DV Skin"
    bl_description = (
        "DV Skin multi-influence brush\n"
        "Smooth, sharpen, stitch, replace, add, remove — all bones, Maya-style"
    )
    bl_icon = "brush.paint_weight.blur"
    bl_widget = None
    bl_keymap = (
        (
            "skin_tools.smooth_paint",
            {"type": 'LEFTMOUSE', "value": 'PRESS'},
            {"properties": [("idle_start", False)]},
        ),
        (
            "skin_tools.smooth_paint",
            {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
            {"properties": [("idle_start", False)]},
        ),
    )

    def draw_settings(context, layout, _tool):
        settings = _settings_from(context)
        if settings is None:
            return
        if settings.paint_active:
            from ..core.paint import mode_label
            layout.alert = True
            layout.label(text=f"{mode_label(settings.mode)} ON")
            layout.operator("skin_tools.smooth_paint_stop", text="", icon='CANCEL')
        _draw_settings(layout, settings, header=True)

    def draw_cursor(context, _tool, xy):
        settings = _settings_from(context)
        if settings is None:
            return
        region = context.region
        rv3d = getattr(context.space_data, "region_3d", None)
        obj = context.active_object
        hit = None
        if obj is not None and region is not None and rv3d is not None:
            origin = region_2d_to_origin_3d(region, rv3d, xy)
            direction = region_2d_to_vector_3d(region, rv3d, xy)
            inv = obj.matrix_world.inverted()
            ok, loc, _n, _i = obj.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())
            if ok:
                hit = obj.matrix_world @ loc
        radius_px = overlay.world_radius_to_px(region, rv3d, hit, settings.radius)
        overlay.draw_brush_cursor(xy, radius_px, overlay.mode_color(settings.mode), settings.intensity)
