from dataclasses import replace
import hashlib
import json

import pytest

pytest.importorskip("gerbonara", reason="optional CAM extra")
pytest.importorskip("shapely", reason="optional CAM extra")
from optimizer.fabrication.cam_import import import_cam_package, main
from optimizer.fabrication.cam_io import final_region, write_copper, write_drill
from optimizer.fabrication.profile_io import write_profile
from optimizer.fabrication.stackup import DrillSpec, LayerSpec, LayerStack, MaterialSpec, MissingInputsError, write_stackup_bundle


def make_package(tmp_path, *, holes=None, metallized=True, cutout=False):
    stack = LayerStack(layers=(LayerSpec("TOP", "copper", "cu", .3, .318, "gerber/top.gbr", "modeled"),
        LayerSpec("D1", "dielectric", "d1", 0, .3),
        LayerSpec("BOTTOM", "copper", "cu", -.018, 0, "gerber/bottom.gbr", "modeled")),
        materials=(MaterialSpec("cu", "metal", "copper", source="fixture definition"),
                   MaterialSpec("d1", "dielectric", "test laminate", 3.66, .004, source="fixture definition")),
        drill_operations=(DrillSpec("through", "TOP", "BOTTOM", "drill/through.drl", metallized),),
        profile_file="gerber/outline.gko", coordinate_datum="fixture global origin")
    package = tmp_path / "package"
    write_stackup_bundle(package, stack)
    ops = [{"kind": "polygon", "polarity": "dark", "points": [[0,0],[4,0],[4,4],[0,4]]},
           {"kind": "circle", "polarity": "clear", "x": 2., "y": 2., "diameter": 1.}]
    for name in ("top", "bottom"): write_copper(package / f"gerber/{name}.gbr", ops)
    rings = [[[0,0],[4,0],[4,4],[0,4]]]
    if cutout: rings.append([[1.5,1.5],[2.5,1.5],[2.5,2.5],[1.5,2.5]])
    write_profile(package / "gerber/outline.gko", rings)
    write_drill(package / "drill/through.drl", holes or [{"x": 1., "y": 1., "diameter": .2}], plated=metallized)
    return package, stack, ops


def test_real_cam_plan_retains_geometry_layers_materials_holes_and_file_hashes(tmp_path):
    package, stack, ops = make_package(tmp_path)
    plan = import_cam_package(package, stack)
    assert plan["source"] == "actual-cam-files"
    assert plan["cad_modified"] is False and plan["solver_called"] is False
    assert final_region(plan["copper"]["TOP"]).symmetric_difference(final_region(ops)).area < 1e-10
    op = plan["drill_operations"][0]
    assert (op["z_bottom_mm"], op["z_top_mm"]) == (-.018, .318)
    assert op["hits"] == [{"x": 1., "y": 1., "diameter": .2}]
    assert plan["stackup"]["materials"][1]["permittivity"] == 3.66
    assert len(plan["file_hashes"]) == 4
    for path, sha in plan["file_hashes"].items():
        assert hashlib.sha256((package / path).read_bytes()).hexdigest() == sha
    result_path = tmp_path / "result.json"
    assert main([str(package), "--output", str(result_path)]) == 0
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "planned"
    with pytest.raises(SystemExit): main([str(package), "--output", str(result_path)])


def test_missing_material_properties_produce_report_without_parsing_cam(tmp_path, monkeypatch):
    import optimizer.fabrication.cam_import as module
    package, stack, _ = make_package(tmp_path)
    stack = replace(stack, materials=(stack.materials[0], replace(stack.materials[1], permittivity=None)))
    (package / "stackup.json").write_text(json.dumps(stack.to_dict()), encoding="utf-8")
    monkeypatch.setattr(module, "read_copper", lambda _: pytest.fail("CAM parsed before missing-input gate"))
    with pytest.raises(MissingInputsError): import_cam_package(package, stack)
    result = tmp_path / "missing.json"
    assert main([str(package), "--output", str(result)]) == 2
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["missing"] == ["materials.d1.permittivity"]
    assert report["cad_modified"] is False


