"""Mirror skin weights across the local X axis.

Reuses the proven ``build_x_mirror_map`` from mesh_data.  For each
vertex pair across X, the heavier side wins: its weights are copied
to the lighter side with bone names flipped (``.L`` <-> ``.R`` and
friends) so a left-arm weight arrives as a right-arm weight.  Bones
without an opposite (spine, root) keep their name — their weights are
copied as-is.  Vertices without a mirror partner (midline) are left
untouched.

The pair map is built from ``mesh.vertices.co`` — the undeformed rest
mesh — so the armature pose never matters: mirror works whether the
model is in rest pose, mirror pose, or mid-animation.
"""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

_EPS = 1e-12

_SIDE_SEPARATORS = (".", "_", "-", " ")

# "hand.L", "upper_arm.L.001", "l_foot", "Hand-R" …
_SUFFIX_RE = re.compile(r"^(.+?)([._\- ])([LRlr])((?:[._\- ]\d+)*)$")
# "L_hand", "r.foot" …
_PREFIX_RE = re.compile(r"^([LRlr])([._\- ])(.+?)((?:[._\- ]\d+)*)$")


def flip_side_name(name):
    """Return the opposite-side bone name, or ``name`` if it has no side.

    Handles common conventions: ``hand.L``, ``hand_l``, ``L_hand``,
    ``r_foot``, ``Hand-R``, ``upper_arm.L.001`` …  Center bones
    (``spine``, ``root``) come back unchanged.
    """
    m = _SUFFIX_RE.match(name)
    if m:
        pre, sep, tag, ext = m.groups()
        if tag in ("L", "l"):
            return pre + sep + ("R" if tag == "L" else "r") + ext
        return pre + sep + ("L" if tag == "R" else "l") + ext
    m = _PREFIX_RE.match(name)
    if m:
        tag, sep, rest, ext = m.groups()
        if tag in ("L", "l"):
            return ("R" if tag == "L" else "r") + sep + rest + ext
        return ("L" if tag == "R" else "l") + sep + rest + ext
    return name


@lru_cache(maxsize=32)
def parse_mirror_pattern(pattern):
    """Detect the side convention from one example bone name.

    ``pattern`` is a single bone name typed by the user, e.g. ``R-arm``,
    ``Arm_R``, ``R__arm`` or ``RIGHT_arm``. Returns a rule tuple:

    - ``("affix", "prefix"|"suffix", sep)`` — side letter + separator,
      e.g. ``R-`` / ``_R``. The letter case always follows the bone being
      flipped, so ``R-arm`` also covers ``r-leg``.
    - ``("word", right_word, left_word)`` — ``Right``/``Left`` style words
      as typed, e.g. ``RIGHT_arm``.

    Returns ``None`` when no side marker is found (built-in rules apply).
    """
    p = (pattern or "").strip()
    if not p:
        return None
    m = _SUFFIX_RE.match(p)
    if m:
        _pre, sep, _tag, _ext = m.groups()
        return ("affix", "suffix", sep)
    m = _PREFIX_RE.match(p)
    if m:
        _tag, sep, _rest, _ext = m.groups()
        return ("affix", "prefix", sep)
    low = p.lower()
    if "right" in low:
        i = low.index("right")
        found = p[i:i + 5]
        return ("word", found, _counterpart(found, "left"))
    if "left" in low:
        i = low.index("left")
        found = p[i:i + 4]
        return ("word", _counterpart(found, "right"), found)
    return None


def _counterpart(found, base):
    """Return ``base`` word in the case style of ``found``."""
    if found.isupper():
        return base.upper()
    if found[:1].isupper():
        return base.capitalize()
    return base.lower()


def _match_case(found, word):
    """Return ``word`` in the case style of the ``found`` occurrence."""
    return _counterpart(found, word)


def _flip_with_rule(name, rule):
    """Flip ``name`` using a :func:`parse_mirror_pattern` rule."""
    if rule[0] == "affix":
        _, pos, sep = rule
        s = re.escape(sep)
        if pos == "suffix":
            m = re.match(r"^(.*?)" + s + r"([LRlr])((?:[._\- ]\d+)*)$", name)
            if not m:
                return name
            pre, tag, ext = m.groups()
            return pre + sep + {"R": "L", "r": "l", "L": "R", "l": "r"}[tag] + ext
        m = re.match(r"^([LRlr])" + s + r"(.*?)((?:[._\- ]\d+)*)$", name)
        if not m:
            return name
        tag, rest, ext = m.groups()
        return {"R": "L", "r": "l", "L": "R", "l": "r"}[tag] + sep + rest + ext
    # Word rule: replace the first side-word occurrence, keeping the
    # bone's own case style (RIGHT_leg -> LEFT_leg).
    _, right_w, left_w = rule
    low = name.lower()
    rl, ll = right_w.lower(), left_w.lower()
    ir, il = low.find(rl), low.find(ll)
    if ir >= 0 and (il < 0 or ir <= il):
        return name[:ir] + _match_case(name[ir:ir + len(rl)], left_w) + name[ir + len(rl):]
    if il >= 0:
        return name[:il] + _match_case(name[il:il + len(ll)], right_w) + name[il + len(ll):]
    return name


