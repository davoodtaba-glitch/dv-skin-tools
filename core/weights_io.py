"""Per-vertex skin weight export / import (JSON).

Format (version 1) — fully per-vertex, no surface sampling needed:

{
  "version": 1,
  "source": "<mesh name>",
  "vertex_count": 123,
  "groups": ["BoneA", "BoneB"],     # index order for the pairs below
  "vertices": [                     # one entry per vertex, index = vertex index
      [[0, 1.0]],                   # [group_index, weight] pairs, weights > 0
      [[0, 0.5], [1, 0.5]],
      ...
  ]
}

Import matches groups by name (creating missing ones), skips locked
groups, and writes by vertex index when counts match. If the vertex
count differs (typical Blender <-> Maya FBX split), import uses stored
object-space positions and nearest-vertex transfer.
"""
from __future__ import annotations

import json

import numpy as np
from mathutils.kdtree import KDTree

from .weight_undo import push_groups
from .weights import read_weights, refresh_overlay, write_weights

_FORMAT_VERSION = 1
_ZERO = 1e-6
_AXIS = (
    (0, 1, 2, 1.0, 1.0, 1.0),
    (0, 2, 1, 1.0, 1.0, -1.0),
    (0, 2, 1, 1.0, -1.0, 1.0),
    (0, 2, 1, 1.0, 1.0, 1.0),
    (0, 1, 2, 1.0, -1.0, -1.0),
    (0, 1, 2, -1.0, 1.0, -1.0),
)
_SCALES = (1.0, 100.0, 0.01)


def _mesh_positions(obj):
    n = len(obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(n, 3)


def _apply_axis(pts, spec, scale):
    i0, i1, i2, s0, s1, s2 = spec
    out = np.empty_like(pts)
    out[:, 0] = pts[:, i0] * (s0 * scale)
    out[:, 1] = pts[:, i1] * (s1 * scale)
    out[:, 2] = pts[:, i2] * (s2 * scale)
    return out


def _align_points(src, dst):
    dst_c = dst.mean(axis=0)
    step = max(1, len(src) // 128)
    sample = src[::step][:128]
    tree = KDTree(len(dst))
    for i, p in enumerate(dst):
        tree.insert((float(p[0]), float(p[1]), float(p[2])), i)
    tree.balance()
    best_score = None
    best = src
    for spec in _AXIS:
        for scale in _SCALES:
            xf = _apply_axis(sample, spec, scale)
            t = dst_c - xf.mean(axis=0)
            score = 0.0
            for p in xf:
                _co, _idx, d = tree.find(
                    (float(p[0] + t[0]), float(p[1] + t[1]), float(p[2] + t[2]))
                )
                score += d
            if best_score is None or score < best_score:
                best_score = score
                full = _apply_axis(src, spec, scale)
                best = full + (dst_c - full.mean(axis=0))
    return best


def _nearest_indices(src_pts, dst_pts):
    tree = KDTree(len(src_pts))
    for i, p in enumerate(src_pts):
        tree.insert((float(p[0]), float(p[1]), float(p[2])), i)
    tree.balance()
    out = np.empty(len(dst_pts), dtype=np.int32)
    for i, p in enumerate(dst_pts):
        _co, idx, _d = tree.find((float(p[0]), float(p[1]), float(p[2])))
        out[i] = idx
    return out


def _file_positions(data, file_n):
    pos = data.get("positions")
    if not isinstance(pos, list) or not pos:
        return None
    limit = min(file_n, len(pos))
    out = np.empty((limit, 3), dtype=np.float64)
    for i in range(limit):
        p = pos[i]
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            return None
        out[i] = (float(p[0]), float(p[1]), float(p[2]))
    return out


def export_skin_weights(obj, path):
    """Write every vertex group's per-vertex weights to ``path`` (JSON).

    Exports the whole mesh — the paint mask is a paint-time concept and
    a data export must stay complete. Returns a stats dict.
    """
    vgs = obj.vertex_groups
    if not vgs:
        raise RuntimeError("Mesh has no vertex groups to export")
    n = len(obj.data.vertices)
    names = [vg.name for vg in vgs]
    weights = read_weights(obj, [vg.index for vg in vgs])

    vertices = []
    for vi in range(n):
        row = weights[vi]
        nz = np.nonzero(row > _ZERO)[0]
        vertices.append([[int(g), float(row[g])] for g in nz])

    data = {
        "version": _FORMAT_VERSION,
        "source": obj.name,
        "vertex_count": n,
        "groups": names,
        "vertices": vertices,
        "positions": np.round(_mesh_positions(obj), 6).tolist(),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return {"vertices": n, "groups": len(names)}


def import_skin_weights(context, obj, path):
    """Read a per-vertex weights file onto ``obj``. Returns a stats dict.

    Groups are matched by name and created when missing. Imported groups
    are fully replaced per vertex (stale weights in those groups are
    cleared first by the batch writer); groups not present in the file
    are left untouched. Locked groups are protected. Vertices beyond
    the file's vertex_count are cleared in the imported groups.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Not a valid weights file: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("version") != _FORMAT_VERSION
        or not isinstance(data.get("groups"), list)
        or not isinstance(data.get("vertices"), list)
    ):
        raise RuntimeError("Not a DV Skin per-vertex weights file (version 1)")

    names = [str(name) for name in data["groups"]]
    vertices = data["vertices"]
    if not names:
        raise RuntimeError("Weights file contains no groups")

    vgs = obj.vertex_groups
    n = len(obj.data.vertices)
    file_n = int(data.get("vertex_count", len(vertices)))

    # Create missing groups so every influence in the file has a home.
    for name in names:
        if vgs.get(name) is None:
            vgs.new(name=name)
    group_indices = [vgs[name].index for name in names]
    from .mesh_data import locked_mask

    locked = locked_mask(obj, group_indices)
    if bool(np.all(locked)):
        raise RuntimeError("All groups in the file are locked on this mesh")

    out = np.zeros((n, len(names)), dtype=np.float32)
    method = "index"
    if n == file_n:
        limit = min(n, len(vertices))
        for vi in range(limit):
            for entry in vertices[vi]:
                gi, w = entry[0], entry[1]
                if 0 <= int(gi) < len(names):
                    out[vi, int(gi)] = float(w)
    else:
        src_pts = _file_positions(data, file_n)
        if src_pts is None:
            raise RuntimeError(
                f"Vertex count differs (mesh {n} vs file {file_n}) and the "
                "file has no positions. Re-export weights, then import again."
            )
        dst_pts = _mesh_positions(obj)
        src_idx = _nearest_indices(_align_points(src_pts, dst_pts), dst_pts)
        method = "closest_vertex"
        for vi in range(n):
            si = int(src_idx[vi])
            if si < 0 or si >= len(vertices):
                continue
            for entry in vertices[si]:
                gi, w = entry[0], entry[1]
                if 0 <= int(gi) < len(names):
                    out[vi, int(gi)] = float(w)

    push_groups(obj, "import")
    dirty = np.arange(n, dtype=np.int32)
    written = write_weights(
        obj,
        group_indices,
        out,
        dirty,
        previous=read_weights(obj, group_indices),
        prune=1e-4,
        locked=locked,
    )
    refresh_overlay(context, obj)
    return {
        "vertices": written,
        "groups": len(group_indices),
        "mesh_vertices": n,
        "file_vertices": file_n,
        "method": method,
    }
