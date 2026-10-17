"""RPC-callable methods. Each takes keyword args and returns a JSON-serialisable dict.

Runs inside FreeCAD (GUI thread when the GUI is up). GUI-only calls degrade
gracefully when FreeCAD runs headless (freecadcmd), which is how tests run.
"""
import base64
import contextlib
import io
import json
import os
import tempfile
import traceback

import FreeCAD as App

from . import builder as B

VERSION = "0.1.0"


def _gui():
    if not App.GuiUp:
        return None
    import FreeCADGui
    return FreeCADGui


def work_dir():
    d = os.path.join(App.getUserAppDataDir(), "HermesCAD")
    for sub in ("refs", "exports", "views"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def _doc(name=None, create=False):
    if name:
        d = App.getDocument(name) if name in App.listDocuments() else None
        if d is None:
            for doc in App.listDocuments().values():
                if doc.Label == name:
                    d = doc
        if d is None:
            if create:
                return new_document(name=name, _return_doc=True)
            raise ValueError("no open document %r (open: %s)" % (name, ", ".join(App.listDocuments())))
        return d
    d = App.ActiveDocument
    if d is None:
        if create:
            return new_document(name="HermesCAD", _return_doc=True)
        raise ValueError("no active document; call new_document or open_document first")
    return d


def _activate(doc):
    App.setActiveDocument(doc.Name)
    g = _gui()
    if g is not None:
        g.ActiveDocument = g.getDocument(doc.Name)


@contextlib.contextmanager
def _transaction(doc, title):
    if not doc.UndoMode:  # headless documents start with undo disabled
        doc.UndoMode = 1
    doc.openTransaction(title)
    try:
        yield
    except Exception:
        doc.abortTransaction()
        raise
    else:
        doc.commitTransaction()


# ---------------------------------------------------------------- documents

def status():
    return {"hermescad": VERSION, "freecad": ".".join(App.Version()[:3]),
            "gui": bool(App.GuiUp), "documents": list(App.listDocuments()),
            "active": App.ActiveDocument.Name if App.ActiveDocument else None,
            "work_dir": work_dir()}


def new_document(name="HermesCAD", _return_doc=False):
    doc = App.newDocument(B._safe(name))
    doc.Label = name
    _activate(doc)
    return doc if _return_doc else {"document": doc.Name}


def open_document(path):
    doc = App.openDocument(path)
    _activate(doc)
    return {"document": doc.Name, "parts": B.list_parts(doc)}


def save_document(path=None, doc=None):
    d = _doc(doc)
    if path:
        if not os.path.isabs(path):
            path = os.path.join(work_dir(), "exports", path)
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
        d.saveAs(path)
    elif d.FileName:
        d.save()
    else:
        path = os.path.join(work_dir(), "exports", d.Name + ".FCStd")
        d.saveAs(path)
    return {"saved": d.FileName}


def close_document(doc=None):
    d = _doc(doc)
    name = d.Name
    App.closeDocument(name)
    return {"closed": name, "documents": list(App.listDocuments())}


def list_documents():
    return {"documents": [{"name": n, "label": d.Label, "file": d.FileName,
                           "parts": B.list_parts(d)} for n, d in App.listDocuments().items()],
            "active": App.ActiveDocument.Name if App.ActiveDocument else None}


def get_summary(doc=None):
    d = _doc(doc)
    parts = []
    for o in d.Objects:
        if o.TypeId == "PartDesign::Body" and o.Visibility:  # hidden = trim helper bodies
            parts.append(B.part_summary(d, o))
    others = [{"name": o.Name, "label": o.Label, "type": o.TypeId, "valid": o.isValid()}
              for o in d.Objects if o.TypeId != "PartDesign::Body" and not o.getParentGeoFeatureGroup()
              and not o.TypeId.startswith("App::Origin")]
    invalid = [o.Name for o in d.Objects if not o.isValid()]
    return {"document": d.Name, "file": d.FileName, "parts": parts,
            "other_objects": others, "invalid_objects": invalid}


# -------------------------------------------------------------------- parts

def build_part(spec, doc=None, replace=True):
    d = _doc(doc, create=True)
    _activate(d)
    if isinstance(spec, str):
        spec = json.loads(spec)
    try:
        with _transaction(d, "HermesCAD build"):
            out = B.build_part(d, spec, replace=replace)
    except B.BuildError:
        d.recompute()
        raise
    out["document"] = d.Name
    return out


def set_parameters(part, values, doc=None):
    d = _doc(doc)
    with _transaction(d, "HermesCAD parameters"):
        out = B.set_parameters(d, part, values)
    out["document"] = d.Name
    return out


def get_spec(part, doc=None):
    d = _doc(doc)
    body = B.find_body(d, part)
    if body is None or "HermesSpec" not in body.PropertiesList:
        raise ValueError("no HermesCAD part %r (parts: %s)" % (part, ", ".join(B.list_parts(d))))
    return {"part": part, "spec": json.loads(body.HermesSpec)}


def delete_object(name, doc=None):
    d = _doc(doc)
    with _transaction(d, "HermesCAD delete"):
        if B.remove_part(d, name):
            return {"deleted_part": name}
        o = d.getObject(name) or next((x for x in d.Objects if x.Label == name), None)
        if o is None:
            raise ValueError("no object %r" % name)
        d.removeObject(o.Name)
    d.recompute()
    return {"deleted": name}


def undo(steps=1, doc=None):
    d = _doc(doc)
    done = 0
    for _ in range(int(steps)):
        if d.UndoCount <= 0:
            break
        d.undo()
        done += 1
    d.recompute()
    return {"undone": done, "remaining_undo": d.UndoCount}


# --------------------------------------------------------------- references

_PLANE_ROT = {
    "XY": App.Rotation(),
    "TOP": App.Rotation(),
    "XZ": App.Rotation(App.Vector(1, 0, 0), 90),
    "FRONT": App.Rotation(App.Vector(1, 0, 0), 90),
    "YZ": App.Rotation(App.Vector(1, 1, 1), 120),
    "RIGHT": App.Rotation(App.Vector(1, 1, 1), 120),
}


def add_reference_image(image_b64, filename, width_mm, height_mm, plane="XY",
                        x=0.0, y=0.0, offset=0.0, opacity=0.5, name="Reference", doc=None):
    """Place an image as a scaled plane (Image::ImagePlane) for tracing/comparison."""
    d = _doc(doc, create=True)
    plane = plane.upper()
    if plane not in _PLANE_ROT:
        raise ValueError("plane must be XY/XZ/YZ")
    path = os.path.join(work_dir(), "refs", os.path.basename(filename))
    with open(path, "wb") as f:
        f.write(base64.b64decode(image_b64))
    rot = _PLANE_ROT[plane]
    base = rot.multVec(App.Vector(float(x), float(y), float(offset)))
    with _transaction(d, "HermesCAD reference"):
        obj = d.addObject("Image::ImagePlane", B._safe(name))
        obj.Label = name
        obj.ImageFile = path
        obj.XSize = float(width_mm)
        obj.YSize = float(height_mm)
        obj.Placement = App.Placement(base, rot)
        if App.GuiUp and hasattr(obj, "ViewObject") and obj.ViewObject:
            try:
                obj.ViewObject.Transparency = int(max(0, min(100, (1 - float(opacity)) * 100)))
            except Exception:
                pass
    d.recompute()
    return {"object": obj.Name, "file": path, "size_mm": [width_mm, height_mm], "plane": plane}


# -------------------------------------------------------------------- views

_VIEWS = {"isometric": "viewIsometric", "iso": "viewIsometric", "front": "viewFront",
          "back": "viewRear", "rear": "viewRear", "top": "viewTop", "bottom": "viewBottom",
          "right": "viewRight", "left": "viewLeft", "dimetric": "viewDimetric",
          "trimetric": "viewTrimetric", "axonometric": "viewAxonometric"}


def get_view(view="isometric", width=1024, height=768, doc=None, fit=True,
             hide_references=False, background="White", part=None):
    g = _gui()
    if g is None:
        raise RuntimeError("screenshots need the FreeCAD GUI (FreeCAD is running headless)")
    d = _doc(doc)
    _activate(d)
    gdoc = g.getDocument(d.Name)
    views = []
    try:
        views = gdoc.mdiViewsOfType("Gui::View3DInventor")
    except Exception:
        pass
    v = views[0] if views else gdoc.activeView()
    try:
        g.getMainWindow().setActiveWindow  # noqa - ensure main window exists
        if views:
            gdoc.setActiveView(v)
    except Exception:
        pass
    meth = _VIEWS.get(str(view).lower())
    if meth is None:
        raise ValueError("view must be one of: %s" % ", ".join(sorted(_VIEWS)))
    hidden = []
    focus = B.find_body(d, part) if part else None
    if part and focus is None:
        raise ValueError("no part %r (parts: %s)" % (part, ", ".join(B.list_parts(d))))
    for o in d.Objects:
        vo = getattr(o, "ViewObject", None)
        if vo is None or not vo.Visibility:
            continue
        if (hide_references and o.TypeId == "Image::ImagePlane") or \
                (focus is not None and o.TypeId == "PartDesign::Body" and o is not focus):
            vo.Visibility = False
            hidden.append(o)
    # FreeCAD animates camera changes; capture would happen mid-animation.
    vp = App.ParamGet("User parameter:BaseApp/Preferences/View")
    anim = vp.GetBool("UseNavigationAnimations", True)
    vp.SetBool("UseNavigationAnimations", False)
    try:
        if hasattr(v, "setAnimationEnabled"):
            v.setAnimationEnabled(False)
        if hasattr(v, "stopAnimating"):
            v.stopAnimating()
        getattr(v, meth)()
        g.updateGui()
        if fit:
            v.fitAll()
        g.updateGui()
        import time
        tag = (B._safe(part) + "_") if part else ""
        path = os.path.join(work_dir(), "views", "%s%s_%s.png"
                            % (tag, str(view).lower(), time.strftime("%H%M%S")))
        v.saveImage(path, int(width), int(height), background)
    finally:
        vp.SetBool("UseNavigationAnimations", anim)
        if hasattr(v, "setAnimationEnabled"):
            try:
                v.setAnimationEnabled(anim)
            except Exception:
                pass
        for o in hidden:
            o.ViewObject.Visibility = True
    with open(path, "rb") as f:
        data = f.read()
    try:  # keep the views folder small: newest 60 files
        vdir = os.path.dirname(path)
        files = sorted((os.path.join(vdir, n) for n in os.listdir(vdir) if n.endswith(".png")),
                       key=os.path.getmtime)
        for old_file in files[:-60]:
            os.remove(old_file)
    except OSError:
        pass
    return {"view": view, "png_b64": base64.b64encode(data).decode("ascii"), "path": path}


# ------------------------------------------------------------------- export

def export(path, format=None, part=None, doc=None, linear_deflection=0.05, angular_deflection=0.3):
    d = _doc(doc)
    fmt = (format or os.path.splitext(path)[1].lstrip(".") or "stl").lower()
    if not os.path.isabs(path):
        path = os.path.join(work_dir(), "exports", path)
    if not os.path.splitext(path)[1]:
        path += "." + fmt
    if part == "all":
        objs = [o for o in d.Objects if o.TypeId == "PartDesign::Body" and "HermesPart" in o.PropertiesList]
    elif part:
        body = B.find_body(d, part)
        if body is None:
            raise ValueError("no part %r" % part)
        objs = [body]
    elif len(B.list_parts(d)) > 1:
        raise ValueError("document has several parts (%s): pass part=<name>, or part='all' to "
                         "merge them into one file" % ", ".join(B.list_parts(d)))
    else:
        objs = [o for o in d.Objects if o.TypeId == "PartDesign::Body" and o.Visibility] or \
               [o for o in d.Objects if hasattr(o, "Shape") and o.isDerivedFrom("Part::Feature")
                and not o.getParentGeoFeatureGroup()]
    if not objs:
        raise ValueError("nothing to export")
    d.recompute()
    if fmt == "stl":
        import Mesh
        import MeshPart
        mesh = Mesh.Mesh()
        for o in objs:
            mesh.addMesh(MeshPart.meshFromShape(Shape=o.Shape, LinearDeflection=float(linear_deflection),
                                                AngularDeflection=float(angular_deflection),
                                                Relative=False))
        mesh.write(path)
        solid_vol = sum(o.Shape.Volume for o in objs)
        bb = mesh.BoundBox
        extra = {"triangles": mesh.CountFacets,
                 "mesh_check": {
                     "watertight": bool(mesh.isSolid()),
                     "non_manifold": bool(mesh.hasNonManifolds()),
                     "self_intersections": bool(mesh.hasSelfIntersections()),
                     "volume_mm3": round(mesh.Volume, 2),
                     "volume_deviation_pct": round(abs(mesh.Volume - solid_vol) / solid_vol * 100, 3)
                     if solid_vol else None,
                     "bbox_size_mm": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)]}}
        mc = extra["mesh_check"]
        extra["print_ready"] = mc["watertight"] and not mc["non_manifold"] \
            and not mc["self_intersections"] and (mc["volume_deviation_pct"] or 0) < 1.0
    elif fmt in ("step", "stp", "iges", "igs", "brep"):
        import Part
        shape = Part.makeCompound([o.Shape for o in objs]) if len(objs) > 1 else objs[0].Shape
        {"step": shape.exportStep, "stp": shape.exportStep, "iges": shape.exportIges,
         "igs": shape.exportIges, "brep": shape.exportBrep}[fmt](path)
        extra = {}
    else:
        raise ValueError("format must be stl, step, iges or brep")
    out = {"path": path, "format": fmt, "bytes": os.path.getsize(path),
           "objects": [o.Name for o in objs]}
    out.update(extra)
    return out


