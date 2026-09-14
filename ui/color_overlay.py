"""Maya-style multi-color display: each bone a hue, blended by live weights."""

from __future__ import annotations

import colorsys

import numpy as np
import bpy
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..core.influence import active_local_index
from ..core.mesh_data import deform_group_indices
from ..core.weights import read_weights
from ..properties import _settings_from

_handler = None
_mode_handler = None
_pick = {"active": False, "highlight": None, "group": None}
_pick_surface = {"key": None, "alpha": None, "tris": None}
_cache = {
    "key": None,
    "colors": None,
    "tris": None,
    "nverts": 0,
    "count": 0,
}


def set_pick_state(active=False, highlight=None, group=None):
    """Shared state for the hold-S influence picker.

    While active, ``highlight`` (a bone name) is drawn enlarged, red, and
    x-ray so the user can see which influence would be picked, and
    ``group`` (the active influence) renders its bones green and its
    vertices white on the mesh.
    """
    _pick["active"] = bool(active)
    _pick["highlight"] = highlight
    _pick["group"] = group
    if not _pick["active"]:
        _pick_surface["key"] = None
        _pick_surface["alpha"] = None
        _pick_surface["tris"] = None


# Neighbours on the bone list get ~137.5° hue steps, not adjacent rainbow bands.
_GOLDEN = 0.618033988749895


def influence_hues(count, seed=1):
    n = max(int(count), 1)
    rng = np.random.default_rng(int(seed) % (2**32 - 1))
    start = float(rng.random())
    return np.mod(start + np.arange(n, dtype=np.float64) * _GOLDEN, 1.0)


def influence_color(index, count=8, seed=1):
    hues = influence_hues(count, seed)
    h = float(hues[int(index) % len(hues)])
    return np.array(colorsys.hsv_to_rgb(h, 1.0, 1.0), dtype=np.float32)


def influence_colors(count, seed=1, active_index=-1):
    hues = influence_hues(count, seed)
    pal = np.array(
        [colorsys.hsv_to_rgb(float(h), 1.0, 1.0) for h in hues],
        dtype=np.float32,
    )
    if 0 <= int(active_index) < pal.shape[0]:
        pal[int(active_index)] = (1.0, 1.0, 1.0)
    return pal


def reroll_color_seed(settings):
    """New palette. Does not touch skin weights."""
    settings.color_seed = int(np.random.default_rng().integers(1, 2**31 - 1))
    settings.display_dirty = True
    return settings.color_seed


def _object_key(obj):
    return (obj.name, obj.data.name if obj.data else "", len(obj.data.vertices) if obj.data else 0)


