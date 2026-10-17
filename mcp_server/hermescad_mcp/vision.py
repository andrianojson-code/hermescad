"""Image helpers: load/downscale, contour extraction from drawings, side-by-side compare."""
import io
import math

from PIL import Image as PILImage, ImageDraw, ImageFont, ImageOps

MAX_SIDE = 1568  # what most vision models use without further downscaling


def load(path):
    img = PILImage.open(path)
    img = ImageOps.exif_transpose(img)  # phone photos
    return img.convert("RGB")


def to_png(img, max_side=MAX_SIDE):
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def side_by_side(left, right, labels=("reference", "model"), height=640):
    def fit(im):
        w = int(im.width * height / float(im.height))
        return im.resize((max(w, 1), height))
    a, b = fit(left), fit(right)
    pad = 12
    canvas = PILImage.new("RGB", (a.width + b.width + pad * 3, height + 40 + pad), "white")
    canvas.paste(a, (pad, 40))
    canvas.paste(b, (a.width + pad * 2, 40))
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=24)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    d.text((pad, 8), labels[0], fill=(200, 30, 30), font=font)
    d.text((a.width + pad * 2, 8), labels[1], fill=(30, 30, 200), font=font)
    return canvas


def _photo_mask(rgb, np, cv2):
    """Foreground mask for a part photographed on a plain background."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    b = max(2, min(h, w) // 40)
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    if np.linalg.norm(border - bg, axis=1).mean() > 8.0:
        # busy background (checkerboard "transparency", texture): colour distance fails,
        # use GrabCut seeded with "everything near the border is background"
        return _grabcut_mask(rgb, np, cv2)
    dist = np.linalg.norm(lab - bg, axis=2)
    dist = cv2.GaussianBlur(dist, (5, 5), 0)
    d8 = np.clip(dist * (255.0 / max(dist.max(), 1e-6)), 0, 255).astype(np.uint8)
    _, mask = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    k = max(3, int(round(min(h, w) / 150.0)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab_cc, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = np.where(lab_cc == biggest, 255, 0).astype(np.uint8)
    # fill interior (shading / reflections inside the part are not holes)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, cnts, -1, 255, thickness=-1)
    return filled


def _grabcut_mask(rgb, np, cv2):
    h0, w0 = rgb.shape[:2]
    f = 3.0 if max(h0, w0) < 700 else 1.0
    up = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC) if f != 1 else rgb.copy()
    h, w = up.shape[:2]
    m = np.zeros((h, w), np.uint8)
    rect = (max(1, int(w * 0.015)), max(1, int(h * 0.015)), int(w * 0.97), int(h * 0.97))
    bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(np.ascontiguousarray(up), m, rect, bgm, fgm, 8, cv2.GC_INIT_WITH_RECT)
    fm = np.where((m == 1) | (m == 3), 255, 0).astype(np.uint8)
    fm = cv2.morphologyEx(fm, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab_cc, stats, _ = cv2.connectedComponentsWithStats(fm)
    if n > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fm = np.where(lab_cc == big, 255, 0).astype(np.uint8)
    cnts, _ = cv2.findContours(fm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(fm)
    cv2.drawContours(filled, cnts, -1, 255, thickness=-1)
    if f != 1:
        filled = cv2.resize(filled, (w0, h0), interpolation=cv2.INTER_NEAREST)
    return filled


def _resample(contour, n, np):
    pts = contour.reshape(-1, 2).astype(np.float64)
    seg = np.sqrt(((np.roll(pts, -1, axis=0) - pts) ** 2).sum(axis=1))
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    out = []
    for t in np.linspace(0, total, n, endpoint=False):
        i = int(np.searchsorted(cum, t, side="right") - 1)
        i = min(i, len(pts) - 1)
        f = (t - cum[i]) / seg[i] if seg[i] > 0 else 0.0
        out.append(pts[i] + f * (pts[(i + 1) % len(pts)] - pts[i]))
    return out


def extract_contours(path, crop=None, invert=None, threshold=None, min_area_frac=0.002,
                     epsilon_frac=0.004, ref_length_mm=None, ref_axis="width",
                     mm_per_px=None, max_points=400, mode="auto", as_spline=False,
                     spline_points=32):
    """Find the main outline + inner holes of a part in a drawing/silhouette/clean photo.

    Returns coordinates in mm (if a scale is known) or px, origin at the centre of the
    outline's bounding box, Y axis pointing UP (CAD convention).
    """
    import cv2
    import numpy as np

    img = load(path)
    if crop:
        x0, y0, x1, y1 = [int(v) for v in crop]
        img = img.crop((x0, y0, x1, y1))
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    h, w = gray.shape

    if mode == "auto":
        # photos have many mid-tones; drawings/silhouettes are mostly two-tone
        hist = np.histogram(gray, bins=8, range=(0, 255))[0] / float(gray.size)
        mode = "photo" if np.sort(hist)[-2:].sum() < 0.85 else "drawing"
    photo = mode == "photo"
    if invert is None:  # bright border => dark object on light background
        border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
        invert = border.mean() > 127
    flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    if threshold is None:
        _, bw = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
    else:
        _, bw = cv2.threshold(gray, int(threshold), 255, flag)
    k = max(3, int(round(min(h, w) / 300.0)) | 1)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    if photo:
        bw = _photo_mask(np.array(img), np, cv2)

    # line drawings: fill closed outlines so the part becomes a solid region
    cnts, hier = cv2.findContours(bw, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        raise ValueError("no contours found (try invert=true/false, threshold or crop)")
    hier = hier[0]
    area = [cv2.contourArea(c) for c in cnts]
    min_area = min_area_frac * h * w

    def children(i):
        out, c = [], hier[i][2]
        while c >= 0:
            out.append(c)
            c = hier[c][0]
        return out

    outers = [i for i in range(len(cnts)) if hier[i][3] < 0 and area[i] >= min_area]
    if not outers:
        raise ValueError("no contour bigger than min_area_frac; lower it or crop")
    main = max(outers, key=lambda i: area[i])
    kids = [c for c in children(main) if area[c] >= min_area * 0.05]
    big = [c for c in kids if area[c] > 0.6 * area[main]]
    mode = "silhouette"
    if big:  # outline drawn as a thin line: holes are drawn rings inside it
        mode = "line drawing"
        kids = [c for c in children(big[0]) if area[c] >= min_area * 0.05]
    holes = kids

    x, y, bw_w, bw_h = cv2.boundingRect(cnts[main])
    ox, oy = x + bw_w / 2.0, y + bw_h / 2.0
    if mm_per_px:
        scale, unit = float(mm_per_px), "mm"
    elif ref_length_mm:
        scale = float(ref_length_mm) / float(bw_w if ref_axis == "width" else bw_h)
        unit = "mm"
    else:
        scale, unit = 1.0, "px"

    def conv(px, py):
        return [round((px - ox) * scale, 2), round(-(py - oy) * scale, 2)]

    def describe(c):
        area = cv2.contourArea(c)
        peri = cv2.arcLength(c, True)
        circ = 4 * math.pi * area / (peri * peri) if peri else 0
        (cx, cy), r = cv2.minEnclosingCircle(c)
        if circ > 0.86 and area / (math.pi * r * r) > 0.86:
            return {"type": "circle", "x": conv(cx, cy)[0], "y": conv(cx, cy)[1],
                    "d": round(2 * math.sqrt(area / math.pi) * scale, 2)}
        eps = epsilon_frac * peri
        approx = cv2.approxPolyDP(c, eps, True)
        while len(approx) > max_points:
            eps *= 1.5
            approx = cv2.approxPolyDP(c, eps, True)
        pts = [conv(p[0][0], p[0][1]) for p in approx]
        rx, ry, rw, rh = cv2.boundingRect(c)
        if len(pts) == 4 and area / float(rw * rh) > 0.95:
            ccx, ccy = conv(rx + rw / 2.0, ry + rh / 2.0)
            return {"type": "rect", "x": ccx, "y": ccy,
                    "w": round(rw * scale, 2), "h": round(rh * scale, 2)}
        return {"type": "polygon", "points": pts}

    outline = describe(cnts[main])
    if as_spline:
        n = max(8, min(int(spline_points), 120))
        outline = {"type": "spline", "points": [conv(px, py) for px, py in _resample(cnts[main], n, np)]}
    hole_profiles = [describe(cnts[i]) for i in holes]

    overlay = img.copy()
    dr = ImageDraw.Draw(overlay)
    for i, color in [(main, (230, 40, 40))] + [(j, (40, 90, 230)) for j in holes]:
        pts = [tuple(p[0]) for p in cnts[i][:: max(1, len(cnts[i]) // 400)]]
        if len(pts) > 1:
            dr.line(pts + [pts[0]], fill=color, width=max(2, w // 300))
    dr.rectangle([x, y, x + bw_w, y + bw_h], outline=(40, 160, 40), width=1)

    return {
        "unit": unit,
        "mode": ("photo silhouette" if photo else mode),
        "scale_mm_per_px": scale if unit == "mm" else None,
        "image_px": [w, h],
        "outline_bbox": {"w": round(bw_w * scale, 2), "h": round(bw_h * scale, 2), "unit": unit},
        "outline": outline,
        "holes": hole_profiles,
        "note": ("origin = centre of outline bbox, +Y up. Use these as sketch profiles; "
                 "replace pixel coordinates by mm once a reference dimension is known."
                 if unit == "px" else "origin = centre of outline bbox, +Y up, millimetres."),
    }, overlay


def cutout(path, crop=None, margin=0.08, size=1024):
    """Cut the object out of its background -> square RGBA PNG (what image->3D generators like).
    Returns (PIL RGBA image, info)."""
    import cv2
    import numpy as np
    img = load(path)
    if crop:
        x0, y0, x1, y1 = [int(v) for v in crop]
        img = img.crop((x0, y0, x1, y1))
    rgb = np.array(img)
    mask = _photo_mask(rgb, np, cv2)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("could not separate the object from the background; crop tighter")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    rgba = np.dstack([rgb, mask]).astype(np.uint8)[y0:y1 + 1, x0:x1 + 1]
    h, w = rgba.shape[:2]
    side = int(max(h, w) * (1 + 2 * margin))
    canvas = np.zeros((side, side, 4), np.uint8)
    oy, ox = (side - h) // 2, (side - w) // 2
    canvas[oy:oy + h, ox:ox + w] = rgba
    out = PILImage.fromarray(canvas, "RGBA").resize((size, size), PILImage.LANCZOS)
    coverage = float((mask > 0).mean())
    return out, {"object_bbox_px": [int(x0), int(y0), int(x1), int(y1)], "coverage": round(coverage, 3)}
