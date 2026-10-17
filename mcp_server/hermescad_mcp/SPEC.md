# HermesCAD part spec (v0.1)

A part is a JSON object. Units are millimetres and degrees.

```json
{
  "name": "MountPlate",
  "parameters": {"L": 80, "W": 50, "T": 6, "hole_d": 6.5, "margin": 8},
  "features": [
    {"id": "base", "type": "pad", "plane": "XY",
     "profile": {"type": "rect", "w": "L", "h": "W"}, "length": "T"},
    {"id": "holes", "type": "hole", "plane": "XY", "offset": "T",
     "profile": {"type": "grid", "nx": 2, "ny": 2, "dx": "L-2*margin", "dy": "W-2*margin", "d": "hole_d"}},
    {"id": "corners", "type": "fillet", "edges": "vertical", "radius": 4}
  ]
}
```

## Overall size check (always use it with drawings)
Add `"expect_bbox": [X, Y, Z]` with the drawing's OVERALL dimensions (null for unknown axes).
`build_part` then warns `overall Z is 49 mm but expect_bbox says 33 mm`. Drawing dimensions are
measured over the whole part from its outer faces: a total height of 33 with a 16 mm base means
the upright adds 17, not 33. Hole heights are from the bottom face unless the drawing says otherwise.

## Values
Any number can be a literal (`12.5`) or an expression string using parameters:
`"L/2 - margin"`, `"sqrt(W^2 + T^2)"`, `"D*cos(30)"`.
Operators: `+ - * / ^ %`. Functions: sin cos tan asin acos atan atan2 (DEGREES), sqrt abs min max round floor ceil hypot. Constants: pi, e.
A parameter value may itself use parameters defined before it: `{"L": 80, "half": "L/2"}`.

**Always put every important dimension into `parameters`.** That way the user can say "make it 10 mm longer" and you only change one number with `set_parameters`.

## Planes and sketch placement
`plane`: `XY` (top view, sketch x→X, y→Y), `XZ` (front view, sketch x→X, y→Z), `YZ` (right view, sketch x→Y, y→Z).
`offset`: distance of the sketch along the plane normal (XY: +Z, XZ: −Y, YZ: +X). Put pockets/holes on the face you cut from, e.g. `"offset": "T"` for the top of a plate of thickness T.
A feature takes either `profile` (one shape) or `profiles` (list). Several closed shapes in one sketch: nested shapes become holes in a pad; separate shapes give separate islands.

## Orientation: which plane for which face (read this before any hole)
A sketch extrudes / drills ALONG the plane normal:  `XY` → along Z,  `XZ` → along Y,  `YZ` → along X.
So sketch every hole on the plane PARALLEL to the face it goes through:

| Face being drilled | Its normal | Sketch plane | Profile x, y mean |
|---|---|---|---|
| horizontal (top of a plate/base) | Z | `XY` | X, Y |
| vertical wall facing front/back | Y | `XZ` | X, Z |
| vertical wall facing left/right | X | `YZ` | Y, Z |

Before writing the spec, write one line per wall: "upright: thin along X → its holes on YZ".
`build_part` REJECTS a `hole` that does not produce a full round hole (e.g. a groove cut along a
wall because the plane was wrong) and tells you which plane to use.

Worked example — L-bracket with an upright tab (rounded top, hole) and a base with a hole:
upright = pad of a rect on `YZ` (w = depth along Y, h = height along Z, `y: "height/2"`), length = tab
thickness along +X; base = pad of a rect on `XY` placed beside it; tab hole on `YZ` (`x` = Y position,
`y` = Z height); base hole on `XY` at `offset: base_t`; rounded tab top = fillet `["top","parallel_x"]`.
```json
{
 "name": "L_Bracket_Tab",
 "parameters": {
  "length": 40,
  "depth": 25,
  "height": 33,
  "upright_t": 10,
  "base_t": 8,
  "tab_hole_d": 10,
  "tab_hole_z": 20,
  "base_hole_d": 9,
  "top_r": 12,
  "inner_r": 3
 },
 "features": [
  {
   "id": "upright",
   "type": "pad",
   "plane": "YZ",
   "profile": {
    "type": "rect",
    "w": "depth",
    "h": "height",
    "x": 0,
    "y": "height/2"
   },
   "length": "upright_t"
  },
  {
   "id": "base",
   "type": "pad",
   "plane": "XY",
   "profile": {
    "type": "rect",
    "w": "length-upright_t",
    "h": "depth",
    "x": "(length+upright_t)/2",
    "y": 0
   },
   "length": "base_t"
  },
  {
   "id": "tab_round",
   "type": "fillet",
   "edges": [
    "top",
    "parallel_x"
   ],
   "radius": "top_r"
  },
  {
   "id": "tab_hole",
   "type": "hole",
   "plane": "YZ",
   "profile": {
    "type": "circle",
    "d": "tab_hole_d",
    "x": 0,
    "y": "tab_hole_z"
   }
  },
  {
   "id": "base_hole",
   "type": "hole",
   "plane": "XY",
   "offset": "base_t",
   "profile": {
    "type": "circle",
    "d": "base_hole_d",
    "x": "(length+upright_t)/2",
    "y": 0
   }
  },
  {
   "id": "inner_bend",
   "type": "fillet",
   "edges": [
    "parallel_y",
    "!outer"
   ],
   "radius": "inner_r"
  }
 ]
}
```

