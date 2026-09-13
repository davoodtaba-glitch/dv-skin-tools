"""DV Skin Weights I/O for Maya.

Same JSON format as Blender DV Skin Tools (version 1), so weights can
move between Maya and Blender on meshes with matching vertex order.

{
  "version": 1,
  "source": "<mesh name>",
  "vertex_count": 123,
  "groups": ["BoneA", "BoneB"],
  "vertices": [
      [[0, 1.0]],
      [[0, 0.5], [1, 0.5]]
  ]
}

Usage (Maya Script Editor, Python):

    import dv_skin_weights_io
    dv_skin_weights_io.show()

Reload:

    import importlib
    import dv_skin_weights_io
    importlib.reload(dv_skin_weights_io)
    dv_skin_weights_io.show()

Select a skinned mesh, then Export / Import. Groups are joint names.
Missing influences are added when the joint exists in the scene.

Names: any Maya FBXASC### code is decoded from that file's joints
(FBXASC045='-', FBXASC046='.', or whatever ASCII that file used).
Export writes Blender names; import matches FBXASC, decoded, or underscore forms.
"""
from __future__ import annotations

import json
import math
import os
import re

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

_FORMAT_VERSION = 1
_ZERO = 1e-6
_WINDOW = "dvSkinWeightsIOWin"
_NORMALIZE = "dvSkinWtsNormalize"
_ADD_INF = "dvSkinWtsAddInf"
_ZERO_OTHERS = "dvSkinWtsZeroOthers"
_STATUS = "dvSkinWtsStatus"


def _short(name):
    return name.split("|")[-1]


def _leaf(name):
    return _short(name).split(":")[-1]


_FBXASC = re.compile(r"FBXASC(\d{3})", re.IGNORECASE)
_NON_TOKEN = re.compile(r"[^A-Za-z0-9]+")


def _decode_fbxasc(name):
    def _repl(m):
        code = int(m.group(1))
        if 32 <= code <= 126:
            return chr(code)
        return m.group(0)

    return _FBXASC.sub(_repl, name)


def blender_to_maya(name):
    name = _leaf(name)
    if _FBXASC.search(name):
        return name
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("FBXASC{:03d}".format(ord(ch)))
    return "".join(out)


def maya_to_blender(name):
    return _decode_fbxasc(_leaf(name))


def _underscore_name(name):
    return _NON_TOKEN.sub("_", maya_to_blender(name)).strip("_")


def _tight_variants(name):
    seen = []
    for n in (
        name,
        _short(name),
        _leaf(name),
        blender_to_maya(name),
        maya_to_blender(name),
    ):
        if n and n not in seen:
            seen.append(n)
    return seen


def _name_variants(name):
    seen = _tight_variants(name)
    u = _underscore_name(name)
    if u and u not in seen:
        seen.append(u)
    return seen


def _dag_path(name):
    sel = om.MSelectionList()
    sel.add(name)
    dag = sel.getDagPath(0)
    if dag.apiType() == om.MFn.kTransform:
        for i in range(dag.numberOfShapesDirectlyBelow()):
            shape_dag = om.MDagPath(dag)
            shape_dag.extendToShapeDirectlyBelow(i)
            if not om.MFnDagNode(shape_dag).isIntermediateObject:
                return shape_dag
        dag.extendToShape()
    return dag


def _depend_node(name):
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDependNode(0)


def selected_mesh():
    sel = cmds.ls(sl=True, long=True) or []
    if not sel:
        raise RuntimeError("Select a mesh")
    node = sel[0].split(".")[0]
    if cmds.nodeType(node) == "mesh":
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        if not parents:
            raise RuntimeError("Select a mesh")
        node = parents[0]
    shapes = cmds.listRelatives(
        node, shapes=True, type="mesh", noIntermediate=True, fullPath=True
    ) or []
    if not shapes:
        raise RuntimeError("Selection is not a mesh")
    return node, shapes[0]


