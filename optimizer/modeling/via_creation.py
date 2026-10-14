"""Checked first-time solid via creation with a verified project identity.

Existing arrays require an exact verified ownership record for replacement.
The default requires an isolated work project. An explicitly
requested standard-source update requires a distinct byte-verified backup.
No prefix deletion or solver calls occur.
"""
from __future__ import annotations

import json
import hashlib
import math
import re
import uuid
from pathlib import Path

from .path_geometry import eval_length_mm, prepare_polylines


def capture_live_line_path(editor, name, *, closed):
    """Read final native edges, rejecting curves instead of treating them as chords."""
    if editor.GetModelUnits() != "mm":
        raise ValueError("Live via capture currently requires model units mm")
    points, segments, edges = [], [], []
    for edge_id in editor.GetEdgeIDsFromObject(name):
        vertex_ids = list(editor.GetVertexIDsFromEdge(edge_id))
        if len(vertex_ids) != 2:
            raise ValueError("Live line capture requires two vertices per edge")
        endpoints = [tuple(float(v) for v in editor.GetVertexPosition(i)) for i in vertex_ids]
        length = float(editor.GetEdgeLength(edge_id))
        middle = tuple(float(v) for v in editor.GetEdgePositionAtNormalizedParameter(edge_id, 0.5))
        if not all(math.isfinite(v) for point in endpoints + [middle] for v in point):
            raise ValueError("Nonfinite native path geometry")
        if not math.isfinite(length) or length <= 0 or not math.isclose(length, math.dist(*endpoints), abs_tol=1e-8, rel_tol=1e-9):
            raise ValueError("Live edge is curved or degenerate; line capture refused")
        if math.dist(middle, tuple((a + b) / 2 for a, b in zip(*endpoints))) > 1e-8:
            raise ValueError("Live edge midpoint does not match a line")
        segments.append({"SegmentType": "Line", "StartIndex": len(points), "NoOfPoints": 2})
        points.extend({axis: f"{value:.17g}mm" for axis, value in zip("xyz", point)} for point in endpoints)
        edges.append({"edge_id": int(edge_id), "endpoints_mm": endpoints, "length_mm": length})
    if not segments:
        raise ValueError("Path has no native edges")
    return {"name": name, "closed": bool(closed), "points": points, "segments": segments}, edges


def line_position_expressions(plan, polyline, variables):
    """Preserve parameterized line positions only after matching final native edges.

    The plan may order/reverse edges differently from file history. Matching uses
    undirected endpoint pairs, then interpolation in the original expression.
    """
    prepared_points, _, _ = prepare_polylines([polyline], variables)[0]
    source_edges = []
    for segment in polyline["segments"]:
        if segment["SegmentType"] != "Line":
            raise ValueError("Parameterized position capture currently supports lines only")
        start = int(segment["StartIndex"])
        numeric = [prepared_points[i] for i in (start, start + 1)]
        source_edges.append((numeric, [polyline["points"][i] for i in (start, start + 1)]))
    # Native geometry is supplied by the caller and checked against every source
    # edge, including unused endpoints; never infer final geometry from history.
    native_edges = json.loads(plan.source_json).get("native_edges", [])
    if len(native_edges) != len(source_edges):
        raise ValueError("Native/file path edge counts differ")
    unmatched = list(source_edges)
    for edge in native_edges:
        a, b = edge["endpoints_mm"]
        matches = [i for i, (numeric, _) in enumerate(unmatched)
                   if (math.dist(a, numeric[0]) < 1e-8 and math.dist(b, numeric[1]) < 1e-8)
                   or (math.dist(a, numeric[1]) < 1e-8 and math.dist(b, numeric[0]) < 1e-8)]
        if len(matches) != 1:
            raise ValueError("File expressions do not uniquely match final native path")
        unmatched.pop(matches[0])
    positions = []
    for point in plan.path.points:
        result = None
        for (a, b), expressions in source_edges:
            delta = tuple(y - x for x, y in zip(a, b))
            length2 = sum(v * v for v in delta)
            if length2 <= 1e-18:
                raise ValueError("Degenerate source line")
            t = sum((p - x) * d for p, x, d in zip(point, a, delta)) / length2
            projected = tuple(x + t * d for x, d in zip(a, delta))
            if -1e-9 <= t <= 1 + 1e-9 and math.dist(point, projected) < 1e-8:
                t = max(0.0, min(1.0, t))
                result = tuple(expressions[0][axis] if t == 0 else expressions[1][axis] if t == 1
                               else f"({expressions[0][axis]})+({t:.17g})*(({expressions[1][axis]})-({expressions[0][axis]}))"
                               for axis in "xy")
                break
        if result is None:
            raise ValueError("Via point does not match a source line")
        positions.append(result)
    return tuple(positions)


