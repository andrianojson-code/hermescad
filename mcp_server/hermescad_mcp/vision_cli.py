"""Run OpenCV-based vision helpers in a separate process.

OpenCV can deadlock when called from the MCP server's worker thread on Windows, so the
servers call these through `run(...)`, which spawns `python -m hermescad_mcp.vision_cli`.
"""
import json
import os
import subprocess
import sys
import tempfile


def _main():
    req = json.loads(sys.stdin.read())
    from . import vision
    op, kw = req["op"], req.get("kwargs", {})
    if op == "cutout":
        img, info = vision.cutout(kw.pop("path"), **kw)
        img.save(req["out"])
        info["cutout_path"] = req["out"]
        res = info
    elif op == "extract_contours":
        data, overlay = vision.extract_contours(kw.pop("path"), **kw)
        overlay.save(req["out"])
        data["overlay_png"] = req["out"]
        res = data
    else:
        raise SystemExit("unknown op %s" % op)
    sys.stdout.write(json.dumps(res))


def run(op, out, timeout=180, **kwargs):
    env = dict(os.environ)
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-m", "hermescad_mcp.vision_cli"],
                       input=json.dumps({"op": op, "out": out, "kwargs": kwargs}),
                       capture_output=True, text=True, timeout=timeout, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        raise RuntimeError("vision %s failed: %s" % (op, err[-1] if err else p.returncode))
    return json.loads(p.stdout)


if __name__ == "__main__":
    _main()