# ------------------------------------------------------------- escape hatch

def execute_code(code, doc=None):
    if not App.ParamGet("User parameter:BaseApp/Preferences/Mod/HermesCAD").GetBool("AllowCode", True):
        raise PermissionError("execute_code is disabled in HermesCAD preferences")
    g = {"App": App, "FreeCAD": App, "doc": App.ActiveDocument, "result": None}
    if App.GuiUp:
        import FreeCADGui
        g["Gui"] = g["FreeCADGui"] = FreeCADGui
    if doc:
        g["doc"] = _doc(doc)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<hermescad>", "exec"), g)
    except Exception:
        return {"ok": False, "stdout": buf.getvalue()[-8000:], "error": traceback.format_exc()[-4000:]}
    if g.get("doc") is not None:
        g["doc"].recompute()
    res = g.get("result")
    try:
        json.dumps(res)
    except (TypeError, ValueError):
        res = repr(res)
    return {"ok": True, "stdout": buf.getvalue()[-8000:], "result": res}


METHODS = {f.__name__: f for f in (
    status, new_document, open_document, save_document, close_document, list_documents, get_summary,
    build_part, set_parameters, get_spec, delete_object, undo, add_reference_image,
    get_view, export, execute_code)}


def dispatch(method, params):
    fn = METHODS.get(method)
    if fn is None:
        return {"ok": False, "error": "unknown method %r" % method}
    try:
        res = fn(**(params or {}))
        if isinstance(res, dict) and "ok" in res:
            return res
        return {"ok": True, "result": res}
    except B.BuildError as exc:
        return {"ok": False, "error": str(exc), "kind": "build"}
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc()[-3000:]}
