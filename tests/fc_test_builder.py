# Run:  freecadcmd -c "exec(open('tests/fc_test_builder.py').read())"   (cwd = repo root)
import json, os, sys, tempfile
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
import FreeCAD as App
from hermescad_core import builder as B

fails = []
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: fails.append(msg)

doc = App.newDocument("T")
spec = json.load(open(os.path.join(ROOT, "examples", "plate_with_holes.json")))
r = B.build_part(doc, spec)
print(json.dumps({k: r[k] for k in ("volume_mm3", "bbox_mm", "warnings")}))
import math
exp = 80*50*6 - 4*math.pi*(6.5/2)**2*6 - (20*10 + math.pi*25)*6
check(r["bbox_mm"]["size"] == [80, 50, 6], "plate bbox 80x50x6")
check(abs(r["volume_mm3"] - (exp - 4*(4*4 - math.pi*16/4)*6)) < 1.0, "plate volume incl. fillets %.1f" % r["volume_mm3"])

r2 = B.set_parameters(doc, "MountPlate", {"L": 120, "R": 6})
check(r2["mode"].startswith("updated"), "L change goes through spreadsheet: " + r2["mode"])
check(r2["bbox_mm"]["size"][0] == 120, "L=120 applied")
check("invalid_objects" not in r2, "all features valid after change")
r3 = B.set_parameters(doc, "MountPlate", {"T": 10})
check(r3["bbox_mm"]["size"][2] == 10, "T=10 applied (pad + hole offset)")

f = json.load(open(os.path.join(ROOT, "examples", "flange_revolve.json")))
rf = B.build_part(doc, f)
print(json.dumps({k: rf[k] for k in ("volume_mm3", "bbox_mm", "baked_parameters")}))
check(rf["bbox_mm"]["size"][2] == 32, "flange height 32")
check(abs(rf["bbox_mm"]["size"][0] - 100) < 0.01, "flange D 100")
rf2 = B.set_parameters(doc, "Flange", {"D": 120, "pcd": 90})
check(rf2["mode"].startswith("rebuilt"), "baked change triggers rebuild")
check(abs(rf2["bbox_mm"]["size"][0] - 120) < 0.01, "flange D 120")
check(len(B.list_parts(doc)) == 2, "two parts in doc: %s" % B.list_parts(doc))

# error reporting
try:
    B.build_part(doc, {"name": "Bad", "parameters": {"a": 5}, "features": [
        {"type": "pad", "profile": {"type": "rect", "w": "a", "h": "b"}, "length": 3}]})
    check(False, "unknown param should fail")
except B.BuildError as e:
    check("unknown parameter" in str(e), "clear error: %s" % e)
try:
    B.build_part(doc, {"name": "Bad2", "features": [{"type": "fillet", "radius": 1}]})
    check(False, "fillet on empty should fail")
except B.BuildError as e:
    check(True, "clear error: %s" % e)

# reserved / cell-like names
rr = B.build_part(doc, {"name": "Cyl", "parameters": {"D1": 20, "h": 15},
    "features": [{"type": "pad", "profile": {"type": "circle", "d": "D1"}, "length": "h"}]})
check(abs(rr["volume_mm3"] - math.pi*100*15) < 0.5, "cell-like alias D1 works")
B.set_parameters(doc, "Cyl", {"D1": 30})
check(abs(B.part_summary(doc, B.find_body(doc, "Cyl"))["volume_mm3"] - math.pi*225*15) < 0.5, "D1 update")

out = os.path.join(tempfile.gettempdir(), "hc_test.FCStd")
doc.saveAs(out)
check(os.path.getsize(out) > 1000, "saved FCStd")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
