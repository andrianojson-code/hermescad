# HermesCAD + Hermes3D

**English** · [Русский](README.ru.md)

Let [Hermes Agent](https://github.com/NousResearch/hermes-agent) turn pictures into 3D models on your own PC:

| Part | Input | Tool | Output |
|---|---|---|---|
| **HermesCAD** | technical drawing, screenshot, photo of a mechanical part | FreeCAD 1.0+ | **parametric** PartDesign body (editable "Params" spreadsheet), STL / STEP / IGES / BREP |
| **Hermes3D** | screenshot or photo of a free-form object (toy, car, figurine, handle) | Blender 4.2+ | mesh from a cloud image-to-3D model, scaled to real size and repaired for printing, STL / GLB / OBJ / FBX / PLY |

You talk to Hermes in plain language ("here is the drawing, plate 120 mm wide, give me an STL"); Hermes uses the MCP tools in this repo and a skill that tells it how to work.

```
Hermes Agent ──stdio──► hermescad_mcp (Python venv) ──XML-RPC 127.0.0.1:9876──► FreeCAD + HermesCAD add-on
     │                   20 tools, OpenCV, Pillow                                   PartDesign builder, Params, views
     └──────stdio──► hermescad_mcp.blender ─────────XML-RPC 127.0.0.1:9877──► Blender + Hermes3D add-on
                         16 tools ──► cloud image→3D (Hunyuan3D-2.1 Space, free) / Tripo API (optional)
```

## Status

Personal project, works on Windows 10/11 with FreeCAD 1.1, Blender 5.2 and Hermes Agent (desktop and CLI). Expect rough edges.

* From **drawings** HermesCAD builds accurate parametric parts.
* From **photos** it gives approximate shapes. A side photo with a ruler gives the best result.
* Hermes3D needs no local GPU: generation runs on Hugging Face (daily free quota) or the paid Tripo API.

## Install (Windows)

Requirements: Python 3.10+ (python.org, tick "Add to PATH"), Hermes Agent, FreeCAD 1.0+ and/or Blender 4.2+.

```bat
git clone https://github.com/andrianojson-code/hermescad.git
cd hermescad
install.bat
```

`install.bat` runs `install.ps1`, which:

1. **FreeCAD:** links `addon/HermesCAD` into FreeCAD's `Mod` folder (junction, so `git pull` updates it) and turns on bridge autostart. Use `-Copy` to copy instead of linking.
2. **MCP:** creates `.venv` and installs both MCP servers into it.
3. **Blender:** copies `blender_addon/hermes3d` into Blender's add-ons folder and enables it. Use `-NoBlender` to skip this step.
4. **Hermes:** copies the `hermescad` and `hermes3d` skills into Hermes, then prints the `mcp_servers` block for Hermes `config.yaml` and saves it to `hermes/config-snippet.generated.yaml`. A template is in [`hermes/config-snippet.yaml`](hermes/config-snippet.yaml).

Then:

1. Merge the printed block into Hermes `config.yaml`:
   * desktop app: `%LOCALAPPDATA%\hermes\`
   * CLI: `%USERPROFILE%\.hermes\`
2. Restart FreeCAD and/or Blender. Each bridge starts by itself; the FreeCAD Report view shows `HermesCAD RPC listening on 127.0.0.1:9876`.
3. Start a **new** Hermes chat and ask: "check freecad_status" or "check blender_status".

If Blender does not show the add-on as enabled, open **Edit → Preferences → Add-ons**, search for "Hermes3D" and tick it.

**Hermes in WSL2 or on a VPS:** run the MCP server where Hermes runs and reach the bridges over the network.
* WSL2: see the WSL block in `hermes/config-snippet.yaml`.
* VPS: use an SSH tunnel or Tailscale.
* In both cases, set the bridge host to `0.0.0.0` and **always set a token**.

The GUI (FreeCAD / Blender) stays on the Windows PC, because that is where the views are rendered.

## Usage

**Drawing → parametric part (FreeCAD)**

> Here is `D:\drawings\plate.png`, width 120. Build it, 4 mm thick, and export an STL.
>
> Make the holes 8 mm and round the corners R5.  ·  Undo the last change.

Hermes reads the drawing and writes a JSON spec. It then builds the part, compares a render with the drawing, fixes the differences and exports. In FreeCAD each part gets a **"<name> Params"** spreadsheet: edit a cell and the model updates.

The spec format is in [`mcp_server/hermescad_mcp/SPEC.md`](mcp_server/hermescad_mcp/SPEC.md), with examples in [`examples/`](examples).
* Profiles: rect, circle, slot, polygon, regular polygon, patterns, path (line / arc / spline).
* Features: pad (with taper), pocket, hole, revolve, groove, trim (visual hull), fillet, chamfer.

**Picture → mesh (Blender)**

> Make a 3D model of this toy in Blender, 60 mm tall, STL for printing.

Hermes runs this pipeline:
1. cuts the object out of the background;
2. sends it to an image→3D generator;
3. imports the result into Blender and scales it to your dimension;
4. repairs it into a single watertight mesh;
5. renders it and compares it with the picture;
6. exports the file.

You can also make the model on a website (Tripo, Meshy, Hunyuan3D…), save it as **GLB** and ask Hermes to import it.

## MCP tools

| Server | Tools |
|---|---|
| `hermescad` (FreeCAD) | `freecad_status`, `get_spec_reference`, `new_document`, `open_document`, `save_document`, `close_document`, `list_documents`, `get_model_summary`, `build_part`, `get_part_spec`, `set_parameters`, `delete_object`, `undo`, `inspect_image`, `extract_contours`, `add_reference_image`, `get_view`, `compare_with_reference`, `export_model`, `execute_freecad_code` |
| `hermes3d` (Blender) | `blender_status`, `prepare_image`, `generate_3d`, `hf_space_api`, `import_model`, `normalize`, `symmetrize`, `cleanup`, `mesh_stats`, `list_models`, `clear_scene`, `render_view`, `compare_with_reference`, `export_model`, `save_blend`, `execute_blender_code` |

## Security

Both bridges execute commands inside FreeCAD / Blender, so:

* they listen on `127.0.0.1` only by default;
* they refuse browser requests (`Origin` header, non-`text/xml` body, foreign `Host`), which blocks CSRF and DNS rebinding from web pages;
* they support a shared token; set one whenever the bridge listens on anything other than localhost;
* `execute_*_code` (arbitrary Python) can be switched off in the add-on settings.

## Limits

* No assemblies, threads, lofts or sweeps in the spec; `execute_freecad_code` is the fallback for these.
* A single photo cannot give exact dimensions; give Hermes at least one real size.
* Image→3D invents the unseen side, simplifies small details and has no texture on the free tier.
* Free Hugging Face Spaces have a daily GPU quota. Setting a free account token in `HF_TOKEN` raises it.

## Development

```bat
:: FreeCAD builder tests (headless)
"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" -c "exec(open('tests/fc_test_builder.py').read())"
"C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" -c "exec(open('tests/fc_test_recipes.py').read())"
:: Windows self-test of the installed FreeCAD bridge and MCP server
.venv\Scripts\python.exe tests\win_selftest.py
:: Hermes3D end-to-end: photo -> cloud generation -> Blender -> STL (Blender must be open)
run_hermes3d_test.bat
```

Run the tests from the repository root.

Layout:
* `addon/HermesCAD/`: FreeCAD workbench and bridge.
* `blender_addon/hermes3d/`: Blender add-on and bridge.
* `mcp_server/hermescad_mcp/`: both MCP servers, vision tools and generators.
* `hermes/skills/`: Hermes skills.
* `tests/`: tests.

## License

[MIT](LICENSE)
