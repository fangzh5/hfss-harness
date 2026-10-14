from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.core.fitness import FitnessCalculator


def _calculator() -> FitnessCalculator:
    return FitnessCalculator(
        freq_band=(26.0, 36.0),
        s11_target=-10.0,
        objective_mode="feasible_first",
        fitness_config={"single_objective_strategy": "legacy"},
        s11_lower_bands=[
            {
                "name": "stopband_after_36",
                "freq_band": [36.1, 40.0],
                "threshold": -10.0,
                "strict": True,
            }
        ],
    )


def test_reverse_s11_band_accepts_only_unmatched_stopband_points():
    calc = _calculator()
    freqs = np.array([26.0, 30.0, 36.0, 36.1, 38.0, 40.0])
    s11 = np.array([-12.0, -15.0, -11.0, -9.8, -7.0, -3.0])

    result = calc.calculate_s11(freqs, s11)

    assert result.target_met is True
    assert result.raw_metrics["lower_s11_violation_raw"] == pytest.approx(0.0)
    assert result.extra_metrics["lower_s11_bands"][0]["point_count"] == 3
    assert result.extra_metrics["lower_s11_bands"][0]["feasible"] is True


def test_reverse_s11_band_rejects_a_too_wide_match_even_when_primary_band_passes():
    calc = _calculator()
    freqs = np.array([26.0, 30.0, 36.0, 36.1, 38.0, 40.0])
    s11 = np.array([-12.0, -15.0, -11.0, -9.8, -12.0, -3.0])

    result = calc.calculate_s11(freqs, s11)

    assert result.target_met is False
    assert result.stage_met is False
    assert result.raw_metrics["lower_s11_violation_raw"] > 0.0
    assert result.component_costs["lower_s11_cost"] > 0.0
    assert result.cost > 1000.0


def test_reverse_s11_band_honors_strict_threshold_and_requires_its_frequency_data():
    calc = _calculator()
    freqs = np.array([26.0, 30.0, 36.0, 36.1, 38.0, 40.0])
    equality_s11 = np.array([-12.0, -15.0, -11.0, -10.0, -10.0, -10.0])

    equality_result = calc.calculate_s11(freqs, equality_s11)
    assert equality_result.target_met is False
    assert equality_result.raw_metrics["lower_s11_violation_raw"] > 0.0

    missing_result = calc.calculate_s11(
        np.array([26.0, 30.0, 36.0]),
        np.array([-12.0, -15.0, -11.0]),
    )
    assert missing_result.target_met is False
    assert missing_result.raw_metrics["lower_s11_missing_bands_raw"] == pytest.approx(1.0)
