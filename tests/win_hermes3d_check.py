"""Windows check: Blender bridge reachable, Hugging Face reachable. Writes tests/selftest_out/hermes3d.txt"""
import json, os, sys, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mcp_server"))
OUT = os.path.join(ROOT, "tests", "selftest_out"); os.makedirs(OUT, exist_ok=True)
lines = []
def log(s):
    lines.append(str(s)); open(os.path.join(OUT, "hermes3d.txt"), "w", encoding="utf-8").write("\n".join(lines))
try:
    import gradio_client; log("gradio_client %s" % gradio_client.__version__)
except Exception as e:
    log("gradio_client MISSING: %r" % e)
try:
    from hermescad_mcp.client import Bridge
    log("blender: " + json.dumps(Bridge(port=9877).call("status")))
except Exception as e:
    log("blender bridge: %r" % e)
try:
    from hermescad_mcp import gen3d
    eps = gen3d.space_api("VAST-AI/TripoSG")
    log("HF TripoSG reachable, endpoints: " + ", ".join(eps))
except Exception as e:
    log("HF TripoSG: %r" % e)
log("DONE")
