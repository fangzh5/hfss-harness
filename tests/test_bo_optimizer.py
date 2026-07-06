from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import optimizer.main as main
from optimizer.core.parameter import ParameterManager


def _sphere(x: np.ndarray) -> float:
    return float(np.sum(np.square(np.asarray(x, dtype=float))))


def test_create_algorithm_builds_bo_optimizer():
    config = {
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
            {"name": "y", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "algorithm": {
            "method": "bo",
            "n_initial": 4,
            "acquisition": "log_ei",
            "raw_samples": 64,
            "num_restarts": 5,
        },
        "optimization": {},
    }
    param_mgr = ParameterManager(config["parameters"])

    algorithm = main.create_algorithm(config, param_mgr)

    assert algorithm.name == "BO"
    assert algorithm.n_initial == 4
    assert algorithm.strategy == "tr"
    assert algorithm.acquisition == "log_ei"
    assert algorithm.raw_samples == 64
    assert algorithm.num_restarts == 5


def test_create_algorithm_builds_bo_optimizer_with_global_strategy():
    config = {
        "parameters": [
            {"name": "x", "min": -1.0, "max": 1.0, "resolution": 0.01},
        ],
        "algorithm": {
            "method": "bo",
            "strategy": "global",
        },
        "optimization": {},
    }
    param_mgr = ParameterManager(config["parameters"])

    algorithm = main.create_algorithm(config, param_mgr)

    assert algorithm.name == "BO"
    assert algorithm.strategy == "global"


def test_bo_optimizer_finds_low_cost_on_sphere_benchmark():
    pytest.importorskip("torch")
    from optimizer.algorithms.bo import BOOptimizer

    np.random.seed(7)
    optimizer = BOOptimizer(
        bounds=[(-1.0, 1.0), (-1.0, 1.0)],
        n_initial=4,
        acquisition="log_ei",
        raw_samples=64,
        num_restarts=5,
    )

    for _ in range(12):
        candidate = optimizer.suggest()
        assert candidate.shape == (2,)
        assert np.all(candidate >= -1.0)
        assert np.all(candidate <= 1.0)
        optimizer.update(
            [
                SimpleNamespace(
                    params=np.asarray(candidate, dtype=float).copy(),
                    cost=_sphere(candidate),
                )
            ]
        )

    assert optimizer.best_cost < 0.05
    assert np.linalg.norm(optimizer.get_best()) < 0.3


def test_bo_optimizer_uses_seed_point_first():
    pytest.importorskip("torch")
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(bounds=[(-1.0, 1.0)], n_initial=3)
    optimizer.seed_point = np.array([0.25], dtype=float)

    first = optimizer.suggest()
    second = optimizer.suggest()

    assert first[0] == pytest.approx(0.25)
    assert second[0] != pytest.approx(0.25)


def test_bo_optimizer_uses_deterministic_sobol_warmup():
    pytest.importorskip("torch")
    from optimizer.algorithms.bo import BOOptimizer

    first = BOOptimizer(bounds=[(-1.0, 1.0), (-1.0, 1.0)], n_initial=4)
    second = BOOptimizer(bounds=[(-1.0, 1.0), (-1.0, 1.0)], n_initial=4)

    first_sequence = [first.suggest() for _ in range(3)]
    second_sequence = [second.suggest() for _ in range(3)]

    for first_point, second_point in zip(first_sequence, second_sequence):
        assert np.allclose(first_point, second_point, atol=1e-12, rtol=0.0)


def test_bo_optimizer_attaches_compact_prediction_diagnostics(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(bounds=[(-1.0, 1.0)], n_initial=1)
    optimizer.X_train = np.array([[0.0]], dtype=float)
    optimizer.y_train = np.array([1.0], dtype=float)

    def fake_optimize():
        return np.array([0.25], dtype=float), {
            "phase": "bo",
            "candidate_source": "bo",
            "pred_mean": 1.5,
            "pred_std": 0.5,
            "acq_value": 0.2,
        }

    monkeypatch.setattr(optimizer, "_optimize_log_ei", fake_optimize)

    candidate = optimizer.suggest()
    result = SimpleNamespace(params=candidate.copy(), cost=2.0, extra_metrics={})
    diagnostics = optimizer.attach_result_diagnostics(result)

    assert diagnostics["phase"] == "bo"
    assert diagnostics["candidate_source"] == "bo"
    assert diagnostics["pred_mean"] == pytest.approx(1.5)
    assert diagnostics["pred_std"] == pytest.approx(0.5)
    assert diagnostics["abs_error"] == pytest.approx(0.5)
    assert diagnostics["within_2sigma"] is True
    assert diagnostics["summary"]["observations"] == 1
    assert diagnostics["summary"]["mae"] == pytest.approx(0.5)
    assert diagnostics["summary"]["coverage_2sigma"] == pytest.approx(1.0)
    assert result.extra_metrics["bo_diagnostics"]["abs_error"] == pytest.approx(0.5)
    assert result.extra_metrics["bo_diagnostics"]["candidate_source"] == "bo"


def test_bo_optimizer_preloads_history_and_skips_warmup(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(bounds=[(-1.0, 1.0)], n_initial=3)
    loaded = optimizer.preload_history(
        np.array([[-0.4], [0.0], [0.35]], dtype=float),
        np.array([0.16, 0.0, 0.1225], dtype=float),
    )

    assert loaded == 3
    assert optimizer.history_loaded_count == 3

    def fake_optimize():
        return np.array([0.1], dtype=float), {
            "phase": "bo",
            "pred_mean": 0.02,
            "pred_std": 0.1,
            "acq_value": 0.5,
        }

    monkeypatch.setattr(optimizer, "_optimize_log_ei", fake_optimize)

    candidate = optimizer.suggest()

    assert candidate[0] == pytest.approx(0.1)
    assert optimizer._pending_diagnostics["phase"] == "bo"


def test_bo_optimizer_marks_seed_used_when_history_already_contains_it():
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(bounds=[(-1.0, 1.0)], n_initial=2)
    optimizer.seed_point = np.array([0.25], dtype=float)

    optimizer.preload_history(
        np.array([[0.25], [-0.1]], dtype=float),
        np.array([1.0, 0.5], dtype=float),
    )

    assert optimizer._seed_point_used is True


def test_bo_optimizer_global_strategy_uses_full_bounds():
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(-1.0, 1.0), (-2.0, 2.0)],
        n_initial=2,
        strategy="global",
    )

    lower, upper = optimizer._candidate_bounds()

    assert np.allclose(lower, np.array([-1.0, -2.0]))
    assert np.allclose(upper, np.array([1.0, 2.0]))


def test_bo_optimizer_tr_strategy_uses_local_bounds_around_best():
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(-1.0, 1.0), (-1.0, 1.0)],
        n_initial=2,
        strategy="tr",
    )
    optimizer.preload_history(
        np.array([[-0.5, 0.3], [0.2, -0.1]], dtype=float),
        np.array([1.0, 0.2], dtype=float),
    )

    lower, upper = optimizer._candidate_bounds()
    midpoint = (lower + upper) / 2.0

    assert np.all(lower >= np.array([-1.0, -1.0]))
    assert np.all(upper <= np.array([1.0, 1.0]))
    assert np.all((upper - lower) < np.array([2.0, 2.0]))
    assert np.allclose(midpoint, np.array([0.2, -0.1]))


