"""MCP stdio client -> hermes3d MCP server -> bridge -> Blender (headless bpy)."""
import asyncio, json, os, subprocess, sys, tempfile, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: fails.append(m)
def t(r): return "".join(c.text for c in r.content if c.type == "text")
def imgs(r): return sum(c.type == "image" for c in r.content)
tmp = tempfile.mkdtemp()
# a "generated" mesh: suzanne glb made by bpy in a subprocess
subprocess.run([sys.executable, "-c", "import bpy;bpy.ops.wm.read_factory_settings(use_empty=True);"
                "bpy.ops.mesh.primitive_monkey_add(size=2);"
                "bpy.ops.export_scene.gltf(filepath=r'%s', export_format='GLB')" % os.path.join(tmp, "gen.glb")],
               capture_output=True)
async def main():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "mcp_server"), HERMES3D_OUT=tmp)
    async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "hermescad_mcp.blender"], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [x.name for x in (await s.list_tools()).tools]
            check(len(tools) == 16, "16 tools: %s" % tools)
            st = json.loads(t(await s.call_tool("blender_status", {})))
            check(st["blender"].startswith("5."), "status: Blender %s" % st["blender"])
            await s.call_tool("clear_scene", {})
            res = await s.call_tool("prepare_image", {"image_path": os.path.join(ROOT, "tests", "data", "lever_photo.png")})
            info = json.loads(t(res))
            check(os.path.isfile(info["cutout_path"]) and imgs(res) == 1, "prepare_image cutout (coverage %s)" % info["coverage"])
            res = await s.call_tool("generate_3d", {"image_path": info["cutout_path"], "backend": "hf:triposg"})
            check(res.isError and ("Hugging Face" in t(res) or "TripoSG" in t(res)), "generator offline -> clear error: %s" % t(res)[:140])
            res = await s.call_tool("import_model", {"path": os.path.join(tmp, "gen.glb"), "name": "Lever"})
            check(not res.isError and imgs(res) == 1, "import_model + render")
            res = await s.call_tool("normalize", {"name": "Lever", "size_mm": 60, "axis": "z"})
            d = json.loads(t(res))
            check(abs(d["dimensions_mm"][2] - 60) < 0.01, "normalize z=60: %s" % d["dimensions_mm"])
            res = json.loads(t(await s.call_tool("cleanup", {"name": "Lever", "mode": "print", "resolution": 128, "target_faces": 30000})))
            check(res["print_ready"], "cleanup print_ready: %s" % {k: res["after"][k] for k in ("faces", "watertight", "loose_parts")})
            res = await s.call_tool("compare_with_reference", {"reference_path": os.path.join(ROOT, "tests", "data", "lever_photo.png"), "name": "Lever"})
            check(not res.isError and "_compare.png" in t(res), "compare_with_reference")
            ex = json.loads(t(await s.call_tool("export_model", {"path": os.path.join(tmp, "lever.stl"), "name": "Lever"})))
            check(ex["mesh"]["watertight"] and ex["bytes"] > 1000, "export STL watertight")
            ex = json.loads(t(await s.call_tool("export_model", {"path": "lever.glb", "name": "Lever"})))
            check(os.path.isfile(ex["path"]), "export GLB to work dir")
    print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
asyncio.run(main())
