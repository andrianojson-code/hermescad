"""Windows self-test: Hermes-like MCP client -> hermescad_mcp -> FreeCAD bridge.
Run with the project venv:  .venv\\Scripts\\python.exe tests\\win_selftest.py
Writes tests\\selftest_out\\report.txt and screenshots."""
import asyncio, base64, json, os, sys, traceback
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "selftest_out")
os.makedirs(OUT, exist_ok=True)
lines = []

def log(s):
    lines.append(s)
    open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8").write("\n".join(lines))

def text(r):
    return "".join(c.text for c in r.content if c.type == "text")

def save_imgs(r, name):
    n = 0
    for c in r.content:
        if c.type == "image":
            n += 1
            open(os.path.join(OUT, "%s_%d.png" % (name, n)), "wb").write(base64.b64decode(c.data))
    return n

async def main():
    p = StdioServerParameters(command=sys.executable, args=["-m", "hermescad_mcp"], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            log("tools: %d" % len(tools.tools))
            log("status: " + text(await s.call_tool("freecad_status", {})).replace("\n", " "))
            await s.call_tool("new_document", {"name": "SelfTest"})
            spec = json.load(open(os.path.join(ROOT, "examples", "flange_revolve.json")))
            res = await s.call_tool("build_part", {"spec": spec})
            log("build_part error=%s images=%d" % (res.isError, save_imgs(res, "build")))
            log(text(res)[:600])
            res = await s.call_tool("set_parameters", {"part": "Flange", "values": {"D": 120}})
            log("set_parameters error=%s images=%d bbox=%s" % (res.isError, save_imgs(res, "set"),
                json.loads(text(res)).get("bbox_mm", {}).get("size") if not res.isError else text(res)))
            for v in ("front", "top"):
                res = await s.call_tool("get_view", {"view": v})
                log("get_view %s error=%s images=%d" % (v, res.isError, save_imgs(res, "view_" + v)))
            res = await s.call_tool("export_model", {"path": "selftest_flange.stl"})
            log("export: " + text(res).replace("\n", " "))
            res = await s.call_tool("save_document", {"path": "selftest_flange.FCStd"})
            log("save: " + text(res).replace("\n", " "))
            res = await s.call_tool("close_document", {"document": "SelfTest"})
            log("close: " + text(res).replace("\n", " "))
    log("SELFTEST DONE")

try:
    asyncio.run(main())
except Exception:
    log("SELFTEST FAILED\n" + traceback.format_exc())
