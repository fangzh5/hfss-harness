---
name: hh-sim
description: Create HFSS/AEDT opt, sweep, or validation tasks for the hfss-harness repository. Use when the user asks to create a config or task for a specific .aedt file, including requests to make an optimization, sweep, or validation config, or asks to start such a run after intake. The skill reads the repo contract, inspects the .aedt design, setup, sweep, and parameter set, requires explicit user confirmation of parameter ranges, target definition, algorithm, and end time before launch, drafts the config, summarizes it in chat, launches only through optimizer/cli.py, and watches the first five simulations for startup issues.
---

# HFSS Harness Sim

Use this skill only inside the hfss-harness repository.

## Workflow

1. Read AGENT.md first.
2. Determine whether the request is opt, sweep, or val.
   - If the user already says opt, use opt.
   - If the user asks for scan or study, use sweep.
   - If the user asks to verify fixed cases, use val.
   - If ambiguous, ask one short question.
3. Inspect the target .aedt before proposing the config.
   - Use the repo's metadata reader or the nearest deterministic alternative available in this checkout.
   - Collect available designs, the active design, setup names, analysis sweeps, and nominal parameter values.
4. Ask only for missing intake inputs.
   - Required launch inputs are parameter ranges, target definition, algorithm, and time budget.
   - Reuse anything the user already provided.
   - Do not infer or substitute any launch-critical input.
5. Draft the config from configs/template.json.
   - Save the config under configs/ in the repo.
   - Follow repo rules from AGENT.md.
   - For new opt configs, prefer min/max/resolution; do not introduce count or step unless the user explicitly needs legacy behavior.
6. Before launch, stop and summarize in chat only.
   - Do not create a separate summary file.
   - Present a table with parameter ranges, target, algorithm, estimated simulation count, and estimated finish time.
   - Require the user to explicitly confirm the ranges, target, algorithm, and end time before calling optimizer/cli.py.
   - If anything is still ambiguous, ask instead of launching.
7. Launch only after explicit confirmation.
   - The only supported entry is python optimizer\\cli.py <config>.
8. After launch, monitor the first five simulations.
   - Report whether startup looks normal after each of the first five simulations.
   - If startup is abnormal, safely stop only run-related processes, then relaunch once and report what changed.

## Launch Rules

- Use optimizer/cli.py only.
- Keep dashboard behavior consistent with the repo config unless the user explicitly changes it.
- If the config needs an estimated end time, compute it from the current local time plus the agreed budget.
- Before launch, always restate the parameter ranges, target, algorithm, and estimated end time in one compact confirmation block and wait for the user's approval.

## Resources

- scripts/read_aedt_metadata.py: deterministic .aedt metadata reader when present in the checkout
- AGENT.md: repo-specific startup and config rules


