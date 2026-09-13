"""Maya-style Copy Skin Weights from one skinned mesh to another.

Surface association picks which source surface sample feeds each target
vertex; influence association decides how the source's bones map onto
the target's vertex groups.
"""
from __future__ import annotations

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .mesh_data import (
    _build_kdtree,
    deform_group_indices,
    locked_mask,
    object_armature,
    vertex_paint_mask,
)
from .weights import read_weights, refresh_overlay, write_weights


def _world_verts(obj):
    n = len(obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(obj.matrix_world, dtype=np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def _world_bone_heads(obj):
    """Bone name -> world-space head position for the object's armature."""
    arm = object_armature(obj)
    heads = {}
    if arm is None:
        return heads
    for pb in arm.pose.bones:
        heads[pb.name] = arm.matrix_world @ pb.head
    return heads


def map_influences(src_names, src_obj, tgt_names, tgt_obj, assoc):
    """Source influence column -> target influence column (or -1)."""
    tgt_index = {n: i for i, n in enumerate(tgt_names)}
    col = [-1] * len(src_names)
    unmatched = []
    for i, name in enumerate(src_names):
        j = tgt_index.get(name, -1)
        if j >= 0:
            col[i] = j
        else:
            unmatched.append(i)
    if not unmatched or assoc == 'NAME':
        return col

    if assoc == 'ONE_TO_ONE':
        used = {j for j in col if j >= 0}
        free = [j for j in range(len(tgt_names)) if j not in used]
        for k, i in enumerate(unmatched):
            if k < len(free):
                col[i] = free[k]
        return col

    # CLOSEST_JOINT: name match first, then nearest bone joint.
    src_heads = _world_bone_heads(src_obj)
    tgt_heads = _world_bone_heads(tgt_obj)
    used = {j for j in col if j >= 0}
    for i in unmatched:
        p = src_heads.get(src_names[i])
        if p is None or not tgt_heads:
            continue
        best, best_d = -1, None
        for j, name in enumerate(tgt_names):
            if j in used:
                continue
            q = tgt_heads.get(name)
            if q is None:
                continue
            d = (p - q).length_squared
            if best_d is None or d < best_d:
                best_d, best = d, j
        if best >= 0:
            col[i] = best
            used.add(best)
    return col


def _barycentric(verts_w, poly, point):
    pts = np.array([verts_w[i] for i in poly])
    a = np.vstack([pts.T, np.ones(len(poly))])
    b = np.append(point, 1.0)
    w, *_ = np.linalg.lstsq(a, b, rcond=None)
    w = np.clip(w, 0.0, 1.0)
    s = w.sum()
    return w / s if s > 1e-9 else w


def _sample_source_weights(src_obj, src_weights, target_world, visible, surface):
    """(rows, dists): sampled source weights per target vert, plus the
    distance from each target vertex to this source's surface (inf where
    nothing was found). The distance is what lets a multi-source copy
    pick the nearest source per vertex, like Maya."""
    n_t = target_world.shape[0]
    rows = np.zeros((n_t, src_weights.shape[1]), dtype=np.float32)
    dists = np.full(n_t, np.inf, dtype=np.float32)
    if surface == 'NEAREST_VERTEX':
        tree = _build_kdtree(_world_verts(src_obj).astype(np.float32))
        for vi in visible:
            _co, idx, d = tree.find(target_world[vi])
            if idx is not None:
                rows[vi] = src_weights[int(idx)]
                dists[vi] = float(d)
        return rows, dists

    mesh = src_obj.data
    verts_w = _world_verts(src_obj)
    polys = [tuple(p.vertices) for p in mesh.polygons]
    bvh = BVHTree.FromPolygons([Vector(c) for c in verts_w], polys)
    for vi in visible:
        loc, _no, poly_i, d = bvh.find_nearest(Vector(target_world[vi]))
        if poly_i is None:
            continue
        poly = polys[int(poly_i)]
        b = _barycentric(verts_w, poly, np.asarray(loc))
        rows[vi] = b @ src_weights[list(poly)]
        dists[vi] = float(d) if d is not None else np.inf
    return rows, dists


def copy_skin_weights_multi(context, src_objs, tgt_obj,
                            surface='CLOSEST_SURFACE', assoc='CLOSEST_JOINT',
                            normalize=True):
    """Maya-style multi-source Copy Skin Weights.

    Every target vertex inherits from the source whose surface is
    nearest to it, so one target (e.g. a belt) can take its weights from
    several overlapping garments (shirt, pants) and follow both in the
    intersection areas. Returns the number of verts written. Vertices
    that no source can sample keep their existing weights.
    """
    sources = []
    for src in src_objs:
        if src is None or src == tgt_obj or src.type != 'MESH':
            continue
        gis = deform_group_indices(src)
        if gis:
            sources.append((src, gis, [src.vertex_groups[gi].name for gi in gis]))
    if not sources:
        raise RuntimeError("No source mesh with deform vertex groups")

    from .bind import ensure_groups

    # Unified target influence list: existing deform groups plus, per
    # association mode, everything the sources can contribute.
    tgt_groups = deform_group_indices(tgt_obj)
    if not tgt_groups and tgt_obj.vertex_groups:
        tgt_groups = [vg.index for vg in tgt_obj.vertex_groups]
    needed = {tgt_obj.vertex_groups[gi].name for gi in tgt_groups}
    if assoc == 'NAME':
        for _src, _gis, names in sources:
            needed |= set(names)
    elif assoc == 'CLOSEST_JOINT':
        arm = object_armature(tgt_obj)
        if arm is not None:
            needed |= {b.name for b in arm.data.bones if b.use_deform}
        else:
            for _src, _gis, names in sources:
                needed |= set(names)
    missing = needed - {vg.name for vg in tgt_obj.vertex_groups}
    if missing:
        ensure_groups(tgt_obj, sorted(missing))
    tgt_groups = deform_group_indices(tgt_obj)
    if not tgt_groups and tgt_obj.vertex_groups:
        tgt_groups = [vg.index for vg in tgt_obj.vertex_groups]
    tgt_groups = [gi for gi in tgt_groups if gi < len(tgt_obj.vertex_groups)]
    if not tgt_groups:
        raise RuntimeError(
            "Target mesh has no usable vertex groups (and no bones to create them for)"
        )
    tgt_names = [tgt_obj.vertex_groups[gi].name for gi in tgt_groups]

    target_world = _world_verts(tgt_obj)
    visible = np.nonzero(vertex_paint_mask(tgt_obj))[0]
    if visible.size == 0:
        raise RuntimeError("No vertices under the paint mask")

    # Sample every source once, then let each target vertex pick the
    # nearest source surface (per-vertex source assignment, Maya-style).
    n_t = len(target_world)
    best_si = np.full(n_t, -1, dtype=np.int32)
    best_dist = np.full(n_t, np.inf, dtype=np.float32)
    samples = []
    for si, (src, gis, names) in enumerate(sources):
        rows, dists = _sample_source_weights(
            src, read_weights(src, gis), target_world, visible, surface
        )
        colmap = map_influences(names, src, tgt_names, tgt_obj, assoc)
        samples.append((rows, colmap))
        nearer = dists < best_dist
        best_si[nearer] = si
        best_dist[nearer] = dists[nearer]

    out = np.zeros((n_t, len(tgt_groups)), dtype=np.float32)
    wrote_any = False
    for si, (rows, colmap) in enumerate(samples):
        sel = visible[best_si[visible] == si]
        if sel.size == 0:
            continue
        wrote_any = True
        for s, t in enumerate(colmap):
            if t >= 0:
                out[sel, t] += rows[sel, s]
    if not wrote_any:
        raise RuntimeError("No target vertex could be sampled from any source")

    hit = visible[best_si[visible] >= 0]
    if normalize and hit.size:
        sums = out[hit].sum(axis=1)
        scale = np.ones_like(sums)
        good = sums > 1e-6
        scale[good] = 1.0 / sums[good]
        out[hit] *= scale[:, None]

    from .weight_undo import push_current

    push_current(tgt_obj, tgt_groups, "copy", dirty=hit.astype(np.int32))
    written = write_weights(
        tgt_obj,
        tgt_groups,
        out,
        hit.astype(np.int32),
        previous=read_weights(tgt_obj, tgt_groups),
        locked=locked_mask(tgt_obj, tgt_groups),
    )
    refresh_overlay(context, tgt_obj)
    return written


def copy_skin_weights(context, src_obj, tgt_obj,
                      surface='CLOSEST_SURFACE', assoc='CLOSEST_JOINT',
                      normalize=True):
    """Back-compat single-source wrapper around copy_skin_weights_multi."""
    return copy_skin_weights_multi(
        context, [src_obj], tgt_obj, surface, assoc, normalize
    )
