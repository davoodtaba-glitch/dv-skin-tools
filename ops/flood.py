import numpy as np
import bpy
from bpy.types import Operator

from ..core.influence import active_local_index
from ..core.mesh_data import build_mesh_cache, ensure_stitch_map
from ..core.paint import apply_single_influence
from ..core.smooth import (
    border_sync_indices,
    coherentize_factors,
    neighbor_average_csr,
    neighbor_average_volume,
    smooth_weights,
    stitch_targets,
)
from ..core.weights import read_weights, refresh_overlay, write_weights
from ..properties import _settings_from, ensure_radius


def _stitch_tol_local(settings):
    """Stitch Threshold in local mesh units, or None for the automatic
    half-edge-length default (same convention as Mirror Threshold)."""
    value = float(getattr(settings, "stitch_threshold", 0.0) or 0.0)
    return value if value > 0.0 else None


def _border_sync_set(cache, settings, indices, mode=None):
    """Vertices a Sync Border Weights pass will touch, or None.

    Gathered border vertices that have a seam partner within the stitch
    threshold, plus the partners themselves (they are written too, and
    undo bookkeeping must cover them). ``mode`` defaults to the panel
    setting; callers that ctrl-flip the mode pass the flipped value.
    """
    mode = mode or settings.mode
    if mode not in {'SMOOTH', 'SHARPEN'}:
        return None
    if not getattr(settings, "sync_border_weights", False):
        return None
    ensure_stitch_map(cache, _stitch_tol_local(settings))
    return border_sync_indices(
        indices,
        getattr(cache, "stitch_map", None),
        getattr(cache, "stitch_edge_map", None),
    )


def _neighbor_fn(cache, settings):
    if settings.neighbor_mode == 'VOLUME':
        radius = cache.volume_radius(settings)

        def fn(weights, indices):
            return neighbor_average_volume(
                weights, cache.world_co, cache.kdtree, indices, radius
            )

        return fn

    def fn(weights, indices):
        return neighbor_average_csr(
            weights, cache.offsets, cache.neighbors, indices, cache.world_co
        )

    return fn


