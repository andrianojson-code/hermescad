---
name: hermescad
description: Model mechanical parts in FreeCAD from photos, screenshots or technical drawings, and edit existing models by natural language, using the hermescad MCP tools (build_part, set_parameters, compare_with_reference, export_model).
version: 0.3.0
metadata:
  hermes:
    tags: [cad, freecad, 3d, modeling, 3d-printing, vision]
---

# HermesCAD: image → parametric FreeCAD model

Use this skill when the user wants a CAD model / STL / STEP of a physical part, gives a
photo, screenshot or drawing of a part, or asks to change a FreeCAD model
("make the holes bigger", "add a 2 mm chamfer", "make it 10 mm longer").
Answer in the user's language.

## Hard rules (keep it fast)
- The skill's FreeCAD code route is `mcp__hermescad__execute_freecad_code`; never write FreeCAD scripts in the terminal. Import modules used by the snippet explicitly inside the FreeCAD session (e.g. `import Part, math`), because not every module is present in its execution globals.

  Do NOT read other FreeCAD projects, addons or skills on disk (fcagent, fcctl, freecad-agent,
  freecad-mcp, ...) — they are unrelated. The one terminal route is the documented headless
  export fallback in `references/curved-bodies-and-export.md`, used when `export_model` refuses a
  document of `Part::Feature` objects.
- `execute_freecad_code` runs each snippet in a fresh namespace: nothing defined in the previous
  snippet survives. Keep a build in one snippet, or recompute its inputs at the top of the next.
- A few failed MCP calls in a row make the hermescad server pause for about a minute. After a
  failure change the approach (different arguments, a spec build, the `freecadcmd` route) instead
  of resubmitting the same call.
- If the hermescad tools are not in your tool list, STOP and tell the user:
  "Start a new session (/new) so the hermescad tools load." Do not improvise a workaround.
- Look at each image ONCE. If it is attached and you can see it, do not call vision_analyze
  on it again; if you only have a file path (e.g. `...\composer-images\image_*.png`), call
  `inspect_image(path)` once. For unclear dimension arrows, inspect one targeted crop once; avoid repeated full-image analysis because separate interpretations may conflict.
- A simple part (plate, bracket, bushing, flange) = at most ~8 tool calls:
  status → (spec reference) → (extract_contours) → build_part → compare/get_view → fix → save/export.
- Unknown dimensions: estimate proportionally from ONE key size, state the assumptions, build.
  Do not stall waiting for perfect data; the user corrects via set_parameters.

## 0. Preflight
Call `freecad_status`. If it fails, tell the user: open FreeCAD → workbench **HermesCAD** →
**Start Hermes bridge** (or enable autostart in HermesCAD settings). Read `get_spec_reference`
once per session before writing your first spec.
- The bridge keeps its last session's documents open: `SelfTest` (holding the bundled sample
  `Flange`) is usually still there and is the ACTIVE document. Call `new_document(name=<Part>)`
  first, then pass `document=<Part>` to `build_part`, `get_view`, `compare_with_reference`,
  `export_model` and `save_document`. Otherwise the part is built into the leftover document and
  every render shows unrelated bodies beside it. If a stray copy landed there, remove it with
  `delete_object(name, document=<doc>)`, or drop a whole leftover document with `close_document`.

## 1. Understand the part
- FIRST read the image with the structured prompt in `references/part-reading-prompt.md`
  (pass it as the `vision_analyze` question, once per image). Build from that JSON:
  overall_mm -> expect_bbox, features[].axis -> sketch plane, unknowns -> stated assumptions.
- Look at the image (attached, or `inspect_image` for a file path) — once.
- Classify it: **orthographic drawing / clean silhouette** (exact) vs **photo / perspective
  render** (estimate).
- Identify the base form: prismatic plate/block (pad), turned part (revolve), bent/L shape
  (pad of a side profile), plus holes, slots, bosses, fillets, chamfers.
