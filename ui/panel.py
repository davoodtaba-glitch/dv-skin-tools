import bpy
from bpy.types import Panel, UIList

from ..core.mesh_data import deform_group_indices, object_armature
from ..core.paint import mode_label
from ..properties import _settings_from, ensure_radius

def _version_label():
    try:
        from .. import bl_info
        v = bl_info.get("version", (0, 0, 0))
        return "DV Skin Tools {}.{}.{}".format(*v)
    except Exception:
        return "DV Skin Tools"


PANEL_LABEL = _version_label()


def _section(layout, panel_id, title, default_closed=False):
    header, body = layout.panel(panel_id, default_closed=default_closed)
    header.label(text=title)
    return body


def _draw_settings(layout, settings, *, header=False):
    if header:
        layout.prop(settings, "mode", text="")
        layout.prop(settings, "intensity", text="I", slider=True)
        layout.prop(settings, "radius", text="R")
        if settings.mode in {'SMOOTH', 'SHARPEN', 'STITCH'}:
            layout.prop(settings, "iterations", text="N")
            if settings.mode != 'STITCH' and settings.sync_border_weights:
                layout.prop(settings, "stitch_threshold", text="T")
        return

    row = layout.row(align=True)
    row.prop_enum(settings, "mode", "SMOOTH")
    row.prop_enum(settings, "mode", "SHARPEN")
    row.prop_enum(settings, "mode", "STITCH")
    row = layout.row(align=True)
    row.prop_enum(settings, "mode", "REPLACE")
    row.prop_enum(settings, "mode", "ADD")
    row.prop_enum(settings, "mode", "REMOVE")

    split = layout.split(factor=0.3, align=True)
    split.operator("skin_tools.smooth_flood", text="Flood", icon='MOD_SMOOTH')
    split.operator(
        "paint.skin_toggle_x_mirror",
        text="Interactive Mirror Paint",
        icon='CHECKBOX_HLT' if settings.use_x_mirror else 'CHECKBOX_DEHLT',
        depress=bool(settings.use_x_mirror),
    )

    col = layout.column(align=True)
    col.prop(settings, "intensity", slider=True)
    if settings.mode in {'SMOOTH', 'SHARPEN', 'STITCH'}:
        col.prop(settings, "iterations")
    col.prop(settings, "radius")
    col.prop(settings, "falloff", text="Falloff")

    if settings.mode in {'SMOOTH', 'SHARPEN'}:
        col = layout.column(align=True)
        col.prop(settings, "neighbor_mode", text="Neighbors")
        if settings.neighbor_mode == 'VOLUME':
            col.prop(settings, "volume_radius")
        col.prop(settings, "only_existing")
        col.prop(settings, "skip_border_edges")
        col.prop(settings, "sync_border_weights")
    if settings.mode == 'STITCH' or (
        settings.mode in {'SMOOTH', 'SHARPEN'}
        and settings.sync_border_weights
    ):
        col = layout.column(align=True)
        col.prop(settings, "stitch_threshold")

    col = layout.column(align=True)
    col.prop(settings, "projection", text="Projection")
    col.prop(settings, "target", text="Target")


class SKIN_UL_influences(UIList):
    """Compact, filterable list of the mesh's deform bones."""

    def filter_items(self, context, data, propname):
        vgs = getattr(data, propname)
        n = len(vgs)
        helper = bpy.types.UI_UL_list
        if self.filter_name:
            flt_flags = helper.filter_items_by_name(
                self.filter_name, self.bitflag_filter_item, vgs, "name"
            )
        else:
            flt_flags = [self.bitflag_filter_item] * n
        if self.use_filter_invert:
            flt_flags = [0 if f else self.bitflag_filter_item for f in flt_flags]
        deform_names = None
        obj = context.active_object
        if obj is not None and obj.type == 'MESH':
            try:
                deform_names = {obj.vertex_groups[gi].name for gi in deform_group_indices(obj)}
            except Exception:
                deform_names = None
        if deform_names is not None:
            for i, vg in enumerate(vgs):
                if vg.name not in deform_names:
                    flt_flags[i] = 0
        flt_neworder = []
        if self.use_filter_sort_alpha:
            flt_neworder = helper.sort_items_by_name(vgs, "name")
        return flt_flags, flt_neworder

    def _pose_bone(self, context, name):
        """Pose bone matching a vertex-group name, for selection toggles."""
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return None
        try:
            arm = object_armature(obj)
        except Exception:
            return None
        if arm is None:
            return None
        return arm.pose.bones.get(name)

    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        pb = self._pose_bone(context, item.name)
        if pb is not None:
            # Checkbox = pose-bone selection: check several rows to
            # multi-select bones for Bind Nearest (Selected) and the
            # brush's Selected-Bones target.
            row.prop(pb, "select", text="", invert_checkbox=True)
        locked = bool(getattr(item, "lock_weight", False))
        row.label(text=item.name, translate=False, icon='LOCKED' if locked else 'BONE_DATA')


