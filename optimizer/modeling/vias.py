"""Data-only via planning. Applying/replacing geometry belongs to the AEDT service.

Solid EM pins and plated manufacturing barrels have distinct explicit intent.
Planning does not connect to AEDT, modify a model, or infer a drill from a pin.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .path_geometry import POINT_TOLERANCE_MM, PathSample, eval_length_mm, prepare_polylines, sample_path


def _finite_nonnegative(value, name, *, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if isinstance(value, bool) or not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'} and finite")
    return number


@dataclass(frozen=True)
class ViaIntent:
    kind: str = "solid_pin"
    start_layer: str | None = None
    end_layer: str | None = None
    finished_hole_diameter_mm: float | None = None
    plating_thickness_mm: float | None = None

    def __post_init__(self):
        if self.kind not in {"solid_pin", "plated_barrel"}:
            raise ValueError("Via intent must be solid_pin or plated_barrel")
        if self.kind == "solid_pin":
            if self.finished_hole_diameter_mm is not None or self.plating_thickness_mm is not None:
                raise ValueError("A solid EM pin must not implicitly define a fabrication drill")
        else:
            if not isinstance(self.start_layer, str) or not isinstance(self.end_layer, str) or not self.start_layer.strip() or not self.end_layer.strip() or self.start_layer == self.end_layer:
                raise ValueError("A plated barrel requires distinct start/end layers")
            object.__setattr__(self, "finished_hole_diameter_mm", _finite_nonnegative(self.finished_hole_diameter_mm, "finished hole diameter", positive=True))
            object.__setattr__(self, "plating_thickness_mm", _finite_nonnegative(self.plating_thickness_mm, "plating thickness", positive=True))


@dataclass(frozen=True)
class CircularKeepout:
    center_xy_mm: tuple[float, float]
    radius_mm: float
    clearance_mm: float = 0.0
    name: str = "keepout"

    def __post_init__(self):
        if len(self.center_xy_mm) != 2 or not all(math.isfinite(float(item)) for item in self.center_xy_mm):
            raise ValueError("Keepout center must have two finite coordinates")
        object.__setattr__(self, "center_xy_mm", tuple(float(item) for item in self.center_xy_mm))
        object.__setattr__(self, "radius_mm", _finite_nonnegative(self.radius_mm, "keepout radius"))
        object.__setattr__(self, "clearance_mm", _finite_nonnegative(self.clearance_mm, "keepout clearance"))


@dataclass(frozen=True)
class ViaPlan:
    prefix: str
    radius_expression: str
    z_start_expression: str
    height_expression: str
    radius_mm: float
    z_start_mm: float
    height_mm: float
    spacing_mm: float
    spacing_rule: str
    minimum_center_distance_mm: float
    minimum_edge_clearance_mm: float
    path: PathSample
    centers_mm: tuple[tuple[float, float, float], ...]
    intent: ViaIntent
    source_json: str

    @property
    def names(self):
        return tuple(f"{self.prefix}_{index}" for index in range(1, len(self.centers_mm) + 1))

    def to_dict(self):
        data = asdict(self)
        data["geometry_source"] = json.loads(data.pop("source_json"))
        data["names"] = list(self.names)
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        data["plan_sha256"] = hashlib.sha256(raw).hexdigest()
        return data


def _check_clearances(centers, radius_mm, minimum_distance_mm, keepouts):
    # Neighbour buckets prove the all-pairs minimum without an O(N^2) scan.
    buckets = {}
    for index, center in enumerate(centers):
        try:
            cell = tuple(math.floor(center[axis] / minimum_distance_mm) for axis in (0, 1))
        except (OverflowError, ValueError) as exc:
            raise ValueError("Coordinate/clearance exceeds numeric range") from exc
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in buckets.get((cell[0] + dx, cell[1] + dy), ()):
                    distance = math.dist(center[:2], centers[other_index][:2])
                    tolerance = min(POINT_TOLERANCE_MM, minimum_distance_mm * 1e-8)
                    if distance == 0 or distance + tolerance < minimum_distance_mm:
                        raise ValueError(f"Via centers {other_index + 1}/{index + 1} violate minimum clearance")
        buckets.setdefault(cell, []).append(index)
        for keepout in keepouts:
            distance = math.dist(center[:2], keepout.center_xy_mm)
            required = radius_mm + keepout.radius_mm + keepout.clearance_mm
            if distance + min(POINT_TOLERANCE_MM, required * 1e-8) < required:
                # Dropping endpoints/corners or opening gaps would change the stated path policy.
                raise ValueError(f"Via {index + 1} violates circular keepout {keepout.name!r}")


def build_via_plan(
    polylines, variables, *, prefix, spacing_mm, radius, z_start, height,
    closed=None, spacing_rule="max", minimum_center_distance_mm=0.0,
    minimum_edge_clearance_mm=0.0, keepouts=(), intent=None, geometry_source=None,
):
    """Compile a checked plan from explicitly supplied geometry and variable snapshot.

    spacing_rule measures each segment's arc length. All cylinders use Z direction;
    physical centers use z_start, and clearance is checked on actual XY placement.
    Circular keepouts apply to the whole extrusion. Unsupported expressions,
    branch/disconnected paths, incompatible endpoints and collisions fail closed.
    """
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", prefix):
        raise ValueError("Via prefix must be an ASCII identifier")
    expressions = (str(radius), str(z_start), str(height))
    radius_mm, z_start_mm, height_mm = [eval_length_mm(expr, variables) for expr in expressions]
    _finite_nonnegative(radius_mm, "via radius", positive=True)
    _finite_nonnegative(height_mm, "via height", positive=True)
    if not math.isfinite(z_start_mm + height_mm) or z_start_mm + height_mm == z_start_mm:
        raise ValueError("Via vertical extent cannot be represented as finite coordinates")
    min_center = _finite_nonnegative(minimum_center_distance_mm, "minimum center distance")
    min_edge = _finite_nonnegative(minimum_edge_clearance_mm, "minimum edge clearance")
    required_distance = max(min_center, 2 * radius_mm + min_edge)
    if not math.isfinite(required_distance):
        raise ValueError("Via clearance exceeds numeric range")
    intent = ViaIntent() if intent is None else intent
    if not isinstance(intent, ViaIntent):
        raise ValueError("A validated ViaIntent is required")
    if intent.kind == "plated_barrel":
        expected = intent.finished_hole_diameter_mm / 2 + intent.plating_thickness_mm
        if not math.isclose(radius_mm, expected, rel_tol=1e-9, abs_tol=POINT_TOLERANCE_MM):
            raise ValueError("Barrel outer radius differs from finished hole plus plating")
    if closed is None:
        if len(polylines) != 1:
            raise ValueError("Composite paths require an explicit closed flag")
        closed = polylines[0].get("closed", False)
    path = sample_path(prepare_polylines(polylines, variables), spacing_mm, closed, spacing_rule)
    centers = tuple((point[0], point[1], z_start_mm) for point in path.points)
    keepouts = tuple(keepouts)
    if not all(isinstance(item, CircularKeepout) for item in keepouts):
        raise ValueError("Keepouts must be validated circular keepout records")
    _check_clearances(centers, radius_mm, required_distance, keepouts)
    snapshot = {"polylines": polylines, "variables": variables}
    snapshot_sha = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    source = dict(geometry_source or {"mode": "provided_geometry"})
    if source.get("mode") not in {"provided_geometry", "file_history_snapshot", "live_snapshot"}:
        raise ValueError("Geometry source mode must be explicit")
    source["geometry_variables_sha256"] = snapshot_sha
    source_json = json.dumps(source, sort_keys=True, allow_nan=False)
    return ViaPlan(prefix, *expressions, radius_mm, z_start_mm, height_mm, float(spacing_mm), spacing_rule,
                   required_distance, min_edge, path, centers, intent, source_json)


def write_via_plan_csv(plan: ViaPlan, path: Path):
    """Export exact path lengths and actual cylinder bottom coordinates; never overwrite."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["plan_sha256", plan.to_dict()["plan_sha256"]])
        writer.writerow(["source_mode", json.loads(plan.source_json)["mode"]])
        writer.writerow(["intent", plan.intent.kind])
        writer.writerow(["closed", plan.path.closed])
        writer.writerow(["path_length_mm", f"{plan.path.total_length_mm:.12g}"])
        writer.writerow(["nominal_spacing_mm", plan.spacing_mm, "spacing_rule", plan.spacing_rule])
        writer.writerow(["radius_expression", plan.radius_expression, "height_expression", plan.height_expression])
        writer.writerow(["point_count", len(plan.centers_mm)])
        writer.writerow([])
        writer.writerow(["name", "x_mm", "y_mm", "bottom_z_mm", "path_z_mm", "previous_arclength_step_mm", "previous_center_distance_mm"])
        for index, (name, center, source_point, step) in enumerate(zip(plan.names, plan.centers_mm, plan.path.points, plan.path.previous_arclength_steps_mm)):
            previous_distance = math.dist(plan.centers_mm[index - 1], center) if index or plan.path.closed else 0.0
            writer.writerow([name, *[f"{value:.12g}" for value in center], f"{source_point[2]:.12g}", f"{step:.12g}", f"{previous_distance:.12g}"])
