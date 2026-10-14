from types import SimpleNamespace

import numpy as np
import pytest

from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.metrics import collect_geometry_snapshot
from optimizer.sweep import run_hfss_sweep
from test_case_executor_workflows import MemoryAdapter, config, journal


class GeometryAdapter(MemoryAdapter):
    def __init__(self, broken_restore=False):
        super().__init__()
        self.cad_x = 1.0
        self.broken_restore = broken_restore

    def set_parameter(self, name, value):
        result = super().set_parameter(name, value)
        if name == "x":
            self.cad_x = float(value)
        return result

    def restore_parameter_state(self, state):
        result = super().restore_parameter_state(state)
        if not self.broken_restore:
            self.cad_x = float(state["x"].removesuffix("mm"))
        return result

    def capture_geometry_snapshot(self, names):
        return {"model_unit": "mm", "parameters": dict(self.current),
                "objects": {"patch": {"bounding_box": [0, 0, 0, self.cad_x, 2, 0.1],
                                      "dimensions": [self.cad_x, 2, 0.1]}}}


def test_changed_cad_and_restoration_are_persisted_for_each_oat_case(tmp_path):
    cfg = config(tmp_path)
    cfg["output"] = {"geometry_snapshot": {"objects": ["patch"]}}
    adapter = GeometryAdapter()
    result = run_hfss_sweep(cfg, adapter)
    assert result["status"] == "Completed"
    rows = [r for r in journal(tmp_path) if r["record_type"] == "case_finished"]
    assert [r["extra_metrics"]["geometry_snapshot"]["objects"]["patch"]["dimensions"][0]
            for r in rows] == [3, 4, 1]
    assert all(r["restored_geometry"]["objects"]["patch"]["dimensions"][0] == 1 for r in rows)


def test_restored_expressions_cannot_hide_stale_cad(tmp_path):
    cfg = config(tmp_path)
    cfg["output"] = {"geometry_snapshot": {"objects": ["patch"]}}
    adapter = GeometryAdapter(broken_restore=True)
    with pytest.raises(RuntimeError, match="geometry mismatch"):
        run_hfss_sweep(cfg, adapter)
    assert adapter.current == adapter.baseline
    assert len(adapter.solved) == 1
    failure = next(r for r in journal(tmp_path) if r["record_type"] == "case_restore_failed")
    assert failure["status"] == "failed" and "result" in failure


@pytest.mark.parametrize("cfg", [{"objects": []}, {"objects": ["patch", "patch"]},
    {"objects": ["patch"], "absolute_tolerance": 0},
    {"objects": ["patch"], "absolute_tolerance": float("nan")}])
def test_malformed_observation_does_not_reach_adapter(cfg):
    with pytest.raises(ValueError):
        collect_geometry_snapshot({"output": {"geometry_snapshot": cfg}}, MemoryAdapter())


@pytest.mark.parametrize("bbox,obj_type", [([0, 0, 0, 1], "Solid"),
    ([0, 0, 0, np.nan, 1, 1], "Solid"), ([1, 0, 0, 0, 1, 1], "Solid"),
    ([0, 0, 0, 0, 0, 0], "Unclassified")])
def test_invalid_native_cad_is_rejected(bbox, obj_type):
    adapter = HFSSAdapter({})
    adapter.app = SimpleNamespace(modeler=SimpleNamespace(object_names=["patch"], model_units="mm",
        objects={"patch": SimpleNamespace(object_type=obj_type, bounding_box=bbox)}))
    with pytest.raises(RuntimeError):
        adapter.capture_geometry_snapshot(["patch"])


@pytest.mark.parametrize("closed", [True, False])
def test_sweep_honors_desktop_close_and_keeps_unconfirmed_workcopy(monkeypatch, closed):
    adapter = HFSSAdapter({"close_desktop": True, "close_projects": True}, {"task_type": "sweep"})
    calls = []
    adapter.app = SimpleNamespace(modeler=SimpleNamespace(fit_all=lambda: None),
        close_desktop=lambda: calls.append("close") or closed)
    adapter.work_project_path = "owned_work.aedt"
    monkeypatch.setattr("optimizer.adapters.hfss_adapter.time.sleep", lambda seconds: None)
    monkeypatch.setattr(adapter, "_clean_lock_files", lambda path: calls.append("locks"))
    monkeypatch.setattr(adapter, "_cleanup_temp_copy", lambda: calls.append("cleanup"))
    adapter.disconnect()
    assert calls == (["close", "locks", "cleanup"] if closed else ["close"])


@pytest.mark.parametrize("close_projects", [True, False])
def test_release_explicitly_preserves_desktop_when_requested(monkeypatch, close_projects):
    adapter = HFSSAdapter({"close_desktop": False, "close_projects": close_projects},
                          {"task_type": "sweep"})
    calls = []
    def release(**kwargs):
        calls.append(kwargs)
        return True
    adapter.app = SimpleNamespace(modeler=SimpleNamespace(fit_all=lambda: None), release_desktop=release)
    adapter.work_project_path = "owned_work.aedt"
    monkeypatch.setattr("optimizer.adapters.hfss_adapter.time.sleep", lambda seconds: None)
    monkeypatch.setattr(adapter, "_clean_lock_files", lambda path: None)
    monkeypatch.setattr(adapter, "_cleanup_temp_copy", lambda: calls.append("cleanup"))
    adapter.disconnect()
    expected = [{"close_projects": close_projects, "close_desktop": False}]
    assert calls == (expected + ["cleanup"] if close_projects else expected)


def test_explicit_workcopy_retention_still_closes_owned_desktop(monkeypatch):
    adapter = HFSSAdapter({"close_desktop": True, "close_projects": True},
                          {"task_type": "sweep", "keep_working_copy": True})
    calls = []
    adapter.app = SimpleNamespace(modeler=SimpleNamespace(fit_all=lambda: None),
        close_desktop=lambda: calls.append("close") or True)
    adapter.work_project_path = "owned_work.aedt"
    monkeypatch.setattr("optimizer.adapters.hfss_adapter.time.sleep", lambda seconds: None)
    monkeypatch.setattr(adapter, "_clean_lock_files", lambda path: calls.append("locks"))
    monkeypatch.setattr(adapter, "_cleanup_temp_copy", lambda: calls.append("cleanup"))
    adapter.disconnect()
    assert calls == ["close", "locks"]
