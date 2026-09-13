"""Build the per-mesh cache the brush and flood operators share."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

GEOM_DEBUG = bool(os.environ.get("DVSKIN_DEBUG_GATHER"))

# Geometry staleness watch: any depsgraph update (weight writes that
# re-pose the armature, undo, pose tweaks, transforms) bumps the epoch.
# Live brush caches compare their last-seen epoch and re-verify against
# the evaluated mesh instead of staying stale until a manual restart.
_GEOM_EPOCH = 0


@persistent
def _on_depsgraph_update(_scene=None, _depsgraph=None):
    global _GEOM_EPOCH

    _GEOM_EPOCH += 1


def geom_epoch():
    return _GEOM_EPOCH


def register_geom_watch():
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister_geom_watch():
    try:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    except ValueError:
        pass


def object_armature(obj):
    for mod in obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object is not None and mod.show_viewport:
            return mod.object
    return None


def _object_armature(obj):
    return object_armature(obj)


def deform_group_indices(obj):
    """Vertex-group indices that belong to deform bones (or all groups if unbound)."""
    armature = _object_armature(obj)
    if armature is None:
        return [vg.index for vg in obj.vertex_groups]

    deform_names = {bone.name for bone in armature.data.bones if bone.use_deform}
    return [vg.index for vg in obj.vertex_groups if vg.name in deform_names]


def selected_group_mask(obj, group_indices, context=None):
    """Bool mask over `group_indices` for currently selected pose bones."""
    armature = _object_armature(obj)
    selected = set()
    if armature is not None:
        for pbone in armature.pose.bones:
            if getattr(pbone, "select", False):
                selected.add(pbone.name)
        if context is not None:
            pose_obj = getattr(context, "pose_object", None)
            if pose_obj is not None and pose_obj.type == 'ARMATURE':
                for pbone in pose_obj.pose.bones:
                    if getattr(pbone, "select", False):
                        selected.add(pbone.name)
    if not selected:
        return np.ones(len(group_indices), dtype=bool)
    names = obj.vertex_groups
    return np.array([names[i].name in selected for i in group_indices], dtype=bool)


def locked_mask(obj, group_indices):
    return np.array([obj.vertex_groups[i].lock_weight for i in group_indices], dtype=bool)


def edges_to_csr(nverts, edge_verts):
    """Undirected adjacency as CSR offsets + neighbor indices."""
    if edge_verts.size == 0:
        return np.zeros(nverts + 1, dtype=np.int32), np.zeros(0, dtype=np.int32)
    a = edge_verts[:, 0]
    b = edge_verts[:, 1]
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    order = np.argsort(src, kind="mergesort")
    src = src[order]
    dst = dst[order]
    counts = np.bincount(src, minlength=nverts)
    offsets = np.zeros(nverts + 1, dtype=np.int32)
    np.cumsum(counts, out=offsets[1:])
    return offsets, dst.astype(np.int32, copy=False)


def _apply_matrix(coords, matrix):
    m = np.array(matrix, dtype=np.float64)
    return (coords @ m[:3, :3].T + m[:3, 3]).astype(np.float32)


def _evaluated_coords_and_normals(obj, context):
    """World-space coords/normals. Prefer posed mesh when topology is unchanged."""
    mesh = obj.data
    n = len(mesh.vertices)
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    try:
        src = eval_mesh if len(eval_mesh.vertices) == n else mesh
        matrix = eval_obj.matrix_world if src is eval_mesh else obj.matrix_world
        co = np.empty(n * 3, dtype=np.float32)
        no = np.empty(n * 3, dtype=np.float32)
        src.vertices.foreach_get("co", co)
        src.vertices.foreach_get("normal", no)
        world_co = _apply_matrix(co.reshape(n, 3), matrix)
        rot = np.array(matrix.to_3x3(), dtype=np.float64)
        world_no = (no.reshape(n, 3) @ rot.T).astype(np.float32)
        lengths = np.linalg.norm(world_no, axis=1, keepdims=True)
        np.divide(world_no, lengths, out=world_no, where=lengths > 1e-12)
        return world_co, world_no, depsgraph, eval_obj
    finally:
        eval_obj.to_mesh_clear()


def _build_kdtree(world_co):
    tree = KDTree(len(world_co))
    for i, co in enumerate(world_co):
        tree.insert(co, i)
    tree.balance()
    return tree


def _build_bvh(obj, context):
    depsgraph = context.evaluated_depsgraph_get()
    try:
        return BVHTree.FromObject(obj, depsgraph, epsilon=0.0)
    except Exception:
        mesh = obj.data
        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        verts = [Vector(co[i:i + 3]) for i in range(0, n * 3, 3)]
        polys = [tuple(p.vertices) for p in mesh.polygons]
        return BVHTree.FromPolygons(verts, polys)


def vertex_paint_mask(obj):
    """True for vertices the current weight-paint mask allows."""
    mesh = obj.data
    n = len(mesh.vertices)
    if mesh.use_paint_mask_vertex:
        sel = np.zeros(n, dtype=bool)
        mesh.vertices.foreach_get("select", sel)
        return sel
    if mesh.use_paint_mask:
        sel = np.zeros(n, dtype=bool)
        for poly in mesh.polygons:
            if poly.select:
                for vi in poly.vertices:
                    sel[vi] = True
        return sel
    return np.ones(n, dtype=bool)


def build_x_mirror_map(local_co, kdtree, avg_edge, max_dist=None, seam=None):
    """Mutual nearest pairs across local X. Skips the midline (chest/spine).

    ``max_dist`` / ``seam`` override the automatic tolerances (local
    mesh units).  By default they derive from the average edge length.
    """
    n = len(local_co)
    pair = np.full(n, -1, dtype=np.int32)
    if n == 0 or kdtree is None:
        return pair
    xs = local_co[:, 0]
    extent = float(np.max(xs) - np.min(xs)) if n else 0.0
    if seam is None:
        seam = max(float(avg_edge) * 0.5, extent * 0.02, 1e-5)
    if max_dist is None:
        max_dist = max(float(avg_edge) * 1.75, extent * 0.04, seam * 3.0)
    for i in range(n):
        x = float(local_co[i, 0])
        if abs(x) < seam:
            continue
        flipped = (-x, float(local_co[i, 1]), float(local_co[i, 2]))
        _co, j, dist = kdtree.find(flipped)
        if j is None or int(j) == i or dist > max_dist:
            continue
        ox = float(local_co[int(j), 0])
        if abs(ox) < seam:
            continue
        if (x > 0.0) == (ox > 0.0):
            continue
        _co2, k, _d2 = kdtree.find((-ox, float(local_co[int(j), 1]), float(local_co[int(j), 2])))
        if k is None or int(k) != i:
            continue
        pair[i] = int(j)
    return pair


def average_edge_length(world_co, edge_verts):
    if edge_verts.size == 0:
        return 0.05
    delta = world_co[edge_verts[:, 0]] - world_co[edge_verts[:, 1]]
    return float(np.mean(np.linalg.norm(delta, axis=1)))


def border_edge_mask(mesh):
    """Bool mask over ``mesh.edges``: True for edges used by one polygon.

    Open boundary (border) edges come from split seams — shells modeled
    apart, duplicated loops, sheet ends. Loose wire edges (no faces) are
    excluded; there is nothing meaningful to stitch them to.
    """
    n_edges = len(mesh.edges)
    if n_edges == 0:
        return np.zeros(0, dtype=bool)
    n_loops = len(mesh.loops)
    if n_loops == 0:
        return np.zeros(n_edges, dtype=bool)
    loop_edges = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get("edge_index", loop_edges)
    counts = np.bincount(loop_edges, minlength=n_edges)
    return counts == 1


def border_vertex_mask(nverts, edge_verts, border_edges):
    """Bool mask over vertices incident to at least one border edge."""
    mask = np.zeros(nverts, dtype=bool)
    if (
        border_edges is not None
        and border_edges.size
        and np.any(border_edges)
        and edge_verts is not None
        and edge_verts.size
    ):
        verts = np.unique(edge_verts[border_edges].ravel())
        mask[verts] = True
    return mask


def stitch_max_distance(local_co, edge_verts):
    """Automatic stitch pairing tolerance: half the average edge length.

    Coincident seam partners sit at distance ~0, while the next vertex
    along the same border loop is a full edge away — the cutoff stays
    below that so a border loop never pairs with itself.
    """
    if edge_verts is not None and edge_verts.size:
        delta = local_co[edge_verts[:, 0]] - local_co[edge_verts[:, 1]]
        avg = float(np.mean(np.linalg.norm(delta, axis=1)))
    else:
        avg = 0.05
    return max(avg * 0.5, 1e-6)


def border_edge_verts_from_mask(border_edges, edge_verts):
    """(Eb, 2) vertex table of open boundary edges from the bool mask."""
    if (
        border_edges is not None
        and np.any(border_edges)
        and edge_verts is not None
        and edge_verts.size
    ):
        return np.asarray(edge_verts[border_edges], dtype=np.int32)
    return np.zeros((0, 2), dtype=np.int32)


def _border_loop_components(border_edge_verts):
    """Connected components (loops/chains) of the border-edge graph.

    Vertices joined by a border edge share a component, so every edge
    of one open border belongs to the same id. Used to keep the edge
    fallback away from the vertex's own border.
    """
    parent = {}

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in border_edge_verts:
        a, b = int(a), int(b)
        for v in (a, b):
            if v not in parent:
                parent[v] = v
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return {v: find(v) for v in parent}


def build_stitch_map(local_co, kdtree, offsets, neighbors, border_verts,
                     border_edge_verts, max_dist):
    """Cross-seam partner for each border vertex (rest pose).

    Split seams usually mean two coincident (or nearly touching)
    duplicated border loops. Pass 1 pairs every border vertex with the
    closest other border vertex within ``max_dist`` (local mesh units)
    that is not already an edge neighbor. Pass 2 handles mismatched
    tessellation: vertices without a vertex partner are projected onto
    the nearest border edge of a *different* border loop (own loops and
    neighbor-touching edges are excluded); the edge endpoints and the
    projection parameter are stored so weights can be interpolated
    along it at paint time.

    Returns ``(pair, edge_map, edge_t)``: int32 vertex map (-1 =
    unpaired), int32 (n, 2) edge endpoint map (-1 = none) and float32
    (n,) projection parameter.
    """
    n = len(local_co)
    pair = np.full(n, -1, dtype=np.int32)
    edge_map = np.full((n, 2), -1, dtype=np.int32)
    edge_t = np.zeros(n, dtype=np.float32)
    if kdtree is None or not np.any(border_verts):
        return pair, edge_map, edge_t
    for i in np.nonzero(border_verts)[0]:
        i = int(i)
        nbrs = set(neighbors[offsets[i]:offsets[i + 1]].tolist())
        best = -1
        best_d = 0.0
        for _co, j, d in kdtree.find_range(local_co[i], max_dist):
            j = int(j)
            if j == i or j in nbrs or not border_verts[j]:
                continue
            if best < 0 or d < best_d:
                best = j
                best_d = d
        if best >= 0:
            pair[i] = best

    if border_edge_verts is None or not len(border_edge_verts):
        return pair, edge_map, edge_t
    be = np.asarray(border_edge_verts, dtype=np.int32)
    be_a = be[:, 0]
    be_b = be[:, 1]
    comp = _border_loop_components(be)
    edge_comp = np.array([comp[int(a)] for a in be_a], dtype=np.int64)
    own = {}
    for a, b in be:
        cid = comp[int(a)]
        own.setdefault(int(a), set()).add(cid)
        own.setdefault(int(b), set()).add(cid)
    for i in np.nonzero(border_verts)[0]:
        i = int(i)
        if pair[i] >= 0:
            continue
        excl_verts = [i]
        excl_verts.extend(neighbors[offsets[i]:offsets[i + 1]].tolist())
        excl = np.isin(be_a, excl_verts) | np.isin(be_b, excl_verts)
        my_loops = own.get(i)
        if my_loops:
            excl |= np.isin(edge_comp, list(my_loops))
        cand = np.nonzero(~excl)[0]
        if cand.size == 0:
            continue
        a = local_co[be_a[cand]].astype(np.float32)
        b = local_co[be_b[cand]].astype(np.float32)
        ab = b - a
        denom = np.einsum('ij,ij->i', ab, ab)
        tt = np.einsum('ij,ij->i', local_co[i] - a, ab) / np.maximum(denom, 1e-24)
        np.clip(tt, 0.0, 1.0, out=tt)
        proj = a + tt[:, None] * ab
        dist = np.linalg.norm(local_co[i] - proj, axis=1)
        k = int(np.argmin(dist))
        if dist[k] <= max_dist:
            edge_map[i, 0] = int(be_a[cand[k]])
            edge_map[i, 1] = int(be_b[cand[k]])
            edge_t[i] = tt[k]
    return pair, edge_map, edge_t


def ensure_stitch_map(cache, tol_local=None):
    """Point the cache's stitch maps at the requested pairing tolerance.

    ``tol_local`` is in local mesh units (same convention as Mirror
    Threshold); ``None`` selects the automatic half-edge-length default
    frozen at cache build. Rebuilds the maps in place only when the
    tolerance actually changed, so strokes never pay for an unchanged
    setting. The maps are topology + rest-pose data, safe to rebuild
    mid-stroke.
    """
    if tol_local is None:
        tol_local = getattr(cache, "stitch_auto_tol", None)
        if tol_local is None:
            tol_local = stitch_max_distance(cache.local_co, cache.edge_verts)
            cache.stitch_auto_tol = tol_local
    if tol_local == getattr(cache, "stitch_map_tol", None):
        return
    pair, edge_map, edge_t = build_stitch_map(
        cache.local_co, cache.local_kdtree, cache.offsets,
        cache.neighbors, cache.border_verts, _border_edges(cache),
        tol_local,
    )
    cache.stitch_map = pair
    cache.stitch_edge_map = edge_map
    cache.stitch_edge_t = edge_t
    cache.stitch_map_tol = tol_local


def _border_edges(cache):
    """Border-edge vertex table for the cache, rebuilding it if absent."""
    be = getattr(cache, "border_edge_verts", None)
    if be is None:
        be = (
            cache.edge_verts[cache.border_edges]
            if cache.border_edges is not None and cache.border_edges.size
            and np.any(cache.border_edges)
            else np.zeros((0, 2), dtype=np.int32)
        )
        cache.border_edge_verts = be
    return be


@dataclass
class MeshCache:
    obj_name: str
    nverts: int
    group_indices: list
    locked: np.ndarray
    selected: np.ndarray
    offsets: np.ndarray
    neighbors: np.ndarray
    world_co: np.ndarray
    world_no: np.ndarray
    paint_mask: np.ndarray
    local_co: np.ndarray
    avg_edge: float
    kdtree: object = None
    local_kdtree: object = None
    bvh: object = None
    matrix_world: object = None
    matrix_world_inv: object = None
    mirror_map: np.ndarray = field(default=None)
    weights: np.ndarray = field(default=None)
    # Vertices on open boundary edges (split seams, shell edges).
    border_verts: np.ndarray = field(default=None)
    # (Eb, 2) vertex table of open boundary edges (subset of edge_verts).
    border_edges: np.ndarray = field(default=None)
    border_edge_verts: np.ndarray = field(default=None)
    # Nearest cross-seam partner per border vertex (-1 = unpaired).
    stitch_map: np.ndarray = field(default=None)
    # Edge-projection fallback: (n, 2) endpoints + (n,) parameter. Used
    # when no vertex partner exists within the tolerance.
    stitch_edge_map: np.ndarray = field(default=None)
    stitch_edge_t: np.ndarray = field(default=None)
    # Tolerance (local units) the stitch maps were built with.
    stitch_map_tol: float = field(default=None)
    # Automatic tolerance frozen at cache build.
    stitch_auto_tol: float = field(default=None)
    # (E, 2) vertex-index table so edge lengths can be refreshed without
    # re-reading topology (see refresh_geometry).
    edge_verts: np.ndarray = field(default=None)
    # Last depsgraph epoch this cache verified against (-1 = never).
    _geom_epoch: int = field(default=-1, repr=False)

    def effective_locked(self, target):
        locked = np.array(self.locked, dtype=bool, copy=True)
        if target == 'SELECTED':
            # Unselected bones behave like locked — a layer-less isolation stand-in.
            locked |= ~self.selected
        return locked

    def volume_radius(self, settings):
        if settings.volume_radius > 0.0:
            return float(settings.volume_radius)
        return max(self.avg_edge * 1.35, 1e-6)

    # ------------------------------------------------------------------
    # Staleness detection & repair
    #
    # The cache snapshots the evaluated (posed, deformed) surface when
    # the tool starts. Weight writes re-evaluate the armature modifier
    # and move that surface, so the snapshot drifts away from what the
    # viewport shows: raycasts then hit the old surface, gathered
    # distances no longer match the visible geometry, and whole regions
    # become silent no-ops until the tool is disabled and re-enabled
    # (the one operation that rebuilt this state). position_drift()
    # measures the drift; refresh_geometry() repairs the cache in place,
    # without touching stroke state.
    # ------------------------------------------------------------------

    def position_drift(self, context, obj):
        """Largest world-space movement of the evaluated mesh vs the cache.

        Full-array compare against the CURRENT evaluated coordinates
        (C-speed foreach_get + one numpy pass, a few ms even on dense
        meshes). Also folds in the object transform so grabbing/moving
        the object counts as drift. Returns inf when the vertex count
        changed (topology edit): the cache is unusable, not just stale.
        """
        n = self.nverts
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh(
            preserve_all_data_layers=False, depsgraph=depsgraph
        )
        try:
            if len(eval_mesh.vertices) != n:
                return float("inf")
            flat = np.empty(n * 3, dtype=np.float32)
            eval_mesh.vertices.foreach_get("co", flat)
        finally:
            eval_obj.to_mesh_clear()
        eval_co = _apply_matrix(flat.reshape(n, 3), obj.matrix_world)
        delta = eval_co - self.world_co
        drift = float(np.max(np.linalg.norm(delta, axis=1)))
        if self.matrix_world is not None:
            mdelta = np.abs(
                np.array(obj.matrix_world) - np.array(self.matrix_world)
            )
            drift = max(drift, float(np.max(mdelta)))
        return drift

    def refresh_geometry(self, context, obj, rebuild_spatial=True):
        """Rebuild the geometry-dependent parts of the cache in place.

        World coords, normals, transform, paint mask and edge lengths
        are always re-derived from the current evaluated mesh (cheap,
        C-speed fetches). With ``rebuild_spatial`` the KDTree and BVH
        are rebuilt too (the expensive part) — callers pass False for
        tiny drift where only the cheap arrays need to catch up.
        Topology (offsets/neighbors), group lists, the weights matrix
        and all stroke bookkeeping are preserved, so a refresh
        mid-stroke is safe and never loses the in-flight undo snapshot.
        Raises RuntimeError when the vertex count changed (topology
        edit) — callers must fall back to a full build_mesh_cache().
        """
        n = self.nverts
        world_co, world_no, _deps, _eval = _evaluated_coords_and_normals(
            obj, context
        )
        if len(world_co) != n:
            raise RuntimeError("topology changed")
        self.world_co = world_co
        self.world_no = world_no
        if rebuild_spatial:
            self.kdtree = _build_kdtree(world_co)
            self.bvh = _build_bvh(obj, context)
        self.matrix_world = obj.matrix_world.copy()
        self.matrix_world_inv = obj.matrix_world.inverted()
        self.paint_mask = vertex_paint_mask(obj)
        if self.edge_verts is not None and self.edge_verts.size:
            self.avg_edge = average_edge_length(world_co, self.edge_verts)
        self._geom_epoch = geom_epoch()
        if GEOM_DEBUG:
            print(
                f"[DV Skin] geometry refresh: epoch={self._geom_epoch} "
                f"nverts={n} avg_edge={self.avg_edge:.4f} "
                f"spatial={rebuild_spatial}"
            )


def build_mesh_cache(context, obj):
    mesh = obj.data
    n = len(mesh.vertices)
    group_indices = deform_group_indices(obj)
    if not group_indices:
        raise RuntimeError("No deform vertex groups on the active mesh")

    n_edges = len(mesh.edges)
    edge_flat = np.empty(n_edges * 2, dtype=np.int32)
    if n_edges:
        mesh.edges.foreach_get("vertices", edge_flat)
    edge_verts = edge_flat.reshape(n_edges, 2) if n_edges else np.zeros((0, 2), dtype=np.int32)
    offsets, neighbors = edges_to_csr(n, edge_verts)

    local = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", local)
    local_co = local.reshape(n, 3)

    border_edges = border_edge_mask(mesh)
    border_verts = border_vertex_mask(n, edge_verts, border_edges)

    world_co, world_no, _deps, _eval = _evaluated_coords_and_normals(obj, context)
    avg_edge = average_edge_length(world_co, edge_verts)
    local_kdtree = _build_kdtree(local_co)
    cache = MeshCache(
        obj_name=obj.name,
        nverts=n,
        group_indices=group_indices,
        locked=locked_mask(obj, group_indices),
        selected=selected_group_mask(obj, group_indices, context),
        offsets=offsets,
        neighbors=neighbors,
        world_co=world_co,
        world_no=world_no,
        paint_mask=vertex_paint_mask(obj),
        local_co=local_co,
        avg_edge=avg_edge,
        kdtree=_build_kdtree(world_co),
        local_kdtree=local_kdtree,
        bvh=_build_bvh(obj, context),
        matrix_world=obj.matrix_world.copy(),
        matrix_world_inv=obj.matrix_world.inverted(),
        mirror_map=build_x_mirror_map(local_co, local_kdtree, avg_edge),
        border_verts=border_verts,
        edge_verts=edge_verts,
    )
    cache.stitch_auto_tol = stitch_max_distance(local_co, edge_verts)
    cache.stitch_map_tol = cache.stitch_auto_tol
    cache.border_edges = border_edges
    be = border_edge_verts_from_mask(border_edges, edge_verts)
    cache.border_edge_verts = be
    pair, edge_map, edge_t = build_stitch_map(
        local_co, local_kdtree, offsets, neighbors,
        border_verts, be, cache.stitch_auto_tol,
    )
    cache.stitch_map = pair
    cache.stitch_edge_map = edge_map
    cache.stitch_edge_t = edge_t
    return cache
