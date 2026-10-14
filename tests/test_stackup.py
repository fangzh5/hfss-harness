from dataclasses import replace
import json

import pytest

from optimizer.fabrication.stackup import (
    DrillSpec, LayerSpec, LayerStack, MaterialSpec, MissingInputsError, load_stackup, write_stackup_bundle,
)


def make_stack():
    return LayerStack(layers=(
        LayerSpec("TOP", "copper", "cu", .3, .318, "gerber/top.gbr", "modeled", "native TOP"),
        LayerSpec("D1", "dielectric", "d1", 0, .3, source="native substrate"),
        LayerSpec("BOTTOM", "copper", "cu", -.018, 0, "gerber/bottom.gbr", "modeled", "native BOTTOM")),
        materials=(MaterialSpec("cu", "metal", "copper", source="native material"),
                   MaterialSpec("d1", "dielectric", "Rogers", 3.66, .004, source="native material readback")),
        drill_operations=(DrillSpec("through", "TOP", "BOTTOM", "drill/through.drl", True, "confirmed mapping"),),
        profile_file="gerber/outline.gko", coordinate_datum="original global origin; Z=0 at substrate bottom")


def test_stackup_roundtrip_retains_absolute_origin_materials_and_layer_pair(tmp_path):
    stack = make_stack()
    report = write_stackup_bundle(tmp_path / "bundle", stack)
    assert report["rebuild"].ready
    result = load_stackup(tmp_path / "bundle/stackup.json")
    assert result == stack
    assert result.layers[-1].z_bottom_mm == -.018
    assert sum(l.thickness_mm for l in result.layers) == pytest.approx(.336)
    assert result.drill_operations[0].end_layer == "BOTTOM"
    md = (tmp_path / "bundle/docs/stackup.md").read_text(encoding="utf-8")
    assert "3.66" in md and "0.004" in md and "0.336" in md
    with pytest.raises(FileExistsError):
        write_stackup_bundle(tmp_path / "bundle", stack)


def test_unknown_dielectric_properties_remain_missing_and_are_not_needed_for_fabrication(tmp_path):
    stack = make_stack()
    stack = replace(stack, materials=(stack.materials[0], replace(stack.materials[1], permittivity=None, loss_tangent=None)))
    assert stack.check("fabrication", require_cam_files=True).ready
    assert stack.check("rebuild").missing == ("materials.d1.permittivity", "materials.d1.loss_tangent")
    with pytest.raises(MissingInputsError) as exc:
        stack.check("rebuild").require_ready()
    assert exc.value.fields == stack.check("rebuild").missing
    write_stackup_bundle(tmp_path / "unknown", stack)
    payload = json.loads((tmp_path / "unknown/stackup.json").read_text(encoding="utf-8"))
    assert payload["materials"][1]["permittivity"] is None
    assert "materials.d1.permittivity" in (tmp_path / "unknown/docs/stackup.md").read_text(encoding="utf-8")


def test_multimaterial_stack_keeps_each_dielectric_definition():
    stack = make_stack()
    layers = (stack.layers[0], replace(stack.layers[1], z_bottom_mm=.15),
              LayerSpec("D2", "dielectric", "d2", 0, .15), stack.layers[-1])
    materials = (*stack.materials, MaterialSpec("d2", "dielectric", "other laminate", 2.2, 0.0, source="confirmed supplier sheet"))
    result = LayerStack.from_dict(replace(stack, layers=layers, materials=materials).to_dict())
    assert result.check("rebuild", require_cam_files=True).ready
    assert result.layers[2].material_id == "d2"
    assert result.materials[-1].permittivity == 2.2 and result.materials[-1].loss_tangent == 0


@pytest.mark.parametrize("defect", ["unit", "schema", "gap", "overlap", "reversed", "negative_thickness", "nan_z",
    "unknown_material", "wrong_material_kind", "duplicate_layer", "duplicate_material", "noncopper_end", "same_end",
    "string_metallized", "boolean_dk", "negative_df", "infinite_df", "duplicate_operation", "path_escape", "shared_file"])
