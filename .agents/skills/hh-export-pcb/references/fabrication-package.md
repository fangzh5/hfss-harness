# Fabrication Package Contract

Use this reference when preparing the actual package for a PCB manufacturer.

## Manufacturing Authority

For HFSS-derived antenna or passive RF boards, the manufacturing authority is:

1. Gerber files for copper and outline geometry.
2. Excellon drill files for hole diameter, hole location, and layer pair.
3. Stackup/fabrication notes for material, copper thickness, dielectric thickness, total thickness, and via intent.

Do not tell the vendor to regenerate fabrication files from optional KiCad/Altium source unless the project has been converted into a true PCB-authoring source.

## Generic Directory Layout

```text
package/
  gerber/
    <layer-name>.gbr
    ...
    BOARD_OUTLINE.gko
  drill/
    <via-type-or-layer-pair>.drl
    ...
  docs/
    stackup.md
    fab_notes.md
  fabrication.json
  stackup.json
  manifest.json
  preview/
```

Layer names should reflect stack order, for example `L1_TOP`, `L2_INNER`, ..., `LN_BOTTOM`. Do not assume the board has exactly four layers.

## Gerber Rules

- Emit one copper Gerber per copper layer.
- Use Gerber dark/clear polarity deliberately.
- Copper pads, antenna elements, ground areas, and CPW conductors are Gerber geometry.
- Cutouts, clearance windows, antipads, CPW gaps, and etched voids are clear Gerber regions.
- Board outline is mandatory in a separate `BOARD_OUTLINE.gko`. Derive it from the actual dielectric/board-body boundary, not the copper bounding box. Use closed centerline contours rather than a filled copper region; profile line width is a viewing width, not cutter compensation.
- Parse the written GKO back, verify closure/units/origin/dimensions, and display it alongside copper and Drill. Preserve actual board cutouts; unsupported curved/complex profiles must be explicitly rejected instead of dropped.
- Exclude simulation-only ports and boundaries unless the user explicitly marks them as copper.

## Drill Rules

- Via drill diameter comes from HFSS model diameter, normally `2 * cylinder_radius`. The project default maps copper/PEC via objects to metallized drills unless specially annotated; special annotations take priority. Do not infer plating thickness or add unspecified pads.
- A feedthrough explicitly classified by the user as a fabricated via belongs in Drill. Object names alone never override that intent; separate outside-board simulation connector geometry from the board hole.
- Drill files should encode both hole coordinates and intended layer pair.
- Use separate files for different manufacturing intent: through holes, blind vias, buried vias, or adjacent-layer laser microvias.
- Copper pad geometry is in Gerber; hole definition is in Drill.

## Stackup Notes

The stackup note should be generated from the current design or user-confirmed manufacturing stack, not from a fixed template.

Minimum fields:

| Order | Layer | Type | Material | Thickness (mm) |
| ---: | --- | --- | --- | ---: |
| 1 | L1_TOP | copper | user-confirmed copper | user-confirmed |
| 2 | D1 | dielectric | user-confirmed dielectric | user-confirmed |
| ... | ... | ... | ... | ... |
| N | LN_BOTTOM | copper | user-confirmed copper | user-confirmed |

If total thickness is known, include it. If it is inferred, say so clearly.

Also write a machine-readable `stackup.json`, with a declared schema/version and units. It must map each ordered layer to its copper Gerber or dielectric region, and include kind, material, thickness, `z_bottom`/`z_top`, coordinate datum and copper thickness convention. Record known dielectric permittivity (Dk) and loss tangent (Df) per dielectric layer/material, with source (native material readback, confirmed user input or identified supplier data). Include drill file-to-layer-pair mapping and the conductor approximation where relevant. A single material record may be referenced by multiple layers only when their identity is confirmed.

Unknown fields are explicit nulls plus a missing-input list, not guessed values. Missing manufacturing layer order/material/thickness prevents a complete fabrication handoff. Unknown Dk/Df may be documented in a fabrication-only package, but it is not ready for material-faithful HFSS reconstruction; rebuild must obtain those values first. Structured stackup and Markdown must derive from the same resolved inputs, and their layer intervals/thickness sum must be checked after writing. Resolve contradictions rather than silently prefer one file.

Implementation boundary: the legacy `write_stackup` emits only name/kind/material/Z/thickness in Markdown, and FabModel v1 has no Dk/Df fields. Use `optimizer.fabrication.stackup.LayerStack` and `write_stackup_bundle` for resolved per-layer inputs and JSON/Markdown readback. The current schema stores explicit Z intervals and derives thickness from them, avoiding contradictory duplicates. `optimizer.fabrication.native_export` provides native scalar material/geometry extraction through explicit exhaustive roles for its constant-section solid/straight/full-circle subset. Unknown EM values stay null and block material-faithful rebuild until resolved. See [the current data and mapping contract](../../../../docs/pcb-stackup.md). A successful model-specific test does not establish universal exporter support.

## Vendor Note Template

Adapt language to the vendor. For a Chinese PCB vendor:

```markdown
# PCB 加工说明

请以本包中的 Gerber、Excellon Drill 和叠层说明作为加工基准。

铜皮图形以各层 Gerber 为准；孔径、孔位和孔层对以 Drill 文件为准；叠层以 docs/stackup.md 为准。

不同 Drill 文件代表不同孔类型或不同层对，请不要在未确认的情况下合并为一份通孔钻孔文件。
```
