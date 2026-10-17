"""expect_bbox warning, STL mesh_check, close_document. Needs headless bridge on :9876."""
import json, re, html, zipfile, sys, xmlrpc.client
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)
p = xmlrpc.client.ServerProxy("http://127.0.0.1:9876/RPC2")
def c(m, **k): return json.loads(p.call("", m, json.dumps(k)))
c("new_document", name="Checks")
spec = {"name": "Stack", "parameters": {"base_t": 16, "wall_h": 33},
        "expect_bbox": [40, 32, 33],
        "features": [{"type": "pad", "profile": {"type": "rect", "w": 40, "h": 32, "x": 20}, "length": "base_t"},
                     {"type": "pad", "plane": "XY", "offset": "base_t", "profile": {"type": "rect", "w": 25, "h": 32, "x": 12.5}, "length": "wall_h"}]}
r = c("build_part", spec=spec)["result"]
check(r["matches_expected_bbox"] is False and any("overall Z is 49" in w for w in r["warnings"]), "stacking error flagged: %s" % r["warnings"][:1])
spec["parameters"]["wall_h"] = "33-base_t"
r = c("build_part", spec=spec)["result"]
check(r["matches_expected_bbox"] is True and not r["warnings"], "fixed stacking passes")
r = c("export", path="/tmp/checks.stl", part="Stack")["result"]
check(r["print_ready"] and r["mesh_check"]["watertight"], "STL mesh_check: %s" % r["mesh_check"])
r = c("close_document", doc="Checks")
check(r["ok"] and "Checks" not in r["result"]["documents"], "close_document")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))

# --- photo silhouette (pure MCP-side, no FreeCAD needed)
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_server"))
from hermescad_mcp import vision
d, _ = vision.extract_contours(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lever_photo.png"),
                               as_spline=True, spline_points=28, ref_length_mm=40, ref_axis="height")
check(d["mode"] == "photo silhouette" and d["outline"]["type"] == "spline" and len(d["outline"]["points"]) == 28,
      "photo -> spline outline (%s, %s)" % (d["mode"], d["outline_bbox"]))
print("RESULT2:", "OK" if not fails else "FAILED %d" % len(fails))