def _loop_tris(mesh):
    n = len(mesh.loop_triangles)
    if n == 0 and len(mesh.polygons):
        if hasattr(mesh, "calc_loop_triangles"):
            mesh.calc_loop_triangles()
        n = len(mesh.loop_triangles)
    if n == 0:
        return np.zeros((0, 3), dtype=np.int32)
    data = np.empty(n * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", data)
    return data.reshape(n, 3)


def _evaluated_world_coords_and_normals(context, obj):
    n = len(obj.data.vertices)
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    try:
        src = eval_mesh if len(eval_mesh.vertices) == n else obj.data
        matrix = eval_obj.matrix_world if src is eval_mesh else obj.matrix_world
        flat = np.empty(n * 3, dtype=np.float32)
        nrm = np.empty(n * 3, dtype=np.float32)
        src.vertices.foreach_get("co", flat)
        src.vertices.foreach_get("normal", nrm)
        coords = flat.reshape(n, 3).astype(np.float64)
        normals = nrm.reshape(n, 3).astype(np.float64)
        m = np.array(matrix, dtype=np.float64)
        rot = m[:3, :3]
        world = (coords @ rot.T + m[:3, 3]).astype(np.float32)
        world_no = (normals @ rot.T).astype(np.float32)
        lengths = np.linalg.norm(world_no, axis=1, keepdims=True)
        np.divide(world_no, lengths, out=world_no, where=lengths > 1e-12)
        return world, world_no
    finally:
        eval_obj.to_mesh_clear()


def _nudge_overlay_coords(coords, normals, rv3d):
    """Pull the overlay off the original surface so they do not z-fight."""
    view_dist = 1.0
    if rv3d is not None:
        view_dist = max(abs(float(rv3d.view_distance)), 0.01)
        view_inv = rv3d.view_matrix.inverted()
        # Camera looks along local -Z; pull geometry toward the camera.
        toward_camera = np.array(view_inv.col[2].xyz, dtype=np.float32)
        length = float(np.linalg.norm(toward_camera))
        if length > 1e-12:
            toward_camera /= length
            coords = coords + toward_camera * (view_dist * 2.5e-4)
    if normals is not None:
        coords = coords + normals * max(view_dist * 8e-5, 2e-5)
    return coords


def set_native_heatmap_hidden(context, hide):
    """Hide original mesh + default heatmap while Show All Influences is on."""
    settings = _settings_from(context)
    screen = getattr(context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            overlay = area.spaces.active.overlay
            if hide:
                if settings is not None and not settings.wp_opacity_stashed:
                    settings.saved_wp_opacity = overlay.weight_paint_mode_opacity
                    settings.wp_opacity_stashed = True
                overlay.weight_paint_mode_opacity = 0.0
            else:
                restore = 1.0
                if settings is not None and settings.wp_opacity_stashed:
                    restore = settings.saved_wp_opacity
                overlay.weight_paint_mode_opacity = restore
    if settings is not None and not hide:
        settings.wp_opacity_stashed = False

    obj = getattr(context, "active_object", None)
    if hide:
        if obj is not None and obj.type == 'MESH':
            if settings is not None and not settings.mesh_hide_stashed:
                settings.saved_hide = bool(obj.hide_get())
                settings.saved_hide_obj = obj.name
                settings.mesh_hide_stashed = True
            try:
                obj.hide_set(True)
            except Exception:
                pass
        return
    if settings is None or not settings.mesh_hide_stashed:
        return
    restore_obj = bpy.data.objects.get(settings.saved_hide_obj) if settings.saved_hide_obj else obj
    if restore_obj is not None:
        try:
            restore_obj.hide_set(bool(settings.saved_hide))
        except Exception:
            pass
    settings.mesh_hide_stashed = False
    settings.saved_hide_obj = ""


def patch_overlay_colors(obj, dirty, rows, settings):
    """Update overlay colors for a vertex subset. Returns False if a full rebuild is needed."""
    colors = _cache.get("colors")
    if colors is None or not settings.show_all_influences:
        return False
    if obj is None or obj.data is None:
        return False
    if len(colors) != len(obj.data.vertices):
        return False
    if rows is None or rows.size == 0:
        return False
    dirty = np.asarray(dirty, dtype=np.int32)
    if dirty.size != rows.shape[0]:
        return False
    groups = deform_group_indices(obj)
    active = active_local_index(obj, groups) if groups else -1
    palette = influence_colors(rows.shape[1], settings.color_seed, active)
    rgb = rows @ palette
    colors[dirty, :3] = rgb
    colors[dirty, 3] = float(settings.overlay_opacity)
    return True


def colors_from_weights(weights, seed=1, active_index=-1):
    """Vertex RGB = sum(weight_i * hue_i). Active influence is white."""
    ninf = weights.shape[1]
    if ninf == 0:
        return np.zeros((weights.shape[0], 4), dtype=np.float32)
    palette = influence_colors(ninf, seed, active_index)
    rgb = weights @ palette
    return rgb.astype(np.float32)


def _rebuild_colors(obj, settings):
    groups = deform_group_indices(obj)
    if not groups:
        return None, None, 0
    weights = read_weights(obj, groups)
    active = active_local_index(obj, groups)
    rgb = colors_from_weights(weights, settings.color_seed, active)
    alpha = np.full((rgb.shape[0], 1), float(settings.overlay_opacity), dtype=np.float32)
    colors = np.concatenate([rgb, alpha], axis=1)
    tris = _loop_tris(obj.data)
    return colors, tris, len(groups)


def _pick_group_index(obj, bone_name):
    """Vertex-group index for a bone name, or None."""
    try:
        return obj.vertex_groups[bone_name].index
    except Exception:
        return None


def _pick_surface_data(obj, group_index):
    """Cached (per-vertex weight, loop triangles) for one influence."""
    key = (_object_key(obj), int(group_index))
    if _pick_surface["key"] == key and _pick_surface["alpha"] is not None:
        return _pick_surface["alpha"], _pick_surface["tris"]
    weights = read_weights(obj, [int(group_index)])[:, 0]
    tris = _loop_tris(obj.data)
    _pick_surface["key"] = key
    _pick_surface["alpha"] = weights
    _pick_surface["tris"] = tris
    return weights, tris


def _wire_edges(obj):
    """Cached (edges, 2) vertex-index array for the wireframe overlay."""
    mesh = obj.data
    key = (_object_key(obj), len(mesh.vertices), len(mesh.edges))
    if _wire["key"] == key and _wire["edges"] is not None:
        return _wire["edges"]
    n = len(mesh.edges)
    if not n:
        edges = np.zeros((0, 2), np.int32)
    else:
        flat = np.empty(n * 2, np.int32)
        mesh.edges.foreach_get("vertices", flat)
        edges = flat.reshape(n, 2)
    _wire["key"] = key
    _wire["edges"] = edges
    return edges


_wire = {"key": None, "edges": None}


def _draw_pick_weight_surface(context, obj, settings):
    """White weight preview while picking.

    Shows the hovered bone's weights, or the active influence's weights
    when nothing is hovered. Alpha equals the vertex weight, so fully
    weighted areas glow solid white and untouched areas stay invisible.
    """
    # Hovered bone wins; otherwise preview the active influence itself.
    bone_name = _pick.get("highlight") or _pick.get("group")
    if not bone_name:
        return
    try:
        gi = _pick_group_index(obj, bone_name)
        if gi is None:
            return
        alpha, tris = _pick_surface_data(obj, gi)
        if alpha is None or not alpha.size or tris is None or not tris.size:
            return
        opacity = float(getattr(settings, "overlay_opacity", 1.0))
        colors = np.empty((alpha.shape[0], 4), dtype=np.float32)
        colors[:, 0] = 1.0
        colors[:, 1] = 1.0
        colors[:, 2] = 1.0
        colors[:, 3] = alpha * opacity
        coords, normals = _evaluated_world_coords_and_normals(context, obj)
        rv3d = getattr(context.space_data, "region_3d", None) if context.space_data else None
        coords = _nudge_overlay_coords(coords, normals, rv3d)
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set('ALPHA')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords, "color": colors}, indices=tris)
        batch.draw(shader)
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('NONE')
    except Exception:
        pass


