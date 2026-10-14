# Environment Dependencies

Use this reference when setting up a new machine, documenting prerequisites, or deciding which tools are required for a specific HFSS-to-PCB fabrication workflow.

## Dependency Levels

### Required for file generation

- Python supported by the repository.
- Repository source code and its Python dependencies.
- Ability to read the source `.aedt` file, either through AEDT/HFSS automation or through text/archive parsing used by the current workflow.
- Write access to the chosen output directory.

Typical Python packages used by this workflow family include:

- `pytest` for verification.
- `numpy` for geometry/raster operations.
- `matplotlib` when using `matplotlib.path.Path` for point-in-polygon checks.

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

If the workflow only parses existing `.aedt` text/archive content and the required geometry is accessible, AEDT may not be required for that specific run. State this distinction clearly when documenting setup.

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

1. Minimal fabrication mode: Python environment + Gerber viewer + source `.aedt` that can be parsed/exported.
2. Full review mode: minimal mode + KiCad + optional AEDT/HFSS automation + optional Altium Designer.

Do not require Altium Designer just to manufacture an HFSS-derived antenna board if the Gerber, Drill, and stackup notes are complete.
