#!/usr/bin/env python3
"""Analyze a hfss-harness optimization round and draft the next config."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from statistics import mean
from typing import Any


EDGE_FREQS = {54.0, 66.0}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a hfss-harness optimization run and write a next-round config."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-id", help="Task folder name under runs/")
    group.add_argument("--run-dir", help="Path to a concrete timestamped run folder")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root that contains runs/ and configs/ (default: current directory)",
    )
    parser.add_argument(
        "--output-config",
        help="Where to write the next config JSON. Default: configs/<task_id>_next.json",
    )
    parser.add_argument(
        "--summary-json",
        help="Optional path for a machine-readable analysis summary",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the proposed config without writing files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def rankdata(values: list[float]) -> list[float]:
    order = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and order[j][1] == order[i][1]:
            j += 1
        rank = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[order[k][0]] = rank
        i = j
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = mean(x)
    my = mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = math.sqrt(sum((a - mx) ** 2 for a in x))
    deny = math.sqrt(sum((b - my) ** 2 for b in y))
    if denx == 0.0 or deny == 0.0:
        return 0.0
    return num / (denx * deny)


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(rankdata(x), rankdata(y))


def threshold(freq: float) -> float:
    return -10.0 if freq in EDGE_FREQS else -13.0


def evaluate_sample(sample: dict[str, Any]) -> dict[str, float]:
    freqs = [float(v) for v in sample.get("s_freqs", [])]
    s11 = [float(v) for v in sample.get("s11", [])]
    violations = [max(0.0, s11v - threshold(freq)) for freq, s11v in zip(freqs, s11)]
    return {
        "total_violation": sum(violations),
        "worst_violation": max(violations) if violations else 0.0,
        "band_max": max(s11) if s11 else 0.0,
        "edge54": s11[0] if s11 else 0.0,
        "edge66": s11[-1] if s11 else 0.0,
        "pass_points": sum(1 for freq, s11v in zip(freqs, s11) if s11v <= threshold(freq)),
        "min_margin": min((threshold(freq) - s11v) for freq, s11v in zip(freqs, s11)) if s11 else 0.0,
    }


def choose_latest_run_dir(task_root: Path) -> Path:
    candidates = [p for p in task_root.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run subdirectories under {task_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def find_existing(root: Path, names: list[str]) -> Path:
    for name in names:
        candidate = root / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"None of these files exist under {root}: {', '.join(names)}")


def round_to_resolution(value: float, resolution: float) -> float:
    if resolution <= 0:
        return value
    return round(round(value / resolution) * resolution, 10)


def propose_range(
    old_min: float,
    old_max: float,
    best_value: float,
    top_mean: float,
    rho_cost: float,
    rho_violation: float,
    low_hit: float,
    high_hit: float,
    resolution: float,
) -> tuple[float, float, dict[str, Any]]:
    width = old_max - old_min
    sensitivity = max(abs(rho_cost), abs(rho_violation))
    if sensitivity >= 0.45:
        shrink = 0.50
    elif sensitivity >= 0.25:
        shrink = 0.65
    else:
        shrink = 0.80

    target_width = max(resolution * 4.0, width * shrink)
    center = 0.65 * best_value + 0.35 * top_mean
    reason: list[str] = [f"sensitivity={sensitivity:.3f}", f"shrink={shrink:.2f}"]
    lower_cap = old_min
    upper_cap = old_max

    low_pressure = low_hit >= 0.40 and best_value <= old_min + 0.10 * width
    high_pressure = high_hit >= 0.40 and best_value >= old_max - 0.10 * width
    if low_pressure and not high_pressure:
        lower_cap = old_min - 0.15 * width
        center = min(center, old_min + 0.25 * width)
        reason.append("expand_low")
    elif high_pressure and not low_pressure:
        upper_cap = old_max + 0.15 * width
        center = max(center, old_max - 0.25 * width)
        reason.append("expand_high")

    new_min = center - target_width / 2.0
    new_max = center + target_width / 2.0
    new_min = max(new_min, lower_cap)
    new_max = min(new_max, upper_cap)

    if new_min > best_value:
        new_min = min(best_value - resolution, upper_cap - 2 * resolution)
        reason.append("keep_best_inside_min")
    if new_max < best_value:
        new_max = max(best_value + resolution, lower_cap + 2 * resolution)
        reason.append("keep_best_inside_max")

    if new_max <= new_min:
        half = max(resolution * 2.0, target_width / 2.0)
        new_min = best_value - half
        new_max = best_value + half
        reason.append("fallback_centered")

    new_min = round_to_resolution(new_min, resolution)
    new_max = round_to_resolution(new_max, resolution)
    if new_max <= new_min:
        new_max = round_to_resolution(new_min + resolution, resolution)

    return new_min, new_max, {"center": center, "width": target_width, "reasons": reason}


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        task_id = run_dir.parent.name if run_dir.parent != run_dir else run_dir.name
    else:
        task_id = args.task_id
        run_root = workspace / "runs" / task_id
        run_dir = choose_latest_run_dir(run_root)

    config_path = run_dir / "config.json"
    if not config_path.exists():
        configs_dir = workspace / "configs"
        candidates = sorted(configs_dir.glob(f"{task_id}*.json"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise FileNotFoundError(f"Could not find base config for {task_id}")
        config_path = candidates[-1]

    data_path = find_existing(run_dir, ["opt_data.jsonl", "data.jsonl"])
    history_path = find_existing(run_dir, ["opt_history.csv", "history.csv"])

    config = load_json(config_path)
    data_rows = load_jsonl(data_path)
    history_rows = load_csv(history_path)

    history_by_sim: dict[int, dict[str, str]] = {}
    for row in history_rows:
        sim_id = row.get("sim_id")
        if sim_id is None:
            continue
        try:
            history_by_sim[int(sim_id)] = row
        except ValueError:
            continue

    analyzed: list[dict[str, Any]] = []
    for sample in data_rows:
        sim_id = int(sample["sim_id"])
        metrics = evaluate_sample(sample)
        hist = history_by_sim.get(sim_id, {})
        params = sample.get("params", {})
        analyzed.append(
            {
                "sim_id": sim_id,
                "iter": int(sample.get("iter", 0)),
                "cost": as_float(hist.get("cost"), metrics["total_violation"]) or 0.0,
                **metrics,
                **{k: float(v) for k, v in params.items()},
            }
        )

    if not analyzed:
        raise RuntimeError(f"No analyzable rows found in {data_path}")

    best_row = min(analyzed, key=lambda row: row["cost"])
    top_n = max(6, math.ceil(len(analyzed) * 0.10))
    top_rows = sorted(analyzed, key=lambda row: row["total_violation"])[:top_n]

    parameter_names = [p["name"] for p in config.get("parameters", [])]
    metrics = {
        "cost": [row["cost"] for row in analyzed],
        "total_violation": [row["total_violation"] for row in analyzed],
        "band_max": [row["band_max"] for row in analyzed],
        "edge54": [row["edge54"] for row in analyzed],
        "edge66": [row["edge66"] for row in analyzed],
        "pass_points": [row["pass_points"] for row in analyzed],
        "worst_violation": [row["worst_violation"] for row in analyzed],
    }

    sensitivity_rows: list[dict[str, Any]] = []
    next_parameters: list[dict[str, Any]] = []
    best_params = [best_row[name] for name in parameter_names]

    for param in config.get("parameters", []):
        name = param["name"]
        values = [row[name] for row in analyzed]
        rho_cost = spearman(values, metrics["cost"])
        rho_violation = spearman(values, metrics["total_violation"])

        top_mean = mean(row[name] for row in top_rows)
        low = float(param["min"])
        high = float(param["max"])
        resolution = float(param.get("resolution", 0.01))
        width = high - low
        tol = max(1e-9, width * 0.05)
        low_hit = sum(1 for row in top_rows if row[name] <= low + tol) / len(top_rows)
        high_hit = sum(1 for row in top_rows if row[name] >= high - tol) / len(top_rows)
        new_min, new_max, policy = propose_range(
            low,
            high,
            float(best_row[name]),
            float(top_mean),
            rho_cost,
            rho_violation,
            low_hit,
            high_hit,
            resolution,
        )

        sensitivity_rows.append(
            {
                "name": name,
                "rho_cost": rho_cost,
                "rho_total_violation": rho_violation,
                "low_hit": low_hit,
                "high_hit": high_hit,
                "best_value": float(best_row[name]),
                "top_mean": float(top_mean),
                "new_min": new_min,
                "new_max": new_max,
                "policy": policy,
            }
        )
        next_parameters.append(
            {
                **param,
                "min": new_min,
                "max": new_max,
            }
        )

    next_config = dict(config)
    next_config["name"] = f"{config.get('name', task_id)}_next"
    optimization = dict(config.get("optimization", {}))
    optimization["initial_point"] = best_params
    original_work_dir = optimization.get("work_dir", "../temp")
    if os.path.isabs(str(original_work_dir)):
        optimization["work_dir"] = "../temp"
    optimization.pop("run_stamp", None)
    optimization.pop("task_output_dir", None)
    next_config["optimization"] = optimization
    next_config["parameters"] = next_parameters

    if args.output_config:
        output_config = Path(args.output_config)
    else:
        output_config = workspace / "configs" / f"{task_id}_next.json"

    output_config.parent.mkdir(parents=True, exist_ok=True)
    if output_config.exists() and not args.force and not args.preview:
        raise FileExistsError(f"Refusing to overwrite existing file: {output_config}")

    summary = {
        "task_id": task_id,
        "run_dir": str(run_dir),
        "config_path": str(config_path),
        "data_path": str(data_path),
        "history_path": str(history_path),
        "best_sim_id": best_row["sim_id"],
        "best_iter": best_row["iter"],
        "best_cost": best_row["cost"],
        "best_total_violation": best_row["total_violation"],
        "best_params": {name: best_row[name] for name in parameter_names},
        "sensitivity": sensitivity_rows,
        "next_config_path": str(output_config),
    }

    print(f"Run: {run_dir}")
    print(f"Best sim: {best_row['sim_id']} | iter: {best_row['iter']} | cost: {best_row['cost']:.6f}")
    print(f"Best S11 max: {best_row['band_max']:.2f} dB | total violation: {best_row['total_violation']:.6f}")
    print("Sensitivity ranking:")
    for row in sorted(sensitivity_rows, key=lambda item: max(abs(item["rho_cost"]), abs(item["rho_total_violation"])), reverse=True):
        print(
            f"  {row['name']}: rho(cost)={row['rho_cost']:+.3f}, "
            f"rho(total_violation)={row['rho_total_violation']:+.3f}, "
            f"hits(low/high)={row['low_hit']:.2f}/{row['high_hit']:.2f}, "
            f"range=[{row['new_min']:.3f}, {row['new_max']:.3f}]"
        )

    if args.preview:
        print("\nProposed next config:")
        print(json.dumps(next_config, indent=2, ensure_ascii=False))
    else:
        with output_config.open("w", encoding="utf-8") as fh:
            json.dump(next_config, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Next config written: {output_config}")

    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Summary written: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


