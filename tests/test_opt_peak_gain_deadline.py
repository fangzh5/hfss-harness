from datetime import datetime

import numpy as np
import pytest

from optimizer.core.fitness import FitnessCalculator
from optimizer.run_deadline import parse_deadline, budget_exhausted


def evaluate(gains, frequencies=(23.7, 24.1, 24.6)):
    calc = FitnessCalculator(freq_band=(23.7, 24.6), s11_target=-10, gain_target=6)
    metrics = {"far_field": {"per_frequency": [
        {"frequency": f"{f}GHz", "global_peak_direction": {"gain_db": g}}
        for f, g in zip(frequencies, gains)
    ]}}
    return calc.calculate(np.array([23.7, 24.1, 24.6]), np.array([-12., -13., -12.]), extra_metrics=metrics)


def test_gain_uses_worst_frequency_and_changes_fitness():
    good = evaluate([7, 6.2, 8])
    bad = evaluate([7, 5.2, 8])
    assert good.target_met
    assert good.gain_min == pytest.approx(6.2)
    assert not bad.target_met
    assert bad.cost > good.cost


@pytest.mark.parametrize("gains,freqs", [([], []), ([7, 8], [24, 24.6]), ([7, float('nan'), 8], [23.7, 24.1, 24.6])])
def test_missing_or_invalid_gain_cannot_pass(gains, freqs):
    result = evaluate(gains, freqs)
    assert not result.target_met
    assert result.gain_min is None


def test_deadline_timezone_and_final_save_reserve():
    deadline = parse_deadline("2026-09-17T09:00:00+08:00")
    assert deadline == datetime.fromisoformat("2026-09-17T01:00:00+00:00").timestamp()
    assert not budget_exhausted(deadline, deadline - 3600, 600)
    assert budget_exhausted(deadline, deadline - 1600, 600)
    assert not budget_exhausted(None, deadline, 600)
    with pytest.raises(ValueError):
        parse_deadline("2026-09-17T09:00:00")


@pytest.mark.parametrize("strategy", ["de", "bo", "weighted_metrics"])
def test_scalar_gain_reaches_final_cost_without_s12(strategy):
    cfg = {"scalarization": strategy}
    calc = FitnessCalculator(freq_band=(23.7, 24.6), s11_target=-10, gain_target=6,
                             objective_mode="algorithm_aware", fitness_config=cfg)
    def score(gain):
        metrics = {"far_field": {"per_frequency": [
            {"frequency": f, "global_peak_direction": {"gain_db": gain}}
            for f in [23.7, 24.6]]}}
        return calc.calculate(np.array([23.7,24.6]), np.array([-12.,-12.]), extra_metrics=metrics)
    good, bad = score(7), score(4)
    assert good.target_met and not bad.target_met
    assert bad.cost - good.cost == pytest.approx(1)
    assert good.extra_metrics["fitness_metrics"]["gain_shortfall"] == 0


def test_search_algorithm_does_not_change_target_scoring():
    from optimizer.task_runner import _apply_default_single_objective_fitness_config
    targets = []
    for method in ["de", "bo", "pso", "cmaes"]:
        config = {"target": {"freq_band": [23.7,24.6], "gain_min":6}, "algorithm":{"method":method}}
        _apply_default_single_objective_fitness_config(config)
        targets.append(config["target"])
    assert all(t == targets[0] for t in targets)


def test_explicit_pareto_gain_direction_and_constraints():
    calc = FitnessCalculator(freq_band=(23.7,24.6), s11_target=-10, gain_target=6,
        multi_objective_config={"enabled":True,"objectives":[
            {"type":"s11_worst"},{"type":"peak_gain_min"}]})
    def score(g):
        return calc.calculate(np.array([23.7,24.6]),np.array([-12.,-11.]),
            extra_metrics={"far_field":{"per_frequency":[
                {"frequency":f,"global_peak_direction":{"gain_db":g}} for f in [23.7,24.6]]}})
    good,bad=score(7),score(4)
    assert good.objectives == [-11,-7]
    assert bad.objectives == [-11,-4]
    assert good.stage_met and not bad.stage_met
    assert good.constraint_violation == 0
    assert bad.constraint_violation == 2
