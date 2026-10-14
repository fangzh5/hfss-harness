"""Optional metric collection shared by optimization and sweep paths."""

from __future__ import annotations

from typing import Any
import math
try:
    from .results import TraceData
except ImportError:  # pragma: no cover
    from results import TraceData


def _target_requires_far_field_metrics(config: dict[str, Any]) -> bool:
    target = config.get("target", {})
    if target.get("gain_min") is not None:
        return True
    far_field_cfg = target.get("far_field") or target.get("boresight")
    if isinstance(far_field_cfg, dict) and bool(far_field_cfg.get("required", False)):
        return True

    multi_objective = target.get("multi_objective", {})
    if not isinstance(multi_objective, dict) or not bool(multi_objective.get("enabled", False)):
        return False

    for objective in multi_objective.get("objectives", []):
        if not isinstance(objective, dict):
            continue
        obj_type = str(objective.get("type", objective.get("name", ""))).strip().lower()
        if (
            obj_type.startswith("peak_gain")
            or obj_type.startswith("pointing_error")
            or obj_type.startswith("peak_loss")
            or obj_type.startswith("boresight_gain")
        ):
            return True
    return False


def _collect_extra_traces(config: dict[str, Any], adapter) -> dict[str, Any]:
    simulator_cfg = config.get("simulator", {})
    hfss_cfg = simulator_cfg.get("hfss", {}) if isinstance(simulator_cfg, dict) else {}
    results_cfg = hfss_cfg.get("results", {}) if isinstance(hfss_cfg, dict) else {}
    traces_cfg = results_cfg.get("extra_traces", []) if isinstance(results_cfg, dict) else []
    if not traces_cfg:
        return {}
    if not hasattr(adapter, "get_trace_data"):
        raise RuntimeError("Configured extra_traces require adapter.get_trace_data().")

    traces: dict[str, Any] = {}
    for item in traces_cfg:
        if isinstance(item, str):
            name = item
            expression = item
        elif isinstance(item, dict):
            expression = str(item.get("expression", "")).strip()
            name = str(item.get("name") or expression).strip()
        else:
            raise ValueError("extra_traces entries must be expressions or objects")
        if not expression or not name:
            raise ValueError("extra_traces require a nonempty name and expression")
        freqs, values = adapter.get_trace_data(expression)
        if freqs is None or values is None:
            raise RuntimeError(f"Failed to read extra trace '{name}' ({expression}).")
        TraceData(expression, freqs, values, value_unit="")
        traces[name] = {
            "expression": expression,
            "freqs": [float(value) for value in freqs],
            "values": [float(value) for value in values],
        }
    return {"traces": traces} if traces else {}


def collect_geometry_snapshot(config: dict[str, Any], adapter) -> dict[str, Any] | None:
    """A requested geometry observation is required evidence, never silently skipped."""
    cfg = config.get("output", {}).get("geometry_snapshot")
    if cfg is None:
        return None
    if not isinstance(cfg, dict):
        raise ValueError("output.geometry_snapshot must be an object")
    names = cfg.get("objects")
    if (not isinstance(names, list) or not names or
            any(not isinstance(name, str) or not name.strip() for name in names) or
            len(set(names)) != len(names)):
        raise ValueError("geometry_snapshot.objects requires unique nonempty names")
    tolerance = cfg.get("absolute_tolerance", 1e-8)
    if isinstance(tolerance, bool) or not math.isfinite(float(tolerance)) or float(tolerance) <= 0:
        raise ValueError("geometry_snapshot.absolute_tolerance must be positive and finite in model units")
    if not callable(getattr(adapter, "capture_geometry_snapshot", None)):
        raise RuntimeError("Requested geometry snapshot is unsupported by this adapter")
    return adapter.capture_geometry_snapshot(names)


def collect_optional_metrics(config: dict[str, Any], adapter) -> dict[str, Any]:
    """Collect optional configured metrics and traces."""
    collected: dict[str, Any] = {}
    geometry = collect_geometry_snapshot(config, adapter)
    if geometry is not None:
        collected["geometry_snapshot"] = geometry
    bundle = getattr(adapter, "last_result_bundle", None)
    if bundle is not None:
        collected["result_bundle"] = bundle.to_dict()
    extra_traces = _collect_extra_traces(config, adapter)
    if extra_traces:
        collected.update(extra_traces)

    target = config.get("target", {})
    far_field_cfg = target.get("far_field") or target.get("boresight")
    required = _target_requires_far_field_metrics(config)
    if not isinstance(far_field_cfg, dict):
        if required:
            raise RuntimeError("Required far-field metric config is missing.")
        return collected
    if not bool(far_field_cfg.get("enabled", False)):
        if required:
            raise RuntimeError("Required far-field metric config is disabled.")
        return collected
    if not hasattr(adapter, "get_far_field_peak_loss_band"):
        if required:
            raise RuntimeError("Required far-field metric API is not available on the simulator adapter.")
        return collected

    try:
        freq_list = far_field_cfg.get("freqs")
        if isinstance(freq_list, str):
            freq_list = [freq_list]

        kwargs = {
            "freqs": freq_list,
            "freq_start": far_field_cfg.get("freq_start"),
            "freq_end": far_field_cfg.get("freq_end"),
            "freq_step": far_field_cfg.get("freq_step"),
            "boresight_theta": float(far_field_cfg.get("theta_deg", far_field_cfg.get("theta", 0.0))),
            "boresight_phi": float(far_field_cfg.get("phi_deg", far_field_cfg.get("phi", 0.0))),
            "sphere_name": far_field_cfg.get("sphere", "3D"),
            "expression": far_field_cfg.get("expression", "RealizedGainTotal"),
            "setup_sweep_name": far_field_cfg.get("setup_sweep_name"),
            "phi_samples_deg": far_field_cfg.get("phi_samples_deg"),
            "plane_phi_deg": (
                None
                if far_field_cfg.get("plane_phi_deg") is None
                else float(far_field_cfg.get("plane_phi_deg"))
            ),
            "plane_tolerance_deg": float(far_field_cfg.get("plane_tolerance_deg", 1e-6)),
            "plane_include_opposite": bool(far_field_cfg.get("plane_include_opposite", True)),
        }

        if kwargs["freqs"] is None and (
            kwargs["freq_start"] is None or kwargs["freq_end"] is None or kwargs["freq_step"] is None
        ):
            kwargs["freq_start"] = float(target.get("freq_band", [0.0, 0.0])[0])
            kwargs["freq_end"] = float(target.get("freq_band", [0.0, 0.0])[1])
            kwargs["freq_step"] = 1.0

        far_field_metrics = adapter.get_far_field_peak_loss_band(**kwargs)
        if required and (not isinstance(far_field_metrics, dict) or not far_field_metrics.get("per_frequency")):
            raise RuntimeError("Required far-field acquisition returned no frequency records")
        collected["far_field"] = far_field_metrics
        return collected
    except Exception as exc:
        message = f"Optional far-field metric collection failed: {exc}"
        print(message)
        if required:
            raise RuntimeError(message) from exc
        return collected
