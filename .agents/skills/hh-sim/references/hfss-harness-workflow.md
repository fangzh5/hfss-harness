# Task configuration and run checks

## Intake and templates

Read only the relevant template and repository implementation. `configs/template.json` is absent; use the task-specific templates below. Public intake is `python -m optimizer.inspect_aedt <source> --design <design> --setup <setup> --sweep <sweep> --temp-root <temp> --runs-root <runs/inspection>`. It uses a new owned non-GUI COM session and an unchanged protected copy, then closes the session. Missing selections return `needs_input` (exit 2); explicit absent selections or failed integrity/closure return `failed` (exit 1). Read `inspection.json` for expressions/units, setup/sweep, excitations, objects and available report quantities. Quantity discovery is capability metadata, not proof that solved data exists; optional query diagnostics remain visible. Reuse exact selections, and never create a default design or open the original writable project as an inspection shortcut.

| Task | Template | Task-specific fields | Case count |
| --- | --- | --- | --- |
| opt | `configs/template_opt.json` | `parameters`, `target`, `algorithm` | Declared simulation budget; population × iterations is an estimate, excluding final revalidation and some startup calls |
| sweep OAT | `configs/template_sweep.json` | `study.mode=oat`, `study.variables[*].name/start/stop/step`, target in `study` | Sum of generated per-variable grids |
| sweep grid | Same sweep template | `study.mode=grid`, same variable fields, `study.max_cases` | Product of grid sizes |
| sweep explicit | Same sweep template | `study.mode=explicit`, `study.cases[*].params`, target in `study` | Number of listed cases |
| val | `configs/template_val.json` | `cases[*].name/params`, `target`, optional `evaluation_mode` | Number of listed cases |

Sweep configs must not contain top-level `parameters`, `target` or `algorithm`. Use `optimizer.core.study.build_study_cases` to count the actual points, including endpoint semantics and max_cases limits; do not estimate using binary floating-point division. OAT starts each case from the same full baseline. Grid/explicit change only their declared values from that baseline.

For opt, prefer `min/max/resolution` plus unit and constraints when needed. Choose an algorithm appropriate to the user's objective, budget and existing decisions; do not impose a universal DE/JADE default. `configs/template_bo.json` is an optional BO-specific example.

For val, explicit unit strings preserve intended assignments. In `existing_results` mode, parameter edits and new solves are forbidden; prove the existing variation matches. Required evaluation targets and result expressions follow the current evaluator/collector interface, not invented config keys.

Load configs with `optimizer.config_io.load_config`; check with `optimizer.task_config.validate_task_config`. This check is partial: still verify live variable names, expressions/units, project/design/setup/sweep and available outputs before solving. Use the selected template's path conventions and the current path resolver. Store generated configs under `configs/`; use unique run identities and let the CLI allocate run stamps.

## Time and launch summary

Summarize the concrete config in chat, with only applicable fields. A single baseline val is one parameter case, not one frequency sample; analyzing a setup may execute multiple enabled sweeps. Declare whether the target is a diagnostic or a scientific acceptance requirement.

Use current local time with explicit timezone for `optimization.end_at`. If no measured per-case duration exists, state that runtime is unknown and distinguish the soft budget from a duration prediction. The first real solve can establish a later estimate. Do not call this deadline a hard solver timeout.

Only the CLI launches tasks: `python optimizer/cli.py <config>` in a source checkout, or `python -m optimizer.cli <config>` in an installed-package workspace without that source file. Preserve requested dashboard/browser settings. Neither `optimizer/main.py` nor `optimizer/run_optimizer.py` is a second launch path for this skill.

## Result acceptance

Check persisted evidence, not only console success:

