---
name: hh-sim
description: Prepare or run HFSS/AEDT optimization, parameter sweeps, and fixed-case validation in hfss-harness. Use for a specific .aedt simulation task; use the modeling skills for via creation, fabrication, or reconstruction.
---

# HFSS Harness Sim

Read the applicable repository contract (`AGENTS.md`, or legacy `AGENT.md`), then select the requested task. Use [task configuration and run checks](references/hfss-harness-workflow.md) for the relevant mode and failure handling.

## Prepare a concrete task

- Inspect designs, setup/sweep names, nominal variable expressions and units on a protected project copy. Pin the intended project and design; inspection does not authorize solving or editing the source project.
- Use `python -m optimizer.inspect_aedt <source> --design <design> --setup <setup> --sweep <sweep>` for protected-copy metadata intake. Omit unknown selections to get `needs_input` and the available inventory; an explicit wrong selection fails instead of falling back. The inspection command never solves or saves the source.
- `opt`: collect varying parameters, bounds/resolution, target, algorithm and search budget.
- `sweep`: collect OAT/grid/explicit mode, variable values or ranges/steps, evaluation target and budget. No search algorithm is needed.
- `val`: collect explicit parameter cases and evaluation target; distinguish fresh `solve` from `existing_results`. Fixed cases need neither parameter ranges nor a search algorithm. For a chain smoke test, report target attainment separately from data validity.
- Ask only for material inputs still missing after inspecting the project and conversation. Reuse the user's supplied baseline, target and launch authorization.
- Draft a JSON config using the matching `configs/template_opt.json`, `template_sweep.json` or `template_val.json`; validate it with the current checkout's config and case builders. Templates are examples, not a complete schema or verified compatibility declaration.
- Replace example project/design/setup/sweep, parameter names/values, constraints and frequency targets with the inspected model and current user inputs. Do not carry another model's settings into a new task or launch an unchanged example template.

Summarize the concrete config in chat: selected project/design/setup/sweep, parameter cases or ranges, target, applicable algorithm, case count or estimate, output location and time budget. Preserve the config and evidence in files when useful.

## Launch within the authorized scope

Explicit user instructions take precedence over this skill's guidelines. If launch authorization is already present, proceed without asking again. A request only to draft a config does not authorize solving. If authorization is missing, finish the reviewable config first, then ask for launch approval. Diagnosed fixes and retests can reuse authorization that covers them; a new physical scope or contradictory input needs clarification.

Launch only through:

```powershell
python optimizer/cli.py <config>
```

In a workspace created from an installed package, use `python -m optimizer.cli <config>` when the source file is absent. This is the same CLI entrypoint, not a second task runner.

Keep dashboard behavior consistent with the config/user preference. Compute a budget deadline from the actual launch time in the user's timezone. Current `end_at` prevents starting another case; it does not guarantee cancellation of an active AEDT solve.

## Verify completion and handle failures

Observe the first `min(5, planned_case_count)` cases; a one-case validation ends after that case and terminal artifact checks. For optimization without a known finite case count, observe the first five attempts. Check logs, case journal, actual result data and final task state; a dashboard or successful connection alone is insufficient.

Accept a baseline chain only after a real solve succeeds, finite frequency data has explicit units and required coverage, setup/sweep and returned variation match the requested case, evaluation is valid, and the full baseline is restored. `target_met=false` can be a valid scientific result. Report the outcome, failed attempts, result artifacts and remaining untested paths.

On failure, use [diagnosis and retest guidance](references/hfss-harness-workflow.md#diagnosis-and-retest). Preserve failure evidence, correct a supported cause, and use a fresh run directory for each retest. Never bypass variation, unit or coverage checks to make a run pass. Stop repeating an unchanged failure when no useful diagnosis remains; explain any external blocker. Close or stop only resources whose ownership by this run is established.
