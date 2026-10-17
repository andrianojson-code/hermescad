"""Build a parametric PartDesign body from a HermesCAD part spec (JSON/dict).

Pure App-level code (no GUI), so it runs in FreeCAD and in freecadcmd alike.
See docs/SPEC.md for the format. Main ideas:
  * every spec parameter becomes an aliased cell in a Params spreadsheet;
  * rect/circle sizes and positions, pad/pocket lengths, revolve angles and
    fillet/chamfer sizes are bound to the sheet by expressions, so editing a
    cell in FreeCAD (or via set_parameters) updates the model;
  * polygons, slots, patterns are "baked": their coordinates are computed from
    the parameters at build time; set_parameters rebuilds when those change;
  * fillet/chamfer edges are chosen by geometric selectors and re-resolved
    after every parameter change (avoids topological-naming breakage).
"""
import json
import math

import FreeCAD as App
import Part
import Sketcher

from . import expr as X

V = App.Vector
PROP_GROUP = "HermesCAD"


class BuildError(Exception):
    pass


# ----------------------------------------------------------------- helpers

def _origin_feature(body, role):
    for o in body.Origin.OriginFeatures:
        if getattr(o, "Role", "") == role or o.Name.startswith(role):
            return o
    raise BuildError("body origin has no %s" % role)


def _set_support(obj, support):
    if hasattr(obj, "AttachmentSupport"):
        obj.AttachmentSupport = support
    else:  # FreeCAD < 1.0
        obj.Support = support


def _add_prop(obj, ptype, name, value, doc=""):
    if name not in obj.PropertiesList:
        obj.addProperty(ptype, name, PROP_GROUP, doc)
    setattr(obj, name, value)


def _safe(name):
    out = "".join(c if c.isalnum() or c == "_" else "_" for c in str(name))
    return out if out and not out[0].isdigit() else "P_" + out


class Ctx(object):
    def __init__(self, doc, body, sheet, params):
        self.doc, self.body, self.sheet = doc, body, sheet
        self.params = params
        self.baked = set()  # params that geometry depends on without live binding
        self.aux = []  # helper bodies (trim tools) owned by this part
        self.warnings = []

    # value -> float, and FreeCAD expression if it depends on parameters
    def resolve(self, v, what):
        if v is None:
            raise BuildError("missing value for %s" % what)
        try:
            val = X.evaluate(v, self.params)
            names = X.names_in(v) & set(self.params) if isinstance(v, str) else set()
            fc = X.to_freecad_expr(v, self.params, self.sheet.Name) if names else None
        except X.ExprError as exc:
            raise BuildError("%s: %s" % (what, exc))
        return val, fc, names

    def num(self, v, what, bake=True):
        val, _fc, names = self.resolve(v, what)
        if bake:
            self.baked |= names
        return val

    def bind(self, obj, prop, v, what):
        val, fc, _names = self.resolve(v, what)
        setattr(obj, prop, val)
        if fc:
            obj.setExpression(prop, fc)
        return val


# ---------------------------------------------------------------- sketches

PLANES = {"XY": "XY_Plane", "XZ": "XZ_Plane", "YZ": "YZ_Plane",
          "TOP": "XY_Plane", "FRONT": "XZ_Plane", "RIGHT": "YZ_Plane"}


