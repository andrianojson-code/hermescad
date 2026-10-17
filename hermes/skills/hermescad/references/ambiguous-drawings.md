# Contradictory or AI-generated drawings

Most drawings users hand over are machine-generated: several orthographic views plus an isometric,
with numbers that do not all belong to a single consistent solid. Treat them as a hypothesis to
reconcile, not as data to transcribe.

## Which readings to trust
- Read the whole drawing once, then at most ONE crop per view. Vision readings of dimension arrows
drift between calls — the same "16" comes back as a thickness, a hole offset or a step depending
on the crop. Keep a number only if two independent reads agree; everything else is an estimate.
- Sub-model geometry claims are reliable for TOPOLOGY (which plate sits where, which wall a hole
passes through, whether an axis is vertical or horizontal) and unreliable for POSITIONS,
PROPORTIONS and "is it rounded". Take topology from the isometric, take numbers from the
orthographic views.
- If the callouts match the worked example in `get_spec_reference` (`length 40 / depth 25 /
height 33 / tab_hole_z 20`), the drawing is that L-bracket redrawn: start from that spec and fix
only what this drawing genuinely adds.

## Reconcile before you build
- Write the dimension table first, then sanity-test each candidate reading: a hole whose edge lands
within a few tenths of a millimetre of a neighbouring face, or a hole that would break into the
plate it sits on, means that reading is wrong.
- Prefer the reading that consumes the MOST callouts at once, even when it makes the overall size
an odd number. A single self-consistent interpretation beats five "most likely" guesses.
- When two readings both survive the sanity test, build the one that is mechanically sound (a
bracket that can be made and used) and name the other in the report.

## Hand over an interpreted part
- Put EVERY callout into `parameters` (one name per dimension) so any wrong reading is a one-line
`set_parameters` fix; never hide a guess inside a hardcoded coordinate.
- Report an assumption table: value | source (drawing / user / estimated), and mark diameters,
radii and thicknesses the drawing never dimensioned as estimates.
- Name the one or two readings you chose between, say which you rejected and why, and offer the
alternative as a short selectable phrase in the reply (e.g. "33 above the base" vs "33 total") —
the model is already usable, so this is an offer, not a blocking question.
- Say plainly that the drawing has no hole diameters / radii when it has none, rather than leaving
the user to discover the invented values.