def _bone_visible(arm_data, bone):
    """Respect per-bone hide and bone-collection visibility."""
    if bone.hide:
        return False
    try:
        refs = bone.collections
    except Exception:
        return True
    if not len(refs):
        return True
    for ref in refs:
        try:
            bcoll = arm_data.collections.get(ref.name)
            if bcoll is None or bcoll.is_visible:
                return True
        except Exception:
            return True
    return False


def bound_group_names(obj):
    """Names of vertex groups that deform this mesh (the bound bones)."""
    try:
        return {obj.vertex_groups[gi].name for gi in deform_group_indices(obj)}
    except Exception:
        return None


def _bone_world_points(pb, mw, rot3, radius_scale=1.0):
    """Head/tail/ring points of a bone octahedron in world space."""
    head_local = pb.matrix.translation
    axis_local = pb.matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
    if axis_local.length < 1e-9:
        axis_local = Vector((0.0, 1.0, 0.0))
    axis = (rot3 @ axis_local).normalized()
    length = max(float(pb.length), 1e-6)
    head = mw @ head_local
    tail = head + axis * length
    ref = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    u = axis.cross(ref).normalized()
    v = axis.cross(u).normalized()
    ring_c = head + axis * (length * 0.1)
    r = length * 0.1 * float(radius_scale)
    ring = (ring_c + u * r, ring_c + v * r, ring_c - u * r, ring_c - v * r)
    return head, tail, ring


def _octa_tris(head, tail, ring):
    p1, p2, p3, p4 = ring
    return (
        (head, p1, p2), (head, p2, p3), (head, p3, p4), (head, p4, p1),
        (tail, p2, p1), (tail, p3, p2), (tail, p4, p3), (tail, p1, p4),
    )


_BONE_COLOR = (0.52, 0.56, 0.62)
_BONE_COLOR_SELECTED = (0.95, 0.50, 0.20)
_BONE_COLOR_ACTIVE = (1.00, 0.62, 0.15)
_BONE_COLOR_PICK = (0.95, 0.18, 0.18)
_BONE_COLOR_INSPECT = (0.15, 0.90, 0.40)


