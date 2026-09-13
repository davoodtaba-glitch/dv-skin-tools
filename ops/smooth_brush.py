import numpy as np
import bpy
from bpy.props import BoolProperty
from bpy.types import Operator
from mathutils import Vector
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
)

from ..core.mesh_data import (
    GEOM_DEBUG,
    build_mesh_cache,
    geom_epoch,
    register_geom_watch,
    unregister_geom_watch,
)
from ..core.smooth import apply_falloff
from ..core.weights import read_weights
from .flood import _border_sync_set, apply_smooth_to_indices
from ..properties import _settings_from, ensure_radius, restore_display_state
from ..ui import overlay

_NAV_TYPES = {
    'MIDDLEMOUSE',
    'TRACKPADPAN',
    'TRACKPADZOOM',
    'NDOF_MOTION',
    'MOUSEROTATE',
    'INBETWEEN_MOUSEMOVE',
    'WHEELUPMOUSE',
    'WHEELDOWNMOUSE',
}


def _region_contains(region, event):
    return (
        region.x <= event.mouse_x < region.x + region.width
        and region.y <= event.mouse_y < region.y + region.height
    )


def _event_over_ui(context, event):
    """True when the cursor is over a 3D-view sidebar, header, or toolbar."""
    if context.screen is None:
        return False
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            if (
                area.x <= event.mouse_x < area.x + area.width
                and area.y <= event.mouse_y < area.y + area.height
            ):
                return True
            continue
        for region in area.regions:
            if region.type == 'WINDOW':
                continue
            if _region_contains(region, event):
                return True
    return False


def _view_region(context, event):
    if context.screen is None:
        return None, None, None
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type != 'WINDOW':
                continue
            if _region_contains(region, event):
                space = area.spaces.active
                return region, space.region_3d, area
    return None, None, None


def _raycast(cache, region, rv3d, mouse):
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    if origin is None or direction is None:
        return None, None
    local_origin = cache.matrix_world_inv @ origin
    local_dir = (cache.matrix_world_inv.to_3x3() @ direction).normalized()
    hit = cache.bvh.ray_cast(local_origin, local_dir)
    if hit[0] is None:
        return None, origin
    world_hit = cache.matrix_world @ hit[0]
    return Vector(world_hit), origin


def _front_facing(cache, indices, view_dir):
    if view_dir is None or not len(indices):
        return indices
    dots = cache.world_no[indices] @ np.array(view_dir, dtype=np.float32)
    return indices[dots < 0.0]


def _mirror_indices(cache, indices, factors):
    """Append mirrored partners, tracking which rows are mirrored.

    Returns ``(all_indices, all_factors, is_mirror)`` where ``is_mirror``
    is False for directly painted vertices and True for mirrored
    partners. Vertices already under the brush win as direct hits so a
    large brush over the midline never double-paints them as mirrored.
    """
    mmap = getattr(cache, "mirror_map", None)
    if mmap is None or mmap.size == 0:
        return indices, factors, np.zeros(len(indices), dtype=bool)
    extra_i = []
    extra_f = []
    seen = set(int(i) for i in indices)
    for vi, fac in zip(indices, factors):
        mirror = int(mmap[int(vi)])
        if mirror < 0 or mirror in seen:
            continue
        seen.add(mirror)
        extra_i.append(mirror)
        extra_f.append(float(fac))
    if not extra_i:
        return indices, factors, np.zeros(len(indices), dtype=bool)
    return (
        np.concatenate([indices, np.array(extra_i, dtype=np.int32)]),
        np.concatenate([factors, np.array(extra_f, dtype=np.float32)]),
        np.concatenate(
            [
                np.zeros(len(indices), dtype=bool),
                np.ones(len(extra_i), dtype=bool),
            ]
        ),
    )


