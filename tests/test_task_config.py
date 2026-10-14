from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.task_config import validate_task_config
from optimizer.task_config import resolve_evaluation_mode


def test_hfss_sweep_rejects_optimization_fields():
    config = {
        "task_type": "sweep",
        "parameters": [{"name": "x", "min": 0, "max": 1}],
        "target": {"freq_band": [1, 2]},
        "algorithm": {"method": "de"},
        "study": {
            "variables": [{"name": "x", "start": 0.0, "stop": 1.0, "step": 0.5}],
        },
    }

    with pytest.raises(ValueError, match="sweep"):
        validate_task_config(config)


def test_hfss_requires_optimization_fields():
    config = {
        "task_type": "opt",
        "parameters": [{"name": "x", "min": 0, "max": 1}],
        "target": {"freq_band": [1, 2]},
    }

    with pytest.raises(ValueError, match="algorithm"):
        validate_task_config(config)


def test_opt_rejects_readonly_flags():
    config = {
        "task_type": "opt",
        "parameters": [{"name": "x", "min": 0, "max": 1}],
        "target": {"freq_band": [1, 2]},
        "algorithm": {"method": "de"},
        "optimization": {"skip_simulation": True},
    }

    with pytest.raises(ValueError, match="skip_simulation"):
        validate_task_config(config)


def test_sweep_rejects_readonly_flags():
    config = {
        "task_type": "sweep",
        "study": {"variables": [{"name": "x", "start": 0.0, "stop": 1.0, "step": 0.5}]},
        "optimization": {"use_original_project": True},
    }

    with pytest.raises(ValueError, match="use_original_project"):
        validate_task_config(config)


def test_legacy_task_type_aliases_still_normalize():
    opt_config = {
        "task_type": "hfss",
        "parameters": [{"name": "x", "min": 0, "max": 1}],
        "target": {"freq_band": [1, 2]},
        "algorithm": {"method": "de"},
    }
    sweep_config = {
        "task_type": "hfss_sweep",
        "study": {"variables": [{"name": "x", "start": 0.0, "stop": 1.0, "step": 0.5}]},
    }

    assert validate_task_config(opt_config) == "opt"
    assert validate_task_config(sweep_config) == "sweep"


@pytest.mark.parametrize("task_type", ["opt", "sweep"])
def test_nested_hfss_flags_cannot_bypass_validation(task_type):
    config = {"task_type": task_type, "parameters": [], "target": {}, "algorithm": {}}
    if task_type == "sweep":
        config = {"task_type": "sweep", "study": {
            "variables": [{"name": "x", "start": 0, "stop": 1, "step": 1}]}}
    config["simulator"] = {"hfss": {"skip_simulation": True}}
    with pytest.raises(ValueError, match="simulator.hfss.skip_simulation"):
        validate_task_config(config)


def test_legacy_val_flags_normalize_but_conflicts_and_source_writes_are_rejected():
    assert resolve_evaluation_mode({"optimization": {"skip_simulation": True}}) == "existing_results"
    with pytest.raises(ValueError, match="Conflicting"):
        resolve_evaluation_mode({"skip_simulation": False, "simulator": {"hfss": {"skip_simulation": True}}})
    with pytest.raises(ValueError, match="source writes"):
        resolve_evaluation_mode({"optimization": {"use_original_project": True}})
    with pytest.raises(ValueError, match="boolean"):
        resolve_evaluation_mode({"skip_simulation": "false"})