class SketchMaker(object):
    def __init__(self, ctx, fid, sketch):
        self.ctx, self.fid, self.s = ctx, fid, sketch
        self.n = 0

    def _name(self, tag):
        self.n += 1
        return "%s_%s%d" % (self.fid, tag, self.n)

    def con(self, c, value=None, tag=None):
        """Add constraint; if value is a spec value, set its datum (+ expression)."""
        idx = self.s.addConstraint(c)
        if value is not None:
            val, fc, _ = self.ctx.resolve(value, "%s constraint" % self.fid)
            if fc:
                name = self._name(tag or "c")
                self.s.renameConstraint(idx, name)
                self.s.setExpression("Constraints.%s" % name, fc)
        return idx

    def position(self, geo, pos, x, y):
        """Constrain point (geo,pos) to x,y relative to the sketch origin."""
        for axis, v, ext_axis in (("DistanceX", x, -2), ("DistanceY", y, -1)):
            val, fc, _ = self.ctx.resolve(v, "%s position" % self.fid)
            if fc is None and abs(val) < 1e-12:
                # on the opposite axis: x=0 -> on V axis (-2), y=0 -> on H axis (-1)
                self.s.addConstraint(Sketcher.Constraint("PointOnObject", geo, pos, ext_axis))
            else:
                self.con(Sketcher.Constraint(axis, -1, 1, geo, pos, val), v, axis[-1].lower())

    # --- live (expression-bound) profiles
    def rect(self, p):
        w = self.ctx.num(p.get("w", p.get("width")), "rect.w", bake=False)
        h = self.ctx.num(p.get("h", p.get("height")), "rect.h", bake=False)
        cx = self.ctx.num(p.get("x", 0), "rect.x", bake=False)
        cy = self.ctx.num(p.get("y", 0), "rect.y", bake=False)
        if w <= 0 or h <= 0:
            raise BuildError("%s: rect w/h must be > 0 (got %g x %g)" % (self.fid, w, h))
        pts = [V(cx - w / 2, cy - h / 2, 0), V(cx + w / 2, cy - h / 2, 0),
               V(cx + w / 2, cy + h / 2, 0), V(cx - w / 2, cy + h / 2, 0)]
        g = [self.s.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
             for i in range(4)]
        for i in range(4):
            self.s.addConstraint(Sketcher.Constraint("Coincident", g[i], 2, g[(i + 1) % 4], 1))
        self.s.addConstraint(Sketcher.Constraint("Horizontal", g[0]))
        self.s.addConstraint(Sketcher.Constraint("Horizontal", g[2]))
        self.s.addConstraint(Sketcher.Constraint("Vertical", g[1]))
        self.s.addConstraint(Sketcher.Constraint("Vertical", g[3]))
        self.con(Sketcher.Constraint("DistanceX", g[0], 1, g[0], 2, w),
                 p.get("w", p.get("width")), "w")
        self.con(Sketcher.Constraint("DistanceY", g[1], 1, g[1], 2, h),
                 p.get("h", p.get("height")), "h")
        c = self.s.addGeometry(Part.Point(V(cx, cy, 0)), True)
        self.s.addConstraint(Sketcher.Constraint("Symmetric", g[0], 1, g[2], 1, c, 1))
        self.position(c, 1, p.get("x", 0), p.get("y", 0))

    def circle(self, p):
        if "d" in p or "diameter" in p:
            dv = p.get("d", p.get("diameter"))
        elif "r" in p or "radius" in p:
            rv = p.get("r", p.get("radius"))
            dv = "2*(%s)" % rv if isinstance(rv, str) else 2 * float(rv)
        else:
            raise BuildError("%s: circle needs d or r" % self.fid)
        d = self.ctx.num(dv, "circle.d", bake=False)
        if d <= 0:
            raise BuildError("%s: circle diameter must be > 0" % self.fid)
        cx = self.ctx.num(p.get("x", 0), "circle.x", bake=False)
        cy = self.ctx.num(p.get("y", 0), "circle.y", bake=False)
        g = self.s.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), d / 2), False)
        self.con(Sketcher.Constraint("Diameter", g, d), dv, "d")
        self.position(g, 3, p.get("x", 0), p.get("y", 0))

    # --- baked profiles
    def _closed(self, pts):
        n = len(pts)
        if n < 3:
            raise BuildError("%s: polygon needs >= 3 points" % self.fid)
        g = [self.s.addGeometry(Part.LineSegment(V(*pts[i], 0), V(*pts[(i + 1) % n], 0)), False)
             for i in range(n)]
        for i in range(n):
            self.s.addConstraint(Sketcher.Constraint("Coincident", g[i], 2, g[(i + 1) % n], 1))

    def polygon(self, p):
        pts = []
        for i, xy in enumerate(p.get("points") or []):
            pts.append((self.ctx.num(xy[0], "polygon.points[%d].x" % i),
                        self.ctx.num(xy[1], "polygon.points[%d].y" % i)))
        # drop duplicate closing point
        if len(pts) > 3 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
            pts.pop()
        self._closed(pts)

    def regular_polygon(self, p):
        n = int(self.ctx.num(p.get("n", 6), "regular_polygon.n"))
        if "across_flats" in p:
            r = self.ctx.num(p["across_flats"], "across_flats") / 2 / math.cos(math.pi / n)
        else:
            r = self.ctx.num(p.get("d"), "regular_polygon.d") / 2
        cx, cy = self.ctx.num(p.get("x", 0), "x"), self.ctx.num(p.get("y", 0), "y")
        a0 = math.radians(self.ctx.num(p.get("angle", 0), "angle"))
        self._closed([(cx + r * math.cos(a0 + 2 * math.pi * i / n),
                       cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)])

    def slot(self, p):
        L = self.ctx.num(p.get("length"), "slot.length")
        w = self.ctx.num(p.get("w", p.get("width")), "slot.w")
        cx, cy = self.ctx.num(p.get("x", 0), "x"), self.ctx.num(p.get("y", 0), "y")
        ang = math.radians(self.ctx.num(p.get("angle", 0), "angle"))
        r, c = w / 2, (L - w) / 2
        if r <= 0 or c <= 0:
            raise BuildError("%s: slot needs length > w > 0" % self.fid)
        ux, uy = math.cos(ang), math.sin(ang)
        c1 = V(cx + c * ux, cy + c * uy, 0)
        c2 = V(cx - c * ux, cy - c * uy, 0)
        a1 = self.s.addGeometry(Part.ArcOfCircle(Part.Circle(c1, V(0, 0, 1), r),
                                                 ang - math.pi / 2, ang + math.pi / 2), False)
        a2 = self.s.addGeometry(Part.ArcOfCircle(Part.Circle(c2, V(0, 0, 1), r),
                                                 ang + math.pi / 2, ang + 3 * math.pi / 2), False)
        nx, ny = -uy * r, ux * r
        top = self.s.addGeometry(Part.LineSegment(V(c1.x + nx, c1.y + ny, 0),
                                                  V(c2.x + nx, c2.y + ny, 0)), False)
        bot = self.s.addGeometry(Part.LineSegment(V(c2.x - nx, c2.y - ny, 0),
                                                  V(c1.x - nx, c1.y - ny, 0)), False)
        for a, pa, b, pb in ((a1, 2, top, 1), (top, 2, a2, 1), (a2, 2, bot, 1), (bot, 2, a1, 1)):
            self.s.addConstraint(Sketcher.Constraint("Coincident", a, pa, b, pb))

    def circle_pattern(self, p):
        n = int(self.ctx.num(p.get("count"), "circle_pattern.count"))
        pcd = self.ctx.num(p.get("pcd"), "circle_pattern.pcd")
        cx, cy = self.ctx.num(p.get("x", 0), "x"), self.ctx.num(p.get("y", 0), "y")
        a0 = self.ctx.num(p.get("start_angle", 0), "start_angle")
        for i in range(n):
            a = math.radians(a0 + 360.0 * i / n)
            self.circle({"d": p.get("d"), "x": cx + pcd / 2 * math.cos(a),
                         "y": cy + pcd / 2 * math.sin(a)})

    def grid(self, p):
        """Rectangular array of circles: nx x ny, pitch dx/dy, centred on x,y."""
        nx = int(self.ctx.num(p.get("nx", 1), "grid.nx"))
        ny = int(self.ctx.num(p.get("ny", 1), "grid.ny"))
        dx = self.ctx.num(p.get("dx", 0), "grid.dx")
        dy = self.ctx.num(p.get("dy", 0), "grid.dy")
        cx, cy = self.ctx.num(p.get("x", 0), "x"), self.ctx.num(p.get("y", 0), "y")
        for i in range(nx):
            for j in range(ny):
                self.circle({"d": p.get("d"), "x": cx + (i - (nx - 1) / 2.0) * dx,
                             "y": cy + (j - (ny - 1) / 2.0) * dy})

    def _pt(self, xy, what):
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise BuildError("%s: %s must be [x, y]" % (self.fid, what))
        return V(self.ctx.num(xy[0], what + ".x"), self.ctx.num(xy[1], what + ".y"), 0)

    def _pts(self, pts, what):
        out = [self._pt(p, "%s[%d]" % (what, i)) for i, p in enumerate(pts or [])]
        clean = [out[0]] if out else []
        for p in out[1:]:  # drop consecutive duplicates (they break splines)
            if (p - clean[-1]).Length > 1e-9:
                clean.append(p)
        return clean

    def path(self, p):
        """Closed outline of lines, 3-point arcs and splines.
        {"type":"path","start":[x,y],"segments":[{"line":[x,y]},
           {"arc":{"through":[x,y],"to":[x,y]}}, {"spline":[[x,y],...,[x_end,y_end]]}]}
        The outline is closed back to start automatically (with a line)."""
        cur = self._pt(p.get("start"), "path.start")
        start = cur
        segs = p.get("segments") or []
        if not segs:
            raise BuildError("%s: path needs segments" % self.fid)
        geos = []
        for i, sg in enumerate(segs):
            what = "path.segments[%d]" % i
            if "line" in sg:
                nxt = self._pt(sg["line"], what + ".line")
                if (nxt - cur).Length > 1e-9:
                    geos.append(Part.LineSegment(cur, nxt))
            elif "arc" in sg:
                a = sg["arc"]
                mid = self._pt(a.get("through"), what + ".arc.through")
                nxt = self._pt(a.get("to"), what + ".arc.to")
                try:
                    geos.append(Part.Arc(cur, mid, nxt))
                except Exception:
                    raise BuildError("%s: arc points are collinear or coincide" % what)
            elif "spline" in sg:
                pts = [cur] + self._pts(sg["spline"], what + ".spline")
                if len(pts) < 2:
                    raise BuildError("%s: spline needs points" % what)
                nxt = pts[-1]
                if len(pts) == 2:
                    geos.append(Part.LineSegment(cur, nxt))
                else:
                    bs = Part.BSplineCurve()
                    bs.interpolate(pts)
                    geos.append(bs)
            else:
                raise BuildError("%s: segment must be line, arc or spline" % what)
            cur = nxt
        if (cur - start).Length > 1e-6:
            geos.append(Part.LineSegment(cur, start))
        if len(geos) < 2:
            raise BuildError("%s: path is degenerate" % self.fid)
        self._add_chain(geos)

    def spline(self, p):
        """Smooth closed outline through points (e.g. from extract_contours as_spline=true)."""
        pts = self._pts(p.get("points"), "spline.points")
        if len(pts) > 3 and (pts[0] - pts[-1]).Length < 1e-6:
            pts.pop()
        if len(pts) < 4:
            raise BuildError("%s: closed spline needs >= 4 points" % self.fid)
        bs = Part.BSplineCurve()
        try:
            bs.interpolate(pts, PeriodicFlag=True)
        except Exception as exc:
            raise BuildError("%s: cannot fit a closed spline through the points (%s); "
                             "use fewer, well-spread points" % (self.fid, exc))
        self.s.addGeometry(bs, False)

    def _add_chain(self, geos):
        idx = [self.s.addGeometry(g, False) for g in geos]
        n = len(idx)
        for i in range(n):  # endpoints were built coincident; constrain so the solver keeps them
            try:
                self.s.addConstraint(Sketcher.Constraint("Coincident", idx[i], 2, idx[(i + 1) % n], 1))
            except Exception:
                pass

    def add(self, prof):
        kind = prof.get("type")
        fn = {"rect": self.rect, "rectangle": self.rect, "circle": self.circle,
              "polygon": self.polygon, "regular_polygon": self.regular_polygon,
              "slot": self.slot, "circle_pattern": self.circle_pattern,
              "grid": self.grid, "path": self.path, "spline": self.spline}.get(kind)
        if fn is None:
            raise BuildError("%s: unknown profile type %r" % (self.fid, kind))
        fn(prof)


