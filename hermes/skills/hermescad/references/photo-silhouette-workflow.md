# Reading a part from a small photo without vision help

Use when the photo is small (~400 px side) or the object is unfamiliar and the vision pass
answers in generalities ("possibly a plastic clip, dimensions cannot be determined").
Repeating the vision call does not help: a second full-image pass returns different, vaguer
prose, and the two readings conflict. Switch to pixel work and read the shape yourself.

## 1. Measure the file first

```python
from PIL import Image
im = Image.open(path).convert('RGB')
print(im.size, im.mode)
```

Work in the Hermes scratch dir (`$TMPDIR`), not next to the user's file.

## 2. Find the real part bbox — screenshots have UI bands

A naive `luminance < 120 → bbox` on a screenshot returns the WHOLE frame, because the image
carries a dark header/footer strip. Print per-row dark-pixel counts first and pick the rows
where the count is structurally non-zero *and* varying:

```python
px = im.convert('L').load(); w, h = im.size
for y in range(0, h, 10):
    print(y, sum(1 for x in range(w) if px[x, y] < 150))
```

A row counting exactly `w` (or 0) is a solid band, not the part.

## 3. Print the silhouette as ASCII — read geometry directly

Downsample to ~100×58 cells, average luminance per cell, map to a ramp; darker = higher index:

```python
chars = ' .:-=+*#%@'
for j in range(H):
    line = ''
    for i in range(W):
        # average luminance of the cell (x0..x1, y0..y1)
        k = int((255 - v) / 255 * (len(chars) - 1))
        line += chars[k]
    print(f'{j:02d} ' + line)
```

Read from it: outer contour, lobes, the waist/neck, horizontal steps (overhangs), gaps where
the mask jumps inward (an undercut or a separate tongue), and any point where the outline
terminates in a curve (rounded paddle / finger). Uniform `*` = flat surface facing the light;
`%`/`#` clusters = shading or a second surface at an angle — that separates a flat plate from
a curved band.

Convert what you read into a side profile: a rounded end becomes a circle pad, a neck becomes a
tapered polygon, an overhang becomes a separate pad. Build base → stem → lobe → ledge, fillets
last.

## 4. Zoom for one targeted vision pass, not more

Crop to the bbox, upscale 3–5× with `Image.LANCZOS`, keep the long side ≤ 1568 px, then one
`vision_analyze` on that file. One enlarged pass beats three full-frame passes.

## 5. Verify the render against the photo silhouette

The FreeCAD renders are white-background, so the same mask code works on them: build the mask
with `abs(r-bg[0])+abs(g-bg[1])+abs(b-bg[2]) > 25` where `bg = px[0,0]`, and print the ASCII
side by side with the photo's. Compare aspect ratio of the projected silhouette and the
position of the waist and lobes — that is objective evidence; "build_part returned valid:true"
is not.

## Where the render files land

`get_view` / `compare_with_reference` may answer with only `view=<name>` and no path. The PNG is
still written:

- renders: `<freecad_status.work_dir>/views/<view>_<HHMMSS>.png`
- exports and saved documents: `<freecad_status.work_dir>/exports/`

Pick the newest with `ls -t <work_dir>/views/*.png | head -3` and read that path. If the
combined reference-vs-model image is not on disk, open the newest `isometric_*.png` on its own.

## Interpreter note

Hermes's host python may not have numpy. Write these probes as PIL-only loops (they run in
seconds at these sizes) instead of stalling on an import, or install numpy first if you prefer.
