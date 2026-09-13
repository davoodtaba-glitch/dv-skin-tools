bl_info = {
    "name": "DV Skin Tools",
    "author": "Davood Taba <davoodice@gmail.com>",
    "version": (0, 8, 26),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Weight Paint > Sidebar > DV Skin Tools",
    "description": "Maya-style multi-influence skinning: smooth, bind nearest, replace/add/remove",
    "category": "Paint",
    "doc_url": "",
}

import bpy
from bpy.app.handlers import persistent

from . import ops, properties, ui

_modules = (properties, ops, ui)


@persistent
def _load_post(_dummy):
    try:
        if not bpy.app.background:
            bpy.app.timers.register(ui._boot_ui, first_interval=1.0)
    except Exception:
        pass


def register():
    for mod in _modules:
        mod.register()
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)


def unregister():
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    for mod in reversed(_modules):
        mod.unregister()