def test_bad_stackup_is_rejected_before_output(defect, tmp_path):
    stack = make_stack()
    if defect == "unit": stack = replace(stack, unit="mil")
    elif defect == "schema": stack = replace(stack, schema_version="future")
    elif defect == "gap": stack = replace(stack, layers=(replace(stack.layers[0], z_bottom_mm=.31), *stack.layers[1:]))
    elif defect == "overlap": stack = replace(stack, layers=(replace(stack.layers[0], z_bottom_mm=.29), *stack.layers[1:]))
    elif defect == "reversed": stack = replace(stack, layers=tuple(reversed(stack.layers)))
    elif defect == "negative_thickness": stack = replace(stack, layers=(replace(stack.layers[0], z_top_mm=.2), *stack.layers[1:]))
    elif defect == "nan_z": stack = replace(stack, layers=(replace(stack.layers[0], z_top_mm=float("nan")), *stack.layers[1:]))
    elif defect == "unknown_material": stack = replace(stack, layers=(replace(stack.layers[0], material_id="missing"), *stack.layers[1:]))
    elif defect == "wrong_material_kind": stack = replace(stack, layers=(replace(stack.layers[0], material_id="d1"), *stack.layers[1:]))
    elif defect == "duplicate_layer": stack = replace(stack, layers=(*stack.layers, stack.layers[0]))
    elif defect == "duplicate_material": stack = replace(stack, materials=(*stack.materials, stack.materials[0]))
    elif defect == "noncopper_end": stack = replace(stack, drill_operations=(replace(stack.drill_operations[0], end_layer="D1"),))
    elif defect == "same_end": stack = replace(stack, drill_operations=(replace(stack.drill_operations[0], end_layer="TOP"),))
    elif defect == "string_metallized": stack = replace(stack, drill_operations=(replace(stack.drill_operations[0], metallized="false"),))
    elif defect == "boolean_dk": stack = replace(stack, materials=(stack.materials[0], replace(stack.materials[1], permittivity=True)))
    elif defect == "negative_df": stack = replace(stack, materials=(stack.materials[0], replace(stack.materials[1], loss_tangent=-.1)))
    elif defect == "infinite_df": stack = replace(stack, materials=(stack.materials[0], replace(stack.materials[1], loss_tangent=float("inf"))))
    elif defect == "duplicate_operation": stack = replace(stack, drill_operations=(*stack.drill_operations, stack.drill_operations[0]))
    elif defect == "path_escape": stack = replace(stack, profile_file="../outline.gko")
    elif defect == "shared_file": stack = replace(stack, profile_file="gerber/top.gbr")
    assert stack.check().errors
    with pytest.raises(ValueError): write_stackup_bundle(tmp_path / "bad", stack)
    assert not (tmp_path / "bad").exists()


def test_geometry_and_mapping_missing_fields_report_without_guessing():
    stack = make_stack()
    stack = replace(stack, layers=(replace(stack.layers[0], z_bottom_mm=None, copper_file=None, thickness_basis=None), *stack.layers[1:]),
                    drill_operations=(replace(stack.drill_operations[0], metallized=None),), coordinate_datum=None)
    check = stack.check(require_cam_files=True)
    assert not check.errors
    assert set(check.missing) == {"coordinate_datum", "layers.TOP.z_bottom_mm", "layers.TOP.copper_file", "layers.TOP.thickness_basis",
                                  "drill_operations.through.metallized"}


@pytest.mark.parametrize("change", ["unknown_key", "missing_unit", "layer_typo", "thickness_typo", "materials_not_array"])
def test_json_loader_refuses_unknown_or_implicit_fields(change):
    payload = make_stack().to_dict()
    if change == "unknown_key": payload["copper_thikness"] = .018
    elif change == "missing_unit": del payload["unit"]
    elif change == "layer_typo": payload["layers"][0]["z_top"] = .318
    elif change == "thickness_typo": payload["layers"][0]["thikness"] = .018
    elif change == "materials_not_array": payload["materials"] = {}
    with pytest.raises(ValueError): LayerStack.from_dict(payload)
