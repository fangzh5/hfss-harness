"""Isolated, geometry-only AEDT execution of the supported actual-CAM subset.

No original project is opened. No ports, setups, air region or solve is added.
Native primitives follow the previously accepted patch CAM fixture.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid

from .cam_import import import_cam_package
from .cam_io import final_region
from .stackup import LayerStack, MissingInputsError, load_stackup


def geometry_inputs(plan):
    """Check the native executor's narrower subset before starting AEDT."""
    from shapely.geometry import Point, Polygon
    stack = LayerStack.from_dict(plan["stackup"])
    stack.check("rebuild", require_cam_files=True).require_ready()
    rings = [Polygon(ring) for ring in plan["profile_contours"]]
    outer = max(rings, key=lambda ring: ring.area)
    board = Polygon(outer.exterior.coords, [r.exterior.coords for r in rings if r is not outer])
    if not board.is_valid:
        raise ValueError("Invalid board topology")
    materials = {m.id: m for m in stack.materials}
    for material in materials.values():
        if material.id not in {layer.material_id for layer in stack.layers}:
            continue
        if material.kind == "metal" and material.name.lower() not in ("copper", "pec") and material.conductivity_s_per_m is None:
            raise ValueError(f"Unknown metal {material.id} needs explicit conductivity")
    regions = {}
    for layer in stack.layers:
        region = final_region(plan["copper"][layer.name]) if layer.kind == "copper" else board
        if region.is_empty or not board.buffer(1e-9).covers(region):
            raise ValueError(f"Empty layer or copper outside board: {layer.name}")
        if layer.kind == "copper":
            # Until native union/split lifecycle is covered, refuse overlapping
            # dark primitives rather than double-counting material volume.
            current = Polygon()
            for op in plan["copper"][layer.name]:
                feature = final_region([{**op, "polarity": "dark"}])
                if op["polarity"] == "dark":
                    if current.intersection(feature).area > 1e-12:
                        raise ValueError("Overlapping dark copper operations unsupported by native executor")
                    current = current.union(feature)
                else:
                    current = current.difference(feature)
        regions[layer.name] = region
    hits_seen = []
    for operation in plan["drill_operations"]:
        lo, hi = operation["z_bottom_mm"], operation["z_top_mm"]
        for hit in operation["hits"]:
            for previous, lower, upper in hits_seen:
                if min(hi, upper) >= max(lo, lower) and math.dist((hit["x"], hit["y"]), (previous["x"], previous["y"])) <= (hit["diameter"] + previous["diameter"]) / 2:
                    raise ValueError("Overlapping/touching drills unsupported by native executor")
            hits_seen.append((hit, lo, hi))
            disc = Point(hit["x"], hit["y"]).buffer(hit["diameter"] / 2, quad_segs=1024)
            for layer in stack.layers:
                if layer.z_bottom_mm >= lo - 1e-8 and layer.z_top_mm <= hi + 1e-8:
                    region = regions[layer.name]
                    if not region.covers(disc) and region.intersects(disc):
                        raise ValueError("Partial drill/copper intersection unsupported by native executor")
                    regions[layer.name] = region.difference(disc)
    return stack, regions


def fmt(value):
    return f"{float(value):.17g}mm"


def attributes(name, material):
    return ["NAME:Attributes", "Name:=", name, "Flags:=", "", "Color:=", "(0 0 255)", "Transparency:=", .7,
            "PartCoordinateSystem:=", "Global", "MaterialValue:=", '"' + material + '"', "SolveInside:=", material not in ("copper", "pec")]