def _draw_influence_list(layout, obj, settings):
    """Compact, searchable influence list; the active group stays selected.

    The list height is user-adjustable, the search field filters bones by
    name, and picking a row selects the matching bone in the 3D viewport.
    """
    if obj is None:
        return
    rows = max(1, int(getattr(settings, "list_rows", 5)))
    col = layout.column(align=True)
    col.operator("skin_tools.add_selected_influences", text="Add Selected", icon='ADD')
    row = col.row(align=True)
    row.prop(settings, "live_select", text="Live Select", toggle=True, icon='RESTRICT_SELECT_ON')
    row.operator("skin_tools.bones_select_invert", text="", icon='CHECKBOX_HLT')
    row.operator("skin_tools.bones_deselect_all", text="", icon='X')
    col.prop(settings, "list_rows", text="Size", slider=True)
    box = col.box()
    box.template_list(
        "SKIN_UL_influences",
        "skin_influences",
        obj,
        "vertex_groups",
        obj.vertex_groups,
        "active_index",
        rows=rows,
        maxrows=rows,
    )


def _iter_scene_armatures(context):
    scene = getattr(context, "scene", None)
    seen = set()
    obj = getattr(context, "active_object", None)
    if obj is not None and obj.type == 'ARMATURE':
        seen.add(obj.name)
        yield obj
    elif obj is not None and obj.type == 'MESH':
        try:
            arm = object_armature(obj)
        except Exception:
            arm = None
        if arm is not None:
            seen.add(arm.name)
            yield arm
    if scene is None:
        return
    for o in scene.objects:
        if o.type == 'ARMATURE' and o.name not in seen:
            seen.add(o.name)
            yield o


def _deform_bone_names(arm):
    names = []
    try:
        bones = arm.data.bones
    except Exception:
        return names
    for bone in bones:
        try:
            if bone.use_deform:
                names.append(bone.name)
        except Exception:
            continue
    return names


def _sync_scene_bones(settings, context):
    parts = ["deform_only"]
    arms = list(_iter_scene_armatures(context))
    pairs = []
    for arm in arms:
        parts.append(arm.name)
        for name in _deform_bone_names(arm):
            parts.append(name)
            pairs.append((arm.name, name))
    sig = "\n".join(parts)
    if sig == getattr(settings, "scene_bones_sig", "") and len(settings.scene_bones) == len(pairs):
        return
    settings.scene_bones_sig = sig
    items = settings.scene_bones
    items.clear()
    for arm_name, name in pairs:
        it = items.add()
        it.name = name
        it.armature_name = arm_name


def _draw_all_bones_rollout(layout, context, settings):
    header, body = layout.panel("dv_skin_all_bones", default_closed=True)
    header.label(text="All Bones")
    if body is None:
        return
    _sync_scene_bones(settings, context)
    if not settings.scene_bones:
        body.label(text="No bones in the scene")
        return
    rows = max(1, int(getattr(settings, "list_rows", 5)))
    body.template_list(
        "SKIN_UL_scene_bones",
        "scene_bones",
        settings,
        "scene_bones",
        settings,
        "scene_bone_index",
        rows=rows,
        maxrows=rows,
    )


