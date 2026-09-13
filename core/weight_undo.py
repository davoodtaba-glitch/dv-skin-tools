"""Independent weight undo stack. Stores only changed vertices per step."""

from __future__ import annotations

import numpy as np

_undo = []
_redo = []


class _Snap:
    __slots__ = ("obj_name", "group_indices", "dirty", "rows", "label", "groups", "active_vg")

    def __init__(self, obj_name, group_indices, dirty, rows, label, groups=None, active_vg=None):
        self.obj_name = obj_name
        self.group_indices = list(group_indices)
        self.dirty = np.asarray(dirty, dtype=np.int32)
        self.rows = np.array(rows, dtype=np.float32, copy=True)
        self.label = label
        # Full vertex-group state (name, lock, per-vertex weights column).
        self.groups = groups
        self.active_vg = active_vg


def clear():
    _undo.clear()
    _redo.clear()


def can_undo():
    return bool(_undo)


def can_redo():
    return bool(_redo)


def push_matrix(obj, group_indices, weights, label="", dirty=None):
    """Save pre-edit weights. `weights` is (nverts, I) or compact (len(dirty), I)."""
    if obj is None or weights is None:
        return
    if dirty is None:
        dirty = np.arange(weights.shape[0], dtype=np.int32)
        rows = weights
    else:
        dirty = np.unique(np.asarray(dirty, dtype=np.int32))
        if dirty.size == 0:
            return
        rows = weights if weights.shape[0] == dirty.size else weights[dirty]
    if _undo:
        last = _undo[-1]
        if (
            last.obj_name == obj.name
            and last.dirty.size == dirty.size
            and np.array_equal(last.dirty, dirty)
            and last.rows.shape == rows.shape
            and np.allclose(last.rows, rows, atol=1e-6)
        ):
            return
    _redo.clear()
    _undo.append(_Snap(obj.name, group_indices, dirty, rows, label))


def push_current(obj, group_indices, label="", dirty=None):
    from .weights import read_weight_rows, read_weights

    if dirty is None:
        w = read_weights(obj, group_indices)
        dirty = np.arange(w.shape[0], dtype=np.int32)
        push_matrix(obj, group_indices, w, label=label, dirty=dirty)
        return
    dirty = np.unique(np.asarray(dirty, dtype=np.int32))
    rows = read_weight_rows(obj, group_indices, dirty)
    push_matrix(obj, group_indices, rows, label=label, dirty=dirty)


def _capture_groups_snap(obj, label):
    """Full vertex-group snapshot: names, locks, active index, weights."""
    from .weights import read_weights

    idx = [vg.index for vg in obj.vertex_groups]
    weights = read_weights(obj, idx)
    groups = [
        (vg.name, bool(vg.lock_weight), weights[:, local].copy())
        for local, vg in enumerate(obj.vertex_groups)
    ]
    return _Snap(
        obj.name, [], np.zeros(0, np.int32),
        np.zeros((0, 0), np.float32), label,
        groups=groups, active_vg=obj.vertex_groups.active_index,
    )


def push_groups(obj, label="groups"):
    """Push the full vertex-group state so undo can restore deletions."""
    if obj is None or not obj.vertex_groups:
        return
    _redo.clear()
    _undo.append(_capture_groups_snap(obj, label))


def _restore_groups(context, obj, snap):
    from .weights import refresh_overlay, write_weights

    obj.vertex_groups.clear()
    n = len(obj.data.vertices)
    dirty = np.arange(n, dtype=np.int32)
    for name, lock, column in snap.groups:
        vg = obj.vertex_groups.new(name=name)
        vg.lock_weight = lock
        write_weights(
            obj, [vg.index], column.reshape(n, 1), dirty,
            previous=None, prune=1e-4, locked=None,
        )
    if 0 <= snap.active_vg < len(obj.vertex_groups):
        obj.vertex_groups.active_index = snap.active_vg
    obj.data.update()
    obj.update_tag(refresh={'DATA', 'OBJECT'})
    refresh_overlay(context, obj)
    return True


def _restore(context, snap):
    import bpy

    from .weights import refresh_overlay, write_weights

    obj = bpy.data.objects.get(snap.obj_name)
    if obj is None or obj.type != 'MESH':
        return False
    write_weights(
        obj,
        snap.group_indices,
        snap.rows,
        snap.dirty,
        previous=None,
        prune=1e-6,
        locked=None,
    )
    obj.data.update()
    obj.update_tag(refresh={'DATA', 'OBJECT'})
    refresh_overlay(context, obj, dirty=snap.dirty, rows=snap.rows)
    return True


def _snap_current_region(obj, snap, label):
    from .weights import read_weight_rows

    rows = read_weight_rows(obj, snap.group_indices, snap.dirty)
    return _Snap(obj.name, snap.group_indices, snap.dirty, rows, label)


def undo(context):
    import bpy

    if not _undo:
        return False
    snap = _undo.pop()
    if snap.groups is not None:
        obj = bpy.data.objects.get(snap.obj_name)
        if obj is None or obj.type != 'MESH':
            return False
        _redo.append(_capture_groups_snap(obj, "redo"))
        return _restore_groups(context, obj, snap)
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return False
    _redo.append(_snap_current_region(obj, snap, "redo"))
    return _restore(context, snap)


def redo(context):
    import bpy

    if not _redo:
        return False
    snap = _redo.pop()
    if snap.groups is not None:
        obj = bpy.data.objects.get(snap.obj_name)
        if obj is None or obj.type != 'MESH':
            return False
        _undo.append(_capture_groups_snap(obj, "undo"))
        return _restore_groups(context, obj, snap)
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return False
    _undo.append(_snap_current_region(obj, snap, "undo"))
    return _restore(context, snap)