def _bone_color(pb, active_bone):
    if active_bone is not None and pb.bone == active_bone:
        return _BONE_COLOR_ACTIVE
    if getattr(pb, "select", False):
        return _BONE_COLOR_SELECTED
    return _BONE_COLOR


def _render_bone_base(picking, highlight, pb, active_bone, inspect_names=None):
    """Base color for a bone while drawing.

    While picking, the hovered (highlighted) bone renders red and bones
    of the inspected influence (``inspect_names``) render green; all
    other bones keep their normal colors.
    """
    if picking and highlight is not None and pb.name == highlight:
        return _BONE_COLOR_PICK
    if inspect_names and pb.name in inspect_names:
        return _BONE_COLOR_INSPECT
    return _bone_color(pb, active_bone)


def _bones_in_front(settings, arm_data):
    """X-ray bones when the panel toggle is on, or the armature's own In Front."""
    if settings is not None and bool(getattr(settings, "bone_xray", False)):
        return True
    return bool(getattr(arm_data, "show_in_front", False))


def _draw_pick_hud(region, rv3d, arm_obj, bone_name, mw):
    """Show the candidate bone's name and a hint beside it while holding S."""
    import blf

    from bpy_extras.view3d_utils import location_3d_to_region_2d

    try:
        pb = arm_obj.pose.bones.get(bone_name)
        if pb is None or region is None or rv3d is None:
            return
        p = location_3d_to_region_2d(region, rv3d, mw @ pb.matrix.translation)
        if p is None:
            return
        font = 0
        blf.size(font, 13)
        lines = (str(bone_name), "release S or click LMB to select this influence")
        for i, line in enumerate(lines):
            py = int(p.y) - i * 15
            blf.color(font, 0.0, 0.0, 0.0, 0.85)
            blf.position(font, int(p.x) + 8 + 1, py - 1, 0)
            blf.draw(font, line)
            blf.color(font, 1.0, 1.0, 1.0, 1.0)
            blf.position(font, int(p.x) + 8, py, 0)
            blf.draw(font, line)
    except Exception:
        pass


def draw_bound_armature_bones(context, obj, settings=None):
    """Draw the skin's armature over the influence colors.

    While the picker is active, bones are always drawn x-ray (on top),
    scaled up slightly, and the candidate bone gets a bright halo + white
    body so it is unmistakable.  Outside picking, X-ray comes from the
    panel toggle or the armature's own In Front display.
    """
    from ..core.mesh_data import object_armature

    picking = bool(_pick.get("active"))
    xray_all = bool(getattr(settings, "bone_xray_all", False)) if settings is not None else False
    try:
        arm_obj = object_armature(obj)
        if arm_obj is None or arm_obj.type != 'ARMATURE':
            return
        # While picking (or with X-Ray All Bones on), bones are drawn even
        # when the armature object is hidden, so hold-S works with only
        # the mesh selected.
        if not picking and not xray_all and (arm_obj.hide_get() or arm_obj.hide_viewport):
            return
    except Exception:
        return

    arm_data = arm_obj.data
    active_bone = arm_data.bones.active
    mw = arm_obj.matrix_world
    rot3 = mw.to_3x3()

    # Only show bones actually bound to this mesh.
    bound = bound_group_names(obj)

    highlight = _pick.get("highlight") if picking else None
    if picking:
        group_name = _pick.get("group")
    else:
        # Outside picking, the current paint influence still renders green.
        try:
            av = obj.vertex_groups.active
            group_name = av.name if av is not None else None
        except Exception:
            group_name = None
    inspect_names = {group_name} if group_name else None

    rv3d = getattr(context.space_data, "region_3d", None) if context.space_data else None
    region = getattr(context, "region", None)
    if rv3d is not None:
        light = rv3d.view_matrix.inverted().col[2].xyz.normalized()
    else:
        light = Vector((0.3, 0.2, 1.0))

    positions = []
    colors = []
    hl_positions = []
    radius_scale = 1.35 if picking else 1.0

    for pb in arm_obj.pose.bones:
        if bound is not None and pb.name not in bound:
            continue
        # While picking or with X-Ray All Bones on, every bound bone is
        # shown even if its bone collection is invisible or the bone
        # itself is hidden; otherwise visibility is respected.
        if not (picking or xray_all) and not _bone_visible(arm_data, pb.bone):
            continue
        is_hl = bool(picking and highlight is not None and pb.name == highlight)
        base = _render_bone_base(picking, highlight, pb, active_bone, inspect_names)
        head, tail, ring = _bone_world_points(pb, mw, rot3, radius_scale)
        tris = _octa_tris(head, tail, ring)
        if is_hl:
            for a, b, c in tris:
                hl_positions.extend((a[:], b[:], c[:]))
        for a, b, c in tris:
            n = (b - a).cross(c - a)
            if n.length > 1e-12:
                n.normalize()
            s = 0.45 + 0.55 * abs(n.dot(light))
            col = (base[0] * s, base[1] * s, base[2] * s, 1.0)
            positions.extend((a[:], b[:], c[:]))
            colors.extend((col, col, col))

    if not positions:
        return

    try:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    except Exception:
        return

    in_front = True if (picking or xray_all) else _bones_in_front(settings, arm_data)
    gpu.state.depth_test_set('NONE' if in_front else 'LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')
    batch_for_shader(shader, 'TRIS', {"pos": positions, "color": colors}).draw(shader)

    # Bright red wire outline so the hovered bone pops even against red-ish
    # influence colors underneath.
    if hl_positions:
        try:
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            idx = []
            for t in range(0, len(hl_positions), 3):
                idx.extend(((t, t + 1), (t + 1, t + 2), (t + 2, t)))
            lbatch = batch_for_shader(line_shader, 'LINES', {"pos": hl_positions}, indices=idx)
            line_shader.uniform_float("color", (1.0, 0.15, 0.1, 1.0))
            gpu.state.line_width_set(2.5)
            lbatch.draw(line_shader)
        except Exception:
            pass
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')

    if picking and highlight is not None:
        _draw_pick_hud(region, rv3d, arm_obj, highlight, mw)


