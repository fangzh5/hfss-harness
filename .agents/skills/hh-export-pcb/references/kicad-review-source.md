# KiCad Review Source

Use this reference when the user asks for a PCB source project in addition to Gerber/Drill files.

## Role of the KiCad Project

The generated KiCad project is usually a review artifact, not the manufacturing authority.

Reason:

- The workflow source is HFSS geometry.
- Gerber and Drill are generated directly from HFSS-derived fabrication geometry.
- The `.kicad_pcb` may be reconstructed from the resolved fabrication geometry for viewing, layer inspection, and communication.
- Complex dark/clear regions may be approximated or decomposed into graphical copper polygons.

Tell the user and vendor:

> 加工以 Gerber、Drill 和叠层说明为准；KiCad 工程仅用于查看图形、叠层和孔对关系。

## KiCad Layer Names

KiCad names outer copper layers as:

- top: `F.Cu`
- bottom: `B.Cu`

KiCad names inner copper layers as:

- first inner layer: `In1.Cu`
- second inner layer: `In2.Cu`
- continue as `In<N>.Cu`

Map fabrication layers dynamically:

| Fabrication position | KiCad layer |
| --- | --- |
| first/top copper | F.Cu |
| inner copper 1 | In1.Cu |
| inner copper 2 | In2.Cu |
| ... | ... |
| last/bottom copper | B.Cu |

Do not assume exactly two inner layers.

## Visual Artifacts

PCB Editor artifacts can appear when Gerber dark/clear results are converted into viewable PCB graphics:

- stair-stepped circles from rasterized copper visualization;
- small seams or waves along boundaries when many polygon pieces meet;
- apparent mismatch if an old KiCad window is showing a stale project.

First verify Gerber Viewer. If Gerber Viewer matches HFSS, manufacturing geometry is normally correct. Fix KiCad source only if it is needed as a review aid.

## Better KiCad Source Strategy

- Use exact polygon/rectangle splitting for rectilinear layers where feasible.
- Use high-resolution approximation only for non-rectilinear clear geometry when no robust boolean engine is available.
- Keep Drill objects as vias with correct layer pairs and hole diameters.
- Do not imply that generated graphical copper is the same as hand-authored PCB tracks/nets.
