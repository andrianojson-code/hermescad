"""XML-RPC bridge: one method `call(token, method, params_json) -> result_json`.

The socket lives on a background thread; FreeCAD work is marshalled onto the
GUI thread through a queue drained by a Qt timer (FreeCAD is not thread-safe).
Headless (freecadcmd), calls run directly on the server thread.
"""
import hmac
import json
import queue
import threading
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

import FreeCAD as App

from . import service

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/HermesCAD"
DEFAULT_PORT = 9876
CALL_TIMEOUT = 300


def prefs():
    p = App.ParamGet(PARAM_PATH)
    return {"host": p.GetString("Host", "127.0.0.1"),
            "port": p.GetInt("Port", DEFAULT_PORT) or DEFAULT_PORT,
            "token": p.GetString("Token", ""),
            # installing the addon means "I want the bridge"; safe because of _Guarded below
            "autostart": p.GetBool("AutoStart", True),
            "allow_code": p.GetBool("AllowCode", True)}


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class _Guarded(SimpleXMLRPCRequestHandler):
    """Blocks browsers: any web page can POST to localhost ("simple" text/plain request,
    no CORS preflight) and DNS-rebinding pages can even look same-origin. Real XML-RPC
    clients send Content-Type text/xml and never an Origin header; browsers always send
    Origin on POST and cannot send text/xml cross-origin without a preflight we refuse."""
    rpc_paths = ("/RPC2", "/")

    def log_message(self, *args):
        pass

    def _refuse(self, why):
        try:
            import hermescad_core
            hermescad_core.log("refused request from %s: %s" % (self.client_address[0], why))
        except Exception:
            pass
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):  # CORS preflight: always no
        self._refuse("CORS preflight")

    def do_POST(self):
        if self.headers.get("Origin") is not None:
            return self._refuse("browser Origin header %r" % self.headers.get("Origin"))
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "text/xml":
            return self._refuse("content-type %r" % ctype)
        if self.server.server_address[0] in ("127.0.0.1", "::1"):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            if host not in _LOCAL_HOSTS:
                return self._refuse("Host %r (DNS rebinding?)" % host)
        return SimpleXMLRPCRequestHandler.do_POST(self)


class Bridge(object):
    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, token="", use_gui=None):
        self.host, self.port, self.token = host, int(port), token or ""
        self.use_gui = App.GuiUp if use_gui is None else use_gui
        self.jobs = queue.Queue()
        self.server = None
        self.thread = None
        self.timer = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if self.server is not None:
            return
        self.server = SimpleXMLRPCServer((self.host, self.port), requestHandler=_Guarded,
                                         allow_none=True, logRequests=False)
        self.server.register_function(self._call, "call")
        self.server.register_function(lambda: "pong", "ping")
        self.thread = threading.Thread(target=self.server.serve_forever, name="HermesCAD-RPC",
                                       daemon=True)
        self.thread.start()
        if self.use_gui:
            from PySide import QtCore
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._pump)
            self.timer.start(25)
        App.Console.PrintMessage("HermesCAD RPC listening on %s:%d%s\n"
                                 % (self.host, self.port, " (token required)" if self.token else ""))
        if self.host not in ("127.0.0.1", "localhost") and not self.token:
            App.Console.PrintWarning("HermesCAD: RPC is reachable from the network WITHOUT a token. "
                                     "Set a token in preferences.\n")

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        App.Console.PrintMessage("HermesCAD RPC stopped\n")

    @property
    def running(self):
        return self.server is not None

    # ------------------------------------------------------------- calls
    def _call(self, token, method, params_json):
        if self.token and not hmac.compare_digest(str(token or ""), self.token):
            return json.dumps({"ok": False, "error": "bad token"})
        try:
            params = json.loads(params_json) if params_json else {}
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "params must be JSON: %s" % exc})
        if not self.use_gui:
            return json.dumps(service.dispatch(method, params), ensure_ascii=True)
        box = {}
        done = threading.Event()
        self.jobs.put((method, params, box, done))
        if not done.wait(CALL_TIMEOUT):
            return json.dumps({"ok": False, "error": "timed out waiting for FreeCAD GUI thread "
                                                     "(is a modal dialog open?)"})
        return json.dumps(box["result"], ensure_ascii=True)

    def _pump(self):
        while True:
            try:
                method, params, box, done = self.jobs.get_nowait()
            except queue.Empty:
                return
            try:
                box["result"] = service.dispatch(method, params)
            except BaseException as exc:  # never let the timer die
                box["result"] = {"ok": False, "error": repr(exc)}
                try:
                    import hermescad_core
                    hermescad_core.log("pump error in %s: %r" % (method, exc))
                except Exception:
                    pass
            done.set()


_bridge = None


def start(host=None, port=None, token=None):
    global _bridge
    if _bridge is not None and _bridge.running:
        return _bridge
    p = prefs()
    _bridge = Bridge(host or p["host"], port or p["port"], p["token"] if token is None else token)
    _bridge.start()
    return _bridge


def stop():
    global _bridge
    if _bridge is not None:
        _bridge.stop()
        _bridge = None


def is_running():
    return _bridge is not None and _bridge.running