def test_bo_optimizer_tr_strategy_expands_on_success_and_shrinks_on_failures():
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(-1.0, 1.0)],
        n_initial=1,
        strategy="tr",
    )
    optimizer.update([SimpleNamespace(params=np.array([0.0]), cost=1.0)])

    initial_fraction = optimizer._tr_fraction

    optimizer.update([SimpleNamespace(params=np.array([0.1]), cost=0.5)])
    expanded_fraction = optimizer._tr_fraction

    for idx in range(optimizer._tr_failure_tolerance):
        optimizer.update([SimpleNamespace(params=np.array([0.2 + idx * 0.01]), cost=0.8 + idx)])

    assert expanded_fraction > initial_fraction
    assert optimizer._tr_fraction < expanded_fraction


def test_bo_optimizer_retries_quantized_duplicate_initial_candidates(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(0.0, 1.0)],
        n_initial=4,
        neighbor_tolerance=[0.01],
    )
    optimizer.seed_point = np.array([0.22], dtype=float)

    # First observed point already occupies the 0.22 bin.
    optimizer.update([SimpleNamespace(params=np.array([0.22]), cost=1.0)])
    first = optimizer.suggest()
    assert first[0] == pytest.approx(0.22)

    samples = iter(
        [
            np.array([0.221], dtype=float),  # too close after quantization
            np.array([0.236], dtype=float),  # acceptable new point
        ]
    )

    monkeypatch.setattr(optimizer, "_sobol_sample", lambda: next(samples))

    candidate = optimizer.suggest()

    assert candidate[0] == pytest.approx(0.236)
    assert optimizer._pending_diagnostics["phase"] == "initial"


