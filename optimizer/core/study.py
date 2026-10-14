"""Helpers for sweep-style S-parameter studies."""

from __future__ import annotations

from typing import Iterable, Sequence
from decimal import Decimal
import math
import itertools

import numpy as np


def build_step_sweep_values(start: float, stop: float, step: float, digits: int | None = None) -> list[float]:
    """Build an inclusive rounded sweep grid."""
    if not all(math.isfinite(float(value)) for value in (start, stop, step)):
        raise ValueError("Sweep values must be finite")
    if step <= 0:
        raise ValueError("step must be positive")
    if stop < start:
        raise ValueError("stop must be greater than or equal to start")

    low, high, delta = (Decimal(str(value)) for value in (start, stop, step))
    count = int((high - low) / delta) + 1
    if count > 100000:
        raise ValueError("Sweep grid exceeds 100000 points")
    values = [float(low + index * delta) for index in range(count)]
    return [round(value, digits) for value in values] if digits is not None else values


def build_study_cases(study):
    """Build bounded OAT, Cartesian grid or explicit cases before touching AEDT."""
    mode = study.get("mode", "oat")
    limit = study.get("max_cases", 100000)
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError("study.max_cases must be an integer in 1..100000")
    if mode == "explicit":
        entries = study.get("cases")
        if not isinstance(entries, list) or not entries or len(entries) > limit:
            raise ValueError("Explicit study requires cases within max_cases")
        cases = []
        for index, case in enumerate(entries, 1):
            if not isinstance(case, dict):
                raise ValueError("Explicit cases must be objects")
            values = case.get("params", {k: v for k, v in case.items() if k != "name"})
            if not isinstance(values, dict) or not values:
                raise ValueError("Explicit cases require parameter values")
            cases.append({"params": dict(values), "variable": "explicit", "value": index,
                          "case_name": case.get("name", f"case_{index:03d}"),
                          "variable_index": 1, "point_index": index, "point_count": len(entries)})
        return cases
    if mode not in {"oat", "grid"}:
        raise ValueError("study.mode must be oat, grid or explicit")
    variables = study.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("Study requires at least one variable")
    names = [str(variable["name"]) for variable in variables]
    if len(set(names)) != len(names):
        raise ValueError("Study variable names must be unique")
    grids = [build_step_sweep_values(v["start"], v["stop"], v["step"]) for v in variables]
    count = sum(map(len, grids)) if mode == "oat" else math.prod(map(len, grids))
    if count > limit:
        raise ValueError("Study exceeds configured max_cases")
    if mode == "grid":
        return [{"params": dict(zip(names, point)), "variable": "grid", "value": index,
                 "variable_index": 1, "point_index": index, "point_count": count}
                for index, point in enumerate(itertools.product(*grids), 1)]
    return [{"params": {name: value}, "variable": name, "value": value,
             "variable_index": vi, "point_index": pi, "point_count": len(grid)}
            for vi, (name, grid) in enumerate(zip(names, grids), 1)
            for pi, value in enumerate(grid, 1)]