def find_skin_cluster(geo):
    hist = cmds.listHistory(geo, pruneDagObjects=True) or []
    skins = cmds.ls(hist, type="skinCluster") or []
    return skins[0] if skins else None


def _influence_dags(fn_skin):
    return list(fn_skin.influenceObjects())


def _logical_indices(fn_skin, dags):
    return om.MIntArray([fn_skin.indexForInfluenceObject(d) for d in dags])


def _is_locked(skin, logical_index):
    attr = "{}.lockWeights[{}]".format(skin, logical_index)
    if not cmds.objExists(attr):
        return False
    return bool(cmds.getAttr(attr))


def _pick_hit(hits):
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        for hit in hits:
            if ":" not in _short(hit):
                return hit
        return hits[0]
    return None


def _resolve_name(name, joints):
    for t in _tight_variants(name):
        if cmds.objExists(t):
            return cmds.ls(t, long=True)[0]
    tight = set(_tight_variants(name))
    hit = _pick_hit([j for j in joints if tight & set(_tight_variants(j))])
    if hit:
        return hit
    target_u = _underscore_name(name)
    return _pick_hit([j for j in joints if _underscore_name(j) == target_u])


def _joint_list():
    return cmds.ls(type="joint", long=True) or []


def _skin_fn(skin, shape):
    fn_skin = oma.MFnSkinCluster(_depend_node(skin))
    dag = _dag_path(shape)
    fn_mesh = om.MFnMesh(dag)
    n = fn_mesh.numVertices
    comp_fn = om.MFnSingleIndexedComponent()
    comp = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.setCompleteData(n)
    return fn_skin, dag, comp, n


def export_skin_weights(mesh=None, path=None):
    if not path:
        raise RuntimeError("No export path")
    if mesh is None:
        transform, shape = selected_mesh()
    elif isinstance(mesh, (tuple, list)):
        transform, shape = mesh[0], mesh[1]
    else:
        transform = mesh
        shapes = cmds.listRelatives(
            transform, shapes=True, type="mesh", noIntermediate=True, fullPath=True
        ) or []
        if not shapes:
            raise RuntimeError("Not a mesh")
        shape = shapes[0]

    skin = find_skin_cluster(shape)
    if not skin:
        raise RuntimeError("Mesh has no skinCluster to export")

    fn_skin, dag, comp, n = _skin_fn(skin, shape)
    dags = _influence_dags(fn_skin)
    if not dags:
        raise RuntimeError("skinCluster has no influences")

    names = []
    used = set()
    for d in dags:
        blender_name = maya_to_blender(d.fullPathName())
        if blender_name not in used:
            names.append(blender_name)
            used.add(blender_name)
        else:
            fallback = _leaf(d.fullPathName())
            names.append(fallback)
            used.add(fallback)
    weight_array, inf_count = fn_skin.getWeights(dag, comp)

    vertices = []
    for vi in range(n):
        base = vi * inf_count
        row = []
        for gi in range(inf_count):
            w = weight_array[base + gi]
            if w > _ZERO:
                row.append([gi, float(w)])
        vertices.append(row)

    rest = _rest_points(fn_skin, dag, n)
    positions = [[round(p[0], 6), round(p[1], 6), round(p[2], 6)] for p in rest]

    data = {
        "version": _FORMAT_VERSION,
        "source": _short(transform),
        "vertex_count": n,
        "groups": names,
        "vertices": vertices,
        "positions": positions,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return {"vertices": n, "groups": len(names)}


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Not a valid weights file: {}".format(exc)) from exc
    if (
        not isinstance(data, dict)
        or data.get("version") != _FORMAT_VERSION
        or not isinstance(data.get("groups"), list)
        or not isinstance(data.get("vertices"), list)
    ):
        raise RuntimeError("Not a DV Skin per-vertex weights file (version 1)")
    names = [str(name) for name in data["groups"]]
    if not names:
        raise RuntimeError("Weights file contains no groups")
    return data, names, data["vertices"]


_AXIS = (
    (0, 1, 2, 1.0, 1.0, 1.0),
    (0, 2, 1, 1.0, 1.0, -1.0),
    (0, 2, 1, 1.0, -1.0, 1.0),
    (0, 2, 1, 1.0, 1.0, 1.0),
    (0, 1, 2, 1.0, -1.0, -1.0),
    (0, 1, 2, -1.0, 1.0, -1.0),
)
_SCALES = (1.0, 100.0, 0.01)


def _rest_points(fn_skin, dag, n):
    try:
        geoms = fn_skin.getInputGeometry()
        if geoms:
            fn = om.MFnMesh(geoms[0])
            if fn.numVertices == n:
                return [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kObject)]
    except Exception:
        pass
    return [(p.x, p.y, p.z) for p in om.MFnMesh(dag).getPoints(om.MSpace.kObject)]


