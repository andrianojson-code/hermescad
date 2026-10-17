"""Run: python tests/bpy_test_service.py  (needs `pip install bpy==5.2.*`)"""
import os, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "blender_addon"))
import bpy
from hermes3d import service as S
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: fails.append(m)
tmp = tempfile.mkdtemp()
# make a test GLB: Suzanne (open boundaries, separate eyes) + a child cube under an empty
S.clear_scene()
bpy.ops.mesh.primitive_monkey_add(size=2)
bpy.ops.object.empty_add(location=(3, 0, 0)); e = bpy.context.object
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0, 0, 0)); c = bpy.context.object; c.parent = e
glb = os.path.join(tmp, "test.glb")
bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB")
S.clear_scene()
r = S.dispatch("import_model", {"path": glb, "name": "Gen"})
check(r["ok"] and r["result"]["name"] == "Gen" and S._models() == ["Gen"], "import merges into one object: %s" % S._models())
st = r["result"]; print("  imported:", {k: st[k] for k in ("faces", "dimensions_mm", "watertight", "loose_parts")})
check(not st["watertight"], "suzanne reported NOT watertight")
r = S.dispatch("normalize", {"name": "Gen", "size_mm": 120, "axis": "max"})["result"]
check(abs(max(r["dimensions_mm"]) - 120) < 0.01 and abs(r["bbox_min"][2]) < 1e-6, "normalize: max dim 120, on ground: %s" % r["dimensions_mm"])
r = S.dispatch("cleanup", {"name": "Gen", "mode": "print", "resolution": 128, "target_faces": 20000})
res = r["result"]; print("  after cleanup:", {k: res["after"][k] for k in ("faces", "watertight", "loose_parts", "volume_mm3")})
check(r["ok"] and res["print_ready"] and res["after"]["faces"] <= 20000 * 1.3, "cleanup print -> watertight single part")
check(res["removed_small_parts"] == 1, "tiny separate cube reported as removed junk")
out = S.dispatch("export_model", {"path": os.path.join(tmp, "out.stl"), "name": "Gen"})
check(out["ok"] and out["result"]["bytes"] > 10000, "STL export %s bytes" % out.get("result", {}).get("bytes"))
out = S.dispatch("export_model", {"path": os.path.join(tmp, "out.glb"), "name": "Gen"})
check(out["ok"], "GLB export")
r = S.dispatch("import_model", {"path": os.path.join(tmp, "out.stl"), "name": "Back"})
check(r["ok"] and abs(max(r["result"]["dimensions_mm"]) - max(res["after"]["dimensions_mm"])) < 0.5, "STL re-import keeps mm size: %s" % r["result"]["dimensions_mm"])
r = S.dispatch("render_view", {"view": "isometric", "name": "Gen", "width": 400, "height": 300})
print("  render:", r["ok"], (r.get("result") or {}).get("path") or r.get("error", "")[:300])
r = S.dispatch("execute_code", {"code": "result = len(bpy.data.objects)"})
check(r["ok"], "execute_code")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
