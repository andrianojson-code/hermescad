"""Image -> 3D mesh generators (pluggable). Runs inside the MCP server process.

Backends
  hf:hunyuan3d   free (default), Space tencent/Hunyuan3D-2.1 shape model (~30 s, white mesh GLB);
                 falls back to tencent/Hunyuan3D-2, then TripoSG.
  hf:triposg     free, Hugging Face Space VAST-AI/TripoSG (shape only, GLB). Uses HF_TOKEN if set
                 (a free HF account gives a bigger daily GPU quota).
  hf:<owner/space> any other Space: endpoints are discovered with view_api(); see hf_space_api().
  tripo          paid/credit API (TRIPO_API_KEY), textured GLB, fast and robust.
  file           not a generator: the user made the model elsewhere and gives a .glb/.obj/.stl path.
No GPU is needed locally for any of these.
"""
import json
import os
import shutil
import time
import urllib.request

OUT_DIR = os.environ.get("HERMES3D_OUT") or os.path.join(os.path.expanduser("~"), "Hermes3D", "generated")


class GenError(RuntimeError):
    pass


def _out(name, ext=".glb"):
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, "%s_%s%s" % (name, time.strftime("%Y%m%d_%H%M%S"), ext))


def _client(space):
    try:
        from gradio_client import Client
    except ImportError:
        raise GenError("gradio_client is not installed in the MCP server venv (pip install gradio_client)")
    token = os.environ.get("HF_TOKEN") or None
    try:
        return Client(space, token=token, verbose=False)
    except TypeError:  # older gradio_client
        return Client(space, hf_token=token, verbose=False)
    except Exception as exc:
        raise GenError("cannot reach Hugging Face Space %s: %s (no internet / HF blocked? try a VPN, "
                       "backend 'tripo', or generate on a website and use backend 'file')" % (space, exc))


def space_api(space):
    c = _client(space)
    info = c.view_api(return_format="dict", print_info=False)
    eps = {}
    for name, ep in (info.get("named_endpoints") or {}).items():
        eps[name] = {"params": [(p.get("parameter_name") or p.get("label"),
                                 (p.get("python_type") or {}).get("type"),
                                 p.get("parameter_default")) for p in ep.get("parameters", [])],
                     "returns": [(r.get("label"), (r.get("python_type") or {}).get("type"))
                                 for r in ep.get("returns", [])]}
    return eps


def _pick(eps, *needles):
    for n in eps:
        low = n.lower()
        if all(k in low for k in needles):
            return n
    return None


def _file_of(res):
    """Find a local mesh file path in a gradio result (str, dict, tuple...)."""
    if isinstance(res, (list, tuple)):
        for r in res:
            f = _file_of(r)
            if f:
                return f
        return None
    if isinstance(res, dict):
        for k in ("value", "path", "name", "file"):
            if k in res:
                f = _file_of(res[k])
                if f:
                    return f
        return None
    if isinstance(res, str) and os.path.isfile(res) and \
            os.path.splitext(res)[1].lower() in (".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx"):
        return res
    return None


def gen_triposg(image_path, name, faces=100000, steps=50, seed=0):
    from gradio_client import handle_file
    space = "VAST-AI/TripoSG"
    c = _client(space)
    try:
        eps = space_api(space)
    except Exception:
        eps = {}
    seg_ep = _pick(eps, "segment") or "/run_segmentation"
    gen_ep = _pick(eps, "image_to_3d") or _pick(eps, "3d") or "/image_to_3d"
    if "/start_session" in eps:  # the web UI calls this on page load; it creates the output dir
        try:
            c.predict(api_name="/start_session")
        except Exception:
            pass
    try:
        seg = c.predict(handle_file(image_path), api_name=seg_ep)
        seg_path = seg if isinstance(seg, str) else _first_image(seg)
        res = c.predict(handle_file(seg_path), int(seed), int(steps), 7.0, True, int(faces),
                        api_name=gen_ep)
    except Exception as exc:
        raise GenError("TripoSG Space failed: %s: %s. Endpoints: %s. If it mentions quota/ZeroGPU, wait or "
                       "set HF_TOKEN; otherwise try another backend." % (type(exc).__name__, _why(exc), list(eps)))
    f = _file_of(res)
    if not f:
        raise GenError("TripoSG returned no mesh file: %r" % (res,))
    dst = _out(name, os.path.splitext(f)[1])
    shutil.copy(f, dst)
    return dst


def _why(exc):
    msg = str(exc).strip()
    if not msg and exc.__cause__ is not None:
        msg = "%s: %s" % (type(exc.__cause__).__name__, exc.__cause__)
    if not msg:
        msg = repr(exc)
    return msg[:800]


def _first_image(res):
    if isinstance(res, (list, tuple)):
        for r in res:
            p = _first_image(r)
            if p:
                return p
    if isinstance(res, dict):
        for k in ("path", "value", "name"):
            if isinstance(res.get(k), str):
                return res[k]
    if isinstance(res, str):
        return res
    return None