def prism(editor, name, points, z, height, material):
    points = [list(p) for p in points]
    if points[0] == points[-1]:
        points.pop()
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2
    if area < 0:
        points.reverse()
    xs, ys = sorted({p[0] for p in points}), sorted({p[1] for p in points})
    if len(points) == 4 and len(xs) == len(ys) == 2 and {tuple(p) for p in points} == {(x, y) for x in xs for y in ys} and all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:] + points[:1])):
        editor.CreateBox(["NAME:BoxParameters", "XPosition:=", fmt(xs[0]), "YPosition:=", fmt(ys[0]), "ZPosition:=", fmt(z),
            "XSize:=", fmt(xs[1]-xs[0]), "YSize:=", fmt(ys[1]-ys[0]), "ZSize:=", fmt(height)], attributes(name, material))
        return
    points.append(points[0])
    editor.CreatePolyline(["NAME:PolylineParameters", "IsPolylineCovered:=", True, "IsPolylineClosed:=", True,
        ["NAME:PolylinePoints", *[["NAME:PLPoint", "X:=", fmt(x), "Y:=", fmt(y), "Z:=", fmt(z)] for x, y in points]],
        ["NAME:PolylineSegments", *[["NAME:PLSegment", "SegmentType:=", "Line", "StartIndex:=", i, "NoOfPoints:=", 2] for i in range(len(points)-1)]],
        ["NAME:PolylineXSection", "XSectionType:=", "None", "XSectionOrient:=", "Auto", "XSectionWidth:=", "0mm",
         "XSectionTopWidth:=", "0mm", "XSectionHeight:=", "0mm", "XSectionNumSegments:=", "0", "XSectionBendType:=", "Corner"]], attributes(name, material))
    editor.ThickenSheet(["NAME:Selections", "Selections:=", name, "NewPartsModelFlag:=", "Model"],
        ["NAME:SheetThickenParameters", "Thickness:=", fmt(height), "BothSides:=", False])


def cylinder(editor, name, hit, z, height, material="vacuum"):
    editor.CreateCylinder(["NAME:CylinderParameters", "XCenter:=", fmt(hit["x"]), "YCenter:=", fmt(hit["y"]), "ZCenter:=", fmt(z),
        "Radius:=", fmt(hit["diameter"]/2), "Height:=", fmt(height), "WhichAxis:=", "Z", "NumSides:=", "0"], attributes(name, material))


def subtract(editor, blanks, tool):
    if not blanks:
        editor.Delete(["NAME:Selections", "Selections:=", tool])
        return
    editor.Subtract(["NAME:Selections", "Blank Parts:=", ",".join(blanks), "Tool Parts:=", tool],
        ["NAME:SubtractParameters", "KeepOriginals:=", False])


