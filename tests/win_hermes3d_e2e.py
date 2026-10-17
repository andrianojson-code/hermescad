"""Windows end-to-end: photo -> cutout -> TripoSG (HF) -> Blender -> cleanup -> STL.
Writes tests/selftest_out/hermes3d_e2e.txt"""
import asyncio, json, os, sys, time, traceback
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "selftest_out"); os.makedirs(OUT, exist_ok=True)
lines = []
def log(s):
    lines.append(str(s)); open(os.path.join(OUT, "hermes3d_e2e.txt"), "w", encoding="utf-8").write("\n".join(lines))
def t(r): return "".join(c.text for c in r.content if c.type == "text")
async def main():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "mcp_server"), HERMES3D_OUT=os.path.join(ROOT, "generated"))
    async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "hermescad_mcp.blender"], env=env)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            log("status: " + t(await s.call_tool("blender_status", {})).replace("\n", " "))
            await s.call_tool("clear_scene", {})
            res = await s.call_tool("prepare_image", {"image_path": os.path.join(ROOT, "tests", "data", "lever_photo.png")})
            cut = json.loads(t(res))["cutout_path"]; log("cutout: " + cut)
            t0 = time.time()
            res = await s.call_tool("generate_3d", {"image_path": cut, "backend": "auto", "name": "Lever"})
            log("generate %.0fs error=%s: %s" % (time.time() - t0, res.isError, t(res)[:1500].replace("\n", " ")))
            if res.isError:
                return
            log("normalize: " + t(await s.call_tool("normalize", {"name": "Lever", "size_mm": 40, "axis": "z"}))[:400].replace("\n", " "))
            cl = json.loads(t(await s.call_tool("cleanup", {"name": "Lever", "mode": "print", "resolution": 200, "target_faces": 80000})))
            log("cleanup: print_ready=%s after=%s" % (cl["print_ready"], {k: cl["after"][k] for k in ("faces", "watertight", "loose_parts", "dimensions_mm")}))
            for v in ("three_quarter", "right"):
                log("render: " + t(await s.call_tool("render_view", {"view": v, "name": "Lever"})))
            log("compare: " + t(await s.call_tool("compare_with_reference", {"reference_path": os.path.join(ROOT, "tests", "data", "lever_photo.png"), "name": "Lever"})))
            log("export: " + t(await s.call_tool("export_model", {"path": "lever_hermes3d.stl", "name": "Lever"}))[:300].replace("\n", " "))
    log("E2E DONE")
try:
    asyncio.run(main())
except Exception:
    log("E2E FAILED\n" + traceback.format_exc())