def make_sketch(ctx, fid, feat, default_plane="XY"):
    sk = feat.get("sketch") or {}
    plane = str(sk.get("plane", feat.get("plane", default_plane))).upper()
    if plane not in PLANES:
        raise BuildError("%s: unknown plane %r (use XY, XZ, YZ)" % (fid, plane))
    profiles = sk.get("profiles") or feat.get("profiles") or \
        ([feat["profile"]] if "profile" in feat else []) or \
        ([sk["profile"]] if "profile" in sk else [])
    if not profiles:
        raise BuildError("%s: no profiles" % fid)
    s = ctx.body.newObject("Sketcher::SketchObject", "%s_Sketch" % fid)
    _set_support(s, [(_origin_feature(ctx.body, PLANES[plane]), "")])
    s.MapMode = "FlatFace"
    offset = sk.get("offset", feat.get("offset", 0))
    off_val, off_fc, off_names = ctx.resolve(offset, "%s.offset" % fid)
    rot = App.Rotation()
    tilt = sk.get("tilt", feat.get("tilt"))  # {"axis": "x"|"y", "angle": deg} in sketch coords
    if tilt:
        ax = str(tilt.get("axis", "x")).lower()
        if ax not in ("x", "y"):
            raise BuildError("%s: tilt.axis must be x or y (sketch axes)" % fid)
        ang = ctx.num(tilt.get("angle", 0), "%s.tilt.angle" % fid)
        rot = App.Rotation(V(1, 0, 0) if ax == "x" else V(0, 1, 0), ang)
    base = V(ctx.num(sk.get("shift_x", feat.get("shift_x", 0)), "%s.shift_x" % fid),
             ctx.num(sk.get("shift_y", feat.get("shift_y", 0)), "%s.shift_y" % fid), off_val)
    s.AttachmentOffset = App.Placement(base, rot)
    if off_fc and not tilt:
        s.setExpression(".AttachmentOffset.Base.z", off_fc)
    elif tilt:
        ctx.baked |= off_names
    if sk.get("reversed") or feat.get("sketch_reversed"):
        s.MapReversed = True
    m = SketchMaker(ctx, fid, s)
    for prof in profiles:
        m.add(prof)
    s.Visibility = False
    return s