def create_geometry(project, design, plan, stack):
    """Only call on the new isolated empty design owned by rebuild_package."""
    editor = design.SetActiveEditor("3D Modeler")
    if any(list(editor.GetObjectsInGroup(group)) for group in ("Solids", "Sheets", "Lines", "Unclassified")):
        raise ValueError("CAM executor requires an empty design")
    materials = {}
    for i, material in enumerate(stack.materials):
        if material.id not in {layer.material_id for layer in stack.layers}:
            continue
        if material.kind == "metal" and material.name.lower() in ("copper", "pec") and material.conductivity_s_per_m is None:
            materials[material.id] = material.name.lower()
            continue
        name = f"cam_material_{i:03d}"
        data = ["NAME:" + name, "CoordinateSystemType:=", "Cartesian", "BulkOrSurfaceType:=", 1,
            ["NAME:PhysicsTypes", "set:=", ["Electromagnetic"]]]
        if material.kind == "dielectric":
            data += ["permittivity:=", str(material.permittivity), "dielectric_loss_tangent:=", str(material.loss_tangent)]
            if material.conductivity_s_per_m is not None:
                data += ["conductivity:=", str(material.conductivity_s_per_m)]
        else:
            data += ["conductivity:=", str(material.conductivity_s_per_m)]
        project.GetDefinitionManager().AddMaterial(data)
        materials[material.id] = name
    by_layer, appearance, walls = {}, {}, {}
    drilled = {layer.name: [] for layer in stack.layers}
    copper_colors = [(217, 119, 6), (22, 163, 74), (168, 85, 247), (239, 68, 68), (234, 179, 8)]
    copper_index = 0
    rings = plan["profile_contours"]
    from shapely.geometry import Polygon
    outer_index = max(range(len(rings)), key=lambda i: Polygon(rings[i]).area)
    for i, layer in enumerate(stack.layers):
        z, height = layer.z_bottom_mm, layer.thickness_mm
        material = materials[layer.material_id]
        baseline = set(editor.GetObjectsInGroup("Solids"))
        if layer.kind == "copper":
            color = copper_colors[copper_index % len(copper_colors)]
            copper_index += 1
            source_file = layer.copper_file
            entries = plan["copper"][layer.name]
        else:
            color, source_file = (125, 211, 252), stack.profile_file
            entries = [{"kind": "polygon", "polarity": "dark", "points": rings[outer_index]}]
            entries += [{"kind": "polygon", "polarity": "clear", "points": ring} for j, ring in enumerate(rings) if j != outer_index]
        for j, op in enumerate(entries):
            name = f"layer_{i:03d}_{j:04d}"
            blanks = sorted(set(editor.GetObjectsInGroup("Solids")) - baseline)
            if op["polarity"] == "clear" and not blanks:
                continue
            clear = op["polarity"] == "clear"
            bottom, thickness = (z-height, 3*height) if clear else (z, height)
            if op["kind"] == "polygon":
                prism(editor, name, op["points"], bottom, thickness, material)
            else:
                cylinder(editor, name, op, bottom, thickness, material)
            if clear:
                subtract(editor, blanks, name)
        by_layer[layer.name] = sorted(set(editor.GetObjectsInGroup("Solids")) - baseline)
        if not by_layer[layer.name]:
            raise RuntimeError("Native operation removed an entire layer")
        for name in by_layer[layer.name]:
            appearance[name] = {"color": color, "source_file": source_file, "layer": layer.name, "material": material}
    for i, operation in enumerate(plan["drill_operations"]):
        lo, hi = operation["z_bottom_mm"], operation["z_top_mm"]
        blanks = [name for layer in stack.layers if layer.z_bottom_mm >= lo - 1e-8 and layer.z_top_mm <= hi + 1e-8 for name in by_layer[layer.name]]
        for j, hit in enumerate(operation["hits"]):
            from shapely.geometry import Point
            disc = Point(hit["x"], hit["y"]).buffer(hit["diameter"]/2, quad_segs=1024)
            for layer in stack.layers:
                if layer.z_bottom_mm >= lo - 1e-8 and layer.z_top_mm <= hi + 1e-8:
                    region = final_region(plan["copper"][layer.name]) if layer.kind == "copper" else Polygon(rings[outer_index], [ring for k, ring in enumerate(rings) if k != outer_index])
                    if region.covers(disc):
                        drilled[layer.name].append(hit)
            tool = f"drill_tool_{i:03d}_{j:04d}"
            cylinder(editor, tool, hit, lo-(hi-lo), 3*(hi-lo))
            subtract(editor, blanks, tool)
            if not operation["metallized"]:
                continue
            wall = f"wall_{i:03d}_{j:04d}"
            editor.CreateCircle(["NAME:CircleParameters", "IsCovered:=", False, "XCenter:=", fmt(hit["x"]), "YCenter:=", fmt(hit["y"]),
                "ZCenter:=", fmt(lo), "Radius:=", fmt(hit["diameter"]/2), "WhichAxis:=", "Z", "NumSegments:=", "0"], attributes(wall, "pec"))
            editor.SweepAlongVector(["NAME:Selections", "Selections:=", wall, "NewPartsModelFlag:=", "Model"],
                ["NAME:VectorSweepParameters", "DraftAngle:=", "0deg", "DraftType:=", "Round", "SweepVectorX:=", "0mm", "SweepVectorY:=", "0mm", "SweepVectorZ:=", fmt(hi-lo)])
            walls[wall] = {"hit": hit, "z_bottom_mm": lo, "z_top_mm": hi}
            appearance[wall] = {"color": (37, 99, 235), "source_file": next(op.file for op in stack.drill_operations if op.id == operation["id"])}
    if walls:
        design.GetModule("BoundarySetup").AssignPerfectE(["NAME:metallized_walls", "Objects:=", sorted(walls), "InfGroundPlane:=", False])
    for name, entry in appearance.items():
        r, g, b = entry["color"]
        editor.ChangeProperty(["NAME:AllTabs", ["NAME:Geometry3DAttributeTab", ["NAME:PropServers", name],
            ["NAME:ChangedProps", ["NAME:Color", "R:=", r, "G:=", g, "B:=", b], ["NAME:Transparent", "Value:=", .7],
             ["NAME:Material Appearance", "Value:=", False]]]])
    return by_layer, materials, walls, appearance, drilled


