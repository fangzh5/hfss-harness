# Range Policy

Use this policy when a hfss-harness optimization round has finished and the next config needs to be drafted.

## Inputs

- current round config
- `opt_data.jsonl` or `data.jsonl`
- `opt_history.csv` or `history.csv`

## Main signals

- `cost`
- `total_violation`
- `band_max`
- `edge54`
- `edge66`

## Sensitivity checks

- Spearman correlation against `cost`
- Spearman correlation against `total_violation`
- top-sample boundary pressure
- repeated boundary hits among the best samples

## Range update rules

- Keep the best case inside the next range.
- Narrow stable parameters.
- Shift ranges in the direction that reduces `total_violation`.
- Expand a side if the best samples repeatedly hit that boundary.
- Keep resolution and units unchanged unless the user asks otherwise.
- Keep the change conservative when the logs are sparse or noisy.

## Output

The next config should include:

- the best case as `initial_point`
- updated parameter windows
- the original target and simulator settings


