import json
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.core import FitnessCalculator, FitnessResult, ParameterManager
from optimizer.stage_transition import restart_stage
from optimizer.algorithms import cmaes
from optimizer.algorithms.pso import PSOOptimizer


class Strategy:
    def __init__(self, initial_point, sigma, options):
        self.initial_point = initial_point
        self.popsize = 4


class Evaluator:
    def calculate(self, freqs, s11, s12, extra_metrics=None):
        cost = 10 - float(s11[0]) * 10
        return FitnessResult(cost=cost, objectives=[cost, cost * 2], valid=cost >= 5)


@pytest.mark.parametrize("method", ["de", "pso", "bo", "surrogate", "nsga2", "cmaes"])
def test_every_algorithm_restarts_with_current_scores(method, monkeypatch):
    monkeypatch.setattr(cmaes, "_load_cma", lambda: SimpleNamespace(CMAEvolutionStrategy=Strategy))
    config = {"algorithm": {"method": method, "population_size": 4, "n_candidates": 4},
              "parameters": [{"name": "x", "unit": "mm", "min": 0, "max": 1, "resolution": 0.01},
                             {"name": "y", "unit": "mm", "min": 0, "max": 1, "resolution": 0.01}],
              "target": {}, "optimization": {"initial_point": [0.1, 0.1]}}
    mgr = ParameterManager(config["parameters"])
    adapter = SimpleNamespace(config={"param_names": ["x", "y"], "param_units": ["mm", "mm"]})
    old = task_runner.create_algorithm(config, mgr)
    old.best_params, old.best_cost = np.array([0.1, 0.1]), -99999
    positions = np.array([[0.1, 0.1], [0.2, 0.2], [0.3, 0.3], [0.4, 0.4]])
    if method in {"de", "nsga2"}:
        old.population = positions.copy()
    if method == "de":
        old.fitness[:] = -99999
    if method == "pso":
        old.positions = positions.copy()
        old.personal_best_costs[:] = old.global_best_cost = -99999
    if method == "bo":
        old.preload_history(positions, np.full(4, -99999))
    if method == "nsga2":
        old.objectives = np.full((4, 2), -99999)
    cache = {}
    for index, params in enumerate(positions):
        key = task_runner._simulation_cache_key(params, mgr, adapter)
        cache[key] = {"params": params, "freqs": np.array([55, 65]), "s11": np.full(2, params[0]),
                      "s12": None, "extra_metrics": {}, "source_sim_id": index + 1}
    fresh, best, count = restart_stage(config, mgr, Evaluator(), old, cache, adapter,
                                     factory=task_runner.create_algorithm,
                                     cache_key=task_runner._simulation_cache_key)
    assert fresh is not old and count == 4
    assert best.cost == 6
    np.testing.assert_allclose(best.params, [0.4, 0.4])
    if method in {"bo", "surrogate"}:
        np.testing.assert_allclose(fresh.y_train, [9, 8, 7, 6])
    if method == "de":
        assert fresh.fitness.tolist() == [6, 8, 7, 6]
        assert fresh.best_cost == 6 and fresh.best_idx == 0
    if method == "pso":
        assert fresh.personal_best_costs.tolist() == [6, 8, 7, 6]
        assert fresh.global_best_cost == 6
    if method == "nsga2":
        assert np.all(fresh.objectives >= 6)
        assert fresh.best_result.cost == 6
        assert fresh.pareto_front
    if method == "cmaes":
        assert fresh._strategy is not old._strategy
        np.testing.assert_allclose(fresh.initial_point, [0.4, 0.4])
    assert old.best_cost < 0  # previous state is retained for audit, not modified


def test_invalid_raw_observation_does_not_become_stage_best():
    config = {"algorithm": {"method": "bo"},
              "parameters": [{"name": "x", "unit": "mm", "min": 0, "max": 1}], "target": {}}
    mgr = ParameterManager(config["parameters"])
    adapter = SimpleNamespace(config={"param_names": ["x"], "param_units": ["mm"]})
    old = task_runner.create_algorithm(config, mgr)
    raw = {("0.8mm",): {"params": np.array([0.8]), "freqs": np.array([55, 65]),
                         "s11": np.full(2, 0.8), "s12": None, "extra_metrics": {}}}
    fresh, best, count = restart_stage(config, mgr, Evaluator(), old, raw, adapter,
                                     factory=task_runner.create_algorithm,
                                     cache_key=task_runner._simulation_cache_key)
    assert best is None and count == 0
    assert fresh.best_params is None and not fresh.y_train.size


def test_pso_default_scalar_velocity_bound_is_supported():
    optimizer = PSOOptimizer([(0, 1), (0, 1)], n_particles=4)
    result = FitnessResult(cost=1)
    result.particle_idx = 0
    optimizer.update([result])
    assert np.all(np.abs(optimizer.velocities) <= 0.5)


