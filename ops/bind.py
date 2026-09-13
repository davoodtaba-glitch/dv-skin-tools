import bpy
from bpy.types import Operator

from ..core.bind import (
    _selected_pose_bones,
    bind_nearest,
    clear_skin_weights,
    ensure_groups,
    remove_selected_bones,
    target_vertex_indices,
)
from ..core.mesh_data import deform_group_indices, object_armature
from ..core.weights import read_weights, refresh_overlay, write_weights
from ..properties import _settings_from


def _scene_armatures(context, obj):
    seen = set()
    if obj is not None and obj.type == 'MESH':
        try:
            arm = object_armature(obj)
        except Exception:
            arm = None
        if arm is not None:
            seen.add(arm.name)
            yield arm
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    for o in scene.objects:
        if o.type == 'ARMATURE' and o.name not in seen:
            seen.add(o.name)
            yield o


def _all_bones_selected(context, obj):
    selected = []
    seen = set()
    for arm in _scene_armatures(context, obj):
        try:
            data_bones = arm.data.bones
            pose_bones = arm.pose.bones
        except Exception:
            continue
        for pb in pose_bones:
            bone = data_bones.get(pb.name)
            if bone is None or not bone.use_deform:
                continue
            if getattr(pb, "select", False) and pb.name not in seen:
                selected.append(pb)
                seen.add(pb.name)
    return selected


def _all_bones_highlighted(context):
    settings = _settings_from(context)
    if settings is None:
        return None
    items = getattr(settings, "scene_bones", None)
    if not items:
        return None
    idx = int(getattr(settings, "scene_bone_index", 0) or 0)
    if idx < 0 or idx >= len(items):
        return None
    item = items[idx]
    arm = bpy.data.objects.get(item.armature_name)
    if arm is None or arm.type != 'ARMATURE':
        return None
    try:
        bone = arm.data.bones.get(item.name)
        pb = arm.pose.bones.get(item.name)
    except Exception:
        return None
    if bone is None or not bone.use_deform or pb is None:
        return None
    return pb


def _bones_to_add(context, obj):
    bones = _all_bones_selected(context, obj)
    if bones:
        return bones
    pb = _all_bones_highlighted(context)
    if pb is not None:
        return [pb]
    return []


def _ensure_armature_modifier(obj, armature):
    if obj is None or armature is None:
        return None
    for mod in obj.modifiers:
        if mod.type == 'ARMATURE':
            if mod.object is None:
                mod.object = armature
            return mod
    mod = obj.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = armature
    mod.use_vertex_groups = True
    return mod


