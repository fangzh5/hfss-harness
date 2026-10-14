# Troubleshooting Notes

Use this reference when a generated package does not match HFSS or when viewer behavior is confusing.

## Viewer Scale or Unit Looks Wrong

Symptoms:

- Imported board appears too small or huge.
- Drill points are visible but outline/copper is mis-scaled.

Checks:

- Confirm Gerber units, coordinate format, and Excellon units.
- Prefer KiCad Gerber Viewer for independent verification.
- Use zoom-to-fit and coordinate readout before changing geometry.

## Gerber Viewer Matches HFSS but PCB Editor Does Not

Likely cause:

- The generated PCB project is reconstructed from Gerber-style dark/clear geometry.
- PCB Editor graphics may be approximated, decomposed, or stale from an older opened project.

Action:

1. Treat Gerber Viewer as the fabrication reference.
2. Fix `.kicad_pcb` only if the review source must visually match.
3. Do not change Gerber/Drill based only on a PCB Editor visualization artifact.

## Missing or Extra Copper on a Layer

Common causes:

- Object-to-layer mapping was inferred from name instead of z/material/intent.
- A copied or mirrored HFSS object exists on multiple z levels but only one level was exported.
- A helper object was treated as copper.
- A simulation object such as a port was treated as copper.

Checks:

- Inspect the fabrication intermediate model for `source_objects`, `layer`, and `polarity`.
- Compare suspect object extents and z coordinates against the AEDT geometry.
- Ask the user for layer intent when geometry is ambiguous.
- Regenerate Gerber and inspect the layer in Gerber Viewer.

## Clear/Cutout Polarity Wrong

Symptoms:

- Ground plane is solid where it should have windows.
- CPW gaps disappear.
- Antipads become copper pads or vice versa.

Checks:

- Confirm whether each object adds copper or removes copper on that exact layer.
- Preserve operation order where dark/clear regions overlap.
- Avoid converting all objects to dark copper just because they are visible in HFSS.

## Via Intent Confusion

If the user wants laser or blind vias, emit separate drill files by layer pair. If the user wants through holes, emit through-hole drill data. Do not collapse multiple via intents into one drill file unless the manufacturer and user confirm it.

Checks:

- Determine start and end copper layers for each via from z span or user intent.
- Derive drill diameter from actual cylindrical geometry where available.
- Ensure copper pads are in Gerber and holes are in Drill.

## Final Handoff Question

If the user asks whether to send PCB source or Gerber:

- Send the fabrication zip containing Gerber, Drill, and docs.
- Make the vendor note explicit: Gerber defines copper; Drill defines hole diameter/location/layer pair; docs define stackup.
- Send KiCad/Altium source only as auxiliary review material unless it is the true design source.
