"""HermesCAD core. Startup diagnostics go to <UserAppData>/HermesCAD/hermescad.log."""
import os
import time

_fault_file = None


def log_path():
    try:
        import FreeCAD
        base = FreeCAD.getUserAppDataDir()
    except Exception:
        base = os.path.expanduser("~")
    d = os.path.join(base, "HermesCAD")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "hermescad.log")


def log(msg):
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def enable_crash_log():
    """Dump Python tracebacks of all threads into the log if FreeCAD crashes hard."""
    global _fault_file
    if _fault_file is not None:
        return
    try:
        import faulthandler
        _fault_file = open(log_path(), "a", encoding="utf-8")
        faulthandler.enable(_fault_file, all_threads=True)
    except Exception as exc:
        log("faulthandler unavailable: %r" % (exc,))
