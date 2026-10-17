"""HermesCAD MCP server: exposes FreeCAD (via the HermesCAD addon bridge) to Hermes Agent.

Run:  python -m hermescad_mcp            (stdio, what Hermes launches)
Env:  HERMESCAD_HOST / HERMESCAD_PORT / HERMESCAD_TOKEN / HERMESCAD_TIMEOUT
"""
import base64
import io
import json
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP, Image

from . import vision
from .client import Bridge, BridgeError

SPEC_PATH = os.path.join(os.path.dirname(__file__), "SPEC.md")

mcp = FastMCP(
    "hermescad",
    instructions=(
        "Tools to build and edit parametric FreeCAD models. To model a part from a photo, "
        "screenshot or drawing: (1) look at the image (inspect_image), (2) estimate dimensions "
        "from known references or ask the user for one key dimension, (3) for drawings and clean "
        "silhouettes use extract_contours to get exact outlines, (4) write a part spec "
        "(read get_spec_reference once) and call build_part, (5) compare_with_reference in the "
        "same view and fix the spec until it matches, (6) save_document / export_model. "
        "Edit existing parts with get_part_spec + set_parameters or build_part with the same name."
    ),
)
bridge = Bridge()


def _j(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _call(method, **kw):
    try:
        return bridge.call(method, **kw)
    except BridgeError as exc:
        raise RuntimeError(str(exc))


def _shot(view="isometric", width=720, height=540, document=None, part=None):
    try:
        r = bridge.call("get_view", view=view, width=width, height=height, doc=document,
                        hide_references=True, part=part)
        return Image(data=base64.b64decode(r["png_b64"]), format="png"), r.get("path")
    except BridgeError:
        return None, None  # headless FreeCAD or no view: text-only feedback


def _with_shot(result, view, screenshot, document=None, part=None):
    img, path = (None, None)
    if screenshot:
        img, path = _shot(view, document=document, part=part)
        if path:
            result = dict(result, screenshot_path=path)
    out = [_j(result)]
    if img is not None:
        out.append(img)
    return out


# ------------------------------------------------------------------ session

@mcp.tool()
def freecad_status() -> str:
    """Check the FreeCAD connection: versions, open documents, active document."""
    return _j(_call("status"))


@mcp.tool()
def get_spec_reference() -> str:
    """Full reference of the part-spec JSON format used by build_part (profiles, features,
    edge selectors, recipes). Read it before writing your first spec in a session."""
    with open(SPEC_PATH, encoding="utf-8") as f:
        return f.read()


@mcp.tool()
def new_document(name: str = "HermesCAD") -> str:
    """Create a new empty FreeCAD document and make it active."""
    return _j(_call("new_document", name=name))


@mcp.tool()
def open_document(path: str) -> str:
    """Open an .FCStd file (path on the FreeCAD computer)."""
    return _j(_call("open_document", path=path))


@mcp.tool()
def save_document(path: Optional[str] = None, document: Optional[str] = None) -> str:
    """Save the document. path: absolute .FCStd path, or a bare file name to save into the
    HermesCAD exports folder. Without path: save in place (or into exports if never saved)."""
    return _j(_call("save_document", path=path, doc=document))


@mcp.tool()
def close_document(document: Optional[str] = None) -> str:
    """Close a document without saving (default: the active one). Use it to drop leftovers
    such as an old test document before starting a new part."""
    return _j(_call("close_document", doc=document))


@mcp.tool()
def list_documents() -> str:
    """List open documents and the HermesCAD parts in each."""
    return _j(_call("list_documents"))


@mcp.tool()
def get_model_summary(document: Optional[str] = None) -> str:
    """Parts in the document with bounding box (mm), volume, parameters, validity, plus other objects."""
    return _j(_call("get_summary", doc=document))


# -------------------------------------------------------------------- parts

@mcp.tool()
def build_part(spec: dict[str, Any], document: Optional[str] = None, replace: bool = True,
               screenshot: bool = True, view: str = "isometric") -> list:
    """Build a parametric part (PartDesign body + Params spreadsheet) from a JSON spec.

    spec = {"name": str, "parameters": {name: number|expr},
            "features": [{"id", "type": pad|pocket|hole|revolve|groove|fillet|chamfer,
                          "plane": XY|XZ|YZ, "offset", "profile"|"profiles", "length"|"depth"|
                          "through_all", "edges", "radius"|"size", ...}]}
    Profiles: rect{w,h,x,y}, circle{d|r,x,y}, slot{length,w,x,y,angle}, polygon{points},
    regular_polygon{n,d|across_flats}, circle_pattern{count,pcd,d}, grid{nx,ny,dx,dy,d},
    path{start, segments:[{line},{arc:{through,to}},{spline:[...]}]}, spline{points} (closed).
    Pad extras: "taper": deg (positive narrows). Sketch extras: "tilt": {"axis":"x"|"y","angle"}.
    Values may be expressions over parameters ("L/2-8"). Call get_spec_reference for details.
    Optional "expect_bbox": [X, Y, Z] overall size from the drawing (null = unknown): the
    result then warns if the model's envelope does not match.
    Same name replaces the existing part. Returns bbox/volume, a screenshot and its file path."""
    res = _call("build_part", spec=spec, doc=document, replace=replace)
    return _with_shot(res, view, screenshot, document, part=res.get("part"))


@mcp.tool()
def get_part_spec(part: str, document: Optional[str] = None) -> str:
    """Return the stored spec of a part (to modify it and call build_part again)."""
    return _j(_call("get_spec", part=part, doc=document))


@mcp.tool()
def set_parameters(part: str, values: dict[str, Any], document: Optional[str] = None,
                   screenshot: bool = True, view: str = "isometric") -> list:
    """Change named parameters of a part, e.g. {"L": 120, "hole_d": 8}. Fast path for edits
    like 'make it 10 mm longer'. Values may be expressions. Returns new bbox and a screenshot."""
    res = _call("set_parameters", part=part, values=values, doc=document)
    return _with_shot(res, view, screenshot, document, part=part)


@mcp.tool()
def delete_object(name: str, document: Optional[str] = None) -> str:
    """Delete a part (by part name) or any object (by name/label)."""
    return _j(_call("delete_object", name=name, doc=document))


@mcp.tool()
def undo(steps: int = 1, document: Optional[str] = None) -> str:
    """Undo the last operations (each build_part / set_parameters is one step)."""
    return _j(_call("undo", steps=steps, doc=document))


# ------------------------------------------------------------------- images

@mcp.tool()
def inspect_image(image_path: str, max_side: int = 1568) -> list:
    """Load an image file (photo, screenshot, drawing) so you can look at it. Returns the image
    (downscaled) and its pixel size. Use when the user gives a path instead of attaching."""
    img = vision.load(image_path)
    return ["%s: %dx%d px" % (os.path.basename(image_path), img.width, img.height),
            Image(data=vision.to_png(img, max_side), format="png")]


@mcp.tool()
def extract_contours(image_path: str, ref_length_mm: Optional[float] = None,
                     ref_axis: str = "width", mm_per_px: Optional[float] = None,
                     crop: Optional[list[int]] = None, invert: Optional[bool] = None,
                     threshold: Optional[int] = None, min_area_frac: float = 0.002,
                     epsilon_frac: float = 0.004, mode: str = "auto",
                     as_spline: bool = False, spline_points: int = 32) -> list:
    """Trace the part outline (and holes) from a drawing, silhouette OR a photo on a plain
    background. THE way to get organic / curved shapes: trace the view that shows the part's
    main silhouette (usually a side view) and pad it.

    mode: auto | drawing | photo (photo = cut the part out of a plain background).
    as_spline=true returns the outline as {"type":"spline","points":[...]} ready to paste into a
    spec profile (spline_points 16..60; fewer = smoother). Scale: ref_length_mm = real size of the
    outline along ref_axis ("width"|"height"), or mm_per_px. crop=[x0,y0,x1,y1] isolates one view.
    Coordinates: mm, origin at the outline bbox centre, +Y up. Returns an overlay image + its
    path (red = outline, blue = holes): check it before building. Perspective photos give an
    approximate outline; a straight side-on photo gives a good one."""
    from . import vision_cli
    ov_path = os.path.splitext(image_path)[0] + "_outline.png"
    data = vision_cli.run("extract_contours", ov_path, path=image_path, crop=crop, invert=invert,
                          threshold=threshold, min_area_frac=min_area_frac,
                          epsilon_frac=epsilon_frac, ref_length_mm=ref_length_mm,
                          ref_axis=ref_axis, mm_per_px=mm_per_px, mode=mode,
                          as_spline=as_spline, spline_points=spline_points)
    data["overlay_image_file"] = data.pop("overlay_png", ov_path)
    from PIL import Image as PILImage
    png = vision.to_png(PILImage.open(data["overlay_image_file"]).convert("RGB"), 1200)
    return [_j(data), Image(data=png, format="png")]


@mcp.tool()
def add_reference_image(image_path: str, width_mm: float, height_mm: Optional[float] = None,
                        plane: str = "XY", x: float = 0, y: float = 0, offset: float = -0.5,
                        opacity: float = 0.5, name: str = "Reference",
                        document: Optional[str] = None) -> str:
    """Put an image into the 3D scene as a scaled plane (for tracing and visual comparison).
    width_mm = real width the image covers; height defaults to keep the aspect ratio.
    plane XY = top view, XZ = front, YZ = right. Centre at (x, y); offset along the normal."""
    img = vision.load(image_path)
    if not height_mm:
        height_mm = width_mm * img.height / float(img.width)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    res = _call("add_reference_image", image_b64=base64.b64encode(buf.getvalue()).decode(),
                filename=os.path.splitext(os.path.basename(image_path))[0] + ".png",
                width_mm=width_mm, height_mm=height_mm, plane=plane, x=x, y=y,
                offset=offset, opacity=opacity, name=name, doc=document)
    return _j(res)


@mcp.tool()
def get_view(view: str = "isometric", width: int = 1024, height: int = 768,
             document: Optional[str] = None, hide_references: bool = False,
             part: Optional[str] = None) -> list:
    """Screenshot of the model. view: isometric, front, back, top, bottom, left, right,
    dimetric, trimetric. part: show only this part (other parts hidden for the shot)."""
    r = _call("get_view", view=view, width=width, height=height, doc=document,
              hide_references=hide_references, part=part)
    return ["view=%s\nimage file (open it with your image tool if you cannot see the picture): %s"
            % (view, r.get("path")), Image(data=base64.b64decode(r["png_b64"]), format="png")]


@mcp.tool()
def compare_with_reference(reference_path: str, view: str = "isometric",
                           document: Optional[str] = None, part: Optional[str] = None) -> list:
    """Render the model in `view` and return it side by side with the reference image
    (left = reference, right = model). Pick the view that matches the photo/drawing
    (front/top/right for orthographic drawings). Then list concrete differences and fix them."""
    ref = vision.load(reference_path)
    r = _call("get_view", view=view, width=1024, height=768, doc=document, hide_references=True,
              part=part)
    from PIL import Image as PILImage
    model = PILImage.open(io.BytesIO(base64.b64decode(r["png_b64"]))).convert("RGB")
    combo = vision.side_by_side(ref, model, ("reference", "model: %s" % view))
    png = vision.to_png(combo, 1600)
    out_path = os.path.splitext(r["path"])[0] + "_compare.png"
    try:
        with open(out_path, "wb") as f:
            f.write(png)
    except OSError:
        out_path = None
    return ["left: reference, right: model (%s view)\ncomparison image file (open it with your "
            "image tool if you cannot see the picture, and list concrete differences): %s"
            % (view, out_path), Image(data=png, format="png")]


# ------------------------------------------------------------------- output

@mcp.tool()
def export_model(path: str, format: Optional[str] = None, part: Optional[str] = None,
                 document: Optional[str] = None, linear_deflection: float = 0.05) -> str:
    """Export to STL (3D printing) or STEP/IGES/BREP. path: absolute path or bare file name
    (goes to the HermesCAD exports folder). part: required when the document has several
    parts; part='all' merges every part into one file.
    linear_deflection: STL accuracy in mm (smaller = finer)."""
    return _j(_call("export", path=path, format=format, part=part, doc=document,
                    linear_deflection=linear_deflection))


@mcp.tool()
def execute_freecad_code(code: str, document: Optional[str] = None) -> str:
    """Escape hatch: run Python inside FreeCAD (App, Gui, doc are predefined; assign `result`
    to return a value; print() output is returned). Use only when build_part cannot express
    the geometry (lofts, sweeps, threads, assemblies). Can be disabled in HermesCAD settings."""
    return _j(_call("execute_code", code=code, doc=document))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