class NativeViaBackend:
    """Small native editor interface; all reads bypass PyAEDT object caches."""
    def __init__(self, project, design, *, source, working, temp_root, source_update_backup=None):
        self.project, self.design = project, design
        self.editor = design.SetActiveEditor("3D Modeler")
        self.source, self.working, self.temp_root = map(lambda p: Path(p).resolve(), (source, working, temp_root))
        self.source_update_backup = Path(source_update_backup).resolve() if source_update_backup else None

    def assert_isolated_workspace(self):
        actual = (Path(self.project.GetPath()) / (self.project.GetName() + ".aedt")).resolve()
        if self.source_update_backup is not None:
            backup = self.source_update_backup
            if actual != self.source or self.working != self.source or backup == self.source:
                raise ValueError("Explicit source update identity/backup mismatch")
            if hashlib.sha256(backup.read_bytes()).digest() != hashlib.sha256(self.source.read_bytes()).digest():
                raise ValueError("Source-update backup does not match the saved source")
        elif actual != self.working or self.working == self.source or not self.working.is_relative_to(self.temp_root):
            raise ValueError("Via creation requires the verified isolated temp project")
        if self.editor.GetModelUnits() != "mm":
            raise ValueError("Via creation currently requires model units mm")

    def names(self):
        return set(str(name) for group in ("Solids", "Sheets", "Lines", "Unclassified")
                   for name in self.editor.GetObjectsInGroup(group))

    def variables(self):
        return {str(name): str(owner.GetVariableValue(name))
                for owner in (self.project, self.design) for name in owner.GetVariables()}

    def snapshot(self, names):
        result = {}
        for name in sorted(names):
            group = next(group for group in ("Solids", "Sheets", "Lines", "Unclassified")
                         if name in self.editor.GetObjectsInGroup(group))
            result[name] = {"group": group, "bbox_mm": [float(v) for v in self.editor.GetObjectBoundingBox(name)]}
            if group == "Solids":
                result[name]["volume_mm3"] = float(self.editor.GetObjectVolume(name))
                result[name]["attributes"] = self.attributes(name)
        return result

    def attributes(self, name):
        tab = "Geometry3DAttributeTab"
        available = set(self.editor.GetProperties(tab, name))
        if not {"Model", "Color"}.issubset(available):
            raise ValueError(f"Unsupported model attributes for {name}")
        model = str(self.editor.GetPropertyValue(tab, name, "Model"))
        result = {"Model": model, "Color": str(self.editor.GetPropertyValue(tab, name, "Color"))}
        # AEDT hides material/solve-inside properties for non-model solids.
        # Preserve their geometry and model state; never issue unsupported reads.
        for prop in ("Material", "Solve Inside"):
            if prop in available:
                result[prop] = str(self.editor.GetPropertyValue(tab, name, prop))
            elif model.lower() == "false":
                result[prop] = None
            else:
                raise ValueError(f"Model solid {name} does not expose {prop}")
        for prop in ("Transparent", "Orientation", "Group", "Display Wireframe", "Material Appearance"):
            if prop in available:
                result[prop] = str(self.editor.GetPropertyValue(tab, name, prop))
        return result

    def create(self, name, plan, xy, color):
        self.editor.CreateCylinder(
            ["NAME:CylinderParameters", "XCenter:=", xy[0], "YCenter:=", xy[1],
             "ZCenter:=", plan.z_start_expression, "Radius:=", plan.radius_expression,
             "Height:=", plan.height_expression, "WhichAxis:=", "Z", "NumSides:=", "0"],
            ["NAME:Attributes", "Name:=", name, "Flags:=", "", "Color:=", f"({color[0]} {color[1]} {color[2]})",
             "Transparency:=", 0, "PartCoordinateSystem:=", "Global", "MaterialValue:=", '"copper"',
             "SolveInside:=", False])

    def rename(self, old, new):
        self.editor.ChangeProperty(["NAME:AllTabs", ["NAME:Geometry3DAttributeTab",
                                  ["NAME:PropServers", old], ["NAME:ChangedProps", ["NAME:Name", "Value:=", new]]]])

    def delete(self, names):
        if names:
            self.editor.Delete(["NAME:Selections", "Selections:=", ",".join(sorted(names))])

    def restore(self, name, observation):
        command = observation["command"]
        xy_z = [v.strip() for v in command["Center Position"].split(",")]
        attrs = observation["attributes"]
        validate_restorable_cylinder(observation)
        packed = int(attrs["Color"])
        from types import SimpleNamespace
        old = SimpleNamespace(z_start_expression=xy_z[2], radius_expression=command["Radius"], height_expression=command["Height"])
        result = self.create(name, old, xy_z[:2], (packed & 255, (packed >> 8) & 255, (packed >> 16) & 255))
        if result is False:
            return False
        changes = []
        for prop in ("Transparent", "Orientation", "Group", "Display Wireframe", "Material Appearance"):
            if prop in attrs:
                value = attrs[prop]
                if prop in ("Display Wireframe", "Material Appearance"):
                    value = value.lower() == "true"
                changes.append(["NAME:" + prop, "Value:=", value])
        if changes:
            return self.editor.ChangeProperty(["NAME:AllTabs", ["NAME:Geometry3DAttributeTab",
                ["NAME:PropServers", name], ["NAME:ChangedProps", *changes]]])

    def inspect(self, name):
        server, tab = name + ":CreateCylinder:1", "Geometry3DCmdTab"
        command = {str(prop): str(self.editor.GetPropertyValue(tab, server, prop))
                   for prop in self.editor.GetProperties(tab, server)}
        return {"bbox_mm": [float(v) for v in self.editor.GetObjectBoundingBox(name)],
                "volume_mm3": float(self.editor.GetObjectVolume(name)),
                "attributes": self.attributes(name), "command": command}

    def save(self):
        return self.project.Save()


