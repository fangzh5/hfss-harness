import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from optimizer.algorithms.bo import BOOptimizer
from optimizer.core import FitnessCalculator, ParameterManager
from optimizer.provenance import build_execution_manifest, file_sha256, valid_manifest
from optimizer.results import ResultBundle, TraceData
from optimizer import task_runner


def context(tmp_path):
    project = tmp_path / "source.aedt"
    project.write_bytes(b"model with setup and materials")
    config = {"task_type": "opt", "algorithm": {"method": "bo"},
              "simulator": {"hfss": {"project_path": str(project), "design_name": "base",
                                     "setup_name": "Setup1", "sweep_name": "Sweep"}},
              "parameters": [{"name": "x", "unit": "mm", "min": 0, "max": 1}],
              "target": {"freq_band": [55, 65], "s11_threshold": -20}}
    adapter = SimpleNamespace(source_project_sha256=file_sha256(project),
                              app=SimpleNamespace(aedt_version_id="2023.2", design_name="base"),
                              config={"fixed_parameters": {"fixed": "2mm"}},
                              capture_current_parameter_state=lambda: {"x": "0mm", "r": "1mm", "fixed": "0mm"})
    return config, adapter


def row(manifest, x=0.2):
    provenance = {"execution_fingerprint": manifest["fingerprint"],
                  "source_sha256": manifest["context"]["source_sha256"], "solved_this_call": True,
                  "parameters": {"x": f"{x}mm", "r": "1mm", "fixed": "2mm"},
                  "design": "base", "setup": "Setup1", "sweep": "Sweep"}
    bundle = ResultBundle({"s11": TraceData("dB(S(1,1))", np.array([55, 60, 65]),
                                           np.full(3, -12), source={"variation_verified": True})}, provenance)
    return {"record_type": "case_finished", "status": "completed", "params": [x],
            "source_sim_id": 1, "cost": -999999, "result_bundle": bundle.to_dict(), "extra_metrics": {}}


def load(tmp_path, config, manifest, rows, *, source_manifest=None, contents=None):
    source = tmp_path / "history"
    source.mkdir()
    (source / "execution_manifest.json").write_text(json.dumps(source_manifest or manifest), encoding="utf-8")
    (source / "cases.jsonl").write_text(contents if contents is not None else
                                       "\n".join(json.dumps(item) for item in rows), encoding="utf-8")
    config["history"] = {"mode": "manual", "sources": [str(source)]}
    mgr = ParameterManager(config["parameters"])
    algorithm = BOOptimizer(mgr.get_bounds())
    calculator = FitnessCalculator(tuple(config["target"]["freq_band"]), config["target"]["s11_threshold"])
    summary = task_runner._load_manual_bo_history(config, algorithm, mgr, manifest=manifest,
                                                 fitness_calc=calculator)
    return summary, algorithm, calculator


def test_history_requires_content_identity_and_recalculates_cost(tmp_path):
    config, adapter = context(tmp_path)
    manifest = build_execution_manifest(config, adapter)
    assert valid_manifest(manifest)
    summary, algorithm, calculator = load(tmp_path, config, manifest, [row(manifest), row(manifest, 2)])
    assert summary["loaded"] == 1 and summary["skipped_out_of_bounds"] == 1
    expected = calculator.calculate(np.array([55, 60, 65]), np.full(3, -12), None)
    assert algorithm.y_train[0] == expected.cost
    assert algorithm.y_train[0] != -999999
    assert len(summary["raw_history"]) == 1


