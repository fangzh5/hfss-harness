from copy import deepcopy
import json
import math

import pytest

pytest.importorskip("gerbonara")
pytest.importorskip("shapely")
from optimizer.fabrication import native_export as mod
from optimizer.fabrication.cam_io import final_region
from optimizer.fabrication.stackup import MissingInputsError


def mapping():
    return {"schema_version":mod.MAP_SCHEMA,"coordinate_datum":"native global origin",
        "profile_layer":"core", "layers":[
            {"name":"front","kind":"copper","objects":["metal_a"],"thickness_basis":"modeled"},
            {"name":"core","kind":"dielectric","objects":["body_b"]},
            {"name":"back","kind":"copper","objects":["metal_c"],"thickness_basis":"modeled"}],
        "drill_operations":[{"id":"bore","start_layer":"front","end_layer":"back","objects":["pin_d"]}],
        "excluded_objects":{"helper_e":"simulation only"}}


def polygon(points):
    return {"kind":"polygon","polarity":"dark","points":points}


def square(lo=0,hi=4):
    return polygon([[lo,lo],[hi,lo],[hi,hi],[lo,hi]])


def test_roles_are_exhaustive_exclusive_and_have_no_name_heuristic():
    data = mapping()
    inventory = ["metal_a","body_b","metal_c","pin_d","helper_e","unassigned_feed"]
    with pytest.raises(MissingInputsError,match="object_role:unassigned_feed"):
        mod.mapping_check(data,inventory)
    data["excluded_objects"]["unassigned_feed"] = "explicit simulation connector"
    mod.mapping_check(data,inventory)
    data["drill_operations"][0]["objects"].append("metal_a")
    with pytest.raises(ValueError,match="more than once"):
        mod.mapping_check(data,inventory)


@pytest.mark.parametrize("case",["schema","unknown_key","non_list","duplicate_layer","duplicate_drill","absent_object","bad_pair","same_pair","bad_flag","bad_material","empty_reason"])
def test_bad_mapping_is_rejected(case):
    data = mapping()
    inventory = ["metal_a","body_b","metal_c","pin_d","helper_e"]
    if case == "schema": data["schema_version"] = "guess"
    elif case == "unknown_key": data["default_drill"] = .2
    elif case == "non_list": data["layers"] = {}
    elif case == "duplicate_layer": data["layers"][2]["name"] = "front"
    elif case == "duplicate_drill": data["drill_operations"] *= 2
    elif case == "absent_object": data["layers"][0]["objects"] = ["typo"]
    elif case == "bad_pair": data["drill_operations"][0]["end_layer"] = "core"
    elif case == "same_pair": data["drill_operations"][0]["end_layer"] = "front"
    elif case == "bad_flag": data["drill_operations"][0]["metallized"] = "false"
    elif case == "bad_material": data["layers"][1]["fabrication_material"] = "copper"
    else: data["excluded_objects"]["helper_e"] = ""
    with pytest.raises(ValueError): mod.mapping_check(data,inventory)


def test_native_thickness_is_not_a_guessed_fabrication_thickness():
    data = mapping()
    data["layers"][0]["thickness_basis"] = "finished"
    with pytest.raises(MissingInputsError,match="modeled"):
        mod.mapping_check(data)


def test_unordered_native_segments_close_without_dropping_edges():
    rings = mod.straight_loops([([4,4,0],[4,0,0]),([0,0,0],[0,4,0]),([4,0,0],[0,0,0]),([0,4,0],[4,4,0])])
    assert final_region(rings).area == 16
    with pytest.raises(ValueError,match="Open or branched"):
        mod.straight_loops([([0,0],[1,0]),([1,0],[1,1])])
    with pytest.raises(ValueError,match="duplicate"):
        mod.straight_loops([([0,0],[1,0]),([1,0],[0,0])])


def test_nested_topology_preserves_hole_island_and_circle():
    circle = {"kind":"circle","polarity":"dark","x":2.,"y":2.,"diameter":1.}
    ops = mod.nested_operations([circle,square(),square(1,3)])
    assert [o["polarity"] for o in ops] == ["dark","clear","dark"]
    assert final_region(ops).area == pytest.approx(12+math.pi/4,abs=1e-6)
    with pytest.raises(ValueError,match="Touching/coincident"):
        mod.nested_operations([square(),square()])
    with pytest.raises(ValueError,match="Intersecting"):
        mod.nested_operations([square(),polygon([[2,-1],[5,-1],[5,2],[2,2]])])


