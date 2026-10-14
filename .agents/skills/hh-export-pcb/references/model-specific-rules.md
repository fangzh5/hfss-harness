# Model-Specific Rule Notes

Use this reference when a fabrication workflow needs object-specific interpretation rules for one AEDT/HFSS model family.

## Principle

Generic HFSS-to-fabrication logic should not silently encode assumptions about a single antenna, board, stackup, material system, or naming convention. If a model needs special handling, document those rules as project-local inputs and keep them separate from the reusable exporter.

## What To Document

For each model-specific rule, record:

- The source object names or name patterns.
- Whether the objects represent copper, clear regions, drill/via geometry, board outline, ports, boundaries, labels, or helper geometry.
- The intended fabrication layer or layer pair.
- Whether the rule is required for manufacturing output or only for review-source visualization.
- The user or manufacturing decision that justifies the rule.

## Guardrails

- Do not assume a fixed number of copper layers.
- Do not assume fixed copper thickness, dielectric material, dielectric thickness, or via type.
- Do not infer that every visible AEDT object is copper.
- Do not export ports, air boxes, radiation boundaries, or construction helpers unless the user explicitly classifies them as fabrication geometry.
- Keep reusable geometry extraction code separate from project-local object mapping.

## Review Checklist

Before packaging fabrication files, verify that:

- Layer mapping came from the current design or explicit user stackup intent.
- Dark and clear Gerber polarity is correct for every layer.
- Drill files represent real hole diameter, location, and layer pair.
- Any model-specific exclusions or duplicated-layer features are listed in the package notes.
- Optional KiCad or Altium review sources are clearly marked as review artifacts unless they are the true design source.
