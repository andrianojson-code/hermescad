"""Blender-side operations for Hermes3D (run on Blender's main thread).

Convention: 1 Blender unit = 1 mm (scene units are set to millimetres), so STL
exports open at the right size in slicers.
"""
import base64
import contextlib
import io
import json
import math
import os
import tempfile
import time
import traceback

import bpy
import bmesh
from mathutils import Vector, Matrix

VERSION = "0.1.0"
HELPER_PREFIX = "H3D_"


# ----------------------------------------------------------------- helpers

def work_dir():
    base = bpy.utils.user_resource("DATAFILES", path="hermes3d", create=True)
    for sub in ("imports", "exports", "views"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    return base


def _mm_scene():
    us = bpy.context.scene.unit_settings
    us.system = "METRIC"
    us.scale_length = 0.001
    us.length_unit = "MILLIMETERS"


def _obj(name=None):
    if name:
        o = bpy.data.objects.get(name)
        if o is None:
            raise ValueError("no object %r (objects: %s)" % (name, ", ".join(_models())))
        return o
    models = _models()
    if len(models) == 1:
        return bpy.data.objects[models[0]]
    raise ValueError("pass name=<object>; models in scene: %s" % (", ".join(models) or "none"))


def _models():
    return [o.name for o in bpy.context.scene.objects
            if o.type == "MESH" and not o.name.startswith(HELPER_PREFIX)]


def _bbox(o):
    """World bbox from the actual vertices (obj.bound_box is cached and goes stale after
    mesh.transform until the depsgraph updates)."""
    import numpy as np
    n = len(o.data.vertices)
    if n == 0:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    co = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(o.matrix_world)
    w = co @ m[:3, :3].T + m[:3, 3]
    lo, hi = w.min(axis=0), w.max(axis=0)
    return Vector(lo.tolist()), Vector(hi.tolist())


def _apply_modifiers(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    new = bpy.data.meshes.new_from_object(ev)
    old = o.data
    o.modifiers.clear()
    o.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)


def _apply_transform(o):
    o.data.transform(o.matrix_world)
    o.matrix_world = Matrix.Identity(4)


def stats(o):
    lo, hi = _bbox(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    try:
        vol = abs(bm.calc_volume(signed=True))
    except Exception:
        vol = None
    parts = 0
    seen = set()
    for v in bm.verts:  # connected components
        if v.index in seen:
            continue
        parts += 1
        stack = [v]
        while stack:
            x = stack.pop()
            if x.index in seen:
                continue
            seen.add(x.index)
            stack.extend(e.other_vert(x) for e in x.link_edges if e.other_vert(x).index not in seen)
    out = {"name": o.name, "vertices": len(bm.verts), "faces": len(bm.faces),
           "dimensions_mm": [round(hi.x - lo.x, 3), round(hi.y - lo.y, 3), round(hi.z - lo.z, 3)],
           "bbox_min": [round(v, 3) for v in lo], "bbox_max": [round(v, 3) for v in hi],
           "non_manifold_edges": non_manifold, "open_boundary_edges": boundary,
           "watertight": non_manifold == 0 and boundary == 0,
           "loose_parts": parts,
           "volume_mm3": round(vol, 2) if vol is not None else None}
    bm.free()
    return out


# ------------------------------------------------------------------ session

def status():
    gpu = None
    try:
        import gpu as _gpu
        gpu = "%s / %s" % (_gpu.platform.vendor_get(), _gpu.platform.renderer_get())
    except Exception:
        pass
    return {"hermes3d": VERSION, "blender": bpy.app.version_string,
            "background": bpy.app.background, "gpu": gpu,
            "file": bpy.data.filepath or None, "models": _models(), "work_dir": work_dir()}


def clear_scene(keep_lights=False):
    for o in list(bpy.context.scene.objects):
        if keep_lights and o.type in ("LIGHT", "CAMERA"):
            continue
        bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        if m.users == 0:
            bpy.data.meshes.remove(m)
    _mm_scene()
    return {"cleared": True, "models": _models()}


def list_models():
    return {"models": [stats(bpy.data.objects[n]) for n in _models()]}


def mesh_stats(name=None):
    return stats(_obj(name))


# ------------------------------------------------------------------ import

_IMPORTERS = {
    ".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".stl": lambda p: bpy.ops.wm.stl_import(filepath=p),
    ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p),
    ".ply": lambda p: bpy.ops.wm.ply_import(filepath=p),
    ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p),
}