def gather_stroke_vertices(cache, settings, region, rv3d, mouse, world_hit, view_dir):
    radius = max(float(settings.radius), 1e-6)
    if settings.projection == 'SCREEN':
        px_radius = overlay.world_radius_to_px(region, rv3d, world_hit, radius)
        if world_hit is not None:
            candidates = [idx for _co, idx, _d in cache.kdtree.find_range(world_hit, radius * 4.0)]
        else:
            candidates = range(cache.nverts)
        picked = []
        distances = []
        for vi in candidates:
            if not cache.paint_mask[vi]:
                continue
            p2 = location_3d_to_region_2d(region, rv3d, cache.world_co[vi])
            if p2 is None:
                continue
            dist_px = (p2 - Vector(mouse)).length
            if dist_px <= px_radius:
                picked.append(vi)
                distances.append(dist_px / max(px_radius, 1e-6) * radius)
        indices = np.array(picked, dtype=np.int32)
        distances = np.array(distances, dtype=np.float32)
    else:
        if world_hit is None:
            return (
                np.zeros(0, dtype=np.int32),
                np.zeros(0, dtype=np.float32),
                np.zeros(0, dtype=bool),
            )
        hits = cache.kdtree.find_range(world_hit, radius)
        if not hits:
            return (
                np.zeros(0, dtype=np.int32),
                np.zeros(0, dtype=np.float32),
                np.zeros(0, dtype=bool),
            )
        indices = np.array([idx for _co, idx, _d in hits], dtype=np.int32)
        keep = cache.paint_mask[indices]
        indices = indices[keep]
        # KDTree candidates come from a position snapshot; the live
        # surface can be further along (weight writes re-pose the
        # armature between BVH/KDTree rebuilds). Recompute distances
        # against the current snapshot and re-filter, so falloff never
        # runs on stale distances — vertices that moved out of the
        # radius are dropped instead of silently getting factor ~0.
        hit_arr = np.asarray(world_hit, dtype=np.float32)
        delta = cache.world_co[indices] - hit_arr
        distances = np.linalg.norm(delta, axis=1).astype(np.float32)
        in_radius = distances <= radius
        indices = indices[in_radius]
        distances = distances[in_radius]

    if settings.front_faces_only and settings.projection != 'SCREEN':
        indices = _front_facing(cache, indices, view_dir)
        # Recompute distances for the filtered set.
        if world_hit is not None and indices.size:
            delta = cache.world_co[indices] - np.array(world_hit, dtype=np.float32)
            distances = np.linalg.norm(delta, axis=1).astype(np.float32)
        else:
            distances = np.zeros(indices.size, dtype=np.float32)

    if indices.size == 0:
        return indices, np.zeros(0, dtype=np.float32), np.zeros(0, dtype=bool)

    factors = apply_falloff(distances, radius, settings.falloff)
    if settings.use_x_mirror:
        indices, factors, mirror_mask = _mirror_indices(cache, indices, factors)
    else:
        mirror_mask = np.zeros(len(indices), dtype=bool)
    if (
        getattr(settings, "skip_border_edges", False)
        and settings.mode in {'SMOOTH', 'SHARPEN'}
        and getattr(cache, "border_verts", None) is not None
    ):
        # Skip Border Edges: open-boundary vertices keep their weights,
        # so smoothing can never pull a split seam out of alignment.
        keep = ~cache.border_verts[indices]
        if not np.all(keep):
            indices = indices[keep]
            factors = factors[keep]
            mirror_mask = mirror_mask[keep]
    return indices, factors, mirror_mask


class SKIN_OT_smooth_paint_stop(Operator):
    bl_idname = "skin_tools.smooth_paint_stop"
    bl_label = "Stop Smooth Brush"
    bl_description = "Exit DV Skin and restore Blender's default brush and overlay"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from ..core.session import shutdown_tool

        shutdown_tool(context, restore_tool=True)
        return {'FINISHED'}


# Drift (world units) at which the geometry cache is considered stale.
# Small enough to catch weight-driven re-posing before stamps visibly
# mis-gather; large enough that float noise / no-op depsgraph updates
# never trigger pointless rebuilds.
_STALE_DRIFT = 1e-4

