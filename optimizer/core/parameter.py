"""Parameter management helpers for the optimizer."""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class Parameter:
    """Single optimization parameter."""

    name: str
    min_val: float
    max_val: float
    unit: str = "mm"
    mode: str = "step"
    count: Optional[int] = None
    step: Optional[float] = None
    resolution: float = 0.01
    constraint: Optional[str] = None

    @property
    def bounds(self) -> Tuple[float, float]:
        return (self.min_val, self.max_val)

    def get_step_size(self) -> float:
        if self.resolution is not None:
            try:
                resolution = float(self.resolution)
            except Exception:
                resolution = 0.0
            if resolution > 0.0:
                return resolution
        if self.mode == "count" and self.count:
            if self.count <= 1:
                return 0.0
            return (self.max_val - self.min_val) / (self.count - 1)
        if self.step is not None:
            return self.step
        return 0.01


class ParameterManager:
    """Parameter manager."""

    def __init__(self, param_configs: List[dict]):
        self.parameters = self._parse_configs(param_configs)
        self._param_dict = {p.name: p for p in self.parameters}

    def _parse_configs(self, configs: List[dict]) -> List[Parameter]:
        params = []
        for cfg in configs:
            param = Parameter(
                name=cfg["name"],
                min_val=cfg["min"],
                max_val=cfg["max"],
                unit=cfg.get("unit", "mm"),
                mode=cfg.get("mode", "step"),
                count=cfg.get("count"),
                step=cfg.get("step"),
                resolution=cfg.get("resolution", 0.01),
                constraint=cfg.get("constraint"),
            )
            params.append(param)
        return params

    def discretize(
        self,
        params: np.ndarray,
        *,
        include_count: bool = True,
        include_resolution: bool = True,
    ) -> np.ndarray:
        """Snap values to the configured grid."""
        result = np.zeros_like(params, dtype=float)
        for i, p in enumerate(self.parameters):
            value = float(params[i])
            if include_count and p.mode == "count" and p.count:
                if p.count <= 1:
                    value = p.min_val
                else:
                    grid = np.linspace(p.min_val, p.max_val, int(p.count))
                    value = float(grid[int(np.argmin(np.abs(grid - value)))])
            if include_resolution and p.resolution:
                value = np.round(value / p.resolution) * p.resolution
            result[i] = value
        return result

    def clamp(self, params: np.ndarray) -> np.ndarray:
        """Clamp values to bounds."""
        result = np.zeros_like(params, dtype=float)
        for i, p in enumerate(self.parameters):
            result[i] = np.clip(params[i], p.min_val, p.max_val)
        return result

    def quantize_manufacturing(self, params: np.ndarray) -> np.ndarray:
        """Quantize a parameter vector for manufacturable export.

        Manufacturing quantization intentionally uses only the configured
        `resolution`. Search-only helpers such as `count` are ignored here so
        continuous optimizers can explore freely and only snap the final export
        to the actual fabrication precision.
        """
        clamped = self.clamp(np.asarray(params, dtype=float))
        return self.discretize(clamped, include_count=False, include_resolution=True)

    def repair_constraints(self, params: np.ndarray) -> np.ndarray:
        """Repair constrained parameters in-place order while keeping others fixed.

        For simple dependency constraints such as ``probe_p <= patch_w / 2``,
        only the constrained parameter is adjusted. The repair snaps that
        parameter to the nearest legal value on its own configured grid.
        """
        repaired = self.clamp(np.asarray(params, dtype=float)).copy()
        for index, parameter in enumerate(self.parameters):
            if not parameter.constraint:
                continue
            if self._eval_constraint(parameter.constraint, repaired):
                continue
            repaired_value = self._nearest_feasible_value(index, repaired)
            if repaired_value is not None:
                repaired[index] = repaired_value
        return repaired

    def check_constraints(self, params: np.ndarray) -> bool:
        """Check constraint expressions."""
        for p in self.parameters:
            if p.constraint and not self._eval_constraint(p.constraint, params):
                return False
        return True

    def _nearest_feasible_value(self, index: int, params: np.ndarray) -> Optional[float]:
        """Find the closest legal value for one constrained parameter."""
        parameter = self.parameters[index]
        original = float(params[index])
        candidate_values = self._repair_grid(parameter)
        if candidate_values.size == 0:
            return None
        order = np.argsort(np.abs(candidate_values - original), kind="mergesort")
        for candidate in candidate_values[order]:
            trial = params.copy()
            trial[index] = float(candidate)
            if self._eval_constraint(parameter.constraint, trial):
                return float(candidate)
        return None

    def _repair_grid(self, parameter: Parameter) -> np.ndarray:
        """Build a deterministic value grid for constrained-parameter repair."""
        resolution = parameter.get_step_size()
        span = max(float(parameter.max_val) - float(parameter.min_val), 0.0)
        if resolution > 0.0:
            steps = max(int(np.floor(span / resolution + 1e-9)), 0)
            grid = float(parameter.min_val) + np.arange(steps + 1, dtype=float) * resolution
            if grid.size == 0:
                grid = np.array([float(parameter.min_val)], dtype=float)
            if grid[-1] < float(parameter.max_val) - 1e-9:
                grid = np.append(grid, float(parameter.max_val))
            else:
                grid[-1] = min(grid[-1], float(parameter.max_val))
            return np.clip(grid, float(parameter.min_val), float(parameter.max_val))
        return np.array([float(parameter.min_val), float(parameter.max_val)], dtype=float)

    def _eval_constraint(self, constraint_expr: str, params: np.ndarray) -> bool:
        """Evaluate a constraint expression."""
        try:
            expr = constraint_expr
            for i, p in enumerate(self.parameters):
                expr = expr.replace(p.name, f"params[{i}]")
            return bool(eval(expr))
        except Exception:
            return True

    def get_step_size(self) -> np.ndarray:
        """Get the current step-size vector."""
        return np.array([p.get_step_size() for p in self.parameters], dtype=float)

    def get_param_names(self) -> List[str]:
        """Get parameter names."""
        return [p.name for p in self.parameters]

    def get_bounds(self) -> List[Tuple[float, float]]:
        """Get parameter bounds."""
        return [p.bounds for p in self.parameters]

    def get_units(self) -> List[str]:
        """Get parameter units."""
        return [p.unit for p in self.parameters]

    @property
    def n_params(self) -> int:
        return len(self.parameters)
