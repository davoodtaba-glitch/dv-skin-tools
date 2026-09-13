"""Viewport overlay for the smooth brush cursor and HUD."""

from __future__ import annotations

import blf
import gpu
from gpu_extras.presets import draw_circle_2d
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d


def world_radius_to_px(region, rv3d, world_loc, world_radius):
    if world_loc is None or rv3d is None:
        return 48.0
    center = location_3d_to_region_2d(region, rv3d, world_loc)
    right = rv3d.view_matrix.inverted().col[0].xyz.normalized()
    edge = location_3d_to_region_2d(region, rv3d, Vector(world_loc) + right * world_radius)
    if center is None or edge is None:
        return 48.0
    return max((edge - center).length, 4.0)


def draw_brush_cursor(mouse, radius_px, color, strength=1.0):
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    draw_circle_2d(mouse, color, radius_px)
    inner = max(radius_px * (0.08 + 0.22 * float(strength)), 2.0)
    inner_color = (color[0], color[1], color[2], color[3] * 0.55)
    draw_circle_2d(mouse, inner_color, inner)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def draw_hud(region, lines):
    if not lines:
        return
    font = 0
    x = 18
    y = 28
    blf.size(font, 13)
    for i, text in enumerate(reversed(lines)):
        py = y + i * 18
        blf.color(font, 0.0, 0.0, 0.0, 0.7)
        blf.position(font, x + 1, py - 1, 0)
        blf.draw(font, text)
        blf.color(font, 0.85, 0.95, 1.0, 1.0)
        blf.position(font, x, py, 0)
        blf.draw(font, text)


SMOOTH_COLOR = (0.30, 0.88, 0.92, 0.95)
SHARPEN_COLOR = (0.98, 0.62, 0.22, 0.95)
STITCH_COLOR = (0.65, 0.50, 0.95, 0.95)
REPLACE_COLOR = (0.95, 0.35, 0.45, 0.95)
ADD_COLOR = (0.35, 0.90, 0.45, 0.95)
REMOVE_COLOR = (0.95, 0.45, 0.85, 0.95)
ADJUST_COLOR = (1.00, 0.92, 0.35, 0.95)

_MODE_COLORS = {
    'SMOOTH': SMOOTH_COLOR,
    'SHARPEN': SHARPEN_COLOR,
    'STITCH': STITCH_COLOR,
    'REPLACE': REPLACE_COLOR,
    'ADD': ADD_COLOR,
    'REMOVE': REMOVE_COLOR,
}


def mode_color(mode):
    return _MODE_COLORS.get(mode, SMOOTH_COLOR)
