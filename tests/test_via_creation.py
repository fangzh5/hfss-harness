import copy
import json
import math

import pytest

from optimizer.modeling.path_geometry import eval_length_mm
from optimizer.modeling.vias import ViaIntent, build_via_plan
from optimizer.modeling.via_creation import (capture_live_line_path, create_checked_vias,
                                           line_position_expressions, snapshot_differences, NativeViaBackend, verify_cylinder)


def fixture():
    variables = {"sx": "3mm", "sy": "3.5mm", "via_r": "0.2mm", "sub_h": "0.3mm"}
    points = [{"x": x, "y": y, "z": "0mm"} for x, y in (
        ("-sx/2", "-sy/2"), ("-sx/2", "sy/2"), ("sx/2", "sy/2"), ("sx/2", "-sy/2"), ("-sx/2", "-sy/2"))]
    segments = [{"SegmentType": "Line", "StartIndex": i, "NoOfPoints": 2} for i in range(4)]
    polyline = {"points": points, "segments": segments, "closed": True}
    numeric = [tuple(eval_length_mm(point[a], variables) for a in "xyz") for point in points]
    edges = [{"endpoints_mm": numeric[i:i + 2]} for i in range(4)]
    plan = build_via_plan([polyline], variables, prefix="via", radius="via_r", height="sub_h", z_start="0mm",
                          spacing_mm=0.8, geometry_source={"mode": "live_snapshot", "native_edges": edges, "variables": variables})
    return plan, polyline, variables


class FakeBackend:
    def __init__(self, *, create_fail=0, rename_fail=0, save_fail=False, wrong_geometry=False, delete_fail=False):
        self.objects = {"board": {"untouched": True}}
        self.create_fail, self.rename_fail = create_fail, rename_fail
        self.save_fail, self.wrong_geometry, self.delete_fail = save_fail, wrong_geometry, delete_fail
        self.creates = self.renames = self.saves = 0
        self.isolated = True
        self.live_variables = fixture()[2]

    def assert_isolated_workspace(self):
        if not self.isolated:
            raise ValueError("Not isolated")

    def variables(self):
        return self.live_variables.copy()

    def names(self):
        return set(self.objects)

    def snapshot(self, names):
        return {name: copy.deepcopy(self.objects[name]) for name in names}

    def create(self, name, plan, xy, color):
        self.creates += 1
        self.objects[name] = {"plan": plan, "xy": xy, "color": color}
        if self.creates == self.create_fail:
            raise RuntimeError("creation threw after allocating")

    def rename(self, old, new):
        self.renames += 1
        self.objects[new] = self.objects.pop(old)
        if self.renames == self.rename_fail:
            raise RuntimeError("rename threw after mutating")

    def inspect(self, name):
        stored = self.objects[name]
        if "restored" in stored:
            return copy.deepcopy(stored["restored"])
        p, xy, color = stored["plan"], stored["xy"], stored["color"]
        x, y = [eval_length_mm(v, self.live_variables) for v in xy]
        z, r, h = p.z_start_mm, p.radius_mm, p.height_mm
        return {"bbox_mm": [x - r, y - r, z, x + r, y + r, z + h + (0.1 if self.wrong_geometry else 0)],
                "volume_mm3": math.pi * r * r * h,
                "attributes": {"Material": '"copper"', "Solve Inside": "false", "Model": "true",
                               "Color": str(color[0] | color[1] << 8 | color[2] << 16)},
                "command": {"Center Position": f"{xy[0]} ,{xy[1]} ,{p.z_start_expression}",
                            "Radius": p.radius_expression, "Height": p.height_expression, "Axis": "Z",
                            "Coordinate System": "Global", "Command": "CreateCylinder", "Number of Segments": "0"}}

    def delete(self, names):
        if self.delete_fail:
            raise RuntimeError("delete failed")
        for name in names:
            del self.objects[name]

    def save(self):
        self.saves += 1
        return False if self.save_fail else None

    def restore(self, name, observation):
        self.objects[name] = {"restored": copy.deepcopy(observation)}


