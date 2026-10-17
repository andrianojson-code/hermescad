"""End-to-end: MCP stdio client -> hermescad_mcp -> RPC -> FreeCAD (headless)."""
import asyncio, json, os, sys, tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []

def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)

def text(res):
    return "".join(c.text for c in res.content if c.type == "text")

async def main():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "mcp_server"))
    params = StdioServerParameters(command=sys.executable, args=["-m", "hermescad_mcp"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            st = json.loads(text(await s.call_tool("freecad_status", {})))
            check(st["freecad"].startswith("1."), "status: FreeCAD %s" % st["freecad"])
            ref = text(await s.call_tool("get_spec_reference", {}))
            check("Edge selectors" in ref, "spec reference served")
            await s.call_tool("new_document", {"name": "E2E"})
            spec = json.load(open(os.path.join(ROOT, "examples", "plate_with_holes.json")))
            res = await s.call_tool("build_part", {"spec": spec})
            check(not res.isError, "build_part ok")
            out = json.loads(text(res))
            check(out["bbox_mm"]["size"] == [80, 50, 6], "bbox via MCP")
            res = await s.call_tool("set_parameters", {"part": "MountPlate", "values": {"W": 70}})
            check(json.loads(text(res))["bbox_mm"]["size"][1] == 70, "set_parameters via MCP")
            res = await s.call_tool("build_part", {"spec": {"name": "X", "features": [{"type": "pad", "profile": {"type": "rect", "w": 1, "h": "Q"}, "length": 1}]}})
            check(res.isError and "unknown parameter" in text(res), "error surfaces to agent: " + text(res)[:90])
            sm = json.loads(text(await s.call_tool("get_model_summary", {})))
            check([p["part"] for p in sm["parts"]] == ["MountPlate"], "failed build rolled back")
            stl = os.path.join(tempfile.gettempdir(), "e2e_plate.stl")
            ex = json.loads(text(await s.call_tool("export_model", {"path": stl})))
            check(ex["bytes"] > 1000 and ex["triangles"] > 50, "STL export %d triangles" % ex["triangles"])
            ex = json.loads(text(await s.call_tool("export_model", {"path": stl[:-4] + ".step"})))
            check(ex["bytes"] > 1000, "STEP export")
            ec = json.loads(text(await s.call_tool("execute_freecad_code", {"code": "print(len(doc.Objects)); result = doc.Name"})))
            check(ec["ok"] and ec["result"] == "E2E", "execute_code")
            sv = json.loads(text(await s.call_tool("save_document", {"path": os.path.join(tempfile.gettempdir(), "e2e.FCStd")})))
            check(sv["saved"].endswith("e2e.FCStd"), "save")
            u = json.loads(text(await s.call_tool("undo", {})))
            check(u["undone"] == 1, "undo")
            sm = json.loads(text(await s.call_tool("get_model_summary", {})))
            check(sm["parts"][0]["bbox_mm"]["size"][1] == 50, "undo restored W=50")
            img = os.path.join(ROOT, "tests", "data", "bracket_drawing.png")
            res = await s.call_tool("extract_contours", {"image_path": img, "ref_length_mm": 100})
            data = json.loads(text(res))
            print(json.dumps(data)[:600])
            check(any(c.type == "image" for c in res.content), "overlay image returned")
            check(len(data["holes"]) == 3, "3 holes detected: %d" % len(data["holes"]))
            res = await s.call_tool("inspect_image", {"image_path": img})
            check(any(c.type == "image" for c in res.content), "inspect_image")
            rr = await s.call_tool("add_reference_image", {"image_path": img, "width_mm": 100})
            check(not rr.isError, "reference image plane: " + text(rr)[:80])
    print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))

asyncio.run(main())