- If it is a small/unfamiliar photo and the vision pass comes back generic ("possibly a clip,
  cannot determine dimensions"), STOP asking vision again and read the outline yourself at pixel
  level — `references/photo-silhouette-workflow.md`. Two vision passes on the same small photo
  return vague, mutually inconsistent prose; an ASCII silhouette of the mask gives real geometry
  (lobes, waists, overhangs, gaps) you can turn into a profile.
- Decide the modelling strategy aloud in 2–4 short lines: base feature, which plane, which
  features follow.

## 2. Get the dimensions (never invent scale silently)
Priority order:
1. Dimensions written on the drawing → use them exactly.
2. User-provided dimension(s). If none is known, **ask for ONE key dimension** (overall length
   or a hole diameter) and continue estimating the rest proportionally.
3. Known references in the photo: a ruler, a coin (RUB 5 = 25 mm, RUB 10 = 22 mm, 1 € = 23.25 mm),
   a standard bolt (M3/M4/M5/M6/M8 head and thread), a credit card (85.6 × 54 mm), A4 sheet.
4. Standard sizes: snap estimates to round values (0.5 / 1 mm steps; holes to clearance
   sizes 3.4, 4.5, 5.5, 6.6, 9, 11 mm; sheet thickness 1, 1.5, 2, 3, 4, 5, 6, 8, 10).
For drawings and silhouettes, inspect the current `extract_contours` schema before calling it; pass only supported arguments, since the installed tool may not expose options such as `mode` or `as_spline`. Set `ref_length_mm` from a known overall width or height; use `crop` to isolate one view of a multi-view drawing. The returned outline/hole profiles are in mm and usually ready for the spec. Check the overlay when one is returned: red = outline, blue = holes. If it picked the frame or dimension text, crop tighter. If the source has no known scale, use a clearly labelled provisional scale for a proportional draft, never report that arbitrary scale as measured.

Write down a short dimension table (name, value, source: drawing / user / estimated). Cross-check that each callout belongs to the feature and view assigned to it; treat ambiguous dimensions and missing hole callouts as estimates, not facts. If uncertainty affects fit, ask one focused question; otherwise label the reconstruction approximate and keep estimated values editable.

## 3. Build
- Put every meaningful dimension into `parameters` with readable names
  (`length`, `width`, `thickness`, `hole_d`, `pcd`, `fillet_r`) and reference those parameters in the profile/features; avoid hardcoded coordinates or parameters that do not affect geometry, because they create misleadingly editable models.
- Before building, map every drawing callout to the feature/view it controls and outline the proposed feature sequence briefly. Treat undimensioned thickness, hole size, and radii as explicit estimates; do not infer that a dimension controls a feature unless its arrows/views support that mapping.
- Keep the spec simple and robust: base feature first, then cuts, then fillets/chamfers last. For geometry the spec cannot express (such as a gear tooth profile), use `execute_freecad_code` rather than silently substituting a primitive or approximate feature; see `references/gears.md` for the gear-specific workflow.
- Map every drawing callout and visible feature to a planned feature, then verify the built geometry against that map. A custom property attached to a static shape is reference metadata only: unless the geometry actually depends on it, do not describe the model as parametrically editable.
- ALWAYS put the drawing's overall size into the spec as `"expect_bbox": [X, Y, Z]` (null = unknown).
  Drawing dimensions are OVERALL sizes from the outer faces: total height 33 with a 16 mm base means
  the upright adds 17, not 33; hole heights are measured from the bottom face. For a traced polygon,
  derive expected extents from the final profile coordinates (min/max on each axis), because contour
  simplification can make the reported image bbox differ slightly from the built body's bbox. If
  build_part warns `overall Z is ... but expect_bbox says ...`, fix the stacking before anything else.
- Do not add fillets/chamfers that the drawing does not show.
- ORIENTATION (most common mistake): a sketch drills/extrudes ALONG its plane normal —
  `XY`→Z, `XZ`→Y, `YZ`→X. Sketch each hole on the plane PARALLEL to the face it goes through.
  Before the spec, write one line per wall, e.g. "upright: thin along X → its hole on YZ".
  If build_part says a hole "did not make a round hole", switch that hole's plane as it suggests.
- AI-generated / sketchy drawings often have views and numbers that contradict each other.
  Then trust the isometric view for topology, use the numbers that are consistent, and say so —
  `references/ambiguous-drawings.md` gives the rules for which readings to trust, how to reconcile
  contradictory views, and how to hand over a part you had to interpret.
- Orient the part the way it is drawn: top view → `XY`, front view → `XZ`, turned parts →
  revolve on `XZ` (x = radius, y = height).
- Call `build_part`. On error, read the message (it names the failing feature), fix only that
  feature and call again with the same `name`.

## 4. Verify visually (mandatory)
- `compare_with_reference(reference_path, view)` using the view that matches the source:
  drawings → `top` / `front` / `right`; photos → `isometric` (or the closest). For multi-view drawings, verify the model against the view that actually constrains the built profile and separately inspect the isometric form.
- Inspect the returned rendered comparison or viewport image itself before claiming visual verification. A tool response that merely confirms rendering, or build metadata alone, does not establish that the shape matches; if the image is not presented, use an available visual inspection route or report that visual comparison could not be verified.
- Vision check of a render answers only about the image you hand it. Asking "does this match the
  photo?" returns "there is no photo in this image" or an invented comparison; either pass the
  `compare_with_reference` composite, or put the reference's key features into the question
  ("должен быть отдельный капот, тёмная кабина, два колеса под арками").
- If the image only came as an attachment and has no file path, use `get_view` and
  compare with what you saw.
- List concrete differences (missing hole, wrong proportion, wrong side) and fix them with
  `set_parameters` (dimensions) or a corrected spec (topology). At most 3 fix iterations,
  then show the user and ask.
- Also check `bbox_mm` against the known overall dimensions.
- Orientation decides which view shows the profile: a body built along X shows its side in
  `front`, while `right` / `left` show the end faces. Read `bbox_mm` first to know which axis is
  the length, then pick the view — judging an X-aligned part from `right` compares the wrong shape.
- The document may hold several parts: pass `part=<name>` to `get_view` / `compare_with_reference`
  so only the part you are checking is in the picture (build_part/set_parameters already do this).
- Image tools may return only a view label or render confirmation rather than a usable path.
  Never invent a filename or timestamp: use the actual path in the response, or list
  `<freecad_status.work_dir>/views/` and select the newest relevant render, then open that exact
  file once. For a comparison, inspect the actual comparison image; if it was not saved or
  presented, inspect the source and model render separately and state the limitation rather than
  claiming a visual match. Exports land in `<work_dir>/exports/`. Do not build your own composites
  and never pip-install packages for this.

## 5. Deliver
- `save_document` (bare name → HermesCAD exports folder) and, if asked or for printing,
  `export_model` to STL (`linear_deflection` 0.02–0.05) and/or STEP; pass `part=<name>` when the
  document has several parts (`part="all"` merges them).
- `export_model` to STL returns `mesh_check` (watertight, non_manifold, self_intersections,
  volume deviation, bbox) and `print_ready`. Report it; if `print_ready` is false, fix before delivering.
- `export_model` only walks PartDesign bodies; a document made of `Part::Feature` objects
  answers `nothing to export`. Export that case headless (`freecadcmd` + `MeshPart.meshFromShape`,
  recipe in `references/curved-bodies-and-export.md`) and report the result honestly: a compound
  of several bodies is not a single watertight mesh.
- Capture the FreeCAD viewport separately and confirm the intended model/document is visible and oriented usefully; bridge status or build metadata is not visual verification.
- Report briefly: what was built, key dimensions and estimates, verified file paths, and how to change a parameter ("say: hole_d = 8"). Deliver local files using the chat's file-attachment mechanism, not a `file://` link.

For toothed wheels and spur gears from drawings, follow the topology, tooth-geometry, and validation workflow in `references/gears.md`.

## Organic / moulded parts from photos (silhouette method)
Curved plastic parts (levers, clips, hooks, handles) must NOT be approximated by boxes and disks.
1. Model from the exact image attached in the current request, not a prose summary or an older
   image/model from conversation history. Pick the view that shows the main silhouette (usually
   the side). Most such parts are that outline extruded across their width.
2. Inspect the live `extract_contours` schema and call it with supported arguments, including
   `image_path` and a known `ref_length_mm`/`ref_axis` when available; do not assume optional
   `mode` or spline flags exist. Open the returned overlay once, if present, to confirm the trace
   hugs the part. A perspective photo's extracted contour is the camera-projected outer boundary,
   not automatically a true side profile: do not infer hidden edges, depth, or physical topology
   from it. Treat a 3/4-view extrusion as a rough visual draft and request a straight side photo
   with a ruler to refine. When the tool cannot trace the photo, use the pixel silhouette workflow
   in `references/photo-silhouette-workflow.md`; do not replace the observed outline with an
   imagined generic shape or disconnected primitive pads.
3. Pad the returned `outline` (a `spline` profile) on the matching plane: side view → `XZ`,
   `symmetric: true`, `length` = part width. Then cut slots/holes/steps; use `taper` for sloped
   walls and `tilt` for angled faces; use `path` (lines + arcs + splines) for mixed outlines.
   For rounded paddles, use the traced contour or a rounded closed profile joined into the
   curved arm; a full-thickness circular disk often reads as a wheel, not a thin moulded tab.
4. From one 3/4 perspective photo the result is approximate - say so and ask for a straight
   side photo (plain background, ruler or one known size) to refine.
5. Verify against the same source file with `compare_with_reference`; inspect the actual
   comparison/render and list concrete silhouette mismatches (tip shape, neck curvature,
   base outline, visible recesses). A successful build or a visually plausible isometric alone
   is not evidence that it resembles the reference. Iterate the contour/profile rather than
   merely changing dimensions when the topology or silhouette is wrong.
6. After building, verify body topology (`valid` and `len(Shape.Solids)`) in FreeCAD. A valid
   PartDesign body can still contain multiple disconnected solids; visually touching pads are
   not proof of a single connected part. If one solid is intended, fix the profiles/intersections
   and recheck before exporting.
7. If your model cannot see images, the silhouette method still works: the numbers come from
   `extract_contours`, not from your eyes; use vision_analyze only on the overlay/compare files.

## Smooth lofted bodies (cars, housings, handles)
The JSON spec cannot express lofts, so these go through ONE `execute_freecad_code` snippet:
periodic BSpline sections along the length, plan taper, tumblehome above the beltline, wheel
arches as cylinder cuts, decorative solids offset ~3 mm outward so coplanar faces do not tear.
Check `len(body.Faces)` before judging the look — hundreds of faces means polygon sections and a
striped render. Full recipe, artifact fixes, view mapping and the export fallback:
`references/curved-bodies-and-export.md`.

## Several views of a free-form object (car, toy, housing): visual hull
- Do NOT write raw FreeCAD scripts (lofts by hand) for this. Use the spec:
  1. `extract_contours(image, crop=<one view>, mode="photo", as_spline=true, ref_length_mm=<SAME real
     height for every view>, ref_axis="height")` for the side view and the front/rear view.
  2. `pad` the side outline on `XZ`, `symmetric: true`, `length` = 1.2 x the width (deliberately wider).
  3. `trim` with the front/rear outline on `YZ` (keeps only material inside it); optional `trim` with a
     top-view outline on `XY`. `expect_bbox` = [length, width, height].
- The result is the outer envelope (proportions, mock-ups, print shells); say that windows, lights
  and panel details are not reconstructed.
- Before judging the render set `ViewObject.DisplayMode = 'Shaded'` and `Deviation = 0.02`: the
  default 'Flat Lines' draws every face edge, a spline hull then looks striped and the vision pass
  reports surface bands that do not exist.
- `execute_freecad_code` is a last resort, not the default for "complex" shapes.

## Editing an existing model
`list_documents` / `get_model_summary` → `get_part_spec(part)`.
- Dimension change → `set_parameters(part, {"name": value})`.
- New/removed feature → modify the spec and `build_part` with the same name.
- Mistake → `undo`.

## Limits (be honest with the user)
- Single solid PartDesign bodies; no assemblies, threads, lofts or sweeps in the spec —
  use `execute_freecad_code` only for those, and keep such code short.
- Dimensions from a single perspective photo are approximate; say which values are guesses.
- Features you cannot resolve (a dark spot that is either a hole or a moulding witness mark, a
  narrow line that might be a shadow) are NOT modelled, and the report lists them as
  "not modelled" together with the request for another view. Inventing them ships a confident
  wrong part; omitting them keeps the model honest and editable.
- Never call a photo-based reconstruction an "exact copy". State the key size, mark the rest as
  proportional estimates in the dimension table, and close by asking for ONE key dimension plus
  side/top photos — that request is part of the deliverable, not a reason to stall.
