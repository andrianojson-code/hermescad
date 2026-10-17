import json, math, os, sys
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
import FreeCAD as App
from hermescad_core import builder as B
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)
doc = App.newDocument("S")
# path with line + arc + spline, padded
r = B.build_part(doc, {"name": "Lever", "parameters": {"t": 8},
    "features": [{"type": "pad", "plane": "XZ", "symmetric": True, "length": "t",
      "profile": {"type": "path", "start": [0, 0], "segments": [
         {"line": [30, 0]}, {"line": [30, 10]},
         {"spline": [[22, 18], [18, 32], [24, 46]]},
         {"arc": {"through": [12, 54], "to": [2, 44]}},
         {"line": [0, 10]}]}}]})
check(r["valid"] and r["solids"] == 1, "path (line+spline+arc) pads: bbox %s" % r["bbox_mm"]["size"])
# closed spline
pts = [[20*math.cos(a), 12*math.sin(a)] for a in [i*2*math.pi/12 for i in range(12)]]
r = B.build_part(doc, {"name": "Blob", "features": [{"type": "pad", "profile": {"type": "spline", "points": pts}, "length": 5}]})
check(r["valid"] and abs(r["volume_mm3"] - math.pi*20*12*5) / (math.pi*20*12*5) < 0.02, "closed spline ~ ellipse vol %.0f" % r["volume_mm3"])
# taper
r = B.build_part(doc, {"name": "Taper", "features": [{"type": "pad", "profile": {"type": "rect", "w": 20, "h": 20}, "length": 10, "taper": 10}]})
top = r["bbox_mm"]
check(r["valid"] and r["volume_mm3"] < 4000, "taper narrows: vol %.0f < 4000" % r["volume_mm3"])
# tilted plane cut
r = B.build_part(doc, {"name": "Tilt", "features": [
    {"type": "pad", "profile": {"type": "rect", "w": 30, "h": 30}, "length": 20},
    {"type": "pocket", "plane": "XZ", "tilt": {"axis": "x", "angle": 30}, "through_all": True,
     "profile": {"type": "rect", "w": 40, "h": 20, "y": 25}}]})
check(r["valid"] and r["volume_mm3"] < 18000, "tilted pocket cuts: vol %.0f" % r["volume_mm3"])
# hole check still fires for a path-based body
try:
    B.build_part(doc, {"name": "BadHole", "features": [
        {"type": "pad", "plane": "XZ", "symmetric": True, "length": 6, "profile": {"type": "rect", "w": 30, "h": 30, "y": 15}},
        {"type": "hole", "plane": "YZ", "profile": {"type": "circle", "d": 9, "x": 0, "y": 15}}]})
    check(False, "groove hole must fail")
except B.BuildError as e:
    check("did not make a round hole" in str(e), "hole check still works")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))

# --- trim (visual hull) from the car silhouettes
import json as _j
o = _j.load(open(os.path.join(ROOT, "tests", "data", "car_outlines.json")))
r = B.build_part(doc, {"name": "CarHull", "expect_bbox": [round(o["L"]), round(o["Wd"]), 1490], "features": [
    {"type": "pad", "plane": "XZ", "symmetric": True, "length": round(o["Wd"] * 1.2, 1), "profile": o["side"]},
    {"id": "rear_trim", "type": "trim", "plane": "YZ", "profile": o["rear"]}]})
check(r["valid"] and r["matches_expected_bbox"], "car visual hull: %s warnings=%s" % (r["bbox_mm"]["size"], r["warnings"]))
check(len(B.list_parts(doc)) == len(set(B.list_parts(doc))), "trim tool body not listed as part")
B.remove_part(doc, "CarHull")
check(not [x for x in doc.Objects if "CarHull" in x.Name], "trim tool removed with part")
print("RESULT2:", "OK" if not fails else "FAILED %d" % len(fails))