def flip_side_name_with_pattern(name, pattern):
    """Flip ``name`` trying the user pattern first, then built-ins.

    An empty/unrecognized ``pattern`` behaves exactly like
    :func:`flip_side_name`.
    """
    rule = parse_mirror_pattern(pattern or "")
    if rule is not None:
        flipped = _flip_with_rule(name, rule)
        if flipped != name:
            return flipped
    return flip_side_name(name)


def describe_mirror_rule(rule):
    """Short human-readable description of a parsed pattern rule."""
    if rule is None:
        return "not recognized"
    if rule[0] == "affix":
        _, pos, sep = rule
        if pos == "prefix":
            return f"prefix 'R{sep}...' <-> 'L{sep}...'"
        return f"suffix '...{sep}R' <-> '...{sep}L'"
    _, right_w, left_w = rule
    return f"'{right_w}' <-> '{left_w}'"


def _side_flip_permutation(obj, group_indices, pattern=""):
    """Column permutation that flips bone sides for the weight matrix.

    ``perm[local]`` is the local column of the opposite-side bone, or
    the same column for center bones / groups without an opposite.
    ``pattern`` is an optional user example bone (Advanced > Mirror
    Pattern) tried before the built-in rules.
    """
    groups = obj.vertex_groups
    index_by_name = {vg.name: vg.index for vg in groups}
    local_by_gi = {gi: li for li, gi in enumerate(group_indices)}
    perm = np.arange(len(group_indices), dtype=np.int32)
    for li, gi in enumerate(group_indices):
        name = groups[gi].name
        flip = flip_side_name_with_pattern(name, pattern or "")
        if flip == name:
            continue
        other_gi = index_by_name.get(flip)
        if other_gi is None:
            continue
        other_li = local_by_gi.get(other_gi)
        if other_li is not None:
            perm[li] = other_li
    return perm


def side_flip_permutation(obj, group_indices, pattern=""):
    """Public wrapper for :func:`_side_flip_permutation`."""
    return _side_flip_permutation(obj, group_indices, pattern)


def mirrored_local_index(obj, group_indices, active_local, pattern=""):
    """Local column of the opposite-side bone for ``active_local``.

    Returns ``active_local`` itself for center bones, and ``-1`` when
    the opposite-side group does not exist (nothing to paint on the
    mirrored vertex).
    """
    try:
        active_local = int(active_local)
    except Exception:
        return -1
    if active_local < 0 or active_local >= len(group_indices):
        return -1
    groups = obj.vertex_groups
    try:
        name = groups[group_indices[active_local]].name
    except Exception:
        return -1
    flip = flip_side_name_with_pattern(name, pattern or "")
    if flip == name:
        return active_local
    try:
        index_by_name = {vg.name: vg.index for vg in groups}
        local_by_gi = {gi: li for li, gi in enumerate(group_indices)}
    except Exception:
        return -1
    other_gi = index_by_name.get(flip)
    if other_gi is None:
        return -1
    return int(local_by_gi.get(other_gi, -1))


def flipped_mask(mask, obj, group_indices, pattern=""):
    """Flip a per-influence bool mask across sides (``mask[perm]``).

    Used so ``SELECTED`` isolation follows the bone: when only ``R.arm``
    is selected, its mirror ``L.arm`` counts as selected on mirrored
    vertices.
    """
    import numpy as _np

    mask = _np.asarray(mask, dtype=bool)
    try:
        perm = _side_flip_permutation(obj, group_indices, pattern or "")
    except Exception:
        return mask
    if mask.shape[0] != perm.shape[0]:
        return mask
    return mask[perm]


def _directional_mirror_map(local_co, kdtree, seam, max_dist, source_sign):
    """Source-side vertex -> nearest opposite-side partner.

    Unlike ``build_x_mirror_map`` there is no mutual-pair check: the
    transfer direction is explicit, so every source vertex within the
    threshold of an opposite-side partner is paired.
    """
    n = len(local_co)
    pair = np.full(n, -1, dtype=np.int32)
    if n == 0 or kdtree is None:
        return pair
    xs = local_co[:, 0]
    for i in range(n):
        x = float(local_co[i, 0])
        if x * source_sign <= seam:
            continue
        flipped = (-x, float(local_co[i, 1]), float(local_co[i, 2]))
        _co, j, dist = kdtree.find(flipped)
        if j is None or int(j) == i or dist > max_dist:
            continue
        ox = float(local_co[int(j), 0])
        if abs(ox) <= seam:
            continue
        if ox * source_sign >= 0.0:
            continue
        pair[i] = int(j)
    return pair