def test_bo_optimizer_retries_nearby_bo_candidates(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(0.0, 1.0)],
        n_initial=1,
        neighbor_tolerance=[0.01],
    )
    optimizer.preload_history(
        np.array([[0.20], [0.24]], dtype=float),
        np.array([1.0, 0.5], dtype=float),
    )

    calls = {"count": 0}

    def fake_optimize():
        calls["count"] += 1
        if calls["count"] == 1:
            return np.array([0.239], dtype=float), {
                "phase": "bo",
                "pred_mean": 0.4,
                "pred_std": 0.1,
                "acq_value": 0.2,
            }
        return np.array([0.27], dtype=float), {
            "phase": "bo",
            "pred_mean": 0.3,
            "pred_std": 0.1,
            "acq_value": 0.1,
        }

    monkeypatch.setattr(optimizer, "_optimize_log_ei", fake_optimize)

    candidate = optimizer.suggest()

    assert calls["count"] == 2
    assert candidate[0] == pytest.approx(0.27)
    assert optimizer._pending_diagnostics["phase"] == "bo"


def test_bo_optimizer_falls_back_to_random_unique_candidate_when_acquisition_stalls(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer

    optimizer = BOOptimizer(
        bounds=[(0.0, 1.0)],
        n_initial=1,
        neighbor_tolerance=[0.01],
    )
    optimizer.preload_history(
        np.array([[0.20], [0.24]], dtype=float),
        np.array([1.0, 0.5], dtype=float),
    )

    monkeypatch.setattr(
        optimizer,
        "_optimize_log_ei",
        lambda: (
            np.array([0.239], dtype=float),
            {
                "phase": "bo",
                "pred_mean": 0.3,
                "pred_std": 0.1,
                "acq_value": 0.2,
            },
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_random_sample_in_bounds",
        lambda lows, highs: np.array([0.27], dtype=float),
    )

    candidate = optimizer.suggest()

    assert candidate[0] == pytest.approx(0.27)
    assert optimizer._pending_diagnostics["phase"] == "bo"
    assert optimizer._pending_diagnostics["pred_mean"] is None


def test_bo_optimizer_raises_when_no_unique_candidate_can_be_found(monkeypatch):
    from optimizer.algorithms.bo import BOOptimizer, DuplicateCandidateExhausted

    optimizer = BOOptimizer(
        bounds=[(0.0, 1.0)],
        n_initial=1,
        neighbor_tolerance=[0.01],
        max_duplicate_retries=2,
    )
    optimizer.preload_history(
        np.array([[0.20], [0.24]], dtype=float),
        np.array([1.0, 0.5], dtype=float),
    )

    monkeypatch.setattr(
        optimizer,
        "_optimize_log_ei",
        lambda: (
            np.array([0.239], dtype=float),
            {
                "phase": "bo",
                "pred_mean": 0.3,
                "pred_std": 0.1,
                "acq_value": 0.2,
            },
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_random_sample_in_bounds",
        lambda lows, highs: np.array([0.239], dtype=float),
    )

    with pytest.raises(DuplicateCandidateExhausted):
        optimizer.suggest()