# ------------------------------------------------------------ edge selectors

def _edge_matches(edge, sel, bb, tol):
    sel = sel.lower()
    verts = [v.Point for v in edge.Vertexes] or [edge.CenterOfMass]
    curve = getattr(edge, "Curve", None)
    is_line = isinstance(curve, (Part.Line, Part.LineSegment))
    is_circle = isinstance(curve, Part.Circle)

    def parallel(axis):
        if not is_line:
            return False
        d = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
        return d.Length > 0 and abs(abs(d.normalize().dot(axis)) - 1) < 1e-6

    if sel == "all":
        return True
    if sel in ("vertical", "parallel_z", "z"):
        return parallel(V(0, 0, 1))
    if sel in ("parallel_x", "x"):
        return parallel(V(1, 0, 0))
    if sel in ("parallel_y", "y"):
        return parallel(V(0, 1, 0))
    if sel in ("line", "straight"):
        return is_line
    if sel in ("circle", "circular", "round"):
        return is_circle
    if sel in ("top", "zmax"):
        return all(p.z >= bb.ZMax - tol for p in verts)
    if sel in ("bottom", "zmin"):
        return all(p.z <= bb.ZMin + tol for p in verts)
    if sel in ("right", "xmax"):
        return all(p.x >= bb.XMax - tol for p in verts)
    if sel in ("left", "xmin"):
        return all(p.x <= bb.XMin + tol for p in verts)
    if sel in ("back", "ymax"):
        return all(p.y >= bb.YMax - tol for p in verts)
    if sel in ("front", "ymin"):
        return all(p.y <= bb.YMin + tol for p in verts)
    if sel in ("outer", "boundary"):
        # edges lying on the bounding box surface
        return any(_edge_matches(edge, s, bb, tol)
                   for s in ("top", "bottom", "left", "right", "front", "back"))
    raise BuildError("unknown edge selector %r" % sel)


