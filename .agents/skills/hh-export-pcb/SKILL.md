---
name: hh-export-pcb
description: Use when converting, auditing, or packaging an HFSS/AEDT antenna or passive RF multilayer board into PCB fabrication deliverables, including Gerber, Excellon drill, stackup notes, vendor handoff notes, or optional KiCad/Altium review files.
---

# HFSS Harness Export PCB

Use this skill when HFSS/AEDT geometry is the design source for a PCB-like antenna or passive RF structure. Do not assume a fixed layer count, fixed object names, or a schematic-driven PCB workflow.

## Core Principle

Derive the fabrication model from HFSS geometry and explicit user/manufacturing intent. Gerber + Drill + stackup notes are the manufacturing reference. Generated PCB source files are review artifacts unless the project is intentionally converted into a true PCB-authoring source.

## General Workflow

1. Check the environment.
   - Read `references/environment.md` when setting up a new machine or sharing this workflow.
   - Confirm Python dependencies, AEDT/HFSS access if needed, and at least one Gerber viewer.
2. Identify the source.
   - Confirm AEDT path, design name, model units, and whether the user wants fabrication files, a review PCB source, or both.
   - Read the selected design and existing task inputs before asking for manufacturing fields. After discovery, ask only for missing or conflicting layer/material/thickness/via mapping or ambiguous fabrication roles; do not make the user transcribe values available from the model.
3. Discover the layer model.
   - Determine copper layers from z locations, object extents, materials, or explicit user mapping.
   - Name layers consistently, for example `L1_TOP`, `L2_INNER`, ..., `LN_BOTTOM`; do not hard-code four layers.
   - Derive dielectric intervals between adjacent copper layers from stackup intent, not only from object names.
4. Classify geometry.
   - Copper solids/sheets become dark Gerber regions on their assigned layer.
   - Cutouts, voids, clearance windows, and CPW gaps become clear Gerber regions on the same layer.
   - Simulation-only objects such as ports are excluded unless the user explicitly identifies them as copper.
   - Lines/curves/helpers are ignored unless the requested output needs slots, routing paths, or labels.
5. Classify holes and vias.
   - For via objects, drill diameter is the actual model diameter (twice radius). This project's confirmed default treats copper/PEC vias as metallized unless explicitly annotated otherwise; explicit annotations override it. Do not add an assumed plating thickness or repeatedly ask for it when only this drill mapping is requested.
   - Assign each via to its intended start/end copper layers: through, blind, buried, or adjacent-layer laser microvia.
   - Use separate drill files when different layer pairs represent different manufacturing operations.
6. Generate fabrication outputs.
   - One copper Gerber per copper layer.
   - Mandatory `BOARD_OUTLINE.gko`: a closed centerline profile from the actual dielectric/board-body outer boundary. Never substitute the copper bounding box or a filled-region preview for the physical board profile. Preserve real cutouts and curved boundaries; refuse unsupported shapes rather than omit them.
   - Excellon drill files grouped by layer pair and via intent.
   - Structured `stackup.json` plus readable `docs/stackup.md` and fabrication notes, using `references/fabrication-package.md`. Preserve each layer's absolute Z, thickness, material and known dielectric Dk/Df with their source; mark unknowns explicitly rather than insert defaults. Inspect the chosen exporter: the legacy writer only emits geometric Markdown and does not provide a complete EM stackup.
7. Validate before packaging.
   - Use Gerber Viewer as the manufacturing visual reference.
   - Verify each layer against HFSS/user intent, including clear polarity and drill alignment.
   - Verify drill tool diameters, layer-pair naming, and stackup thickness/materials.
   - Re-read the actual GKO and verify closed loops, dimensions/area, units/origin, and alignment with copper and drill. The profile display line width is not routing kerf or cutter compensation. A package missing its confirmed board profile is incomplete.
8. Generate optional PCB source only after fabrication geometry is stable.
   - In KiCad, map outer layers to `F.Cu`/`B.Cu` and inner layers to `In1.Cu`, `In2.Cu`, etc.
   - Explain that generated PCB graphics may be reconstructed from Gerber/Drill and are for review unless explicitly made authoritative.

Finish with the package path, a viewable CAM preview, layer/drill counts and validation status. Clearly distinguish verified completion, missing inputs, unsupported features and execution failure; a preview or partially written package is not verified completion. Keep technical logs in the evidence folder and surface only the findings needed for the user's next decision. User-requested display/open/close behavior takes priority.

