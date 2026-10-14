# Range Policy

Use this policy when a hfss-harness optimization round has finished and the next config needs to be drafted.

## Inputs

- the selected round's config snapshot and terminal summary
- actual case journal, raw data and history paths declared by that run
- parameter order/units, project/context provenance and active evaluation stage

## Main signals

- valid final-stage cost and target attainment
- task-defined constraint violation and objective components when present
- actual requested band/edge values, isolation, gain or other required metrics
- sample identity and validity, failure reasons, cache provenance and stage changes

Read metric names, units, frequencies and thresholds from the current config/evaluator and raw data. Do not require a particular frequency label or manufacture missing values. Re-evaluate compatible raw results under one target/stage before comparing incompatible historical costs; do not bypass provenance checks or modify the completed logs.

## Sensitivity checks

- Spearman correlation against comparable valid cost and task-specific violations, when enough distinct observations exist
- top-sample boundary pressure
- repeated boundary hits among the best samples

Deduplicate cached/repeated observations. Report sample counts, constant parameters, coupled parameter changes and uncertainty. A correlation is an association; do not present it as a causal effect or a guarantee that narrowing will help.

## Range update rules

- Keep the best case inside the next range.
- Narrow stable parameters.
- Shift a range only when comparable valid observations support lower task-defined violation/cost.
- Expand a side if the best samples repeatedly hit that boundary.
- Keep resolution and units unchanged unless the user asks otherwise.
- Keep the change conservative when the logs are sparse or noisy.
- Recheck bounds, manufacturing resolution and all constraints; keep the verified best point feasible. Preserve target/setup/material/model context unless the user authorizes a change.

## Output

The next config should include:

- the verified best case as `optimization.initial_point` in the current parameter order/units
- updated parameter windows
- the original target and simulator settings
