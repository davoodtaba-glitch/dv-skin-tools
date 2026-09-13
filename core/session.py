"""Start/stop the DV Skin tool as one session."""

from __future__ import annotations

import bpy


def restore_builtin_brush(context):
    try:
        bpy.ops.wm.tool_set_by_id(name="builtin.brush")
    except Exception:
        pass


def shutdown_tool(context, *, restore_tool=True):
    """Turn off paint modal, overlay, heatmap override, and custom wheel.

    The Show All Influences / Wireframe toggles are deliberately left
    alone: the colored overlay's draw handler stays registered for the
    whole addon session, so the display stays consistent after the
    brush exits, and the user's choice is remembered across
    disable/enable cycles. Only the Object-Mode auto-exit
    (color_overlay._auto_exit_show_all) may clear them, and it stashes
    the values for restore_display_state() first.
    """
    from ..properties import _settings_from
    from ..ui.color_overlay import set_native_heatmap_hidden

    settings = _settings_from(context)
    if settings is not None:
        settings.paint_active = False
        if not settings.show_all_influences and settings.wp_opacity_stashed:
            # Toggle was switched off mid-session; make sure the native
            # heatmap/visibility restore ran (its update callback did it
            # already — this is the belt-and-braces fallback).
            set_native_heatmap_hidden(context, False)
    try:
        if context.window:
            context.window.cursor_modal_restore()
    except Exception:
        pass
    workspace = getattr(context, "workspace", None)
    if workspace is not None:
        workspace.status_text_set(None)
    if restore_tool:
        restore_builtin_brush(context)