# Shift+F strength adjust: full strength at this many screen pixels
# from the anchor, like the fixed drag range of Blender's native
# strength resize.
_ADJUST_STRENGTH_PX = 200.0


class SKIN_OT_smooth_paint(Operator):
    bl_idname = "skin_tools.smooth_paint"
    bl_label = "Smooth Skin Brush"
    bl_description = (
        "Paint to smooth all bone influences at once. "
        "Not the same as Blender's Blur brush, which only edits the active group"
    )
    bl_options = {'REGISTER', 'BLOCKING'}

    idle_start: BoolProperty(
        name="Idle Start",
        description="Start in hover mode without painting (used by the sidebar button)",
        default=True,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'WEIGHT_PAINT'
            and bool(obj.vertex_groups)
        )

    def _rebuild_cache(self, context, obj, why):
        try:
            self._cache = build_mesh_cache(context, obj)
            self._cache.weights = read_weights(obj, self._cache.group_indices)
            if GEOM_DEBUG:
                print(f"[DV Skin] cache rebuilt ({why})")
        except RuntimeError as exc:
            print(f"[DV Skin] cache rebuild failed: {exc}")

    def _ensure_fresh_geometry(self, context, obj, settings, force=False):
        """Detect and repair a stale geometry cache automatically.

        This is the automatic version of the disable/re-enable fix. The
        cache snapshots the evaluated surface when the tool starts; any
        weight write that re-poses the armature, any undo, any pose or
        transform tweak then moves the surface the viewport shows, while
        the brush keeps raycasting and gathering against the old
        snapshot — until only a disable/re-enable cycle restored
        correctness. Here every depsgraph update schedules a drift
        check, and real drift repairs the cache in place without losing
        stroke state:

        - tiny drift: refresh world arrays, normals, matrix and paint
          mask (C-speed fetches, no spatial structures);
        - drift past the perceptibility threshold (or stroke start /
          idle): also rebuild BVH + KDTree;
        - vertex-count change: full cache rebuild.
        """
        cache = self._cache
        if cache is None:
            return
        try:
            epoch = geom_epoch()
            if not force and epoch == getattr(cache, "_geom_epoch", -1):
                return
            drift = cache.position_drift(context, obj)
        except Exception as exc:
            if GEOM_DEBUG:
                print(f"[DV Skin] drift check failed: {exc}")
            return
        cache._geom_epoch = epoch
        if drift == float("inf"):
            self._rebuild_cache(context, obj, "topology changed")
            return
        if drift <= _STALE_DRIFT:
            return
        try:
            mid = max(
                float(cache.avg_edge) * 0.08, float(settings.radius) * 0.1
            )
            cache.refresh_geometry(
                context, obj, rebuild_spatial=(force or drift > mid)
            )
            if GEOM_DEBUG:
                print(f"[DV Skin] geometry refreshed: drift={drift:.6f} "
                      f"spatial={force or drift > mid}")
        except RuntimeError:
            self._rebuild_cache(context, obj, "refresh failed")
        except Exception as exc:
            if GEOM_DEBUG:
                print(f"[DV Skin] geometry refresh failed: {exc}")

    def invoke(self, context, event):
        obj = context.active_object
        settings = _settings_from(context)
        if settings.paint_active:
            # Modal is already running.  Pass the event through so the
            # modal handler can process it (e.g. start a new stroke on LMB)
            # instead of cancelling and letting the default brush consume it.
            return {'PASS_THROUGH'}
        # A previous session stashed Show All Influences / Wireframe when
        # it shut down; bring the user's display state back.
        restore_display_state(context)
        ensure_radius(settings, obj)
        try:
            self._cache = build_mesh_cache(context, obj)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self._cache.weights = read_weights(obj, self._cache.group_indices)
        # Watch depsgraph updates so the geometry cache can detect drift
        # (posed-armature re-evaluation, undo, transforms) and repair
        # itself instead of staying stale until a manual tool restart.
        register_geom_watch()
        self._obj_name = obj.name
        self._painting = False
        self._last_stamp = None
        self._stroke_start = None
        self._stroke_dirty = []
        self._stroke_add_max = None
        self._adjust = None
        self._adjust_value = 0.0
        self._adjust_ppu = None
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._hit = None
        self._area = context.area
        self._timer = context.window_manager.event_timer_add(0.05, window=context.window)
        self._handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw, (context,), 'WINDOW', 'POST_PIXEL'
        )
        settings.paint_active = True
        from ..core.weight_undo import push_matrix

        push_matrix(obj, self._cache.group_indices, self._cache.weights, "activate")
        # Take over the Weight Paint LMB keymap so the default Draw/Add brush
        # cannot fire on the first click.
        if self.idle_start:
            try:
                bpy.ops.wm.tool_set_by_id(name="skin_tools.smooth_brush_tool")
            except Exception:
                pass
        context.window.cursor_modal_set('PAINT_CROSS')
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "DV Skin  |  LMB paint  |  F resize  |  Shift+F intensity  |  "
            "Wheel zoom  |  Esc/RMB exit"
        )
        if not self.idle_start and event.type == 'LEFTMOUSE':
            self._begin_stroke(context, event)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        obj = context.active_object
        if (
            obj is None
            or obj.name != self._obj_name
            or obj.mode != 'WEIGHT_PAINT'
        ):
            self._cleanup(context)
            return {'CANCELLED'}

        settings = _settings_from(context)
        if not settings.paint_active:
            self._cleanup(context)
            return {'FINISHED'}

        # Repair a drifted geometry cache before anything raycasts or
        # gathers against it (cheap epoch fast-path when nothing changed).
        self._ensure_fresh_geometry(context, obj, settings)

        if event.type == 'ESC' and event.value == 'PRESS':
            if self._adjust:
                self._handle_adjust(context, event, settings)
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}
            if self._painting:
                self._end_stroke(context)
                return {'RUNNING_MODAL'}
            self._cleanup(context)
            return {'FINISHED'}

        if not self._adjust and _event_over_ui(context, event):
            if self._painting:
                self._end_stroke(context)
            try:
                context.window.cursor_modal_restore()
            except Exception:
                pass
            return {'PASS_THROUGH'}

        try:
            context.window.cursor_modal_set('PAINT_CROSS')
        except Exception:
            pass

        region, rv3d, _area = _view_region(context, event)
        if region is not None:
            self._mouse = (
                event.mouse_x - region.x,
                event.mouse_y - region.y,
            )

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if self._adjust:
                self._handle_adjust(context, event, settings)
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}
            if self._painting:
                self._end_stroke(context)
                return {'RUNNING_MODAL'}
            self._cleanup(context)
            return {'FINISHED'}
        if event.type == 'TAB':
            return {'PASS_THROUGH'}
        if event.type in _NAV_TYPES or (event.type.startswith('NUMPAD_') and not event.ascii):
            return {'PASS_THROUGH'}
        if event.alt and event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}:
            return {'PASS_THROUGH'}
        if event.ctrl and event.shift and event.type == 'LEFTMOUSE':
            return {'PASS_THROUGH'}
        if event.type == 'Z' and (event.ctrl or event.oskey) and event.value == 'PRESS':
            if self._painting:
                self._revert_stroke(context)
                return {'RUNNING_MODAL'}
            from ..core.weight_undo import redo as wu_redo, undo as wu_undo

            if event.shift:
                wu_redo(context)
            else:
                wu_undo(context)
            obj = context.active_object
            if obj is not None:
                self._cache.weights = read_weights(obj, self._cache.group_indices)
            return {'RUNNING_MODAL'}

        if self._handle_adjust(context, event, settings):
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFT_BRACKET' and event.value == 'PRESS':
            settings.radius = max(0.0001, settings.radius / 1.15)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}
        if event.type == 'RIGHT_BRACKET' and event.value == 'PRESS':
            settings.radius *= 1.15
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and not event.alt and not (event.ctrl and event.shift):
            # Consume every LMB value (PRESS/RELEASE/CLICK/CLICK_DRAG). Passing
            # CLICK through lets Blender's default Mix/Add brush run â€” that is
            # the "first click acts like Replace/Add" bug.
            if event.value in {'PRESS', 'CLICK_DRAG'}:
                if not self._painting:
                    self._begin_stroke(context, event)
                elif event.value == 'CLICK_DRAG':
                    self._maybe_stamp(context, event, settings, region, rv3d)
            elif event.value in {'RELEASE', 'CLICK', 'DOUBLE_CLICK'}:
                if event.value == 'RELEASE':
                    self._end_stroke(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if region is not None and rv3d is not None:
                self._hit, _origin = _raycast(self._cache, region, rv3d, self._mouse)
            if self._painting:
                self._maybe_stamp(context, event, settings, region, rv3d)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER' and self._painting and settings.airbrush:
            self._stamp(context, event, settings, region, rv3d, force=True)
            return {'RUNNING_MODAL'}

        # Let the N-panel and the rest of Blender receive unused keys.
        return {'PASS_THROUGH'}

    def _handle_adjust(self, context, event, settings):
        """Blender-native F adjust.

        Press F: the ring anchors where the cursor was. Moving the mouse
        sets the value from the cursor's distance to that point — radius
        in world units, converted from the screen distance at the
        anchor's depth, exactly like Blender's native resize. Left click
        sets the size, right click / Esc cancels, and the confirming
        click never paints. The OS cursor stays free (no warping).
        """
        if not self._adjust:
            if event.type == 'F' and event.value == 'PRESS' and not self._painting:
                self._adjust = 'INTENSITY' if event.shift else 'RADIUS'
                self._adjust_origin = tuple(self._mouse)
                if self._adjust == 'RADIUS':
                    self._adjust_value = max(float(settings.radius), 1e-6)
                else:
                    self._adjust_value = float(np.clip(settings.intensity, 0.0, 1.0))
                # Pixels per world unit at the anchor's depth, so the
                # dragged screen distance maps 1:1 onto the ring size
                # the brush will use after confirmation.
                region = context.region
                rv3d = getattr(context.space_data, "region_3d", None)
                hit = self._hit
                if hit is None and region is not None and rv3d is not None:
                    hit, _origin = _raycast(self._cache, region, rv3d, self._mouse)
                    self._hit = hit
                ppu = 0.0
                if hit is not None and region is not None and rv3d is not None:
                    ppu = float(overlay.world_radius_to_px(region, rv3d, hit, 1.0))
                if ppu <= 1e-6 and self._adjust == 'RADIUS':
                    # No surface under the cursor: scale from the default
                    # 48 px on-screen ring so relative resizing still works.
                    ppu = 48.0 / self._adjust_value
                self._adjust_ppu = ppu
                return True
            return False

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if self._adjust_origin is not None:
                # Horizontal control: right increases, left decreases,
                # starting from the value the key was pressed with.
                dx = self._mouse[0] - self._adjust_origin[0]
                if self._adjust == 'RADIUS':
                    ppu = self._adjust_ppu or 0.0
                    if ppu > 1e-6:
                        settings.radius = max(
                            0.0001, self._adjust_value + dx / ppu
                        )
                else:
                    settings.intensity = float(
                        np.clip(
                            self._adjust_value + dx / _ADJUST_STRENGTH_PX,
                            0.0, 1.0,
                        )
                    )
            return True

        if event.type == 'LEFTMOUSE':
            # Confirm on press; consume the release so it never paints.
            if event.value == 'PRESS':
                self._adjust = None
            return True

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._adjust = None
            return True

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            # Cancel: put the pre-adjust value back.
            if self._adjust == 'RADIUS':
                settings.radius = self._adjust_value
            else:
                settings.intensity = self._adjust_value
            self._adjust = None
            return True

        if event.type == 'F' and event.value == 'PRESS':
            # Re-press: restart the adjust anchored at the current
            # cursor (Shift switches to strength, like Blender's Shift+F).
            self._adjust = None
            return self._handle_adjust(context, event, settings)
        if event.type == 'F':
            # Consume F releases/repeats so nothing passes through while
            # adjusting. The adjust itself survives the key release:
            # press F, let go, move the mouse, click to set.
            return True

        return False

    def _begin_stroke(self, context, event):
        obj = context.active_object
        settings = _settings_from(context)
        # Stroke start is a natural checkpoint: catch up on any drift
        # (full spatial rebuild) before the first stamp raycasts.
        self._ensure_fresh_geometry(context, obj, settings, force=True)
        # Re-read so undo / other brushes stay in sync.
        self._cache.weights = read_weights(obj, self._cache.group_indices)
        self._cache.locked = np.array(
            [obj.vertex_groups[i].lock_weight for i in self._cache.group_indices],
            dtype=bool,
        )
        self._stroke_start = self._cache.weights.copy()
        self._stroke_dirty = []
        self._stroke_add_max = np.zeros(self._cache.nverts, dtype=np.float32)
        self._painting = True
        self._last_stamp = None
        settings = _settings_from(context)
        region, rv3d, _area = _view_region(context, event)
        self._stamp(context, event, settings, region, rv3d, force=True)

    def _end_stroke(self, context):
        if self._painting and self._stroke_start is not None and self._stroke_dirty:
            from ..core.weight_undo import push_matrix

            obj = context.active_object
            if obj is not None:
                dirty = np.unique(np.concatenate(self._stroke_dirty))
                push_matrix(
                    obj,
                    self._cache.group_indices,
                    self._stroke_start,
                    "stroke",
                    dirty=dirty,
                )
        self._painting = False
        self._last_stamp = None
        self._stroke_start = None
        self._stroke_dirty = []
        self._stroke_add_max = None

    def _revert_stroke(self, context):
        obj = context.active_object
        if obj is not None and self._stroke_start is not None and self._stroke_dirty:
            from ..core.weights import refresh_overlay, write_weights
            import numpy as np
            settings = _settings_from(context)
            dirty = np.concatenate(self._stroke_dirty)
            locked = self._cache.effective_locked(settings.target)
            write_weights(
                obj,
                self._cache.group_indices,
                self._stroke_start,
                dirty,
                previous=self._cache.weights,
                prune=settings.prune,
                locked=locked,
            )
            self._cache.weights = self._stroke_start.copy()
            refresh_overlay(context, obj)
        self._painting = False
        self._last_stamp = None
        self._stroke_start = None
        self._stroke_dirty = []
        self._stroke_add_max = None

    def _maybe_stamp(self, context, event, settings, region, rv3d):
        if self._hit is None and settings.projection != 'SCREEN':
            return
        if self._last_stamp is not None and settings.spacing > 0.0:
            if self._hit is not None:
                travel = (self._hit - self._last_stamp).length
            else:
                travel = 0.0
            if travel < settings.spacing * settings.radius:
                return
        self._stamp(context, event, settings, region, rv3d, force=False)

    def _stamp(self, context, event, settings, region, rv3d, force=False):
        if region is None or rv3d is None:
            return
        world_hit, origin = _raycast(self._cache, region, rv3d, self._mouse)
        self._hit = world_hit
        view_dir = region_2d_to_vector_3d(region, rv3d, self._mouse)
        indices, factors, mirror_mask = gather_stroke_vertices(
            self._cache, settings, region, rv3d, self._mouse, world_hit, view_dir
        )
        if indices.size == 0:
            return
        intensity = settings.intensity
        if settings.use_pressure and getattr(event, "is_tablet", False):
            intensity *= max(float(event.pressure), 0.0)
        mode = settings.mode
        if event.ctrl and mode in {'SMOOTH', 'SHARPEN'}:
            mode = 'SHARPEN' if mode == 'SMOOTH' else 'SMOOTH'
        if mode in {'SMOOTH', 'SHARPEN', 'STITCH'}:
            stamp_factors = factors * intensity
        else:
            stamp_factors = factors
        if (
            mode == 'ADD'
            and not settings.airbrush
            and self._stroke_add_max is not None
        ):
            contrib = intensity * factors
            prev = self._stroke_add_max[indices]
            new_max = np.maximum(prev, contrib)
            extra = new_max - prev
            grew = extra > 1e-6
            if not np.any(grew):
                if world_hit is not None:
                    self._last_stamp = world_hit.copy()
                return
            self._stroke_add_max[indices] = new_max
            indices = indices[grew]
            stamp_factors = extra[grew]
            mirror_mask = np.asarray(mirror_mask, dtype=bool)[grew]
            intensity = 1.0
        obj = context.active_object
        apply_smooth_to_indices(
            context,
            obj,
            self._cache,
            settings,
            indices,
            stamp_factors,
            mode=mode,
            intensity=intensity,
            mirror_mask=mirror_mask,
        )
        if getattr(self, "_stroke_dirty", None) is not None:
            dirty = np.asarray(indices, dtype=np.int32)
            # Sync Border Weights writes seam partners outside the
            # gathered set; undo must revert them together.
            sync_set = _border_sync_set(self._cache, settings, dirty, mode)
            if sync_set is not None:
                dirty = np.union1d(dirty, sync_set)
            self._stroke_dirty.append(dirty)
        if world_hit is not None:
            self._last_stamp = world_hit.copy()
        elif force:
            self._last_stamp = Vector((event.mouse_x, event.mouse_y, 0.0))

    def _draw(self, context):
        settings = _settings_from(context)
        if settings is None:
            return
        region = context.region
        rv3d = getattr(context.space_data, "region_3d", None)
        if region is None or rv3d is None:
            return
        radius_px = overlay.world_radius_to_px(region, rv3d, self._hit, settings.radius)
        if self._adjust == 'RADIUS':
            color = overlay.ADJUST_COLOR
        else:
            color = overlay.mode_color(settings.mode)
        # While adjusting (F / Shift+F) the ring stays anchored where the
        # key was pressed; otherwise it follows the mouse.
        pos = self._adjust_origin if self._adjust else self._mouse
        overlay.draw_brush_cursor(pos, radius_px, color, settings.intensity)
        from ..core.paint import mode_label
        mode = mode_label(settings.mode)
        if self._adjust == 'RADIUS':
            hud = [
                f"Radius  {settings.radius:.4f}",
                "LMB set   RMB/Esc cancel",
            ]
        elif self._adjust == 'INTENSITY':
            hud = [
                f"Intensity  {settings.intensity:.3f}",
                "LMB set   RMB/Esc cancel",
            ]
        else:
            hud = [
                f"DV Skin  {mode}   I {settings.intensity:.2f}   R {settings.radius:.3f}   "
                f"x{settings.iterations}",
                "LMB paint   F radius   Ctrl+Z undo   Esc/RMB exit",
            ]
        overlay.draw_hud(region, hud)

    def _tag_redraw(self, context):
        if context.area:
            context.area.tag_redraw()
        elif self._area:
            self._area.tag_redraw()

    def _cleanup(self, context):
        if getattr(self, "_painting", False):
            try:
                self._end_stroke(context)
            except Exception:
                pass
        if getattr(self, "_timer", None) is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if getattr(self, "_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, 'WINDOW')
            self._handler = None
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        if context.workspace:
            context.workspace.status_text_set(None)
        unregister_geom_watch()
        from ..core.session import shutdown_tool

        shutdown_tool(context, restore_tool=True)
        self._tag_redraw(context)

    def cancel(self, context):
        self._cleanup(context)
