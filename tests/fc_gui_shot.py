# Run with the GUI binary: freecad tests/fc_gui_shot.py  (cwd = repo root); writes a log to %TEMP%
import os, sys, json, traceback
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
import FreeCAD as App, FreeCADGui as Gui
import tempfile
log = open(os.path.join(tempfile.gettempdir(), "hermescad_gui_test.log"), "w")
try:
    from hermescad_core import service as S
    S.new_document("G")
    spec = json.load(open(os.path.join(ROOT, "examples", "flange_revolve.json")))
    S.build_part(spec)
    for v in ("isometric", "front", "top"):
        r = S.get_view(view=v, width=800, height=600)
        log.write("view %s %s %d\n" % (v, r["path"], len(r["png_b64"])))
except Exception:
    log.write(traceback.format_exc())
log.close()
os._exit(0)