def test_multimaterial_plan_does_not_collapse_dielectrics(tmp_path):
    package, stack, _ = make_package(tmp_path)
    stack = replace(stack, layers=(stack.layers[0], replace(stack.layers[1], z_bottom_mm=.15),
            LayerSpec("D2", "dielectric", "d2", 0, .15), stack.layers[-1]),
        materials=(*stack.materials, MaterialSpec("d2", "dielectric", "second laminate", 2.2, 0., source="fixture")))
    plan = import_cam_package(package, stack)
    assert [l["material_id"] for l in plan["stackup"]["layers"]] == ["cu", "d1", "d2", "cu"]
    assert plan["stackup"]["materials"][-1]["loss_tangent"] == 0


def test_metallization_conflict_is_rejected(tmp_path):
    package, stack, _ = make_package(tmp_path)
    stack = replace(stack, drill_operations=(replace(stack.drill_operations[0], metallized=False),))
    with pytest.raises(ValueError, match="metallization conflicts"): import_cam_package(package, stack)


def test_nonmetallized_annotation_is_kept(tmp_path):
    package, stack, _ = make_package(tmp_path, metallized=False)
    assert import_cam_package(package, stack)["drill_operations"][0]["metallized"] is False


@pytest.mark.parametrize("case", ["outside", "duplicate", "cutout"])
def test_invalid_drill_placement_or_duplicate_hit_is_refused(case, tmp_path):
    hits = [{"x": -.05 if case == "outside" else 2., "y": 2., "diameter": .2}]
    if case == "duplicate": hits *= 2
    package, stack, _ = make_package(tmp_path, holes=hits, cutout=case == "cutout")
    with pytest.raises(ValueError, match="Duplicate|outside board|cutout"): import_cam_package(package, stack)


def test_profile_cutout_kept_when_holes_do_not_intersect_it(tmp_path):
    package, stack, _ = make_package(tmp_path, cutout=True)
    assert len(import_cam_package(package, stack)["profile_contours"]) == 2


def test_file_changes_during_parse_are_rejected(tmp_path, monkeypatch):
    import optimizer.fabrication.cam_import as module
    package, stack, _ = make_package(tmp_path)
    original = module.read_copper
    def mutate(path):
        ops = original(path)
        with path.open("ab") as stream: stream.write(b"\n")
        return ops
    monkeypatch.setattr(module, "read_copper", mutate)
    with pytest.raises(ValueError, match="changed during parsing"): import_cam_package(package, stack)


def test_already_parsed_file_changes_later_in_package_are_rejected(tmp_path, monkeypatch):
    import optimizer.fabrication.cam_import as module
    package, stack, _ = make_package(tmp_path)
    original = module.read_drill
    def mutate_earlier(path):
        hits = original(path)
        with (package / "gerber/top.gbr").open("ab") as stream: stream.write(b"\n")
        return hits
    monkeypatch.setattr(module, "read_drill", mutate_earlier)
    with pytest.raises(ValueError, match="package changed"): import_cam_package(package, stack)


def test_stackup_change_while_planning_does_not_write_result(tmp_path, monkeypatch):
    import optimizer.fabrication.cam_import as module
    package, stack, _ = make_package(tmp_path)
    original = module.import_cam_package
    def mutate_input(*args, **kwargs):
        result = original(*args, **kwargs)
        with (package / "stackup.json").open("a", encoding="utf-8") as stream: stream.write("\n")
        return result
    monkeypatch.setattr(module, "import_cam_package", mutate_input)
    output = tmp_path / "failed.json"
    assert main([str(package), "--output", str(output)]) == 1
    assert not output.exists()


def test_unsupported_gerber_feature_is_not_dropped_from_plan(tmp_path):
    package, stack, _ = make_package(tmp_path)
    (package / "gerber/top.gbr").write_text("%FSLAX46Y46*%\n%MOMM*%\n%ADD10R,1X2*%\n%LPD*%\nD10*\nX0Y0D03*\nM02*\n")
    output = tmp_path / "failed.json"
    assert main([str(package), "--output", str(output)]) == 1
    assert not output.exists()