def test_batch_ask_failure_propagates_without_scalar_fallback():
    class Broken:
        def suggest_population(self):
            raise RuntimeError("pending batch")
        def suggest(self):
            raise AssertionError("must not silently change algorithm contract")
    with pytest.raises(RuntimeError, match="pending batch"):
        task_runner._get_candidate_batch(Broken())


def test_stage_boundary_changes_reported_best_and_is_journaled(tmp_path, monkeypatch):
    from test_optimization_safeguards import Adapter, Algorithm, config
    task = config(tmp_path, method="de")
    task["algorithm"]["max_iterations"] = 1
    class Staged:
        is_multi_objective = False
        stage_index = 0
        active_stage = SimpleNamespace(name="easy", s11_target=-10, s12_target=None, freq_band=(55, 65))
        def calculate(self, *args, **kwargs):
            return FitnessResult(cost=-999 if self.stage_index == 0 else 42, s11_max=-12,
                                 stage_met=self.stage_index == 0)
        def advance_stage(self):
            self.stage_index = 1
            self.active_stage = SimpleNamespace(name="strict", s11_target=-20, s12_target=None, freq_band=(55, 65))
            return True
    evaluator = Staged()
    replacement = Algorithm()
    monkeypatch.setattr(task_runner, "create_algorithm", lambda config, mgr: replacement)
    # The helper's native DE population contract is exercised by the tests above.
    original = Algorithm()
    original.population = np.array([[0.2]])
    adapter = Adapter()
    _, cost, result = task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), evaluator, original)
    assert cost == 42 and result.cost == 42
    assert adapter.best_fitness == 42
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    transition = next(item for item in events if item["record_type"] == "stage_transition")
    assert transition["best_cost"] == 42 and transition["stage_index"] == 1
    assert adapter.active_algorithm is replacement


def test_adaptive_evaluation_is_order_independent_within_an_epoch():
    calculator = FitnessCalculator((55, 65), -20,
                                   fitness_config={"adaptive_penalty": True})
    freqs, s11 = np.array([55, 60, 65]), np.full(3, -12)
    first = calculator.calculate(freqs, s11, None)
    second = calculator.calculate(freqs, s11, None)
    assert first.cost == second.cost
    assert calculator.adaptive_scales == first.adaptive_scales == second.adaptive_scales
    assert calculator.advance_penalty_epoch([first, second])
    newer = calculator.calculate(freqs, s11, None)
    assert newer.cost > first.cost
    assert calculator.calculate(freqs, s11, None).cost == newer.cost


def test_adaptive_epoch_rebuilds_best_and_records_scales(tmp_path, monkeypatch):
    from test_optimization_safeguards import Adapter, Algorithm, config
    task = config(tmp_path)
    task["target"]["fitness"] = {"adaptive_penalty": True}
    task["algorithm"]["max_iterations"] = 1
    original = Algorithm()
    original.population = np.array([[0.2]])
    replacement = Algorithm()
    monkeypatch.setattr(task_runner, "create_algorithm", lambda config, mgr: replacement)
    calculator = FitnessCalculator((55, 65), -20, fitness_config=task["target"]["fitness"])
    adapter = Adapter()
    _, cost, result = task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), calculator, original)
    current = calculator.calculate(np.array([55, 60, 65]), np.full(3, -12), None)
    assert cost == result.cost == adapter.best_fitness == current.cost
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    epoch = next(item for item in events if item["record_type"] == "penalty_epoch_transition")
    assert epoch["adaptive_scales"] == calculator.adaptive_scales
    assert epoch["best_cost"] == cost


def test_complete_de_batch_includes_failed_evaluation_before_failure_budget_stop(tmp_path):
    from test_optimization_safeguards import Adapter, Algorithm, config
    class Partial(Adapter):
        def simulate(self):
            self.fail = self.current_params[0] > 0.5
            return super().simulate()
    class Batch(Algorithm):
        def suggest_population(self):
            return np.array([[0.2], [0.8]])
    task = config(tmp_path, max_consecutive_failures=1)
    algorithm = Batch()
    task_runner.run_optimization(task, Partial(), ParameterManager(task["parameters"]),
                                 FitnessCalculator((55, 65), -20), algorithm)
    # Both candidates were evaluated; the failed last candidate fills its slot.
    assert len(algorithm.costs) == 1
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    batch = next(item for item in events if item["record_type"] == "batch_finished")
    assert batch["complete"] and batch["algorithm_updated"] and batch["valid_candidates"] == 1


def test_all_cache_batch_still_completes_algorithm_generation(tmp_path):
    from test_optimization_safeguards import Adapter, Algorithm, ChangingEvaluator, config
    algorithm, adapter = Algorithm(), Adapter()
    task_runner.run_optimization(config(tmp_path), adapter, ParameterManager(config(tmp_path)["parameters"]),
                                 ChangingEvaluator(), algorithm)
    assert adapter.solves == 1 and algorithm.costs == [1, 2]