def replacement_fixture():
    from dataclasses import replace
    old, path, variables = fixture()
    variables = dict(variables, via_r="0.1mm")
    b = FakeBackend()
    b.live_variables = variables
    old = replace(old, radius_mm=0.1)
    for name, xy in zip(old.names, line_position_expressions(old, path, variables)):
        b.create(name, old, xy, (0, 0, 255))
    b.creates = 0
    ownership = {n: b.inspect(n) for n in old.names}
    source = json.loads(old.source_json)
    source["variables"] = variables
    new = build_via_plan([path], variables, prefix="via", spacing_mm=0.4, radius="via_r", height="sub_h", z_start="0mm", geometry_source=source)
    return b, ownership, new, line_position_expressions(new, path, variables)


@pytest.mark.parametrize("failure", ["none", "create", "rename_previous", "rename_new", "save"])
def test_owned_array_replacement_stages_first_and_restores_previous_on_failure(failure):
    b, ownership, p, xy = replacement_fixture()
    if failure == "create": b.create_fail = 7
    if failure == "rename_previous": b.rename_fail = 5
    if failure == "rename_new": b.rename_fail = 24
    if failure == "save": b.save_fail = True
    if failure == "none":
        result = create_checked_vias(b, p, positions=xy, owned_existing=ownership)
        assert len(result["names"]) == 34 and len(result["replaced_names"]) == 18
        assert b.names() == {"board"} | set(p.names)
    else:
        with pytest.raises(RuntimeError):
            create_checked_vias(b, p, positions=xy, owned_existing=ownership)
        assert b.names() == {"board"} | set(ownership)
        assert {n: b.inspect(n) for n in ownership} == ownership


def test_replacement_rejects_incomplete_or_changed_ownership_before_writes():
    b, ownership, p, xy = replacement_fixture()
    ownership.pop(next(iter(ownership)))
    with pytest.raises(ValueError, match="exactly match"):
        create_checked_vias(b, p, positions=xy, owned_existing=ownership)
    assert b.creates == b.renames == b.saves == 0


@pytest.mark.parametrize("section,prop,value", [("command", "Number of Segments", "8"),
    ("attributes", "Model", "false"), ("attributes", "Solve Inside", "true"),
    ("attributes", "Orientation", "Local")])
def test_replacement_rejects_cylinders_that_cannot_be_faithfully_restored(section, prop, value):
    b, ownership, p, xy = replacement_fixture()
    name = next(iter(ownership))
    ownership[name][section][prop] = value
    b.objects[name] = {"restored": copy.deepcopy(ownership[name])}
    with pytest.raises(ValueError, match="plain global round"):
        create_checked_vias(b, p, positions=xy, owned_existing=ownership)
    assert b.creates == b.renames == b.saves == 0


def test_native_restore_preserves_display_attributes_and_group_after_old_array_deletion():
    b, ownership, _, _ = replacement_fixture()
    observed = next(iter(ownership.values()))
    observed["attributes"].update({"Transparent": "0.8", "Orientation": "Global", "Group": "Model",
                                   "Display Wireframe": "true", "Material Appearance": "false"})
    class Editor:
        def CreateCylinder(self, command, attributes):
            self.command, self.attributes = command, attributes
        def ChangeProperty(self, properties): self.properties = properties
    backend = object.__new__(NativeViaBackend)
    backend.editor = Editor()
    backend.restore("via_1", observed)
    assert backend.editor.command[backend.editor.command.index("Radius:=") + 1] == "via_r"
    changes = backend.editor.properties[1][2][1:]
    assert changes == [["NAME:Transparent", "Value:=", "0.8"], ["NAME:Orientation", "Value:=", "Global"],
                       ["NAME:Group", "Value:=", "Model"], ["NAME:Display Wireframe", "Value:=", True],
                       ["NAME:Material Appearance", "Value:=", False]]


