from . import color_overlay
from .panel import (
    SKIN_PT_copy_skin,
    SKIN_PT_mirror_weights,
    SKIN_PT_sidebar,
    SKIN_PT_sidebar_advanced,
    SKIN_UL_influences,
    SKIN_UL_scene_bones,
)

classes = (
    SKIN_UL_influences,
    SKIN_UL_scene_bones,
    SKIN_PT_sidebar,
    SKIN_PT_sidebar_advanced,
    SKIN_PT_mirror_weights,
    SKIN_PT_copy_skin,
)



def _ui_ready():
    import bpy

    if bpy.app.background:
        return False
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False
    try:
        return len(wm.windows) > 0
    except Exception:
        return False


def _redraw_view3d():
    if not _ui_ready():
        return
    import bpy

    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def _boot_ui():
    import bpy

    if bpy.app.background:
        return None
    if not _ui_ready():
        return 0.5
    try:
        _redraw_view3d()
    except Exception:
        pass
    # Show All Influences defaults on (and is remembered across
    # sessions of the brush), but the RNA default never fires the
    # property's update callback — apply the native-heatmap hide once
    # at startup so the display is consistent from the first frame.
    try:
        from ..properties import _settings_from

        settings = _settings_from(bpy.context)
        obj = getattr(bpy.context, "active_object", None)
        if (
            settings is not None
            and bool(settings.show_all_influences)
            and not bool(settings.wp_opacity_stashed)
            and obj is not None
            and obj.type == 'MESH'
            and bpy.context.mode == 'PAINT_WEIGHT'
        ):
            from .color_overlay import set_native_heatmap_hidden

            set_native_heatmap_hidden(bpy.context, True)
    except Exception:
        pass
    return None


def register():
    import bpy

    for cls in classes:
        bpy.utils.register_class(cls)
    color_overlay.register()
    if not bpy.app.background:
        try:
            bpy.app.timers.register(_boot_ui, first_interval=1.0)
        except Exception:
            pass


def unregister():
    color_overlay.unregister()
    # Show All Influences / Wireframe are intentionally NOT reset here:
    # the values are the user's remembered display choice. The native
    # heatmap stash is restored by color_overlay.unregister().
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
