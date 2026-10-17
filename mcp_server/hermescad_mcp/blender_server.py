"""Hermes3D MCP server: image -> 3D mesh (cloud generator) -> Blender (clean, scale, export).

Run:  python -m hermescad_mcp.blender     (stdio, what Hermes launches)
Env:  HERMES3D_HOST / HERMES3D_PORT (9877) / HERMES3D_TOKEN, HF_TOKEN, TRIPO_API_KEY, HERMES3D_OUT
"""
import base64
import io
import json
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP, Image

from . import gen3d, vision
from .client import Bridge, BridgeError

mcp = FastMCP(
    "hermes3d",
    instructions=(
        "Turn a screenshot/photo of an object into a 3D model in Blender. Do NOT model by hand: "
        "(1) prepare_image (cut the object out, one view), (2) generate_3d (cloud image->3D), "
        "(3) normalize to the real size, (4) render_view / compare_with_reference to check, "
        "(5) cleanup(mode='print') for 3D printing, (6) export_model (stl/glb/obj/fbx). "
        "Hand edits only with execute_blender_code for small fixes."),
)
bridge = Bridge(host=os.environ.get("HERMES3D_HOST", "127.0.0.1"),
                port=int(os.environ.get("HERMES3D_PORT", "9877")),
                token=os.environ.get("HERMES3D_TOKEN", ""), timeout=900)


def _j(o):
    return json.dumps(o, ensure_ascii=False, indent=1)


def _call(method, **kw):
    try:
        return bridge.call(method, **kw)
    except BridgeError as exc:
        msg = str(exc).replace("Open FreeCAD, switch to the HermesCAD workbench and press "
                               "'Start Hermes bridge' (or enable autostart).",
                               "Open Blender (the Hermes3D add-on starts the bridge automatically).")
        raise RuntimeError(msg)


def _shot(view="isometric", name=None):
    try:
        r = bridge.call("render_view", view=view, name=name, width=800, height=600)
        return Image(data=base64.b64decode(r["png_b64"]), format="png"), r["path"]
    except BridgeError:
        return None, None


@mcp.tool()
def blender_status() -> str:
    """Check the Blender connection: version, GPU, models in the scene, work folder."""
    return _j(_call("status"))


@mcp.tool()
def prepare_image(image_path: str, crop: Optional[list[int]] = None) -> list:
    """Cut the object out of its background (plain, busy or checkerboard) into a square RGBA PNG -
    the best input for generate_3d. crop=[x0,y0,x1,y1] px selects ONE view of a multi-view
    picture (use the most informative 3/4 or side view). Returns the new file path + preview."""
    from . import vision_cli
    out = os.path.splitext(image_path)[0] + "_cutout.png"
    info = vision_cli.run("cutout", out, path=image_path, crop=crop)
    from PIL import Image as PILImage
    img = PILImage.open(out)
    prev = io.BytesIO()
    bg = PILImage.new("RGB", img.size, "white")
    bg.paste(img, mask=img.split()[3])
    bg.thumbnail((512, 512))
    bg.save(prev, "PNG")
    return [_j(info), Image(data=prev.getvalue(), format="png")]


@mcp.tool()
def generate_3d(image_path: str, backend: str = "auto", name: str = "Model",
                import_into_blender: bool = True, faces: int = 100000) -> list:
    """Generate a 3D mesh from ONE image (ideally the prepare_image cutout) with a cloud model,
    then import it into Blender as one object `name`.
    backend: auto (Hunyuan3D-2.1 free Space -> Hunyuan3D-2 -> TripoSG; tripo if TRIPO_API_KEY) |
    hf:hunyuan3d | hf:triposg | tripo (credits, textured) | hf:<owner/space> (any HF Space).
    Takes ~30 s - 3 min. The mesh is shape-only (white) for the free Spaces. Returns the mesh file, Blender stats and a render."""
    path, used = gen3d.generate(image_path, backend=backend, name=name, faces=faces)
    out = {"mesh_file": path, "backend": used}
    if not import_into_blender:
        return [_j(out)]
    st = _call("import_model", path=path, name=name)
    out["blender"] = st
    img, p = _shot("isometric", name)
    if p:
        out["render_path"] = p
    return [_j(out)] + ([img] if img else [])


@mcp.tool()
def hf_space_api(space: str) -> str:
    """Show the callable endpoints of a Hugging Face Space (to use another generator with
    generate_3d(backend='hf:<space>'))."""
    return _j(gen3d.space_api(space))


