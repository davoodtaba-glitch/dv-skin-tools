import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Object, PropertyGroup


class SkinSceneBone(PropertyGroup):
    name: StringProperty(name="Bone")
    armature_name: StringProperty(name="Armature")


class SkinToolsSettings(PropertyGroup):
    intensity: FloatProperty(
        name="Intensity",
        description="Brush strength. Smooth/Add/Remove blend by this amount. Replace uses it as the target weight",
        default=0.1,
        min=0.0,
        max=1.0,
        soft_min=0.01,
        soft_max=1.0,
        precision=3,
    )
    iterations: IntProperty(
        name="Iterations",
        description="Repeat the smooth inside each stamp. Higher values spread faster on dense meshes",
        default=1,
        min=1,
        max=50,
    )
    radius: FloatProperty(
        name="Radius",
        description="Brush radius in scene units",
        default=0.15,
        min=0.0001,
        soft_max=10.0,
        unit='LENGTH',
        precision=4,
    )
    radius_initialized: BoolProperty(
        name="Radius Initialized",
        default=False,
        options={'HIDDEN'},
    )
    falloff: EnumProperty(
        name="Falloff",
        description="Brush falloff from center to edge",
        items=(
            ('SMOOTH', "Smooth", "Smoothstep falloff"),
            ('LINEAR', "Linear", "Linear falloff"),
            ('SPHERE', "Sphere", "Spherical falloff"),
            ('CONSTANT', "Constant", "Full strength inside the radius"),
        ),
        default='SMOOTH',
    )
    neighbor_mode: EnumProperty(
        name="Neighbors",
        description="Which vertices contribute to the average",
        items=(
            ('SURFACE', "Surface", "Average along mesh edges (default)"),
            ('VOLUME', "Volume", "Average nearby vertices in space, including across gaps and thin surfaces"),
        ),
        default='SURFACE',
    )
    volume_radius: FloatProperty(
        name="Volume Radius",
        description="Search radius for volume neighbors. 0 uses a multiple of average edge length",
        default=0.0,
        min=0.0,
        soft_max=2.0,
        unit='LENGTH',
        precision=4,
    )
    projection: EnumProperty(
        name="Projection",
        description="How the brush picks vertices",
        items=(
            ('SURFACE', "Surface", "Vertices near the surface hit point"),
            ('SCREEN', "Screen", "Vertices near the mouse in screen space, including both sides of the mesh"),
        ),
        default='SURFACE',
    )
    target: EnumProperty(
        name="Target",
        description="Which influences the brush is allowed to change",
        items=(
            ('ALL', "All Deform", "All deform bones. Locked groups are always preserved"),
            ('SELECTED', "Selected Bones", "Only selected pose bones. Others are treated as locked"),
        ),
        default='ALL',
    )
    only_existing: BoolProperty(
        name="Only Existing Influences",
        description="Do not add new influences to a vertex. Leave off to blend between bones",
        default=False,
    )
    max_influences: IntProperty(
        name="Max Influences",
        description="Cap influences per vertex after smoothing. 0 means no extra cap",
        default=0,
        min=0,
        max=32,
    )
    prune: FloatProperty(
        name="Prune",
        description="Weights at or below this are removed after smoothing",
        default=0.0001,
        min=0.0,
        max=0.1,
        precision=5,
    )
    front_faces_only: BoolProperty(
        name="Front Faces Only",
        description="Ignore vertices facing away from the view",
        default=False,
    )
    skip_border_edges: BoolProperty(
        name="Skip Border Edges",
        description=(
            "Leave vertices on open boundary edges out of Smooth/Sharpen, "
            "so smoothing cannot pull split-seam borders out of alignment"
        ),
        default=False,
    )
    sync_border_weights: BoolProperty(
        name="Sync Border Weights",
        description=(
            "While smoothing, keep split-seam borders matched: each border "
            "vertex with a partner across the gap (within Stitch Threshold) "
            "is averaged with it after every stamp, so the two open border "
            "edges cannot pull apart. Without a matching vertex the partner "
            "weights are interpolated on the nearest edge of the other border"
        ),
        default=False,
    )
    stitch_threshold: FloatProperty(
        name="Stitch Threshold",
        description=(
            "Max distance between border vertex pairs for Stitch and Sync "
            "Border Weights (local mesh units, like Mirror Threshold). "
            "Without a matching vertex, weights are taken from the nearest "
            "border edge of the other side within this distance. "
            "0 derives it from half the average edge length"
        ),
        default=0.0,
        min=0.0,
        soft_max=1.0,
        precision=4,
        unit='LENGTH',
    )
    use_x_mirror: BoolProperty(
        name="Interactive Mirror Paint",
        description="Also paint the mirrored vertex across local X with the mirrored bone (R.arm paints L.arm on the other side)",
        default=False,
    )
    spacing: FloatProperty(
        name="Spacing",
        description="Minimum travel, as a fraction of radius, before the next stamp",
        default=0.2,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    airbrush: BoolProperty(
        name="Airbrush",
        description="Keep applying while the mouse is held still",
        default=False,
    )
    use_pressure: BoolProperty(
        name="Tablet Pressure",
        description="Multiply intensity by stylus pressure",
        default=True,
    )
    mode: EnumProperty(
        name="Mode",
        description="Brush operation",
        items=(
            ('SMOOTH', "Smooth", "Average all influences with neighbors, keeping relative weight transitions between nearby vertices"),
            ('SHARPEN', "Sharpen", "Push weights away from the neighbor average to restore definition"),
            ('STITCH', "Stitch", "Blend border vertices toward their partner across open seam gaps"),
            ('REPLACE', "Replace", "Set the active bone to Intensity"),
            ('ADD', "Add", "Add Intensity to the active bone"),
            ('REMOVE', "Remove", "Subtract Intensity from the active bone"),
        ),
        default='SMOOTH',
        update=lambda self, context: _update_mode(self, context),
    )
    # Per-mode last-used intensity: switching brush modes restores what
    # the user had in that mode instead of the factory default. Hidden
    # slots, one per mode of the enum above.
    intensity_smooth: FloatProperty(
        default=0.1, min=0.0, max=1.0, options={'HIDDEN'},
    )
    intensity_sharpen: FloatProperty(
        default=0.1, min=0.0, max=1.0, options={'HIDDEN'},
    )
    intensity_stitch: FloatProperty(
        default=0.5, min=0.0, max=1.0, options={'HIDDEN'},
    )
    intensity_replace: FloatProperty(
        default=1.0, min=0.0, max=1.0, options={'HIDDEN'},
    )
    intensity_add: FloatProperty(
        default=0.1, min=0.0, max=1.0, options={'HIDDEN'},
    )
    intensity_remove: FloatProperty(
        default=1.0, min=0.0, max=1.0, options={'HIDDEN'},
    )
    paint_active: BoolProperty(
        name="Brush Active",
        description="True while the Smooth Skin brush modal is running",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    saved_show_all: BoolProperty(
        name="Saved Show All Influences",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    saved_wireframe: BoolProperty(
        name="Saved Wireframe",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    display_state_stashed: BoolProperty(
        name="Display State Stashed",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    mode_prev: StringProperty(
        name="Previous Mode",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    show_all_influences: BoolProperty(
        name="Show All Influences",
        description="Color the mesh by every bone at once, like Maya (replaces the blue-red heatmap)",
        default=True,
        update=lambda self, context: _update_show_all(self, context),
    )
    saved_wp_opacity: FloatProperty(
        name="Saved Weight Paint Opacity",
        default=1.0,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    wp_opacity_stashed: BoolProperty(
        name="Weight Paint Opacity Stashed",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    saved_hide: BoolProperty(
        name="Saved Hide",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    saved_hide_obj: StringProperty(
        name="Saved Hide Object",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    mesh_hide_stashed: BoolProperty(
        name="Mesh Hide Stashed",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    overlay_opacity: FloatProperty(
        name="Overlay Opacity",
        description="Opacity of the multi-color influence display",
        default=1.0,
        min=0.1,
        max=1.0,
        subtype='FACTOR',
        update=lambda self, context: _tag_view3d(context),
    )
    display_dirty: BoolProperty(
        name="Display Dirty",
        default=True,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    color_seed: IntProperty(
        name="Color Seed",
        description="Seed for influence display colors. Changing it recolors bones without changing weights",
        default=1,
        min=1,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    mirror_direction: EnumProperty(
        name="Mirror Direction",
        description="Which side of the X axis provides the weights",
        items=(
            ('POS_TO_NEG', "+X to -X", "Copy weights from the +X side onto the -X side (left to right)"),
            ('NEG_TO_POS', "-X to +X", "Copy weights from the -X side onto the +X side (right to left)"),
            ('HEAVIER', "Heavier Side", "Mutual pairs: whichever side has more total weight wins"),
        ),
        default='POS_TO_NEG',
    )
    mirror_threshold: FloatProperty(
        name="Mirror Threshold",
        description="Max distance between mirror vertex pairs (local mesh units). 0 derives it from the average edge length",
        default=1.0,
        min=0.0,
        soft_max=1.0,
        precision=4,
        unit='LENGTH',
    )
    mirror_pattern: StringProperty(
        name="Mirror Pattern",
        description="Optional example bone showing your side convention (e.g. R-arm, Arm_R, R__arm, RIGHT_arm). X-Mirror and Mirror Weights try this rule first, then fall back to the built-in .L/.R rules. Leave empty to use built-ins only",
        default="",
    )
    bone_xray: BoolProperty(
        name="Bone X-Ray",
        description="Draw the skin's armature bones on top of the influence colors (x-ray), like the armature's In Front display",
        default=False,
        update=lambda self, context: _tag_view3d(context),
    )
    bone_xray_all: BoolProperty(
        name="X-Ray All Bones",
        description="Draw every bound bone through the mesh, even when its bone collection is invisible, the bone is hidden, or the armature object is hidden",
        default=False,
        update=lambda self, context: _tag_view3d(context),
    )
    bind_selected: BoolProperty(
        name="Selected",
        description="Bind Nearest affects only the selected pose bones; when off, all deform bones compete",
        default=False,
    )
    bind_mirror: BoolProperty(
        name="Mirror",
        description="Mirror the Bind Nearest result across X using the Mirror Weights direction and threshold; when off, no mirror is applied",
        default=False,
    )
    live_select: BoolProperty(
        name="Live Select",
        description="While holding S, hovering a bone adds it to the selection; holding D and hovering a bone subtracts it from the selection",
        default=False,
    )
    overlay_wireframe: BoolProperty(
        name="Wireframe",
        description="Draw the mesh wireframe over the Show All Influences colors",
        default=True,
        update=lambda self, context: _tag_view3d(context),
    )
    last_picked_group: StringProperty(
        name="Last Picked Group",
        description="Vertex group chosen with the hold-S picker, highlighted in the panel influence list",
        default="",
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    copy_skin_source: PointerProperty(
        name="Source Object",
        description="Skinned mesh to copy skin weights from onto the active mesh",
        type=Object,
        poll=lambda self, obj: obj is not None and obj.type == 'MESH',
    )
    copy_use_selected_sources: BoolProperty(
        name="Use Selected as Sources",
        description=(
            "Maya-style multi-source copy: the active mesh is the target "
            "and every other selected mesh is a source. Each target vertex "
            "takes its weights from the nearest source surface, so one "
            "mesh can follow several overlapping garments"
        ),
        default=False,
    )
    copy_skin_surface: EnumProperty(
        name="Surface Association",
        description="How each target vertex finds its source weights",
        items=(
            ('CLOSEST_SURFACE', "Closest point on surface",
             "Interpolate the source weights at the closest point on the source surface"),
            ('NEAREST_VERTEX', "Nearest vertex",
             "Take the weights of the nearest source vertex"),
        ),
        default='CLOSEST_SURFACE',
    )
    copy_skin_assoc: EnumProperty(
        name="Influence Association",
        description="How source influences map to the target's vertex groups",
        items=(
            ('CLOSEST_JOINT', "Closest joint",
             "Match by name first, then by nearest bone joint position"),
            ('NAME', "Name lookup",
             "Only match influences with identical names"),
            ('ONE_TO_ONE', "One-to-one",
             "Match vertex groups by their order in the list"),
        ),
        default='CLOSEST_JOINT',
    )
    copy_skin_normalize: BoolProperty(
        name="Normalize",
        description="Normalize the copied weights to sum to 1.0 per vertex",
        default=True,
    )
    bone_filter: StringProperty(
        name="Bone Filter",
        description="Show only bones whose name contains this text",
        default="",
    )
    list_rows: IntProperty(
        name="List Height",
        description="Visible rows in the influence list",
        default=5,
        min=1,
        max=30,
    )
    scene_bones: CollectionProperty(type=SkinSceneBone, options={'SKIP_SAVE'})
    scene_bone_index: IntProperty(
        name="Scene Bone",
        default=0,
        options={'SKIP_SAVE'},
    )
    scene_bones_sig: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})


def _update_show_all(self, context):
    from .ui.color_overlay import set_native_heatmap_hidden

    set_native_heatmap_hidden(context, self.show_all_influences)
    _tag_view3d(context)


# Factory default intensity per mode, used only the first time a mode
# is entered (afterwards the user's last value in that mode wins).
_MODE_DEFAULT_INTENSITY = {
    'REPLACE': 1.0,
    'REMOVE': 1.0,
    'SMOOTH': 0.1,
    'SHARPEN': 0.1,
    'STITCH': 0.5,
    'ADD': 0.1,
}


def _intensity_slot(mode):
    """Property name of the hidden per-mode intensity slot."""
    return "intensity_" + str(mode).lower()


def _update_mode(self, context):
    # Fires on any assignment (even same-value via Python). Only act on
    # an actual mode change, so re-setting the same mode never touches
    # values. Leaving a mode stashes the current intensity in that
    # mode's slot; entering a mode restores its slot — the user's last
    # value — instead of clobbering it with the factory default. The
    # factory default applies only when a mode is entered for the very
    # first time (slot untouched since the property group was created).
    if self.mode_prev == self.mode:
        return
    if self.mode_prev:
        slot = _intensity_slot(self.mode_prev)
        if getattr(self, slot, None) is not None:
            setattr(self, slot, float(self.intensity))
    slot = _intensity_slot(self.mode)
    saved = getattr(self, slot, None)
    if saved is None:
        default = _MODE_DEFAULT_INTENSITY.get(self.mode)
        if default is not None:
            self.intensity = default
    else:
        self.intensity = float(saved)
    self.mode_prev = self.mode


def remember_display_state(settings):
    """Stash the display toggles before something force-clears them.

    First stash wins: a repeated stash (e.g. a second shutdown while
    the values are already cleared) must not overwrite the user's
    remembered choice with the cleared values.
    """
    if settings.display_state_stashed:
        return
    settings.saved_show_all = bool(settings.show_all_influences)
    settings.saved_wireframe = bool(settings.overlay_wireframe)
    settings.display_state_stashed = True


def restore_display_state(context):
    """Re-apply the stashed display toggles (no-op when nothing stashed)."""
    settings = _settings_from(context)
    if settings is None or not settings.display_state_stashed:
        return
    from .core.mesh_data import mesh_has_influences

    settings.display_state_stashed = False
    obj = getattr(context, "active_object", None)
    settings.show_all_influences = bool(settings.saved_show_all) and mesh_has_influences(obj)
    settings.overlay_wireframe = bool(settings.saved_wireframe)


def _tag_view3d(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _settings_from(context):
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        return wm.skin_tools
    return None


def ensure_radius(settings, obj):
    if settings.radius_initialized:
        return
    dim = max(obj.dimensions) if obj is not None else 0.0
    if dim <= 0.0:
        dim = 1.0
    settings.radius = max(dim * 0.06, 0.01)
    settings.radius_initialized = True


classes = (SkinSceneBone, SkinToolsSettings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.skin_tools = PointerProperty(type=SkinToolsSettings)


def unregister():
    del bpy.types.WindowManager.skin_tools
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
