---
name: hermes3d
description: Turn a screenshot or photo of an object (toy, car, figurine, organic or decorative part) into a 3D model in Blender with the hermes3d MCP tools - cloud image-to-3D generation, then scale, repair, compare and export (STL/GLB/OBJ/FBX).
version: 0.1.0
metadata:
  hermes:
    tags: [blender, 3d, mesh, image-to-3d, 3d-printing, vision]
---

# Hermes3D: picture -> 3D model in Blender

Use for free-form objects from pictures (cars, toys, figurines, handles, decor, organic parts).
For mechanical parts with a DRAWING and exact dimensions use the `hermescad` skill (FreeCAD) instead.
Answer in the user's language.

## Hard rules
- Do NOT model by hand (no box/sphere/loft scripts). A cloud generator makes the mesh; you are the
  operator: prepare -> generate -> scale -> check -> repair -> export.
- Use only the hermes3d tools (`mcp__hermes3d__*`). `execute_blender_code` only for small edits
  (delete a part, add a base plate, boolean a hole). Never pip-install anything.
- If the tools are missing, tell the user to open Blender and start a new chat. Do not improvise.
- Look at each image once. If you cannot see images, use the returned file paths with vision_analyze once.

## Workflow (about 6-8 tool calls)
1. `blender_status`. If it fails: "open Blender 5.2 (the Hermes3D add-on starts the bridge)".
   Then `clear_scene` for a new job.
2. Pick ONE view: a clean 3/4 view is best (shows front, side and top); for multi-view sheets pass
   `crop=[x0,y0,x1,y1]` around that view. `prepare_image(image_path, crop)` -> `cutout_path`.
3. `generate_3d(cutout_path, backend="auto", name=<short latin name>)` - takes 30 s to 3 min.
   - `auto` uses the free Hunyuan3D-2.1 Space (about 30 s), then fallbacks. On quota/network errors tell the user; options: wait, set HF_TOKEN (free HF
     account = more quota), backend `tripo` with TRIPO_API_KEY, or the user generates the model on a
     website (Meshy, Tripo, Rodin, Hunyuan3D) and gives you the .glb -> `import_model(path)`.
4. `normalize(name, size_mm=<real size>, axis=...)`. Ask the user for ONE real dimension if unknown
   (car length, toy height...). Fix orientation with `up` / `rotate_deg` so the object stands on Z
   and its front faces -Y. Use `symmetrize(axis="x")` for symmetric objects.
5. `compare_with_reference(original_image, view=<matching view>)` - list concrete differences.
   Generators get proportions right but small details wrong; regenerating with a better/cleaner view
   is usually better than editing.
6. Purpose:
   - 3D print: `cleanup(mode="print", resolution=256, target_faces=150000)` -> needs `print_ready: true`
     (watertight, one part). Then `export_model("<name>.stl")`.
   - Visualisation/games: `cleanup(mode="light")`, export `glb` (keeps textures if the backend made them).
7. Report: file paths, real size, faces, print_ready, what is approximate (hidden back side is guessed
   by the generator), and how to improve (better photo, another backend).

## Limits (say them)
- One picture -> the unseen side is invented by the generator.
- Text, logos, thin parts (antennas, wires) and exact dimensions are not reliable; for exact
  mechanical parts use FreeCAD (hermescad).
- Free Hugging Face generation has a daily GPU quota; the free mesh has no texture (white).
