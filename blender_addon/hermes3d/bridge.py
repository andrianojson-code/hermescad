"""XML-RPC bridge for Blender: `call(token, method, params_json) -> result_json`.

Socket on a background thread; work is executed on Blender's main thread via
bpy.app.timers. Browsers are refused (Origin / Content-Type / Host checks), same
policy as the HermesCAD FreeCAD bridge. Headless (blender -b / bpy module) calls
run directly on the server thread.
"""
import hmac
import json
import queue
import threading
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

DEFAULT_PORT = 9877
CALL_TIMEOUT = 900  # generation imports / remesh can be slow
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class _Guarded(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2", "/")

    def log_message(self, *args):
        pass

    def _refuse(self, why):
        from . import log
        log("refused request from %s: %s" % (self.client_address[0], why))
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
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
    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, token="", use_timer=True):
        self.host, self.port, self.token = host, int(port), token or ""
        self.use_timer = use_timer
        self.jobs = queue.Queue()
        self.server = None
        self.thread = None

    def start(self):
        if self.server is not None:
            return
        self.server = SimpleXMLRPCServer((self.host, self.port), requestHandler=_Guarded,
                                         allow_none=True, logRequests=False)
        self.server.register_function(self._call, "call")
        self.thread = threading.Thread(target=self.server.serve_forever, name="Hermes3D-RPC",
                                       daemon=True)
        self.thread.start()
        if self.use_timer is True:
            import bpy
            if not bpy.app.timers.is_registered(self._pump):
                bpy.app.timers.register(self._pump, first_interval=0.1, persistent=True)
        # use_timer == "manual": the host loop calls pump() on the main thread (tests, blender -b)
        from . import log
        log("bridge listening on %s:%d" % (self.host, self.port))

    def pump(self):
        return self._pump()

    def stop(self):
        if self.use_timer is True:
            import bpy
            if bpy.app.timers.is_registered(self._pump):
                bpy.app.timers.unregister(self._pump)
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    @property
    def running(self):
        return self.server is not None

    def _call(self, token, method, params_json):
        from . import service
        if self.token and not hmac.compare_digest(str(token or ""), self.token):
            return json.dumps({"ok": False, "error": "bad token"})
        try:
            params = json.loads(params_json) if params_json else {}
        except ValueError as exc:
            return json.dumps({"ok": False, "error": "params must be JSON: %s" % exc})
        if not self.use_timer:
            return json.dumps(service.dispatch(method, params), ensure_ascii=True)
        box, done = {}, threading.Event()
        self.jobs.put((method, params, box, done))
        if not done.wait(CALL_TIMEOUT):
            return json.dumps({"ok": False, "error": "timed out waiting for Blender main thread"})
        return json.dumps(box["result"], ensure_ascii=True)

    def _pump(self):
        from . import service
        while True:
            try:
                method, params, box, done = self.jobs.get_nowait()
            except queue.Empty:
                return 0.05
            try:
                box["result"] = service.dispatch(method, params)
            except BaseException as exc:
                box["result"] = {"ok": False, "error": repr(exc)}
            done.set()


_bridge = None


def start(host="127.0.0.1", port=DEFAULT_PORT, token="", use_timer=True):
    global _bridge
    if _bridge is not None and _bridge.running:
        return _bridge
    _bridge = Bridge(host, port, token, use_timer)
    _bridge.start()
    return _bridge


def stop():
    global _bridge
    if _bridge is not None:
        _bridge.stop()
        _bridge = None


def is_running():
    return _bridge is not None and _bridge.running
