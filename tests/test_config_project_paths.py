import json
from pathlib import Path

from optimizer.config_io import load_config, save_config_snapshot
from optimizer.path_utils import resolve_runs_root, resolve_temp_root
from optimizer.adapters.hfss_adapter import HFSSAdapter


def test_installed_workspace_project_is_pinned_to_config_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "user workspace"
    project = workspace / "hfss/model.aedt"
    project.parent.mkdir(parents=True)
    project.write_bytes(b"source model")
    path = workspace / "configs/val.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"task_type": "val", "simulator": {"hfss": {
        "project_path": "../hfss/model.aedt"}}, "optimization": {"work_dir": "../temp"},
        "output": {"output_dir": "../runs"}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = load_config(path)
    assert Path(config["simulator"]["hfss"]["project_path"]) == project
    assert resolve_runs_root(config) == workspace / "runs"
    assert resolve_temp_root(config) == workspace / "temp"
    adapter = HFSSAdapter(config["simulator"]["hfss"], {"task_type": "val"})
    assert Path(adapter.original_project_path) == project
    assert project.read_bytes() == b"source model"
    snapshot = save_config_snapshot(workspace / "runs/task/stamp", config)
    assert load_config(snapshot)["simulator"]["hfss"]["project_path"] == str(project)


def test_absolute_project_path_and_unrelated_config_are_preserved(tmp_path):
    project = tmp_path / "external.aedt"
    config = {"simulator": {"hfss": {"project_path": str(project)}},
              "output": {"output_dir": "../runs"}, "unrelated": "../untouched"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_config(path) == config


def test_non_hfss_config_is_not_rewritten(tmp_path):
    config = {"task_type": "csv", "simulator": {"csv": {"path": "data.csv"}}}
    path = tmp_path / "csv.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_config(path) == config
