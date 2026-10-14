---
name: hh-iter
description: Analyze the finished hfss-harness optimization round by reading the current config, data log, and history log, summarize how parameters affected the optimization target, and draft the next config with the current best case as the initial point. Use when a round has just finished and the next optimization round needs a lightweight update.
---

# HFSS Harness Iter

Use this skill after one optimization round finishes.

1. Locate the selected round's actual config snapshot, terminal summary, case journal, raw data and history files. Read their declared paths and schemas; do not assume a model name, frequency band or log filename. Check that the round is no longer running.
2. Confirm project/context, parameter names/order/units, target and active evaluation stage. Use valid cases only. Cross-check the terminal best parameters with their successful case and final evaluation; costs from different stages/targets are not directly comparable. For multi-objective runs, identify the recorded representative and Pareto alternatives instead of inventing a unique optimum.
3. Analyze metrics actually defined by this task. Separate genuine solves from repeated cache reuse, and do not count the same observation repeatedly. Describe associations and boundary pressure with sample counts; correlations from a few optimization samples do not establish causal sensitivity.
4. Report the best valid case, target attainment, weak/strong evidence and missing information. A valid result may miss the target; failed or nonfinite data is not a poor-but-valid sample.
5. Write a new config draft without overwriting the current round. Put the verified best point in `optimization.initial_point`, using the current parameter order or supported name mapping and numerical values in the declared units. Check new bounds, resolution and constraints against that point. Preserve explicit `seed_initial_point` choices and explain if seeding is disabled. Use [range policy](references/range_policy.md) for conservative changes.

Rules:

- Keep the target, units, simulator setup, and resolution unchanged unless the user asks otherwise.
- Do not invent new parameters.
- Do not drop the current best case from the new range.
- If the logs are incomplete, report that clearly and make the smallest safe update.
- If no best case can be verified, do not invent an initial point or claim an optimized next round. Preserve the existing config and identify the missing evidence.
- Drafting the next config does not launch a solve. Run preparation/launch follows `$hh-sim` and the user's existing authorization.

## Resources

- [references/range_policy.md](references/range_policy.md): signals, evidence limits and range changes
- `agents/openai.yaml`: UI metadata and default prompt for the project skill

No general iteration helper is currently provided by this skill. Read the selected artifacts directly or use a small task-local analysis. Historical helpers use case-specific evaluation assumptions and are excluded from the active skill; do not reuse them as a general evaluator or add a new framework for a single round.
