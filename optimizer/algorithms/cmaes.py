from typing import List

import numpy as np

from .base import OptimizationAlgorithm


def _load_cma():
    try:
        import cma
    except ImportError as exc:
        raise RuntimeError(
            "CMA-ES requires the optional 'cma' package. Install pycma before using CMAESOptimizer."
        ) from exc
    return cma


class CMAESOptimizer(OptimizationAlgorithm):
    """CMA-ES adapter operating in a normalized unit hypercube."""

    def __init__(
        self,
        bounds: List[tuple],
        initial_point=None,
        mode: str = "local",
        sigma0=None,
        seed=None,
    ):
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in {"local", "global"}:
            raise ValueError(f"Unsupported CMA-ES mode: {mode}")

        super().__init__(bounds)
        self._bounds_array = np.asarray(bounds, dtype=float)
        if (
            self._bounds_array.ndim != 2
            or self._bounds_array.shape[0] == 0
            or self._bounds_array.shape[1] != 2
            or not np.all(np.isfinite(self._bounds_array))
            or np.any(self._bounds_array[:, 1] < self._bounds_array[:, 0])
        ):
            raise ValueError("bounds must be a non-empty finite sequence of (low, high) pairs.")
        self._lows = self._bounds_array[:, 0]
        self._highs = self._bounds_array[:, 1]
        self._spans = self._highs - self._lows

        if initial_point is None:
            initial_point = self._lows + 0.5 * self._spans
        initial_point = self._validate_vector(initial_point, "initial_point")
        self.initial_point = self.to_physical(self.to_normalized(initial_point))

        sigma = float(sigma0) if sigma0 is not None else (0.10 if normalized_mode == "local" else 0.25)
        if not np.isfinite(sigma) or sigma <= 0.0:
            raise ValueError("sigma0 must be a positive finite value.")
        options = {
            "bounds": [0.0, 1.0],
            "verbose": -9,
            "verb_disp": 0,
            "verb_log": 0,
        }
        if seed is not None:
            options["seed"] = seed

        cma = _load_cma()
        self._strategy = cma.CMAEvolutionStrategy(
            self.to_normalized(self.initial_point).tolist(),
            sigma,
            options,
        )
        self.n_particles = int(self._strategy.popsize)
        self._asked_batch = None

    def _validate_vector(self, values, name: str) -> np.ndarray:
        vector = np.asarray(values, dtype=float)
        if vector.shape != (len(self.bounds),) or not np.all(np.isfinite(vector)):
            raise ValueError(f"{name} must be a finite vector with {len(self.bounds)} values.")
        return vector

    def to_normalized(self, params) -> np.ndarray:
        physical = np.asarray(params, dtype=float)
        if physical.ndim not in {1, 2} or physical.shape[-1] != len(self.bounds):
            raise ValueError(f"params must have {len(self.bounds)} values per point.")
        normalized = np.zeros_like(physical, dtype=float)
        np.divide(
            physical - self._lows,
            self._spans,
            out=normalized,
            where=self._spans != 0.0,
        )
        return np.clip(normalized, 0.0, 1.0)

    def to_physical(self, points) -> np.ndarray:
        normalized = np.asarray(points, dtype=float)
        if normalized.ndim not in {1, 2} or normalized.shape[-1] != len(self.bounds):
            raise ValueError(f"points must have {len(self.bounds)} values per point.")
        normalized = np.clip(normalized, 0.0, 1.0)
        return self._lows + normalized * self._spans

    def suggest(self) -> np.ndarray:
        return self.get_best()

    def suggest_population(self) -> np.ndarray:
        if self._asked_batch is not None:
            raise RuntimeError("CMA-ES already has a pending evaluation batch.")
        asked = self._strategy.ask()
        self._asked_batch = np.asarray(asked, dtype=float).copy()
        return self.to_physical(self._asked_batch)

    def update(self, fitness_results: List):
        if self._asked_batch is None:
            raise ValueError("suggest_population must be called before update.")

        results = list(fitness_results)
        if len(results) != len(self._asked_batch):
            raise ValueError("CMA-ES update requires a complete result batch.")

        costs = []
        physical_points = []
        for expected_idx, result in enumerate(results):
            for attribute in ("individual_idx", "params", "cost"):
                if not hasattr(result, attribute):
                    raise ValueError(f"CMA-ES result is missing {attribute}.")
            if result.individual_idx != expected_idx:
                raise ValueError("CMA-ES results must be ordered by individual_idx.")

            physical = self.to_physical(self.to_normalized(self._validate_vector(result.params, "params")))
            cost = float(result.cost)
            if not np.isfinite(cost):
                raise ValueError("CMA-ES result costs must be finite.")
            physical_points.append(physical)
            costs.append(cost)

        self._strategy.tell(self._asked_batch.copy(), costs)
        self._asked_batch = None
        for physical, cost in zip(physical_points, costs):
            self.update_best(physical, cost)

    def get_best(self) -> np.ndarray:
        if self.best_params is not None:
            return self.best_params.copy()
        return self.initial_point.copy()

    @property
    def name(self) -> str:
        return "CMA-ES"