def verify_cylinder(observed, plan, center, xy, color):
    x, y, z = center
    r, h = plan.radius_mm, plan.height_mm
    bbox = (x - r, y - r, z, x + r, y + r, z + h)
    if len(observed["bbox_mm"]) != 6 or any(not math.isclose(a, b, abs_tol=1e-8, rel_tol=1e-9)
                                            for a, b in zip(observed["bbox_mm"], bbox)):
        raise ValueError("Native via bounding box differs from plan")
    if not math.isclose(observed["volume_mm3"], math.pi * r * r * h, rel_tol=1e-7, abs_tol=1e-12):
        raise ValueError("Native via volume differs from analytic cylinder")
    attrs = observed["attributes"]
    if attrs["Model"].lower() != "true" or not isinstance(attrs["Material"], str) or not isinstance(attrs["Solve Inside"], str) or attrs["Material"].strip('"').lower() != "copper" or attrs["Solve Inside"].lower() != "false":
        raise ValueError("Via must be a model copper body with Solve Inside disabled")
    packed = int(attrs["Color"])
    if (packed & 255, (packed >> 8) & 255, (packed >> 16) & 255) != tuple(color):
        raise ValueError("Native via color differs from requested RGB")
    command = observed["command"]
    position = tuple(part.strip() for part in command.get("Center Position", "").split(","))
    if position != (*xy, plan.z_start_expression):
        raise ValueError("Via center expressions differ from requested parameterization")
    expected = {"Radius": plan.radius_expression, "Height": plan.height_expression, "Axis": "Z",
                "Coordinate System": "Global", "Command": "CreateCylinder", "Number of Segments": "0"}
    for prop, expression in expected.items():
        if command.get(prop) != expression:
            raise ValueError(f"Via parameter expression mismatch: {prop}: {command.get(prop)!r}")


