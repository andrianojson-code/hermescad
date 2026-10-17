# Part-reading prompt (for the vision model)

Use this as the `question` of `vision_analyze` (once per image; for multi-view drawings once
for the whole sheet). Then build from the JSON, not from your own impression of the picture.

```
You are a mechanical drafter. Read this image of ONE part and answer ONLY with JSON:
{
  "image_kind": "orthographic drawing | multi-view drawing | photo | render | sketch",
  "views": ["front", "top", ...],            // which views are shown (for photos: "3/4", "side"...)
  "base_form": "plate | block | L-bracket | turned (shaft/flange) | lever/organic | sheet metal | other",
  "main_silhouette_view": "side | front | top",   // view whose outline best describes the part
  "overall_mm": {"x": number|null, "y": number|null, "z": number|null},  // OVERALL sizes, from outer faces
  "features": [
    {"kind": "hole | slot | pocket | boss | rib | step | fillet | chamfer | groove | thread | tab",
     "on_face": "top | bottom | front | back | left | right | <describe>",
     "axis": "X | Y | Z",                      // drilling / extrusion direction
     "position_mm": {"x": .., "y": .., "z": ..},   // from the part's bottom-left-front corner; null if unknown
     "size_mm": {"d": .., "w": .., "h": .., "depth": ..},
     "through": true|false,
     "source": "drawing | estimated"}
  ],
  "dimensions": [{"value": number, "meaning": "overall height | hole dia | ...", "view": "front", "confidence": "high|low"}],
  "contradictions": ["views or numbers that disagree"],
  "unknowns": ["what cannot be determined"],
  "best_next_photo": "e.g. straight side view with a ruler"
}
Rules: dimensions on drawings are overall sizes measured from outer faces unless an arrow shows
otherwise; hole heights are from the bottom face; never invent numbers - use null and list it
in unknowns; prefer what the isometric shows for topology when views contradict.
```

How to use the answer:
- `overall_mm` -> `expect_bbox` in the spec.
- `main_silhouette_view` + `base_form` lever/organic -> silhouette method (`extract_contours`).
- each feature -> one spec feature; `axis` picks the sketch plane: Z -> XY, Y -> XZ, X -> YZ.
- `contradictions`/`unknowns` -> tell the user which values are assumed.
