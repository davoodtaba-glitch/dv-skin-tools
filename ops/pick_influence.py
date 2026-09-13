"""Hold-S influence picker: preview bound bones, release to set the
active paint influence (vertex group)."""

from __future__ import annotations

import bpy

from mathutils import Vector
from bpy.props import EnumProperty
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Operator

from ..core.mesh_data import deform_group_indices, object_armature
from ..properties import _settings_from
from ..ui.color_overlay import set_pick_state
from .smooth_brush import _event_over_ui


def pick_bone(candidates, mouse):
    """Closest candidate to a region-space mouse point.

    ``candidates`` is a sequence of ``(name, group_index, (x, y))``.
    Returns ``(name, group_index)`` or ``(None, None)``.
    """
    best = None
    best_d = None
    mx, my = float(mouse[0]), float(mouse[1])
    for name, gi, (x, y) in candidates:
        d = (x - mx) ** 2 + (y - my) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = (name, gi)
    if best is None:
        return (None, None)
    return best


def modal_view(context, event):
    """Robustly find a usable (region, region_3d) in the 3D viewport.

    The modal context from a keymap invoke can lack ``space_data`` /
    ``region``, so we fall back to scanning the screen for a VIEW_3D
    window region (preferring the one under the mouse).
    """
    region = getattr(context, "region", None)
    rv3d = None
    space = getattr(context, "space_data", None)
    if space is not None:
        rv3d = getattr(space, "region_3d", None)
    if rv3d is None and region is not None:
        rv3d = getattr(region, "region_3d", None)
    if rv3d is not None:
        return region, rv3d

    screen = getattr(context, "screen", None)
    if screen is None:
        return None, None
    mouse = None
    if event is not None:
        mouse = (getattr(event, "mouse_x", -1), getattr(event, "mouse_y", -1))
    fallback = None
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        r3 = getattr(space, "region_3d", None)
        if r3 is None:
            continue
        for r in area.regions:
            if r.type != 'WINDOW':
                continue
            if fallback is None:
                fallback = (r, r3)
            if mouse is not None and (r.x <= mouse[0] <= r.x + r.width and r.y <= mouse[1] <= r.y + r.height):
                return r, r3
    return fallback if fallback is not None else (None, None)