def verify_round_holes(editor, names, expected, z):
    """Match requested drills to native closed circle edges, not just volume."""
    remaining = list(expected)
    circles = []
    for name in names:
        for face_id in editor.GetFaceIDs(name):
            for edge_id in editor.GetEdgeIDsFromFace(face_id):
                pts = [[float(v) for v in editor.GetEdgePositionAtNormalizedParameter(edge_id, i/16)] for i in range(17)]
                if any(abs(p[2]-z) > 1e-8 for p in pts) or math.dist(pts[0], pts[-1]) > 1e-8:
                    continue
                for index, hit in enumerate(remaining):
                    if all(abs(math.dist(p[:2], (hit["x"], hit["y"])) - hit["diameter"]/2) < 1e-8 for p in pts):
                        length = float(editor.GetEdgeLength(edge_id))
                        if abs(length - math.pi*hit["diameter"]) > 1e-8:
                            raise RuntimeError("Native circular drill edge length differs")
                        circles.append({**hit, "edge_length_mm": length})
                        remaining.pop(index)
                        break
    if remaining:
        raise RuntimeError("Native drilled circle is missing or distorted")
    return circles


def verify_wall_boundary(editor, boundaries, walls):
    if list(boundaries.GetBoundaries()) != (["metallized_walls", "Perfect E"] if walls else []):
        raise RuntimeError("Native wall boundary differs")
    # AEDT 2023.2 GetBoundaryAssignment resolves object assignments to face IDs.
    expected = {str(face) for name in walls for face in editor.GetFaceIDs(name)}
    if walls and set(map(str, boundaries.GetBoundaryAssignment("metallized_walls"))) != expected:
        raise RuntimeError("Native wall boundary assignment differs")


def verify_geometry(project, design, stack, regions, built):
    by_layer, materials, walls, appearance, drilled = built
    editor = design.SetActiveEditor("3D Modeler")
    solids = set(editor.GetObjectsInGroup("Solids"))
    if solids != {name for names in by_layer.values() for name in names} or set(editor.GetObjectsInGroup("Sheets")) != set(walls):
        raise RuntimeError("Unexpected or missing native objects")
    if list(editor.GetObjectsInGroup("Lines")) or list(editor.GetObjectsInGroup("Unclassified")):
        raise RuntimeError("Native line/unclassified geometry remains")
    volumes, hole_contours = {}, {}
    for layer in stack.layers:
        actual = sum(float(editor.GetObjectVolume(name)) for name in by_layer[layer.name])
        expected = regions[layer.name].area * layer.thickness_mm
        # CAM circles use 4096-sided reference polygons; native circles stay exact.
        if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=4e-7, abs_tol=1e-7):
            raise RuntimeError(f"Native volume differs for {layer.name}: {actual} vs {expected}")
        volumes[layer.name] = {"expected_mm3": expected, "actual_mm3": actual}
        hole_contours[layer.name] = verify_round_holes(editor, by_layer[layer.name], drilled[layer.name], layer.z_top_mm)
        native_bounds = [[float(v) for v in editor.GetObjectBoundingBox(name)] for name in by_layer[layer.name]]
        xmin, ymin, xmax, ymax = regions[layer.name].bounds
        aggregate = [min(b[0] for b in native_bounds), min(b[1] for b in native_bounds),
                     max(b[3] for b in native_bounds), max(b[4] for b in native_bounds)]
        if any(abs(a-b) > 1e-8 for a, b in zip(aggregate, [xmin, ymin, xmax, ymax])):
            raise RuntimeError("Native layer XY extent differs")
        for name in by_layer[layer.name]:
            bbox = [float(v) for v in editor.GetObjectBoundingBox(name)]
            if abs(bbox[2]-layer.z_bottom_mm) > 1e-8 or abs(bbox[5]-layer.z_top_mm) > 1e-8:
                raise RuntimeError("Native layer Z differs")
            material = str(editor.GetPropertyValue("Geometry3DAttributeTab", name, "Material")).strip('"')
            if material != materials[layer.material_id]:
                raise RuntimeError("Native layer material differs")
    for material in stack.materials:
        if material.id not in materials:
            continue
        if material.kind == "dielectric" or materials[material.id].startswith("cam_material_"):
            values = list(project.GetDefinitionManager().GetManager("Material").GetData(materials[material.id]))
            props = {"permittivity": material.permittivity, "dielectric_loss_tangent": material.loss_tangent} if material.kind == "dielectric" else {"conductivity": material.conductivity_s_per_m}
            if material.kind == "dielectric" and material.conductivity_s_per_m is not None:
                props["conductivity"] = material.conductivity_s_per_m
            if any(not math.isclose(float(values[values.index(key+":=")+1]), value, rel_tol=1e-12, abs_tol=1e-14) for key, value in props.items()):
                raise RuntimeError("Native material properties differ")
    for name, wall in walls.items():
        hit, lo, hi = wall["hit"], wall["z_bottom_mm"], wall["z_top_mm"]
        x, y, r = hit["x"], hit["y"], hit["diameter"]/2
        bbox = [float(v) for v in editor.GetObjectBoundingBox(name)]
        if any(abs(a-b) > 1e-8 for a, b in zip(bbox, [x-r, y-r, lo, x+r, y+r, hi])):
            raise RuntimeError("Native metallized wall extent differs")
    boundaries = design.GetModule("BoundarySetup")
    verify_wall_boundary(editor, boundaries, walls)
    observed = {}
    for name, entry in appearance.items():
        props = {key: str(editor.GetPropertyValue("Geometry3DAttributeTab", name, key)) for key in ("Model", "Color", "Transparent", "Material Appearance")}
        r, g, b = entry["color"]
        if props["Model"].lower() != "true" or int(props["Color"]) != r+256*g+65536*b or not math.isclose(float(props["Transparent"]), .7) or props["Material Appearance"].lower() != "false":
            raise RuntimeError("Native display/model properties differ")
        observed[name] = props
    return {"volumes": volumes, "native_drill_contours": hole_contours, "appearance": observed, "solid_count": len(solids), "wall_count": len(walls)}