@pytest.mark.parametrize("case",["line","circle","arc","ellipse","wrong_length"])
def test_native_edges_prove_shape_before_cam(case):
    if case == "line":
        points = [[3*i/16,4*i/16,1] for i in range(17)]
        assert mod.edge_feature(points,5) == (points[0],points[-1])
        return
    angle = math.pi if case == "arc" else 2*math.pi
    points = [[1+2*math.cos(angle*i/16),-2+(1 if case == "ellipse" else 2)*math.sin(angle*i/16),.7] for i in range(17)]
    if case == "circle":
        feature = mod.edge_feature(points,4*math.pi)
        assert feature["x"] == pytest.approx(1) and feature["y"] == pytest.approx(-2)
        assert feature["diameter"] == pytest.approx(4)
    else:
        with pytest.raises(ValueError):
            mod.edge_feature(points,4*math.pi+(.001 if case == "wrong_length" else 0))


@pytest.mark.parametrize("value",[None,"not_defined","nan","-1",["tensor"],"2*freq",True])
def test_unknown_material_values_never_get_a_default(value):
    raw = [] if value is None else ["permittivity:=",value]
    assert mod.scalar_material(raw,"permittivity") is None


def test_material_lossless_zero_is_distinct_from_absent_loss():
    assert mod.scalar_material(["dielectric_loss_tangent:=","0"],"dielectric_loss_tangent") == 0
    assert mod.scalar_material([],"dielectric_loss_tangent") is None
    assert mod.scalar_material(["permittivity:=","3.7",["NAME:ModifierData",["frequency"]]],"permittivity") is None


def fake_native(monkeypatch):
    materials = {"metal_a":"pec","body_b":"laminate","metal_c":"copper","pin_d":"pec"}
    class Editor:
        def GetModelUnits(self): return "mm"
        def GetPropertyValue(self,tab,name,key): return "true" if key == "Model" else materials[name]
    class Design:
        def SetActiveEditor(self,name): return Editor()
    class Project:
        def GetDefinitionManager(self): return self
        def GetManager(self,name): return self
        def GetData(self,name): return ["permittivity:=","4.1","dielectric_loss_tangent:=","0.007"]
    solids = {}
    for n,lo,hi in [("metal_a",.4,.42),("body_b",0,.4),("metal_c",-.02,0)]:
        solids[n] = {"bbox_mm":[0,0,lo,4,4,hi],"volume_mm3":16*(hi-lo),"native_end_area_mm2":16,"operations":[square()]}
    solids["pin_d"] = {"bbox_mm":[.85,.85,-1,1.15,1.15,.4],"volume_mm3":math.pi*.15**2*1.4,
        "native_end_area_mm2":math.pi*.15**2,"operations":[{"kind":"circle","polarity":"dark","x":1.,"y":1.,"diameter":.3}]}
    monkeypatch.setattr(mod,"read_prism",lambda editor,name:deepcopy(solids[name]))
    inventory = {n:"Solids" for n in materials} | {"helper_e":"Lines"}
    return Project(),Design(),inventory,solids,materials


def test_native_dimensions_materials_explicit_span_and_actual_cam(monkeypatch,tmp_path):
    project,design,inventory,_,_ = fake_native(monkeypatch)
    stack,copper,contours,hits,evidence = mod.extract_design(project,design,mapping(),inventory)
    assert stack.layers[0].thickness_mm == pytest.approx(.02)
    assert stack.materials[1].permittivity == 4.1 and stack.materials[1].loss_tangent == .007
    assert evidence["drill_spans"]["pin_d"] == {"native_z_mm":[-1,.4],"explicit_fabrication_z_mm":[-.02,.42]}
    assert hits["bore"][0]["diameter"] == .3
    plan,comparison = mod.write_verified_package(tmp_path/"package",stack,copper,contours,hits)
    assert plan["drill_operations"][0]["hits"] == hits["bore"]
    assert plan["drill_operations"][0]["metallized"] is True
    assert comparison["maximum_drill_center_offset_mm"] < 1e-6
    assert (tmp_path/"package/docs/fab_notes.md").is_file()
    with pytest.raises(FileExistsError):
        mod.write_verified_package(tmp_path/"package",stack,copper,contours,hits)