def apply_paint_to_indices(context, obj, cache, settings, indices, factors, mode=None, intensity=None, mirror_mask=None):
    if indices.size == 0:
        return 0
    mode = mode or settings.mode
    if intensity is None:
        intensity = settings.intensity
    locked = cache.effective_locked(settings.target)
    if cache.weights is None:
        cache.weights = read_weights(obj, cache.group_indices)
    previous = cache.weights.copy()

    if mode in {'SMOOTH', 'SHARPEN'}:
        neighbor_fn = _neighbor_fn(cache, settings)
        smooth_factors = factors
        if mode == 'SMOOTH':
            smooth_factors = coherentize_factors(
                factors,
                indices,
                cache.offsets,
                cache.neighbors,
                cache.world_co,
            )
        targets = neighbor_fn(cache.weights, indices)
        smooth_weights(
            cache.weights,
            indices,
            targets,
            smooth_factors,
            locked=locked,
            only_existing=settings.only_existing,
            iterations=settings.iterations,
            mode=mode,
            prune=settings.prune,
            max_influences=settings.max_influences,
            neighbor_fn=neighbor_fn,
        )
        # Sync Border Weights: re-unify split-seam pairs after smoothing
        # (factor 1.0 toward the pair midpoint) so the open border cannot
        # drift apart while brushing. Partners outside the gathered set
        # are included and written too.
        sync_set = _border_sync_set(cache, settings, indices, mode)
        write_dirty = indices
        if sync_set is not None:
            partner = np.asarray(cache.stitch_map)
            sync_targets = stitch_targets(
                cache.weights,
                sync_set,
                partner,
                getattr(cache, "stitch_edge_map", None),
                getattr(cache, "stitch_edge_t", None),
            )
            smooth_weights(
                cache.weights,
                sync_set,
                sync_targets,
                np.ones(len(sync_set), dtype=np.float32),
                locked=locked,
                only_existing=settings.only_existing,
                iterations=1,
                mode='SMOOTH',
                prune=settings.prune,
                max_influences=settings.max_influences,
            )
            write_dirty = np.union1d(indices, sync_set)
        written = write_weights(
            obj,
            cache.group_indices,
            cache.weights,
            write_dirty,
            previous=previous,
            prune=settings.prune,
            locked=locked,
        )
        refresh_overlay(context, obj)
        return written

    if mode == 'STITCH':
        # Blend each border vertex toward the midpoint of itself and its
        # cross-seam partner. Targets recompute per iteration so uneven
        # falloff factors keep re-centering on the live pair midpoint.
        ensure_stitch_map(cache, _stitch_tol_local(settings))
        partner = getattr(cache, "stitch_map", None)
        if partner is not None:
            partner = np.asarray(partner)
            edge_map = getattr(cache, "stitch_edge_map", None)
            edge_t = getattr(cache, "stitch_edge_t", None)

            def stitch_fn(w, idx):
                return stitch_targets(w, idx, partner, edge_map, edge_t)

            targets = stitch_fn(cache.weights, indices)
            smooth_weights(
                cache.weights,
                indices,
                targets,
                factors,
                locked=locked,
                only_existing=settings.only_existing,
                iterations=settings.iterations,
                mode='SMOOTH',
                prune=settings.prune,
                max_influences=settings.max_influences,
                neighbor_fn=stitch_fn,
            )
            written = write_weights(
                obj,
                cache.group_indices,
                cache.weights,
                indices,
                previous=previous,
                prune=settings.prune,
                locked=locked,
            )
            refresh_overlay(context, obj)
            return written
        return 0

    active = active_local_index(obj, cache.group_indices)
    if active < 0:
        return 0

    # Interactive X-mirror: mirrored vertices are painted with the
    # opposite-side bone (R.arm -> L.arm). Center bones map to
    # themselves; a missing opposite group means the mirrored vertex
    # is skipped instead of receiving the wrong bone.
    mirror_mask = None if mirror_mask is None else np.asarray(mirror_mask, dtype=bool)
    if (
        mirror_mask is not None
        and mirror_mask.shape[0] == np.asarray(indices).shape[0]
        and bool(np.any(mirror_mask))
    ):
        from ..core.mirror import flipped_mask, mirrored_local_index

        pattern = str(getattr(settings, "mirror_pattern", "") or "")
        indices = np.asarray(indices, dtype=np.int32)
        factors = np.asarray(factors, dtype=np.float32)
        orig_idx = indices[~mirror_mask]
        orig_fac = factors[~mirror_mask]
        mirr_idx = indices[mirror_mask]
        mirr_fac = factors[mirror_mask]
        flipped = mirrored_local_index(obj, cache.group_indices, active, pattern)
        if flipped < 0:
            # No opposite bone: paint only the direct side.
            if orig_idx.size == 0:
                return 0
            apply_single_influence(
                cache.weights,
                orig_idx,
                orig_fac,
                active,
                locked=locked,
                mode=mode,
                intensity=intensity,
                prune=settings.prune,
                max_influences=settings.max_influences,
            )
            written = write_weights(
                obj,
                cache.group_indices,
                cache.weights,
                orig_idx,
                previous=previous,
                prune=settings.prune,
                locked=locked,
            )
            refresh_overlay(context, obj)
            return written
        if flipped == active:
            # Center bone: same influence on both sides.
            apply_single_influence(
                cache.weights,
                indices,
                factors,
                active,
                locked=locked,
                mode=mode,
                intensity=intensity,
                prune=settings.prune,
                max_influences=settings.max_influences,
            )
            written = write_weights(
                obj,
                cache.group_indices,
                cache.weights,
                indices,
                previous=previous,
                prune=settings.prune,
                locked=locked,
            )
            refresh_overlay(context, obj)
            return written
        # SELECTED isolation follows the bone: L.arm counts as selected
        # on mirrored verts when R.arm is selected.
        locked_mirr = np.array(cache.locked, dtype=bool, copy=True)
        if settings.target == 'SELECTED':
            selected_mirr = flipped_mask(cache.selected, obj, cache.group_indices, pattern)
            locked_mirr |= ~selected_mirr
        if orig_idx.size:
            apply_single_influence(
                cache.weights,
                orig_idx,
                orig_fac,
                active,
                locked=locked,
                mode=mode,
                intensity=intensity,
                prune=settings.prune,
                max_influences=settings.max_influences,
            )
        if mirr_idx.size:
            apply_single_influence(
                cache.weights,
                mirr_idx,
                mirr_fac,
                int(flipped),
                locked=locked_mirr,
                mode=mode,
                intensity=intensity,
                prune=settings.prune,
                max_influences=settings.max_influences,
            )
        written = 0
        if orig_idx.size:
            written += write_weights(
                obj,
                cache.group_indices,
                cache.weights,
                orig_idx,
                previous=previous,
                prune=settings.prune,
                locked=locked,
            )
        if mirr_idx.size:
            written += write_weights(
                obj,
                cache.group_indices,
                cache.weights,
                mirr_idx,
                previous=previous,
                prune=settings.prune,
                locked=locked_mirr,
            )
        refresh_overlay(context, obj)
        return written

    apply_single_influence(
        cache.weights,
        indices,
        factors,
        active,
        locked=locked,
        mode=mode,
        intensity=intensity,
        prune=settings.prune,
        max_influences=settings.max_influences,
    )

    written = write_weights(
        obj,
        cache.group_indices,
        cache.weights,
        indices,
        previous=previous,
        prune=settings.prune,
        locked=locked,
    )
    refresh_overlay(context, obj)
    return written


