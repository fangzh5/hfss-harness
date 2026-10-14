from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import optimizer.main as main
from optimizer.core.fitness import FitnessResult
from optimizer.core.parameter import ParameterManager
from fake_parameter_state import FakeParameterState


def test_continuous_optimizers_default_to_continuous_search():
    assert main._use_continuous_search("de", {}) is True
    assert main._use_continuous_search("nsga2", {}) is True
    assert main._use_continuous_search("bo", {}) is True
    assert main._use_continuous_search("cmaes", {}) is True
    assert main._use_continuous_search("pso", {}) is False


def test_pso_uses_resolution_when_count_and_step_are_omitted():
    config = {
        "parameters": [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "resolution": 0.02,
            }
        ],
        "algorithm": {
            "method": "pso",
            "population_size": 4,
        },
        "optimization": {},
    }
    param_mgr = ParameterManager(config["parameters"])

    algorithm = main.create_algorithm(config, param_mgr)

    assert algorithm.step_size[0] == pytest.approx(0.02)


def test_continuous_search_projection_ignores_count_grid():
    param_mgr = ParameterManager(
        [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "mode": "count",
                "count": 11,
                "resolution": 0.1,
            }
        ]
    )

    projected = main._project_search_params(np.array([0.63]), param_mgr, continuous_search=True)

    assert projected[0] == pytest.approx(0.63)


def test_legacy_search_projection_keeps_discretization():
    param_mgr = ParameterManager(
        [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "mode": "count",
                "count": 11,
                "resolution": 0.1,
            }
        ]
    )

    projected = main._project_search_params(np.array([0.63]), param_mgr, continuous_search=False)

    assert projected[0] == pytest.approx(0.6)


def test_manufacturing_quantization_uses_resolution_not_count():
    param_mgr = ParameterManager(
        [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "mode": "count",
                "count": 5,
                "resolution": 0.01,
            }
        ]
    )

    quantized = param_mgr.quantize_manufacturing(np.array([0.626]))

    assert quantized[0] == pytest.approx(0.63)


def test_constraint_repair_adjusts_only_the_constrained_parameter():
    param_mgr = ParameterManager(
        [
            {
                "name": "patch_w",
                "min": 0.8,
                "max": 1.2,
                "resolution": 0.01,
            },
            {
                "name": "probe_p",
                "min": 0.1,
                "max": 0.8,
                "resolution": 0.01,
                "constraint": "probe_p <= patch_w / 2",
            },
        ]
    )

    repaired = param_mgr.repair_constraints(np.array([1.01, 0.53]))

    assert repaired[0] == pytest.approx(1.01)
    assert repaired[1] == pytest.approx(0.50)
    assert param_mgr.check_constraints(repaired) is True


class DummyAdapter:
    def __init__(self):
        self.best_params = None
        self.best_fitness = None
        self.set_calls = []

    def set_parameters(self, params):
        self.set_calls.append(np.asarray(params, dtype=float).copy())
        return True

    def simulate(self):
        freqs = np.array([55.0, 56.0], dtype=float)
        s11 = np.array([-15.0, -16.0], dtype=float)
        s12 = None
        return freqs, s11, s12


class DummyFitnessCalculator:
    def calculate(self, freqs, s11, s12, extra_metrics=None):
        return FitnessResult(cost=1.23, s11_max=float(np.max(s11)), extra_metrics=extra_metrics or {})


def test_revalidate_export_candidate_quantizes_before_save(monkeypatch):
    param_mgr = ParameterManager(
        [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "resolution": 0.01,
            }
        ]
    )
    adapter = DummyAdapter()
    fitness_calc = DummyFitnessCalculator()

    monkeypatch.setattr(main, "_collect_optional_metrics", lambda config, adapter: {})

    export_params, export_cost, export_result = main._revalidate_export_candidate(
        config={"target": {"freq_band": [55, 56]}},
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        best_params=np.array([0.626]),
    )

    assert export_params[0] == pytest.approx(0.63)
    assert export_cost == pytest.approx(1.23)
    assert export_result is not None
    assert len(adapter.set_calls) == 1
    assert adapter.set_calls[0][0] == pytest.approx(0.63)


class CacheKeyAdapter:
    def _format_parameter_assignment(self, name, value, unit=None, resolution=None):
        numeric = float(value)
        if resolution:
            numeric = round(numeric / resolution) * resolution
        numeric = round(numeric, 4)
        return f"{numeric}{unit or ''}"