def _parse_positions(data, file_n):
    pos = data.get("positions")
    if not isinstance(pos, list) or not pos:
        return None
    out = []
    for i in range(min(file_n, len(pos))):
        p = pos[i]
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            return None
        out.append((float(p[0]), float(p[1]), float(p[2])))
    return out


def _centroid(pts):
    n = float(len(pts))
    sx = sy = sz = 0.0
    for p in pts:
        sx += p[0]
        sy += p[1]
        sz += p[2]
    return (sx / n, sy / n, sz / n)


def _bbox_size(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-8)


def _xform_pt(p, spec, scale):
    i0, i1, i2, s0, s1, s2 = spec
    return (p[i0] * s0 * scale, p[i1] * s1 * scale, p[i2] * s2 * scale)


def _build_grid(pts, cell):
    inv = 1.0 / cell
    grid = {}
    for i, p in enumerate(pts):
        key = (
            int(math.floor(p[0] * inv)),
            int(math.floor(p[1] * inv)),
            int(math.floor(p[2] * inv)),
        )
        grid.setdefault(key, []).append(i)
    return grid, inv


def _nn_one(p, pts, grid, inv):
    cx = int(math.floor(p[0] * inv))
    cy = int(math.floor(p[1] * inv))
    cz = int(math.floor(p[2] * inv))
    best_i = 0
    best_d = 1e30
    found = False
    for rad in range(0, 8):
        for ix in range(cx - rad, cx + rad + 1):
            for iy in range(cy - rad, cy + rad + 1):
                for iz in range(cz - rad, cz + rad + 1):
                    bucket = grid.get((ix, iy, iz))
                    if not bucket:
                        continue
                    for i in bucket:
                        q = pts[i]
                        dx = p[0] - q[0]
                        dy = p[1] - q[1]
                        dz = p[2] - q[2]
                        d = dx * dx + dy * dy + dz * dz
                        if d < best_d:
                            best_d = d
                            best_i = i
                            found = True
        if found:
            return best_i, best_d
    for i, q in enumerate(pts):
        dx = p[0] - q[0]
        dy = p[1] - q[1]
        dz = p[2] - q[2]
        d = dx * dx + dy * dy + dz * dz
        if d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d


