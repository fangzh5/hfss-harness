from types import SimpleNamespace

import numpy as np
import pytest

from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.core.fitness import FitnessCalculator
from optimizer.results import ResultBundle, TraceData
from optimizer.core.reader import ResultReader


def solution(axis=(55, 60, 65), values=(-12, -13, -12), unit="GHz"):
    return SimpleNamespace(primary_sweep="Freq", primary_sweep_values=list(axis),
        data_real=lambda: values, units_sweeps={"Freq": unit}, variations=[{}])


@pytest.mark.parametrize("unit,multiplier", [("Hz", 1e9), ("MHz", 1e3), ("GHz", 1)])
def test_solution_units_are_explicit_and_equivalent(unit, multiplier):
    adapter = HFSSAdapter({})
    axis, values = adapter._extract_solution_series(solution(
        axis=np.array([55, 60, 65]) * multiplier, unit=unit))
    assert axis == pytest.approx([55, 60, 65])
    assert values == pytest.approx([-12, -13, -12])


@pytest.mark.parametrize("data", [
    solution(values=[-12]), solution(values=[[-12, -13, -12]]),
    solution(values=[-12, np.nan, -12]), solution(axis=[55, 55, 65]),
    solution(unit=None), solution(axis=[65, 60, 55]),
])
def test_malformed_solution_never_truncated_or_flattened(data):
    assert HFSSAdapter({})._extract_solution_series(data) == (None, None)


def test_s11_and_isolation_cannot_have_different_axes(monkeypatch):
    adapter = HFSSAdapter({"results": {"s12": "dB(S(1,2))"}})
    reads = iter([(np.array([55, 60, 65]), np.array([-12, -13, -12])),
                  (np.array([55, 61, 65]), np.array([-20, -20, -20]))])
    monkeypatch.setattr(adapter, "_get_solution_data_direct", lambda _: next(reads))
    assert adapter._get_solution_data() == (None, None, None)
    assert adapter.last_result_bundle is None


def test_explicit_setup_sweep_does_not_fall_back_to_nominal():
    adapter = HFSSAdapter({"setup_name": "Intended", "sweep_name": "Required"})
    calls = []
    def read(**kwargs):
        calls.append(kwargs["setup_sweep_name"])
        return False
    adapter.app = SimpleNamespace(post=SimpleNamespace(get_solution_data=read),
        nominal_sweep="Wrong : Sweep", existing_analysis_sweeps=["Wrong : Sweep"])
    assert adapter._get_solution_data_direct("dB(S(1,1))") == (None, None)
    assert calls == ["Intended : Required"]


@pytest.mark.parametrize("axis,values", [
    ([56, 60, 64], [-12, -12, -12]), ([55, 60, 65], [-12, np.nan, -12]),
    ([55, 60, 65], [-12, -12]), ([55, 55, 65], [-12, -12, -12]),
    ([55, 60, 65], [-12, -np.inf, -12]),
])
def test_invalid_data_never_passes_or_produces_nonfinite_cost(axis, values):
    calc = FitnessCalculator((55, 65), -10)
    result = calc.calculate(np.array(axis), np.array(values))
    assert not result.valid
    assert not result.target_met and not result.stage_met
    assert np.isfinite(result.cost)
    assert result.failure_reason


@pytest.mark.parametrize("multi", [False, True])
def test_gain_and_isolation_are_independent_requirements(multi):
    calc = FitnessCalculator((55, 65), -10, s12_target=-15, gain_target=6,
        multi_objective_config={"enabled": multi,
            "objectives": [{"type": "s11_worst"}, {"type": "peak_gain_min"}]})
    def evaluate(gain, isolation):
        metrics = {"far_field": {"per_frequency": [
            {"frequency": f, "global_peak_direction": {"gain_db": gain}} for f in [55, 60, 65]]}}
        return calc.calculate(np.array([55, 60, 65]), np.array([-12, -12, -12]),
            np.full(3, isolation), extra_metrics=metrics)
    good = evaluate(7, -20)
    assert good.target_met
    assert good.gain_min == 7 and good.s12_max == -20
    assert not evaluate(5, -20).target_met
    assert not evaluate(7, -14).target_met


def test_explicit_frequency_unit_for_evaluation_and_configured_max_gap():
    calc = FitnessCalculator((55, 65), -10, fitness_config={"max_frequency_gap_ghz": 5})
    assert calc.calculate(np.array([55000, 60000, 65000]), np.full(3, -12), frequency_unit="MHz").target_met
    assert not calc.calculate(np.array([55, 65]), np.full(2, -12)).valid


def test_partial_far_field_cannot_satisfy_peak_gain_target():
    calc = FitnessCalculator((55, 65), -10, gain_target=6)
    points = [{"frequency": f, "global_peak_direction": {"gain_db": 9},
               "acquisition": {"angular_scope": "principal_cuts"}} for f in [55, 65]]
    result = calc.calculate(np.array([55, 65]), np.full(2, -12),
                            extra_metrics={"far_field": {"per_frequency": points}})
    assert not result.target_met and not result.valid


