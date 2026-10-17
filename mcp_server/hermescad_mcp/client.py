"""Thin client for the HermesCAD RPC bridge running inside FreeCAD."""
import json
import os
import socket
import xmlrpc.client


class BridgeError(RuntimeError):
    pass


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class Bridge:
    def __init__(self, host=None, port=None, token=None, timeout=None):
        self.host = host or os.environ.get("HERMESCAD_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("HERMESCAD_PORT", "9876"))
        self.token = token if token is not None else os.environ.get("HERMESCAD_TOKEN", "")
        self.timeout = float(timeout or os.environ.get("HERMESCAD_TIMEOUT", "300"))

    @property
    def url(self):
        return "http://%s:%d/RPC2" % (self.host, self.port)

    def call(self, method, **params):
        proxy = xmlrpc.client.ServerProxy(self.url, allow_none=True,
                                          transport=_TimeoutTransport(self.timeout))
        try:
            raw = proxy.call(self.token, method, json.dumps(params))
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            raise BridgeError(
                "Cannot reach FreeCAD at %s (%s). Open FreeCAD, switch to the HermesCAD "
                "workbench and press 'Start Hermes bridge' (or enable autostart)." % (self.url, exc))
        except xmlrpc.client.Fault as exc:
            raise BridgeError("RPC fault: %s" % exc.faultString)
        res = json.loads(raw)
        if not res.get("ok"):
            msg = res.get("error", "unknown error")
            if res.get("traceback"):
                msg += "\n" + res["traceback"]
            raise BridgeError(msg)
        return res["result"] if set(res) == {"ok", "result"} else res
