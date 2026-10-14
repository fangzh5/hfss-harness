from pathlib import Path

import pytest

from optimizer.inspect_aedt import inspect_project


class Editor:
    def GetObjectsInGroup(self, group):
        return ["body"] if group == "Solids" else []

    def GetObjectBoundingBox(self, name):
        return [0, 0, 0, 1, 2, 3]

    def GetModelUnits(self):
        return "cm"


class Module:
    def GetSetups(self): return ["Analysis"]
    def GetSweeps(self, name): return ["Band"]
    def GetExcitations(self): return ["feed:1", "Lumped Port"]
    def GetBoundaries(self): return ["feed"]
    def GetAvailableReportTypes(self): return ["Modal Solution Data"]
    def GetAllReportNames(self): return ["Existing"]
    def GetAvailableSolutions(self, category): return ["Analysis : Band"]
    def GetAllCategories(self, *args): return ["S Parameter"]
    def GetAllQuantities(self, *args): return ["S(1,1)"]


class Design:
    editor = Editor()
    module = Module()
    def GetDesignType(self): return "HFSS"
    def SetActiveEditor(self, name): return self.editor
    def GetModule(self, name): return self.module
    def GetVariables(self): return ["length"]
    def GetVariableValue(self, name): return "2cm"


class Project:
    design = Design()
    def __init__(self, target): self.target = Path(target)
    def GetName(self): return self.target.stem
    def GetPath(self): return str(self.target.parent)
    def GetTopDesignList(self): return ["HFSS;Renamed"]
    def GetVariables(self): return ["$height"]
    def GetVariableValue(self, name): return "length/2"
    def SetActiveDesign(self, name):
        assert name == "Renamed"
        return self.design


class Desktop:
    aedt_process_id = 123
    def __init__(self, **kwargs):
        assert kwargs["new_desktop"] and kwargs["non_graphical"]
        self.odesktop = self
        self.project = None
        self.closed = False
    def GetVersion(self): return "2023.2"
    def GetIsNonGraphical(self): return True
    def OpenProject(self, path): self.project = Project(path)
    def SetActiveProject(self, name):
        assert name == self.project.GetName()
        return self.project
    def project_list(self): return [self.project.GetName()] if self.project else []
    def CloseProject(self, name): self.closed = True
    def release_desktop(self, **kwargs):
        assert kwargs == {"close_projects": True, "close_on_exit": True}
        return True


def run(tmp_path, factory=Desktop, **kwargs):
    source = tmp_path / "source.aedt"
    source.write_bytes(b"protected source")
    result = inspect_project(source, design_name=kwargs.pop("design_name", "Renamed"),
                             setup=kwargs.pop("setup", "Analysis"), sweep=kwargs.pop("sweep", "Band"),
                             temp_root=tmp_path / "temp", runs_root=tmp_path / "runs",
                             _desktop_factory=factory, **kwargs)
    assert source.read_bytes() == b"protected source"
    assert Path(result["output"], "inspection.json").is_file()
    return result


def test_native_inspection_preserves_units_expressions_and_quantities(tmp_path):
    result = run(tmp_path)
    assert result["status"] == "inspected"
    assert result["variables"] == {"$height": "length/2", "length": "2cm"}
    assert result["model_unit"] == "cm"
    assert result["available_quantities"]["Modal Solution Data"]["S Parameter"] == ["S(1,1)"]
    assert result["source_and_copy_unchanged"] and result["owned_desktop_closed"]
    assert not result["solver_called"] and not result["save_called"]


@pytest.mark.parametrize("field,value", [("design_name", None), ("setup", None), ("sweep", None)])
def test_missing_context_returns_inventory_without_guessing(tmp_path, field, value):
    result = run(tmp_path, **{field: value})
    assert result["status"] == "needs_input" and result["owned_desktop_closed"]
    assert ("design" if field=="design_name" else field) in result["missing"]


@pytest.mark.parametrize("field,value", [("design_name", "Absent"), ("setup", "Absent"), ("sweep", "Absent")])
def test_explicit_wrong_context_fails_instead_of_fallback(tmp_path, field, value):
    result = run(tmp_path, **{field: value})
    assert result["status"] == "failed" and result["owned_desktop_closed"]
    assert "absent" in result["reason"].lower()


def test_unconfirmed_closure_invalidates_even_successful_intake(tmp_path):
    class Unclosed(Desktop):
        def release_desktop(self, **kwargs): return False
    result = run(tmp_path, Unclosed)
    assert result["status"] == "failed" and not result["owned_desktop_closed"]


def test_source_directory_cannot_be_used_as_temp(tmp_path):
    source = tmp_path / "source.aedt"
    source.write_bytes(b"source")
    with pytest.raises(ValueError, match="separate"):
        inspect_project(source, temp_root=tmp_path, runs_root=tmp_path/"out", _desktop_factory=Desktop)


def test_copy_modification_is_rejected_after_closure(tmp_path):
    class Changed(Desktop):
        def CloseProject(self, name):
            self.project.target.write_bytes(b"unexpected save")
    result = run(tmp_path, Changed)
    assert result["status"] == "failed" and "integrity_error" in result


def test_connection_identity_mismatch_is_rejected(tmp_path):
    class Foreign(Desktop):
        def SetActiveProject(self, name):
            project = super().SetActiveProject(name)
            project.GetPath = lambda: str(tmp_path)
            return project
    result = run(tmp_path, Foreign)
    assert result["status"] == "failed" and "differs" in result["reason"]


def test_graphical_session_is_rejected(tmp_path):
    class Graphical(Desktop):
        def GetIsNonGraphical(self): return False
    assert run(tmp_path, Graphical)["status"] == "failed"