def test_simulation_cache_key_matches_resolution_quantization():
    param_mgr = ParameterManager(
        [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "unit": "mm",
                "resolution": 0.01,
            }
        ]
    )
    adapter = CacheKeyAdapter()

    key_a = main._simulation_cache_key(np.array([0.12344]), param_mgr, adapter)
    key_b = main._simulation_cache_key(np.array([0.12101]), param_mgr, adapter)
    key_c = main._simulation_cache_key(np.array([0.12901]), param_mgr, adapter)

    assert key_a == key_b
    assert key_a != key_c


class DuplicateBatchAdapter(FakeParameterState):
    def __init__(self):
        self.current_params = None
        self.sim_calls = 0
        self.best_params = None
        self.best_fitness = float("inf")
        self.config = {
            "param_names": ["x"],
            "param_units": ["mm"],
        }

    def set_parameters(self, params):
        self.current_params = np.asarray(params, dtype=float).copy()
        return True

    def simulate(self):
        self.sim_calls += 1
        freqs = np.array([55.0], dtype=float)
        s11 = np.array([self.current_params[0]], dtype=float)
        s12 = None
        return freqs, s11, s12

    def update_best(self, params, cost):
        if cost < self.best_fitness:
            self.best_fitness = cost
            self.best_params = np.asarray(params, dtype=float).copy()
            return True
        return False

    def _format_parameter_assignment(self, name, value, unit=None, resolution=None):
        numeric = float(value)
        if resolution:
            numeric = round(numeric / resolution) * resolution
        numeric = round(numeric, 4)
        return f"{numeric}{unit or ''}"


class DuplicateBatchFitness:
    is_multi_objective = False
    active_stage = type("Stage", (), {"name": "final", "s11_target": -10.0, "s12_target": None, "freq_band": (55.0, 56.0)})()

    def calculate(self, freqs, s11, s12, extra_metrics=None):
        return FitnessResult(cost=float(s11[0]), s11_max=float(s11[0]), target_met=False, stage_met=False)

    def advance_stage(self):
        return False


class DuplicateBatchAlgorithm:
    name = "BatchAlgo"
    is_multi_objective = False

    def __init__(self):
        self.results = None

    def suggest_population(self):
        return np.array([[0.12344], [0.12101]], dtype=float)

    def update(self, fitness_results):
        self.results = list(fitness_results)


