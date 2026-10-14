import builtins
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer.algorithms.cmaes import CMAESOptimizer
import optimizer.algorithms.cmaes as cmaes_module


class FakeStrategy:
    instances = []

    def __init__(self, initial_point, sigma0, options):
        self.initial_point = np.asarray(initial_point, dtype=float)
        self.sigma0 = float(sigma0)
        self.options = dict(options)
        self.popsize = 2
        self.ask_response = [
            np.array([0.2, 0.8], dtype=float),
            np.array([0.7, 0.1], dtype=float),
        ]
        self.tell_calls = []
        self.__class__.instances.append(self)

    def ask(self):
        return self.ask_response

    def tell(self, points, costs):
        self.tell_calls.append((points, costs))


@pytest.fixture
def fake_cma(monkeypatch):
    FakeStrategy.instances.clear()
    monkeypatch.setattr(
        cmaes_module,
        "_load_cma",
        lambda: SimpleNamespace(CMAEvolutionStrategy=FakeStrategy),
    )
    return FakeStrategy


def test_constructor_uses_center_local_sigma_and_quiet_bounded_options(fake_cma):
    optimizer = CMAESOptimizer(
        bounds=[(10.0, 20.0), (-4.0, 6.0)],
        seed=17,
    )

    strategy = fake_cma.instances[-1]
    np.testing.assert_allclose(strategy.initial_point, [0.5, 0.5])
    assert strategy.sigma0 == pytest.approx(0.10)
    assert strategy.options["bounds"] == [0.0, 1.0]
    assert strategy.options["verbose"] < 0
    assert strategy.options["verb_disp"] == 0
    assert strategy.options["verb_log"] == 0
    assert strategy.options["seed"] == 17
    np.testing.assert_allclose(optimizer.get_best(), [15.0, 1.0])
    np.testing.assert_allclose(optimizer.suggest(), [15.0, 1.0])
    assert optimizer.name == "CMA-ES"


def test_failed_cases_complete_tell_without_becoming_best(fake_cma):
    optimizer = CMAESOptimizer([(0, 1), (0, 1)])
    points = optimizer.suggest_population()
    results = [SimpleNamespace(params=point, cost=1e12, individual_idx=index, valid=False)
               for index, point in enumerate(points)]
    optimizer.update(results)
    assert len(fake_cma.instances[-1].tell_calls) == 1
    assert optimizer.best_params is None
    assert optimizer.best_cost == float("inf")


def test_constructor_supports_global_and_explicit_sigma(fake_cma):
    CMAESOptimizer(bounds=[(0.0, 1.0)], mode="global")
    assert fake_cma.instances[-1].sigma0 == pytest.approx(0.25)

    CMAESOptimizer(bounds=[(0.0, 1.0)], mode="global", sigma0=0.4)
    assert fake_cma.instances[-1].sigma0 == pytest.approx(0.4)


def test_constructor_rejects_invalid_mode(fake_cma):
    with pytest.raises(ValueError, match="mode"):
        CMAESOptimizer(bounds=[(0.0, 1.0)], mode="regional")


def test_normalization_clips_and_handles_zero_span(fake_cma):
    optimizer = CMAESOptimizer(
        bounds=[(10.0, 20.0), (3.0, 3.0)],
        initial_point=[25.0, -100.0],
    )

    np.testing.assert_allclose(optimizer.to_normalized([5.0, 99.0]), [0.0, 0.0])
    np.testing.assert_allclose(optimizer.to_normalized([15.0, 3.0]), [0.5, 0.0])
    np.testing.assert_allclose(optimizer.to_physical([-0.5, 0.8]), [10.0, 3.0])
    np.testing.assert_allclose(optimizer.to_physical([1.5, -0.2]), [20.0, 3.0])
    np.testing.assert_allclose(fake_cma.instances[-1].initial_point, [1.0, 0.0])


def test_suggest_population_asks_once_stores_exact_batch_and_returns_physical(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(10.0, 20.0), (-4.0, 6.0)])
    strategy = fake_cma.instances[-1]

    population = optimizer.suggest_population()

    np.testing.assert_allclose(
        optimizer._asked_batch,
        strategy.ask_response,
    )
    np.testing.assert_allclose(
        population,
        [
            [12.0, 4.0],
            [17.0, -3.0],
        ],
    )


