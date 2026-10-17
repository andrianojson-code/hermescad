import json, math, os, sys
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
import FreeCAD as App
from hermescad_core import builder as B
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)
doc = App.newDocument("R")

# XZ offset direction (spec says normal = -Y)
r = B.build_part(doc, {"name": "XZoff", "features": [
    {"type": "pad", "plane": "XZ", "offset": 10, "profile": {"type": "rect", "w": 4, "h": 4}, "length": 2}]})
print("XZ offset bbox y:", r["bbox_mm"]["y"])
# YZ
r2 = B.build_part(doc, {"name": "YZoff", "features": [
    {"type": "pad", "plane": "YZ", "offset": 10, "profile": {"type": "rect", "w": 4, "h": 2, "x": 5}, "length": 2}]})
print("YZ bbox:", r2["bbox_mm"])

# L-bracket from polygon on XZ, symmetric width
L = B.build_part(doc, {"name": "LBracket", "parameters": {"A": 40, "Bh": 30, "t": 5, "w": 25},
    "features": [
     {"id": "body", "type": "pad", "plane": "XZ", "symmetric": True, "length": "w",
      "profile": {"type": "polygon", "points": [[0,0],["A",0],["A","t"],["t","t"],["t","Bh"],[0,"Bh"]]}},
     {"id": "hole", "type": "hole", "plane": "XY", "offset": "t", "profile": {"type": "circle", "d": 6, "x": "A*0.65"}},
     {"id": "inner", "type": "fillet", "edges": ["parallel_y", "!outer"], "radius": 3}]})
print("L:", L["bbox_mm"]["size"], L["volume_mm3"])
check(L["bbox_mm"]["size"] == [40, 25, 30], "L bracket bbox")
check(abs(L["bbox_mm"]["y"][0] + 12.5) < 1e-6, "symmetric about XZ")
vol_noF = (40*5 + 5*25)*25 - math.pi*9*5
check(L["volume_mm3"] > vol_noF, "inner fillet adds material (%.1f > %.1f)" % (L["volume_mm3"], vol_noF))

# counterbore
cb = B.build_part(doc, {"name": "CB", "parameters": {"T": 10}, "features": [
    {"type": "pad", "profile": {"type": "rect", "w": 30, "h": 30}, "length": "T"},
    {"type": "hole", "offset": "T", "profile": {"type": "circle", "d": 6.6}},
    {"id": "cbore", "type": "pocket", "offset": "T", "profile": {"type": "circle", "d": 11}, "depth": 6.5}]})
exp = 30*30*10 - math.pi*3.3**2*3.5 - math.pi*5.5**2*6.5
check(abs(cb["volume_mm3"] - exp) < 0.5, "counterbore volume %.1f vs %.1f" % (cb["volume_mm3"], exp))

# hex nut
nut = B.build_part(doc, {"name": "Nut", "parameters": {"s": 13, "m": 6.5, "d": 8}, "features": [
    {"type": "pad", "profile": {"type": "regular_polygon", "n": 6, "across_flats": "s"}, "length": "m"},
    {"type": "hole", "offset": "m", "profile": {"type": "circle", "d": "d"}},
    {"type": "chamfer", "edges": ["top", "!circular"], "size": 0.8}]})
check(abs(nut["bbox_mm"]["size"][1] - 13) < 0.01 or abs(nut["bbox_mm"]["size"][0] - 13) < 0.01, "nut across flats 13: %s" % nut["bbox_mm"]["size"])

# shaft with groove
sh = B.build_part(doc, {"name": "Shaft", "parameters": {"D": 20, "Lg": 60}, "features": [
    {"type": "revolve", "profile": {"type": "rect", "w": "D/2", "h": "Lg", "x": "D/4", "y": "Lg/2"}},
    {"type": "groove", "profile": {"type": "rect", "w": 1.5, "h": 2, "x": "D/2-0.5", "y": 40}},
    {"type": "chamfer", "edges": ["top", "circular"], "size": 1}]})
check(abs(sh["bbox_mm"]["size"][2] - 60) < 1e-6 and abs(sh["bbox_mm"]["size"][0] - 20) < 1e-6, "shaft bbox %s" % sh["bbox_mm"]["size"])
check(sh["volume_mm3"] < math.pi*100*60, "groove + chamfer removed material")
B.set_parameters(doc, "Shaft", {"D": 24})
check(abs(B.part_summary(doc, B.find_body(doc, "Shaft"))["bbox_mm"]["size"][0] - 24) < 1e-6, "shaft D live 24")

# pocket one-way through_all from top
p1 = B.build_part(doc, {"name": "OneWay", "features": [
    {"type": "pad", "profile": {"type": "rect", "w": 20, "h": 20}, "length": 10},
    {"type": "pocket", "offset": 10, "through_all": True, "symmetric": False, "profile": {"type": "circle", "d": 5}}]})
check(abs(p1["volume_mm3"] - (4000 - math.pi*6.25*10)) < 0.5, "one-way through_all from top")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
