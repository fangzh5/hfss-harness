"""Failed evaluations complete a batch without becoming observations or best points."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.algorithms import BOOptimizer, DEOptimizer, NSGA2Optimizer, PSOOptimizer, SurrogateOptimizer
from optimizer.core import FitnessCalculator, FitnessResult, ParameterManager
from test_opt_case_executor import StateAdapter
from test_optimization_safeguards import config


def result(point, index, valid=True, cost=10.0):
    item = FitnessResult(cost=cost, objectives=[cost, cost], constraint_violation=2 if valid else 0,
                         valid=valid, source_sim_id=index + 1 if valid else None)
    item.params = np.asarray(point, dtype=float).copy()
    item.individual_idx = item.particle_idx = index
    return item


@pytest.mark.parametrize("factory", [
    lambda: DEOptimizer([(0, 1)], pop_size=4),
    lambda: PSOOptimizer([(0, 1)], n_particles=4),
    lambda: BOOptimizer([(0, 1)]),
    lambda: SurrogateOptimizer([(0, 1)], n_candidates=4),
])
def test_failed_low_scores_never_enter_best_or_training_data(factory):
    algorithm = factory()
    if hasattr(algorithm, "trial_population"):
        points = algorithm.trial_population
    elif hasattr(algorithm, "positions"):
        points = algorithm.positions
    elif hasattr(algorithm, "base_opt"):
        points = algorithm.base_opt.trial_population
    else:
        points = np.array([[0.1], [0.2], [0.3], [0.4]])
    batch = [result(point, idx, valid=idx == 0, cost=10 if idx == 0 else -1000) for idx, point in enumerate(points)]
    algorithm.update(batch)
    best_cost = algorithm.global_best_cost if isinstance(algorithm, PSOOptimizer) else algorithm.best_cost
    assert best_cost == 10
    if hasattr(algorithm, "y_train"):
        assert algorithm.y_train.tolist() == [10]
    if isinstance(algorithm, DEOptimizer):
        assert np.isinf(algorithm.fitness[1:]).all()
    if isinstance(algorithm, PSOOptimizer):
        assert np.isinf(algorithm.personal_best_costs[1:]).all()


def test_nsga_invalid_candidates_never_enter_front_or_representative_across_generations():
    algorithm = NSGA2Optimizer([(0, 1)], pop_size=4)
    first = algorithm.suggest_population()
    algorithm.update([result(point, idx, idx == 0, 10 if idx == 0 else -1000) for idx, point in enumerate(first)])
    assert algorithm.best_result.valid
    assert algorithm.best_result.constraint_violation == 2  # valid but infeasible still beats failed solves
    assert algorithm.best_source_sim_id == 1
    assert len(algorithm.pareto_front) == 1 and algorithm.pareto_front[0]["source_sim_id"] == 1
    algorithm.update([result(point, idx, False, -2000) for idx, point in enumerate(algorithm.suggest_population())])
    assert algorithm.best_result.valid and algorithm.best_source_sim_id == 1
    assert algorithm.best_result.cost == 10  # full evaluation data survives parent selection
    assert all(item["source_sim_id"] == 1 for item in algorithm.pareto_front)


def test_nsga_all_failed_initial_batch_has_no_best_and_can_generate_another_batch():
    algorithm = NSGA2Optimizer([(0, 1)], pop_size=4)
    algorithm.update([result(point, idx, False, -1000) for idx, point in enumerate(algorithm.suggest_population())])
    assert algorithm.best_params is None and algorithm.best_result is None
    assert algorithm.pareto_front == [] and not algorithm.valid_individuals.any()
    points = algorithm.suggest_population()
    assert points.shape == (4, 1) and np.isfinite(points).all()
    algorithm.update([result(point, idx) for idx, point in enumerate(points)])
    assert algorithm.best_result.valid and algorithm.pareto_front


def test_cma_failure_penalty_is_strictly_worse_than_large_valid_costs():
    batch = [result([0.2], 0, True, 1e20), result([0.3], 1, False, -1)]
    task_runner._penalize_failed_cma_results(batch)
    assert np.isfinite(batch[1].cost) and batch[1].cost > batch[0].cost


def test_cma_failure_penalty_rejects_unrepresentable_finite_value():
    batch = [result([0.2], 0, True, np.finfo(float).max), result([0.3], 1, False, -1)]
    with pytest.raises(ValueError, match="finite CMA failure penalty"):
        task_runner._penalize_failed_cma_results(batch)


def test_all_valid_cma_batch_requires_no_failure_penalty():
    batch = [result([0.2], 0, True, np.finfo(float).max)]
    task_runner._penalize_failed_cma_results(batch)
    assert batch[0].cost == np.finfo(float).max


class CapturingBatch:
    name = "Captured batch"
    is_multi_objective = False

    def __init__(self):
        self.batches = []

    def suggest_population(self):
        return np.array([[0.2], [0.4]]) if not self.batches else np.array([[0.6], [0.8]])

    def update(self, results):
        self.batches.append(results)


def execute(task, adapter, algorithm):
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]),
                                 FitnessCalculator((55, 65), -20), algorithm)


def test_runner_submits_mixed_failure_batch_once_and_proceeds_to_next_generation(tmp_path):
    task = config(tmp_path)
    adapter, algorithm = StateAdapter(), CapturingBatch()
    adapter.fail_first = True
    execute(task, adapter, algorithm)
    assert len(algorithm.batches) == 2
    first = algorithm.batches[0]
    assert [item.individual_idx for item in first] == [0, 1]
    assert [item.particle_idx for item in first] == [0, 1]
    assert not first[0].valid and first[1].valid
    assert "injected solve failure" in first[0].failure_reason
    assert [item["x"] for item in adapter.observed] == pytest.approx([0.2, 0.4, 0.6, 0.8])
    assert adapter.last_task_outcome["failures"] == 1
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    batches = [item for item in events if item["record_type"] == "batch_finished"]
    assert [item["valid_candidates"] for item in batches] == [1, 2]
    assert all(item["complete"] and item["algorithm_updated"] for item in batches)


def test_incomplete_batch_at_failure_budget_is_not_submitted(tmp_path):
    task = config(tmp_path, max_consecutive_failures=1)
    adapter, algorithm = StateAdapter(), CapturingBatch()
    adapter.fail_first = True
    execute(task, adapter, algorithm)
    assert algorithm.batches == [] and len(adapter.observed) == 1
    assert adapter.last_task_outcome["termination_reason"] == "failure_budget"
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    batch = next(item for item in events if item["record_type"] == "batch_finished")
    assert not batch["complete"] and not batch["algorithm_updated"]


def test_all_failed_batch_advances_candidates_but_is_bounded_by_failure_budget(tmp_path):
    task = config(tmp_path, max_consecutive_failures=3)
    task["algorithm"]["max_iterations"] = 10
    adapter, algorithm = StateAdapter(), CapturingBatch()
    adapter.fail = True
    execute(task, adapter, algorithm)
    assert len(algorithm.batches) == 1 and not any(item.valid for item in algorithm.batches[0])
    assert [item["x"] for item in adapter.observed] == pytest.approx([0.2, 0.4, 0.6])
    assert adapter.best_params is None and adapter.last_task_outcome["status"] == "Failed"
    assert adapter.last_task_outcome["termination_reason"] == "failure_budget"
    assert adapter.last_task_outcome["solve_attempts"] == 3


def test_all_failed_complete_batch_consumes_one_generation_and_never_completes_successfully(tmp_path):
    task = config(tmp_path)
    task["algorithm"]["max_iterations"] = 1
    adapter, algorithm = StateAdapter(), CapturingBatch()
    adapter.fail = True
    execute(task, adapter, algorithm)
    assert len(algorithm.batches) == 1 and len(adapter.observed) == 2
    assert adapter.last_task_outcome["termination_reason"] == "max_iters"
    assert adapter.last_task_outcome["status"] == "Failed" and adapter.best_params is None


def test_constraints_failure_fills_its_batch_slot_without_solving(tmp_path):
    task = config(tmp_path)
    task["algorithm"]["max_iterations"] = 1
    adapter, algorithm = StateAdapter(), CapturingBatch()
    manager = ParameterManager(task["parameters"])
    manager.check_constraints = lambda point: point[0] < 0.3
    task_runner.run_optimization(task, adapter, manager, FitnessCalculator((55, 65), -20), algorithm)
    assert len(algorithm.batches) == 1
    assert [item.valid for item in algorithm.batches[0]] == [True, False]
    assert algorithm.batches[0][1].failure_reason == "constraints"
    assert len(adapter.observed) == 1 and adapter.last_task_outcome["failures"] == 1


def test_invalid_cached_evaluation_fills_its_batch_slot(tmp_path):
    class Repeat(CapturingBatch):
        def suggest_population(self):
            return np.array([[0.2], [0.2]])

    class RejectCache(FitnessCalculator):
        calls = 0

        def calculate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                return FitnessResult(cost=1e12, valid=False, failure_reason="invalid cache evaluation")
            return super().calculate(*args, **kwargs)

    task = config(tmp_path)
    task["algorithm"]["max_iterations"] = 1
    adapter, algorithm = StateAdapter(), Repeat()
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), RejectCache((55, 65), -20), algorithm)
    assert len(algorithm.batches) == 1
    assert [item.valid for item in algorithm.batches[0]] == [True, False]
    assert len(adapter.observed) == 1 and adapter.last_task_outcome["failures"] == 1


def test_surrogate_ei_generates_a_finite_candidate_after_training():
    algorithm = SurrogateOptimizer([(0, 1)], n_initial=0, n_candidates=4)
    algorithm.gpr.optimizer = None
    algorithm.add_training_data(np.array([[0.1], [0.7]]), np.array([3.0, 1.0]))
    algorithm.train_surrogate()
    assert algorithm.is_trained
    assert np.isfinite(algorithm.expected_improvement(np.array([[0.2], [0.5]]))).all()
    point = algorithm.suggest()
    assert point.shape == (1,) and np.isfinite(point).all() and 0 <= point[0] <= 1


def test_nsga_partial_stop_selects_only_evaluated_valid_points_without_updating_population():
    algorithm = NSGA2Optimizer([(0, 1)], pop_size=4)
    population = algorithm.population.copy()
    offspring = algorithm.offspring_population.copy()
    good = result([0.2], 0)
    good.target_met = True
    algorithm.finalize_partial_batch([good, result([0.4], 1, False, -999)])
    np.testing.assert_array_equal(algorithm.population, population)
    np.testing.assert_array_equal(algorithm.offspring_population, offspring)
    assert algorithm.objectives is None  # no complete generation was committed
    assert algorithm.best_result.valid and algorithm.best_result.target_met
    np.testing.assert_array_equal(algorithm.best_params, [0.2])
    assert len(algorithm.pareto_front) == 1 and algorithm.pareto_front[0]["source_sim_id"] == 1


@pytest.mark.parametrize("stop_on_target", [False, True])
def test_nsga_runner_retains_partial_best_and_can_export_it_on_stop(tmp_path, stop_on_target):
    task = config(tmp_path, method="nsga2", save_best_on_exit=True, stop_on_target=stop_on_target)
    threshold = -10 if stop_on_target else -20
    task["target"].update(s11_threshold=threshold, multi_objective={"enabled": True})
    if not stop_on_target:
        task["algorithm"]["max_simulations"] = 1
    calculator = FitnessCalculator((55, 65), threshold, multi_objective_config={"enabled": True})
    adapter = StateAdapter()
    algorithm = NSGA2Optimizer([(0, 1)], pop_size=4, initial_population=np.array([[0.2], [0.4], [0.6], [0.8]]))
    algorithm.update = lambda _: pytest.fail("incomplete generation was submitted")
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), calculator, algorithm)
    outcome = adapter.last_task_outcome
    assert outcome["best_params"] == pytest.approx([0.2])
    assert outcome["export_verified"] and adapter.saves == 1
    assert outcome["simulations"] == 1 and outcome["export_verification_solve_attempts"] == 1
    assert adapter.solves == 2 and len(adapter.observed) == 2
    assert outcome["termination_reason"] == ("target_met" if stop_on_target else "max_simulations")
    assert outcome["status"] == ("Completed" if stop_on_target else "Stopped")
    assert outcome["target_met"] == stop_on_target
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert any(item["record_type"] == "partial_batch_best_selected" and item["source_sim_id"] == 1 for item in events)
    batch = next(item for item in events if item["record_type"] == "batch_finished")
    assert not batch["complete"] and not batch["algorithm_updated"] and batch["valid_candidates"] == 1


def test_target_met_in_partial_scalar_batch_stops_without_requesting_another_batch(tmp_path):
    task = config(tmp_path)
    task["target"]["s11_threshold"] = -10
    adapter, algorithm = StateAdapter(), CapturingBatch()
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), FitnessCalculator((55, 65), -10), algorithm)
    assert algorithm.batches == [] and len(adapter.observed) == 1
    assert adapter.last_task_outcome["termination_reason"] == "target_met"
    assert adapter.last_task_outcome["status"] == "Completed"
