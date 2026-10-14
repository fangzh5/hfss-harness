from types import SimpleNamespace

import pytest

from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.metrics import collect_optional_metrics
from optimizer.task_config import TaskConfigError, validate_task_config
from optimizer.tracking_port import TrackingPort
from optimizer.provenance import file_sha256


def native_port():
    state = {"height": .5}
    points = [{"PositionType": "OnEdge", "IsAttachedToEntity": True, "EntityID": n, "UParam": .25}
              for n in (10, 11)]
    line = {"GeometryPosition": points}
    def position(edge, u): return [.25, .1 if edge==10 else .23, -state["height"]]
    editor = SimpleNamespace(GetEdgePositionAtNormalizedParameter=position)
    boundary = SimpleNamespace(name="feed", props={"Modes":{"Mode1":{"IntLine":line}}},
                               update=lambda: pytest.fail("Native attachment must not be replaced"))
    app = SimpleNamespace(boundaries=[boundary],modeler=SimpleNamespace(oeditor=editor,model_units="mm"))
    return state, line, app


def test_native_attachment_is_observed_live_without_detaching_or_reversing_motion():
    state, line, app = native_port()
    tracker = TrackingPort(SimpleNamespace(app=app), {"boundary":"feed","height_parameter":"height"}, {"height":"0.5mm"})
    before = tracker.snapshot()
    state["height"] = .55
    tracker.apply({"height":.55})
    during = tracker.snapshot()
    assert during["start"] == [.25,.1,-.55] and during["end"] == [.25,.23,-.55]
    tracker.restore()
    assert "Start" not in line and "GeometryPosition" in line
    state["height"] = .5
    assert tracker.snapshot() == before


def test_unsupported_attachment_and_explicit_gap_are_rejected():
    state, line, app = native_port()
    with pytest.raises(ValueError, match="gap"):
        TrackingPort(SimpleNamespace(app=app), {"boundary":"feed","height_parameter":"height","gap_mm":.1}, {"height":"0.5mm"})
    line["GeometryPosition"][0]["PositionType"] = "OnFace"
    with pytest.raises(ValueError, match="attachments"):
        TrackingPort(SimpleNamespace(app=app), {"boundary":"feed","height_parameter":"height"}, {"height":"0.5mm"})


def test_native_property_wrappers_are_not_deep_copied():
    class LiveProps(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("Live AEDT property owner cannot be cloned")
    state, line, app = native_port()
    line["GeometryPosition"] = [LiveProps(p) for p in line["GeometryPosition"]]
    tracker = TrackingPort(SimpleNamespace(app=app), {"boundary":"feed","height_parameter":"height"}, {"height":"0.5mm"})
    assert type(tracker.attached_line["GeometryPosition"][0]) is dict


def field_adapter(returned="2mm", frequency=63, unit="GHz"):
    a = HFSSAdapter({"setup_name":"Analysis","sweep_name":"Fields"})
    manager = SimpleNamespace(independent_variables={"x":None},variable_names=["x"],get_expression=lambda n:"2mm")
    a.app = SimpleNamespace(variable_manager=manager)
    solution = SimpleNamespace(active_variation={"x":returned},units_sweeps={"Freq":unit},
                               variation_values=lambda n:[frequency])
    return a, solution


def test_far_field_checks_frequency_unit_and_actual_variable_variation():
    a,s = field_adapter(frequency=63000,unit="MHz")
    p = a._verify_far_field_context(s, a._far_field_variables(), "63GHz")
    assert p["variation_verified"] and p["frequency_ghz"] == 63


@pytest.mark.parametrize("returned,frequency,unit", [("1mm",63,"GHz"),("2mm",60,"GHz"),("2mm",63,None)])
def test_stale_variation_or_wrong_frequency_cannot_be_far_field_evidence(returned, frequency, unit):
    a,s = field_adapter(returned,frequency,unit)
    with pytest.raises((RuntimeError, ValueError)):
        a._verify_far_field_context(s, {"x":"2mm"}, "63GHz")


def test_full_sphere_requires_full_theta_azimuth_and_cartesian_grid():
    full = [(t,p,1) for t in (0,90,180) for p in range(0,361,45)]
    assert HFSSAdapter._full_sphere_rows(full)
    assert not HFSSAdapter._full_sphere_rows(full[:-2])
    assert not HFSSAdapter._full_sphere_rows([(t,p,1) for t in (0,45,90) for p in (0,90,180,270)])
    assert not HFSSAdapter._full_sphere_rows([(t,p,1) for t in (0,90,180) for p in (0,10,20,30)])


def test_metric_collector_passes_explicit_field_solution_separate_from_s_parameter_sweep():
    called = {}
    def query(**kwargs):
        called.update(kwargs)
        return {"per_frequency":[{"frequency":"63GHz"}]}
    config = {"target":{"far_field":{"enabled":True,"required":True,"freqs":["63GHz"],
                                      "setup_sweep_name":"Analysis : StoredFields"}}}
    collect_optional_metrics(config,SimpleNamespace(get_far_field_peak_loss_band=query))
    assert called["setup_sweep_name"] == "Analysis : StoredFields"


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_retention_setting_is_explicit_boolean(flag):
    with pytest.raises(TaskConfigError, match="keep_working_copy"):
        validate_task_config({"task_type":"val","optimization":{"keep_working_copy":flag}})


@pytest.mark.parametrize("changed", [False, True])
def test_existing_result_source_hash_is_required_and_checked_after_read(tmp_path, changed):
    source = tmp_path/"solved.aedt"
    source.write_bytes(b"solved model")
    adapter = HFSSAdapter({"project_path":str(source),"evaluation_mode":"existing_results","setup_name":"Analysis"},
                          {"task_type":"val"})
    adapter.app = SimpleNamespace()
    adapter.work_project_path = str(source)
    adapter.source_project_sha256 = file_sha256(source)
    adapter.capture_current_parameter_state = lambda: {"x":"2mm"}
    def read():
        adapter.last_result_bundle = "valid until file changes"
        if changed: source.write_bytes(b"changed externally")
        return [59,60,61],[-12,-12,-12],None
    adapter._get_solution_data = read
    values = adapter.simulate()
    assert adapter._result_context["source_sha256"] is not None
    if changed:
        assert values == (None,None,None) and adapter.last_result_bundle is None
    else:
        assert values[1] == [-12,-12,-12]