def summarize_sparameter_band(
    freqs: Sequence[float] | np.ndarray,
    s11: Sequence[float] | np.ndarray,
    s12: Sequence[float] | np.ndarray | None,
    freq_band: tuple[float, float],
    s11_threshold: float,
    s12_threshold: float | None = None,
) -> dict:
    """Summarize worst-case and pass-rate metrics inside one frequency band."""
    freq_array = np.asarray(freqs, dtype=float)
    s11_array = np.asarray(s11, dtype=float)
    s12_array = np.asarray(s12, dtype=float) if s12 is not None else None

    if freq_array.size == 0 or s11_array.size == 0:
        raise ValueError("freqs and s11 must be non-empty")

    mask = (freq_array >= float(freq_band[0])) & (freq_array <= float(freq_band[1]))
    if not np.any(mask):
        raise ValueError("no frequency points fall inside the requested band")

    band_freqs = freq_array[mask]
    band_s11 = s11_array[mask]
    band_s12 = s12_array[mask] if s12_array is not None else None

    s11_pass_mask = band_s11 <= float(s11_threshold)
    point_count = int(band_freqs.size)
    summary = {
        "freq_start_ghz": float(band_freqs[0]),
        "freq_end_ghz": float(band_freqs[-1]),
        "point_count": point_count,
        "s11_worst_db": float(np.max(band_s11)),
        "s11_best_db": float(np.min(band_s11)),
        "s11_avg_db": float(np.mean(band_s11)),
        "s11_pass_count": int(np.count_nonzero(s11_pass_mask)),
        "s11_pass_ratio": float(np.count_nonzero(s11_pass_mask) / point_count),
    }

    if band_s12 is not None:
        if s12_threshold is None:
            raise ValueError("s12_threshold is required when s12 data is provided")
        s12_pass_mask = band_s12 <= float(s12_threshold)
        summary.update(
            {
                "s12_worst_db": float(np.max(band_s12)),
                "s12_best_db": float(np.min(band_s12)),
                "s12_avg_db": float(np.mean(band_s12)),
                "s12_pass_count": int(np.count_nonzero(s12_pass_mask)),
                "s12_pass_ratio": float(np.count_nonzero(s12_pass_mask) / point_count),
            }
        )

    return summary


def summarize_longest_matched_band(
    freqs: Sequence[float] | np.ndarray,
    s11: Sequence[float] | np.ndarray,
    s12: Sequence[float] | np.ndarray | None,
    s11_threshold: float,
) -> dict:
    """Summarize the longest contiguous S11-feasible band and its S12 quality."""
    freq_array = np.asarray(freqs, dtype=float)
    s11_array = np.asarray(s11, dtype=float)
    s12_array = np.asarray(s12, dtype=float) if s12 is not None else None

    if freq_array.size == 0 or s11_array.size == 0:
        raise ValueError("freqs and s11 must be non-empty")
    if freq_array.size != s11_array.size:
        raise ValueError("freqs and s11 must have the same length")
    if s12_array is not None and s12_array.size != freq_array.size:
        raise ValueError("freqs and s12 must have the same length")

    feasible_idx = np.where(s11_array <= float(s11_threshold))[0]
    if feasible_idx.size == 0:
        return {
            "matched_point_count": 0,
            "matched_bandwidth_ghz": 0.0,
            "matched_start_ghz": None,
            "matched_end_ghz": None,
            "matched_s11_worst_db": None,
            "matched_s12_worst_db": None,
        }

    split_points = np.where(np.diff(feasible_idx) > 1)[0]
    segments = np.split(feasible_idx, split_points + 1)

    best_segment = None
    best_bandwidth = -1.0
    for segment in segments:
        if segment.size == 0:
            continue
        bandwidth = 0.0 if segment.size < 2 else float(freq_array[segment[-1]] - freq_array[segment[0]])
        if bandwidth > best_bandwidth:
            best_segment = segment
            best_bandwidth = bandwidth

    if best_segment is None:
        raise RuntimeError("failed to determine a matched segment")

    seg_freqs = freq_array[best_segment]
    seg_s11 = s11_array[best_segment]
    seg_s12 = s12_array[best_segment] if s12_array is not None else None

    summary = {
        "matched_point_count": int(best_segment.size),
        "matched_bandwidth_ghz": float(best_bandwidth),
        "matched_start_ghz": float(seg_freqs[0]),
        "matched_end_ghz": float(seg_freqs[-1]),
        "matched_s11_worst_db": float(np.max(seg_s11)),
    }
    if seg_s12 is not None:
        summary["matched_s12_worst_db"] = float(np.max(seg_s12))
        summary["matched_s12_best_db"] = float(np.min(seg_s12))
        summary["matched_s12_avg_db"] = float(np.mean(seg_s12))

    return summary