# Back-compat name used by the brush.
apply_smooth_to_indices = apply_paint_to_indices


class SKIN_OT_smooth_flood(Operator):
    bl_idname = "skin_tools.smooth_flood"
    bl_label = "DV Skin Flood"
    bl_description = "Apply the current brush mode to the whole mesh (or the paint mask)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'WEIGHT_PAINT'
            and bool(obj.vertex_groups)
        )

    def execute(self, context):
        obj = context.active_object
        settings = _settings_from(context)
        ensure_radius(settings, obj)
        try:
            cache = build_mesh_cache(context, obj)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        indices = np.nonzero(cache.paint_mask)[0].astype(np.int32)
        if indices.size == 0:
            self.report({'WARNING'}, "Paint mask is empty")
            return {'CANCELLED'}

        if settings.mode in {'REPLACE', 'ADD', 'REMOVE'}:
            if active_local_index(obj, cache.group_indices) < 0:
                self.report({'ERROR'}, "Select a bone / vertex group first")
                return {'CANCELLED'}

        if settings.mode in {'REPLACE', 'ADD', 'REMOVE'}:
            factors = np.ones(len(indices), dtype=np.float32)
        else:
            factors = np.full(len(indices), settings.intensity, dtype=np.float32)
        from ..core.weight_undo import push_current

        # The undo snapshot must also cover seam partners that the
        # Sync Border Weights pass will write outside `indices`.
        sync_set = _border_sync_set(cache, settings, indices)
        undo_dirty = indices if sync_set is None else np.union1d(indices, sync_set)
        push_current(obj, cache.group_indices, "flood", dirty=undo_dirty)
        written = apply_paint_to_indices(context, obj, cache, settings, indices, factors)
        if written == 0 and settings.mode == 'STITCH':
            self.report(
                {'WARNING'},
                "No stitchable border pairs (open border edges with a nearby partner)",
            )
            return {'CANCELLED'}
        self.report({'INFO'}, f"Flood {settings.mode.lower()} on {len(indices)} vertices")
        return {'FINISHED'}