class SKIN_UL_scene_bones(UIList):
    def draw_filter(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="", icon='VIEWZOOM')
        row.prop(self, "use_filter_invert", text="", icon='ARROW_LEFTRIGHT')

    def filter_items(self, context, data, propname):
        self.use_filter_show = True
        items = getattr(data, propname)
        n = len(items)
        helper = bpy.types.UI_UL_list
        if self.filter_name:
            flt_flags = helper.filter_items_by_name(
                self.filter_name, self.bitflag_filter_item, items, "name"
            )
        else:
            flt_flags = [self.bitflag_filter_item] * n
        if self.filter_name and self.use_filter_invert:
            flt_flags = [0 if f else self.bitflag_filter_item for f in flt_flags]
        for i, item in enumerate(items):
            if not flt_flags[i]:
                continue
            arm = bpy.data.objects.get(item.armature_name)
            bone = None
            if arm is not None and arm.type == 'ARMATURE':
                try:
                    bone = arm.data.bones.get(item.name)
                except Exception:
                    bone = None
            if bone is None or not bone.use_deform:
                flt_flags[i] = 0
        flt_neworder = []
        if self.use_filter_sort_alpha:
            flt_neworder = helper.sort_items_by_name(items, "name")
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, index=0, flt_flag=0):
        row = layout.row(align=True)
        arm = bpy.data.objects.get(item.armature_name)
        pb = None
        if arm is not None and arm.type == 'ARMATURE':
            pb = arm.pose.bones.get(item.name)
        if pb is not None:
            row.prop(pb, "select", text="", invert_checkbox=True)
        row.label(text=item.name, translate=False, icon='BONE_DATA')


class SKIN_PT_sidebar(Panel):
    bl_label = PANEL_LABEL
    bl_idname = "SKIN_PT_sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DV Skin Tools"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        settings = _settings_from(context)
        if settings is None:
            layout.label(text="Enable DV Skin Tools in Preferences.")
            return
        if context.mode != 'PAINT_WEIGHT':
            layout.operator("skin_tools.enter_weight_paint", icon='BRUSH_DATA')
            return
        if obj is not None:
            ensure_radius(settings, obj)

        if settings.paint_active:
            box = layout.box()
            box.alert = True
            box.label(text=f"{mode_label(settings.mode)} brush active", icon='BRUSH_DATA')
            box.operator("skin_tools.smooth_paint_stop", text="Stop Brush", icon='CANCEL')
            col = box.column(align=True)
            col.scale_y = 0.85
            col.label(text="LMB paint  |  F radius")
            col.label(text="Esc / RMB stop")
        else:
            col = layout.column(align=True)
            op = col.operator("skin_tools.smooth_paint", text="Paint", icon='BRUSH_DATA')
            op.idle_start = True

        brush = _section(layout, "dv_skin_brush", "Brush")
        if brush:
            _draw_settings(brush, settings)

        skin = _section(layout, "dv_skin_influences", "Influences")
        if skin:
            row = skin.row(align=True)
            row.operator("skin_tools.bind_nearest", text="Bind Nearest", icon='BONE_DATA')
            row.operator("skin_tools.remove_selected_bones", text="Remove Selected")
            row.prop(settings, "bind_selected", text="", icon='RESTRICT_SELECT_ON', toggle=True)
            row.prop(settings, "bind_mirror", text="", icon='MOD_MIRROR', toggle=True)
            _draw_influence_list(skin, obj, settings)

        _draw_all_bones_rollout(layout, context, settings)

        display = _section(layout, "dv_skin_display", "Display")
        if display:
            col = display.column(align=True)
            col.prop(settings, "bone_xray", icon='XRAY')
            col.operator(
                "paint.skin_toggle_xray_all",
                text="X-Ray All Bones",
                icon='CHECKBOX_HLT' if settings.bone_xray_all else 'CHECKBOX_DEHLT',
                depress=bool(settings.bone_xray_all),
            )
            col.operator(
                "paint.skin_toggle_show_influences",
                text="Show All Influences",
                icon='CHECKBOX_HLT' if settings.show_all_influences else 'CHECKBOX_DEHLT',
                depress=bool(settings.show_all_influences),
            )
            if settings.show_all_influences:
                col.prop(settings, "overlay_opacity", slider=True)
                col.prop(settings, "overlay_wireframe")
                col.operator("skin_tools.randomize_colors", text="Randomize Colors", icon='FILE_REFRESH')