def test_result_bundle_preserves_expression_context_and_raw_values():
    trace = TraceData("dB(S(1,2))", np.array([55, 65]), np.array([-20, -21]),
                      source={"setup_sweep": "Setup1 : Sweep", "frequency_unit_original": "MHz"})
    bundle = ResultBundle({"s12": trace}, {"parameters": {"x": "1mm"}, "solved_this_call": True})
    payload = bundle.to_dict()
    assert payload["traces"]["s12"]["expression"] == "dB(S(1,2))"
    assert payload["provenance"]["parameters"]["x"] == "1mm"
    with pytest.raises(ValueError):
        trace.values[0] = 99


def test_csv_frequency_header_and_missing_isolation_rows(tmp_path):
    path = tmp_path / "result.csv"
    path.write_text("Freq [MHz],S11,S12\n55000,-12,-20\n65000,-12,-21\n", encoding="utf-8")
    axis, _, isolation = ResultReader.read_csv(path)
    assert axis == pytest.approx([55, 65])
    assert isolation == pytest.approx([-20, -21])
    path.write_text("Freq,S11,S12\n55,-12,-20\n65,-12,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ResultReader.read_csv(path)


def test_old_model_variation_rejected_even_if_axis_is_correct():
    adapter = HFSSAdapter({"setup_name": "Setup1", "sweep_name": "Sweep"})
    manager = SimpleNamespace(variable_names=["x"], independent_variables={"x": None},
                              get_expression=lambda name: "1mm")
    data = solution()
    data.active_variation = {"x": "2mm"}
    adapter.app = SimpleNamespace(variable_manager=manager,
        post=SimpleNamespace(get_solution_data=lambda **kwargs: data))
    assert adapter._get_solution_data_direct("dB(S(1,1))") == (None, None)


def test_multidimensional_or_multiple_variations_are_rejected():
    data = solution()
    data.variations = [{"x": "1mm"}, {"x": "2mm"}]
    assert HFSSAdapter({})._extract_solution_series(data) == (None, None)


def native_variation_solution(value=5.0, unit="mm", names=("x",)):
    data = solution()
    # Observed AEDT 2023.2/PyAEDT 0.18.1 wrapper: SI number labelled with native unit.
    data.active_variation = {"x": "0.005mm"}
    calls = []
    def read(name, si_value):
        calls.append((name, si_value))
        return value
    data.nominal_variation = SimpleNamespace(
        GetDesignVariableNames=lambda: names,
        GetDesignVariableValue=read, GetDesignVariableUnits=lambda name: unit)
    return data, calls


def variation_adapter(data):
    adapter = HFSSAdapter({"setup_name": "Setup1", "sweep_name": "Sweep"})
    adapter.app = SimpleNamespace(
        variable_manager=SimpleNamespace(variable_names=["x"], independent_variables={"x": None},
                                         get_expression=lambda name: "5mm"),
        post=SimpleNamespace(get_solution_data=lambda **kwargs: data))
    return adapter


def test_native_result_values_use_explicit_non_si_and_keep_wrapper_evidence():
    import json
    data, calls = native_variation_solution()
    adapter = variation_adapter(data)
    axis, values = adapter._get_solution_data_direct("dB(S(1,1))")
    assert axis == pytest.approx([55, 60, 65])
    assert values == pytest.approx([-12, -13, -12])
    assert calls == [("x", False)]
    source = json.loads(json.dumps(adapter._last_trace_source))
    assert source["returned_variation"] == {"x": "5mm"}
    assert source["pyaedt_returned_variation"] == {"x": "0.005mm"}
    assert source["variation_verified"] is True


@pytest.mark.parametrize("value,unit,names", [
    (4.0, "mm", ("x",)), (5.0, "GHz", ("x",)),
    (5.0, "", ("x",)), (False, "mm", ("x",)),
    (float("nan"), "mm", ("x",)), (5.0, "mm", ()),
])
def test_invalid_native_result_does_not_fall_back_to_matching_wrapper(value, unit, names):
    data, _ = native_variation_solution(value, unit, names)
    data.active_variation = {"x": "5mm"}
    assert variation_adapter(data)._get_solution_data_direct("dB(S(1,1))") == (None, None)


@pytest.mark.parametrize("native_value,accepted", [(5.0, True), (4.0, False)])
def test_postprocessor_mutation_does_not_change_requested_variation(native_value, accepted):
    data, _ = native_variation_solution(native_value)
    adapter = variation_adapter(data)
    def read(**kwargs):
        kwargs["variations"]["Freq"] = ["All"]
        kwargs["variations"]["x"].append("All")
        return data
    adapter.app.post.get_solution_data = read
    axis, _ = adapter._get_solution_data_direct("dB(S(1,1))")
    assert (axis is not None) == accepted
    assert adapter._last_trace_source["requested_variation"] == {"x": ["5mm"]}


def test_valid_pareto_result_reports_target_met_independently_of_stop_policy():
    calc = FitnessCalculator((55, 65), -10,
        multi_objective_config={"enabled": True, "objectives": [{"type": "s11_worst"}]})
    result = calc.calculate(np.array([55, 60, 65]), np.full(3, -12))
    assert result.valid and result.stage_met and result.target_met