def validate_restorable_cylinder(observation):
    """Reject ownership that the native reconstruction cannot faithfully restore."""
    c, a = observation["command"], observation["attributes"]
    if (any(c.get(key) != value for key, value in {
            "Command": "CreateCylinder", "Axis": "Z", "Coordinate System": "Global",
            "Number of Segments": "0"}.items())
            or str(a.get("Material")).strip('"').lower() != "copper"
            or str(a.get("Model")).lower() != "true"
            or str(a.get("Solve Inside")).lower() != "false"
            or a.get("Orientation", "Global") != "Global"):
        raise ValueError("Replacement requires owned plain global round model copper cylinders with Solve Inside disabled")


def snapshot_differences(expected, actual, path=""):
    """Strict structure/attributes, bounded floating-point CAD read tolerance."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return [{"path": path, "expected_keys": sorted(expected), "actual_keys": sorted(actual)}]
        return [diff for key in expected for diff in snapshot_differences(expected[key], actual[key], path + "/" + key)]
    if isinstance(expected, (tuple, list)) and isinstance(actual, (tuple, list)):
        if len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        return [diff for i, (a, b) in enumerate(zip(expected, actual)) for diff in snapshot_differences(a, b, path + f"/{i}")]
    if type(expected) in (int, float) and type(actual) in (int, float):
        tolerance = 1e-8 if "/bbox_mm/" in path else 1e-12
        if math.isfinite(expected) and math.isfinite(actual) and math.isclose(expected, actual, abs_tol=tolerance, rel_tol=1e-9):
            return []
    elif expected == actual:
        return []
    return [{"path": path, "expected": expected, "actual": actual}]


def create_checked_vias(backend, plan, *, positions=None, color=(0, 0, 255), emit=None, owned_existing=None):
    """Stage/verify/rename/verify/save vias with exact creation/replacement ownership.

    Runs inside an exclusively controlled work or explicitly backed-up source session. A prefix/name
    collision refuses creation unless owned_existing exactly covers that array.
    Existing objects are never deleted by prefix.
    Saving may return None on native COM success; explicit False is a failure.
    """
    if plan.intent.kind != "solid_pin":
        raise ValueError("Plated barrel construction is not implemented by this backend")
    if len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
        raise ValueError("Color must be three integer RGB channels")
    if positions is None:
        positions = tuple((f"{x:.17g}mm", f"{y:.17g}mm") for x, y, _ in plan.centers_mm)
    if len(positions) != len(plan.names):
        raise ValueError("Position expression count differs from plan")
    # Expressions must resolve to planned centers before any editor write.
    # The supplied plan snapshot must contain its variable values explicitly.
    variables = json.loads(plan.source_json).get("variables", {})
    for xy, center in zip(positions, plan.centers_mm):
        if len(xy) != 2 or any(not math.isclose(eval_length_mm(expr, variables), value, abs_tol=1e-8, rel_tol=1e-9)
                              for expr, value in zip(xy, center)):
            raise ValueError("Position expressions differ from planned native geometry")
    emit = (lambda event, **data: None) if emit is None else emit
    backend.assert_isolated_workspace()
    actual_variables = backend.variables()
    for expression, expected in zip((plan.radius_expression, plan.z_start_expression, plan.height_expression),
                                    (plan.radius_mm, plan.z_start_mm, plan.height_mm)):
        if not math.isclose(eval_length_mm(expression, actual_variables), expected, abs_tol=1e-9, rel_tol=1e-9):
            raise ValueError("Live via dimensions changed after planning")
    for xy, center in zip(positions, plan.centers_mm):
        if any(not math.isclose(eval_length_mm(expr, actual_variables), value, abs_tol=1e-8, rel_tol=1e-9)
               for expr, value in zip(xy, center)):
            raise ValueError("Live via positions changed after planning")
    before = backend.names()
    existing_prefix = {name for name in before if re.fullmatch(re.escape(plan.prefix) + r"_\d+", name)}
    previous = {} if owned_existing is None else owned_existing
    if existing_prefix and owned_existing is None:
        raise ValueError("Existing via prefix is not owned by this creation; replacement refused")
    if owned_existing is not None:
        if set(previous) != existing_prefix or not previous:
            raise ValueError("Ownership manifest does not exactly match the existing array")
        for name, expected in previous.items():
            if snapshot_differences(expected, backend.inspect(name)):
                raise ValueError("Owned via was modified since ownership validation")
            validate_restorable_cylinder(expected)
    retained = before - set(previous)
    protected = backend.snapshot(retained)
    token = uuid.uuid4().hex[:12]
    staged = tuple(f"hh_via_stage_{token}_{i}" for i in range(1, len(plan.names) + 1))
    if set(staged) & before:
        raise ValueError("Staging name collision")
    backups = {name: f"hh_via_previous_{token}_{i}" for i, name in enumerate(previous, 1)}
    if set(backups.values()) & before:
        raise ValueError("Backup object name collision")
    created_names, renamed_previous = set(staged), {}
    emit("via_creation_started", plan_sha256=plan.to_dict()["plan_sha256"], count=len(staged), protected_before=protected)
    try:
        for name, center, xy in zip(staged, plan.centers_mm, positions):
            result = backend.create(name, plan, xy, color)
            if result is False or name not in backend.names():
                raise RuntimeError(f"Native cylinder creation failed: {name}")
            verify_cylinder(backend.inspect(name), plan, center, xy, color)
            emit("via_staged_verified", name=name)
        for old, new in zip(staged, plan.names):
            # Previous names are displaced only after all candidates are verified.
            if not renamed_previous and previous:
                for original, backup_name in backups.items():
                    renamed_previous[original] = backup_name
                    if backend.rename(original, backup_name) is False or backup_name not in backend.names() or original in backend.names():
                        raise RuntimeError("Owned previous via rename failed")
            created_names.add(new)
            result = backend.rename(old, new)
            if result is False or old in backend.names() or new not in backend.names():
                raise RuntimeError(f"Native rename failed: {old}")
        differences = snapshot_differences(protected, backend.snapshot(retained))
        expected_names = retained | set(plan.names) | set(backups.values())
        if backend.names() != expected_names or differences:
            emit("protected_object_check_failed", differences=differences, expected_names=sorted(expected_names),
                 actual_names=sorted(backend.names()))
            raise RuntimeError("Via creation changed protected objects or introduced unexpected objects")
        observations = {name: backend.inspect(name) for name in plan.names}
        for name, center, xy in zip(plan.names, plan.centers_mm, positions):
            verify_cylinder(observations[name], plan, center, xy, color)
        if backups:
            backend.delete(set(backups.values()))
            if backend.names() != retained | set(plan.names):
                raise RuntimeError("Owned previous via cleanup failed")
        if backend.save() is False:
            raise RuntimeError("Native project save failed")
        emit("via_creation_committed", names=list(plan.names), observations=observations)
        return {"names": list(plan.names), "observations": observations, "protected_before": protected,
                "protected_after": backend.snapshot(retained), "color_rgb": list(color), "intent": "solid_pin",
                "replaced_names": list(previous)}
    except Exception as exc:
        try:
            backend.delete(backend.names() & created_names)
            for name, backup_name in renamed_previous.items():
                if backup_name in backend.names():
                    if backend.rename(backup_name, name) is False:
                        raise RuntimeError("Previous array rollback rename failed")
                elif name not in backend.names():
                    if backend.restore(name, previous[name]) is False:
                        raise RuntimeError("Previous array rollback reconstruction failed")
            differences = snapshot_differences(protected, backend.snapshot(retained))
            differences += [d for name, expected in previous.items() for d in snapshot_differences(expected, backend.inspect(name))]
            if backend.names() != before or differences:
                emit("rollback_object_check_failed", differences=differences, expected_names=sorted(before), actual_names=sorted(backend.names()))
                raise RuntimeError("Rollback did not restore protected work-project geometry")
            emit("via_creation_rolled_back", reason=str(exc))
        except Exception as rollback_exc:
            emit("via_creation_rollback_failed", reason=str(exc), rollback_reason=str(rollback_exc))
            raise RuntimeError(f"Via creation failed; work project requires inspection: {rollback_exc}") from exc
        raise
