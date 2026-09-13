from .bind import (
    SKIN_OT_add_selected_influences,
    SKIN_OT_bind_nearest,
    SKIN_OT_remove_selected_bones,
)
from .colors import SKIN_OT_randomize_colors
from .copy_skin import SKIN_OT_copy_skin_weights, SKIN_OT_remove_empty_groups
from .flood import SKIN_OT_smooth_flood
from .history import SKIN_OT_history_step
from .mirror import SKIN_OT_mirror_weights
from .mode import SKIN_OT_enter_weight_paint
from .pick_influence import (
    SKIN_OT_bones_deselect_all,
    SKIN_OT_bones_select_invert,
    SKIN_OT_pick_influence,
)
from .smooth_brush import SKIN_OT_smooth_paint, SKIN_OT_smooth_paint_stop
from .temp_tool import SKIN_OT_shift_temp_tool
from .toggles import (
    SKIN_OT_start_tool,
    SKIN_OT_toggle_show_influences,
    SKIN_OT_toggle_x_mirror,
    SKIN_OT_toggle_xray_all,
)
from .weight_undo import SKIN_OT_weight_redo, SKIN_OT_weight_undo
from .weights_io import SKIN_OT_export_skin_weights, SKIN_OT_import_skin_weights

classes = (
    SKIN_OT_smooth_flood,
    SKIN_OT_smooth_paint,
    SKIN_OT_smooth_paint_stop,
    SKIN_OT_bind_nearest,
    SKIN_OT_remove_selected_bones,
    SKIN_OT_add_selected_influences,
    SKIN_OT_mirror_weights,
    SKIN_OT_pick_influence,
    SKIN_OT_bones_deselect_all,
    SKIN_OT_bones_select_invert,
    SKIN_OT_enter_weight_paint,
    SKIN_OT_copy_skin_weights,
    SKIN_OT_remove_empty_groups,
    SKIN_OT_randomize_colors,
    SKIN_OT_history_step,
    SKIN_OT_weight_undo,
    SKIN_OT_weight_redo,
    SKIN_OT_export_skin_weights,
    SKIN_OT_import_skin_weights,
    SKIN_OT_start_tool,
    SKIN_OT_toggle_show_influences,
    SKIN_OT_toggle_xray_all,
    SKIN_OT_toggle_x_mirror,
    SKIN_OT_shift_temp_tool,
)

_addon_keymaps = []


def _register_keymap():
    import bpy

    wm = bpy.context.window_manager
    if wm is None:
        return False
    kc = wm.keyconfigs.addon
    if kc is None:
        return False
    if _addon_keymaps:
        return True
    km = kc.keymaps.new(name='Weight Paint', space_type='EMPTY')
    kmi = km.keymap_items.new('skin_tools.weight_undo', 'Z', 'PRESS', ctrl=True)
    _addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new(
        'skin_tools.weight_redo', 'Z', 'PRESS', ctrl=True, shift=True
    )
    _addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('skin_tools.pick_influence', 'S', 'PRESS')
    _addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('skin_tools.pick_influence', 'D', 'PRESS')
    kmi.properties.mode = 'SUBTRACT'
    _addon_keymaps.append((km, kmi))
    # Hold Shift: temporarily activate the DV Skin brush while no brush
    # session is running (poll filters the item out during a session).
    kmi = km.keymap_items.new('skin_tools.shift_temp_tool', 'LEFT_SHIFT', 'PRESS')
    _addon_keymaps.append((km, kmi))
    return True


def register():
    import bpy

    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background:
        if not _register_keymap():
            try:
                bpy.app.timers.register(_register_keymap, first_interval=0.2)
            except Exception:
                pass


def unregister():
    import bpy

    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
