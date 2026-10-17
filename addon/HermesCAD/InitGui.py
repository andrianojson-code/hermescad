# HermesCAD workbench: lets the Hermes agent drive FreeCAD over a local RPC bridge.
# NOTE: FreeCAD executes this file with separate globals/locals, so methods below
# must not reference module-level names; everything lives in hermescad_core.gui.
import FreeCAD as App
import FreeCADGui as Gui

try:
    import hermescad_core
    hermescad_core.enable_crash_log()
    hermescad_core.log("InitGui start, FreeCAD %s" % ".".join(App.Version()[:3]))
except Exception as _exc:
    App.Console.PrintError("HermesCAD: init log failed: %r\n" % (_exc,))


class HermesCADWorkbench(Gui.Workbench):
    MenuText = "HermesCAD"
    ToolTip = "Drive FreeCAD from the Hermes agent (image -> parametric model)"

    def __init__(self):
        from hermescad_core import gui
        self.__class__.Icon = gui.icon("hermescad.svg")

    def Initialize(self):
        from hermescad_core import gui
        self.appendToolbar("HermesCAD", gui.COMMANDS)
        self.appendMenu("HermesCAD", gui.COMMANDS)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


try:
    from hermescad_core import gui as _hcgui
    _hcgui.register_commands()
    Gui.addWorkbench(HermesCADWorkbench())
    hermescad_core.log("workbench registered")
    _hcgui.schedule_autostart()
except Exception as _exc:
    import traceback as _tb
    App.Console.PrintError("HermesCAD: failed to load: %r\n" % (_exc,))
    try:
        hermescad_core.log("load failed:\n" + _tb.format_exc())
    except Exception:
        pass
