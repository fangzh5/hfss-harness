"""Fitness calculation for HFSS optimization."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class FitnessResult:
    """Fitness result container."""

    cost: float
    bandwidth: Optional[float] = None
    s11_max: Optional[float] = None
    s12_max: Optional[float] = None
    gain_min: Optional[float] = None
    target_met: bool = False
    stage_met: bool = False
    stage_index: int = 0
    stage_name: str = ""
    component_costs: Dict[str, float] = field(default_factory=dict)
    raw_metrics: Dict[str, float] = field(default_factory=dict)
    adaptive_scales: Dict[str, float] = field(default_factory=dict)
    extra_metrics: Dict[str, Any] = field(default_factory=dict)
    objectives: List[float] = field(default_factory=list)
    constraint_violation: float = 0.0
    rank: Optional[int] = None
    crowding_distance: Optional[float] = None
    source_sim_id: Optional[int] = None

    @property
    def s21_max(self) -> Optional[float]:
        return self.s12_max

    @s21_max.setter
    def s21_max(self, value: Optional[float]) -> None:
        self.s12_max = value


@dataclass
class FitnessStage:
    """One optimization stage."""

    name: str
    freq_band: Tuple[float, float]
    s11_target: float
    s12_target: Optional[float] = None
    bandwidth_target: Optional[float] = None
    gain_target: Optional[float] = None
    center_priority: bool = False
    s11_profile: Optional[Dict[str, Any]] = None

    @property
    def s21_target(self) -> Optional[float]:
        return self.s12_target

    @s21_target.setter
    def s21_target(self, value: Optional[float]) -> None:
        self.s12_target = value


@dataclass
class ExtractedMetrics:
    """Internal metrics extraction payload."""

    metrics: Dict[str, float]
    segment: Dict[str, Optional[float]]


class FitnessCalculator:
    """Compute scalar fitness values for HFSS optimization."""

    TRACKED_COMPONENTS = ("violation", "bandwidth", "coverage", "s12", "gain")

    def __init__(
        self,
        freq_band: Tuple[float, float],
        s11_target: float = -10,
        s12_target: Optional[float] = None,
        bandwidth_target: Optional[float] = None,
        gain_target: Optional[float] = None,
        stages: Optional[List[dict]] = None,
        objective_mode: str = "legacy",
        fitness_config: Optional[dict] = None,
        multi_objective_config: Optional[dict] = None,
        s11_profile: Optional[dict] = None,
    ):
        self.objective_mode = str(objective_mode or "legacy").lower()
        self.fitness_config = fitness_config or {}
        self.multi_objective_config = self._normalize_multi_objective_config(multi_objective_config)
        self.component_weights = self._build_component_weights(self.fitness_config.get("weights"))
        self.depth_bonus_cap = float(self.fitness_config.get("depth_bonus_cap", 6.0))
        self.depth_reference = float(self.fitness_config.get("depth_reference", 1.0))
        self.geometry_reference = max(float(self.fitness_config.get("geometry_reference", 2.0)), 1e-9)
        self.coverage_tolerance = float(self.fitness_config.get("coverage_tolerance", 0.0))
        self.adaptive_config = self._normalize_adaptive_config(self.fitness_config.get("adaptive_penalty"))
        self.adaptive_scales = {name: 1.0 for name in self.TRACKED_COMPONENTS}

        self.stages = self._build_stages(
            freq_band=freq_band,
            s11_target=s11_target,
            s12_target=s12_target,
            bandwidth_target=bandwidth_target,
            gain_target=gain_target,
            stages=stages,
            s11_profile=s11_profile,
        )
        self.stage_index = 0
        self._refresh_active_stage()

    @property
    def is_multi_objective(self) -> bool:
        return bool(self.multi_objective_config.get("enabled", False))

    def _build_stages(
        self,
        freq_band: Tuple[float, float],
        s11_target: float,
        s12_target: Optional[float],
        bandwidth_target: Optional[float],
        gain_target: Optional[float],
        stages: Optional[List[dict]],
        s11_profile: Optional[dict],
    ) -> List[FitnessStage]:
        if not stages:
            return [
                FitnessStage(
                    name="final",
                    freq_band=tuple(freq_band),
                    s11_target=s11_target,
                    s12_target=s12_target,
                    bandwidth_target=bandwidth_target,
                    gain_target=gain_target,
                    center_priority=False,
                    s11_profile=self._normalize_s11_profile(s11_profile, s11_target),
                )
            ]

        normalized_stages: List[FitnessStage] = []
        for idx, stage_cfg in enumerate(stages):
            normalized_stages.append(
                FitnessStage(
                    name=str(stage_cfg.get("name", f"stage_{idx + 1}")),
                    freq_band=tuple(stage_cfg.get("freq_band", freq_band)),
                    s11_target=float(stage_cfg.get("s11_threshold", s11_target)),
                    s12_target=stage_cfg.get(
                        "s12_threshold",
                        stage_cfg.get("s21_threshold", stage_cfg.get("s21_target", s12_target)),
                    ),
                    bandwidth_target=stage_cfg.get("bandwidth_target", bandwidth_target),
                    gain_target=stage_cfg.get("gain_min", stage_cfg.get("gain_target", gain_target)),
                    center_priority=bool(stage_cfg.get("center_priority", False)),
                    s11_profile=self._normalize_s11_profile(stage_cfg.get("s11_profile", s11_profile), s11_target),
                )
            )

        return normalized_stages

    def _refresh_active_stage(self) -> None:
        self.active_stage = self.stages[self.stage_index]

    @property
    def is_final_stage(self) -> bool:
        return self.stage_index >= len(self.stages) - 1

    def advance_stage(self) -> bool:
        """Move to the next stage after the current one is satisfied."""
        if self.is_final_stage:
            return False

        self.stage_index += 1
        self._refresh_active_stage()
        return True

    def _default_component_weights(self) -> Dict[str, float]:
        if self.objective_mode == "feasible_first":
            return {
                "violation": 1.0,
                "bandwidth": 6.0,
                "coverage": 5.0,
                "depth": 0.8,
                "geometry": 1.0,
                "s12": 1.0,
                "gain": 1.0,
            }
        if self.objective_mode == "bandwidth_first":
            return {
                "violation": 1.0,
                "bandwidth": 10.0,
                "coverage": 6.0,
                "depth": 0.8,
                "geometry": 1.0,
                "s12": 1.0,
                "gain": 1.0,
            }
        if self.objective_mode == "coverage_first":
            return {
                "violation": 1.0,
                "bandwidth": 8.0,
                "coverage": 10.0,
                "depth": 1.0,
                "geometry": 1.0,
                "s12": 1.0,
                "gain": 1.0,
            }
        if self.objective_mode == "minimax":
            return {
                "violation": 1.0,
                "bandwidth": 1.0,
                "coverage": 1.0,
                "depth": 0.5,
                "geometry": 1.0,
                "s12": 1.0,
                "gain": 1.0,
            }
        return {
            "violation": 1.0,
            "bandwidth": 7.0,
            "coverage": 7.0,
            "depth": 0.8,
            "geometry": 1.0,
            "s12": 1.0,
            "gain": 1.0,
        }

    def _build_component_weights(self, overrides: Optional[dict]) -> Dict[str, float]:
        weights = self._default_component_weights()
        if not isinstance(overrides, dict):
            return weights

        for key, value in overrides.items():
            try:
                weights[str(key)] = float(value)
            except Exception:
                continue
        return weights

    def _normalize_adaptive_config(self, raw_cfg: Any) -> Dict[str, Any]:
        default = {
            "enabled": False,
            "increase": 1.12,
            "decrease": 0.985,
            "min_scale": 1.0,
            "max_scale": 12.0,
            "components": list(self.TRACKED_COMPONENTS),
        }

        if raw_cfg is None:
            return default
        if isinstance(raw_cfg, bool):
            default["enabled"] = raw_cfg
            return default
        if not isinstance(raw_cfg, dict):
            return default

        cfg = default.copy()
        cfg["enabled"] = bool(raw_cfg.get("enabled", cfg["enabled"]))
        for key in ("increase", "decrease", "min_scale", "max_scale"):
            try:
                cfg[key] = float(raw_cfg.get(key, cfg[key]))
            except Exception:
                pass

        components = raw_cfg.get("components")
        if isinstance(components, (list, tuple)):
            normalized = [str(item) for item in components if str(item) in self.TRACKED_COMPONENTS]
            if normalized:
                cfg["components"] = normalized
        return cfg

    def _normalize_multi_objective_config(self, raw_cfg: Any) -> Dict[str, Any]:
        default = {
            "enabled": False,
            "constraint_strategy": "s11_feasible_first",
            "objectives": [],
            "tail_ratio": 0.25,
            "peak_loss_threshold": None,
            "pointing_error_threshold": None,
            "s11_profile": None,
        }
        if raw_cfg is None:
            return default
        if isinstance(raw_cfg, bool):
            default["enabled"] = raw_cfg
            if raw_cfg and not default["objectives"]:
                default["objectives"] = [
                    {"name": "peak_loss_worst", "type": "peak_loss_worst"},
                    {"name": "peak_loss_cvar", "type": "peak_loss_cvar"},
                ]
            return default
        if not isinstance(raw_cfg, dict):
            return default

        cfg = default.copy()
        cfg["enabled"] = bool(raw_cfg.get("enabled", False))
        cfg["constraint_strategy"] = str(raw_cfg.get("constraint_strategy", cfg["constraint_strategy"]))
        try:
            cfg["tail_ratio"] = float(raw_cfg.get("tail_ratio", cfg["tail_ratio"]))
        except Exception:
            pass
        try:
            peak_loss_threshold = raw_cfg.get("peak_loss_threshold", cfg["peak_loss_threshold"])
            cfg["peak_loss_threshold"] = None if peak_loss_threshold is None else float(peak_loss_threshold)
        except Exception:
            pass
        try:
            pointing_error_threshold = raw_cfg.get("pointing_error_threshold", cfg["pointing_error_threshold"])
            cfg["pointing_error_threshold"] = (
                None if pointing_error_threshold is None else float(pointing_error_threshold)
            )
        except Exception:
            pass
        cfg["s11_profile"] = self._normalize_s11_profile(raw_cfg.get("s11_profile"), None)

        objectives = []
        for item in raw_cfg.get("objectives", []):
            if not isinstance(item, dict):
                continue
            obj_type = str(item.get("type", item.get("name", ""))).strip().lower()
            if not obj_type:
                continue
            objectives.append(
                {
                    "name": str(item.get("name", obj_type)),
                    "type": obj_type,
                    "tail_ratio": float(item.get("tail_ratio", cfg["tail_ratio"])),
                }
            )
        if cfg["enabled"] and not objectives:
            if cfg["pointing_error_threshold"] is not None:
                objectives = [
                    {"name": "pointing_error_worst", "type": "pointing_error_worst", "tail_ratio": cfg["tail_ratio"]},
                    {"name": "pointing_error_cvar", "type": "pointing_error_cvar", "tail_ratio": cfg["tail_ratio"]},
                ]
            else:
                objectives = [
                    {"name": "peak_loss_worst", "type": "peak_loss_worst", "tail_ratio": cfg["tail_ratio"]},
                    {"name": "peak_loss_cvar", "type": "peak_loss_cvar", "tail_ratio": cfg["tail_ratio"]},
                ]
        cfg["objectives"] = objectives
        return cfg

    def _normalize_s11_profile(self, raw_cfg: Any, default_threshold: Optional[float]) -> Optional[Dict[str, Any]]:
        if raw_cfg is None:
            return None
        if not isinstance(raw_cfg, dict):
            return None

        profile: Dict[str, Any] = {
            "interior_threshold": None if default_threshold is None else float(default_threshold),
            "freq_tolerance": 1e-6,
            "edge_points": [],
        }
        try:
            interior = raw_cfg.get("interior_threshold", raw_cfg.get("default_threshold", profile["interior_threshold"]))
            profile["interior_threshold"] = None if interior is None else float(interior)
        except Exception:
            pass
        try:
            profile["freq_tolerance"] = float(raw_cfg.get("freq_tolerance", profile["freq_tolerance"]))
        except Exception:
            pass

        edge_points = []
        for item in raw_cfg.get("edge_points", []):
            if not isinstance(item, dict):
                continue
            try:
                edge_points.append(
                    {
                        "freq": float(item["freq"]),
                        "threshold": float(item["threshold"]),
                    }
                )
            except Exception:
                continue
        profile["edge_points"] = edge_points
        return profile

    def _s11_threshold_array(self, stage: FitnessStage, freqs_ghz: np.ndarray) -> np.ndarray:
        thresholds = np.full(freqs_ghz.shape, float(stage.s11_target), dtype=float)
        profile = stage.s11_profile or self.multi_objective_config.get("s11_profile")
        if not isinstance(profile, dict):
            return thresholds

        interior = profile.get("interior_threshold")
        if interior is not None:
            thresholds[:] = float(interior)

        tol = float(profile.get("freq_tolerance", 1e-6))
        for item in profile.get("edge_points", []):
            try:
                freq = float(item["freq"])
                threshold = float(item["threshold"])
            except Exception:
                continue
            edge_mask = np.abs(freqs_ghz - freq) <= tol
            if np.any(edge_mask):
                thresholds[edge_mask] = threshold
        return thresholds

    def calculate(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        gain: Optional[np.ndarray] = None,
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> FitnessResult:
        """Calculate fitness from available traces."""
        if self.is_multi_objective:
            return self.calculate_multiobjective(freqs, s11, gain, extra_metrics=extra_metrics)
        stage = self.active_stage
        extra_metrics = extra_metrics or {}
        if stage.s12_target is not None:
            if gain is None:
                return FitnessResult(
                    cost=9999.0,
                    target_met=False,
                    stage_met=False,
                    stage_index=self.stage_index,
                    stage_name=stage.name,
                    extra_metrics=extra_metrics,
                )
            return self.calculate_with_s21(freqs, s11, gain, extra_metrics=extra_metrics)
        return self.calculate_s11(freqs, s11, extra_metrics=extra_metrics)

    def calculate_s11(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> FitnessResult:
        """Calculate fitness using S11 only."""
        stage = self.active_stage
        extra_metrics = dict(extra_metrics or {})
        f_ghz = self._normalize_frequency(freqs)
        mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])

        if not np.any(mask):
            return FitnessResult(
                cost=9999.0,
                target_met=False,
                stage_met=False,
                stage_index=self.stage_index,
                stage_name=stage.name,
                extra_metrics=extra_metrics,
            )

        band_freqs = f_ghz[mask]
        band_s11 = np.asarray(s11, dtype=float)[mask]
        s11_max = float(np.max(band_s11))
        extracted = self._extract_metrics_with_segment(
            freqs=f_ghz,
            s11=np.asarray(s11, dtype=float),
            s12=None,
            extra_metrics=extra_metrics,
        )
        segment = extracted.segment
        bandwidth = extracted.metrics["matched_bandwidth"]
        extra_metrics["fitness_metrics"] = dict(extracted.metrics)

        cost, component_costs, raw_metrics = self._compute_cost(
            stage=stage,
            freqs=f_ghz,
            s11=np.asarray(s11, dtype=float),
            bandwidth=bandwidth,
            segment=segment,
            s21=None,
            gain_min=None,
            extra_metrics=extra_metrics,
        )
        stage_met = self.is_target_met(stage, band_freqs, band_s11, bandwidth, None)

        adaptive_scales = self._finalize_adaptive_scales(raw_metrics)

        return FitnessResult(
            cost=cost,
            bandwidth=bandwidth,
            s11_max=s11_max,
            s12_max=None,
            gain_min=None,
            target_met=stage_met and self.is_final_stage,
            stage_met=stage_met,
            stage_index=self.stage_index,
            stage_name=stage.name,
            component_costs=component_costs,
            raw_metrics=raw_metrics,
            adaptive_scales=adaptive_scales,
            extra_metrics=extra_metrics,
        )

    def _compute_constraint_violation(
        self,
        stage: FitnessStage,
        freqs: np.ndarray,
        s11: np.ndarray,
        s12: Optional[np.ndarray],
        bandwidth: Optional[float],
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> tuple[float, Dict[str, float]]:
        """Build the constraint scalar used by Pareto ranking."""
        extra_metrics = extra_metrics or {}
        f_ghz = self._normalize_frequency(freqs)
        band_mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])
        if not np.any(band_mask):
            return 9999.0, {
                "s11_violation": 9999.0,
                "bandwidth_gap": 0.0,
                "s12_violation": 0.0,
                "peak_loss_violation": 0.0,
                "pointing_error_violation": 0.0,
            }

        band_s11 = np.asarray(s11, dtype=float)[band_mask]
        band_thresholds = self._s11_threshold_array(stage, f_ghz[band_mask])
        excess = np.clip(band_s11 - band_thresholds, 0.0, None)
        s11_violation = float(np.mean(np.square(excess)) * 20.0 + np.mean(excess) * 2.0) if excess.size else 0.0

        bw_target = self._get_bandwidth_target_for_cost(stage)
        bandwidth_gap = max(float(bw_target) - float(bandwidth or 0.0), 0.0) if bw_target is not None else 0.0
        bandwidth_violation = float(np.square(bandwidth_gap))
        s12_violation = 0.0
        if stage.s12_target is not None:
            if s12 is None:
                s12_violation = 1000.0
            else:
                band_s12 = np.asarray(s12, dtype=float)[band_mask]
                s12_excess = np.clip(band_s12 - float(stage.s12_target), 0.0, None)
                s12_violation = (
                    float(np.mean(np.square(s12_excess)) * 25.0 + np.mean(s12_excess) * 3.0)
                    if s12_excess.size
                    else 0.0
                )
        peak_loss_violation = 0.0
        pointing_error_violation = 0.0
        peak_loss_threshold = self.multi_objective_config.get("peak_loss_threshold")
        if peak_loss_threshold is not None:
            peak_losses = self._peak_loss_series(extra_metrics)
            if peak_losses:
                excess = np.clip(np.asarray(peak_losses, dtype=float) - float(peak_loss_threshold), 0.0, None)
                peak_loss_violation = float(np.max(excess)) if excess.size else 0.0
        pointing_error_threshold = self.multi_objective_config.get("pointing_error_threshold")
        if pointing_error_threshold is not None:
            pointing_errors = self._pointing_error_series(extra_metrics)
            if pointing_errors:
                excess = np.clip(
                    np.asarray(pointing_errors, dtype=float) - float(pointing_error_threshold),
                    0.0,
                    None,
                )
                pointing_error_violation = float(np.max(excess)) if excess.size else 0.0

        return s11_violation + bandwidth_violation + s12_violation + peak_loss_violation + pointing_error_violation, {
            "s11_violation": s11_violation,
            "bandwidth_gap": bandwidth_gap,
            "s12_violation": s12_violation,
            "peak_loss_violation": peak_loss_violation,
            "pointing_error_violation": pointing_error_violation,
        }

    @staticmethod
    def _peak_loss_series(extra_metrics: Dict[str, Any]) -> list[float]:
        far_field = extra_metrics.get("far_field", {})
        per_frequency = far_field.get("per_frequency", []) if isinstance(far_field, dict) else []
        series = []
        for item in per_frequency:
            try:
                series.append(float(item.get("peak_loss_db")))
            except Exception:
                continue
        return series

    @staticmethod
    def _pointing_error_series(extra_metrics: Dict[str, Any]) -> list[float]:
        far_field = extra_metrics.get("far_field", {})
        per_frequency = far_field.get("per_frequency", []) if isinstance(far_field, dict) else []
        series = []
        for item in per_frequency:
            try:
                series.append(float(item.get("pointing_error_deg")))
            except Exception:
                continue
        return series

    @staticmethod
    def _tail_mean(values: list[float], tail_ratio: float) -> float:
        if not values:
            return 9999.0
        tail_count = max(1, int(np.ceil(len(values) * max(float(tail_ratio), 0.01))))
        return float(np.mean(values[-tail_count:]))

    def _build_multi_objectives(
        self,
        band_s11: np.ndarray,
        band_s12: Optional[np.ndarray],
        extra_metrics: Dict[str, Any],
    ) -> tuple[List[float], Dict[str, float]]:
        s11_values = sorted(np.asarray(band_s11, dtype=float).tolist()) if band_s11 is not None else []
        s12_values = sorted(np.asarray(band_s12, dtype=float).tolist()) if band_s12 is not None else []
        peak_losses = sorted(self._peak_loss_series(extra_metrics))
        pointing_errors = sorted(self._pointing_error_series(extra_metrics))
        metrics: Dict[str, float] = {}
        objectives: List[float] = []

        for objective_cfg in self.multi_objective_config.get("objectives", []):
            obj_type = objective_cfg["type"]
            tail_ratio = float(objective_cfg.get("tail_ratio", self.multi_objective_config.get("tail_ratio", 0.25)))
            if obj_type == "s11_worst":
                value = float(max(s11_values)) if s11_values else 9999.0
            elif obj_type == "s11_avg":
                value = float(np.mean(s11_values)) if s11_values else 9999.0
            elif obj_type == "s11_cvar":
                value = self._tail_mean(s11_values, tail_ratio)
            elif obj_type in {"s12_worst", "s21_worst"}:
                value = float(max(s12_values)) if s12_values else 9999.0
            elif obj_type in {"s12_avg", "s21_avg"}:
                value = float(np.mean(s12_values)) if s12_values else 9999.0
            elif obj_type in {"s12_cvar", "s21_cvar"}:
                value = self._tail_mean(s12_values, tail_ratio)
            elif obj_type == "peak_loss_worst":
                value = float(max(peak_losses)) if peak_losses else 9999.0
            elif obj_type == "peak_loss_avg":
                value = float(np.mean(peak_losses)) if peak_losses else 9999.0
            elif obj_type == "peak_loss_cvar":
                value = self._tail_mean(peak_losses, tail_ratio)
            elif obj_type == "pointing_error_worst":
                value = float(max(pointing_errors)) if pointing_errors else 9999.0
            elif obj_type == "pointing_error_avg":
                value = float(np.mean(pointing_errors)) if pointing_errors else 9999.0
            elif obj_type == "pointing_error_cvar":
                value = self._tail_mean(pointing_errors, tail_ratio)
            elif obj_type == "s11_violation":
                value = float(extra_metrics.get("constraint_details", {}).get("s11_violation", 9999.0))
            elif obj_type in {"s12_violation", "s21_violation"}:
                value = float(extra_metrics.get("constraint_details", {}).get("s12_violation", 9999.0))
            else:
                value = 9999.0

            objectives.append(value)
            metrics[objective_cfg["name"]] = value
        return objectives, metrics

    def calculate_multiobjective(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        gain: Optional[np.ndarray] = None,
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> FitnessResult:
        """Calculate Pareto-oriented objectives while preserving scalar logging fields."""
        stage = self.active_stage
        extra_metrics = dict(extra_metrics or {})
        f_ghz = self._normalize_frequency(freqs)
        mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])

        if not np.any(mask):
            return FitnessResult(
                cost=9999.0,
                target_met=False,
                stage_met=False,
                stage_index=self.stage_index,
                stage_name=stage.name,
                extra_metrics=extra_metrics,
                objectives=[9999.0 for _ in self.multi_objective_config.get("objectives", [])],
                constraint_violation=9999.0,
            )

        band_freqs = f_ghz[mask]
        band_s11 = np.asarray(s11, dtype=float)[mask]
        band_s12 = np.asarray(gain, dtype=float)[mask] if gain is not None else None
        s11_max = float(np.max(band_s11))
        s12_max = float(np.max(band_s12)) if band_s12 is not None and band_s12.size else None
        extracted = self._extract_metrics_with_segment(
            freqs=f_ghz,
            s11=np.asarray(s11, dtype=float),
            s12=np.asarray(gain, dtype=float) if gain is not None else None,
            extra_metrics=extra_metrics,
        )
        metrics = dict(extracted.metrics)
        bandwidth = metrics["matched_bandwidth"]
        extra_metrics["fitness_metrics"] = dict(metrics)

        objectives = self.objectives_for_nsga2(metrics)
        constraint_details = self.constraints_for_nsga2(metrics)
        constraint_violation = float(sum(constraint_details.values()))
        extra_metrics["constraint_details"] = constraint_details
        extra_metrics["objective_metrics"] = {
            "inband_violation_max": float(metrics["inband_violation_max"]),
            "edge_violation_max": float(metrics["edge_violation_max"]),
            "negative_depth_mean": -float(metrics["depth_mean"]),
        }

        display_cost = float(constraint_violation + sum(objectives))
        stage_met = self.is_target_met(stage, band_freqs, band_s11, bandwidth, s12_max)

        return FitnessResult(
            cost=display_cost,
            bandwidth=bandwidth,
            s11_max=s11_max,
            s12_max=s12_max,
            target_met=False,
            stage_met=stage_met,
            stage_index=self.stage_index,
            stage_name=stage.name,
            component_costs={},
            raw_metrics=dict(constraint_details),
            adaptive_scales=self.adaptive_scales.copy(),
            extra_metrics=extra_metrics,
            objectives=objectives,
            constraint_violation=float(constraint_violation),
        )

    def calculate_with_s21(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        s21: np.ndarray,
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> FitnessResult:
        """Calculate fitness using S11 and S12 isolation."""
        stage = self.active_stage
        extra_metrics = dict(extra_metrics or {})
        f_ghz = self._normalize_frequency(freqs)
        mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])

        if not np.any(mask):
            return FitnessResult(
                cost=9999.0,
                target_met=False,
                stage_met=False,
                stage_index=self.stage_index,
                stage_name=stage.name,
                extra_metrics=extra_metrics,
            )

        band_freqs = f_ghz[mask]
        band_s11 = np.asarray(s11, dtype=float)[mask]
        band_s21 = np.asarray(s21, dtype=float)[mask]

        s11_max = float(np.max(band_s11))
        s21_max = float(np.max(band_s21))

        extracted = self._extract_metrics_with_segment(
            freqs=f_ghz,
            s11=np.asarray(s11, dtype=float),
            s12=np.asarray(s21, dtype=float),
            extra_metrics=extra_metrics,
        )
        segment = extracted.segment
        bandwidth = extracted.metrics["matched_bandwidth"]
        extra_metrics["fitness_metrics"] = dict(extracted.metrics)

        cost, component_costs, raw_metrics = self._compute_cost(
            stage=stage,
            freqs=f_ghz,
            s11=np.asarray(s11, dtype=float),
            bandwidth=bandwidth,
            segment=segment,
            s21=np.asarray(s21, dtype=float),
            gain_min=s21_max,
            extra_metrics=extra_metrics,
        )
        stage_met = self.is_target_met(stage, band_freqs, band_s11, bandwidth, s21_max)

        adaptive_scales = self._finalize_adaptive_scales(raw_metrics)

        return FitnessResult(
            cost=cost,
            bandwidth=bandwidth,
            s11_max=s11_max,
            s12_max=s21_max,
            gain_min=s21_max,
            target_met=stage_met and self.is_final_stage,
            stage_met=stage_met,
            stage_index=self.stage_index,
            stage_name=stage.name,
            component_costs=component_costs,
            raw_metrics=raw_metrics,
            adaptive_scales=adaptive_scales,
            extra_metrics=extra_metrics,
        )

    def _normalize_frequency(self, freqs: np.ndarray) -> np.ndarray:
        """Normalize frequency values to GHz."""
        mean_freq = np.mean(freqs)
        if mean_freq > 1000:
            return freqs / 1e9
        return freqs

    def extract_metrics(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        s12: Optional[np.ndarray],
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Extract reusable raw fitness metrics for the active stage."""
        return dict(self._extract_metrics_with_segment(freqs, s11, s12, extra_metrics).metrics)

    def fitness_for_bo(self, metrics: Dict[str, float]) -> float:
        """BO-oriented scalar fitness from shared extracted metrics."""
        return float(
            4.0 * metrics["inband_violation_mean"]
            + 2.5 * metrics["inband_violation_max"]
            + 2.0 * metrics["edge_violation_mean"]
            + 1.5 * metrics["edge_violation_max"]
            + 0.5 * np.sqrt(metrics["fullband_violation_sqmean"])
        )

    def fitness_for_de(self, metrics: Dict[str, float]) -> float:
        """DE-oriented scalar fitness from shared extracted metrics."""
        coverage_gap = metrics["coverage_left_gap"] + metrics["coverage_right_gap"]
        return float(
            6.0 * metrics["inband_violation_mean"]
            + 4.0 * metrics["inband_violation_max"]
            + 3.0 * metrics["edge_violation_mean"]
            + 2.0 * metrics["edge_violation_max"]
            + 1.0 * np.sqrt(metrics["fullband_violation_sqmean"])
            + 0.8 * coverage_gap
            + 0.5 * metrics["s12_violation_mean"]
            + 0.5 * metrics["gain_shortfall"]
            - 0.2 * min(metrics["depth_mean"], 6.0)
        )

    def objectives_for_nsga2(self, metrics: Dict[str, float]) -> List[float]:
        """Package shared metrics into the default NSGA-II objective vector."""
        return [
            float(metrics["inband_violation_max"]),
            float(metrics["edge_violation_max"]),
            -float(metrics["depth_mean"]),
        ]

    def constraints_for_nsga2(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """Package shared metrics into NSGA-II constraint details."""
        return {
            "coverage_gap": float(metrics["coverage_left_gap"] + metrics["coverage_right_gap"]),
            "s12_violation": float(metrics["s12_violation_mean"]),
            "gain_shortfall": float(metrics["gain_shortfall"]),
        }

    def _extract_metrics_with_segment(
        self,
        freqs: np.ndarray,
        s11: np.ndarray,
        s12: Optional[np.ndarray],
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> ExtractedMetrics:
        """Extract reusable raw fitness metrics plus the internal matched segment."""
        stage = self.active_stage
        extra_metrics = extra_metrics or {}
        f_ghz = self._normalize_frequency(np.asarray(freqs, dtype=float))
        s11_values = np.asarray(s11, dtype=float)
        s12_values = np.asarray(s12, dtype=float) if s12 is not None else None
        band_mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])
        if not np.any(band_mask):
            empty_segment = {
                "start": None,
                "end": None,
                "start_freq": None,
                "end_freq": None,
                "bandwidth": 0.0,
                "center": float(np.mean(f_ghz)) if f_ghz.size else 0.0,
            }
            return ExtractedMetrics(
                metrics={
                    "edge_violation_mean": 0.0,
                    "edge_violation_max": 0.0,
                    "inband_violation_mean": 0.0,
                    "inband_violation_max": 0.0,
                    "fullband_violation_sqmean": 0.0,
                    "coverage_left_gap": 0.0,
                    "coverage_right_gap": 0.0,
                    "matched_bandwidth": 0.0,
                    "depth_mean": 0.0,
                    "s12_violation_mean": 0.0,
                    "gain_shortfall": 0.0,
                    "geometry_metric": float(extra_metrics.get("geometry_metric", 0.0) or 0.0),
                },
                segment=empty_segment,
            )

        band_freqs = f_ghz[band_mask]
        band_s11 = s11_values[band_mask]
        band_s12 = s12_values[band_mask] if s12_values is not None else None
        thresholds = self._s11_threshold_array(stage, band_freqs)

        s11_excess = np.clip(band_s11 - thresholds, 0.0, None)
        quality = s11_excess.copy()
        if band_s12 is not None and stage.s12_target is not None:
            s12_excess = np.clip(band_s12 - float(stage.s12_target), 0.0, None)
            if not (self.objective_mode == "feasible_first" and stage.s12_target is not None):
                quality = np.maximum(quality, s12_excess)
        else:
            s12_excess = np.array([], dtype=float)

        segment = self._best_contiguous_segment(band_freqs, quality, 0.0)
        band_start = float(stage.freq_band[0])
        band_end = float(stage.freq_band[1])
        start_freq = segment.get("start_freq")
        end_freq = segment.get("end_freq")
        if start_freq is None or end_freq is None:
            left_gap = max(band_end - band_start, 0.0)
            right_gap = max(band_end - band_start, 0.0)
        else:
            left_gap = max(float(start_freq) - band_start - self.coverage_tolerance, 0.0)
            right_gap = max(band_end - float(end_freq) - self.coverage_tolerance, 0.0)

        edge_mask = np.zeros(band_freqs.shape, dtype=bool)
        profile = stage.s11_profile or self.multi_objective_config.get("s11_profile")
        if isinstance(profile, dict):
            tol = float(profile.get("freq_tolerance", 1e-6))
            for item in profile.get("edge_points", []):
                try:
                    edge_mask |= np.abs(band_freqs - float(item["freq"])) <= tol
                except Exception:
                    continue
        edge_excess = s11_excess[edge_mask]
        inband_excess = s11_excess[~edge_mask] if np.any(~edge_mask) else np.array([], dtype=float)
        depth_margin = np.clip(thresholds - band_s11, 0.0, None)

        gain_shortfall = 0.0
        if stage.gain_target is not None:
            if band_s12 is None or not band_s12.size:
                gain_shortfall = 1000.0
            else:
                gain_shortfall = max(float(stage.gain_target) - float(np.max(band_s12)), 0.0)

        return ExtractedMetrics(
            metrics={
                "edge_violation_mean": float(np.mean(edge_excess)) if edge_excess.size else 0.0,
                "edge_violation_max": float(np.max(edge_excess)) if edge_excess.size else 0.0,
                "inband_violation_mean": float(np.mean(inband_excess)) if inband_excess.size else 0.0,
                "inband_violation_max": float(np.max(inband_excess)) if inband_excess.size else 0.0,
                "fullband_violation_sqmean": float(np.mean(np.square(s11_excess))) if s11_excess.size else 0.0,
                "coverage_left_gap": float(left_gap),
                "coverage_right_gap": float(right_gap),
                "matched_bandwidth": float(segment["bandwidth"]),
                "depth_mean": float(np.mean(depth_margin)) if depth_margin.size else 0.0,
                "s12_violation_mean": float(np.mean(s12_excess)) if s12_excess.size else 0.0,
                "gain_shortfall": float(gain_shortfall),
                "geometry_metric": float(extra_metrics.get("geometry_metric", 0.0) or 0.0),
            },
            segment=segment,
        )

    def _best_contiguous_segment(
        self,
        f_ghz: np.ndarray,
        values: np.ndarray,
        threshold: float,
    ) -> dict:
        """Return the longest contiguous in-band segment below the threshold."""
        good_mask = values <= threshold
        if not np.any(good_mask):
            return {
                "start": None,
                "end": None,
                "start_freq": None,
                "end_freq": None,
                "bandwidth": 0.0,
                "center": float(np.mean(f_ghz)) if len(f_ghz) else 0.0,
            }

        good_indices = np.where(good_mask)[0]
        split_points = np.where(np.diff(good_indices) > 1)[0]
        segments = np.split(good_indices, split_points + 1)

        best_bandwidth = 0.0
        best_segment = None
        for segment in segments:
            if segment.size < 2:
                segment_bandwidth = 0.0
            else:
                segment_bandwidth = float(f_ghz[segment[-1]] - f_ghz[segment[0]])
            if segment_bandwidth > best_bandwidth:
                best_bandwidth = segment_bandwidth
                best_segment = segment

        if best_segment is None:
            idx = int(good_indices[0])
            return {
                "start": idx,
                "end": idx,
                "start_freq": float(f_ghz[idx]),
                "end_freq": float(f_ghz[idx]),
                "bandwidth": 0.0,
                "center": float(f_ghz[idx]),
            }

        start_idx = int(best_segment[0])
        end_idx = int(best_segment[-1])
        return {
            "start": start_idx,
            "end": end_idx,
            "start_freq": float(f_ghz[start_idx]),
            "end_freq": float(f_ghz[end_idx]),
            "bandwidth": float(best_bandwidth),
            "center": float((f_ghz[start_idx] + f_ghz[end_idx]) / 2.0),
        }

    def _get_bandwidth_target_for_cost(self, stage: FitnessStage) -> Optional[float]:
        if stage.bandwidth_target is not None:
            return float(stage.bandwidth_target)

        if self.objective_mode in {"bandwidth_first", "coverage_first"}:
            return max(float(stage.freq_band[1] - stage.freq_band[0]), 0.0)
        return None

    def _legacy_cost(
        self,
        stage: FitnessStage,
        freqs: np.ndarray,
        s11: np.ndarray,
        bandwidth: Optional[float],
        s21: Optional[np.ndarray],
        gain_min: Optional[float],
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, Dict[str, float], Dict[str, float]]:
        """Preserve the previous cost behavior for legacy configs."""
        extra_metrics = extra_metrics or {}
        f_ghz = self._normalize_frequency(freqs)
        band_mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])
        if not np.any(band_mask):
            components = {
                "violation_cost": 9999.0,
                "bandwidth_cost": 0.0,
                "coverage_cost": 0.0,
                "depth_bonus": 0.0,
                "geometry_penalty": 0.0,
                "s12_cost": 0.0,
                "gain_cost": 0.0,
                "constraint_penalty": 9999.0,
            }
            raw_metrics = {
                "violation_raw": 9999.0,
                "bandwidth_gap_raw": 0.0,
                "coverage_gap_raw": 0.0,
                "depth_raw": 0.0,
                "s12_violation_raw": 0.0,
                "gain_violation_raw": 0.0,
                "geometry_raw": 0.0,
                "constraint_raw": 9999.0,
            }
            return 9999.0, components, raw_metrics

        band_s11 = s11[band_mask]
        band_s21 = s21[band_mask] if s21 is not None else None
        thresholds = self._s11_threshold_array(stage, f_ghz[band_mask])
        excess = np.clip(band_s11 - thresholds, 0.0, None)
        violation_cost = float(np.sum(np.square(excess)) * 20.0 + np.sum(excess) * 2.0)
        s11_is_feasible = bool(np.all(excess <= 0.0))

        if self.objective_mode == "feasible_first" and stage.s12_target is not None:
            if not s11_is_feasible:
                cost = 1000.0 + violation_cost
                s12_cost = 0.0
            else:
                if band_s21 is None:
                    s12_cost = 1000.0
                else:
                    s21_threshold = float(stage.s12_target)
                    s21_excess = np.clip(band_s21 - s21_threshold, 0.0, None)
                    s12_cost = float(np.sum(np.square(s21_excess)) * 25.0 + np.sum(s21_excess) * 3.0)
                cost = s12_cost
        else:
            s11_gate_reward = 3.0 if s11_is_feasible else 0.0
            s12_cost = 0.0
            if stage.s12_target is not None:
                if band_s21 is None:
                    s12_cost = 1000.0
                else:
                    s21_threshold = float(stage.s12_target)
                    s21_excess = np.clip(band_s21 - s21_threshold, 0.0, None)
                    s12_cost = float(np.sum(np.square(s21_excess)) * 25.0 + np.sum(s21_excess) * 3.0)

            cost = violation_cost + 8.0 * s12_cost - s11_gate_reward

        bandwidth_cost = 0.0
        if stage.bandwidth_target is not None:
            bw = float(bandwidth or 0.0)
            bw_target = float(stage.bandwidth_target)
            if bw < bw_target:
                bandwidth_cost = (bw_target - bw) * 30.0
                cost += bandwidth_cost
            else:
                reward = min(bw - bw_target, 6.0) * 0.2
                cost -= reward

        gain_cost = 0.0
        if stage.gain_target is not None:
            if gain_min is None:
                gain_cost = 1000.0
            elif gain_min < stage.gain_target:
                gain_cost = (stage.gain_target - gain_min) * 100.0
            cost += gain_cost

        constraint_penalty = violation_cost + bandwidth_cost + s12_cost + gain_cost
        components = {
            "violation_cost": float(violation_cost),
            "bandwidth_cost": float(bandwidth_cost),
            "coverage_cost": 0.0,
            "depth_bonus": float(max(0.0, 3.0 if s11_is_feasible else 0.0)),
            "geometry_penalty": 0.0,
            "s12_cost": float(s12_cost),
            "gain_cost": float(gain_cost),
            "constraint_penalty": float(constraint_penalty),
        }
        raw_metrics = {
            "violation_raw": float(violation_cost),
            "bandwidth_gap_raw": float(max(float(stage.bandwidth_target or 0.0) - float(bandwidth or 0.0), 0.0)),
            "coverage_gap_raw": 0.0,
            "depth_raw": float(np.mean(np.clip(thresholds - band_s11, 0.0, None))) if band_s11.size else 0.0,
            "s12_violation_raw": float(s12_cost),
            "gain_violation_raw": float(gain_cost),
            "geometry_raw": 0.0,
            "constraint_raw": float(constraint_penalty),
        }
        return float(cost), components, raw_metrics

    def _single_objective_strategy(self) -> str:
        """Return the configured scalar wrapper strategy."""
        strategy = self.fitness_config.get("single_objective_strategy", "legacy")
        return str(strategy or "legacy").strip().lower()

    def _single_objective_wrapper_strategy(self) -> str:
        """Return the normalized wrapper strategy used for scalar dispatch."""
        strategy = self._single_objective_strategy()
        if strategy in {"bo", "de"}:
            return strategy
        return "legacy"

    def _fixed_adaptive_scales(self) -> Dict[str, float]:
        """Return identity scales for fixed-target BO scoring."""
        return {name: 1.0 for name in self.TRACKED_COMPONENTS}

    def _finalize_adaptive_scales(self, raw_metrics: Dict[str, float]) -> Dict[str, float]:
        """Apply post-evaluation scale updates consistently with scalar dispatch."""
        if self._single_objective_wrapper_strategy() == "legacy":
            self._update_adaptive_scales(raw_metrics)
            return self.adaptive_scales.copy()
        return self._fixed_adaptive_scales()

    def _compute_component_cost(
        self,
        stage: FitnessStage,
        freqs: np.ndarray,
        s11: np.ndarray,
        bandwidth: Optional[float],
        segment: Optional[dict],
        s21: Optional[np.ndarray],
        gain_min: Optional[float],
        extra_metrics: Optional[Dict[str, Any]] = None,
        adaptive_scales_override: Optional[Dict[str, float]] = None,
    ) -> Tuple[float, Dict[str, float], Dict[str, float]]:
        """Compute weighted component costs for upgraded objective modes."""
        extra_metrics = extra_metrics or {}
        adaptive_scales = adaptive_scales_override or self.adaptive_scales
        f_ghz = self._normalize_frequency(freqs)
        band_mask = (f_ghz >= stage.freq_band[0]) & (f_ghz <= stage.freq_band[1])
        if not np.any(band_mask):
            return self._legacy_cost(stage, freqs, s11, bandwidth, s21, gain_min, extra_metrics=extra_metrics)

        band_freqs = f_ghz[band_mask]
        band_s11 = np.asarray(s11, dtype=float)[band_mask]
        band_s21 = np.asarray(s21, dtype=float)[band_mask] if s21 is not None else None
        thresholds = self._s11_threshold_array(stage, band_freqs)
        band_start = float(stage.freq_band[0])
        band_end = float(stage.freq_band[1])
        band_span = max(band_end - band_start, 0.0)
        bw_value = float(bandwidth or 0.0)

        excess = np.clip(band_s11 - thresholds, 0.0, None)
        violation_raw = float(np.mean(np.square(excess)) * 20.0 + np.mean(excess) * 2.0) if excess.size else 0.0
        s11_feasible = bool(np.all(excess <= 0.0))

        bw_target = self._get_bandwidth_target_for_cost(stage)
        bandwidth_gap_raw = max(float(bw_target) - bw_value, 0.0) if bw_target is not None else 0.0
        bandwidth_raw = float(np.square(bandwidth_gap_raw))

        start_freq = segment.get("start_freq") if segment else None
        end_freq = segment.get("end_freq") if segment else None
        if start_freq is None or end_freq is None:
            start_gap = band_span
            end_gap = band_span
        else:
            start_gap = max(float(start_freq) - band_start - self.coverage_tolerance, 0.0)
            end_gap = max(band_end - float(end_freq) - self.coverage_tolerance, 0.0)
        coverage_gap_raw = float(np.square(start_gap) + np.square(end_gap))

        depth_margin = np.clip(thresholds - band_s11, 0.0, None)
        depth_raw = float(min(np.mean(depth_margin) / max(self.depth_reference, 1e-6), self.depth_bonus_cap)) if depth_margin.size else 0.0

        s12_violation_raw = 0.0
        if stage.s12_target is not None:
            if band_s21 is None:
                s12_violation_raw = 1000.0
            else:
                s21_threshold = float(stage.s12_target)
                s21_excess = np.clip(band_s21 - s21_threshold, 0.0, None)
                s12_violation_raw = float(np.mean(np.square(s21_excess)) * 25.0 + np.mean(s21_excess) * 3.0) if s21_excess.size else 0.0

        gain_violation_raw = 0.0
        if stage.gain_target is not None:
            if gain_min is None:
                gain_violation_raw = 1000.0
            elif gain_min < stage.gain_target:
                gain_violation_raw = float(stage.gain_target - gain_min)

        geometry_raw = float(extra_metrics.get("geometry_metric", 0.0) or 0.0)
        violation_cost = self.component_weights["violation"] * adaptive_scales["violation"] * violation_raw
        bandwidth_cost = self.component_weights["bandwidth"] * adaptive_scales["bandwidth"] * bandwidth_raw
        coverage_cost = self.component_weights["coverage"] * adaptive_scales["coverage"] * coverage_gap_raw
        s12_cost = self.component_weights["s12"] * adaptive_scales["s12"] * s12_violation_raw
        gain_cost = self.component_weights["gain"] * adaptive_scales["gain"] * gain_violation_raw
        geometry_cost = self.component_weights["geometry"] * (geometry_raw / self.geometry_reference)
        depth_bonus = self.component_weights["depth"] * depth_raw

        positive_costs = violation_cost + bandwidth_cost + coverage_cost + s12_cost + gain_cost + geometry_cost
        constraint_penalty = positive_costs

        if self.objective_mode == "feasible_first":
            cost = violation_cost
            if not s11_feasible:
                cost += 1000.0 + bandwidth_cost + coverage_cost
            else:
                cost += bandwidth_cost + coverage_cost + geometry_cost
                if stage.s12_target is not None:
                    cost += s12_cost
                if stage.gain_target is not None:
                    cost += gain_cost
                cost -= depth_bonus
        elif self.objective_mode == "minimax":
            normalized = [
                violation_raw,
                bandwidth_gap_raw,
                np.sqrt(coverage_gap_raw) if coverage_gap_raw > 0 else 0.0,
                s12_violation_raw,
                gain_violation_raw,
            ]
            cost = max(normalized) + 0.1 * sum(normalized) - depth_bonus
        else:
            cost = positive_costs - depth_bonus

        component_costs = {
            "violation_cost": float(violation_cost),
            "bandwidth_cost": float(bandwidth_cost),
            "coverage_cost": float(coverage_cost),
            "depth_bonus": float(depth_bonus),
            "geometry_penalty": float(geometry_cost),
            "s12_cost": float(s12_cost),
            "gain_cost": float(gain_cost),
            "constraint_penalty": float(constraint_penalty),
        }
        raw_metrics = {
            "violation_raw": float(violation_raw),
            "bandwidth_gap_raw": float(bandwidth_gap_raw),
            "coverage_gap_raw": float(coverage_gap_raw),
            "depth_raw": float(depth_raw),
            "s12_violation_raw": float(s12_violation_raw),
            "gain_violation_raw": float(gain_violation_raw),
            "geometry_raw": float(geometry_raw),
            "constraint_raw": float(constraint_penalty),
        }
        return float(cost), component_costs, raw_metrics

    def _compute_cost(
        self,
        stage: FitnessStage,
        freqs: np.ndarray,
        s11: np.ndarray,
        bandwidth: Optional[float],
        segment: Optional[dict],
        s21: Optional[np.ndarray],
        gain_min: Optional[float],
        extra_metrics: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, Dict[str, float], Dict[str, float]]:
        single_objective_strategy = self._single_objective_wrapper_strategy()
        if self.objective_mode == "legacy" and not self.fitness_config:
            return self._legacy_cost(stage, freqs, s11, bandwidth, s21, gain_min)
        adaptive_scales_override = self._fixed_adaptive_scales() if single_objective_strategy in {"bo", "de"} else None
        cost, component_costs, raw_metrics = self._compute_component_cost(
            stage,
            freqs,
            s11,
            bandwidth,
            segment,
            s21,
            gain_min,
            extra_metrics=extra_metrics,
            adaptive_scales_override=adaptive_scales_override,
        )
        if single_objective_strategy == "legacy":
            return cost, component_costs, raw_metrics

        metrics = dict((extra_metrics or {}).get("fitness_metrics") or {})
        if not metrics:
            return cost, component_costs, raw_metrics
        if single_objective_strategy == "bo":
            return self.fitness_for_bo(metrics), component_costs, raw_metrics
        if single_objective_strategy == "de":
            return self.fitness_for_de(metrics), component_costs, raw_metrics
        return cost, component_costs, raw_metrics

    def _update_adaptive_scales(self, raw_metrics: Dict[str, float]) -> None:
        """Update adaptive penalty scales after each evaluation."""
        if not self.adaptive_config.get("enabled", False):
            return

        increase = float(self.adaptive_config["increase"])
        decrease = float(self.adaptive_config["decrease"])
        min_scale = float(self.adaptive_config["min_scale"])
        max_scale = float(self.adaptive_config["max_scale"])

        metric_key_map = {
            "violation": "violation_raw",
            "bandwidth": "bandwidth_gap_raw",
            "coverage": "coverage_gap_raw",
            "s12": "s12_violation_raw",
            "gain": "gain_violation_raw",
        }

        for name in self.adaptive_config.get("components", []):
            metric_key = metric_key_map.get(name)
            if metric_key is None:
                continue

            raw_value = float(raw_metrics.get(metric_key, 0.0))
            if raw_value > 1e-9:
                self.adaptive_scales[name] = min(self.adaptive_scales[name] * increase, max_scale)
            else:
                self.adaptive_scales[name] = max(self.adaptive_scales[name] * decrease, min_scale)

    def is_target_met(
        self,
        stage: FitnessStage,
        freqs: np.ndarray,
        s11: np.ndarray,
        bandwidth: Optional[float],
        gain_min: Optional[float],
    ) -> bool:
        """Check whether the target is satisfied."""
        thresholds = self._s11_threshold_array(stage, np.asarray(freqs, dtype=float))
        band_s11 = np.asarray(s11, dtype=float)
        if band_s11.size == 0 or thresholds.size == 0:
            return False
        if np.any(band_s11 > thresholds + 1e-12):
            return False

        if stage.s12_target is not None:
            if gain_min is None or gain_min > stage.s12_target:
                return False

        if stage.bandwidth_target is not None:
            if bandwidth is None or bandwidth < stage.bandwidth_target:
                return False

        if stage.gain_target is not None:
            if gain_min is None or gain_min < stage.gain_target:
                return False

        return True
