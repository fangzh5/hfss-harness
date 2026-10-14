from dataclasses import replace
import math

import pytest

pytest.importorskip("gerbonara")
pytest.importorskip("shapely")
from optimizer.fabrication.cam_import import import_cam_package
from optimizer.fabrication.cam_rebuild import create_geometry, geometry_inputs, rebuild_package, verify_round_holes, verify_wall_boundary
from optimizer.fabrication.stackup import LayerSpec, MaterialSpec
from test_cam_import import make_package


@pytest.mark.parametrize("gui", [False, True])
def test_rebuild_cli_defaults_to_non_gui(gui, monkeypatch, tmp_path):
    from optimizer.fabrication import cam_rebuild
    captured = {}
    def fake(*args, **kwargs):
        captured.update(kwargs)
        return tmp_path
    monkeypatch.setattr(cam_rebuild, "rebuild_package", fake)
    args = ["package", "--temp-root", "temp", "--runs-root", "runs", "--aedt-version", "2023.2"]
    assert cam_rebuild.main(args + (["--gui"] if gui else [])) == 0
    assert captured["non_graphical"] is not gui


def test_native_inputs_preserve_drilled_volume_and_multimaterial(tmp_path):
    package, stack, _ = make_package(tmp_path)
    stack = replace(stack, layers=(stack.layers[0], replace(stack.layers[1], z_bottom_mm=.15),
        LayerSpec("D2", "dielectric", "d2", 0, .15), stack.layers[-1]),
        materials=(*stack.materials, MaterialSpec("d2", "dielectric", "second", 2.2, 0, source="fixture")))
    resolved, regions = geometry_inputs(import_cam_package(package, stack))
    assert resolved.materials[-1].permittivity == 2.2
    assert math.isclose(regions["D2"].area, 16-math.pi*.1**2, abs_tol=2e-8)
    assert regions["D1"].equals(regions["D2"])


@pytest.mark.parametrize("case", ["overlap_copper", "outside_copper", "partial_drill", "overlap_drill", "unknown_metal"])
def test_unsupported_native_cases_rejected_before_cad(case, tmp_path):
    package, stack, _ = make_package(tmp_path)
    plan = import_cam_package(package, stack)
    if case == "overlap_copper":
        plan["copper"]["TOP"].append({"kind":"circle", "polarity":"dark", "x":1.,"y":1.,"diameter":.2})
    elif case == "outside_copper":
        plan["copper"]["TOP"][0]["points"][0][0] = -1
    elif case == "partial_drill":
        plan["drill_operations"][0]["hits"][0].update(x=1.5,y=2.)
    elif case == "overlap_drill":
        plan["drill_operations"][0]["hits"].append({"x":1.1,"y":1.,"diameter":.2})
    else:
        plan["stackup"]["materials"][0]["name"] = "unknown alloy"
    with pytest.raises(ValueError):
        geometry_inputs(plan)


def test_invalid_input_never_imports_cad_or_creates_output(tmp_path):
    package, _, _ = make_package(tmp_path, holes=[{"x":-.1,"y":2.,"diameter":.2}])
    with pytest.raises(ValueError, match="outside board"):
        rebuild_package(package, temp_root=tmp_path/"temp", runs_root=tmp_path/"runs", aedt_version="2023.2")
    assert not (tmp_path/"temp").exists() and not (tmp_path/"runs").exists()


def test_executor_requires_empty_design_before_material_writes():
    class Editor:
        def GetObjectsInGroup(self, group): return ["existing"]
    class Design:
        def SetActiveEditor(self, name): return Editor()
    with pytest.raises(ValueError, match="empty design"):
        create_geometry(None, Design(), {}, None)


@pytest.mark.parametrize("distorted", [False, True])
def test_native_drill_edges_checked_for_radius_and_circumference(distorted):
    class Editor:
        def GetFaceIDs(self, name): return [1]
        def GetEdgeIDsFromFace(self, face): return [2]
        def GetEdgePositionAtNormalizedParameter(self, edge, t):
            radius = .1 + (.001*math.sin(math.pi*t) if distorted else 0)
            return [1+radius*math.cos(2*math.pi*t), 2+radius*math.sin(2*math.pi*t), .3]
        def GetEdgeLength(self, edge): return math.pi*.2
    expected = [{"x":1.,"y":2.,"diameter":.2}]
    if distorted:
        with pytest.raises(RuntimeError, match="missing or distorted"):
            verify_round_holes(Editor(), ["body"], expected, .3)
    else:
        assert verify_round_holes(Editor(), ["body"], expected, .3)[0]["edge_length_mm"] == math.pi*.2


def test_output_roots_cannot_overlap_input_package(tmp_path):
    package, _, _ = make_package(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        rebuild_package(package, temp_root=package/"temp", runs_root=tmp_path/"runs", aedt_version="2023.2")


def test_package_inside_earlier_run_allowed_before_native_input_check(tmp_path, monkeypatch):
    import optimizer.fabrication.cam_rebuild as module
    (tmp_path/"runs").mkdir()
    package, _, _ = make_package(tmp_path/"runs")
    def stop_before_cad(plan): raise RuntimeError("reached native input check")
    monkeypatch.setattr(module, "geometry_inputs", stop_before_cad)
    with pytest.raises(RuntimeError, match="reached native input check"):
        rebuild_package(package, temp_root=tmp_path/"temp", runs_root=tmp_path/"runs", aedt_version="2023.2")
    assert not (tmp_path/"temp").exists()


def test_native_cli_missing_material_returns_needs_input_without_cad(tmp_path, capsys):
    import json
    from optimizer.fabrication.cam_rebuild import main
    package, _, _ = make_package(tmp_path)
    path = package/"stackup.json"
    stack = json.loads(path.read_text())
    stack["materials"][1]["permittivity"] = None
    path.write_text(json.dumps(stack))
    assert main([str(package), "--temp-root", str(tmp_path/"temp"), "--runs-root", str(tmp_path/"runs"),
        "--aedt-version", "2023.2"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "needs_input" and report["missing"] == ["materials.d1.permittivity"]
    assert report["cad_modified"] is False and not (tmp_path/"temp").exists()


@pytest.mark.parametrize("assignment", [[234,287], [230,283]])
def test_native_boundary_matches_actual_wall_faces_not_object_ids(assignment):
    class Editor:
        def GetFaceIDs(self, name): return {"wall_a":[234],"wall_b":[287]}[name]
    class Boundary:
        def GetBoundaries(self): return ["metallized_walls","Perfect E"]
        def GetBoundaryAssignment(self, name): return assignment
    if assignment == [234,287]:
        verify_wall_boundary(Editor(), Boundary(), {"wall_a":{},"wall_b":{}})
    else:
        with pytest.raises(RuntimeError, match="boundary assignment differs"):
            verify_wall_boundary(Editor(), Boundary(), {"wall_a":{},"wall_b":{}})