def draw():
    context = bpy.context
    settings = _settings_from(context)
    if settings is None:
        return
    picking = bool(_pick.get("active"))
    if (
        not settings.show_all_influences
        and not picking
        and not bool(getattr(settings, "bone_xray", False))
        and not bool(getattr(settings, "bone_xray_all", False))
    ):
        return
    obj = context.active_object
    if obj is None or obj.type != 'MESH' or not obj.vertex_groups:
        return
    if obj.mode not in {'WEIGHT_PAINT', 'POSE', 'OBJECT'}:
        return
    region = context.region
    if region is None or region.type != 'WINDOW':
        return

    # The colored influence surface. Skipped entirely while picking if
    # Show All Influences was not already on.
    if settings.show_all_influences:
        groups = deform_group_indices(obj)
        active = active_local_index(obj, groups) if groups else -1
        key = (_object_key(obj), int(settings.color_seed), int(active))
        if (
            _cache["key"] != key
            or _cache["colors"] is None
            or settings.display_dirty
        ):
            colors, tris, count = _rebuild_colors(obj, settings)
            _cache["key"] = key
            _cache["colors"] = colors
            _cache["tris"] = tris
            _cache["nverts"] = len(obj.data.vertices)
            _cache["count"] = count
            settings.display_dirty = False

        colors = _cache["colors"]
        tris = _cache["tris"]
        if colors is not None and tris is not None and tris.size:
            colors[:, 3] = float(settings.overlay_opacity)
            try:
                coords, normals = _evaluated_world_coords_and_normals(context, obj)
            except Exception:
                coords = None
            if coords is not None and len(coords) == len(colors):
                rv3d = getattr(context.space_data, "region_3d", None) if context.space_data else None
                coords = _nudge_overlay_coords(coords, normals, rv3d)
                try:
                    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
                except Exception:
                    shader = None
                if shader is not None:
                    gpu.state.depth_test_set('LESS_EQUAL')
                    gpu.state.depth_mask_set(True)
                    gpu.state.blend_set('NONE' if settings.overlay_opacity >= 0.999 else 'ALPHA')
                    gpu.state.face_culling_set('BACK')
                    batch = batch_for_shader(
                        shader,
                        'TRIS',
                        {"pos": coords, "color": colors},
                        indices=tris,
                    )
                    batch.draw(shader)
                    gpu.state.face_culling_set('NONE')

                    # Optional wireframe over the influence colors.
                    if bool(getattr(settings, "overlay_wireframe", False)):
                        edges = _wire_edges(obj)
                        if edges.size:
                            try:
                                line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                            except Exception:
                                line_shader = None
                            if line_shader is not None:
                                gpu.state.blend_set('ALPHA')
                                gpu.state.depth_test_set('LESS_EQUAL')
                                gpu.state.depth_mask_set(False)
                                gpu.state.line_width_set(1.0)
                                line_shader.uniform_float(
                                    "color", (0.05, 0.07, 0.08, 0.55)
                                )
                                lbatch = batch_for_shader(
                                    line_shader, 'LINES', {"pos": coords}, indices=edges
                                )
                                lbatch.draw(line_shader)
                                gpu.state.line_width_set(1.0)
                                gpu.state.blend_set(
                                    'NONE' if settings.overlay_opacity >= 0.999 else 'ALPHA'
                                )

    # White preview of the hovered bone's weights, or of the active
    # influence when nothing is hovered.
    if picking and (_pick.get("highlight") or _pick.get("group")):
        _draw_pick_weight_surface(context, obj, settings)

    # Bones are drawn even when the surface above could not be drawn,
    # and forced x-ray while picking.
    draw_bound_armature_bones(context, obj, settings)
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')


