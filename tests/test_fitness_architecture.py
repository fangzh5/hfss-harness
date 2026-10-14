from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.core.fitness import FitnessCalculator
from optimizer.metrics import _target_requires_far_field_metrics


def _make_calculator(single_objective_strategy: str) -> FitnessCalculator:
    return FitnessCalculator(
        freq_band=(54.0, 66.0),
        s11_target=-10.0,
        objective_mode="algorithm_aware",
        fitness_config={"single_objective_strategy": single_objective_strategy},
        s11_profile={
            "interior_threshold": -13.0,
            "edge_points": [
                {"freq": 54.0, "threshold": -10.0},
                {"freq": 66.0, "threshold": -10.0},
            ],
        },
    )


def _make_nsga2_calculator() -> FitnessCalculator:
    return FitnessCalculator(
        freq_band=(54.0, 66.0),
        s11_target=-10.0,
        objective_mode="algorithm_aware",
        fitness_config={"single_objective_strategy": "legacy"},
        multi_objective_config={"enabled": True},
        s11_profile={
            "interior_threshold": -13.0,
            "edge_points": [
                {"freq": 54.0, "threshold": -10.0},
                {"freq": 66.0, "threshold": -10.0},
            ],
        },
    )


def test_extract_metrics_splits_edge_and_inband_violation():
    calc = _make_calculator("bo")
    freqs = np.array([54.0, 55.0, 60.0, 65.0, 66.0], dtype=float)
    s11 = np.array([-9.0, -12.0, -11.0, -14.0, -8.0], dtype=float)

    metrics = calc.extract_metrics(freqs=freqs, s11=s11, s12=None, extra_metrics={})

    assert metrics["edge_violation_max"] == pytest.approx(2.0)
    assert metrics["inband_violation_max"] == pytest.approx(2.0)
    assert metrics["matched_bandwidth"] == pytest.approx(0.0)


def test_algorithm_aware_single_objective_mode_produces_distinct_bo_and_de_costs():
    freqs = np.array([54.0, 55.0, 60.0, 65.0, 66.0], dtype=float)
    s11 = np.array([-9.0, -12.0, -11.0, -14.0, -8.0], dtype=float)

    calc = _make_calculator("bo")
    metrics = calc.extract_metrics(freqs=freqs, s11=s11, s12=None, extra_metrics={})
    bo_result = calc.fitness_for_bo(metrics)
    de_result = calc.fitness_for_de(metrics)

    assert bo_result != pytest.approx(de_result)


def test_nsga2_helpers_package_shared_metrics_into_objectives_and_constraints():
    calc = _make_nsga2_calculator()
    freqs = np.array([54.0, 55.0, 60.0, 65.0, 66.0], dtype=float)
    s11 = np.array([-9.0, -12.0, -11.0, -14.0, -8.0], dtype=float)
    s12 = np.array([-18.0, -17.0, -15.0, -14.0, -13.0], dtype=float)
    metrics = calc.extract_metrics(freqs=freqs, s11=s11, s12=s12, extra_metrics={})

    objectives = calc.objectives_for_nsga2(metrics)
    constraints = calc.constraints_for_nsga2(metrics)

    assert objectives == pytest.approx([2.0, 2.0, -0.2])
    assert constraints == {
        "coverage_gap": pytest.approx(12.0),
        "s12_violation": pytest.approx(0.0),
        "gain_shortfall": pytest.approx(0.0),
    }


def test_calculate_multiobjective_uses_shared_nsga2_packaging_with_scalar_constraint_bridge():
    calc = _make_nsga2_calculator()
    freqs = np.array([54.0, 55.0, 60.0, 65.0, 66.0], dtype=float)
    s11 = np.array([-9.0, -12.0, -11.0, -14.0, -8.0], dtype=float)
    s12 = np.array([-18.0, -17.0, -15.0, -14.0, -13.0], dtype=float)

    result = calc.calculate_multiobjective(freqs, s11, gain=s12, extra_metrics={})

    assert result.extra_metrics["fitness_metrics"]["inband_violation_max"] == pytest.approx(2.0)
    assert result.objectives == pytest.approx([2.0, 2.0, -0.2])
    assert result.extra_metrics["constraint_details"] == {
        "coverage_gap": pytest.approx(12.0),
        "s12_violation": pytest.approx(0.0),
        "gain_shortfall": pytest.approx(0.0),
    }
    assert result.constraint_violation == pytest.approx(12.0)
    assert result.cost == pytest.approx(15.8)

def test_multiobjective_boresight_gain_target_abs_uses_boresight_gain_series():
    calc = FitnessCalculator(
        freq_band=(26.0, 38.0),
        s11_target=-11.0,
        objective_mode="algorithm_aware",
        fitness_config={"single_objective_strategy": "legacy"},
        multi_objective_config={
            "enabled": True,
            "objectives": [
                {
                    "name": "boresight_dir_total_target_abs",
                    "type": "boresight_gain_target_abs",
                    "target": 6.0,
                },
            ],
        },
    )
    freqs = np.array([26.0, 32.0, 38.0], dtype=float)
    s11 = np.array([-12.0, -13.0, -11.5], dtype=float)
    extra_metrics = {
        "far_field": {
            "per_frequency": [
                {"boresight_grid_point": {"gain_db": 5.0}},
                {"boresight_grid_point": {"gain_db": 6.5}},
                {"boresight_grid_point": {"gain_db": 7.0}},
            ]
        }
    }

    result = calc.calculate_multiobjective(freqs, s11, extra_metrics=extra_metrics)

    assert result.constraint_violation == pytest.approx(0.0)
    assert result.objectives == pytest.approx([(1.0 + 0.5 + 1.0) / 3.0])
    assert result.extra_metrics["objective_metrics"]["boresight_dir_total_target_abs"] == pytest.approx(
        (1.0 + 0.5 + 1.0) / 3.0
    )


def test_multiobjective_boresight_gain_window_is_a_hard_constraint():
    calc = FitnessCalculator(
        freq_band=(26.0, 28.0),
        s11_target=-10.0,
        objective_mode="algorithm_aware",
        fitness_config={"single_objective_strategy": "legacy"},
        multi_objective_config={
            "enabled": True,
            "objectives": [
                {
                    "name": "J_gain",
                    "type": "boresight_gain_worst_target_abs",
                    "target": 5.5,
                    "constraint_max": 0.5,
                },
            ],
        },
    )
    freqs = np.array([26.0, 27.0, 28.0], dtype=float)
    s11 = np.array([-12.0, -12.5, -11.0], dtype=float)
    extra_metrics = {
        "far_field": {
            "per_frequency": [
                {"boresight_grid_point": {"gain_db": 5.0}},
                {"boresight_grid_point": {"gain_db": 5.5}},
                {"boresight_grid_point": {"gain_db": 6.2}},
            ]
        }
    }

    result = calc.calculate_multiobjective(freqs, s11, extra_metrics=extra_metrics)

    assert result.objectives == pytest.approx([0.7])
    assert result.extra_metrics["constraint_details"]["J_gain_violation"] == pytest.approx(0.2)
    assert result.constraint_violation == pytest.approx(0.2)
    assert result.stage_met is False


def test_boresight_gain_target_abs_objective_requires_far_field_metrics():
    config = {
        "target": {
            "multi_objective": {
                "enabled": True,
                "objectives": [
                    {"name": "boresight_dir_total_target_abs", "type": "boresight_gain_target_abs"}
                ],
            }
        }
    }

    assert _target_requires_far_field_metrics(config) is True