class SKIN_OT_bind_nearest(Operator):
    bl_idname = "skin_tools.bind_nearest"
    bl_label = "Bind Nearest"
    bl_description = (
        "Replace all current skin weights: each vertex gets 1.0 on the closest "
        "bone and 0 on every other bone. Selected: only the selected pose "
        "bones compete. Mirror: the result is mirrored across X with the "
        "Mirror Weights direction and threshold"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.mode != 'WEIGHT_PAINT':
            return False
        return object_armature(obj) is not None

    def execute(self, context):
        obj = context.active_object
        from ..properties import _settings_from

        settings = _settings_from(context)
        bind_selected = bool(getattr(settings, "bind_selected", False)) if settings is not None else False
        bind_mirror = bool(getattr(settings, "bind_mirror", False)) if settings is not None else False

        armature = object_armature(obj)
        if armature is None:
            self.report({'ERROR'}, "No armature bound to the mesh")
            return {'CANCELLED'}
        if bind_selected:
            # Explicit: only the selected pose bones compete.
            bones = _selected_pose_bones(armature, context)
            if not bones:
                self.report({'ERROR'}, "No deform bones selected")
                return {'CANCELLED'}
        else:
            # Explicit: all deform bones compete, no matter what happens
            # to be selected in the viewport.
            bones = [pb for pb in armature.pose.bones if pb.bone.use_deform]
        if not bones:
            self.report({'ERROR'}, "No deform bones")
            return {'CANCELLED'}

        created = ensure_groups(obj, [b.name for b in bones])
        if not any(m.type == 'ARMATURE' and m.object == armature for m in obj.modifiers):
            mod = obj.modifiers.new(name="Armature", type='ARMATURE')
            mod.object = armature

        group_indices = deform_group_indices(obj)
        if not group_indices:
            self.report({'ERROR'}, "No deform vertex groups")
            return {'CANCELLED'}

        indices = target_vertex_indices(obj)
        if indices.size == 0:
            self.report({'WARNING'}, "No vertices under the paint mask")
            return {'CANCELLED'}

        from ..core.weight_undo import push_current

        push_current(obj, group_indices, "bind", dirty=indices)
        # Wipe existing skin weights first, then hard-assign nearest.
        clear_skin_weights(obj, indices)
        weights = read_weights(obj, group_indices)
        try:
            names, count = bind_nearest(
                obj, context, weights, group_indices, indices, None, bones=bones
            )
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        write_weights(
            obj,
            group_indices,
            weights,
            indices,
            previous=None,
            prune=1e-6,
            locked=None,
        )

        # Mirror: make the binding symmetric across X with the Mirror
        # Weights settings (direction + threshold).
        mirrored = 0
        if bind_mirror and settings is not None:
            from ..core.mirror import mirror_weights

            mirrored = mirror_weights(
                obj,
                group_indices,
                direction=str(settings.mirror_direction),
                threshold=float(settings.mirror_threshold),
                pattern=str(getattr(settings, "mirror_pattern", "") or ""),
            )

        from ..ui.color_overlay import reroll_color_seed

        if settings is not None:
            reroll_color_seed(settings)
        refresh_overlay(context, obj)
        scope = "selected bones" if bind_selected else "all deform bones"
        extra = f" (created {len(created)} groups)" if created else ""
        if mirrored:
            extra += f", mirrored {mirrored}"
        self.report({'INFO'}, f"Bound {count} verts to nearest of {len(names)} ({scope}){extra}")
        return {'FINISHED'}


class SKIN_OT_remove_selected_bones(Operator):
    bl_idname = "skin_tools.remove_selected_bones"
    bl_label = "Remove Selected"
    bl_description = (
        "Remove the selected pose bones from the skin: their weights are "
        "stripped from the vertices (NOT redistributed to other bones) "
        "and their vertex groups are deleted. Other bones keep their "
        "weights untouched. Undo with Ctrl+Z"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.mode != 'WEIGHT_PAINT':
            return False
        armature = object_armature(obj)
        if armature is None:
            return False
        return bool(_selected_pose_bones(armature, context))

    def execute(self, context):
        obj = context.active_object
        from ..core.weight_undo import push_current

        group_indices = deform_group_indices(obj)
        indices = target_vertex_indices(obj)
        if indices.size:
            push_current(obj, group_indices, "remove bones", dirty=indices)

        names, stripped = remove_selected_bones(obj, context)
        if not names:
            self.report({'WARNING'}, "Selected bones have no vertex groups")
            return {'CANCELLED'}

        refresh_overlay(context, obj)
        self.report(
            {'INFO'},
            f"Removed {len(names)} bone(s), stripped {stripped} vertex weights",
        )
        return {'FINISHED'}


class SKIN_OT_add_selected_influences(Operator):
    bl_idname = "skin_tools.add_selected_influences"
    bl_label = "Add Selected"
    bl_description = (
        "Create vertex groups on the mesh for the selected pose bones"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH' or obj.mode != 'WEIGHT_PAINT':
            return False
        return bool(_bones_to_add(context, obj))

    def execute(self, context):
        obj = context.active_object
        bones = _bones_to_add(context, obj)
        if not bones:
            self.report({'ERROR'}, "No deform bones selected")
            return {'CANCELLED'}
        armature = getattr(bones[0], "id_data", None)
        if armature is not None and armature.type == 'ARMATURE':
            _ensure_armature_modifier(obj, armature)
        names = [b.name for b in bones if b.name not in obj.vertex_groups]
        created = ensure_groups(obj, names)
        refresh_overlay(context, obj)
        skipped = len(bones) - len(created)
        if not created:
            self.report({'INFO'}, "Selected bones already have vertex groups")
            return {'FINISHED'}
        extra = f", skipped {skipped} existing" if skipped else ""
        self.report({'INFO'}, f"Added {len(created)} influence(s){extra}")
        return {'FINISHED'}