def _align_points(src, dst):
    dst_c = _centroid(dst)
    cell = _bbox_size(dst) / 32.0
    grid, inv = _build_grid(dst, cell)
    step = max(1, len(src) // 128)
    sample = src[::step][:128]
    best_score = None
    best_spec = _AXIS[0]
    best_scale = 1.0
    for spec in _AXIS:
        for scale in _SCALES:
            xf = [_xform_pt(p, spec, scale) for p in sample]
            c = _centroid(xf)
            t = (dst_c[0] - c[0], dst_c[1] - c[1], dst_c[2] - c[2])
            score = 0.0
            for p in xf:
                q = (p[0] + t[0], p[1] + t[1], p[2] + t[2])
                _i, d = _nn_one(q, dst, grid, inv)
                score += d
            if best_score is None or score < best_score:
                best_score = score
                best_spec = spec
                best_scale = scale
    xf = [_xform_pt(p, best_spec, best_scale) for p in src]
    c = _centroid(xf)
    t = (dst_c[0] - c[0], dst_c[1] - c[1], dst_c[2] - c[2])
    return [(p[0] + t[0], p[1] + t[1], p[2] + t[2]) for p in xf]


def _nearest_indices(src_pts, dst_pts):
    cell = _bbox_size(src_pts) / 32.0
    grid, inv = _build_grid(src_pts, cell)
    return [_nn_one(p, src_pts, grid, inv)[0] for p in dst_pts]


def _source_vertex_map(data, file_n, dst_pts):
    n = len(dst_pts)
    if n == file_n:
        return None
    src_pts = _parse_positions(data, file_n)
    if src_pts is None:
        raise RuntimeError(
            "Vertex count differs (mesh {} vs file {}) and the file has no "
            "positions. Re-export weights, then import again.".format(n, file_n)
        )
    return _nearest_indices(_align_points(src_pts, dst_pts), dst_pts)


def _existing_influence_long(skin):
    infs = cmds.skinCluster(skin, q=True, influence=True) or []
    if not infs:
        return []
    return cmds.ls(infs, long=True) or infs


def _create_skin(transform, influences):
    return cmds.skinCluster(
        influences,
        transform,
        toSelectedBones=True,
        bindMethod=0,
        skinMethod=0,
        normalizeWeights=1,
        maximumInfluences=8,
        obeyMaxInfluences=False,
        removeUnusedInfluence=False,
        weightDistribution=0,
    )[0]


def import_skin_weights(
    path,
    mesh=None,
    normalize=True,
    add_missing=True,
    zero_others=True,
):
    data, names, vertices = _load_json(path)
    if mesh is None:
        transform, shape = selected_mesh()
    else:
        transform = mesh
        shapes = cmds.listRelatives(
            transform, shapes=True, type="mesh", noIntermediate=True, fullPath=True
        ) or []
        if not shapes:
            raise RuntimeError("Not a mesh")
        shape = shapes[0]

    joints = _joint_list()
    resolved = []
    missing = []
    for name in names:
        node = _resolve_name(name, joints)
        resolved.append(node)
        if node is None:
            missing.append(name)

    found = [n for n in resolved if n]
    if not found:
        raise RuntimeError(
            "None of the file influences exist in the scene: {}".format(
                ", ".join(names[:8])
            )
        )

    skin = find_skin_cluster(shape)
    if skin is None:
        skin = _create_skin(transform, found)
    elif add_missing:
        existing = set(_existing_influence_long(skin))
        for node in found:
            if node not in existing:
                cmds.skinCluster(
                    skin,
                    edit=True,
                    addInfluence=node,
                    weight=0.0,
                    lockWeights=False,
                )
                existing.add(node)

    fn_skin, dag, comp, n = _skin_fn(skin, shape)
    dags = _influence_dags(fn_skin)
    inf_count = len(dags)
    if inf_count == 0:
        raise RuntimeError("skinCluster has no influences")

    packed_by_name = {}
    for i, d in enumerate(dags):
        for variant in _name_variants(d.fullPathName()):
            packed_by_name.setdefault(variant, i)

    file_to_packed = []
    unmatched = []
    for i, name in enumerate(names):
        node = resolved[i]
        packed = None
        if node is not None:
            packed = packed_by_name.get(node)
            if packed is None:
                for variant in _name_variants(node):
                    packed = packed_by_name.get(variant)
                    if packed is not None:
                        break
        if packed is None:
            for variant in _name_variants(name):
                packed = packed_by_name.get(variant)
                if packed is not None:
                    break
        file_to_packed.append(packed)
        if packed is None:
            unmatched.append(name)

    logical = _logical_indices(fn_skin, dags)
    locked_packed = set()
    for i, log_i in enumerate(logical):
        if _is_locked(skin, log_i):
            locked_packed.add(i)
    if locked_packed and len(locked_packed) == inf_count:
        raise RuntimeError("All groups in the file are locked on this mesh")

    current, _ = fn_skin.getWeights(dag, comp)
    out = list(current) if not zero_others else [0.0] * (n * inf_count)
    if zero_others:
        for vi in range(n):
            base = vi * inf_count
            for gi in locked_packed:
                out[base + gi] = current[base + gi]

    file_n = int(data.get("vertex_count", len(vertices)))
    imported_packed = [p for p in file_to_packed if p is not None]
    src_map = _source_vertex_map(data, file_n, _rest_points(fn_skin, dag, n))
    method = "index" if src_map is None else "closest_vertex"

    if not zero_others:
        for vi in range(n):
            base = vi * inf_count
            for packed in imported_packed:
                if packed not in locked_packed:
                    out[base + packed] = 0.0

    if src_map is None:
        limit = min(n, file_n, len(vertices))
        for vi in range(limit):
            base = vi * inf_count
            for entry in vertices[vi]:
                gi, w = int(entry[0]), float(entry[1])
                if gi < 0 or gi >= len(file_to_packed):
                    continue
                packed = file_to_packed[gi]
                if packed is None or packed in locked_packed:
                    continue
                out[base + packed] = w
    else:
        limit = n
        for vi in range(n):
            si = src_map[vi]
            if si < 0 or si >= len(vertices):
                continue
            base = vi * inf_count
            for entry in vertices[si]:
                gi, w = int(entry[0]), float(entry[1])
                if gi < 0 or gi >= len(file_to_packed):
                    continue
                packed = file_to_packed[gi]
                if packed is None or packed in locked_packed:
                    continue
                out[base + packed] = w

    max_used = 1
    for vi in range(n):
        base = vi * inf_count
        used = 0
        for gi in range(inf_count):
            if out[base + gi] > _ZERO:
                used += 1
        if used > max_used:
            max_used = used
    try:
        cmds.setAttr("{}.maintainMaxInfluences".format(skin), False)
    except Exception:
        pass
    try:
        current_max = cmds.getAttr("{}.maxInfluences".format(skin))
        if max_used > current_max:
            cmds.setAttr("{}.maxInfluences".format(skin), max_used)
    except Exception:
        pass

    fn_skin.setWeights(
        dag,
        comp,
        logical,
        om.MDoubleArray(out),
        False,
    )
    if normalize:
        cmds.skinCluster(skin, edit=True, forceNormalizeWeights=True)

    return {
        "vertices": limit,
        "groups": len(imported_packed),
        "mesh_vertices": n,
        "file_vertices": file_n,
        "missing": missing,
        "unmatched": unmatched,
        "skin": skin,
        "method": method,
    }


def _status(msg):
    if cmds.text(_STATUS, exists=True):
        cmds.text(_STATUS, edit=True, label=msg)


def _workspace_start(name):
    folder = cmds.workspace(q=True, directory=True) or os.path.expanduser("~")
    return os.path.join(folder, name)


def _on_export(*_):
    try:
        transform, shape = selected_mesh()
        start = _workspace_start(_short(transform) + "_weights.json")
        result = cmds.fileDialog2(
            caption="Export Skin Weights",
            fileFilter="DV Skin Weights (*.json)",
            dialogStyle=2,
            fileMode=0,
            startingDirectory=start,
        )
        if not result:
            return
        path = result[0]
        if not path.lower().endswith(".json"):
            path += ".json"
        stats = export_skin_weights((transform, shape), path)
        msg = "Exported {} vertices / {} groups".format(
            stats["vertices"], stats["groups"]
        )
        _status(msg)
        cmds.inViewMessage(amg=msg, pos="midCenter", fade=True)
    except (RuntimeError, OSError, ValueError) as exc:
        _status(str(exc))
        cmds.confirmDialog(
            title="DV Skin Weights",
            message=str(exc),
            button=["OK"],
            icon="critical",
        )


def _on_import(*_):
    try:
        transform, _shape = selected_mesh()
        start = _workspace_start(_short(transform) + "_weights.json")
        result = cmds.fileDialog2(
            caption="Import Skin Weights",
            fileFilter="DV Skin Weights (*.json)",
            dialogStyle=2,
            fileMode=1,
            startingDirectory=start,
        )
        if not result:
            return
        path = result[0]
        normalize = True
        add_missing = True
        zero_others = True
        if cmds.checkBox(_NORMALIZE, exists=True):
            normalize = cmds.checkBox(_NORMALIZE, q=True, value=True)
        if cmds.checkBox(_ADD_INF, exists=True):
            add_missing = cmds.checkBox(_ADD_INF, q=True, value=True)
        if cmds.checkBox(_ZERO_OTHERS, exists=True):
            zero_others = cmds.checkBox(_ZERO_OTHERS, q=True, value=True)

        cmds.waitCursor(state=True)
        cmds.undoInfo(openChunk=True, chunkName="Import Skin Weights")
        try:
            stats = import_skin_weights(
                path,
                mesh=transform,
                normalize=normalize,
                add_missing=add_missing,
                zero_others=zero_others,
            )
        finally:
            cmds.undoInfo(closeChunk=True)
            cmds.waitCursor(state=False)

        if stats["mesh_vertices"] != stats["file_vertices"]:
            if stats.get("method") == "closest_vertex":
                cmds.warning(
                    "Vertex count differs (mesh {} vs file {}) — "
                    "matched by closest vertex".format(
                        stats["mesh_vertices"], stats["file_vertices"]
                    )
                )
            else:
                cmds.warning(
                    "Vertex count differs (mesh {} vs file {}) — "
                    "imported by index up to the smaller count".format(
                        stats["mesh_vertices"], stats["file_vertices"]
                    )
                )
        extra = []
        if stats["missing"]:
            extra.append("missing joints: " + ", ".join(stats["missing"][:6]))
        if stats["unmatched"]:
            extra.append("unmatched: " + ", ".join(stats["unmatched"][:6]))
        msg = "Imported weights onto {} vertices / {} groups".format(
            stats["vertices"], stats["groups"]
        )
        if extra:
            msg = msg + "  (" + "; ".join(extra) + ")"
        _status(msg)
        cmds.inViewMessage(amg=msg, pos="midCenter", fade=True)
    except (RuntimeError, OSError, ValueError) as exc:
        _status(str(exc))
        cmds.confirmDialog(
            title="DV Skin Weights",
            message=str(exc),
            button=["OK"],
            icon="critical",
        )


def show():
    if cmds.window(_WINDOW, exists=True):
        cmds.deleteUI(_WINDOW)
    cmds.window(
        _WINDOW,
        title="DV Skin Weights I/O",
        widthHeight=(340, 220),
        sizeable=True,
    )
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnOffset=("both", 10))
    cmds.separator(height=8, style="none")
    cmds.text(
        label="Export / import DV Skin per-vertex JSON\n"
        "Names: decode FBXASC from this file's joints",
        align="center",
    )
    cmds.separator(height=4, style="none")
    cmds.button(label="Export Weights...", height=32, command=_on_export)
    cmds.button(label="Import Weights...", height=32, command=_on_import)
    cmds.separator(height=4, style="in")
    cmds.checkBox(_NORMALIZE, label="Normalize after import", value=True)
    cmds.checkBox(
        _ADD_INF,
        label="Add missing influences (if joints exist)",
        value=True,
    )
    cmds.checkBox(
        _ZERO_OTHERS,
        label="Zero influences not in file",
        value=True,
    )
    cmds.separator(height=4, style="none")
    cmds.text(_STATUS, label="Select a mesh, then export or import.", align="left")
    cmds.showWindow(_WINDOW)


if __name__ == "__main__":
    show()
