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
        self.valid_design = True
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
    source_lock = Path(str(project_path) + ".lock")
    source_lock.write_text("locked", encoding="utf-8")
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
    assert source_lock.exists()
    from optimizer.provenance import file_sha256
    assert adapter.source_project_sha256 == file_sha256(project_path) == file_sha256(adapter.work_project_path)


def test_corrupt_work_copy_is_rejected_before_opening_aedt(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")
    source = tmp_path / "source.aedt"
    source.write_bytes(b"protected original")
    def corrupt_copy(source, destination):
        Path(destination).write_bytes(b"partial")
    monkeypatch.setattr(adapter_module.shutil, "copy2", corrupt_copy)
    adapter = adapter_module.HFSSAdapter({"project_path": str(source)},
                                       {"work_dir": str(tmp_path / "work")})
    before = len(FakeHfss.instances)
    assert not adapter.connect()
    assert len(FakeHfss.instances) == before
    assert source.read_bytes() == b"protected original"


def test_connect_rejects_invalid_pyaedt_design(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")

    project_path = tmp_path / "invalid.aedt"
    project_path.write_text("fake", encoding="utf-8")

    original_init = FakeHfss.__init__

    def invalid_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.valid_design = False

    monkeypatch.setattr(FakeHfss, "__init__", invalid_init)
    adapter = adapter_module.HFSSAdapter(
        {
            "project_path": str(project_path),
            "design_name": "MissingDesign",
        },
        optimization_config={"work_dir": str(tmp_path / "work")},
        task_name="invalid_design",
    )

    assert adapter.connect() is False
    assert adapter._is_connected is False


def test_copy_failure_never_opens_or_unlocks_source(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")
    source = tmp_path / "source.aedt"
    source.write_bytes(b"original project")
    lock = Path(str(source) + ".lock")
    lock.write_bytes(b"active project lock")
    before = len(FakeHfss.instances)

    def fail_copy(*args, **kwargs):
        raise PermissionError("injected copy failure")

    monkeypatch.setattr(adapter_module.shutil, "copy2", fail_copy)
    adapter = adapter_module.HFSSAdapter(
        {"project_path": str(source)}, {"work_dir": str(tmp_path / "work")})
    assert adapter.connect() is False
    assert adapter.work_project_path is None
    assert len(FakeHfss.instances) == before
    assert source.read_bytes() == b"original project"
    assert lock.read_bytes() == b"active project lock"


def test_work_copy_cannot_alias_source(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")
    source = tmp_path / "source_task.aedt"
    source.write_bytes(b"original project")
    alias = tmp_path / "source_task_task.aedt"
    alias.hardlink_to(source)
    before = len(FakeHfss.instances)
    adapter = adapter_module.HFSSAdapter(
        {"project_path": str(source)}, {"work_dir": str(tmp_path)})
    assert adapter.connect() is False
    assert len(FakeHfss.instances) == before
    assert source.read_bytes() == b"original project"


def test_partial_copy_is_never_reused_after_failure(monkeypatch, tmp_path):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")
    source = tmp_path / "source.aedt"
    source.write_bytes(b"original project")
    before = len(FakeHfss.instances)

    def partial_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(adapter_module.shutil, "copy2", partial_copy)
    adapter = adapter_module.HFSSAdapter(
        {"project_path": str(source)}, {"work_dir": str(tmp_path / "work")})
    assert not adapter.connect()
    assert not adapter.connect()
    assert len(FakeHfss.instances) == before
    assert source.read_bytes() == b"original project"


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

def test_far_field_solution_data_fallback_reads_single_boresight_point(monkeypatch):
    _install_fake_ansys(monkeypatch)
    adapter_module = importlib.import_module("optimizer.adapters.hfss_adapter")

    class FakeSolutionData:
        def variation_values(self, name):
            if name == "Theta":
                return [0.0]
            if name == "Phi":
                return [0.0]
            raise KeyError(name)

        def data_db10(self, expression=None, convert_to_SI=False):
            return [5.75]

        def data_real(self, expression=None, convert_to_SI=False):
            return [5.75]

    adapter = adapter_module.HFSSAdapter({"project_path": "dummy.aedt"})

    rows = adapter._extract_far_field_rows_from_solution_data(FakeSolutionData(), "DirTotal", "db10")

    assert rows == [(0.0, 0.0, 5.75)]