def test_native_variables_include_project_scope_for_dimension_preflight():
    class Owner:
        def __init__(self, values): self.values = values
        def GetVariables(self): return list(self.values)
        def GetVariableValue(self, name): return self.values[name]
    backend = object.__new__(NativeViaBackend)
    backend.project = Owner({"$via_r": "0.1mm"})
    backend.design = Owner({"sub_h": "0.3mm"})
    assert backend.variables() == {"$via_r": "0.1mm", "sub_h": "0.3mm"}


def test_first_creation_keeps_board_and_verifies_18_parameterized_blue_vias():
    p, path, variables = fixture()
    xy = line_position_expressions(p, path, variables)
    b = FakeBackend()
    events = []
    result = create_checked_vias(b, p, positions=xy, emit=lambda event, **kw: events.append(event))
    assert len(result["names"]) == 18
    assert result["protected_before"] == result["protected_after"] == {"board": {"untouched": True}}
    assert result["color_rgb"] == [0, 0, 255]
    assert b.saves == 1
    assert not any(n.startswith("hh_via_stage") for n in b.names())
    assert events[-1] == "via_creation_committed"
    changed = dict(variables, sx="3.2mm")
    assert max(eval_length_mm(x, changed) for x, _ in xy) == pytest.approx(1.6)


@pytest.mark.parametrize("kwargs", [{"create_fail": 5}, {"rename_fail": 6}, {"save_fail": True}, {"wrong_geometry": True}])
def test_create_rename_verify_and_save_failures_roll_back_only_owned_objects(kwargs):
    p, _, _ = fixture()
    b = FakeBackend(**kwargs)
    events = []
    with pytest.raises((RuntimeError, ValueError)):
        create_checked_vias(b, p, emit=lambda event, **kw: events.append(event))
    assert b.objects == {"board": {"untouched": True}}
    assert events[-1] == "via_creation_rolled_back"


def test_rollback_failure_is_not_silently_reported_as_success():
    b = FakeBackend(create_fail=2, delete_fail=True)
    with pytest.raises(RuntimeError, match="requires inspection"):
        create_checked_vias(b, fixture()[0])
    assert b.saves == 0
    assert b.objects["board"] == {"untouched": True}


def test_unowned_prefix_is_never_deleted_or_overwritten():
    b = FakeBackend()
    b.objects["via_100"] = {"unowned": True}
    with pytest.raises(ValueError, match="replacement refused"):
        create_checked_vias(b, fixture()[0])
    assert b.creates == b.saves == 0
    assert b.objects["via_100"] == {"unowned": True}


@pytest.mark.parametrize("change", ["workspace", "dimensions", "positions", "color"])
def test_preflight_failure_performs_no_cad_writes(change):
    p, path, variables = fixture()
    b = FakeBackend()
    xy = line_position_expressions(p, path, variables)
    color = (0, 0, 255)
    if change == "workspace":
        b.isolated = False
    elif change == "dimensions":
        b.live_variables["via_r"] = "0.3mm"
    elif change == "positions":
        b.live_variables["sx"] = "4mm"
    else:
        color = (0, 0, 256)
    with pytest.raises(ValueError):
        create_checked_vias(b, p, positions=xy, color=color)
    assert b.creates == 0


def test_file_history_that_does_not_match_live_final_edges_is_rejected():
    p, path, variables = fixture()
    path = copy.deepcopy(path)
    path["points"][0]["x"] = "-sx/2+1mm"
    with pytest.raises(ValueError, match="match final native"):
        line_position_expressions(p, path, variables)