def rebuild_package(package, *, temp_root, runs_root, aedt_version, non_graphical=True):
    """Own one desktop, verify saved/reopened geometry, then archive new bytes."""
    package, temp_root, runs_root = (Path(p).resolve() for p in (package, temp_root, runs_root))
    if any(root == package or root.is_relative_to(package) for root in (temp_root, runs_root)) or temp_root == runs_root or temp_root.is_relative_to(runs_root) or runs_root.is_relative_to(temp_root):
        raise ValueError("Package, temp and runs roots must be separate")
    stack_path = package / "stackup.json"
    stack_sha = hashlib.sha256(stack_path.read_bytes()).hexdigest()
    plan = import_cam_package(package, load_stackup(stack_path))
    stack, regions = geometry_inputs(plan)
    def check_inputs():
        if hashlib.sha256(stack_path.read_bytes()).hexdigest() != stack_sha or any(hashlib.sha256((package / path).read_bytes()).hexdigest() != sha for path, sha in plan["file_hashes"].items()):
            raise RuntimeError("CAM/stackup input changed during reconstruction")
    check_inputs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    name = "cam_rebuild_" + stamp
    work, out = temp_root / name, runs_root / name
    work.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=False)
    target = work / (name + ".aedt")
    manifest = {"status": "started", "package": str(package), "working": str(target), "owned_desktop": True,
        "solver_called": False, "non_graphical_requested": non_graphical, "purpose": "geometry/material verification; no EM recipe or EM equivalence claim",
        "metallization_model": "zero-thickness ideal PEC walls; no finite plating thickness/loss inferred",
        "stackup_sha256": stack_sha, "file_hashes": plan["file_hashes"]}
    def persist():
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    persist()
    desktop = None
    transport_changed = False
    try:
        from ansys.aedt.core import Desktop, __version__ as pyaedt_version
        from ansys.aedt.core.generic.settings import settings
        from optimizer.modeling.via_creation import NativeViaBackend, snapshot_differences
        previous_transport = settings.use_grpc_api
        settings.use_grpc_api = False
        transport_changed = True
        desktop = Desktop(version=aedt_version, new_desktop=True, non_graphical=non_graphical, close_on_exit=False)
        manifest.update(aedt_pid=desktop.aedt_process_id, pyaedt_version=pyaedt_version, aedt_version=str(desktop.odesktop.GetVersion()))
        manifest["non_graphical_actual"] = bool(desktop.odesktop.GetIsNonGraphical())
        if manifest["non_graphical_actual"] != non_graphical:
            raise RuntimeError("AEDT graphical mode differs from requested mode")
        persist()
        project = desktop.odesktop.NewProject()
        project.InsertDesign("HFSS", "cam_geometry", "DrivenModal", "")
        if project.SaveAs(str(target), True) is False:
            raise RuntimeError("Initial project save failed")
        design = project.SetActiveDesign("cam_geometry")
        design.SetSolutionType(design.GetSolutionType(), ["NAME:Options", "EnableAutoOpen:=", False])
        editor = design.SetActiveEditor("3D Modeler")
        editor.SetModelUnits(["NAME:Units Parameter", "Units:=", "mm", "Rescale:=", False])
        guard = NativeViaBackend(project, design, source=stack_path, working=target, temp_root=temp_root)
        guard.assert_isolated_workspace()
        built = create_geometry(project, design, plan, stack)
        first = verify_geometry(project, design, stack, regions, built)
        snapshot = guard.snapshot(guard.names())
        manifest.update(measurements_before_save=first, snapshot_before_save=snapshot,
            layer_objects=built[0], material_names=built[1], source_mapping=built[3])
        persist()
        check_inputs()
        if project.Save() is False or not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("Native project save failed")
        saved_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        desktop.odesktop.CloseProject(target.stem)
        desktop.odesktop.OpenProject(str(target))
        project = desktop.odesktop.SetActiveProject(target.stem)
        design = project.SetActiveDesign("cam_geometry")
        guard = NativeViaBackend(project, design, source=stack_path, working=target, temp_root=temp_root)
        guard.assert_isolated_workspace()
        second = verify_geometry(project, design, stack, regions, built)
        manifest.update(measurements_after_reopen=second, snapshot_after_reopen=guard.snapshot(guard.names()))
        manifest["reopen_differences"] = snapshot_differences(first, second) + snapshot_differences(snapshot, manifest["snapshot_after_reopen"])
        persist()
        if manifest["reopen_differences"]:
            raise RuntimeError("Saved/reopened geometry differs")
        check_inputs()
        if hashlib.sha256(target.read_bytes()).hexdigest() != saved_sha:
            raise RuntimeError("Saved bytes changed while reopening")
        result = out / "rebuilt.aedt"
        shutil.copy2(target, result)
        if hashlib.sha256(result.read_bytes()).hexdigest() != saved_sha:
            raise RuntimeError("Archived project differs")
        manifest.update(status="completed_geometry", saved_sha256=saved_sha, model=str(result), measurements=second,
            layer_objects=built[0], material_names=built[1], source_mapping=built[3], input_unchanged=True, saved_reopened=True)
    except Exception as exc:
        manifest.update(status="failed", reason=repr(exc))
        raise
    finally:
        if desktop is not None:
            try:
                if target.stem in desktop.project_list():
                    desktop.odesktop.CloseProject(target.stem)
                if desktop.release_desktop(close_projects=True, close_on_exit=True) is False:
                    raise RuntimeError("Owned desktop did not close")
                manifest["owned_desktop_closed"] = True
            except Exception as exc:
                manifest.update(status="failed", cleanup_error=repr(exc), owned_desktop_closed=False)
        if transport_changed:
            settings.use_grpc_api = previous_transport
        persist()
    if manifest["status"] != "completed_geometry":
        raise RuntimeError("CAD cleanup failed; see " + str(out / "manifest.json"))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild supported actual CAM in a new owned AEDT desktop; geometry only, no solve.")
    parser.add_argument("package", type=Path)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--aedt-version", required=True)
    parser.add_argument("--gui", action="store_true", help="Visible owned session for requested visual review; default is non-GUI.")
    args = parser.parse_args(argv)
    try:
        out = rebuild_package(args.package, temp_root=args.temp_root, runs_root=args.runs_root, aedt_version=args.aedt_version, non_graphical=not args.gui)
    except MissingInputsError as exc:
        print(json.dumps({"status": "needs_input", "missing": list(exc.fields), "cad_modified": False, "solver_called": False}))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "completed_geometry", "report": str(out / "manifest.json"), "model": str(out / "rebuilt.aedt"), "solver_called": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
