import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.core import FitnessResult, ParameterManager
from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.results import TraceData, ResultBundle
from fake_parameter_state import FakeParameterState


class Adapter(FakeParameterState):
    def __init__(self):
        self.config = {"param_names": ["x"], "param_units": ["mm"]}
        self.current_params = None
        self.best_params = None
        self.best_fitness = float("inf")
        self.fail = False
        self.saves = 0
        self.solves = 0
        self.save_ok = True

    def set_parameters(self, params):
        self.current_params = params.copy()
        return True

    def simulate(self):
        self.solves += 1
        if self.fail:
            return None, None, None
        return np.array([55, 60, 65]), np.full(3, -12), None

    def update_best(self, params, cost):
        if cost < self.best_fitness:
            self.best_params, self.best_fitness = params.copy(), cost
            return True
        return False

    def save_best_result(self, **kwargs):
        self.saves += 1
        return self.save_ok


class Algorithm:
    name = "Constant"
    is_multi_objective = False

    def __init__(self):
        self.costs = []

    def suggest_population(self):
        return np.array([[0.2]])

    def update(self, results):
        self.costs.append(results[0].cost)


class ChangingEvaluator:
    is_multi_objective = False
    active_stage = SimpleNamespace(name="final", s11_target=-20, s12_target=None, freq_band=(55, 65))

    def __init__(self):
        self.calls = 0

    def calculate(self, *args, **kwargs):
        self.calls += 1
        return FitnessResult(cost=float(self.calls), s11_max=-12)

    def advance_stage(self):
        return False


def config(path, method="de", **options):
    return {"name": "safeguards", "task_type": "opt",
        "parameters": [{"name": "x", "min": 0, "max": 1, "resolution": 0.01}],
        "target": {"freq_band": [55, 65], "s11_threshold": -20},
        "algorithm": {"method": method, "max_iterations": 2, "early_stop_patience": 0},
        "optimization": {"task_output_dir": str(path), "save_best_on_exit": False, **options},
        "output": {"save_data": False, "plot_fitness_trend": False},
        "simulator": {"hfss": {"setup_name": "Setup1"}}}


def run(task, adapter=None, algorithm=None, evaluator=None):
    adapter, algorithm, evaluator = adapter or Adapter(), algorithm or Algorithm(), evaluator or ChangingEvaluator()
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), evaluator, algorithm)
    return adapter, algorithm, evaluator


def test_persistent_failure_is_bounded_even_without_deadline(tmp_path):
    adapter = Adapter()
    adapter.fail = True
    task = config(tmp_path, max_consecutive_failures=3)
    task["algorithm"]["max_iterations"] = 10  # failure budget precedes the generation budget
    run(task, adapter)
    assert adapter.solves == 3
    summary = json.loads((tmp_path / "optimization_summary.json").read_text())
    assert summary["status"] == "Failed"
    assert summary["termination_reason"] == "failure_budget"
    assert summary["attempts"] == 3 and summary["failures"] == 3


def test_failed_solve_consumes_simulation_budget(tmp_path):
    adapter = Adapter()
    adapter.fail = True
    task = config(tmp_path)
    task["algorithm"]["max_simulations"] = 1
    run(task, adapter)
    assert adapter.solves == 1
    assert adapter.last_task_outcome["solve_attempts"] == 1
    assert adapter.last_task_outcome["status"] == "Failed"


def test_cache_reevaluates_raw_results_using_current_evaluator(tmp_path):
    adapter, algorithm, evaluator = run(config(tmp_path, method="cmaes"))
    assert adapter.solves == 1
    assert algorithm.costs == [1, 2]
    assert evaluator.calls == 2


def test_repeated_cached_candidates_have_a_finite_attempt_budget(tmp_path):
    task = config(tmp_path, max_attempts=3)
    task["algorithm"]["max_iterations"] = 100
    adapter, _, _ = run(task)
    assert adapter.solves == 1
    assert adapter.last_task_outcome["termination_reason"] == "attempt_budget"
    assert adapter.last_task_outcome["attempts"] == 3


