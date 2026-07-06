from __future__ import annotations

from typing import List

import numpy as np

from .base import OptimizationAlgorithm


class DuplicateCandidateExhausted(RuntimeError):
    """Raised when BO cannot produce a new quantized candidate in the current region."""


class BOOptimizer(OptimizationAlgorithm):
    """Minimal sequential Bayesian optimizer backed by BoTorch."""

    def __init__(
        self,
        bounds: List[tuple],
        n_initial: int = 8,
        strategy: str = "tr",
        acquisition: str = "log_ei",
        raw_samples: int = 128,
        num_restarts: int = 8,
        neighbor_tolerance: List[float] | None = None,
        max_duplicate_retries: int = 50,
    ):
        super().__init__(bounds, n_initial)
        self.n_dims = len(bounds)
        self.n_initial = max(int(n_initial), 1)
        self.strategy = str(strategy or "tr").strip().lower()
        if self.strategy not in {"global", "tr"}:
            raise ValueError(f"Unsupported BO strategy: {strategy}")
        self.acquisition = str(acquisition or "log_ei").strip().lower()
        self.raw_samples = max(int(raw_samples), 16)
        self.num_restarts = max(int(num_restarts), 1)
        self.max_duplicate_retries = max(int(max_duplicate_retries), 1)
        self.seed_point = None
        self._seed_point_used = False
        self._initial_samples_drawn = 0
        self._sobol_engine = None
        self._pending_diagnostics = None
        self._bo_observations = 0
        self._bo_abs_error_sum = 0.0
        self._bo_coverage_hits = 0
        self.history_loaded_count = 0
        self._blocked_candidates = np.zeros((0, self.n_dims), dtype=float)
        self._tr_fraction = 0.5
        self._tr_min_fraction = 0.1
        self._tr_max_fraction = 1.0
        self._tr_expand_factor = 1.25
        self._tr_shrink_factor = 0.5
        self._tr_failure_tolerance = 3
        self._tr_failure_streak = 0

        self.X_train = np.zeros((0, self.n_dims), dtype=float)
        self.y_train = np.zeros((0,), dtype=float)
        self._bounds_array = np.asarray(bounds, dtype=float)
        tolerance = np.asarray(neighbor_tolerance if neighbor_tolerance is not None else np.zeros(self.n_dims), dtype=float)
        if tolerance.shape != (self.n_dims,):
            raise ValueError("neighbor_tolerance must match the dimensionality of bounds.")
        self._neighbor_tolerance = np.maximum(tolerance, 0.0)

    def _random_sample_in_bounds(self, lows: np.ndarray, highs: np.ndarray) -> np.ndarray:
        return np.random.uniform(lows, highs).astype(float)

    def _random_sample(self) -> np.ndarray:
        lows = self._bounds_array[:, 0]
        highs = self._bounds_array[:, 1]
        return self._random_sample_in_bounds(lows, highs)

    def _sobol_sample(self) -> np.ndarray:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "BoTorch dependencies are missing. Install the project with the 'bo' extra."
            ) from exc

        if self._sobol_engine is None:
            self._sobol_engine = torch.quasirandom.SobolEngine(
                dimension=self.n_dims,
                scramble=True,
                seed=0,
            )

        sample = self._sobol_engine.draw(1).detach().cpu().numpy().reshape(-1)
        lows = self._bounds_array[:, 0]
        highs = self._bounds_array[:, 1]
        return lows + sample * (highs - lows)

    def _clip(self, params: np.ndarray) -> np.ndarray:
        lows = self._bounds_array[:, 0]
        highs = self._bounds_array[:, 1]
        return np.clip(np.asarray(params, dtype=float), lows, highs)

    def _is_near_existing(self, params: np.ndarray) -> bool:
        candidate = self._clip(params).reshape(1, -1)
        thresholds = np.where(self._neighbor_tolerance > 0.0, 0.5 * self._neighbor_tolerance, 0.0)
        if self.X_train.size > 0:
            train_deltas = np.abs(self.X_train - candidate)
            if np.any(np.all(train_deltas <= thresholds, axis=1)):
                return True
        if self._blocked_candidates.size > 0:
            blocked_deltas = np.abs(self._blocked_candidates - candidate)
            if np.any(np.all(blocked_deltas <= thresholds, axis=1)):
                return True
        return False

    def register_existing_candidate(self, params: np.ndarray) -> None:
        candidate = self._clip(np.asarray(params, dtype=float)).reshape(1, -1)
        if self._blocked_candidates.size == 0:
            self._blocked_candidates = candidate
            return
        if self._is_near_existing(candidate.reshape(-1)):
            return
        self._blocked_candidates = np.vstack([self._blocked_candidates, candidate])

    def _sample_unique_candidate(self, sampler) -> tuple[np.ndarray, dict]:
        last_candidate = None
        last_diagnostics = {
            "phase": "",
            "candidate_source": "",
            "pred_mean": None,
            "pred_std": None,
            "acq_value": None,
        }
        for _ in range(self.max_duplicate_retries):
            sampled = sampler()
            if isinstance(sampled, tuple) and len(sampled) == 2:
                candidate, diagnostics = sampled
            else:
                candidate = sampled
                diagnostics = {
                    "phase": "",
                    "candidate_source": "",
                    "pred_mean": None,
                    "pred_std": None,
                    "acq_value": None,
                }
            candidate = self._clip(candidate)
            last_candidate = candidate
            last_diagnostics = diagnostics
            if not self._is_near_existing(candidate):
                return candidate, diagnostics

        fallback_lows, fallback_highs = self._candidate_bounds()
        for _ in range(self.max_duplicate_retries):
            candidate = self._clip(self._random_sample_in_bounds(fallback_lows, fallback_highs))
            if self._is_near_existing(candidate):
                continue
            fallback_diagnostics = {
                "phase": str(last_diagnostics.get("phase", "") or "fallback"),
                "candidate_source": "fallback_random",
                "pred_mean": None,
                "pred_std": None,
                "acq_value": None,
            }
            return candidate, fallback_diagnostics

        raise DuplicateCandidateExhausted(
            f"Unable to find a new BO candidate after {self.max_duplicate_retries} retries."
        )

    def _candidate_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lows = self._bounds_array[:, 0].copy()
        highs = self._bounds_array[:, 1].copy()
        if self.strategy != "tr" or self.best_params is None:
            return lows, highs

        center = self._clip(self.best_params)
        spans = highs - lows
        half_width = 0.5 * self._tr_fraction * spans
        local_lows = np.maximum(lows, center - half_width)
        local_highs = np.minimum(highs, center + half_width)
        return local_lows, local_highs

    def _build_model(self):
        try:
            import torch
            from botorch.fit import fit_gpytorch_mll
            from botorch.models import SingleTaskGP
            from botorch.models.transforms import Normalize, Standardize
            from gpytorch.mlls import ExactMarginalLogLikelihood
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "BoTorch dependencies are missing. Install the project with the 'bo' extra."
            ) from exc

        train_x = torch.tensor(self.X_train, dtype=torch.double)
        train_y = torch.tensor(self.y_train.reshape(-1, 1), dtype=torch.double)
        model = SingleTaskGP(
            train_x,
            train_y,
            input_transform=Normalize(d=self.n_dims),
            outcome_transform=Standardize(m=1),
        )
        mll = ExactMarginalLogLikelihood(model.likelihood, model)
        fit_gpytorch_mll(mll)
        return model

    def _optimize_log_ei(self):
        try:
            import torch
            from botorch.acquisition import LogExpectedImprovement
            from botorch.optim import optimize_acqf
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "BoTorch dependencies are missing. Install the project with the 'bo' extra."
            ) from exc

        model = self._build_model()
        candidate_lows, candidate_highs = self._candidate_bounds()
        bounds = torch.tensor(np.vstack([candidate_lows, candidate_highs]), dtype=torch.double)
        best_f = torch.tensor(float(np.min(self.y_train)), dtype=torch.double)
        acqf = LogExpectedImprovement(model=model, best_f=best_f, maximize=False)
        candidate, _ = optimize_acqf(
            acq_function=acqf,
            bounds=bounds,
            q=1,
            num_restarts=self.num_restarts,
            raw_samples=self.raw_samples,
        )
        posterior = model.posterior(candidate)
        pred_mean = float(posterior.mean.detach().cpu().reshape(-1)[0])
        pred_std = float(torch.sqrt(posterior.variance.clamp_min(0.0)).detach().cpu().reshape(-1)[0])
        acq_value = float(acqf(candidate).detach().cpu().reshape(-1)[0])
        return candidate.detach().cpu().numpy().reshape(-1), {
            "phase": "bo",
            "candidate_source": "bo",
            "pred_mean": pred_mean,
            "pred_std": pred_std,
            "acq_value": acq_value,
        }

    def _rolling_summary(self) -> dict:
        if self._bo_observations <= 0:
            return {
                "observations": 0,
                "mae": None,
                "coverage_2sigma": None,
                "history_loaded": int(self.history_loaded_count),
            }
        return {
            "observations": int(self._bo_observations),
            "mae": float(self._bo_abs_error_sum / self._bo_observations),
            "coverage_2sigma": float(self._bo_coverage_hits / self._bo_observations),
            "history_loaded": int(self.history_loaded_count),
        }

    def preload_history(self, params_matrix: np.ndarray, costs: np.ndarray) -> int:
        params_array = np.asarray(params_matrix, dtype=float)
        costs_array = np.asarray(costs, dtype=float).reshape(-1)

        if params_array.ndim != 2 or params_array.shape[1] != self.n_dims:
            raise ValueError("History params must have shape (n, n_dims).")
        if params_array.shape[0] != costs_array.shape[0]:
            raise ValueError("History params/cost lengths do not match.")
        if params_array.shape[0] == 0:
            return 0

        clipped = self._clip(params_array)
        self.X_train = np.vstack([self.X_train, clipped])
        self.y_train = np.append(self.y_train, costs_array.astype(float))
        self.history_loaded_count += int(clipped.shape[0])

        best_idx = int(np.argmin(self.y_train))
        self.best_params = self.X_train[best_idx].copy()
        self.best_cost = float(self.y_train[best_idx])

        if self.seed_point is not None:
            clipped_seed = self._clip(self.seed_point)
            if np.any(np.all(np.isclose(self.X_train, clipped_seed, atol=1e-12, rtol=0.0), axis=1)):
                self._seed_point_used = True

        return int(clipped.shape[0])

    def attach_result_diagnostics(self, result) -> dict:
        diagnostics = dict(self._pending_diagnostics or {})
        self._pending_diagnostics = None
        phase = diagnostics.get("phase", "")
        candidate_source = diagnostics.get("candidate_source", "")
        pred_mean = diagnostics.get("pred_mean")
        pred_std = diagnostics.get("pred_std")
        acq_value = diagnostics.get("acq_value")
        abs_error = None
        within_2sigma = None

        if pred_mean is not None and hasattr(result, "cost"):
            observed_cost = float(result.cost)
            abs_error = abs(observed_cost - float(pred_mean))
            std_value = float(pred_std) if pred_std is not None else None
            if std_value is not None and std_value > 0.0:
                within_2sigma = abs_error <= 2.0 * std_value
            self._bo_observations += 1
            self._bo_abs_error_sum += float(abs_error)
            if within_2sigma:
                self._bo_coverage_hits += 1

        payload = {
            "phase": str(phase or ""),
            "candidate_source": str(candidate_source or ""),
            "pred_mean": float(pred_mean) if pred_mean is not None else None,
            "pred_std": float(pred_std) if pred_std is not None else None,
            "acq_value": float(acq_value) if acq_value is not None else None,
            "abs_error": float(abs_error) if abs_error is not None else None,
            "within_2sigma": within_2sigma,
            "summary": self._rolling_summary(),
        }

        extra_metrics = getattr(result, "extra_metrics", None)
        if not isinstance(extra_metrics, dict):
            extra_metrics = {}
            result.extra_metrics = extra_metrics
        extra_metrics["bo_diagnostics"] = payload
        return payload

    def suggest(self) -> np.ndarray:
        if self.seed_point is not None and not self._seed_point_used:
            self._seed_point_used = True
            self._pending_diagnostics = {
                "phase": "seed",
                "candidate_source": "seed",
                "pred_mean": None,
                "pred_std": None,
                "acq_value": None,
            }
            return self._clip(self.seed_point)

        if len(self.X_train) < self.n_initial:
            self._initial_samples_drawn += 1
            candidate, diagnostics = self._sample_unique_candidate(
                lambda: (
                    self._sobol_sample(),
                    {
                        "phase": "initial",
                        "candidate_source": "initial",
                        "pred_mean": None,
                        "pred_std": None,
                        "acq_value": None,
                    },
                ),
            )
            self._pending_diagnostics = diagnostics
            return candidate

        if self.acquisition != "log_ei":
            raise ValueError(f"Unsupported BO acquisition: {self.acquisition}")

        try:
            candidate, diagnostics = self._sample_unique_candidate(
                self._optimize_log_ei,
            )
            self._pending_diagnostics = diagnostics
            return self._clip(candidate)
        except DuplicateCandidateExhausted:
            self._pending_diagnostics = None
            raise
        except Exception:
            self._pending_diagnostics = {
                "phase": "fallback",
                "candidate_source": "fallback_random",
                "pred_mean": None,
                "pred_std": None,
                "acq_value": None,
            }
            return self._random_sample()

    def update(self, fitness_results: List):
        for result in fitness_results:
            if not hasattr(result, "params") or not hasattr(result, "cost"):
                continue

            params = self._clip(np.asarray(result.params, dtype=float))
            cost = float(result.cost)
            self.X_train = np.vstack([self.X_train, params.reshape(1, -1)])
            self.y_train = np.append(self.y_train, cost)
            improved = self.update_best(params, cost)

            if self.strategy == "tr":
                if improved:
                    self._tr_failure_streak = 0
                    self._tr_fraction = min(
                        self._tr_max_fraction,
                        self._tr_fraction * self._tr_expand_factor,
                    )
                else:
                    self._tr_failure_streak += 1
                    if self._tr_failure_streak >= self._tr_failure_tolerance:
                        self._tr_fraction = max(
                            self._tr_min_fraction,
                            self._tr_fraction * self._tr_shrink_factor,
                        )
                        self._tr_failure_streak = 0

    def get_best(self) -> np.ndarray:
        if self.best_params is not None:
            return self.best_params.copy()
        return self._random_sample()

    @property
    def name(self) -> str:
        return "BO"
