"""Regression tests for the 2026-10-16 audit. Needs the headless bridge on 127.0.0.1:9876."""
import json, subprocess, sys, xmlrpc.client
fails = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: fails.append(m)
BODY = ('<?xml version="1.0"?><methodCall><methodName>call</methodName><params>'
        '<param><value><string></string></value></param><param><value><string>status</string></value></param>'
        '<param><value><string>{}</string></value></param></params></methodCall>')
def curl(*h):
    args = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST", "http://127.0.0.1:9876/RPC2", "--data", BODY]
    for x in h: args += ["-H", x]
    return subprocess.run(args, capture_output=True, text=True).stdout
check(curl("Content-Type: text/plain") == "403", "browser-style text/plain refused")
check(curl("Content-Type: text/xml", "Origin: https://evil.example") == "403", "request with Origin refused")
check(curl("Content-Type: text/xml", "Host: evil.example:9876") == "403", "foreign Host (DNS rebinding) refused")
check(curl("Content-Type: text/xml") == "200", "plain XML-RPC client accepted")
p = xmlrpc.client.ServerProxy("http://127.0.0.1:9876/RPC2")
def c(m, **k): return json.loads(p.call("", m, json.dumps(k)))
c("new_document", name="Audit2")
r = c("build_part", spec={"name": "Derived", "parameters": {"L": 60, "half": "L/2"},
      "features": [{"type": "pad", "profile": {"type": "rect", "w": "L", "h": 20}, "length": 5},
                   {"type": "hole", "offset": 5, "profile": {"type": "circle", "d": 4, "x": "half-5"}}]})
check(r["ok"], "derived build")
r = c("set_parameters", part="Derived", values={"L": 100})["result"]
check(r["parameters"]["half"] == 50 and r["mode"].startswith("updated"), "derived half follows L live: %s %s" % (r["parameters"], r["mode"]))
spec = c("get_spec", part="Derived")["result"]["spec"]
check(spec["parameters"]["half"] == "L/2", "formula kept in spec")
r = c("build_part", spec={"name": "Baked", "parameters": {"L": 60, "half": "L/2"},
      "features": [{"type": "pad", "profile": {"type": "polygon", "points": [[0, 0], ["half", 0], ["half", 10], [0, 10]]}, "length": 5}]})
r = c("set_parameters", part="Baked", values={"L": 100})["result"]
check(r["mode"].startswith("rebuilt") and r["bbox_mm"]["size"][0] == 50, "baked via derived param rebuilds: %s" % r["mode"])
r = c("export", path="/tmp/audit_multi.stl")
check(not r["ok"] and "several parts" in r["error"], "multi-part export needs part=")
r = c("export", path="/tmp/audit_one.stl", part="Derived")
check(r["ok"] and r["result"]["objects"] == ["Derived"], "export single part")
r = c("export", path="/tmp/audit_all.stl", part="all")
check(r["ok"] and len(r["result"]["objects"]) == 2, "export all on request")
r = c("build_part", spec={"name": "BigFillet", "features": [{"type": "pad", "profile": {"type": "rect", "w": 10, "h": 10}, "length": 2}, {"type": "fillet", "edges": "all", "radius": 5}]})
check(not r["ok"] and "hint" in r["error"], "fillet failure has hint")
print("RESULT:", "OK" if not fails else "FAILED %d" % len(fails))
