import json
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer import task_runner
from optimizer.core.study import build_study_cases, build_step_sweep_values
from optimizer.sweep import run_hfss_sweep
from optimizer.validation import run_val_cases
from optimizer.tracking_port import TrackingPort


class MemoryAdapter:
    def __init__(self):
        self.baseline = {"x": "1mm", "y": "2mm"}
        self.current = dict(self.baseline)
        self.solved = []
        self.fail_at = None
        self.interrupt_at = None
        self.config = {}
        self.disconnected = False

    def connect(self):
        return True

    def disconnect(self):
        self.disconnected = True

    def capture_current_parameter_state(self):
        return dict(self.current)

    def restore_parameter_state(self, state):
        # Model the actual AEDT setter: restoring one key leaves all others alone.
        self.current.update(state)
        return True

    def set_parameter(self, name, value):
        self.current[name] = f"{float(value):g}mm"
        return True

    def simulate(self):
        self.solved.append(dict(self.current))
        if len(self.solved) == self.interrupt_at:
            raise KeyboardInterrupt()
        if len(self.solved) == self.fail_at:
            return None, None, None
        return np.array([55, 60, 65]), np.full(3, -12), np.full(3, -20)

    def get_far_field_peak_loss_band(self, **kwargs):
        raise RuntimeError("injected required far-field failure")


def config(path, task_type="sweep", **study):
    common = {"name": "workflow", "task_type": task_type,
              "optimization": {"task_output_dir": str(path)},
              "simulator": {"hfss": {}}}
    if task_type == "val":
        common.update(target={"freq_band": [55, 65], "s11_threshold": -10},
                      cases=[{"params": {"x": 3}}, {"params": {"y": 4}}])
    else:
        common["study"] = {"freq_band": [55, 65], "s11_threshold": -10,
            "variables": [{"name": "x", "start": 3, "stop": 4, "step": 1},
                          {"name": "y", "start": 5, "stop": 5, "step": 1}], **study}
    return common


def journal(path):
    return [json.loads(line) for line in (path / "cases.jsonl").read_text(encoding="utf-8").splitlines()]


def test_oat_restores_all_baseline_keys_between_variables_and_points(tmp_path):
    adapter = MemoryAdapter()
    result = run_hfss_sweep(config(tmp_path), adapter)
    assert adapter.solved == [{"x": "3mm", "y": "2mm"}, {"x": "4mm", "y": "2mm"},
                              {"x": "1mm", "y": "5mm"}]
    assert adapter.current == adapter.baseline
    assert result["status"] == "Completed"


@pytest.mark.parametrize("mode,expected", [
    ("grid", [{"x": "3mm", "y": "5mm"}, {"x": "4mm", "y": "5mm"}]),
    ("explicit", [{"x": "3mm", "y": "6mm"}, {"x": "1mm", "y": "4mm"}]),
])
def test_grid_and_explicit_cases_use_the_same_executor(tmp_path, mode, expected):
    adapter = MemoryAdapter()
    task = config(tmp_path, mode=mode)
    if mode == "explicit":
        task["study"]["cases"] = [{"params": {"x": 3, "y": 6}}, {"params": {"y": 4}}]
    result = run_hfss_sweep(task, adapter)
    assert adapter.solved == expected
    assert result["completed_points"] == 2
    assert adapter.current == adapter.baseline


@pytest.mark.parametrize("task_type", ["val", "sweep"])
def test_failed_cases_have_unique_ids_and_durable_failure_records(tmp_path, task_type):
    adapter = MemoryAdapter()
    adapter.fail_at = 1
    task = config(tmp_path, task_type)
    result = (run_val_cases if task_type == "val" else run_hfss_sweep)(task, adapter)
    finished = [row for row in journal(tmp_path) if row["record_type"] == "case_finished"]
    assert [row["case_id"] for row in finished] == list(range(1, len(finished) + 1))
    assert finished[0]["status"] == "failed"
    assert finished[1]["status"] == "completed"
    assert "result" in finished[1]
    assert result["status"] == "Failed"
    assert adapter.current == adapter.baseline


@pytest.mark.parametrize("task_type", ["val", "sweep"])
def test_required_metric_failure_cannot_be_swallowed(tmp_path, task_type):
    adapter = MemoryAdapter()
    task = config(tmp_path, task_type)
    section = task["target" if task_type == "val" else "study"]
    section["far_field"] = {"enabled": True, "required": True, "freqs": ["55GHz"]}
    result = (run_val_cases if task_type == "val" else run_hfss_sweep)(task, adapter)
    assert result["status"] == "Failed"
    assert all("far-field" in row["failure_reason"] for row in journal(tmp_path)
               if row["record_type"] == "case_finished")