def select_edges(shape, selector):
    """selector: 'Edge3' | 'top' | ['top','circular'] (AND) | {'any': [...]} (OR)."""
    bb = shape.BoundBox
    tol = max(bb.DiagonalLength, 1.0) * 1e-6 + 1e-6
    edges = shape.Edges

    def match_one(sel, i, e):
        if isinstance(sel, dict) and "any" in sel:
            return any(match_one(s, i, e) for s in sel["any"])
        if isinstance(sel, (list, tuple)):
            return all(match_one(s, i, e) for s in sel)
        s = str(sel)
        if s.lower().startswith("edge") and s[4:].isdigit():
            return i + 1 == int(s[4:])
        if s.startswith("!"):
            return not match_one(s[1:], i, e)
        return _edge_matches(e, s, bb, tol)

    def is_seam(e):
        # seam edges of cylinders/cones belong to a single face; never fillet them
        try:
            return len(shape.ancestorsOfType(e, Part.Face)) < 2
        except Exception:
            return False

    return ["Edge%d" % (i + 1) for i, e in enumerate(edges)
            if match_one(selector, i, e) and not is_seam(e)]


# ----------------------------------------------------------------- features

def _check(ctx, obj, fid):
    ctx.doc.recompute()
    bad = not obj.isValid()
    shape = getattr(obj, "Shape", None)
    if not bad and shape is not None and obj.TypeId.startswith("PartDesign::") \
            and (shape.isNull() or shape.Volume <= 1e-9):
        bad = True
    if bad:
        status = ""
        try:
            status = obj.getStatusString()
        except Exception:
            pass
        hint = ""
        if obj.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer"):
            n = len(obj.Base[1]) if obj.Base else 0
            hint = (" | hint: %d edge(s) selected; the radius/size is probably larger than the "
                    "adjacent walls allow (keep it below ~half the thinnest wall) or the selector "
                    "picked edges you did not mean - use a narrower selector" % n)
        elif obj.TypeId == "PartDesign::Pocket":
            hint = " | hint: the cut may miss the material: check plane/offset/reversed"
        raise BuildError("feature %r (%s) failed%s%s" % (fid, obj.TypeId,
                                                          ": " + status if status else "", hint))


def _sketch_feature(ctx, fid, feat, typeid, default_plane="XY"):
    s = make_sketch(ctx, fid, feat, default_plane)
    ctx.doc.recompute()
    try:
        if s.solve() != 0:
            ctx.warnings.append("%s: sketch solver reported problems (check constraints)" % fid)
    except Exception:
        pass
    obj = ctx.body.newObject(typeid, _safe(fid))
    obj.Profile = s
    return obj, s


def f_pad(ctx, fid, feat, subtractive=False):
    obj, _s = _sketch_feature(ctx, fid, feat, "PartDesign::Pocket" if subtractive else "PartDesign::Pad")
    if feat.get("through_all"):
        obj.Type = "ThroughAll"
        obj.Midplane = bool(feat.get("symmetric", True))
    else:
        key = "depth" if "depth" in feat else "length"
        if key not in feat:
            raise BuildError("%s: needs length/depth (or through_all)" % fid)
        ctx.bind(obj, "Length", feat[key], "%s.%s" % (fid, key))
        obj.Midplane = bool(feat.get("symmetric", False))
    obj.Reversed = bool(feat.get("reversed", False))
    if "taper" in feat:  # draft angle in degrees; positive narrows the extrusion
        if not hasattr(obj, "TaperAngle"):
            raise BuildError("%s: taper needs FreeCAD 1.0+" % fid)
        tv = feat["taper"]  # FreeCAD: positive TaperAngle widens; ours: positive narrows
        ctx.bind(obj, "TaperAngle", ("-(%s)" % tv) if isinstance(tv, str) else -float(tv),
                 "%s.taper" % fid)
    return obj


def f_revolve(ctx, fid, feat, subtractive=False):
    obj, s = _sketch_feature(ctx, fid, feat,
                             "PartDesign::Groove" if subtractive else "PartDesign::Revolution",
                             default_plane="XZ")
    axis = str(feat.get("axis", "V")).upper()
    obj.ReferenceAxis = (s, ["V_Axis" if axis in ("V", "VERTICAL") else "H_Axis"])
    ctx.bind(obj, "Angle", feat.get("angle", 360), "%s.angle" % fid)
    obj.Midplane = bool(feat.get("symmetric", False))
    obj.Reversed = bool(feat.get("reversed", False))
    return obj


def f_dress(ctx, fid, feat, typeid, prop, keys):
    base = ctx.body.Tip
    if base is None:
        raise BuildError("%s: nothing to %s yet" % (fid, typeid.split("::")[1].lower()))
    selector = feat.get("edges", "all")
    names = select_edges(base.Shape, selector)
    if not names:
        raise BuildError("%s: edge selector %r matched no edges" % (fid, selector))
    obj = ctx.body.newObject(typeid, _safe(fid))
    obj.Base = (base, names)
    val = next((feat[k] for k in keys if k in feat), None)
    ctx.bind(obj, prop, val, "%s.%s" % (fid, keys[0]))
    _add_prop(obj, "App::PropertyString", "HermesEdgeSelector", json.dumps(selector))
    return obj


