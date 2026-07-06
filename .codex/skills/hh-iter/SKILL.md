---
name: hh-iter
description: Analyze the finished hfss-harness optimization round by reading the current config, data log, and history log, summarize how parameters affected the optimization target, and draft the next config with the current best case as the initial point. Use when a round has just finished and the next optimization round needs a lightweight update.
---

# HFSS Harness Iter

Use this skill after one optimization round finishes.

1. Read the round's config, data log, and history log.
2. Find the best case from the finished round.
3. Compare parameter values against the target to see which knobs help or hurt.
4. Report the sensitivity findings briefly.
5. Update the next config with the best case as `initial_point` and adjusted parameter ranges.

Rules:

- Keep the target, units, simulator setup, and resolution unchanged unless the user asks otherwise.
- Do not invent new parameters.
- Do not drop the current best case from the new range.
- If the logs are incomplete, report that clearly and make the smallest safe update.

## Resources

- `scripts/opt_iter.py`: helper for reading run logs, scoring sensitivity, and drafting the next config
- `references/range_policy.md`: short range-adjustment policy for next-round updates
- `agents/openai.yaml`: UI metadata and default prompt for the project skill