def import_model(path=None, name="Model", data_b64=None, filename=None, replace=True):
    """Import a mesh file and merge everything into ONE mesh object called `name`."""
    _mm_scene()
    if data_b64:
        path = os.path.join(work_dir(), "imports", os.path.basename(filename or "model.glb"))
        with open(path, "wb") as f:
            f.write(base64.b64decode(data_b64))
    if not path or not os.path.isfile(path):
        raise ValueError("file not found: %r" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in _IMPORTERS:
        raise ValueError("unsupported format %s (use %s)" % (ext, ", ".join(sorted(_IMPORTERS))))
    if replace and bpy.data.objects.get(name) is not None:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    before = set(bpy.data.objects)
    _IMPORTERS[ext](path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise ValueError("file contained no mesh")
    for o in meshes:
        _apply_transform(o)  # bake parent/empty transforms
    target = meshes[0]
    if len(meshes) > 1:
        bm = bmesh.new()
        for o in meshes:
            bm.from_mesh(o.data)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        target = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(target)
        mats = []
        for o in meshes:
            for m in o.data.materials:
                if m and m not in mats:
                    mats.append(m)
        for m in mats:
            target.data.materials.append(m)
    for o in new:
        if o is not target and o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)
    for col in list(target.users_collection):
        if col is not bpy.context.scene.collection:
            col.objects.unlink(target)
    if target.name not in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.link(target)
    target.name = name
    target.data.name = name
    target.parent = None
    out = stats(target)
    out["source"] = path
    return out


# --------------------------------------------------------------- transform

_UP = {"z": (0, 0, 0), "y": (90, 0, 0), "-y": (-90, 0, 0), "x": (0, -90, 0), "-x": (0, 90, 0),
       "-z": (180, 0, 0)}


def normalize(name=None, size_mm=None, axis="max", up="z", center=True, on_ground=True,
              rotate_deg=None):
    """Orient, scale uniformly so `axis` (x|y|z|max) equals size_mm, centre in XY, sit on Z=0."""
    o = _obj(name)
    _apply_transform(o)
    rot = list(_UP.get(str(up).lower(), (0, 0, 0)))
    if rotate_deg:
        rot = [rot[i] + float(rotate_deg[i]) for i in range(3)]
    if any(rot):
        from mathutils import Euler
        m = Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
        o.data.transform(m)
    lo, hi = _bbox(o)
    dims = hi - lo
    if size_mm:
        idx = {"x": 0, "y": 1, "z": 2}.get(str(axis).lower())
        cur = max(dims) if idx is None else dims[idx]
        if cur <= 0:
            raise ValueError("object has zero size on that axis")
        s = float(size_mm) / cur
        o.data.transform(Matrix.Scale(s, 4))
    lo, hi = _bbox(o)
    if center or on_ground:
        c = (lo + hi) / 2
        off = Vector((-c.x if center else 0, -c.y if center else 0, -lo.z if on_ground else 0))
        o.data.transform(Matrix.Translation(off))
    o.data.update()
    return stats(o)


def mirror_symmetrize(name=None, axis="x"):
    """Make the mesh exactly symmetric (generators are often slightly lopsided)."""
    o = _obj(name)
    mod = o.modifiers.new("H3D_sym", "MIRROR")
    mod.use_axis = [axis.lower() == "x", axis.lower() == "y", axis.lower() == "z"]
    mod.use_bisect_axis = list(mod.use_axis)
    mod.use_clip = True
    _apply_modifiers(o)
    return stats(o)


# ----------------------------------------------------------------- cleanup

def cleanup(name=None, mode="print", resolution=256, target_faces=150000, keep_largest=True,
            merge_distance_mm=0.01, smooth=0):
    """mode: print  -> voxel remesh (watertight, manifold) + decimate
             light  -> merge doubles, fix normals, decimate only (keeps original surface)"""
    o = _obj(name)
    _apply_transform(o)
    before = stats(o)
    removed_parts = 0
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=float(merge_distance_mm))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if keep_largest:
        comps, seen = [], set()
        for v in bm.verts:
            if v in seen:
                continue
            comp, stack = [], [v]
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack.extend(e.other_vert(x) for e in x.link_edges)
            comps.append(comp)
        if len(comps) > 1:
            comps.sort(key=len, reverse=True)
            small = [c for c in comps[1:] if len(c) < 0.02 * len(comps[0])]
            removed_parts = len(small)
            junk = [v for c in small for v in c]
            if junk:
                bmesh.ops.delete(bm, geom=junk, context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    if mode == "print":
        lo, hi = _bbox(o)
        vs = max(hi - lo) / float(max(32, min(int(resolution), 1024)))
        mod = o.modifiers.new("H3D_remesh", "REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = vs
        mod.use_smooth_shade = True
        _apply_modifiers(o)
    if smooth:
        mod = o.modifiers.new("H3D_smooth", "SMOOTH")
        mod.iterations = int(smooth)
        _apply_modifiers(o)
    faces = len(o.data.polygons)
    if target_faces and faces > int(target_faces):
        mod = o.modifiers.new("H3D_decimate", "DECIMATE")
        mod.ratio = max(0.001, float(target_faces) / faces)
        _apply_modifiers(o)
    for p in o.data.polygons:
        p.use_smooth = True
    after = stats(o)
    return {"before": before, "after": after, "removed_small_parts": removed_parts,
            "print_ready": after["watertight"] and after["loose_parts"] == 1}


# ------------------------------------------------------------------ render

_VIEWS = {  # camera direction (from object towards camera)
    "isometric": (1, -1, 0.8), "iso": (1, -1, 0.8), "front": (0, -1, 0), "back": (0, 1, 0),
    "right": (1, 0, 0), "left": (-1, 0, 0), "top": (0, 0, 1), "bottom": (0, 0, -1),
    "three_quarter": (1.2, -1, 0.35),
}


def render_view(view="isometric", name=None, width=900, height=700, color=(0.8, 0.8, 0.82)):
    scene = bpy.context.scene
    focus = _obj(name) if (name or len(_models()) == 1) else None
    objs = [focus] if focus else [bpy.data.objects[n] for n in _models()]
    if not objs:
        raise ValueError("nothing to render")
    pts = []
    for o in objs:
        lo, hi = _bbox(o)
        pts += [lo, hi]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c, size = (lo + hi) / 2, max((hi - lo).length, 1e-6)
    d = Vector(_VIEWS.get(str(view).lower(), _VIEWS["isometric"])).normalized()
    cam_data = bpy.data.cameras.get(HELPER_PREFIX + "cam") or bpy.data.cameras.new(HELPER_PREFIX + "cam")
    cam = bpy.data.objects.get(HELPER_PREFIX + "cam") or bpy.data.objects.new(HELPER_PREFIX + "cam", cam_data)
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = size * 1.1
    cam_data.clip_start, cam_data.clip_end = size * 0.01, size * 10
    cam.location = c + d * size * 2
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    prev = {o.name: o.hide_render for o in scene.objects}
    for o in scene.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    old_cam, old_engine = scene.camera, scene.render.engine
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = color
    scene.display.shading.show_cavity = True
    scene.display.shading.show_object_outline = True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (1, 1, 1)
    scene.render.film_transparent = False
    old_vt = scene.view_settings.view_transform
    scene.view_settings.view_transform = "Standard"  # AgX/Filmic would grey the white background
    scene.render.resolution_x, scene.render.resolution_y = int(width), int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    tag = (objs[0].name + "_") if focus else ""
    path = os.path.join(work_dir(), "views", "%s%s_%s.png" % (tag, view, time.strftime("%H%M%S")))
    scene.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        scene.camera, scene.render.engine = old_cam, old_engine
        scene.view_settings.view_transform = old_vt
        for o in scene.objects:
            if o.name in prev:
                o.hide_render = prev[o.name]
    _trim_views()
    with open(path, "rb") as f:
        data = f.read()
    return {"view": view, "path": path, "png_b64": base64.b64encode(data).decode("ascii")}


def _trim_views(keep=60):
    vdir = os.path.join(work_dir(), "views")
    try:
        files = sorted((os.path.join(vdir, n) for n in os.listdir(vdir) if n.endswith(".png")),
                       key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)
    except OSError:
        pass


# ------------------------------------------------------------------ export

def export_model(path, name=None, format=None):
    o = _obj(name)
    fmt = (format or os.path.splitext(path)[1].lstrip(".") or "stl").lower()
    if not os.path.isabs(path):
        path = os.path.join(work_dir(), "exports", path)
    if not os.path.splitext(path)[1]:
        path += "." + fmt
    for x in bpy.context.scene.objects:
        x.select_set(False)
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    if fmt == "stl":
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, apply_modifiers=True)
    elif fmt in ("glb", "gltf"):
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True,
                                  export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE")
    elif fmt == "obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    elif fmt == "ply":
        bpy.ops.wm.ply_export(filepath=path, export_selected_objects=True)
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True)
    elif fmt == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    else:
        raise ValueError("format must be stl, glb, gltf, obj, ply, fbx or blend")
    out = {"path": path, "format": fmt, "bytes": os.path.getsize(path)}
    out.update({"mesh": stats(o)})
    return out