def f_trim(ctx, fid, feat):
    """Keep only the material inside a silhouette seen along the plane normal (visual hull):
    the outline is padded through everything in a hidden helper body and intersected
    (PartDesign::Boolean Common) with the part. feat: {"type":"trim","plane":"YZ","profile":...}"""
    base = ctx.body.Tip
    if base is None:
        raise BuildError("%s: trim needs material first (pad the main silhouette)" % fid)
    prof = feat.get("profile") or (feat.get("profiles") or [None])[0]
    if not prof:
        raise BuildError("%s: trim needs a profile (the silhouette outline)" % fid)
    if prof.get("type") == "spline":  # planar facets make the boolean far more robust
        pts = [V(ctx.num(p[0], "trim.x"), ctx.num(p[1], "trim.y"), 0) for p in prof.get("points") or []]
        if len(pts) >= 4:
            bs = Part.BSplineCurve()
            bs.interpolate(pts, PeriodicFlag=True)
            prof = {"type": "polygon",
                    "points": [[q.x, q.y] for q in bs.discretize(Number=max(48, min(96, 3 * len(pts))))][:-1]}
    bb = base.Shape.BoundBox
    length = 2.2 * bb.DiagonalLength + 2 * bb.Center.Length + 10
    main = ctx.body
    tool = ctx.doc.addObject("PartDesign::Body", _safe("%s_%s_tool" % (main.Name, fid)))
    tool.Label = "%s trim tool %s" % (main.Label, fid)
    ctx.aux.append(tool.Name)
    ctx.body = tool
    try:
        pad = f_pad(ctx, fid + "_tool", {"type": "pad", "plane": feat.get("plane", "YZ"),
                                          "offset": feat.get("offset", 0), "tilt": feat.get("tilt"),
                                          "profile": prof, "symmetric": True, "length": length})
        _check(ctx, pad, fid + "_tool")
    finally:
        ctx.body = main
    tool.Visibility = False
    obj = main.newObject("PartDesign::Boolean", _safe(fid))
    obj.Type = "Common"
    obj.addObjects([tool])
    return obj


_PLANE_AXIS = {"XY": "Z", "TOP": "Z", "XZ": "Y", "FRONT": "Y", "YZ": "X", "RIGHT": "X"}
_BETTER_PLANE = {"X": "YZ", "Y": "XZ", "Z": "XY"}


def check_holes(ctx, fid, feat, obj, sketch):
    """A hole must leave at least one FULL circular edge per circle in its sketch.
    Otherwise it cut a groove/notch along a face: almost always the wrong sketch plane."""
    shape = obj.Shape
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    circles = [g for i, g in enumerate(sketch.Geometry)
               if isinstance(g, Part.Circle) and not sketch.getConstruction(i)]
    bad = []
    for g in circles:
        found = False
        for e in shape.Edges:
            c = getattr(e, "Curve", None)
            if isinstance(c, Part.Circle) and abs(c.Radius - g.Radius) < 1e-4 and e.isClosed() \
                    and abs(abs(c.Axis.dot(normal)) - 1) < 1e-6:
                found = True
                break
        if not found:
            bad.append(round(2 * g.Radius, 3))
    if bad:
        plane = str((feat.get("sketch") or {}).get("plane", feat.get("plane", "XY"))).upper()
        axis = _PLANE_AXIS.get(plane, "?")
        others = ", ".join("%s (drills along %s)" % (_BETTER_PLANE[a], a)
                           for a in ("X", "Y", "Z") if a != axis)
        raise BuildError(
            "hole %r (d=%s) did not make a round hole: it cut a groove/notch or missed the "
            "material. Plane %s drills along %s. A hole must be sketched on the plane PARALLEL "
            "to the face being drilled; try %s, and check x/y/offset put the centre inside "
            "that face." % (fid, ", ".join(map(str, bad)), plane, axis, others))


def f_hole(ctx, fid, feat):
    feat = dict({"through_all": "depth" not in feat}, **feat)
    obj = f_pad(ctx, fid, feat, subtractive=True)
    _check(ctx, obj, fid)
    check_holes(ctx, fid, feat, obj, obj.Profile[0] if isinstance(obj.Profile, tuple) else obj.Profile)
    return obj


FEATURES = {
    "pad": lambda c, i, f: f_pad(c, i, f),
    "extrude": lambda c, i, f: f_pad(c, i, f),
    "pocket": lambda c, i, f: f_pad(c, i, f, subtractive=True),
    "cut": lambda c, i, f: f_pad(c, i, f, subtractive=True),
    "hole": f_hole,
    "revolve": lambda c, i, f: f_revolve(c, i, f),
    "revolution": lambda c, i, f: f_revolve(c, i, f),
    "groove": lambda c, i, f: f_revolve(c, i, f, subtractive=True),
    "trim": f_trim,
    "silhouette_trim": f_trim,
    "fillet": lambda c, i, f: f_dress(c, i, f, "PartDesign::Fillet", "Radius", ("radius", "r", "size")),
    "chamfer": lambda c, i, f: f_dress(c, i, f, "PartDesign::Chamfer", "Size", ("size", "distance", "d")),
}


