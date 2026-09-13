"""Read and write a dense (vertex x influence) weight matrix."""

from __future__ import annotations

import numpy as np

_WEIGHT_Q = 512.0


def read_weights(obj, group_indices):
    """Return float32 array shaped (nverts, ninfluences)."""
    mesh = obj.data
    nverts = len(mesh.vertices)
    ninf = len(group_indices)
    weights = np.zeros((nverts, ninf), dtype=np.float32)
    index_map = {gi: local for local, gi in enumerate(group_indices)}
    for vi, vert in enumerate(mesh.vertices):
        for elem in vert.groups:
            local = index_map.get(elem.group)
            if local is not None:
                weights[vi, local] = elem.weight
    return weights


def read_weight_rows(obj, group_indices, dirty):
    """Read only `dirty` vertices. Returns (len(dirty), ninfluences)."""
    dirty = np.asarray(dirty, dtype=np.int32)
    ninf = len(group_indices)
    rows = np.zeros((dirty.size, ninf), dtype=np.float32)
    if dirty.size == 0:
        return rows
    index_map = {int(gi): local for local, gi in enumerate(group_indices)}
    mesh = obj.data
    verts = mesh.vertices
    for k, vi in enumerate(dirty):
        for elem in verts[int(vi)].groups:
            local = index_map.get(int(elem.group))
            if local is not None:
                rows[k, local] = elem.weight
    return rows


def write_weights(obj, group_indices, weights, dirty, previous=None, prune=1e-4, locked=None):
    """Write `dirty` vertices. `weights` is (nverts, I) or compact (len(dirty), I)."""
    if dirty is None:
        dirty = np.arange(weights.shape[0], dtype=np.int32)
        cols = weights
        prev_cols = previous
    else:
        dirty = np.asarray(dirty, dtype=np.int32)
        if dirty.size == 0:
            return 0
        if weights.shape[0] == dirty.size:
            cols = weights
            prev_cols = previous
        else:
            cols = weights[dirty]
            prev_cols = previous[dirty] if previous is not None else None

    groups = obj.vertex_groups
    written = 0
    for local, gi in enumerate(group_indices):
        if locked is not None and locked[local]:
            continue
        vg = groups[gi]
        col = cols[:, local]
        if prev_cols is not None:
            changed = np.abs(col - prev_cols[:, local]) > 1e-6
            if not np.any(changed):
                continue
            dsub = dirty[changed]
            csub = col[changed]
        else:
            dsub = dirty
            csub = col
        kill = dsub[csub <= prune]
        if kill.size:
            vg.remove([int(v) for v in kill])
            written += int(kill.size)
        live_mask = csub > prune
        live = dsub[live_mask]
        lw = csub[live_mask]
        if live.size == 0:
            continue
        q = np.round(lw * _WEIGHT_Q)
        for qv in np.unique(q):
            idx = live[q == qv]
            vg.add([int(v) for v in idx], float(qv / _WEIGHT_Q), 'REPLACE')
            written += int(idx.size)
    return written


def refresh_overlay(context, obj, dirty=None, rows=None):
    """Force the weight-paint overlay and armature deform to refresh."""
    mesh = obj.data
    mesh.update()
    obj.update_tag(refresh={'DATA', 'OBJECT'})
    if obj.vertex_groups:
        obj.vertex_groups.active_index = obj.vertex_groups.active_index
    settings = getattr(getattr(context, "window_manager", None), "skin_tools", None)
    if settings is not None:
        if dirty is not None and rows is not None:
            try:
                from ..ui.color_overlay import patch_overlay_colors

                if patch_overlay_colors(obj, dirty, rows, settings):
                    settings.display_dirty = False
                else:
                    settings.display_dirty = True
            except Exception:
                settings.display_dirty = True
        else:
            settings.display_dirty = True
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()
