from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import optimizer.main as main


class DummyAdapter:
    def __init__(self, hfss_config, optimization_config, task_name):
        self.hfss_config = hfss_config
        self.optimization_config = dict(optimization_config)
        self.task_name = task_name


def test_create_adapter_strips_readonly_flags_for_opt(monkeypatch):
    seen = {}

    def factory(hfss_config, optimization_config, task_name):
        adapter = DummyAdapter(hfss_config, optimization_config, task_name)
        seen["optimization_config"] = adapter.optimization_config
        seen["task_name"] = adapter.task_name
        return adapter

    monkeypatch.setattr(main, "HFSSAdapter", factory)

    config = {
        "task_type": "opt",
        "simulator": {"hfss": {"project_path": "hfss/demo.aedt"}},
    }
    adapter = main.create_adapter(
        config,
        {"skip_simulation": True, "use_original_project": True},
        "demo",
    )

    assert isinstance(adapter, DummyAdapter)
    assert seen["task_name"] == "demo"
    assert "skip_simulation" not in seen["optimization_config"]
    assert "use_original_project" not in seen["optimization_config"]


def test_create_adapter_keeps_readonly_flags_for_val(monkeypatch):
    seen = {}

    def factory(hfss_config, optimization_config, task_name):
        adapter = DummyAdapter(hfss_config, optimization_config, task_name)
        seen["optimization_config"] = adapter.optimization_config
        return adapter

    monkeypatch.setattr(main, "HFSSAdapter", factory)

    config = {
        "task_type": "val",
        "simulator": {"hfss": {"project_path": "hfss/demo.aedt"}},
    }
    adapter = main.create_adapter(
        config,
        {"skip_simulation": True, "use_original_project": True},
        "demo",
    )

    assert isinstance(adapter, DummyAdapter)
    assert seen["optimization_config"]["skip_simulation"] is True
    assert seen["optimization_config"]["use_original_project"] is True
