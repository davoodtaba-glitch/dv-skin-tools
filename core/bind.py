"""Assign 1.0 to the nearest deform bone (Maya closest-joint)."""

from __future__ import annotations

import numpy as np
from mathutils import Vector

from .mesh_data import object_armature
from .weights import read_weights


def _selected_pose_bones(armature, context=None):
    selected = []
    seen = set()
    sources = [armature]
    if context is not None:
        pose_obj = getattr(context, "pose_object", None)
        if pose_obj is not None and pose_obj.type == 'ARMATURE' and pose_obj not in sources:
            sources.append(pose_obj)
    for src in sources:
        for pbone in src.pose.bones:
            if not pbone.bone.use_deform:
                continue
            if getattr(pbone, "select", False) and pbone.name not in seen:
                selected.append(pbone)
                seen.add(pbone.name)
    return selected


def candidate_bones(obj, context=None):
    """Selected deform bones, or all deform bones if none are selected."""
    armature = object_armature(obj)
    if armature is None:
        return [], None
    selected = _selected_pose_bones(armature, context)
    if selected:
        return selected, armature
    all_deform = [pb for pb in armature.pose.bones if pb.bone.use_deform]
    return all_deform, armature


def all_bone_group_indices(obj):
    """Every vertex group named after an armature bone (deform or not)."""
    armature = object_armature(obj)
    if armature is None:
        return [vg.index for vg in obj.vertex_groups]
    names = {bone.name for bone in armature.data.bones}
    return [vg.index for vg in obj.vertex_groups if vg.name in names]


def clear_skin_weights(obj, indices):
    """Remove all bone vertex-group assignments on these verts."""
    indices = [int(i) for i in np.asarray(indices, dtype=np.int32)]
    if not indices:
        return
    for gi in all_bone_group_indices(obj):
        obj.vertex_groups[gi].remove(indices)


def target_vertex_indices(obj):
    """Vertices the current weight-paint mask allows; whole mesh otherwise.

    With Vertex Selection (or Face) masking enabled in Weight Paint, only
    the selected vertices are bound — the rest keep their weights.
    """
    from .mesh_data import vertex_paint_mask

    mask = vertex_paint_mask(obj)
    if not bool(mask.all()):
        return np.nonzero(mask)[0].astype(np.int32)
    n = len(obj.data.vertices)
    return np.arange(n, dtype=np.int32)


def _segment_distance(points, heads, tails):
    """points (V,3), heads/tails (B,3) → (V, B) distances."""
    ab = tails - heads
    ab_len2 = np.sum(ab * ab, axis=1)
    ab_len2 = np.maximum(ab_len2, 1e-12)
    # t = ((p - a) · ab) / |ab|^2
    ap = points[:, None, :] - heads[None, :, :]
    t = np.sum(ap * ab[None, :, :], axis=2) / ab_len2[None, :]
    t = np.clip(t, 0.0, 1.0)
    closest = heads[None, :, :] + t[:, :, None] * ab[None, :, :]
    delta = points[:, None, :] - closest
    return np.linalg.norm(delta, axis=2)


def ensure_groups(obj, bone_names):
    created = []
    for name in bone_names:
        if name not in obj.vertex_groups:
            obj.vertex_groups.new(name=name)
            created.append(name)
    return created


def remove_selected_bones(obj, context=None):
    """Strip selected bones' weights from the skin and delete their groups.

    The removed bones' weights are NOT redistributed — other groups keep
    their values untouched (the per-vertex total may drop below 1).
    Respects the weight-paint mask like Bind Nearest: with vertex/face
    masking on, only masked vertices lose the weights. Returns
    ``(bone_names, verts_stripped)``.
    """
    armature = object_armature(obj)
    if armature is None:
        return [], 0
    bones = _selected_pose_bones(armature, context)
    if not bones:
        return [], 0

    indices = target_vertex_indices(obj)
    if indices.size == 0:
        return [b.name for b in bones], 0
    vert_ids = [int(i) for i in indices]

    stripped = 0
    removed_groups = []
    for bone in bones:
        name = bone.name
        vg = obj.vertex_groups.get(name)
        if vg is None:
            continue
        gi = vg.index
        col = read_weights(obj, [gi])[:, 0]
        stripped += int(np.count_nonzero(col[indices] > 1e-6))
        vg.remove(vert_ids)
        removed_groups.append(name)

    # Delete the groups only after every strip succeeded.
    for name in removed_groups:
        obj.vertex_groups.remove(obj.vertex_groups[name])

    if removed_groups:
        from .weights import refresh_overlay

        refresh_overlay(None, obj)
    return removed_groups, stripped


def bind_nearest(obj, context, weights, group_indices, indices, locked, bones=None):
    """Set each target vertex's nearest candidate bone to fill remaining weight.

    ``bones`` explicitly limits the candidates — the operator passes the
    list so the Selected checkbox alone decides the scope. ``None``
    falls back to the legacy auto behavior (selected bones compete when
    any are selected, otherwise all deform bones).
    """
    armature = object_armature(obj)
    if bones is None:
        bones, armature = candidate_bones(obj, context)
    if not bones or armature is None:
        raise RuntimeError("No deform bones on the armature")
    names = [b.name for b in bones]
    name_to_local = {}
    for local, gi in enumerate(group_indices):
        name_to_local[obj.vertex_groups[gi].name] = local
    missing = [n for n in names if n not in name_to_local]
    if missing:
        raise RuntimeError("Vertex groups missing for: " + ", ".join(missing))

    bone_locals = np.array([name_to_local[n] for n in names], dtype=np.int32)
    mw = armature.matrix_world
    heads = np.array([mw @ Vector(b.head) for b in bones], dtype=np.float64)
    tails = np.array([mw @ Vector(b.tail) for b in bones], dtype=np.float64)

    # Use posed mesh positions when available.
    from .mesh_data import _evaluated_coords_and_normals

    world_co, _no, _d, _e = _evaluated_coords_and_normals(obj, context)
    pts = world_co[indices].astype(np.float64)
    dist = _segment_distance(pts, heads, tails)
    nearest = np.argmin(dist, axis=1)
    chosen = bone_locals[nearest]

    # Hard assign: every deform influence is zero except the nearest bone.
    rows = np.zeros((len(indices), weights.shape[1]), dtype=np.float32)
    rows[np.arange(len(indices)), chosen] = 1.0
    weights[indices] = rows
    return names, int(len(indices))