def mark_dirty(context=None):
    context = context or bpy.context
    settings = _settings_from(context)
    if settings is not None:
        settings.display_dirty = True
    _cache["colors"] = None
    _wire["key"] = None
    _wire["edges"] = None
    _pick_surface["key"] = None
    _pick_surface["alpha"] = None
    _pick_surface["tris"] = None
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _should_exit_show_all(context_mode, settings):
    """True when Show All Influences must auto-exit (Object Mode)."""
    return (
        context_mode == 'OBJECT'
        and settings is not None
        and bool(settings.show_all_influences)
    )


@persistent
def _auto_exit_show_all(scene=None, depsgraph=None):
    """Keep Show All Influences consistent across mode changes.

    Leaving weight/pose paint for Object Mode ends Show All Influences
    (the overlay would hide the mesh); re-entering Weight Paint with a
    stashed on-choice (the default) brings it back automatically.
    """
    import bpy as _bpy

    from ..properties import _settings_from

    ctx = _bpy.context
    settings = _settings_from(ctx)
    if settings is None:
        return

    mode = getattr(ctx, "mode", None)

    if _should_exit_show_all(mode, settings):
        def _exit():
            try:
                from ..properties import remember_display_state

                remember_display_state(settings)
                settings.display_state_stashed = True
                settings.show_all_influences = False
            except Exception:
                pass
            return None

        try:
            if _bpy.app.background:
                _exit()
            else:
                # Defer out of the depsgraph callback so the toggle's update
                # (which unhides the mesh) runs in a safe spot.
                _bpy.app.timers.register(_exit, first_interval=0.0)
        except Exception:
            _exit()
        return

    if mode == 'PAINT_WEIGHT' and bool(getattr(settings, "display_state_stashed", False)):
        # Re-entering Weight Paint (default: Show All Influences on
        # when the mesh has influences).
        def _enter():
            try:
                from ..properties import restore_display_state

                restore_display_state(ctx)
            except Exception:
                pass
            return None

        try:
            if _bpy.app.background:
                _enter()
            else:
                _bpy.app.timers.register(_enter, first_interval=0.0)
        except Exception:
            _enter()


_sync = {"obj": "", "vg": -1, "bone": ""}


@persistent
def _sync_load_post(_dummy=None):
    """Seed the sync cache from the just-loaded file.

    Without this the first depsgraph update after a load would look like
    an active-group change and rewrite the pose-bone selection.
    """
    ctx = bpy.context
    obj = getattr(ctx, "active_object", None)
    if obj is not None and obj.type == 'MESH' and obj.vertex_groups:
        _sync["obj"] = obj.name
        _sync["vg"] = obj.vertex_groups.active_index
    else:
        _sync["obj"] = ""
        _sync["vg"] = -1
    _sync["bone"] = ""
    _reset_show_all_after_load()


