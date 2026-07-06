"""Optional metric collection shared by optimization and sweep paths."""

from __future__ import annotations

from typing import Any


def _target_requires_far_field_metrics(config: dict[str, Any]) -> bool:
    target = config.get("target", {})
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
        if obj_type.startswith("pointing_error") or obj_type.startswith("peak_loss"):
            return True
    return False


def collect_optional_metrics(config: dict[str, Any], adapter) -> dict[str, Any]:
    """Collect optional far-field metrics when the target requires them."""
    target = config.get("target", {})
    far_field_cfg = target.get("far_field") or target.get("boresight")
    required = _target_requires_far_field_metrics(config)
    if not isinstance(far_field_cfg, dict):
        if required:
            raise RuntimeError("Required far-field metric config is missing.")
        return {}
    if not bool(far_field_cfg.get("enabled", False)):
        if required:
            raise RuntimeError("Required far-field metric config is disabled.")
        return {}
    if not hasattr(adapter, "get_far_field_peak_loss_band"):
        if required:
            raise RuntimeError("Required far-field metric API is not available on the simulator adapter.")
        return {}

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
        return {"far_field": far_field_metrics}
    except Exception as exc:
        message = f"Optional far-field metric collection failed: {exc}"
        print(message)
        if required:
            raise RuntimeError(message) from exc
        return {}