def test_failed_final_save_is_a_failed_task_and_final_solve_runs_once(tmp_path):
    adapter = Adapter()
    adapter.save_ok = False
    task = config(tmp_path, method="cmaes", save_best_on_exit=True)
    task["algorithm"]["max_iterations"] = 1
    with pytest.raises(RuntimeError, match="could not be saved"):
        run(task, adapter)
    assert adapter.solves == 2  # one candidate and one complete final verification
    assert adapter.saves == 1
    summary = json.loads((tmp_path / "optimization_summary.json").read_text())
    assert summary["status"] == "Failed"
    dashboard = json.loads((tmp_path / "opt_dashboard_state.json").read_text())
    assert dashboard["status"]["label"] == "Failed"


def test_algorithm_update_failure_is_not_swallowed(tmp_path):
    algorithm = Algorithm()
    def fail_update(results):
        raise RuntimeError("injected tell failure")
    algorithm.update = fail_update
    with pytest.raises(RuntimeError, match="Algorithm update failed"):
        run(config(tmp_path), algorithm=algorithm)
    assert json.loads((tmp_path / "optimization_summary.json").read_text())["status"] == "Failed"


def test_adapter_save_requires_success_and_never_resolves_again(tmp_path):
    adapter = HFSSAdapter({"project_path": str(tmp_path / "source.aedt")})
    adapter.work_project_path = str(tmp_path / "work.aedt")
    adapter.current_params = adapter.best_params = np.array([0.2])
    adapter.capture_current_parameter_state = lambda: {"x": "0.2mm"}
    adapter.last_result_bundle = ResultBundle({"s11": TraceData("dB(S(1,1))", np.array([55, 65]),
                                              np.array([-12, -12]))},
        {"parameters": {"x": "0.2mm"}, "solved_this_call": True})
    calls = []
    def save():
        calls.append("save_work_project")
        return False
    adapter.app = SimpleNamespace(save_project=save)
    assert not adapter.save_best_result(output_path=str(tmp_path / "best.aedt"))
    assert calls == ["save_work_project"]
    def success():
        Path(adapter.work_project_path).write_bytes(b"verified best model")
        return True
    adapter.app.save_project = success
    assert adapter.save_best_result(output_path=str(tmp_path / "best.aedt"))
    # Restore/disconnect may save the active work project again. The best snapshot
    # must retain its solved point and must not become that active project.
    Path(adapter.work_project_path).write_bytes(b"restored baseline model")
    assert (tmp_path / "best.aedt").read_bytes() == b"verified best model"
    assert not adapter.save_best_result(output_path=str(tmp_path / "best.aedt"))


def test_best_snapshot_rejects_direct_source_and_mutation_during_save(tmp_path):
    adapter = HFSSAdapter({"project_path": str(tmp_path / "source.aedt")})
    adapter.work_project_path = adapter.original_project_path
    adapter.current_params = adapter.best_params = np.array([0.2])
    state = {"x": "0.2mm"}
    adapter.capture_current_parameter_state = lambda: state.copy()
    adapter.last_result_bundle = ResultBundle(
        {"s11": TraceData("dB(S(1,1))", np.array([55, 65]), np.array([-12, -12]))},
        {"parameters": state.copy(), "solved_this_call": True})
    def save():
        Path(adapter.work_project_path).write_bytes(b"model")
        state["x"] = "0.1mm"
        return True
    adapter.app = SimpleNamespace(save_project=save)
    assert not adapter.save_best_result(output_path=str(tmp_path / "best.aedt"))
    assert not Path(adapter.original_project_path).exists()
    adapter.work_project_path = str(tmp_path / "work.aedt")
    assert not adapter.save_best_result(output_path=str(tmp_path / "best.aedt"))
    assert not (tmp_path / "best.aedt").exists()