@pytest.mark.parametrize("mutation", ["model", "setup", "material_override", "fixed", "baseline", "solver", "pyaedt"])
def test_different_model_or_runtime_context_rejects_history(tmp_path, mutation):
    config, adapter = context(tmp_path)
    original = build_execution_manifest(config, adapter)
    changed = copy.deepcopy(original)
    key = {"model": "source_sha256", "solver": "solver_version", "pyaedt": "pyaedt_version"}.get(mutation)
    if key:
        changed["context"][key] = "a" * 64 if mutation == "model" else "different"
    elif mutation == "setup":
        changed["context"]["hfss"]["setup_name"] = "AnotherSetup"
    elif mutation == "material_override":
        changed["context"]["hfss"]["material_overrides"] = {"substrate": "different"}
    elif mutation == "fixed":
        changed["context"]["fixed_parameters"]["fixed"] = "3mm"
    else:
        changed["context"]["baseline_expressions"]["r"] = "3mm"
    from optimizer.provenance import context_digest
    changed["fingerprint"] = context_digest(changed["context"])
    summary, algorithm, _ = load(tmp_path, config, original, [row(changed)], source_manifest=changed)
    assert summary["rejected_sources"] == 1 and summary["loaded"] == 0
    assert algorithm.X_train.shape == (0, 1)


@pytest.mark.parametrize("mutation", ["params", "nan", "axis", "variation", "fingerprint", "setup", "fixed", "baseline", "unit", "unsolved"])
def test_inconsistent_case_is_never_preloaded(tmp_path, mutation):
    config, adapter = context(tmp_path)
    manifest = build_execution_manifest(config, adapter)
    case = row(manifest)
    provenance = case["result_bundle"]["provenance"]
    trace = case["result_bundle"]["traces"]["s11"]
    if mutation == "params":
        provenance["parameters"]["x"] = "0.5mm"
    elif mutation == "nan":
        case["params"] = [float("nan")]
    elif mutation == "axis":
        trace["values"].pop()
    elif mutation == "variation":
        trace["source"]["variation_verified"] = False
    elif mutation == "fingerprint":
        provenance["execution_fingerprint"] = "wrong"
    elif mutation == "setup":
        provenance["setup"] = "wrong"
    elif mutation in {"fixed", "baseline"}:
        provenance["parameters"]["fixed" if mutation == "fixed" else "r"] = "3mm"
    elif mutation == "unit":
        trace["frequency_unit"] = "Hz"
    else:
        provenance["solved_this_call"] = False
    summary, algorithm, _ = load(tmp_path, config, manifest, [case])
    assert summary["skipped_invalid_rows"] == 1 and summary["loaded"] == 0
    assert not algorithm.y_train.size


def test_truncated_history_is_rejected_without_partial_preload(tmp_path):
    config, adapter = context(tmp_path)
    manifest = build_execution_manifest(config, adapter)
    summary, algorithm, _ = load(tmp_path, config, manifest, [], contents=json.dumps(row(manifest)) + "\n{broken")
    assert summary["rejected_sources"] == 1 and summary["loaded"] == 0
    assert not algorithm.y_train.size


def test_target_change_does_not_change_physical_identity(tmp_path):
    config, adapter = context(tmp_path)
    original = build_execution_manifest(config, adapter)
    config["target"]["s11_threshold"] = -25
    assert build_execution_manifest(config, adapter)["fingerprint"] == original["fingerprint"]
    summary, algorithm, calculator = load(tmp_path, config, original, [row(original)])
    assert summary["loaded"] == 1
    assert algorithm.y_train[0] == calculator.calculate(np.array([55, 60, 65]), np.full(3, -12), None).cost


def test_manifest_tampering_and_unverified_adapter_are_not_reusable(tmp_path):
    config, adapter = context(tmp_path)
    manifest = build_execution_manifest(config, adapter)
    manifest["context"]["source_sha256"] = "f" * 64
    assert not valid_manifest(manifest)
    adapter.source_project_sha256 = None
    assert not valid_manifest(build_execution_manifest(config, adapter))


@pytest.mark.parametrize("params,costs", [([[float("nan")]], [1]), ([[0.2]], [float("inf")]), ([[2]], [1])])
def test_bo_preload_rejects_nonfinite_and_out_of_bounds(params, costs):
    algorithm = BOOptimizer([(0, 1)])
    with pytest.raises(ValueError):
        algorithm.preload_history(np.array(params), np.array(costs))
    assert not algorithm.y_train.size
