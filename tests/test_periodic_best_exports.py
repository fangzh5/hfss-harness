import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.core import FitnessCalculator, ParameterManager
from optimizer.task_config import TaskConfigError, validate_task_config
from test_opt_case_executor import StateAdapter, Sequential
from test_optimization_safeguards import config, Algorithm


class SnapshotAdapter(StateAdapter):
    def __init__(self):
        super().__init__()
        self.snapshots = []

    def simulate(self):
        self.solves += 1
        self.observed.append(self.state.copy())
        # Increasing x is worse, so the interval's latest case is not the best.
        return np.array([55, 60, 65]), np.full(3, -15 + 10 * self.state["x"]), None

    def save_best_result(self, **kwargs):
        self.saves += 1
        if not self.save_ok:
            return False
        assert np.array_equal(self.current_params, self.best_params)
        path = Path(kwargs.get("output_path") or Path(kwargs["output_dir"]) / "final_best.aedt")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.state, stream)
        self.snapshots.append((path, self.state.copy(), self.solves))
        return True


def run(task, adapter, algorithm=None):
    return task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]),
        FitnessCalculator((55, 65), -20), algorithm or Sequential())


def events(path):
    return [json.loads(x) for x in (path / "cases.jsonl").read_text().splitlines()]


def test_interval_exports_best_and_retains_each_snapshot_and_final_work_state(tmp_path):
    adapter = SnapshotAdapter()
    task = config(tmp_path, save_interval=2, save_best_on_exit=True)
    task["algorithm"]["max_iterations"] = 4
    run(task, adapter)
    assert [x[0].name for x in adapter.snapshots] == ["best_after_2_sim.aedt", "best_after_4_sim.aedt", "final_best.aedt"]
    assert all(x[1]["x"] == pytest.approx(.2) for x in adapter.snapshots)
    assert all(json.loads(x[0].read_text()) == x[1] for x in adapter.snapshots)
    assert adapter.state == adapter.snapshots[-1][1]
    summary = json.loads((tmp_path / "optimization_summary.json").read_text())
    assert summary["solve_attempts"] == summary["simulations"] == 4
    assert summary["export_verification_solve_attempts"] == 3
    assert summary["total_solve_attempts"] == adapter.solves == 7
    assert len(summary["periodic_exports"]) == 2
    e = events(tmp_path)
    case_ids = [x["case_id"] for x in e if x["record_type"] == "case_started"]
    assert len(case_ids) == len(set(case_ids))
    assert [x["search_simulations"] for x in e if x["record_type"] == "best_model_exported"] == [2, 4]
    assert e[-1]["status"] == "Completed"


def test_interval_zero_disables_periodic_exports_but_keeps_final_best(tmp_path):
    adapter = SnapshotAdapter()
    task = config(tmp_path, save_interval=0, save_best_on_exit=True)
    task["algorithm"]["max_iterations"] = 4
    run(task, adapter)
    assert adapter.solves == 5 and len(adapter.snapshots) == 1
    assert adapter.snapshots[0][0].name == "final_best.aedt"


def test_cache_hits_do_not_trigger_repeated_periodic_exports(tmp_path):
    adapter = SnapshotAdapter()
    task = config(tmp_path, method="cmaes", save_interval=1, save_best_on_exit=False)
    task["algorithm"]["max_iterations"] = 4
    run(task, adapter, Algorithm())
    assert adapter.solves == 2 and len(adapter.snapshots) == 1
    assert adapter.snapshots[0][0].name == "best_after_1_sim.aedt"
    assert len([x for x in events(tmp_path) if x.get("status") == "cache_reused"]) == 3
    assert adapter.state["x"] == 0  # periodic export returns to ongoing search baseline


def test_periodic_save_failure_fails_task_and_preserves_search_evidence(tmp_path):
    adapter = SnapshotAdapter()
    adapter.save_ok = False
    with pytest.raises(RuntimeError, match="Periodic best project could not be saved"):
        run(config(tmp_path, save_interval=2), adapter)
    assert adapter.state["x"] == 0 and adapter._optimization_finished
    assert len([x for x in events(tmp_path) if x.get("case_role") == "optimization" and x.get("status") == "completed"]) == 2
    assert events(tmp_path)[-1]["status"] == "Failed"
    assert json.loads((tmp_path / "optimization_summary.json").read_text())["status"] == "Failed"


def test_time_reserve_skips_periodic_export_and_records_why(tmp_path, monkeypatch):
    adapter = SnapshotAdapter()
    task = config(tmp_path, save_interval=2, save_best_on_exit=False)
    monkeypatch.setattr(task_runner, "budget_exhausted", lambda *args: adapter.solves >= 2)
    run(task, adapter)
    assert adapter.solves == 2 and not adapter.snapshots
    skipped = [x for x in events(tmp_path) if x["record_type"] == "best_model_export_skipped"]
    assert len(skipped) == 1 and skipped[0]["reason"] == "time_budget"


def test_multiobjective_interval_waits_for_population_representative(tmp_path):
    adapter = SnapshotAdapter()
    class Calculator:
        is_multi_objective = True
        def calculate(self, freqs, s11, s12, extra_metrics=None):
            return task_runner.FitnessResult(cost=float(s11[0] + 15), s11_max=float(s11[0]))
    class Population:
        is_multi_objective = True
        name = "Population"
        def suggest_population(self):
            return np.array([[.2], [.4], [.6]])
        def update(self, results):
            self.best_result = min(results, key=lambda x: x.cost)
            self.best_params = self.best_result.params
            self.best_cost = self.best_result.cost
            self.best_source_sim_id = self.best_result.source_sim_id
        def get_pareto_front(self):
            return []
    task = config(tmp_path, method="nsga2", save_interval=2, save_best_on_exit=False)
    task["algorithm"]["max_iterations"] = 1
    task["output"]["plot_fitness_trend"] = False
    task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]), Calculator(), Population())
    assert [x[0].name for x in adapter.snapshots] == ["best_after_3_sim.aedt"]
    assert adapter.snapshots[0][1]["x"] == pytest.approx(.2)
    assert adapter.solves == 4


@pytest.mark.parametrize("value", [-1, 1.5, "10", True, None])
def test_invalid_save_interval_rejected_before_task_launch(tmp_path, value):
    with pytest.raises(TaskConfigError, match="save_interval"):
        validate_task_config(config(tmp_path, save_interval=value))


@pytest.mark.parametrize("close_desktop", [True, False])
def test_finished_optimization_disconnect_does_not_fit_or_save_work_model(monkeypatch, close_desktop):
    adapter = HFSSAdapter({"close_desktop": close_desktop, "close_projects": True})
    adapter._optimization_finished = True
    calls = []
    adapter.app = SimpleNamespace(
        modeler=SimpleNamespace(fit_all=lambda: pytest.fail("view changed after optimization")),
        save_project=lambda: pytest.fail("work model saved after optimization"),
        close_desktop=lambda: calls.append("close") or True,
        release_desktop=lambda **kw: calls.append(kw) or True)
    monkeypatch.setattr("optimizer.adapters.hfss_adapter.time.sleep", lambda seconds: None)
    monkeypatch.setattr(adapter, "_cleanup_temp_copy", lambda: calls.append("cleanup"))
    adapter.disconnect()
    assert calls == (["close", "cleanup"] if close_desktop else [{"close_projects": True, "close_desktop": False}, "cleanup"])
