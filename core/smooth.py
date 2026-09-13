"""Multi-influence Laplacian smooth / sharpen.

Operates on every influence of a vertex at once, then re-normalizes.
Maya-style relative smooth: neighboring vertices keep proportional
weight transitions instead of each vertex taking an independent mix.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-12


def apply_falloff(distances, radius, shape):
    """Return per-vertex factors in [0, 1] from distances and a world-space radius."""
    dist = np.asarray(distances, dtype=np.float32)
    rad = max(float(radius), _EPS)
    t = np.clip(dist / rad, 0.0, 1.0)
    if shape == 'CONSTANT':
        return (t < 1.0).astype(np.float32)
    if shape == 'LINEAR':
        return (1.0 - t).astype(np.float32)
    if shape == 'SPHERE':
        return np.sqrt(np.maximum(1.0 - t * t, 0.0)).astype(np.float32)
    x = 1.0 - t
    return (x * x * (3.0 - 2.0 * x)).astype(np.float32)


def neighbor_average_csr(weights, offsets, neighbors, indices, world_co=None):
    """Inverse-distance mean of (self + edge neighbors).

    Closer vertices dominate so nearby points keep similar weights.
    Self is included on purpose. A grid is bipartite, so averaging *only*
    neighbors at intensity 1.0 swaps the even/odd sets and makes a
    checkerboard. Smooth damps instead of swapping.
    """
    ninf = weights.shape[1]
    out = np.empty((len(indices), ninf), dtype=weights.dtype)
    co = None if world_co is None else np.asarray(world_co, dtype=np.float32)
    for k, vi in enumerate(indices):
        start = offsets[vi]
        end = offsets[vi + 1]
        if end <= start:
            out[k] = weights[vi]
            continue
        nbrs = neighbors[start:end]
        if co is None:
            acc = weights[nbrs].sum(axis=0) + weights[vi]
            out[k] = acc / float((end - start) + 1)
            continue
        delta = co[nbrs] - co[vi]
        dist = np.sqrt((delta * delta).sum(axis=1))
        inv = 1.0 / np.maximum(dist, 1e-8)
        acc = (weights[nbrs] * inv[:, None]).sum(axis=0)
        self_w = float(inv.mean())
        out[k] = (acc + weights[vi] * self_w) / (float(inv.sum()) + self_w)
    return out


def neighbor_average_volume(weights, world_co, kdtree, indices, radius):
    """Inverse-distance mean of spatially nearby weight rows, including self."""
    ninf = weights.shape[1]
    out = np.empty((len(indices), ninf), dtype=weights.dtype)
    rad = max(float(radius), _EPS)
    for k, vi in enumerate(indices):
        hits = kdtree.find_range(world_co[vi], rad)
        if not hits:
            out[k] = weights[vi]
            continue
        ids = np.array([idx for _co, idx, _dist in hits], dtype=np.int64)
        dists = np.array([d for _co, _idx, d in hits], dtype=np.float32)
        inv = np.where(dists < 1e-12, 0.0, 1.0 / np.maximum(dists, 1e-8))
        pos = inv > 0.0
        if not np.any(pos):
            out[k] = weights[vi]
            continue
        self_w = float(inv[pos].mean())
        acc = (weights[ids] * inv[:, None]).sum(axis=0)
        out[k] = (acc + weights[vi] * self_w) / (float(inv.sum()) + self_w)
    return out


def coherentize_factors(factors, indices, offsets, neighbors, world_co, rings=1):
    """Lift each vertex's mix toward high-factor mesh neighbors.

    Brush falloff is Euclidean, so two verts that share an edge can get
    1.0 vs 0.2. Independent lerps then tear the weight gradient. Close
    neighbors inherit a decayed copy of the stronger factor so they
    move together.
    """
    idx = np.asarray(indices, dtype=np.int64)
    fac = np.clip(np.asarray(factors, dtype=np.float32), 0.0, 1.0)
    if idx.size == 0 or offsets is None or neighbors is None:
        return fac
    nverts = len(offsets) - 1
    field = np.zeros(nverts, dtype=np.float32)
    field[idx] = fac
    co = np.asarray(world_co, dtype=np.float32)
    steps = max(int(rings), 0)
    for _ in range(steps):
        nxt = field.copy()
        for vi in idx:
            start = offsets[vi]
            end = offsets[vi + 1]
            if end <= start:
                continue
            nbrs = neighbors[start:end]
            delta = co[nbrs] - co[vi]
            dist = np.sqrt((delta * delta).sum(axis=1))
            mean_d = max(float(dist.mean()) if dist.size else 1.0, 1e-8)
            inherit = field[nbrs] * np.clip(1.0 - 0.2 * (dist / mean_d), 0.5, 1.0)
            m = float(inherit.max()) if inherit.size else 0.0
            if m > nxt[vi]:
                nxt[vi] = m
        field = nxt
    return field[idx]


def _edge_partner_rows(weights, idx, edge_map, edge_t):
    """Interpolated weights on the projected border edge, per vertex."""
    ea = np.asarray(edge_map[idx, 0], dtype=np.int64)
    eb = np.asarray(edge_map[idx, 1], dtype=np.int64)
    et = np.asarray(edge_t[idx], dtype=np.float32)[:, None]
    return weights[ea] * (1.0 - et) + weights[eb] * et


def stitch_targets(weights, indices, partner, edge_map=None, edge_t=None):
    """Row-wise midpoint between each vertex and its cross-seam partner.

    ``partner`` is the vertex-pair map (see
    :func:`core.mesh_data.build_stitch_map`); ``edge_map`` / ``edge_t``
    describe the edge-projection fallback used when a border vertex has
    no vertex partner — the target is the weights interpolated at the
    projection point on the other side's border edge. Unpaired vertices
    target themselves — a no-op blend.
    """
    idx = np.asarray(indices, dtype=np.int64)
    out = np.array(weights[idx], dtype=np.float32, copy=True)
    if partner is not None:
        p = np.asarray(partner)[idx]
        valid = p >= 0
        if np.any(valid):
            out[valid] = (out[valid] + weights[p[valid]]) * 0.5
    if edge_map is not None:
        em = np.asarray(edge_map)
        on_edge = (em[idx, 0] >= 0) & (em[idx, 1] >= 0)
        if np.any(on_edge):
            sub = idx[on_edge]
            interp = _edge_partner_rows(weights, sub, em, np.asarray(edge_t))
            out[on_edge] = (out[on_edge] + interp) * 0.5
    return out


def border_sync_indices(indices, partner, edge_map=None):
    """Gathered vertices with a seam pairing, plus vertex partners.

    A vertex counts as paired when it has a vertex partner or an
    edge-projection fallback. Those rows are what a border-sync pass
    must touch so both sides of a split seam end up with matching
    weights; vertex partners are written too (they were not gathered).
    Edge endpoints never change from the projection, so they are not
    included. Returns ``None`` when nothing is paired.
    """
    if partner is None and edge_map is None:
        return None
    idx = np.asarray(indices, dtype=np.int64)
    paired = np.zeros(idx.size, dtype=bool)
    p = None
    if partner is not None:
        p = np.asarray(partner)[idx]
        paired |= p >= 0
    if edge_map is not None:
        em = np.asarray(edge_map)[idx]
        paired |= (em[:, 0] >= 0) & (em[:, 1] >= 0)
    if not np.any(paired):
        return None
    members = [idx[paired]]
    if p is not None:
        vp = paired & (p >= 0)
        if np.any(vp):
            members.append(p[vp])
    return np.unique(np.concatenate(members)).astype(np.int32)


def normalize_unlocked(rows, locked):
    """Preserve locked influences and make each row sum to 1.0 using unlocked ones."""
    unlocked = ~locked
    if not np.any(unlocked):
        return rows
    out = np.array(rows, dtype=np.float32, copy=True)
    if np.any(locked):
        locked_sum = out[:, locked].sum(axis=1, keepdims=True)
    else:
        locked_sum = np.zeros((out.shape[0], 1), dtype=np.float32)
    remain = np.clip(1.0 - locked_sum, 0.0, 1.0)
    u = out[:, unlocked]
    usum = u.sum(axis=1, keepdims=True)
    scale = np.divide(remain, usum, out=np.zeros_like(usum), where=usum > _EPS)
    out[:, unlocked] = u * scale
    return out


def prune_and_limit(rows, locked, prune, max_influences):
    """Zero tiny unlocked weights and optionally keep only the strongest ones."""
    unlocked = ~locked
    out = np.array(rows, dtype=np.float32, copy=True)
    if prune > 0.0 and np.any(unlocked):
        small = (out < prune) & unlocked[None, :]
        out[small] = 0.0

    if max_influences and max_influences > 0 and np.any(unlocked):
        n_locked = int(np.count_nonzero(locked))
        keep_u = max(int(max_influences) - n_locked, 0)
        uidx = np.where(unlocked)[0]
        for i in range(out.shape[0]):
            vals = out[i, uidx]
            if keep_u == 0:
                out[i, uidx] = 0.0
                continue
            if vals.size <= keep_u:
                continue
            order = np.argsort(vals, kind='stable')[::-1]
            keep = order[:keep_u]
            newv = np.zeros_like(vals)
            newv[keep] = vals[keep]
            out[i, uidx] = newv
    return normalize_unlocked(out, locked)


def smooth_weights(
    weights,
    indices,
    targets,
    factors,
    *,
    locked,
    only_existing=True,
    iterations=1,
    mode='SMOOTH',
    prune=1e-4,
    max_influences=0,
    neighbor_fn=None,
):
    """Blend selected vertices toward neighbor averages.

    Smooth is Maya-style relative: neighboring vertices are coupled so
    a strong mix cannot leave an adjacent vertex behind. Sharpen stays
    an independent push away from the neighbor average.

    Parameters
    ----------
    weights : (N, I) float array, modified in place
    indices : 1D vertex indices to edit
    targets : (len(indices), I) neighbor averages for the first iteration
              Ignored on later iterations if neighbor_fn is given.
    factors : (len(indices),) blend weights in [0, 1]
    locked : (I,) bool
    neighbor_fn : optional callable(weights, indices) -> (len(indices), I)
                  used to recompute averages between iterations
    """
    if len(indices) == 0:
        return weights

    indices = np.asarray(indices, dtype=np.int32)
    factors = np.clip(np.asarray(factors, dtype=np.float32), 0.0, 1.0)
    locked = np.asarray(locked, dtype=bool)
    target = np.asarray(targets, dtype=np.float32)
    iters = max(int(iterations), 1)

    for step in range(iters):
        if step > 0 and neighbor_fn is not None:
            target = neighbor_fn(weights, indices)
        cur = weights[indices]
        avg = np.array(target, dtype=np.float32, copy=True)
        if only_existing:
            avg = np.where(cur > prune, avg, 0.0)
            empty = avg.sum(axis=1) <= _EPS
            if np.any(empty):
                avg[empty] = cur[empty]
        if mode == 'SHARPEN':
            nxt = cur + (cur - avg)
            nxt = np.clip(nxt, 0.0, None)
        else:
            nxt = avg
        if np.any(locked):
            nxt[:, locked] = cur[:, locked]
        f = factors[:, None]
        blended = cur * (1.0 - f) + nxt * f
        if (
            mode != 'SHARPEN'
            and neighbor_fn is not None
            and float(np.max(factors) - np.min(factors)) > 1e-4
        ):
            for _ in range(3):
                if np.any(locked):
                    blended[:, locked] = cur[:, locked]
                blended = np.clip(blended, 0.0, None)
                weights[indices] = blended
                avg = np.array(neighbor_fn(weights, indices), dtype=np.float32, copy=True)
                if only_existing:
                    avg = np.where(cur > prune, avg, 0.0)
                    empty = avg.sum(axis=1) <= _EPS
                    if np.any(empty):
                        avg[empty] = cur[empty]
                if np.any(locked):
                    avg[:, locked] = cur[:, locked]
                blended = cur * (1.0 - f) + avg * f
        if np.any(locked):
            blended[:, locked] = cur[:, locked]
        blended = np.clip(blended, 0.0, None)
        blended = prune_and_limit(blended, locked, prune, max_influences)
        weights[indices] = blended
    return weights
