import numpy as np
import pytest

from optimizer.adapters.hfss_adapter import HFSSAdapter
from optimizer.core.parameter import ParameterManager


class Variables:
    """Behave like AEDT: a setter can silently reject a variable assignment."""
    def __init__(self):
        self.values = {"x": "1mm", "y": "2mm", "$width": "4mm", "offset": "0.25mm"}
        self.calls = []
        self.reject = lambda name, value: False
        self.variable_manager = self

    @property
    def variable_names(self):
        return list(self.values)

    def get_expression(self, name):
        return self.values[name]

    def __setitem__(self, name, value):
        self.calls.append((name, value))
        if not self.reject(name, value):
            self.values[name] = value
        return not self.reject(name, value)


def adapter(**config):
    result = HFSSAdapter({"param_names": ["x", "y"], "param_units": ["mm", "mm"], **config})
    result.app = Variables()
    return result


def test_small_values_project_variables_and_expressions_preserved():
    hfss = adapter()
    assert hfss.set_parameters(np.array([0.0000123456789, 2.0]))
    assert float(hfss.app.values["x"][:-2]) == pytest.approx(0.0000123456789, abs=1e-18)
    assert hfss.apply_parameter_values({"$width": "5mm", "offset": "$width / 2"})
    assert hfss.app.values["offset"] == "$width / 2"
    state = hfss.capture_current_parameter_state()
    assert state["$width"] == "5mm"


@pytest.mark.parametrize("values", [[1], [1, 2, 3], [1, float("nan")], [[1, 2]]])
def test_bad_vector_is_rejected_before_any_write(values):
    hfss = adapter()
    assert not hfss.set_parameters(np.array(values))
    assert hfss.app.calls == []
    assert hfss.current_params is None


def test_unknown_variable_rejected_before_any_write():
    hfss = adapter()
    assert not hfss.apply_parameter_values({"x": 3, "typo": 4})
    assert hfss.app.calls == []
    assert "typo" not in hfss.app.values


@pytest.mark.parametrize("value", ["", "1e999mm"])
def test_invalid_string_assignments_rejected_before_any_write(value):
    hfss = adapter()
    assert not hfss.set_parameter("x", value)
    assert hfss.app.calls == []


def test_fixed_and_optimized_values_roll_back_together_on_silent_rejection():
    hfss = adapter(fixed_parameters={"offset": "0.5mm"})
    original = hfss.app.values.copy()
    hfss.app.reject = lambda name, value: name == "y" and value != "2mm"
    assert not hfss.set_parameters(np.array([3, 4]))
    assert hfss.app.values == original
    assert hfss.current_params is None
    assert hfss._parameter_state_valid
    assert "readback mismatch" in hfss.last_parameter_error


def test_rollback_failure_prevents_solving_until_full_restore():
    hfss = adapter()
    original = hfss.app.values.copy()
    hfss.app.reject = lambda name, value: (name == "y" or (name == "x" and value == "1mm"))
    assert not hfss.set_parameters(np.array([3, 4]))
    assert not hfss._parameter_state_valid
    assert hfss.simulate() == (None, None, None)
    hfss.app.reject = lambda name, value: False
    assert hfss.set_parameter("offset", 0.3)
    assert not hfss._parameter_state_valid
    assert hfss.restore_parameter_state(original)
    assert hfss._parameter_state_valid


def test_existing_results_never_write_even_for_restore():
    hfss = HFSSAdapter({"skip_simulation": True}, {"task_type": "val"})
    hfss.app = Variables()
    baseline = hfss.capture_current_parameter_state()
    assert hfss.restore_parameter_state(baseline)
    assert hfss.apply_parameter_values({"x": 1})
    assert not hfss.apply_parameter_values({"x": 2})
    assert hfss.app.calls == []


def test_manufacturing_quantization_stays_within_bounds():
    params = ParameterManager([{"name": "x", "min": 0.006, "max": 0.024, "resolution": 0.01}])
    assert params.quantize_manufacturing(np.array([0.024])).tolist() == pytest.approx([0.02])
    assert params.quantize_manufacturing(np.array([0.006])).tolist() == pytest.approx([0.01])
    with pytest.raises(ValueError, match="no manufacturing grid"):
        ParameterManager([{"name": "x", "min": 0.006, "max": 0.009, "resolution": 0.01}])


def test_adapter_itself_rejects_readonly_opt_bypass():
    with pytest.raises(ValueError, match="must solve"):
        HFSSAdapter({"skip_simulation": True}, {"task_type": "opt"})