@pytest.mark.parametrize("field,value", [("Radius", "0.2mm"), ("Axis", "X"), ("Coordinate System", "Local")])
def test_correct_numeric_geometry_does_not_hide_lost_parameterization(field, value):
    p, _, _ = fixture()
    b = FakeBackend()
    xy = ("-1.5mm", "-1.75mm")
    b.create("new", p, xy, (0, 0, 255))
    observed = b.inspect("new")
    observed["command"][field] = value
    with pytest.raises(ValueError, match="expression mismatch"):
        verify_cylinder(observed, p, p.centers_mm[0], xy, (0, 0, 255))


def test_live_line_capture_refuses_arc_chord_conversion():
    class Editor:
        def GetModelUnits(self): return "mm"
        def GetEdgeIDsFromObject(self, name): return [1]
        def GetVertexIDsFromEdge(self, edge): return [1, 2]
        def GetVertexPosition(self, vertex): return (0, vertex - 1, 0)
        def GetEdgeLength(self, edge): return 1.5
        def GetEdgePositionAtNormalizedParameter(self, edge, parameter): return (0, 0.5, 0)
    with pytest.raises(ValueError, match="curved"):
        capture_live_line_path(Editor(), "arc", closed=False)


def test_snapshot_allows_only_cad_numeric_roundoff_and_keeps_attributes_strict():
    original = {"board": {"bbox_mm": [0., 1.], "volume_mm3": 7.5, "material": "copper"}}
    rounded = copy.deepcopy(original)
    rounded["board"]["volume_mm3"] += 1e-14
    rounded["board"]["bbox_mm"][0] += 1e-10
    assert snapshot_differences(original, rounded) == []
    rounded["board"]["bbox_mm"][0] = 0.001
    assert snapshot_differences(original, rounded)[0]["path"] == "/board/bbox_mm/0"
    rounded = copy.deepcopy(original)
    rounded["board"]["material"] = "pec"
    assert snapshot_differences(original, rounded)


@pytest.mark.parametrize("mode", ["default_source_rejected", "verified_backup", "mismatched_backup", "same_file_backup"])
def test_source_update_guard_requires_an_explicit_distinct_byte_verified_backup(tmp_path, mode):
    source = tmp_path / "patch.aedt"
    source.write_bytes(b"baseline")
    backup = tmp_path / "backup.aedt"
    backup.write_bytes(b"different" if mode == "mismatched_backup" else b"baseline")

    class Editor:
        def GetModelUnits(self): return "mm"
    class Project:
        def GetPath(self): return str(tmp_path)
        def GetName(self): return "patch"
    class Design:
        def SetActiveEditor(self, name): return Editor()

    b = NativeViaBackend(Project(), Design(), source=source, working=source, temp_root=tmp_path / "temp",
                         source_update_backup=None if mode == "default_source_rejected" else source if mode == "same_file_backup" else backup)
    if mode == "verified_backup":
        b.assert_isolated_workspace()
    else:
        with pytest.raises(ValueError):
            b.assert_isolated_workspace()


@pytest.mark.parametrize("model,material_exposed", [(False, False), (True, True), (True, False)])
def test_native_attribute_capture_respects_hidden_properties_of_non_model_solids(model, material_exposed):
    class Editor:
        def __init__(self): self.queries = []
        def GetProperties(self, tab, name):
            return ["Model", "Color"] + (["Material", "Solve Inside"] if material_exposed else [])
        def GetPropertyValue(self, tab, name, prop):
            self.queries.append(prop)
            assert prop in self.GetProperties(tab, name), "Unsupported native property query"
            return {"Model": str(model).lower(), "Color": "16711680", "Material": '"copper"', "Solve Inside": "false"}[prop]
    backend = object.__new__(NativeViaBackend)
    backend.editor = Editor()
    if model and not material_exposed:
        with pytest.raises(ValueError, match="does not expose"):
            backend.attributes("top")
    else:
        observed = backend.attributes("top")
        assert observed["Model"] == str(model).lower()
        assert observed["Material"] == ('"copper"' if material_exposed else None)
    if not material_exposed:
        assert "Material" not in backend.editor.queries and "Solve Inside" not in backend.editor.queries
