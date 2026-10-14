"""Shared result-record helpers for optimization and sweep outputs."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import math


def pareto_front_for_json(front):
    """Preserve NSGA boundary meaning without non-standard JSON Infinity."""
    rows = []
    for item in front or []:
        row = dict(item)
        distance = row.get("crowding_distance")
        if distance is not None and not math.isfinite(float(distance)):
            if float(distance) != math.inf:
                raise ValueError("Invalid Pareto crowding distance")
            row["crowding_distance"] = None
            row["crowding_unbounded"] = True
        rows.append(row)
    return rows


def _to_float_list(values: Any) -> list[float]:
    if values is None:
        return []
    try:
        return [float(value) for value in values]
    except Exception:
        return []


def _normalize_param_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    if hasattr(value, "item"):
        try:
            item = value.item()
            if isinstance(item, (int, float, np.integer, np.floating)):
                return float(item)
        except Exception:
            pass
    text = str(value).strip()
    for suffix in ("mm", "cm", "m", "GHz", "Hz", "deg"):
        if text.lower().endswith(suffix.lower()):
            text = text[: -len(suffix)].strip()
            break
    try:
        return float(text)
    except Exception:
        return str(value)


def _normalize_params(params: Any, param_names: Iterable[str] | None = None) -> dict[str, Any]:
    if params is None:
        return {}

    if isinstance(params, dict):
        return {str(name): _normalize_param_value(value) for name, value in params.items()}

    if param_names is not None:
        names = [str(name) for name in param_names]
        values = list(params)
        return {
            name: _normalize_param_value(values[idx])
            for idx, name in enumerate(names)
            if idx < len(values)
        }

    return {str(idx): _normalize_param_value(value) for idx, value in enumerate(list(params))}


def build_far_field_meta_record(far_field: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(far_field, dict):
        return None

    per_frequency = far_field.get("per_frequency")
    if not isinstance(per_frequency, list) or not per_frequency:
        return None

    plane_meta: dict[str, Any] = {}
    for plane_id in ("primary_plane", "orthogonal_plane"):
        plane_info = None
        for item in per_frequency:
            plane_cuts = item.get("plane_cuts") if isinstance(item, dict) else None
            if not isinstance(plane_cuts, dict):
                continue
            candidate = plane_cuts.get(plane_id)
            if isinstance(candidate, dict) and candidate.get("cut_angle_deg"):
                plane_info = candidate
                break
        if not plane_info:
            continue
        plane_meta[plane_id] = {
            "plane_phi_deg": float(plane_info.get("plane_phi_deg", 0.0)),
            "plane_include_opposite": bool(plane_info.get("plane_include_opposite", True)),
            "cut_angle_deg": _to_float_list(plane_info.get("cut_angle_deg", [])),
        }

    return {
        "record_type": "far_field_meta",
        "schema_version": 1,
        "far_field": {
            "freqs_ghz": [
                float(str(freq).replace("GHz", "").strip())
                for freq in far_field.get("frequencies", [])
            ],
            "planes": plane_meta,
        },
    }


def build_far_field_simulation_record(far_field: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(far_field, dict):
        return None

    per_frequency = far_field.get("per_frequency")
    if not isinstance(per_frequency, list) or not per_frequency:
        return None

    cuts = {"primary_plane": [], "orthogonal_plane": []}
    global_peak = {"theta_deg": [], "phi_deg": [], "gain_db": []}
    any_cut = False
    any_peak = False

    for item in per_frequency:
        if not isinstance(item, dict):
            continue

        peak_info = item.get("global_peak_direction")
        if isinstance(peak_info, dict):
            global_peak["theta_deg"].append(float(peak_info.get("theta_deg", 0.0)))
            global_peak["phi_deg"].append(float(peak_info.get("phi_deg", 0.0)))
            global_peak["gain_db"].append(float(peak_info.get("gain_db", 0.0)))
            any_peak = True

        plane_cuts = item.get("plane_cuts")
        if not isinstance(plane_cuts, dict):
            continue

        for plane_id in cuts:
            cut_info = plane_cuts.get(plane_id)
            if isinstance(cut_info, dict):
                cuts[plane_id].append(_to_float_list(cut_info.get("gain_db", [])))
                any_cut = True
            elif cuts[plane_id]:
                cuts[plane_id].append([])

    payload: dict[str, Any] = {}
    if any_cut:
        payload["cuts"] = {plane_id: {"gain_db": values} for plane_id, values in cuts.items() if values}
    if any_peak:
        payload["global_peak"] = global_peak
    coverage = [{"frequency": item.get("frequency"), "peak_scope": item.get("peak_scope"),
                 "acquisition": item.get("acquisition"),
                 "sampled_peak_direction": item.get("sampled_peak_direction")}
                for item in per_frequency if isinstance(item, dict) and item.get("acquisition")]
    if coverage:
        payload["coverage"] = coverage
    summary = far_field.get("summary")
    if isinstance(summary, dict) and summary:
        payload["summary"] = summary
    return payload or None


def build_simulation_record(
    sim_id: int,
    iter_num: int,
    params: Any,
    freqs: Any,
    s11: Any,
    s12: Any,
    g_freqs: Any = None,
    gain: Any = None,
    extra_metrics: dict[str, Any] | None = None,
    param_names: Iterable[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "sim_id": int(sim_id),
        "iter": int(iter_num),
        "params": _normalize_params(params, param_names=param_names),
        "s_freqs": freqs.tolist() if freqs is not None else [],
        "s11": s11.tolist() if s11 is not None else [],
        "s12": s12.tolist() if s12 is not None else [],
        "g_freqs": g_freqs.tolist() if g_freqs is not None else [],
        "gain": gain.tolist() if gain is not None else [],
    }

    if extra_fields:
        record.update(extra_fields)

    far_field = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else None
    far_field_record = build_far_field_simulation_record(far_field) if isinstance(far_field, dict) else None
    if far_field_record is not None:
        record["far_field"] = far_field_record

    traces = extra_metrics.get("traces") if isinstance(extra_metrics, dict) else None
    if isinstance(traces, dict) and traces:
        record["traces"] = traces
    if isinstance(extra_metrics, dict) and extra_metrics.get("result_bundle") is not None:
        record["result_bundle"] = extra_metrics["result_bundle"]
    if isinstance(params, dict):
        record["parameter_expressions"] = {str(name): str(value) for name, value in params.items()}

    return record