- Source SHA256 before/after matches; the connected project/design refer to the protected copy and intended design.
- Case parameter expressions read back correctly; results identify the configured setup/sweep and exactly the requested variation. Preserve units in returned PyAEDT quantities when serializing provenance.
- Frequency axis has explicit units, strictly increasing finite samples, matching curve lengths and required band boundaries/point counts. S parameters come from their declared expressions and consistent axes.
- Required metrics and evaluation are valid and finite. Report target attainment separately; a failed target does not imply a read failure.
- Case journal, raw data and terminal task state agree; failed cases are visible and all-failed tasks return nonzero. Verify per-case baseline isolation/restoration during search, sweep and validation. A successful final optimization export retains the verified best point; do not restore or save the work model again after that export.
- Verify the owned AEDT session actually closes when requested. PyAEDT decorated APIs may return `False` instead of raising; check returns and process state. A retained session must be reported.
- For changed parameters, enable `output.geometry_snapshot` for the selected model objects when CAD readback is required; verify actual dimensions and restored bounding boxes in model units. Bounding boxes do not prove topology, material or connectivity.
- For best-model export, `export_verified=true` certifies the final in-memory solve, not an independently reopened disk model. After optimization has exported its best and disconnected without rewriting the work model, open a fresh protected copy of the actual exported AEDT file. Compare its initial parameters and CAD **before assigning any case parameters** to the verified best point. Then solve through the CLI and compare variation/axes/curves within a declared tolerance. Case assignment can hide a wrong saved model; a completed validation alone is insufficient. Keep a hash of the accepted file and preserve rejected export evidence.
- `optimization.save_interval` controls periodic best snapshots (default 10 search simulations; 0 disables). Cache hits and export verification solves do not trigger intervals. Periodic export adds one verification solve and then restores the ongoing search baseline; final export retains its point. Multi-objective intervals defer/coalesce until a complete population update chooses a representative. Verify `best_model_exported` events/files, not just the old checkpoint flag; time-budget skips and save failures must remain visible. Default work copies belong under temp and snapshots under runs; keep explicitly configured paths in the launch summary.
- Distinguish search solve counts, cache reuse, final export verification and independent reopen solves in reports and budgets. A model-only snapshot excludes solver caches and needs a fresh solve.
- `optimization.keep_working_copy=true` explicitly retains the closed temp project and solver cache for inspection or a later `existing_results` task; it does not keep the desktop running. Default cleanup remains unchanged. Existing-results cases must match saved parameters and must not solve, assign variables, or save the source; preserve its hash and never interpret missing cache as a valid trace.
- Far-field data may use a different stored-field solution from the S-parameter sweep: specify `target.far_field.setup_sweep_name` and explicit frequencies/sphere. Four principal cuts remain cuts. For a full sampled sphere via CSV fallback, provide `phi_samples_deg` (at least eight unique angles in [0,360)); the reader checks full Theta coverage and the Cartesian grid before labeling it `sampled_sphere`. A sampled peak is not a continuous-angle maximum. Missing field storage or incomplete requested coverage fails required metrics.
- A sweep `study.tracking_port` can observe an existing native edge-attached integration line without detaching it; actual edge positions are recorded in case metrics. Only supported OnEdge attachments are accepted, and an explicit gap cannot override them. Explicit Start/End lines retain the existing translation/gap behavior. Verify geometry motion and restored endpoints for the selected model rather than assuming feed-length and port-height signs coincide.

A nominal-case result does not validate changed-parameter CAD regeneration, sweep isolation, optimization search, final project export, far field, via geometry, Gerber, or CAM reconstruction. Record those as separate gates.

## Diagnosis and retest

1. Retain config snapshot, logs, journal and error details for the failed attempt. The current adapter cleans its temporary project/results on disconnect, so copy any extra diagnostic evidence before cleanup if needed; durable run logs remain. Do not describe an automatically deleted work project as retained.
2. Identify the failing phase and actual API values/types/units. Check installed API signatures before changing calls. Preserve correct integrity checks and add a regression test when a substantive code fix is needed.
3. Relaunch the same authorized baseline after a supported correction, with a fresh run identity. This is a fresh test, not checkpoint resume. Do not overwrite journals. Retry only when a changed diagnostic or correction can make progress; do not blindly repeat identical failures.
4. When stopping is needed, first identify the task launcher by config/run identity. Stop AEDT/solver processes only with proven ownership (captured PID, executable/start time, process relationship or working project). Never stop another user's session. If ownership is ambiguous, report the blocker and request the missing information.
5. COM reattachment by PID is not assumed reliable; this environment's preflight created a different desktop despite a requested PID. Prefer retaining and closing the same owned session object, using version-checked release signatures.
6. Report the successful retest and preserved failure paths, source protection and compatibility actually tested. Explicitly list anything blocked by an external license/service rather than marking it passed.