# ------------------------------------------------------------------ parts

def find_body(doc, part):
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body" and getattr(o, "HermesPart", None) == part:
            return o
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body" and (o.Label == part or o.Name == part):
            return o
    return None


def list_parts(doc):
    return [o.HermesPart for o in doc.Objects
            if o.TypeId == "PartDesign::Body" and "HermesPart" in o.PropertiesList]


def remove_part(doc, part):
    body = find_body(doc, part)
    if body is None:
        return False
    sheet = doc.getObject(getattr(body, "HermesSheet", "") or "")
    aux = json.loads(getattr(body, "HermesAux", "") or "[]")
    body.removeObjectsFromDocument()
    doc.removeObject(body.Name)
    for name in aux:
        tb = doc.getObject(name)
        if tb is not None:
            tb.removeObjectsFromDocument()
            doc.removeObject(name)
    if sheet is not None:
        doc.removeObject(sheet.Name)
    return True


def eval_params(raw):
    """Raw parameters (numbers or expressions over EARLIER parameters) -> numeric dict."""
    out = {}
    for k, v in raw.items():
        try:
            X.alias_for(k)
            out[k] = float(X.evaluate(v, out))
        except X.ExprError as exc:
            raise BuildError("parameter %s: %s (use latin letters, digits and _ in names; "
                             "an expression may only use parameters defined above it)" % (k, exc))
    return out


def _sheet_cell(v, numeric):
    """Cell content: a number, or a live formula for derived parameters."""
    if isinstance(v, str) and X.names_in(v) & set(numeric):
        expr = X.to_freecad_expr(v, numeric, "@@")
        return "=" + expr.replace("@@.", "")
    return repr(float(X.evaluate(v, numeric)))


def validate_spec(spec):
    if isinstance(spec, str):
        spec = json.loads(spec)
    if not isinstance(spec, dict):
        raise BuildError("spec must be a JSON object")
    feats = spec.get("features")
    if not isinstance(feats, list) or not feats:
        raise BuildError("spec.features must be a non-empty list")
    params = spec.get("parameters") or {}
    if not isinstance(params, dict):
        raise BuildError("spec.parameters must be an object {name: number}")
    raw = {}
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise BuildError("parameter %s: value must be a number or an expression string" % k)
        raw[k] = float(v) if isinstance(v, (int, float)) else v
    eval_params(raw)  # validates names and expressions
    spec = dict(spec)
    spec["parameters"] = raw  # raw: derived ones ("L/2") stay formulas
    spec.setdefault("name", "Part")
    ids = set()
    for i, f in enumerate(feats):
        if not isinstance(f, dict) or "type" not in f:
            raise BuildError("features[%d] must be an object with 'type'" % i)
        if f["type"] not in FEATURES:
            raise BuildError("features[%d]: unknown type %r (known: %s)"
                             % (i, f["type"], ", ".join(sorted(FEATURES))))
        fid = _safe(f.get("id") or "%s%d" % (f["type"], i + 1))
        if fid in ids:
            raise BuildError("duplicate feature id %r" % fid)
        ids.add(fid)
    return spec


def build_part(doc, spec, replace=True):
    """Build spec into doc. Returns a summary dict. Raises BuildError."""
    spec = validate_spec(spec)
    name = str(spec["name"])
    if find_body(doc, name) is not None:
        if not replace:
            raise BuildError("part %r already exists (use replace=true)" % name)
        remove_part(doc, name)

    raw = spec["parameters"]
    params = eval_params(raw)
    sheet = doc.addObject("Spreadsheet::Sheet", "Params_" + _safe(name))
    sheet.Label = "%s Params" % name
    sheet.set("A1", "Parameter")
    sheet.set("B1", "Value")
    for row, (k, v) in enumerate(raw.items(), start=2):
        sheet.set("A%d" % row, k)
        sheet.setAlias("B%d" % row, X.alias_for(k))
    for row, (k, v) in enumerate(raw.items(), start=2):
        sheet.set("B%d" % row, _sheet_cell(v, params))
    doc.recompute()

    body = doc.addObject("PartDesign::Body", _safe(name))
    body.Label = name
    ctx = Ctx(doc, body, sheet, params)
    built = []
    for i, f in enumerate(spec["features"]):
        fid = _safe(f.get("id") or "%s%d" % (f["type"], i + 1))
        try:
            obj = FEATURES[f["type"]](ctx, fid, f)
            _check(ctx, obj, fid)
        except BuildError:
            raise
        except Exception as exc:  # FreeCAD raises plain exceptions
            raise BuildError("feature %r (%s): %s" % (fid, f["type"], exc))
        built.append({"id": fid, "type": f["type"], "object": obj.Name})

    _add_prop(body, "App::PropertyString", "HermesPart", name)
    _add_prop(body, "App::PropertyString", "HermesSheet", sheet.Name)
    _add_prop(body, "App::PropertyString", "HermesSpec", json.dumps(spec, ensure_ascii=False))
    _add_prop(body, "App::PropertyString", "HermesBaked", json.dumps(sorted(ctx.baked)))
    _add_prop(body, "App::PropertyString", "HermesAux", json.dumps(ctx.aux))
    doc.recompute()
    out = part_summary(doc, body)
    out["features"] = built
    exp = spec.get("expect_bbox")
    if exp and out.get("bbox_mm"):
        for axis, want, got in zip("XYZ", exp, out["bbox_mm"]["size"]):
            if want is None:
                continue
            want = X.evaluate(want, params)
            tol = float(spec["expect_tol"]) if "expect_tol" in spec else max(0.5, 0.01 * abs(want))
            if abs(got - want) > tol:
                ctx.warnings.append(
                    "overall %s is %g mm but expect_bbox says %g mm: drawing dimensions are "
                    "usually overall sizes measured from the part's outer faces (e.g. total height "
                    "from the bottom, not from the top of another feature) - fix the stacking / "
                    "offsets" % (axis, got, want))
    out["warnings"] = ctx.warnings
    out["matches_expected_bbox"] = not any(w.startswith("overall ") for w in ctx.warnings) \
        if exp else None
    return out


