"""Hermes3D: lets the Hermes agent drive Blender (image -> 3D mesh -> clean -> export)."""
bl_info = {
    "name": "Hermes3D bridge",
    "author": "HermesCAD contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Edit > Preferences > Add-ons > Hermes3D",
    "description": "Local RPC bridge for the Hermes agent (MCP server hermes3d)",
    "doc_url": "https://github.com/andrianojson-code/hermescad",
    "tracker_url": "https://github.com/andrianojson-code/hermescad/issues",
    "category": "Interface",
}

import os
import time

import bpy

_LOG = None


def log(msg):
    global _LOG
    try:
        if _LOG is None:
            d = bpy.utils.user_resource("DATAFILES", path="hermes3d", create=True)
            _LOG = os.path.join(d, "hermes3d.log")
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _prefs():
    a = bpy.context.preferences.addons.get(__name__)
    return a.preferences if a else None


class Hermes3DPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    port: bpy.props.IntProperty(name="Port", default=9877, min=1024, max=65535)
    token: bpy.props.StringProperty(name="Token", default="", subtype="PASSWORD")
    autostart: bpy.props.BoolProperty(name="Start bridge with Blender", default=True)
    allow_code: bpy.props.BoolProperty(name="Allow execute_code from the agent", default=True)

    def draw(self, context):
        from . import bridge
        col = self.layout.column()
        col.prop(self, "port")
        col.prop(self, "token")
        col.prop(self, "autostart")
        col.prop(self, "allow_code")
        row = col.row()
        row.label(text="Bridge: %s" % ("running" if bridge.is_running() else "stopped"))
        row.operator("hermes3d.start")
        row.operator("hermes3d.stop")


class H3D_OT_start(bpy.types.Operator):
    bl_idname = "hermes3d.start"
    bl_label = "Start bridge"

    def execute(self, context):
        from . import bridge
        p = _prefs()
        try:
            bridge.start(port=p.port if p else 9877, token=p.token if p else "")
            self.report({"INFO"}, "Hermes3D bridge running")
        except OSError as exc:
            self.report({"ERROR"}, "Cannot start bridge: %s" % exc)
        return {"FINISHED"}


class H3D_OT_stop(bpy.types.Operator):
    bl_idname = "hermes3d.stop"
    bl_label = "Stop bridge"

    def execute(self, context):
        from . import bridge
        bridge.stop()
        return {"FINISHED"}


_classes = (Hermes3DPrefs, H3D_OT_start, H3D_OT_stop)


def _autostart():
    from . import bridge
    p = _prefs()
    if p is None or p.autostart:
        try:
            bridge.start(port=p.port if p else 9877, token=p.token if p else "",
                         use_timer=True if not bpy.app.background else "manual")
        except OSError as exc:
            log("autostart failed: %r" % (exc,))
    return None


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    log("register, Blender %s" % bpy.app.version_string)
    bpy.app.timers.register(_autostart, first_interval=1.0)


def unregister():
    from . import bridge
    bridge.stop()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
