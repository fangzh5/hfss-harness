from types import SimpleNamespace

import numpy as np
import pytest

from optimizer.algorithms.cmaes import CMAESOptimizer


def _sphere(x):
    return float(np.sum(np.square(x)))


def _rosenbrock(x):
    return float(np.sum(100.0 * np.square(x[1:] - np.square(x[:-1])) + np.square(1.0 - x[:-1])))


def _ackley(x):
    dimension = x.size
    square_mean = np.sum(np.square(x)) / dimension
    cosine_mean = np.sum(np.cos(2.0 * np.pi * x)) / dimension
    return float(-20.0 * np.exp(-0.2 * np.sqrt(square_mean)) - np.exp(cosine_mean) + 20.0 + np.e)


@pytest.mark.parametrize(
    ("objective", "dimension", "initial_value", "seed", "iterations", "improvement_ratio"),
    [
        pytest.param(_sphere, 4, 1.5, 11, 35, 0.10, id="sphere"),
        pytest.param(_rosenbrock, 3, 0.2, 23, 50, 0.25, id="rosenbrock"),
        pytest.param(_ackley, 4, 1.5, 37, 40, 0.20, id="ackley"),
    ],
)
def test_cmaes_improves_standard_benchmarks(
    objective,
    dimension,
    initial_value,
    seed,
    iterations,
    improvement_ratio,
):
    pytest.importorskip('cma')

    bounds = [(-5.0, 5.0)] * dimension
    initial_point = np.full(dimension, initial_value, dtype=float)
    optimizer = CMAESOptimizer(
        bounds=bounds,
        initial_point=initial_point,
        mode="local",
        seed=seed,
    )
    lower = np.array([bound[0] for bound in bounds], dtype=float)
    upper = np.array([bound[1] for bound in bounds], dtype=float)
    initial_cost = objective(initial_point)

    for _ in range(iterations):
        candidates = optimizer.suggest_population()
        assert np.all(candidates >= lower)
        assert np.all(candidates <= upper)

        results = [
            SimpleNamespace(
                individual_idx=index,
                params=candidate,
                cost=objective(candidate),
            )
            for index, candidate in enumerate(candidates)
        ]
        optimizer.update(results)

    assert np.isfinite(optimizer.best_cost)
    assert optimizer.best_cost < initial_cost * improvement_ratio