## Repository Workflow

Preserve the source by default: work on a unique temp copy, retain evidence in a unique runs directory, and verify source hashes. Reuse current-task inputs and authorization. An explicitly requested source-fixture edit requires a distinct byte-verified backup and Git rollback point.

Use `optimizer.fabrication.native_export` for the supported native subset: Z-aligned constant-section Model solids, closed straight rings and whole circles, with exhaustive explicit object/layer/drill/exclusion mapping. Read dimensions and scalar materials from final native geometry; missing roles produce an inventory/needs_input report. Unsupported sheets, tapered/stepped solids, arcs/splines and circular dielectric/profile cutouts are refused. See the native mapping and CLI contract in `../../../docs/pcb-stackup.md`. A model-specific test script does not extend this boundary.

Debug in non-GUI mode by default. Add `--gui` only when a user visual review is needed; never silently fall back to a visible session. The current public CAM adapter is `optimizer.fabrication.cam_io`: polygon regions, full circular flashes, and circular drill hits with actual file readback, units and ordered dark/clear composition. Unsupported arc regions, non-circular apertures/macros and routed slots are refused; do not claim complete external CAM coverage.

For resolved stackup output, reuse `optimizer.fabrication.stackup`: `LayerStack` records explicit ordered layer intervals/materials and drill mappings; `write_stackup_bundle` writes JSON and Markdown from one source and checks readback. See `../../../docs/pcb-stackup.md` for the minimal `hfss-stackup-2` contract. This writer consumes resolved inputs; it does not automatically extract native materials or convert legacy packages.

In particular, distinguish thin metal layer shapes, board-spanning via objects, and simulation feed/helper objects. Record exclusions explicitly. Explicit user classification overrides names: a feedthrough intended as a fabricated metallized via must be included in Drill with its measured diameter and layer pair, never silently excluded because it feeds the simulation. Do not turn every PEC solid into a drill. Read final face topology and preserve windows/islands/circles; unsupported topology prevents a complete fabrication package. Label provisional previews explicitly and keep them out of the manufacturing deliverables.

Validate copper-only via layer pairs and all feature/tool references before output. Re-read actual Gerber/Drill, compare final regions and holes, and render from parsed CAM rather than a JSON preview. Drill operations retain layer pair and metallization in file naming/notes and parsed TYPE metadata; no implicit pad or plating dimension is added. Record parser version, coordinate quantization, curve/comparison tolerance and file hashes.

Use the public native exporter for the declared subset. Explicitly supply the source/design and resolve every object role, layer pair and measured drill size before accepting a package. Private or historical helpers are not distributed and do not extend the public support boundary.

```powershell
python -m optimizer.fabrication.native_export --help
```

Legacy KiCad/source-repair helpers are checkout-specific and are not bundled as public workflow resources. Do not promise them in an installed-package workspace or use a helper with fixed project names as a generic exporter. Optional source-checkout tests are developer checks, not required commands in a scaffolded user workspace.

## Required Checks

- Layer count and layer names come from the current design/stackup.
- Every copper layer has a Gerber file and is visually inspected.
- Clear/dark polarity matches intended copper and void regions.
- Drill files encode real hole diameter, position, and layer pair.
- Board outline is present and correctly scaled.
- `BOARD_OUTLINE.gko` contains an actual closed board profile, is parsed back successfully, and is shown with copper/Drill during review. Current `optimizer.fabrication.profile_io` supports closed straight contours; curved board profiles remain unsupported and must be reported.
- Re-read the exported stackup and compare layer order, Z intervals, thickness/materials and known Dk/Df against source or confirmed intent. Both structured data and readable notes must agree; list missing fields and whether the package is ready for reconstruction. Missing/conflicting manufacturing fields go back to intake before declaring the fabrication package complete; unknown EM properties must be flagged for rebuild intake, never silently filled.
- Vendor notes state that copper is defined by Gerber, holes by Drill, and stackup by docs.

## References

- `references/environment.md`: required and optional environment dependencies.
- `references/fabrication-package.md`: generic fabrication package contract.
- `references/kicad-review-source.md`: optional PCB source semantics and layer naming.
- `references/troubleshooting.md`: general diagnostics for mismatches.
- `references/model-specific-rules.md`: how to document project-local object mapping without hard-coding it into the generic workflow.
