import numpy as np
import pytest

from optimizer.core.parameter import ParameterManager


def manager(expression):
    return ParameterManager([
        {"name": "a", "min": 0, "max": 10},
        {"name": "aa", "min": 0, "max": 10, "constraint": expression},
    ])


def test_constraint_names_are_tokens_and_chained_comparisons_work():
    params = manager("0 <= a < aa <= 10 and not (aa < 2)")
    assert params.check_constraints(np.array([1, 3]))
    assert not params.check_constraints(np.array([3, 1]))


@pytest.mark.parametrize("expression", [
    "a <= missing", "a <", "__import__('os').getcwd()", "a.real < aa",
    "[a][0] < aa", "a + aa", "True", "a < 1e999", "a < aa or 1",
])
def test_invalid_constraints_rejected_at_configuration_time(expression):
    with pytest.raises(ValueError, match="Invalid constraint"):
        manager(expression)


@pytest.mark.parametrize("values", [[0, 1], [float("nan"), 1], [1, float("inf")], [1]])
def test_arithmetic_failure_and_invalid_vectors_fail_closed(values):
    assert not manager("aa / a < 2").check_constraints(np.array(values))


def test_project_scope_parameter_constraint():
    params = ParameterManager([
        {"name": "$width", "min": 0, "max": 10},
        {"name": "width", "min": 0, "max": 10, "constraint": "width < $width / 2"},
    ])
    assert params.check_constraints(np.array([4, 1]))
    assert not params.check_constraints(np.array([4, 3]))