@mcp.tool()
def import_model(path: str, name: str = "Model") -> list:
    """Import a mesh file (glb/gltf/obj/stl/ply/fbx) as one object - e.g. a model the user
    generated on a website (Meshy, Tripo, Rodin, Hunyuan3D...)."""
    st = _call("import_model", path=path, name=name)
    img, p = _shot("isometric", name)
    if p:
        st["render_path"] = p
    return [_j(st)] + ([img] if img else [])


@mcp.tool()
def normalize(name: Optional[str] = None, size_mm: Optional[float] = None, axis: str = "max",
              up: str = "z", rotate_deg: Optional[list[float]] = None) -> list:
    """Scale the model uniformly so `axis` (x|y|z|max) is size_mm, fix orientation (up: the
    model's current up axis z|y|-y|x|-x|-z; rotate_deg=[x,y,z] extra rotation), centre it and put it
    on the ground. Generators output arbitrary scale - always call this with a real dimension."""
    st = _call("normalize", name=name, size_mm=size_mm, axis=axis, up=up, rotate_deg=rotate_deg)
    img, p = _shot("isometric", name)
    if p:
        st["render_path"] = p
    return [_j(st)] + ([img] if img else [])


@mcp.tool()
def symmetrize(name: Optional[str] = None, axis: str = "x") -> str:
    """Make the model exactly mirror-symmetric about the given axis (cars, vases, toys...)."""
    return _j(_call("mirror_symmetrize", name=name, axis=axis))


@mcp.tool()
def cleanup(name: Optional[str] = None, mode: str = "print", resolution: int = 256,
            target_faces: int = 150000, keep_largest: bool = True, smooth: int = 0) -> str:
    """Repair the generated mesh. mode='print': voxel remesh -> watertight, manifold, single
    part (resolution 128..512 = detail), then decimate to target_faces. mode='light': only merge
    duplicates, fix normals, drop tiny junk parts, decimate (keeps the original surface/UVs
    better, for visualisation). Returns before/after stats and print_ready."""
    return _j(_call("cleanup", name=name, mode=mode, resolution=resolution,
                    target_faces=target_faces, keep_largest=keep_largest, smooth=smooth))


@mcp.tool()
def mesh_stats(name: Optional[str] = None) -> str:
    """Dimensions (mm), faces, watertight / non-manifold edges, loose parts, volume."""
    return _j(_call("mesh_stats", name=name))


@mcp.tool()
def list_models() -> str:
    """Models (mesh objects) in the Blender scene with their stats."""
    return _j(_call("list_models"))


@mcp.tool()
def clear_scene() -> str:
    """Delete everything in the scene (start a new job)."""
    return _j(_call("clear_scene"))


@mcp.tool()
def render_view(view: str = "isometric", name: Optional[str] = None) -> list:
    """Render the model: isometric, three_quarter, front, back, left, right, top, bottom.
    Returns the picture and its file path (open the path with your image tool if you cannot see
    images)."""
    r = _call("render_view", view=view, name=name, width=1000, height=750)
    return ["view=%s image file: %s" % (view, r["path"]),
            Image(data=base64.b64decode(r["png_b64"]), format="png")]


@mcp.tool()
def compare_with_reference(reference_path: str, view: str = "three_quarter",
                           name: Optional[str] = None) -> list:
    """Render the model and put it next to the reference picture (left = reference). Use the
    view that matches the reference. Returns the composite and its file path."""
    from PIL import Image as PILImage
    r = _call("render_view", view=view, name=name, width=1000, height=750)
    model = PILImage.open(io.BytesIO(base64.b64decode(r["png_b64"]))).convert("RGB")
    combo = vision.side_by_side(vision.load(reference_path), model, ("reference", "model: %s" % view))
    png = vision.to_png(combo, 1600)
    out = os.path.splitext(r["path"])[0] + "_compare.png"
    with open(out, "wb") as f:
        f.write(png)
    return ["left: reference, right: model (%s). comparison image file: %s" % (view, out),
            Image(data=png, format="png")]


@mcp.tool()
def export_model(path: str, name: Optional[str] = None, format: Optional[str] = None) -> str:
    """Export the model: stl (print), glb/gltf (web/games, keeps textures), obj, ply, fbx, blend.
    path: absolute, or a bare file name (goes to the Hermes3D exports folder)."""
    return _j(_call("export_model", path=path, name=name, format=format))


@mcp.tool()
def save_blend(path: Optional[str] = None) -> str:
    """Save the Blender scene as .blend."""
    return _j(_call("save_blend", path=path))


@mcp.tool()
def execute_blender_code(code: str) -> str:
    """Escape hatch: run Python in Blender (bpy, bmesh predefined; set `result`). Use for small
    edits only (delete a part, add a base, boolean a hole). Can be disabled in add-on prefs."""
    return _j(_call("execute_code", code=code))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