## Profiles (sketch shapes; x, y = centre, default 0)
| type | fields | parametric? |
|---|---|---|
| `rect` | `w`, `h`, `x`, `y` | live (sheet-bound) |
| `circle` | `d` or `r`, `x`, `y` | live |
| `slot` | `length` (overall), `w`, `x`, `y`, `angle` | baked |
| `polygon` | `points: [[x,y], ...]` (closed automatically) | baked |
| `regular_polygon` | `n`, `d` (circumscribed) or `across_flats`, `x`, `y`, `angle` | baked |
| `circle_pattern` | `count`, `pcd` (pitch circle Ø), `d`, `x`, `y`, `start_angle` | Ø live, positions baked |
| `grid` | `nx`, `ny`, `dx`, `dy`, `d`, `x`, `y` (centred array of circles) | Ø live, positions baked |
| `path` | `start: [x,y]`, `segments: [{"line":[x,y]}, {"arc":{"through":[x,y],"to":[x,y]}}, {"spline":[[x,y],...]}]` — closed back to start automatically | baked |
| `spline` | `points: [[x,y], ...]` — smooth CLOSED curve through the points (paste from `extract_contours(as_spline=true)`) | baked |

"Live" dimensions are bound to the Params spreadsheet and update instantly. "Baked" ones are computed at build time; `set_parameters` rebuilds the part automatically when they change. Both are fine to use.

## Features (applied in order to one PartDesign body)
| type | fields |
|---|---|
| `pad` / `extrude` | profile(s), `plane`, `offset`, `length`, `symmetric` (both sides), `reversed`, or `through_all` |
| `pocket` / `cut` | profile(s), `plane`, `offset`, `depth` or `through_all: true` (cuts both ways by default, `symmetric: false` to cut one way), `reversed` |
| `hole` | like pocket; through-all unless `depth` given |
| `revolve` | profile(s) on `XZ` by default, revolved about the sketch vertical axis (= global Z). `axis`: `V` or `H`, `angle` (default 360). Profile x = radius, y = height. |
| `groove` | subtractive revolve, same fields |
| `trim` | `plane`, `profile` = spline/polygon outline: keeps only material INSIDE that silhouette seen along the plane normal (second view of the visual hull) |
| `fillet` | `edges` selector, `radius` |
| `chamfer` | `edges` selector, `size` |

The first feature must add material (pad or revolve).
Pockets cut **against** the sketch normal: for a plate from z=0 to z=T, sketch at `"offset": "T"`. If a pocket removes nothing, add `"reversed": true` or use `through_all`.

Extra options: pad `"taper": 5` (draft in degrees, positive narrows — moulded parts, sloped
walls); any sketch `"tilt": {"axis": "x", "angle": 30}` rotates the sketch plane about its own
x or y axis (sloped cuts/faces), `"shift_x"/"shift_y"` move the sketch origin in-plane.

## Organic / moulded parts from a photo (silhouette method)
Do NOT approximate curved parts with boxes and disks. Instead:
1. Find the view where the part shows its main silhouette (usually the side view; a lever,
   hook, bracket or clip is mostly a constant cross-section extruded across its width).
2. `extract_contours(photo, mode="photo", as_spline=true, ref_length_mm=<known size>,
   ref_axis="height")` → paste `outline` as the profile of a `pad` on the matching plane
   (side view → `XZ`, `symmetric: true`, `length` = part width).
3. Add the remaining features with cuts: pockets/slots/holes, tapered or tilted pads for walls.
4. Check with `compare_with_reference`. A 3/4 perspective photo gives an approximate outline:
   say so, and ask the user for a straight side photo on a plain background with a ruler.

## Two or more views of a free-form object (visual hull)
For bodies seen in several orthographic views (car body, toy, housing, mouse, bottle):
1. Crop each view with `extract_contours(image, crop=[x0,y0,x1,y1], mode="photo", as_spline=true,
   ref_length_mm=<same real height>, ref_axis="height")` — scale every view by the SAME real dimension.
2. `pad` the side silhouette on `XZ` (`symmetric: true`, `length` = 1.2 × the width from the
   front/rear view — deliberately WIDER, so the trim defines the real width; equal widths make
   coincident faces and the boolean fails).
3. `trim` with the front/rear silhouette on `YZ`; optionally `trim` with the top view on `XY`.
4. `expect_bbox` = [length, width, height] (tolerance is 1 % by default for big objects).
The result is the outer envelope: good for proportions, mock-ups and 3D-print shells; windows,
lights and other surface details are not reconstructed.

## Edge selectors (fillet / chamfer)
`"all"`, `"vertical"` (∥Z), `"parallel_x"`, `"parallel_y"`, `"line"`, `"circular"`,
`"top"`, `"bottom"`, `"left"`, `"right"`, `"front"`, `"back"` (edges lying on that side of the bounding box),
`"outer"` (any bbox side), `"!outer"` (inner edges, e.g. the bend of an L-bracket), `"!sel"` (negation), `"Edge7"` (explicit).
A list means AND: `["top", "circular"]` = circular edges on the top face. `{"any": ["top", "bottom"]}` means OR.
Selectors are re-evaluated after each parameter change, so they survive edits. Cylinder seam edges are skipped automatically.

## Typical recipes
- **Plate with holes**: pad rect → hole (grid / circles) at offset T → fillet `vertical`.
- **Bracket (L-shape)**: pad polygon on `XZ` with `symmetric: true` and `length` = width; inner bend fillet with `["parallel_y", "!outer"]`.
- **Shaft / bushing / flange**: revolve a polygon of the half-section on `XZ` (x = radius), then holes on `XY` at the flange face, chamfer `["top","circular"]`.
- **Boss on a plate**: second pad with a circle at `offset: T`.
- **Counterbore**: hole Ø d through_all, then pocket Ø D with `depth` from the top.
- **Hex nut**: pad `regular_polygon` n=6 `across_flats`, hole circle.

## When it fails
`build_part` returns the failing feature id and FreeCAD's reason. Nothing is left half-built: the whole build is one undo step and is rolled back on failure. Fix the spec and call again (same `name` replaces the part).