def mirror_weights(obj, group_indices, context=None, direction='HEAVIER', threshold=0.0, pattern=""):
    """Mirror vertex-group weights across local X.

    ``direction``:
      - ``'POS_TO_NEG'`` — copy +X side onto -X side.
      - ``'NEG_TO_POS'`` — copy -X side onto +X side.
      - ``'HEAVIER'``    — mutual pairs, heavier side wins.

    ``threshold`` is the max distance between mirror vertex pairs in
    local mesh units; ``0`` derives it from the average edge length.
    ``pattern`` is an optional user example bone (Advanced > Mirror
    Pattern) tried before the built-in ``.L``/``.R`` rules.
    Returns the number of vertices that were updated.
    """
    from .mesh_data import _build_kdtree, build_x_mirror_map

    mesh = obj.data
    n = len(mesh.vertices)

    # Local coordinates (rest pose).
    local = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", local)
    local_co = local.reshape(n, 3)

    # Average edge length for tolerance defaults.
    n_edges = len(mesh.edges)
    if n_edges:
        edge_flat = np.empty(n_edges * 2, dtype=np.int32)
        mesh.edges.foreach_get("vertices", edge_flat)
        ef = edge_flat.reshape(n_edges, 2)
        delta = local_co[ef[:, 0]] - local_co[ef[:, 1]]
        avg_edge = float(np.mean(np.linalg.norm(delta, axis=1)))
    else:
        avg_edge = 0.05

    xs = local_co[:, 0]
    extent = float(np.max(xs) - np.min(xs)) if n else 0.0
    seam_auto = max(float(avg_edge) * 0.5, extent * 0.02, 1e-5)
    if threshold and threshold > 0.0:
        max_dist = float(threshold)
    else:
        max_dist = max(float(avg_edge) * 1.75, extent * 0.04, seam_auto * 3.0)
    seam = min(seam_auto, max_dist * 0.5)

    # Build mirror map.
    kdtree = _build_kdtree(local_co)
    if direction == 'POS_TO_NEG':
        pair = _directional_mirror_map(local_co, kdtree, seam, max_dist, +1.0)
    elif direction == 'NEG_TO_POS':
        pair = _directional_mirror_map(local_co, kdtree, seam, max_dist, -1.0)
    else:
        pair = build_x_mirror_map(local_co, kdtree, avg_edge, max_dist=max_dist, seam=seam)

    # Column permutation that maps bone names to their opposite side.
    perm = _side_flip_permutation(obj, group_indices, pattern or "")

    # Read all weights.
    ninf = len(group_indices)
    weights = np.zeros((n, ninf), dtype=np.float32)
    index_map = {gi: li for li, gi in enumerate(group_indices)}
    for vi, vert in enumerate(mesh.vertices):
        for elem in vert.groups:
            li = index_map.get(elem.group)
            if li is not None:
                weights[vi, li] = elem.weight

    updated = np.zeros(n, dtype=bool)

    if direction in ('POS_TO_NEG', 'NEG_TO_POS'):
        # Explicit direction: source row (with flipped bone names)
        # overwrites its partner. A completely unpainted source is
        # skipped so an unweighed region cannot erase painted weights.
        for i in range(n):
            j = int(pair[i])
            if j < 0:
                continue
            row = weights[i]
            if float(row.sum()) < _EPS:
                continue
            weights[j] = row[perm]
            updated[j] = True
    else:
        # For each pair, the heavier side wins.
        visited = set()
        for i in range(n):
            j = int(pair[i])
            if j < 0:
                continue
            key = (min(i, j), max(i, j))
            if key in visited:
                continue
            visited.add(key)

            wi = weights[i].copy()
            wj = weights[j].copy()
            si = float(wi.sum())
            sj = float(wj.sum())

            if si < _EPS and sj < _EPS:
                continue

            # Copy the heavier side to the lighter side, flipping bone
            # names so hand.L weights arrive as hand.R weights.
            if sj > si + _EPS:
                weights[i] = wj[perm]
                updated[i] = True
            elif si > sj + _EPS:
                weights[j] = wi[perm]
                updated[j] = True
            elif abs(si - sj) <= _EPS:
                # Equal total — prefer the +X side as the source (left-to-right
                # convention); fall back to index order for centered pairs.
                xi = float(local_co[i, 0])
                xj = float(local_co[int(pair[i]), 0])
                if xi > xj or (xi == xj and i < j):
                    weights[j] = wi[perm]
                    updated[j] = True
                else:
                    weights[i] = wj[perm]
                    updated[i] = True

    verts_updated = int(np.count_nonzero(updated))
    if verts_updated == 0:
        return 0

    from .weights import write_weights

    dirty = np.nonzero(updated)[0].astype(np.int32)
    write_weights(obj, group_indices, weights, dirty, previous=None, prune=1e-6, locked=None)
    return verts_updated
