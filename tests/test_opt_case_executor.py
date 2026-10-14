import json

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.core import FitnessCalculator, ParameterManager
from test_optimization_safeguards import Adapter, config


class StateAdapter(Adapter):
    def __init__(self):
        super().__init__()
        self.config["fixed_parameters"] = {"fixed": 3}
        self.state = {"x": 0, "other": 1, "$project": 2, "fixed": 0}
        self.observed = []
        self.fail_first = False
        self.interrupt_second = False
        self.fail_restore = False

    def capture_current_parameter_state(self, names=None):
        return self.state.copy() if names is None else {name: self.state[name] for name in names}

    def restore_parameter_state(self, values):
        if self.fail_restore:
            return False
        self.state.update(values)
        self.current_params = np.array([self.state["x"]])
        return True

    def set_parameters(self, params):
        self.current_params = params.copy()
        self.state["x"] = float(params[0])
        self.state.update(self.config["fixed_parameters"])
        return True

    def simulate(self):
        self.observed.append(self.state.copy())
        self.state["other"] = 999  # model backend side effect, restored after each case
        if self.interrupt_second and len(self.observed) == 2:
            raise KeyboardInterrupt()
        if self.fail_first and len(self.observed) == 1:
            raise RuntimeError("injected solve failure")
        return super().simulate()


class Sequential:
    name = "Sequential"
    is_multi_objective = False

    def __init__(self):
        self.index = 0

    def suggest(self):
        point = np.array([0.2 + self.index * 0.2])
        self.index += 1
        return point

    def update(self, results):
        pass


def execute(task, adapter):
    return task_runner.run_optimization(task, adapter, ParameterManager(task["parameters"]),
                                        FitnessCalculator((55, 65), -20), Sequential())


def test_optimizer_restores_full_baseline_and_applies_fixed_values_per_case(tmp_path):
    adapter = StateAdapter()
    baseline = adapter.state.copy()
    execute(config(tmp_path), adapter)
    assert [item["x"] for item in adapter.observed] == pytest.approx([0.2, 0.4])
    assert all(item["other"] == 1 and item["$project"] == 2 and item["fixed"] == 3
               for item in adapter.observed)
    assert adapter.state == baseline
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert len([item for item in events if item["record_type"] == "case_started"]) == 2
    completed = [item for item in events if item["record_type"] == "case_finished"]
    assert len(completed) == 2 and all(item["evaluation"]["valid"] for item in completed)


def test_solve_exception_is_an_isolated_failed_case_and_next_case_uses_baseline(tmp_path):
    adapter = StateAdapter()
    adapter.fail_first = True
    baseline = adapter.state.copy()
    execute(config(tmp_path), adapter)
    assert adapter.state == baseline
    assert len(adapter.observed) == 3  # two successful iterations after the first failure
    assert all(item["other"] == 1 for item in adapter.observed)
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    failed = next(item for item in events if item.get("failure_phase") == "solve")
    assert failed["status"] == "failed" and "injected solve failure" in failed["failure_reason"]
    assert adapter.last_task_outcome["failures"] == 1
    assert adapter.last_task_outcome["solve_attempts"] == 3


def test_interruption_restores_baseline_and_keeps_completed_case(tmp_path):
    adapter = StateAdapter()
    adapter.interrupt_second = True
    baseline = adapter.state.copy()
    with pytest.raises(KeyboardInterrupt):
        execute(config(tmp_path), adapter)
    assert adapter.state == baseline
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert any(item.get("status") == "completed" for item in events)
    assert any(item.get("status") == "cancelled" for item in events)
    assert events[-1]["record_type"] == "task_finished" and events[-1]["status"] == "Stopped"


def test_restore_failure_stops_optimization_and_records_failed_task(tmp_path):
    adapter = StateAdapter()
    original_simulate = adapter.simulate
    def simulate():
        result = original_simulate()
        adapter.fail_restore = True
        return result
    adapter.simulate = simulate
    with pytest.raises(RuntimeError, match="restore failed"):
        execute(config(tmp_path), adapter)
    assert len(adapter.observed) == 1
    summary = json.loads((tmp_path / "optimization_summary.json").read_text())
    assert summary["status"] == "Failed" and "restore_failure" in summary
    dashboard = json.loads((tmp_path / "opt_dashboard_state.json").read_text())
    assert dashboard["status"]["label"] == "Failed"
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert any(item["record_type"] == "case_restore_failed" and "result" in item for item in events)


def test_final_verification_is_journaled_once_without_restoring_after_save(tmp_path):
    adapter = StateAdapter()
    saved_state = {}
    original_save = adapter.save_best_result
    def save(**kwargs):
        saved_state.update(adapter.state)
        result = original_save(**kwargs)
        # Any restoration after this final save violates the requested lifecycle.
        adapter.restore_parameter_state = lambda values: pytest.fail("restore after final best save")
        return result
    adapter.save_best_result = save
    task = config(tmp_path, save_best_on_exit=True)
    task["algorithm"]["max_iterations"] = 1
    execute(task, adapter)
    assert adapter.solves == 2 and adapter.saves == 1
    assert adapter.state == saved_state and adapter.state["x"] == pytest.approx(0.2)
    assert adapter._optimization_finished and adapter._optimization_export_saved
    events = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    final = [item for item in events if item.get("case_role") == "export_verification"]
    assert len(final) == 2 and [item["record_type"] for item in final] == ["case_started", "case_finished"]
    assert final[-1]["status"] == "completed"
    assert events[-1]["record_type"] == "task_finished"


def test_adapter_without_baseline_contract_cannot_start_optimization(tmp_path):
    adapter = Adapter()
    adapter.capture_current_parameter_state = None
    with pytest.raises(ValueError, match="complete parameter capture/restore"):
        execute(config(tmp_path), adapter)
    assert adapter.solves == 0