def test_material_conductivity_and_unordered_mapping_are_preserved(monkeypatch):
    project,design,inventory,_,_ = fake_native(monkeypatch)
    project.GetData = lambda name:["permittivity:=","4.1","dielectric_loss_tangent:=","0.007","conductivity:=","0.01"]
    data = mapping()
    data["layers"].reverse()
    stack,_,_,_,_ = mod.extract_design(project,design,data,inventory)
    assert stack.layers[0].name == "front" and stack.layers[0].copper_file == "gerber/layer_000.gbr"
    assert stack.layers[-1].copper_file == "gerber/layer_002.gbr"
    dielectric = next(m for m in stack.materials if m.kind == "dielectric")
    assert dielectric.conductivity_s_per_m == .01


@pytest.mark.parametrize("case",["different_z","different_profile","outside_copper","nonmodel_group","noncircle_drill","disjoint_span","mixed_material","overlap","outside_drill","duplicate_drill"])
def test_native_mismatch_refused_without_omitting_features(case,monkeypatch):
    project,design,inventory,solids,materials = fake_native(monkeypatch)
    data = mapping()
    if case == "different_z":
        solids["extra"] = deepcopy(solids["metal_a"])
        solids["extra"]["bbox_mm"][5] += .01
        inventory["extra"],materials["extra"] = "Solids","pec"
        data["layers"][0]["objects"].append("extra")
    elif case == "different_profile":
        solids["extra"] = deepcopy(solids["body_b"])
        solids["extra"]["operations"] = [square(1,3)]
        solids["extra"]["bbox_mm"][2] = -.4
        solids["extra"]["bbox_mm"][5] = 0
        inventory["extra"],materials["extra"] = "Solids","laminate"
        data["layers"].append({"name":"other_core","kind":"dielectric","objects":["extra"]})
    elif case == "outside_copper": solids["metal_a"]["operations"] = [square(-1,4)]
    elif case == "nonmodel_group": inventory["metal_a"] = "Sheets"
    elif case == "noncircle_drill": solids["pin_d"]["operations"] = [square()]
    elif case == "disjoint_span": solids["pin_d"]["bbox_mm"][2:6:3] = [1,2]
    elif case == "mixed_material":
        solids["extra"] = deepcopy(solids["metal_a"])
        inventory["extra"],materials["extra"] = "Solids","copper"
        data["layers"][0]["objects"].append("extra")
    elif case == "outside_drill": solids["pin_d"]["operations"][0]["x"] = -1
    elif case == "duplicate_drill":
        solids["extra"] = deepcopy(solids["pin_d"])
        inventory["extra"],materials["extra"] = "Solids","pec"
        data["drill_operations"][0]["objects"].append("extra")
    else:
        solids["extra"] = deepcopy(solids["metal_a"])
        inventory["extra"],materials["extra"] = "Solids","pec"
        data["layers"][0]["objects"].append("extra")
    with pytest.raises(ValueError):
        mod.extract_design(project,design,data,inventory)


def test_explicit_npth_override_does_not_change_native_geometry(monkeypatch):
    project,design,inventory,_,_ = fake_native(monkeypatch)
    data = mapping()
    data["drill_operations"][0]["metallized"] = False
    stack,_,_,_,_ = mod.extract_design(project,design,data,inventory)
    assert stack.drill_operations[0].metallized is False


def test_layer_union_preserves_an_island_inside_another_objects_clearance(monkeypatch):
    project,design,inventory,solids,materials = fake_native(monkeypatch)
    data = mapping()
    solids["metal_a"]["operations"] = mod.nested_operations([square(),square(1,3)])
    solids["island"] = deepcopy(solids["metal_a"])
    solids["island"]["operations"] = [square(1.5,2.5)]
    inventory["island"],materials["island"] = "Solids","pec"
    data["layers"][0]["objects"] = ["island","metal_a"]
    _,copper,_,_,_ = mod.extract_design(project,design,data,inventory)
    assert final_region(copper["front"]).area == 13