def tag_view3d(context):
    """Force the 3D viewports to redraw so live highlights update."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def bound_group_map(obj, groups):
    """Map bone (vertex-group) name -> active group index.

    ``groups`` is a list of vertex-group indices; ``obj`` the mesh.
    Returns ``None`` when there is nothing to map.
    """
    if not groups:
        return None
    try:
        return {obj.vertex_groups[gi].name: gi for gi in groups}
    except Exception:
        return None


_TOOL_IDNAME = "skin_tools.smooth_brush_tool"


def _dv_tool_active(context):
    """True when the hold-S picker may own the S key.

    The toolbar tool was removed; the picker is bound to Weight Paint
    mode itself, so S stays free in every other mode.
    """
    return context.mode == 'PAINT_WEIGHT'

def commit_influence(context, obj, group_index, settings=None):
    """Set the active paint influence.

    Returns the group name that became active, or ``None`` if nothing
    was picked.
    """
    from ..ui.color_overlay import set_pick_state

    set_pick_state(False, None)
    if obj is None or group_index is None:
        return None
    vg = obj.vertex_groups[group_index]
    obj.vertex_groups.active_index = group_index
    if settings is not None:
        try:
            settings.last_picked_group = vg.name
        except Exception:
            pass
    arm = object_armature(obj)
    if arm is not None:
        bone = arm.data.bones.get(vg.name)
        if bone is not None:
            arm.data.bones.active = bone
            pb = arm.pose.bones.get(vg.name)
            if pb is not None:
                pb.select = True
    return vg.name


class SKIN_OT_pick_influence(Operator):
    bl_idname = "skin_tools.pick_influence"
    bl_label = "Pick Influence"
    bl_description = (
        "Hold S to inspect influences: the active one shows green x-ray "
        "bones and white vertices; hovering a bone previews it red. With "
        "Live Select off, releasing S picks the hovered bone. With Live "
        "Select on, holding S adds hovered bones to the selection and "
        "holding D subtracts them. LMB confirms (Live Select off), "
        "Esc/RMB cancels"
    )
    bl_options = {'REGISTER'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ('ADD', "Add", "Hover adds the influence / adds bones to the selection"),
            ('SUBTRACT', "Subtract", "Hover subtracts the hovered bone from the selection"),
        ),
        default='ADD',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or context.mode != 'PAINT_WEIGHT':
            return False
        if object_armature(obj) is None:
            return False
        # The hold-S shortcut only belongs to DV Skin while its tool is
        # active; otherwise S stays free for Blender's own shortcuts.
        return _dv_tool_active(context)

    def invoke(self, context, event):
        obj = context.active_object
        groups = deform_group_indices(obj)
        if not groups:
            self.report({'ERROR'}, "No deform vertex groups")
            return {'CANCELLED'}
        arm = object_armature(obj)
        if arm is None:
            self.report({'ERROR'}, "No armature bound to the mesh")
            return {'CANCELLED'}

        self._settings = _settings_from(context)
        self._groups = groups
        self._obj_name = obj.name
        self._arm_name = arm.name
        self._highlight = None
        # ADD (hold S): inspect + pick an influence. SUBTRACT (hold D):
        # live-select only, hovering removes bones from the selection.
        # The physical key that triggered this invocation decides the
        # session: S is always ADD, D is always SUBTRACT. Keymap item
        # properties have been observed to stick across sessions, which
        # once started an S hold as SUBTRACT (hover deselected, and the
        # S release could not end it) — the event cannot lie.
        key = getattr(event, "type", None) if event is not None else None
        if key == 'D':
            self._mode = 'SUBTRACT'
        elif key == 'S':
            self._mode = 'ADD'
        else:
            # No physical key (scripted invoke): fall back to the property.
            self._mode = getattr(self, "mode", 'ADD') or 'ADD'
        self._key = 'D' if self._mode == 'SUBTRACT' else 'S'
        vg = obj.vertex_groups.active
        self._group = vg.name if vg is not None else None
        self._prev_vg = obj.vertex_groups.active_index
        self._last_hover = None
        # Snapshot the pose-bone selection so a cancelled pick (or a
        # release with nothing hovered) can put it back.
        self._prev_selected = frozenset(pb.name for pb in arm.pose.bones if pb.select)
        # Hold-S inspects the active influence. Show All Influences and
        # Bone X-Ray are independent toggles and stay as the user set them.
        set_pick_state(True, None, self._group)
        if event is not None:
            self._update_highlight(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update_highlight(self, context, event):
        obj = context.active_object
        if obj is None or obj.name != self._obj_name:
            return
        arm = object_armature(obj)
        if arm is None or arm.name != self._arm_name:
            return
        region, rv3d = modal_view(context, event)
        if region is None or rv3d is None:
            return
        mw = arm.matrix_world
        rot = mw.to_3x3()
        mouse = (event.mouse_region_x, event.mouse_region_y) if event is not None else None
        if mouse is None:
            return
        candidates = []
        for pb in arm.pose.bones:
            gi = self._bound_group_index(obj, pb.name)
            if gi is None:
                continue
            head = mw @ pb.matrix.translation
            axis = (rot @ (pb.matrix.to_3x3() @ Vector((0.0, 1.0, 0.0)))).normalized()
            tail = head + axis * max(float(pb.length), 1e-6)
            mid = (head + tail) * 0.5
            for world in (head, mid, tail):
                p = location_3d_to_region_2d(region, rv3d, world)
                if p is not None:
                    candidates.append((pb.name, gi, (p.x, p.y)))
        name, gi = pick_bone(candidates, mouse)
        self._highlight = gi
        live = (
            bool(getattr(self._settings, "live_select", False))
            if self._settings is not None
            else False
        )
        if live and name is not None:
            # Live Select: holding S adds the hovered bone to the
            # selection; holding D subtracts it. Hovering the same bone
            # never toggles it back off.
            pb = arm.pose.bones.get(name)
            if pb is not None:
                want = self._mode == 'ADD'
                if pb.select != want:
                    pb.select = want
            self._last_hover = name
        elif live:
            self._last_hover = None
        elif gi is not None and self._mode == 'ADD':
            # Live-preview the hovered influence in the N-panel list and
            # make the hovered pose bone the ONLY selected bone: with
            # Live Select off, no other bone may stay selected while
            # holding S.
            try:
                if obj.vertex_groups.active_index != gi:
                    obj.vertex_groups.active_index = gi
            except Exception:
                pass
            if name is not None and arm is not None:
                for pb in arm.pose.bones:
                    want = pb.name == name
                    if pb.select != want:
                        pb.select = want
        set_pick_state(True, name, self._group)
        tag_view3d(context)

    def _bound_group_index(self, obj, bone_name):
        if not hasattr(self, "_bound"):
            self._bound = bound_group_map(obj, getattr(self, "_groups", None)) or {}
        return self._bound.get(bone_name)

    def _live(self):
        """True while Live Select is enabled (S adds / D subtracts)."""
        settings = getattr(self, "_settings", None)
        return bool(getattr(settings, "live_select", False)) if settings is not None else False

    def _restore(self):
        set_pick_state(False, None)
        # The pick overlay must disappear immediately on release/cancel.
        tag_view3d(bpy.context)
        # SUBTRACT (hold D) only edits the selection: never roll it back
        # and never touch the active vertex group.
        if getattr(self, "_mode", 'ADD') == 'SUBTRACT':
            return
        # With Live Select on the selection edits are the whole point:
        # keep them (and the active vertex group was never changed).
        if self._settings is not None and getattr(self._settings, "live_select", False):
            return
        # Put the pose-bone selection back the way it was before the
        # picker deselected everything except the hovered bone.
        prev_sel = getattr(self, "_prev_selected", None)
        obj = bpy.context.active_object
        if prev_sel is not None and obj is not None and obj.name == getattr(self, "_obj_name", None):
            arm = object_armature(obj)
            if arm is not None and arm.name == getattr(self, "_arm_name", None):
                try:
                    for pb in arm.pose.bones:
                        want = pb.name in prev_sel
                        if pb.select != want:
                            pb.select = want
                except Exception:
                    pass
        prev = getattr(self, "_prev_vg", None)
        if prev is None:
            return
        obj = bpy.context.active_object
        if obj is None or obj.name != getattr(self, "_obj_name", None):
            return
        try:
            if obj.vertex_groups.active_index != prev:
                obj.vertex_groups.active_index = prev
        except Exception:
            pass

    def _commit(self, context):
        obj = context.active_object
        picked = None
        if obj is not None and obj.name == self._obj_name:
            picked = commit_influence(context, obj, self._highlight, settings=self._settings)
        else:
            self._restore()
        if picked is None:
            self.report({'WARNING'}, "No influence under the mouse")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Paint influence: {picked}")
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self._update_highlight(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and _event_over_ui(context, event):
            # Clicks on menus, the N-panel, headers, etc. belong to the
            # UI, never to the picker.
            self._restore()
            return {'PASS_THROUGH'}
        if event.type == self._key and event.value == 'RELEASE':
            # Releasing S picks the hovered influence (it was already
            # live-previewed); with nothing hovered nothing changes.
            # Releasing D — or releasing S while Live Select is on —
            # just ends the pass, keeping the selection edits.
            if self._mode == 'SUBTRACT' or self._live():
                self._restore()
                return {'FINISHED'}
            if self._highlight is not None:
                return self._commit(context)
            self._restore()
            return {'FINISHED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._mode == 'SUBTRACT' or self._live() or self._highlight is None:
                self._restore()
                return {'FINISHED'}
            return self._commit(context)
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._restore()
            return {'CANCELLED'}
        if event.type == 'WINDOW_DEACTIVATE':
            self._restore()
            return {'CANCELLED'}
        return {'PASS_THROUGH'}


class SKIN_OT_bones_deselect_all(Operator):
    """Deselect every pose bone on the active mesh's armature."""

    bl_idname = "skin_tools.bones_deselect_all"
    bl_label = "Deselect All Bones"
    bl_description = "Deselect all pose bones of the active mesh's armature"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and object_armature(obj) is not None

    def execute(self, context):
        arm = object_armature(context.active_object)
        count = 0
        for pb in arm.pose.bones:
            if pb.select:
                pb.select = False
                count += 1
        tag_view3d(context)
        self.report({'INFO'}, f"Deselected {count} bones")
        return {'FINISHED'}


class SKIN_OT_bones_select_invert(Operator):
    """Reverse the influence-list selection: selected deform bones of the
    armature become deselected and vice versa."""

    bl_idname = "skin_tools.bones_select_invert"
    bl_label = "Invert Bone Selection"
    bl_description = (
        "Reverse the selection checkboxes in the influence list: every "
        "deform bone of the active mesh's armature flips its selection "
        "state"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and object_armature(obj) is not None

    def execute(self, context):
        obj = context.active_object
        arm = object_armature(obj)
        # Invert exactly the rows the influence list can show: the mesh's
        # deform bones. Vertex groups without a pose bone have no
        # checkbox, so they cannot participate either way.
        count = 0
        for gi in deform_group_indices(obj):
            try:
                name = obj.vertex_groups[gi].name
            except Exception:
                continue
            pb = arm.pose.bones.get(name)
            if pb is None:
                continue
            pb.select = not pb.select
            count += 1
        tag_view3d(context)
        self.report({'INFO'}, f"Inverted selection on {count} bones")
        return {'FINISHED'}