@pytest.mark.parametrize("task_type", ["val", "sweep"])
def test_interrupt_keeps_completed_data_and_restores_model(tmp_path, task_type):
    adapter = MemoryAdapter()
    adapter.interrupt_at = 2
    task = config(tmp_path, task_type)
    with pytest.raises(KeyboardInterrupt):
        (run_val_cases if task_type == "val" else run_hfss_sweep)(task, adapter)
    rows = journal(tmp_path)
    assert rows[1]["status"] == "completed"
    assert rows[1]["result"]["s11"] == [-12, -12, -12]
    assert rows[3]["status"] == "cancelled"
    assert rows[-1]["status"] == "Stopped"
    assert adapter.current == adapter.baseline


def test_deadline_stops_without_running_cases(tmp_path):
    adapter = MemoryAdapter()
    task = config(tmp_path, "val")
    task["optimization"]["end_at"] = "2000-01-01T00:00:00+00:00"
    result = run_val_cases(task, adapter)
    assert result["status"] == "Stopped" and result["attempted_cases"] == 0
    assert adapter.solved == []


def test_case_journal_refuses_to_overwrite_previous_run(tmp_path):
    adapter = MemoryAdapter()
    task = config(tmp_path, "val")
    run_val_cases(task, adapter)
    original = (tmp_path / "cases.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        run_val_cases(task, adapter)
    assert (tmp_path / "cases.jsonl").read_bytes() == original


def test_baseline_restore_failure_keeps_result_and_stops_batch(tmp_path):
    adapter = MemoryAdapter()
    calls = 0
    def restore(state):
        nonlocal calls
        calls += 1
        adapter.current.update(state)
        return calls != 2
    adapter.restore_parameter_state = restore
    with pytest.raises(RuntimeError, match="baseline restore failed"):
        run_val_cases(config(tmp_path, "val"), adapter)
    rows = journal(tmp_path)
    failure = next(row for row in rows if row["record_type"] == "case_restore_failed")
    assert failure["result"]["s11"] == [-12, -12, -12]
    assert len(adapter.solved) == 1


def test_sweep_preserves_extra_trace_configuration(tmp_path):
    adapter = MemoryAdapter()
    adapter.get_trace_data = lambda expression: (np.array([55, 60, 65]), np.full(3, 0.9))
    task = config(tmp_path)
    task["simulator"]["hfss"]["results"] = {"extra_traces": [{"name": "efficiency", "expression": "Efficiency"}]}
    run_hfss_sweep(task, adapter)
    completed = next(row for row in journal(tmp_path) if row["record_type"] == "case_finished")
    assert completed["result"]["traces"]["efficiency"]["values"] == [0.9, 0.9, 0.9]


def test_output_failure_is_not_recorded_as_completed(monkeypatch, tmp_path):
    import optimizer.validation as validation
    def fail_write(*args):
        raise OSError("injected report failure")
    monkeypatch.setattr(validation, "_write_jsonl", fail_write)
    with pytest.raises(OSError, match="report failure"):
        validation.run_val_cases(config(tmp_path, "val"), MemoryAdapter())
    assert journal(tmp_path)[-1]["status"] == "Failed"
    assert journal(tmp_path)[1]["result"]["s11"] == [-12, -12, -12]


def test_all_failed_validation_returns_failure_exit_code_and_disconnects(monkeypatch, tmp_path):
    adapter = MemoryAdapter()
    task = config(tmp_path, "val")
    task["cases"] = [{"params": {"unknown": 1}}]
    monkeypatch.setattr(task_runner, "create_adapter", lambda *args: adapter)
    assert task_runner.run_task(task, task_output_dir=tmp_path, task_work_dir=tmp_path / "work") == 1
    assert adapter.disconnected


def test_small_sweep_steps_keep_precision_and_explosive_grids_are_rejected():
    assert build_step_sweep_values(0.00001, 0.00003, 0.00001) == [0.00001, 0.00002, 0.00003]
    with pytest.raises(ValueError, match="exceeds"):
        build_step_sweep_values(0, 1, 1e-10)
    with pytest.raises(ValueError, match="max_cases"):
        build_study_cases({"mode": "grid", "max_cases": 3, "variables": [
            {"name": "x", "start": 0, "stop": 1, "step": 1},
            {"name": "y", "start": 0, "stop": 1, "step": 1}]})


def test_tracking_port_preserves_coordinates_and_restores_after_failure():
    original = {"Start": ["2mm", "3mm", "1mm"], "End": ["4mm", "3mm", "1mm"]}
    boundary = SimpleNamespace(name="Port1", auto_update=True,
        props={"Modes": {"Mode1": {"IntLine": {k: list(v) for k, v in original.items()}}}},
        update=lambda: True)
    adapter = SimpleNamespace(app=SimpleNamespace(boundaries=[boundary]))
    tracking = TrackingPort(adapter, {"height_parameter": "h"}, {"h": "1mm"})
    tracking.apply({"h": 2})
    line = boundary.props["Modes"]["Mode1"]["IntLine"]
    assert line["Start"][:2] == ["2mm", "3mm"]
    assert line["End"][:2] == ["4mm", "3mm"]
    assert "h" in line["Start"][2]
    tracking.restore()
    assert line == original and boundary.auto_update is True