def test_run_optimization_reuses_cached_result_for_duplicate_candidates(tmp_path, monkeypatch):
    config = {
        "task_type": "opt",
        "name": "dup_test",
        "parameters": [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "unit": "mm",
                "resolution": 0.01,
            }
        ],
        "target": {"freq_band": [55.0, 56.0]},
        "algorithm": {
            "method": "de",
            "max_iterations": 1,
            "early_stop_patience": 10,
        },
        "optimization": {
            "task_output_dir": str(tmp_path / "run"),
            "save_best_on_exit": False,
            "continuous_search": True,
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    param_mgr = ParameterManager(config["parameters"])
    adapter = DuplicateBatchAdapter()
    fitness_calc = DuplicateBatchFitness()
    algorithm = DuplicateBatchAlgorithm()

    monkeypatch.setattr(main, "_collect_optional_metrics", lambda config, adapter: {})

    best_params, best_cost, best_result = main.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    assert adapter.sim_calls == 1
    assert algorithm.results is not None
    assert len(algorithm.results) == 2
    assert algorithm.results[0].source_sim_id == algorithm.results[1].source_sim_id == 1
    assert best_params[0] == pytest.approx(0.12)
    assert best_cost == pytest.approx(0.12)
    assert best_result is not None


class ConstraintRepairAdapter(FakeParameterState):
    def __init__(self):
        self.current_params = None
        self.sim_calls = 0
        self.best_params = None
        self.best_fitness = float("inf")
        self.config = {
            "param_names": ["patch_w", "probe_p"],
            "param_units": ["mm", "mm"],
            "param_resolutions": [0.01, 0.01],
        }

    def set_parameters(self, params):
        self.current_params = np.asarray(params, dtype=float).copy()
        return True

    def simulate(self):
        self.sim_calls += 1
        self.last_sim_params = self.current_params.copy()
        freqs = np.array([55.0], dtype=float)
        s11 = np.array([-20.0], dtype=float)
        return freqs, s11, None

    def update_best(self, params, cost):
        if cost < self.best_fitness:
            self.best_fitness = cost
            self.best_params = np.asarray(params, dtype=float).copy()
            return True
        return False

    def _format_parameter_assignment(self, name, value, unit=None, resolution=None):
        numeric = float(value)
        if resolution:
            numeric = round(numeric / resolution) * resolution
        numeric = round(numeric, 4)
        return f"{numeric}{unit or ''}"


class ConstraintRepairAlgorithm:
    name = "RepairAlgo"
    is_multi_objective = False

    def __init__(self):
        self.results = None

    def suggest_population(self):
        return np.array([[1.01, 0.53]], dtype=float)

    def update(self, fitness_results):
        self.results = list(fitness_results)


def test_run_optimization_repairs_invalid_constraint_before_simulation(tmp_path, monkeypatch):
    config = {
        "task_type": "opt",
        "name": "constraint_repair",
        "parameters": [
            {
                "name": "patch_w",
                "min": 0.8,
                "max": 1.2,
                "unit": "mm",
                "resolution": 0.01,
            },
            {
                "name": "probe_p",
                "min": 0.1,
                "max": 0.8,
                "unit": "mm",
                "resolution": 0.01,
                "constraint": "probe_p <= patch_w / 2",
            },
        ],
        "target": {"freq_band": [55.0, 56.0]},
        "algorithm": {
            "method": "de",
            "max_iterations": 1,
            "early_stop_patience": 10,
        },
        "optimization": {
            "task_output_dir": str(tmp_path / "run"),
            "save_best_on_exit": False,
            "continuous_search": True,
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    param_mgr = ParameterManager(config["parameters"])
    adapter = ConstraintRepairAdapter()
    fitness_calc = DuplicateBatchFitness()
    algorithm = ConstraintRepairAlgorithm()

    monkeypatch.setattr(main, "_collect_optional_metrics", lambda config, adapter: {})

    best_params, best_cost, best_result = main.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    assert adapter.sim_calls == 1
    assert adapter.last_sim_params[0] == pytest.approx(1.01)
    assert adapter.last_sim_params[1] == pytest.approx(0.50)
    assert adapter.current_params.tolist() == [0.0, 0.0]
    assert best_params[0] == pytest.approx(1.01)
    assert best_params[1] == pytest.approx(0.50)
    assert best_cost == pytest.approx(-20.0)
    assert best_result is not None


class NonImprovingAdapter(FakeParameterState):
    def __init__(self):
        self.current_params = None
        self.sim_calls = 0
        self.best_params = None
        self.best_fitness = float("inf")
        self.config = {
            "param_names": ["x"],
            "param_units": [""],
            "param_resolutions": [0.01],
        }

    def set_parameters(self, params):
        self.current_params = np.asarray(params, dtype=float).copy()
        return True

    def simulate(self):
        self.sim_calls += 1
        freqs = np.array([55.0], dtype=float)
        s11 = np.array([float(self.current_params[0])], dtype=float)
        return freqs, s11, None

    def update_best(self, params, cost):
        if cost < self.best_fitness:
            self.best_fitness = float(cost)
            self.best_params = np.asarray(params, dtype=float).copy()
            return True
        return False


class NonImprovingAlgorithm:
    name = "NonImprovingAlgo"
    is_multi_objective = False

    def __init__(self):
        self._candidates = [
            np.array([0.1], dtype=float),
            np.array([0.9], dtype=float),
            np.array([0.8], dtype=float),
            np.array([0.7], dtype=float),
        ]
        self._idx = 0
        self.results = None

    def suggest(self):
        candidate = self._candidates[min(self._idx, len(self._candidates) - 1)]
        self._idx += 1
        return candidate.copy()

    def update(self, fitness_results):
        self.results = list(fitness_results)


def test_run_optimization_disables_early_stop_when_patience_is_zero(tmp_path, monkeypatch):
    config = {
        "task_type": "opt",
        "name": "no_early_stop",
        "parameters": [
            {
                "name": "x",
                "min": 0.0,
                "max": 1.0,
                "resolution": 0.01,
            }
        ],
        "target": {"freq_band": [55.0, 56.0]},
        "algorithm": {
            "method": "de",
            "max_iterations": 4,
            "early_stop_patience": 0,
        },
        "optimization": {
            "task_output_dir": str(tmp_path / "run"),
            "save_best_on_exit": False,
            "continuous_search": True,
        },
        "output": {
            "save_data": False,
            "plot_fitness_trend": False,
        },
        "simulator": {"hfss": {"setup_name": "Setup1"}},
    }
    param_mgr = ParameterManager(config["parameters"])
    adapter = NonImprovingAdapter()
    fitness_calc = DuplicateBatchFitness()
    algorithm = NonImprovingAlgorithm()

    monkeypatch.setattr(main, "_collect_optional_metrics", lambda config, adapter: {})

    best_params, best_cost, best_result = main.run_optimization(
        config=config,
        adapter=adapter,
        param_mgr=param_mgr,
        fitness_calc=fitness_calc,
        algorithm=algorithm,
    )

    assert adapter.sim_calls == 4
    assert best_params[0] == pytest.approx(0.1)
    assert best_cost == pytest.approx(0.1)
    assert best_result is not None