class SKIN_PT_sidebar_advanced(Panel):
    bl_label = "Advanced"
    bl_idname = "SKIN_PT_sidebar_advanced"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DV Skin Tools"
    bl_parent_id = "SKIN_PT_sidebar"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        # Visible in Weight Paint mode (where the brush lives) or while
        # a paint session is running - hidden the rest of the time.
        settings = _settings_from(context)
        if settings is not None and bool(settings.paint_active):
            return True
        return context.mode == 'PAINT_WEIGHT'

    def draw(self, context):
        settings = _settings_from(context)
        layout = self.layout
        col = layout.column(align=True)
        col.prop(settings, "front_faces_only")
        col.prop(settings, "airbrush")
        col.prop(settings, "use_pressure")
        col.prop(settings, "spacing", slider=True)
        col.separator()
        col.prop(settings, "max_influences")
        col.prop(settings, "prune")
        col.separator()
        col.prop(settings, "mirror_pattern", text="Mirror Pattern", icon='MOD_MIRROR')
        if settings is not None and (settings.mirror_pattern or "").strip():
            from ..core.mirror import describe_mirror_rule, parse_mirror_pattern

            rule = parse_mirror_pattern(settings.mirror_pattern)
            if rule is None:
                col.label(text="Not recognized — built-in .L/.R rules apply", icon='ERROR')
            else:
                col.label(text=f"Detected: {describe_mirror_rule(rule)}", icon='INFO')


class SKIN_PT_mirror_weights(Panel):
    """Mirror Weights sub-panel â€” collapsible, always available."""

    bl_label = "Mirror Skin Weights"
    bl_idname = "SKIN_PT_mirror_weights"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DV Skin Tools"
    bl_parent_id = "SKIN_PT_sidebar"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return SKIN_PT_sidebar.poll(context)

    def draw(self, context):
        settings = _settings_from(context)
        if settings is None:
            return
        col = self.layout.column(align=True)
        col.prop(settings, "mirror_direction", text="")
        col.prop(settings, "mirror_threshold")
        col.operator("skin_tools.mirror_weights", text="Mirror", icon='MOD_MIRROR')


class SKIN_PT_copy_skin(Panel):
    """Transfer Skin Weights sub-panel â€” copy, export, import. Collapsible."""

    bl_label = "Transfer Skin Weights"
    bl_idname = "SKIN_PT_copy_skin"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "DV Skin Tools"
    bl_parent_id = "SKIN_PT_sidebar"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return SKIN_PT_sidebar.poll(context)

    def draw(self, context):
        settings = _settings_from(context)
        if settings is None:
            return
        obj = context.active_object
        col = self.layout.column(align=True)
        col.label(text="Copy between meshes:")
        col.prop(settings, "copy_use_selected_sources", icon='OBJECT_DATAMODE')
        if settings.copy_use_selected_sources:
            n_src = sum(
                1 for o in context.selected_objects
                if o != obj and o.type == 'MESH'
            )
            tgt = obj.name if obj is not None else "-"
            col.label(
                text=f"{n_src} source(s) selected, target: {tgt}",
                icon='INFO',
            )
        else:
            col.prop(settings, "copy_skin_source")
        col.prop(settings, "copy_skin_surface", text="")
        col.prop(settings, "copy_skin_assoc", text="")
        col.prop(settings, "copy_skin_normalize")
        row = col.row()
        row.enabled = obj is not None and obj.type == 'MESH'
        row.operator("skin_tools.copy_skin_weights", icon='COPYDOWN')
        col.operator("skin_tools.remove_empty_groups", icon='X')

        col = self.layout.column(align=True)
        col.label(text="Per-vertex file data:")
        row = col.row(align=True)
        row.operator("skin_tools.export_skin_weights", text="Export", icon='EXPORT')
        row.operator("skin_tools.import_skin_weights", text="Import", icon='IMPORT')