def test_bad_mapping_fails_before_desktop_or_output(tmp_path):
    source = tmp_path/"source.aedt"
    source.write_bytes(b"source")
    path = tmp_path/"map.json"
    path.write_text(json.dumps(mapping() | {"schema_version":"wrong"}))
    with pytest.raises(ValueError,match="schema"):
        mod.export_native(source,"wanted",mapping_path=path,temp_root=tmp_path/"temp",runs_root=tmp_path/"runs",aedt_version="2023.2")
    assert not (tmp_path/"temp").exists() and not (tmp_path/"runs").exists()


def test_overlapping_roots_fail_before_output(tmp_path):
    source = tmp_path/"source.aedt"
    source.write_bytes(b"source")
    with pytest.raises(ValueError,match="distinct"):
        mod.export_native(source,"wanted",temp_root=tmp_path/"temp",runs_root=tmp_path/"temp/runs",aedt_version="2023.2")
    assert not (tmp_path/"temp").exists()


class BoxEditor:
    def __init__(self, defect=None):
        self.defect = defect
        lo, hi = -.1, .6
        self.faces = [
            [[-2,-1,lo],[2,-1,lo],[2,1,lo],[-2,1,lo]],
            [[-2,-1,hi],[2,-1,hi],[2,1,hi],[-2,1,hi]],
            [[-2,-1,lo],[2,-1,lo],[2,-1,hi],[-2,-1,hi]],
            [[2,-1,lo],[2,1,lo],[2,1,hi],[2,-1,hi]],
            [[2,1,lo],[-2,1,lo],[-2,1,hi],[2,1,hi]],
            [[-2,1,lo],[-2,-1,lo],[-2,-1,hi],[-2,1,hi]]]
    def GetObjectBoundingBox(self,name): return [-2,-1,-.1,2,1,.6]
    def GetFaceIDs(self,name): return range(6)
    def GetFaceArea(self,face):
        return [8,8,2.8,1.4,2.8,1.4][face] + (.01 if face == 2 and self.defect == "surface" else 0)
    def GetEdgeIDsFromFace(self,face): return [face*4+i for i in range(4)]
    def GetEdgePositionAtNormalizedParameter(self,edge,t):
        face,index = divmod(edge,4)
        a,b = self.faces[face][index],self.faces[face][(index+1)%4]
        return [x+(y-x)*t for x,y in zip(a,b)]
    def GetEdgeLength(self,edge):
        return math.dist(self.GetEdgePositionAtNormalizedParameter(edge,0),self.GetEdgePositionAtNormalizedParameter(edge,1))
    def GetObjectVolume(self,name): return 5.6+(.01 if self.defect == "volume" else 0)


@pytest.mark.parametrize("defect",[None,"volume","surface","taper"])
def test_extrusion_requires_native_end_volume_and_side_area_consistency(defect):
    editor = BoxEditor(defect)
    if defect == "taper":
        editor.faces[1] = [[x*.9,y,z] for x,y,z in editor.faces[1]]
    if defect is None:
        body = mod.read_prism(editor,"arbitrary")
        assert body["volume_mm3"] == 5.6 and final_region(body["operations"]).area == 8
    else:
        with pytest.raises(ValueError): mod.read_prism(editor,"arbitrary")


def test_discovery_retains_boundary_managed_object_read_errors():
    class Editor:
        def GetObjectBoundingBox(self,name): return [0,0,0,1,1,1]
        def GetProperties(self,tab,name): raise RuntimeError("boundary managed")
    result = mod.inspect_inventory(Editor(),{"owned_surface":"Solids","path":"Lines"})
    assert "attribute_read_error" in result["owned_surface"] and result["path"]["bbox_mm"] == [0,0,0,1,1,1]


@pytest.mark.parametrize("gui",[False,True])
def test_native_cli_defaults_to_non_gui_and_only_changes_on_explicit_flag(gui,monkeypatch,tmp_path):
    captured = {}
    def fake(*args,**kwargs):
        captured.update(kwargs)
        return tmp_path,{"status":"verified_cam_export"}
    monkeypatch.setattr(mod,"export_native",fake)
    args = ["source.aedt","--design","chosen","--temp-root","temp","--runs-root","runs","--aedt-version","2023.2"]
    assert mod.main(args+(["--gui"] if gui else [])) == 0
    assert captured["non_graphical"] is not gui