def reresolve_edges(doc, body):
    """Re-pick fillet/chamfer edges by their stored selectors (after a param change)."""
    changed = []
    for obj in body.Group:
        if obj.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer") \
                and "HermesEdgeSelector" in obj.PropertiesList:
            base = obj.BaseFeature
            doc.recompute()
            names = select_edges(base.Shape, json.loads(obj.HermesEdgeSelector))
            if names and list(obj.Base[1]) != names:
                obj.Base = (base, names)
                changed.append(obj.Name)
    doc.recompute()
    return changed


def set_parameters(doc, part, values):
    body = find_body(doc, part)
    if body is None or "HermesSpec" not in body.PropertiesList:
        raise BuildError("no HermesCAD part %r (parts: %s)" % (part, ", ".join(list_parts(doc))))
    spec = json.loads(body.HermesSpec)
    raw = spec["parameters"]
    unknown = [k for k in values if k not in raw]
    if unknown:
        raise BuildError("unknown parameter(s) %s; known: %s"
                         % (", ".join(unknown), ", ".join(raw)))
    old_num = eval_params(raw)
    new_raw = dict(raw)
    for k, v in values.items():
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise BuildError("parameter %s: value must be a number or an expression string" % k)
        new_raw[k] = float(v) if isinstance(v, (int, float)) else v
    new_num = eval_params(new_raw)
    changed = {k for k in new_num if abs(new_num[k] - old_num[k]) > 1e-12}
    baked = set(json.loads(body.HermesBaked or "[]"))
    spec["parameters"] = new_raw
    if baked & changed:
        out = build_part(doc, spec, replace=True)
        out["mode"] = "rebuilt (baked geometry depends on %s)" % ", ".join(sorted(baked & changed))
        out["changed"] = sorted(changed)
        return out
    sheet = doc.getObject(body.HermesSheet)
    for row, k in enumerate(raw, start=2):  # same order as written by build_part
        if k in values:
            sheet.set("B%d" % row, _sheet_cell(new_raw[k], new_num))
    doc.recompute()
    reresolve_edges(doc, body)
    body.HermesSpec = json.dumps(spec, ensure_ascii=False)
    bad = [o.Name for o in body.Group if not o.isValid()]
    out = part_summary(doc, body)
    out["mode"] = "updated via spreadsheet"
    out["changed"] = sorted(changed)
    if bad:
        out["invalid_objects"] = bad
    return out


def part_summary(doc, body):
    shape = body.Shape
    bb = shape.BoundBox
    info = {"part": getattr(body, "HermesPart", body.Label), "body": body.Name,
            "valid": bool(body.isValid() and not shape.isNull()),
            "tip": body.Tip.Name if body.Tip else None}
    if not shape.isNull():
        info.update({
            "volume_mm3": round(shape.Volume, 3),
            "area_mm2": round(shape.Area, 3),
            "bbox_mm": {"x": [round(bb.XMin, 3), round(bb.XMax, 3)],
                        "y": [round(bb.YMin, 3), round(bb.YMax, 3)],
                        "z": [round(bb.ZMin, 3), round(bb.ZMax, 3)],
                        "size": [round(bb.XLength, 3), round(bb.YLength, 3),
                                 round(bb.ZLength, 3)]},
            "solids": len(shape.Solids), "faces": len(shape.Faces), "edges": len(shape.Edges),
        })
    if "HermesSpec" in body.PropertiesList:
        spec = json.loads(body.HermesSpec)
        raw = spec.get("parameters", {})
        try:
            info["parameters"] = eval_params(raw)
        except BuildError:
            info["parameters"] = raw
        formulas = {k: v for k, v in raw.items() if isinstance(v, str)}
        if formulas:
            info["derived_parameters"] = formulas
        info["baked_parameters"] = json.loads(body.HermesBaked or "[]")
    return info