def test_update_tells_exact_asked_points_with_evaluated_costs_and_tracks_physical_best(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(10.0, 20.0), (-4.0, 6.0)])
    strategy = fake_cma.instances[-1]
    optimizer.suggest_population()
    results = [
        SimpleNamespace(individual_idx=0, params=np.array([12.5, 4.5]), cost=3.0),
        SimpleNamespace(individual_idx=1, params=np.array([18.0, -2.0]), cost=1.0),
    ]

    optimizer.update(results)

    assert len(strategy.tell_calls) == 1
    points, costs = strategy.tell_calls[0]
    np.testing.assert_allclose(points, strategy.ask_response)
    assert costs == [3.0, 1.0]
    np.testing.assert_allclose(optimizer.get_best(), [18.0, -2.0])
    np.testing.assert_allclose(optimizer.suggest(), [18.0, -2.0])
    assert optimizer.best_cost == pytest.approx(1.0)


def test_update_requires_a_pending_asked_batch(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])

    with pytest.raises(ValueError, match="suggest_population"):
        optimizer.update([])


def test_update_rejects_incomplete_results(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()

    with pytest.raises(ValueError, match="complete"):
        optimizer.update(
            [SimpleNamespace(individual_idx=0, params=np.array([0.2, 0.8]), cost=1.0)]
        )


def test_update_rejects_results_not_ordered_by_individual_idx(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()

    with pytest.raises(ValueError, match="ordered"):
        optimizer.update(
            [
                SimpleNamespace(individual_idx=1, params=np.array([0.7, 0.1]), cost=1.0),
                SimpleNamespace(individual_idx=0, params=np.array([0.2, 0.8]), cost=2.0),
            ]
        )


def test_suggest_population_rejects_second_ask_before_update(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()

    with pytest.raises(RuntimeError, match="pending"):
        optimizer.suggest_population()


@pytest.mark.parametrize("cost", [np.nan, np.inf, -np.inf])
def test_update_rejects_non_finite_costs(fake_cma, cost):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()

    with pytest.raises(ValueError, match="finite"):
        optimizer.update(
            [
                SimpleNamespace(individual_idx=0, params=np.array([0.2, 0.8]), cost=cost),
                SimpleNamespace(individual_idx=1, params=np.array([0.7, 0.1]), cost=1.0),
            ]
        )


@pytest.mark.parametrize(
    "bounds",
    [
        [],
        [(0.0, 1.0, 2.0)],
        [(1.0, 0.0)],
        [(0.0, np.inf)],
        [(np.nan, 1.0)],
    ],
)
def test_constructor_rejects_invalid_bounds(fake_cma, bounds):
    with pytest.raises(ValueError, match="bounds"):
        CMAESOptimizer(bounds=bounds)


def test_constructor_rejects_initial_point_with_wrong_shape(fake_cma):
    with pytest.raises(ValueError, match="initial_point"):
        CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)], initial_point=[0.5])


def test_update_rejects_result_params_with_wrong_shape(fake_cma):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()

    with pytest.raises(ValueError, match="params"):
        optimizer.update(
            [
                SimpleNamespace(individual_idx=0, params=np.array([0.2]), cost=2.0),
                SimpleNamespace(individual_idx=1, params=np.array([0.7, 0.1]), cost=1.0),
            ]
        )


@pytest.mark.parametrize("missing_attribute", ["individual_idx", "params", "cost"])
def test_update_rejects_results_missing_required_attributes(fake_cma, missing_attribute):
    optimizer = CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])
    optimizer.suggest_population()
    payloads = [
        {"individual_idx": 0, "params": np.array([0.2, 0.8]), "cost": 2.0},
        {"individual_idx": 1, "params": np.array([0.7, 0.1]), "cost": 1.0},
    ]
    del payloads[0][missing_attribute]

    with pytest.raises(ValueError, match=missing_attribute):
        optimizer.update([SimpleNamespace(**payload) for payload in payloads])


def test_cmaes_optimizer_is_exported_from_algorithms_package():
    from optimizer.algorithms import CMAESOptimizer as ExportedCMAESOptimizer

    assert ExportedCMAESOptimizer is CMAESOptimizer


def test_constructor_raises_clear_runtime_error_when_cma_is_missing(monkeypatch):
    real_import = builtins.__import__

    def missing_cma(name, *args, **kwargs):
        if name == "cma":
            raise ModuleNotFoundError("No module named 'cma'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_cma)

    with pytest.raises(RuntimeError, match="Install pycma"):
        CMAESOptimizer(bounds=[(0.0, 1.0), (0.0, 1.0)])


def test_algorithms_and_task_runner_import_without_loading_optional_cma():
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "cma":
        raise AssertionError("optional cma was imported during module import")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import optimizer.algorithms
import optimizer.task_runner
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(cmaes_module.__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_real_pycma_strategy_can_be_constructed():
    pytest.importorskip("cma")

    optimizer = CMAESOptimizer(
        bounds=[(0.0, 10.0), (-5.0, 5.0)],
        seed=3,
    )

    assert optimizer._strategy.popsize > 0
