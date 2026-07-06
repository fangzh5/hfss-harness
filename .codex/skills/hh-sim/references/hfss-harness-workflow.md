# hfss-harness sim-intake workflow

## Scope

This skill is repo-specific. Use it when the current workspace follows the `hfss-harness` repository layout and the user wants a new `opt`, `sweep`, or `val` task/config for a specific `.aedt` project.

## Repo files to read first

1. `AGENT.md`
2. `configs/template.json`
3. If needed: `docs/agent-reference.md`

## Task-type mapping

- `opt`: optimization request, budgeted search, algorithm choice matters
- `sweep`: one-variable-at-a-time study
- `val`: explicit case verification

## Config drafting rules

### opt

- Start from `configs/template.json`
- Prefer parameter fields:
  - `name`
  - `min`
  - `max`
  - `resolution`
  - optional `unit`
  - optional `constraint`
- Do not introduce `count` or `step` for new configs unless the user explicitly asks for legacy discrete behavior.
- Default single-objective algorithm is usually:
  - `method = "de"`
  - `strategy = "jade"`
- If the user asks for Pareto or multiple conflicting objectives, use `nsga2`.

### sweep

- Use `study.variables[*]` with `name/start/stop/step`
- Sweep one variable at a time
- Total points = sum of per-variable step counts

### val

- Use `cases[*]`
- Preferred shape:
  - `{"name": "case_001", "params": {...}}`
- Total simulations = `len(cases)`

## Naming

Config names should stay close to the repo convention:

- `<antenna>_<band>_<algo>[_variant]` for `opt`
- `<antenna>_<band>_sweep[_variant]` for `sweep`
- `<antenna>_<band>_val[_variant]` for `val`

## Intake questions

Only ask for what is still missing.

Typical missing inputs:

- Which parameters should vary
- Range or step for each varying parameter
- Objective or pass target
- Budget
  - wall-clock budget
  - or expected single-sim time
  - or both

## Chat summary format

Present the summary in the current chat window, not as a local file.

Recommended columns:

- Parameter
- Role
- Min / Start
- Max / Stop
- Step / Resolution
- Notes

Then state:

- task type
- selected design / setup / sweep
- algorithm
- estimated simulation count
- estimated wall time
- estimated finish time
- config output path

## Simulation-count estimation

Use these rules:

- `opt`
  - If `algorithm.max_simulations` is set, use it as the main estimate.
  - Otherwise estimate with `population_size * max_iterations`.
  - Make it explicit when this is an upper bound.
- `sweep`
  - Count each variable's stepped values and sum them.
- `val`
  - Count the cases.

## Finish-time estimation

- Use current local machine time.
- Preferred estimate:
  - `simulation_count * per_sim_time`
- If the user gives a wall-clock budget directly, use that budget for end-time reporting.
- Say clearly whether the estimate is budget-driven or sim-count-driven.

## Launch command

Only use:

```powershell
python optimizer\\cli.py <config>
```

Do not launch through `optimizer/main.py` or `optimizer/run_optimizer.py`.

## First-five-sim monitoring

Treat the run as healthy only if these signs appear:

1. run output directory is created
2. log files are created under `runs/.../logs`
3. progress markers start advancing
4. first simulations complete without repeated immediate failure
5. output data files begin to appear or grow

Abnormal startup examples:

- optimizer process exits immediately
- repeated connection failure to AEDT/HFSS
- repeated `simulate()` failure or empty result arrays
- no progress after a reasonable wait for the first simulation
- dashboard exists but task process is already dead

## Safe restart policy

If startup is abnormal during the first five simulations:

1. Identify the run-specific launcher process first.
   - Match by command line containing `optimizer\cli.py`
   - Match by config path or run stamp when available
2. Stop that launcher process first.
3. Stop AEDT / solver processes only if they can be tied to this run.
   - Match by child-process relationship, run-specific working copy path, or command line.
4. Never kill unrelated manually opened AEDT sessions.
   - If ownership is ambiguous, stop and ask the user.
5. Relaunch once through `optimizer\cli.py`.
6. Report the restart and resume monitoring.

## Metadata inspection script

Use `scripts/read_aedt_metadata.py` to list:

- designs
- active design
- setup names
- analysis sweeps
- nominal parameters

This script must not read the source project directly. It first copies the target `.aedt` into the repository's `temp/readonly/<project>/...` directory, opens that mirror file, prints JSON, then deletes the temporary mirror.


