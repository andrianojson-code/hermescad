import json, os, sys
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
import FreeCAD as App
from hermescad_core import builder as B
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)
doc = App.newDocument("H")
hermes_spec = {"name": "L_mount_bracket", "parameters": {"width": 40.0, "hole_d": 6.5, "base_t": 4.0, "base_hole_x": 20.0, "base_hole_y": 0.0, "wall_hole_x": 4.0, "wall_hole_z": 20.0, "inside_r": 2.0},
 "features": [{"id": "bracket_profile", "type": "pad", "plane": "XZ", "symmetric": True, "length": "width", "profile": {"type": "polygon", "points": [[0, 0], [33, 0], [33, 4], [4, 4], [4, 32], [0, 32]]}},
  {"id": "base_hole", "type": "hole", "plane": "XY", "offset": "base_t", "profile": {"type": "circle", "d": "hole_d", "x": "base_hole_x", "y": "base_hole_y"}, "through_all": True},
  {"id": "wall_hole", "type": "hole", "plane": "XZ", "offset": 0, "profile": {"type": "circle", "d": "hole_d", "x": "wall_hole_x", "y": "wall_hole_z"}, "through_all": True}]}
try:
    B.build_part(doc, hermes_spec)
    check(False, "Hermes' groove-hole must be rejected")
except B.BuildError as e:
    print("   ->", e)
    check("wall_hole" in str(e) and "YZ" in str(e), "groove detected, YZ suggested")
fixed = json.loads(json.dumps(hermes_spec)); fixed["features"][2]["plane"] = "YZ"; fixed["features"][2]["profile"]["x"] = 0
r = B.build_part(doc, fixed)
check(r["valid"], "same bracket with YZ wall hole builds")
r = B.build_part(doc, json.load(open(os.path.join(ROOT, "examples", "l_bracket_tab.json"))))
print(json.dumps({k: r[k] for k in ("bbox_mm", "volume_mm3", "warnings")}))
check(r["bbox_mm"]["size"] == [40, 25, 33], "tab bracket bbox 40x25x33")
B.set_parameters(doc, "L_Bracket_Tab", {"height": 40, "tab_hole_d": 14})
check(B.part_summary(doc, B.find_body(doc, "L_Bracket_Tab"))["bbox_mm"]["size"][2] == 40, "height edit")
doc.saveAs("/tmp/claude-0/-home-claude/efabe239-2b25-56ea-84b2-a55111a8b82f/scratchpad/tab.FCStd")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
