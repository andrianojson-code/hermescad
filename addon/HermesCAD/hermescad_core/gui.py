"""GUI commands for the HermesCAD workbench.

Lives in a normal module (not InitGui.py): FreeCAD executes InitGui.py with
separate globals/locals, so functions defined there are invisible to methods.
"""
import os

import FreeCAD as App
import FreeCADGui as Gui

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")


def icon(name="hermescad.svg"):
    return os.path.join(ICON_DIR, name)


class StartRPC:
    def GetResources(self):
        return {"Pixmap": icon("start.svg"), "MenuText": "Start Hermes bridge",
                "ToolTip": "Start the RPC server the Hermes agent connects to"}

    def Activated(self):
        from . import rpc
        try:
            rpc.start()
        except OSError as exc:
            App.Console.PrintError("HermesCAD: cannot start RPC (%s). Port busy? "
                                   "Change it in HermesCAD settings.\n" % exc)

    def IsActive(self):
        from . import rpc
        return not rpc.is_running()


class StopRPC:
    def GetResources(self):
        return {"Pixmap": icon("stop.svg"), "MenuText": "Stop Hermes bridge",
                "ToolTip": "Stop the RPC server"}

    def Activated(self):
        from . import rpc
        rpc.stop()

    def IsActive(self):
        from . import rpc
        return rpc.is_running()


class Settings:
    def GetResources(self):
        return {"Pixmap": icon("settings.svg"), "MenuText": "HermesCAD settings",
                "ToolTip": "Host, port, token, autostart"}

    def Activated(self):
        from PySide import QtGui
        from . import rpc
        p = App.ParamGet(rpc.PARAM_PATH)
        cur = rpc.prefs()
        dlg = QtGui.QDialog(Gui.getMainWindow())
        dlg.setWindowTitle("HermesCAD settings")
        form = QtGui.QFormLayout(dlg)
        host = QtGui.QLineEdit(cur["host"])
        port = QtGui.QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(cur["port"])
        token = QtGui.QLineEdit(cur["token"])
        token.setPlaceholderText("empty = no token (OK for 127.0.0.1)")
        auto = QtGui.QCheckBox("Start bridge when FreeCAD starts")
        auto.setChecked(cur["autostart"])
        code = QtGui.QCheckBox("Allow execute_code (arbitrary Python from the agent)")
        code.setChecked(cur["allow_code"])
        form.addRow("Host", host)
        form.addRow("Port", port)
        form.addRow("Token", token)
        form.addRow(auto)
        form.addRow(code)
        form.addRow(QtGui.QLabel("Use 127.0.0.1 when Hermes runs on this PC (native).\n"
                                 "Use 0.0.0.0 + a token for WSL2 (NAT) or a remote Hermes via tunnel."))
        bb = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec_():
            p.SetString("Host", host.text().strip() or "127.0.0.1")
            p.SetInt("Port", port.value())
            p.SetString("Token", token.text().strip())
            p.SetBool("AutoStart", auto.isChecked())
            p.SetBool("AllowCode", code.isChecked())
            if rpc.is_running():
                rpc.stop()
                rpc.start()


COMMANDS = ["HermesCAD_StartRPC", "HermesCAD_StopRPC", "HermesCAD_Settings"]


def register_commands():
    Gui.addCommand("HermesCAD_StartRPC", StartRPC())
    Gui.addCommand("HermesCAD_StopRPC", StopRPC())
    Gui.addCommand("HermesCAD_Settings", Settings())


def autostart():
    from . import log, rpc
    try:
        if rpc.prefs()["autostart"]:
            rpc.start()
            log("autostart: bridge running on %s:%s" % (rpc._bridge.host, rpc._bridge.port))
        else:
            log("autostart disabled")
    except Exception as exc:
        log("autostart failed: %r" % (exc,))
        App.Console.PrintError("HermesCAD autostart failed: %s\n" % exc)


def schedule_autostart(delay_ms=1500):
    from PySide import QtCore
    QtCore.QTimer.singleShot(delay_ms, autostart)
