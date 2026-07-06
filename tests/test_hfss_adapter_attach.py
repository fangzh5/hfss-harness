from pathlib import Path
import importlib
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeHfss:
    instances = []

    def __init__(
        self,
        project,
        design,
        version,
        non_graphical,
        new_desktop,
        close_on_exit,
        aedt_process_id=None,
        remove_lock=False,
        **kwargs,
    ):
        self.project = project
        self.design = design
        self.version = version
        self.non_graphical = non_graphical
        self.new_desktop = new_desktop
        self.close_on_exit = close_on_exit
        self.aedt_process_id = aedt_process_id
        self.remove_lock = remove_lock
        self.kwargs = kwargs
        self.project_name = Path(project).stem
        self.design_name = design
        self.available_variations = types.SimpleNamespace(nominal_values={"strip_l": "1.00mm"})
        self.post = types.SimpleNamespace(report_names=[])
        self.nominal_sweep = "Setup1 : Sweep"
        self.existing_analysis_sweeps = ["Setup1 : Sweep"]
        self.setups = []
        FakeHfss.instances.append(self)

    def release_desktop(self, close_projects=False, close_on_exit=False):
        self.released = (close_projects, close_on_exit)


def _install_fake_ansys(monkeypatch):
    ansys_mod = types.ModuleType("ansys")
    aedt_mod = types.ModuleType("ansys.aedt")
    core_mod = types.ModuleType("ansys.aedt.core")
    core_mod.Hfss = FakeHfss

    monkeypatch.setitem(sys.modules, "ansys", ansys_mod)
    monkeypatch.setitem(sys.modules, "ansys.aedt", aedt_mod)
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core_mod)


def test_connect_uses_work_copy_for_sweep(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")

    project_path = tmp_path / "sample.aedt"
    project_path.write_text("fake", encoding="utf-8")
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "out"

    adapter = adapter_module.HFSSAdapter(
        {
            "project_path": str(project_path),
            "design_name": "Design1",
            "setup_name": "Setup1",
            "sweep_name": "Sweep",
            "non_graphical": True,
            "new_desktop": True,
            "close_on_exit": False,
        },
        optimization_config={
            "task_type": "sweep",
            "task_output_dir": str(output_dir),
            "work_dir": str(work_dir),
        },
        task_name="sample_sweep",
    )

    assert adapter.connect() is True
    fake = FakeHfss.instances[-1]
    assert fake.project != str(project_path)
    assert Path(fake.project).parent == work_dir.resolve()
    assert fake.non_graphical is True
    assert fake.new_desktop is True
    assert fake.close_on_exit is False
    assert fake.aedt_process_id is None


def test_cleanup_temp_copy_removes_pyaedt_and_retries_aedtresults(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")

    project_path = tmp_path / "sample.aedt"
    project_path.write_text("fake", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    work_path = work_dir / "sample_task.aedt"
    work_path.write_text("work", encoding="utf-8")
    results_dir = Path(str(work_path) + "results")
    results_dir.mkdir()
    pyaedt_dir = work_path.with_suffix(".pyaedt")
    pyaedt_dir.mkdir()
    lock_file = Path(str(work_path) + ".lock")
    lock_file.write_text("lock", encoding="utf-8")

    adapter = adapter_module.HFSSAdapter(
        {
            "project_path": str(project_path),
            "design_name": "Design1",
            "setup_name": "Setup1",
            "sweep_name": "Sweep",
            "non_graphical": True,
            "new_desktop": True,
            "close_on_exit": False,
        },
        optimization_config={
            "task_type": "sweep",
            "work_dir": str(work_dir),
        },
        task_name="sample_task",
    )
    adapter.work_project_path = str(work_path)

    attempts = []
    original_remove = adapter._remove_path

    def flaky_remove(path):
        attempts.append(Path(path).name)
        if Path(path) == results_dir and attempts.count(results_dir.name) == 1:
            err = PermissionError("busy")
            err.winerror = 32
            raise err
        return original_remove(path)

    monkeypatch.setattr(adapter, "_remove_path", flaky_remove)
    monkeypatch.setattr(adapter_module.time, "sleep", lambda *_: None)

    adapter._cleanup_temp_copy()

    assert not work_path.exists()
    assert not results_dir.exists()
    assert not pyaedt_dir.exists()
    assert not lock_file.exists()
    assert any(name == pyaedt_dir.name for name in attempts)
    assert attempts.count(results_dir.name) >= 2
