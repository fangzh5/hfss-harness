# Environment Dependencies

Use this reference when setting up a new machine, documenting prerequisites, or deciding which tools are required for a specific HFSS-to-PCB fabrication workflow.

## Dependency Levels

### Required for file generation

- Python supported by the repository.
- Source checkout or installed package with the `hfss` and `cam` extras.
- Licensed AEDT/HFSS access for the public native exporter, which reads final modeler geometry from a protected project copy.
- Write access to the chosen output directory.

The extras provide the current runtime dependencies:

- PyAEDT for AEDT automation.
- Gerbonara and Shapely for actual CAM parsing and geometry.
- NumPy and Matplotlib for numeric checks and previews.

`pytest` is a developer dependency, not a requirement for users running the installed workflow.

Install dependencies according to the repository's existing environment policy. Do not introduce a second unmanaged environment if the repo already has one.

### Required for visual fabrication review

At least one Gerber/Drill viewer is required.

Recommended:

- KiCad Gerber Viewer, because it can inspect Gerber and Excellon files independently of Altium import behavior.

Acceptable alternatives:

- Altium Designer CAM/Gerber import.
- Manufacturer-provided CAM preview.
- Other trusted Gerber viewers.

### Required for direct HFSS automation

Install and license Ansys Electronics Desktop / HFSS when the workflow must launch AEDT, query modeler objects through the API, or export geometry through AEDT automation.

Reading an existing fabrication package with `cam_import` does not launch AEDT; extracting fabrication geometry from `.aedt` with `native_export` does. Historical text-parsing helpers are not public export entrypoints.

### Optional for PCB review source

Install KiCad when the workflow needs a `.kicad_pcb` / `.kicad_pro` review project, KiCad Gerber Viewer, or `kicad-cli` validation.

Useful tools:

- KiCad PCB Editor for layer-by-layer review.
- KiCad Gerber Viewer for manufacturing visual review.
- `kicad-cli` for syntax/format validation of generated `.kicad_pcb` files.

Altium Designer is optional when the user or vendor wants AD/CAM inspection, but it is not required if Gerber/Drill are already generated and verified.

## Setup Checklist

- Python command works in the repository workspace.
- Required Python imports for the chosen scripts succeed.
- AEDT/HFSS is available if the chosen extraction path launches AEDT.
- KiCad or another Gerber viewer is installed for visual checks.
- `kicad-cli` is available if generating KiCad source and validating it automatically.
- The user has confirmed stackup materials, copper thickness, dielectric thicknesses, and via manufacturing intent.

## Promotion Notes

When sharing this skill with another user or machine, document two modes:

1. Native export: Python with `hfss`/`cam` extras, licensed AEDT/HFSS and the source `.aedt`; use a CAM viewer for visual review.
2. Existing-package inspection: Python with `cam`, the actual Gerber/Drill/stackup files and a CAM viewer; no AEDT launch is needed until reconstruction.

Do not require Altium Designer just to manufacture an HFSS-derived antenna board if the Gerber, Drill, and stackup notes are complete.