def save_blend(path=None):
    if not path:
        path = os.path.join(work_dir(), "exports", "hermes3d_%s.blend" % time.strftime("%Y%m%d_%H%M%S"))
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return {"saved": path}


def execute_code(code):
    a = bpy.context.preferences.addons.get("hermes3d")
    if a is not None and not a.preferences.allow_code:
        raise PermissionError("execute_code is disabled in Hermes3D preferences")
    g = {"bpy": bpy, "bmesh": bmesh, "result": None}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<hermes3d>", "exec"), g)
    except Exception:
        return {"ok": False, "stdout": buf.getvalue()[-8000:], "error": traceback.format_exc()[-4000:]}
    res = g.get("result")
    try:
        json.dumps(res)
    except (TypeError, ValueError):
        res = repr(res)
    return {"ok": True, "stdout": buf.getvalue()[-8000:], "result": res}


METHODS = {f.__name__: f for f in (
    status, clear_scene, list_models, mesh_stats, import_model, normalize, mirror_symmetrize,
    cleanup, render_view, export_model, save_blend, execute_code)}


def dispatch(method, params):
    fn = METHODS.get(method)
    if fn is None:
        return {"ok": False, "error": "unknown method %r" % method}
    try:
        res = fn(**(params or {}))
        if isinstance(res, dict) and "ok" in res:
            return res
        return {"ok": True, "result": res}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc()[-3000:]}
