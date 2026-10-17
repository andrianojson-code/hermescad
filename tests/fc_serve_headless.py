# Start the bridge in freecadcmd (no GUI) and keep serving. For tests / headless use.
import os, sys, time
ROOT = os.environ.get("HERMESCAD_ROOT", os.getcwd())
sys.path.insert(0, os.path.join(ROOT, "addon", "HermesCAD"))
from hermescad_core import rpc
b = rpc.Bridge("127.0.0.1", int(os.environ.get("HERMESCAD_PORT", "9876")),
               os.environ.get("HERMESCAD_TOKEN", ""), use_gui=False)
b.start()
while True:
    time.sleep(1)
