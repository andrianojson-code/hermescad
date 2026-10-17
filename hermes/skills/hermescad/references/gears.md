# Modeling toothed wheels from drawings

Use this when a drawing shows a spur gear or another toothed rotary part. The goal is a usable, honestly labelled reconstruction—not a visually plausible shape with silently invented tooth geometry.

## Read and map the drawing first
- Use the isometric view to identify topology (external teeth, web, hub side, bore); use orthographic/section views for dimensions. Read the whole sheet, then inspect only targeted crops when a callout is unclear.
- Map each callout to a feature before building: module `m`, tooth count `z`, pitch diameter `d`, outside/root diameters, face width, hub steps/lengths, and bore. Preserve drawing dimensions as written; do not infer that a diameter refers to the gear root or hub unless its leader/view supports that.
- Cross-check standard unshifted full-depth spur-gear relations only as a diagnostic: `d = m*z`, `da ≈ m*(z+2)`, `df ≈ m*(z-2.5)`. A mismatch may indicate a different tooth system or a misread callout; do not overwrite a drawing dimension to force agreement.
- Establish the axial dimension chain from the section view. Distinguish overall length from local step lengths; do not add dimensions whose extension lines overlap or share endpoints. If a chain cannot be read, label each uncertain step as an assumption.
- Put every meaningful callout into the geometry plan and final verification list. If an uncertain dimension is not modeled, name it as omitted rather than implying the reconstruction contains it.

## Choose tooth geometry honestly
- A true involute profile needs enough information or a stated standard assumption: module, tooth count, pressure angle (often but not always 20°), profile shift, and backlash/clearance. Tooth count plus module alone does not establish a manufacturing-ready profile.
- If the pressure angle/profile is absent, either use a standard assumption explicitly and build an involute, or make a clearly identified visual approximation. Do not call a hand-built trapezoidal/radial polygon an involute or precision gear.
- The HermesCAD part-spec feature set has no dedicated gear generator. For actual tooth geometry, call `mcp__hermescad__execute_freecad_code`; import `Part` and any other modules explicitly in that FreeCAD snippet. Do not generate or run FreeCAD scripts in the terminal.
- A robust visual approximation is a root cylinder/web with repeated tooth profiles fused to it, followed by the through-bore and axial hub steps. Build the teeth into one coherent solid and verify `Shape.isValid()` and `len(Shape.Solids) == 1` before saving or exporting.
- Keep key values in the geometry construction. If custom properties are stored on a static shape, they are reference metadata—not live parameters—and changing them does not update the solid.

## Verify and deliver
- Verify the repeated tooth count (44 means exactly 44 teeth), bore, hub orientation, axial total, and each modeled step. Check the bounding box against the drawing's overall diameter and axial length.
- Compare the source drawing and model in matching views: front/top for the tooth outline and a side/section or isometric view for the hub. Inspect the actual comparison image; a render-only screenshot does not prove a match to the drawing.
- Save the FreeCAD document and verify that the saved file exists. State whether teeth are involute or approximate, which dimensions came from the drawing, which were assumed, and what remains unresolved. Never describe an approximate, non-parametric solid as manufacturing-ready.