def _reset_show_all_after_load():
    """Show All Influences defaults ON after a file open when the mesh
    has influences. Empty meshes stay off so the overlay cannot hide them.

    The overlay's stashed hide/opacity references belong to the previous
    file, so the native display is restored first; then the default-on
    multi-color display is applied to the freshly loaded scene. In
    Object Mode the toggle cannot be on (the overlay would hide the
    mesh), so the on-choice is stashed there and restored automatically
    on entering Weight Paint. Deferred out of the load callback like
    the Object-Mode auto-exit; background mode applies directly.
    """
    import bpy as _bpy

    from ..core.mesh_data import mesh_has_influences
    from ..properties import _settings_from

    ctx = _bpy.context
    settings = _settings_from(ctx)
    if settings is None:
        return

    def _reset():
        try:
            set_native_heatmap_hidden(ctx, False)
        except Exception:
            pass
        try:
            settings.display_state_stashed = False
        except Exception:
            pass
        obj = getattr(ctx, "active_object", None)
        has_inf = mesh_has_influences(obj)
        can_show = has_inf and getattr(ctx, "mode", None) != 'OBJECT'
        try:
            if can_show:
                settings.show_all_influences = True
            elif has_inf:
                settings.saved_show_all = True
                settings.saved_wireframe = bool(settings.overlay_wireframe)
                settings.display_state_stashed = True
                settings.show_all_influences = False
            else:
                settings.show_all_influences = False
        except Exception:
            pass
        try:
            settings.display_dirty = True
        except Exception:
            pass
        return None

    try:
        if _bpy.app.background:
            _reset()
        else:
            _bpy.app.timers.register(_reset, first_interval=0.0)
    except Exception:
        _reset()


@persistent
def _sync_active_influence(_scene=None, _depsgraph=None):
    """Keep the active vertex group and its pose bone in sync.

    Picking a group in the sidebar list selects the matching pose bone;
    changing the active pose bone updates the active vertex group. This
    keeps the N-panel list and the 3D viewport consistent both ways.
    """
    ctx = bpy.context
    obj = getattr(ctx, "active_object", None)
    if obj is None or obj.type != 'MESH' or not obj.vertex_groups:
        return
    if obj.mode not in {'WEIGHT_PAINT', 'POSE'}:
        return
    from ..core.mesh_data import object_armature

    arm = object_armature(obj)
    idx = obj.vertex_groups.active_index
    if obj.name != _sync["obj"] or idx != _sync["vg"]:
        # Active group changed (list click, picker commit, ...) -> bone.
        _sync["obj"] = obj.name
        _sync["vg"] = idx
        try:
            vg_name = obj.vertex_groups[idx].name
        except Exception:
            return
        if arm is not None:
            bone = arm.data.bones.get(vg_name)
            if bone is not None:
                arm.data.bones.active = bone
                pb = arm.pose.bones.get(vg_name)
                if pb is not None:
                    pb.select = True
                    # Clicking an influence in the list (or picking it
                    # with the hold-S tool) selects ONLY that bone:
                    # deselect every other pose bone.
                    for other in arm.pose.bones:
                        if other is not pb and other.select:
                            other.select = False
        _sync["bone"] = vg_name
        return
    if arm is None:
        return
    bone = arm.data.bones.active
    bname = bone.name if bone is not None else ""
    if bname == _sync["bone"]:
        return
    _sync["bone"] = bname
    if bone is None:
        return
    try:
        gi = obj.vertex_groups[bone.name].index
        if gi != idx:
            obj.vertex_groups.active_index = gi
            _sync["vg"] = gi
    except Exception:
        pass


def register():
    global _handler
    if _handler is None:
        _handler = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_VIEW')
    global _mode_handler
    if _mode_handler is None:
        _mode_handler = _auto_exit_show_all
        if _auto_exit_show_all not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(_auto_exit_show_all)
    if _sync_active_influence not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_active_influence)
    if _sync_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_sync_load_post)


def unregister():
    global _handler
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, 'WINDOW')
        _handler = None
    global _mode_handler
    if _mode_handler is not None:
        try:
            bpy.app.handlers.depsgraph_update_post.remove(_auto_exit_show_all)
        except Exception:
            pass
        _mode_handler = None
    try:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_active_influence)
    except Exception:
        pass
    try:
        bpy.app.handlers.load_post.remove(_sync_load_post)
    except Exception:
        pass
    try:
        set_native_heatmap_hidden(bpy.context, False)
    except Exception:
        pass
    _cache["key"] = None
    _cache["colors"] = None
    _cache["tris"] = None
    _pick_surface["key"] = None
    _pick_surface["alpha"] = None
    _pick_surface["tris"] = None
