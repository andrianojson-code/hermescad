# Smooth lofted bodies, artifact-free renders, and exporting assemblies

FreeCAD specifics the JSON spec cannot express: lofted organic bodies (car bodies, housings,
handles), the display artifacts that make them look broken, and what to do when `export_model`
refuses a document it did not build.

## Sections: periodic splines, not polygons

```python
import Part, math
V = App.Vector

def sect(x, hw, zbot, ztop, seg=36, n=2.8, narrow=0.0, belt=1015.0):
    b = (ztop - zbot) / 2.0; zc = (ztop + zbot) / 2.0; pts = []
    for i in range(seg):
        th = 2 * math.pi * i / seg
        c, s = math.cos(th), math.sin(th)
        y = math.copysign(abs(c) ** (2.0 / n), c)   # superellipse: flatter floor and roof
        z = math.copysign(abs(s) ** (2.0 / n), s)
        zz = zc + b * z
        k = 1.0
        if zz > belt and ztop > belt:               # tumblehome: narrower above the beltline
            k = 1.0 - narrow * ((zz - belt) / (ztop - belt))
        pts.append(V(x, hw * y * k, zz))
    bs = Part.BSplineCurve()
    bs.interpolate(Points=pts, PeriodicFlag=True)
    return bs.toShape()

body = Part.makeLoft([sect(x, halfw(x), 500, ztop(x)) for x in stations], solid=True)
```

- Polygon sections (`Part.makePolygon`) loft into hundreds of facets: the viewport draws every
  seam in black and the body reads as "striped / wavy / broken". A periodic BSpline section gives
  one smooth surface — sanity check `len(body.Faces)` BEFORE judging appearance (a whole car body
  comes out at ~8 faces; hundreds of faces means you lofted polygon sections).
- `Part.BSplineCurve` has no `setClosed()` in FreeCAD 1.1; close it with
  `interpolate(Points=pts, PeriodicFlag=True)`.
- Vary the half-width along the length (plan taper) and shrink width above the beltline
  (tumblehome). Without both, any lofted vehicle reads as an extruded slab.
- Cut wheel arches with a cylinder along the width axis
  (`Part.makeCylinder(r, 3*W, V(x, -1.5*W, axle_z), V(0, 1, 0))`) after the loft, not with pockets.

## Coplanar faces tear the render

- Never leave a decorative solid exactly on the body surface (glass canopy, panel, trim):
  coplanar faces render as black/torn stripes and look like broken geometry. Offset it outward
  by ~3 mm.
- `Shape.scale(...)` does not take the signature you expect, and `makeOffsetShape` fails on
  BSpline surfaces (`Geom_BSplineSurface: Weights values too small`). Scale with a matrix about a
  fixed centre instead:

```python
m = App.Matrix(); m.A11 = 1.0; m.A22 = 1.008; m.A33 = 1.004
m.A14 = c.x - 1.0 * c.x; m.A34 = c.z - 1.004 * c.z     # keep centre c fixed
obj.Shape = obj.Shape.transformGeometry(m)
```

## Views for parts lying along X

- A body built along X shows its side profile in the `front` view; `right` / `left` show the END
  faces. Do not judge a silhouette (or claim a match) from `right` on an X-aligned part.
- `get_view` / `compare_with_reference` may answer with only `view=<name>`; the PNG is still on
  disk as the newest file in `<work_dir>/views/`.

## Export when `export_model` says "nothing to export"

`export_model` walks PartDesign bodies. A document made of `Part::Feature` objects (lofted body +
wheels + rims) returns `ValueError: nothing to export`, and `Mesh.export` on bare shapes fails too
("None of the objects can be exported"). Export headless with the FreeCAD CLI, which works on a
plain compound:

```
'/c/Program Files/FreeCAD 1.1/bin/freecadcmd.exe' 'C:\Users\<u>\AppData\Local\Temp\export_stl.py'
```

```python
import FreeCAD, Part, MeshPart, os
doc = FreeCAD.openDocument(r"...\exports\<Model>.FCStd")
comp = Part.makeCompound([o.Shape for o in doc.Objects if hasattr(o, "Shape")])
mesh = MeshPart.meshFromShape(Shape=comp, LinearDeflection=0.2, AngularDeflection=0.25)
mesh.write(r"...\exports\<Model>.stl")
print(mesh.CountFacets, mesh.BoundBox)
```

Report it honestly: a compound of several bodies is `isSolid: False` / `selfIntersections: True`
as a mesh, because it is 9 separate solids. Say "assembly of N bodies, not one watertight mesh"
instead of claiming print-readiness.

## Stylized multi-view art with no dimensions

A product/car illustration (several views, checkerboard = transparent background) carries no
scale. Derive proportions from ONE view as fractions of overall length (roof height, wheelbase,
wheel diameter, overhangs), pick a plausible overall length, and state that assumption.

`extract_contours` can time out on a 400-px illustration; do not resubmit it — measure in Python:
mask = white body OR dark lines OR a saturated colour. The checkerboard is mid-grey (~160/190),
so a plain dark threshold returns the whole background; white-on-grey needs the bright side too.
Then print a coarse ASCII silhouette (2-px cells, dark-pixel count per cell) to read the shape,
and take column-wise top/bottom profiles for the outline.

Convert: `X_mm = (px - x_nose) * mm_per_px`, `Z_mm = (y_ground - py) * mm_per_px`. Pixel top
contours of a shaded illustration are noisy at the nose/tail — snap to a sane car-like profile
(hood below roof, raked windshield, hatch rear) and say which numbers are estimates rather than
copying every wobble.
