"""Single-influence Replace / Add / Remove on a weight matrix."""

from __future__ import annotations

import numpy as np

from .smooth import normalize_unlocked, prune_and_limit

_EPS = 1e-12


def apply_single_influence(
    weights,
    indices,
    factors,
    active,
    *,
    locked,
    mode,
    intensity=1.0,
    prune=1e-4,
    max_influences=0,
):
    """Edit the active influence on selected vertices. Modifies weights in place.

    `factors` are brush falloff in [0, 1]. `intensity` is the mode strength
    (Replace uses it as the target weight).
    """
    if len(indices) == 0:
        return weights
    indices = np.asarray(indices, dtype=np.int32)
    falloff = np.clip(np.asarray(factors, dtype=np.float32), 0.0, 1.0)
    intensity = float(np.clip(intensity, 0.0, 1.0))
    locked = np.asarray(locked, dtype=bool)
    active = int(active)
    if active < 0 or active >= weights.shape[1]:
        return weights
    if locked[active]:
        return weights

    cur = np.array(weights[indices], dtype=np.float32, copy=True)
    unlocked = ~locked
    if np.any(locked):
        locked_sum = cur[:, locked].sum(axis=1)
    else:
        locked_sum = np.zeros(cur.shape[0], dtype=np.float32)
    remain_cap = np.clip(1.0 - locked_sum, 0.0, 1.0)
    active_w = cur[:, active]

    if mode == 'REPLACE':
        target = np.minimum(intensity, remain_cap)
        new_active = active_w * (1.0 - falloff) + target * falloff
    elif mode == 'ADD':
        new_active = np.clip(active_w + intensity * falloff, 0.0, remain_cap)
    elif mode == 'REMOVE':
        new_active = np.clip(active_w - intensity * falloff, 0.0, remain_cap)
    else:
        return weights

    new_active = np.clip(new_active, 0.0, remain_cap)
    leftover = np.clip(remain_cap - new_active, 0.0, 1.0)

    other = unlocked.copy()
    other[active] = False
    out = cur.copy()
    if np.any(other):
        others = np.clip(cur[:, other], 0.0, None)
        osum = others.sum(axis=1)
        scale = np.divide(leftover, osum, out=np.zeros_like(osum), where=osum > _EPS)
        out[:, other] = others * scale[:, None]
        none = (osum <= _EPS) & (leftover > _EPS)
        # No other influence to take the remainder — leave it unassigned.
        if np.any(none):
            out[none[:, None] & other[None, :]] = 0.0
    out[:, active] = new_active
    if np.any(locked):
        out[:, locked] = cur[:, locked]
    out = np.clip(out, 0.0, None)
    out = prune_and_limit(out, locked, prune, max_influences)
    weights[indices] = out
    return weights


def mode_label(mode):
    return {
        'SMOOTH': "Smooth",
        'SHARPEN': "Sharpen",
        'STITCH': "Stitch",
        'REPLACE': "Replace",
        'ADD': "Add",
        'REMOVE': "Remove",
    }.get(mode, mode)