def gen_hf_generic(space, image_path, name, api_name=None, extra_args=None):
    """Call any Space endpoint that takes an image first and returns a mesh file."""
    from gradio_client import handle_file
    c = _client(space)
    eps = space_api(space)
    ep = api_name or _pick(eps, "image", "3d") or _pick(eps, "generat") or _pick(eps, "shape")
    if not ep:
        raise GenError("no obvious image->3D endpoint in %s; endpoints: %s" % (space, json.dumps(eps)[:1500]))
    args = [handle_file(image_path)] + list(extra_args or [])
    try:
        res = c.predict(*args, api_name=ep)
    except Exception as exc:
        raise GenError("%s %s failed: %s; endpoints: %s" % (space, ep, _why(exc), json.dumps(eps)[:1500]))
    f = _file_of(res)
    if not f:
        raise GenError("%s returned no mesh file: %r" % (space, res))
    dst = _out(name, os.path.splitext(f)[1])
    shutil.copy(f, dst)
    return dst


HUNYUAN_SPACES = ("tencent/Hunyuan3D-2.1", "tencent/Hunyuan3D-2")


def gen_hunyuan(image_path, name, steps=30, octree_resolution=256, seed=1234, space=None):
    from gradio_client import handle_file
    errors = []
    for sp in ([space] if space else HUNYUAN_SPACES):
        try:
            c = _client(sp)
            kw = dict(image=handle_file(image_path), steps=int(steps), guidance_scale=5.0,
                      seed=int(seed), octree_resolution=int(octree_resolution),
                      check_box_rembg=True, num_chunks=8000, randomize_seed=False)
            if sp == "tencent/Hunyuan3D-2":
                kw["caption"] = None
            res = c.predict(api_name="/shape_generation", **kw)
            f = _file_of(res)
            if not f:
                raise GenError("no mesh in result %r" % (res,))
            dst = _out(name, os.path.splitext(f)[1])
            shutil.copy(f, dst)
            return dst, sp
        except Exception as exc:
            errors.append("%s: %s" % (sp, _why(exc)))
    raise GenError("Hunyuan3D Spaces failed: " + " | ".join(errors))


# ---------------------------------------------------------------- Tripo API

TRIPO = "https://api.tripo3d.ai/v2/openapi"


def _tripo_req(method, url, key, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=dict({"Authorization": "Bearer " + key}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def gen_tripo(image_path, name, timeout_s=600):
    key = os.environ.get("TRIPO_API_KEY")
    if not key:
        raise GenError("TRIPO_API_KEY is not set in the hermes3d MCP server env")
    import uuid
    boundary = uuid.uuid4().hex
    fname = os.path.basename(image_path)
    ext = os.path.splitext(fname)[1].lstrip(".").lower() or "png"
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
             "Content-Type: image/%s\r\n\r\n" % (boundary, fname, "jpeg" if ext == "jpg" else ext)).encode()
            + open(image_path, "rb").read() + ("\r\n--%s--\r\n" % boundary).encode())
    up = _tripo_req("POST", TRIPO + "/upload", key, body,
                    {"Content-Type": "multipart/form-data; boundary=" + boundary})
    token = (up.get("data") or {}).get("image_token") or (up.get("data") or {}).get("file_token")
    if not token:
        raise GenError("Tripo upload failed: %s" % up)
    task = _tripo_req("POST", TRIPO + "/task", key,
                      json.dumps({"type": "image_to_model",
                                  "file": {"type": "jpg" if ext == "jpeg" else ext,
                                           "file_token": token}}).encode(),
                      {"Content-Type": "application/json"})
    tid = (task.get("data") or {}).get("task_id")
    if not tid:
        raise GenError("Tripo task not created: %s" % task)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = _tripo_req("GET", TRIPO + "/task/" + tid, key).get("data") or {}
        if st.get("status") == "success":
            out = st.get("output") or {}
            url = out.get("pbr_model") or out.get("model") or out.get("base_model")
            if not url:
                raise GenError("Tripo finished without model url: %s" % st)
            dst = _out(name, ".glb")
            urllib.request.urlretrieve(url, dst)
            return dst
        if st.get("status") in ("failed", "cancelled", "banned", "expired", "unknown"):
            raise GenError("Tripo task %s: %s" % (st.get("status"), st))
        time.sleep(4)
    raise GenError("Tripo task timed out after %ds" % timeout_s)


def generate(image_path, backend="auto", name="Model", **kw):
    if not os.path.isfile(image_path):
        raise GenError("image not found: %s" % image_path)
    b = (backend or "auto").lower()
    if b == "tripo" or (b == "auto" and os.environ.get("TRIPO_API_KEY")):
        return gen_tripo(image_path, name), "tripo"
    if b in ("auto", "hf:hunyuan3d", "hunyuan3d", "hf:hunyuan"):
        errors = []
        try:
            path, sp = gen_hunyuan(image_path, name)
            return path, "hf:" + sp
        except GenError as exc:
            errors.append(str(exc))
            if b != "auto":
                raise
        try:
            return gen_triposg(image_path, name, **{k: v for k, v in kw.items()
                                                     if k in ("faces", "steps", "seed")}), "hf:triposg"
        except GenError as exc:
            errors.append(str(exc))
        raise GenError("all free generators failed: " + " || ".join(errors) +
                       " - try later (daily GPU quota; HF_TOKEN raises it), backend 'tripo', or "
                       "generate on a website and use import_model.")
    if b in ("hf:triposg", "triposg"):
        return gen_triposg(image_path, name, **{k: v for k, v in kw.items()
                                                 if k in ("faces", "steps", "seed")}), b
    if b.startswith("hf:"):
        return gen_hf_generic(backend[3:], image_path, name, kw.get("api_name"), kw.get("extra_args")), b
    raise GenError("unknown backend %r (auto, hf:hunyuan3d, hf:triposg, hf:<owner/space>, tripo)" % backend)
