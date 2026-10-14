"""Verify line/angular-arc history against final CAD before preserving expressions."""
from __future__ import annotations

import json
import math

from .path_geometry import _angle_degrees, _arc_geometry, prepare_polylines
from .via_creation import line_position_expressions

TOLERANCE_MM = 1e-8
PLANES = {"XY": (0, 1), "YZ": (1, 2), "ZX": (2, 0)}


def _records(polyline, variables):
    points, segments, closed = prepare_polylines([polyline], variables)[0]
    records = []
    for raw, segment in zip(polyline["segments"], segments):
        kind, index = segment["SegmentType"], int(segment["StartIndex"])
        if kind == "Line":
            a, b = points[index:index + 2]
            length = math.dist(a, b)
            if length <= 1e-9:
                raise ValueError("Degenerate source line")
            at = lambda t, a=a, b=b: tuple(x + t * (y - x) for x, y in zip(a, b))
        elif kind == "AngularArc":
            # Constant rotation coefficients retain parameterized radius/center.
            # Variable sweep angles require a different expression compiler.
            try:
                _angle_degrees(raw["ArcAngle"], {})
            except ValueError as exc:
                raise ValueError("Live angular via positions require a constant arc angle; variable angles unsupported") from exc
            if segment.get("ArcPlane") not in PLANES:
                raise ValueError("Live angular via capture requires explicit XY/YZ/ZX plane")
            length, at, a, b = _arc_geometry(points, segment)
        else:
            raise ValueError(f"Unsupported live path segment {kind!r}")
        records.append({"kind": kind, "index": index, "raw": raw, "segment": segment,
                        "points": points, "length": length, "at": at})
    if not records:
        raise ValueError("Empty path history")
    return records, points, segments, closed


def _match(records, native_edges):
    if len(records) != len(native_edges):
        raise ValueError("Native/file path edge counts differ")
    unmatched = list(records)
    for edge in native_edges:
        endpoints = edge["endpoints_mm"]
        samples = edge["samples_mm"]
        if len(endpoints) != 2 or len(samples) != 3 or any(
            len(p) != 3 or not all(math.isfinite(v) for v in p) for p in endpoints + samples
        ) or not math.isfinite(edge["length_mm"]) or edge["length_mm"] <= 0:
            raise ValueError("Incomplete or invalid native edge provenance")
        matches = []
        for index, record in enumerate(unmatched):
            for reverse in (False, True):
                fractions = (1.0, 0.0) if reverse else (0.0, 1.0)
                if any(math.dist(p, record["at"](t)) > TOLERANCE_MM for p, t in zip(endpoints, fractions)):
                    continue
                if not math.isclose(edge["length_mm"], record["length"], abs_tol=TOLERANCE_MM, rel_tol=1e-9):
                    continue
                if any(math.dist(p, record["at"](1 - t if reverse else t)) > TOLERANCE_MM
                       for p, t in zip(samples, (0.25, 0.5, 0.75))):
                    continue
                matches.append(index)
        if len(matches) != 1:
            raise ValueError("File path does not uniquely match final native endpoints, length and curve samples")
        unmatched.pop(matches[0])


def capture_live_path(editor, name, polyline, variables):
    """Read final geometry and verify all historical edges, including curvature."""
    records, points, segments, closed = _records(polyline, variables)
    if editor.GetModelUnits() != "mm":
        raise ValueError("Live via capture currently requires model units mm")
    native_edges = []
    for edge_id in editor.GetEdgeIDsFromObject(name):
        if len(list(editor.GetVertexIDsFromEdge(edge_id))) != 2:
            raise ValueError("Live path requires two native vertices per edge; split full-circle arcs")
        samples = [tuple(float(v) for v in editor.GetEdgePositionAtNormalizedParameter(edge_id, t))
                   for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
        length = float(editor.GetEdgeLength(edge_id))
        if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in samples) or not math.isfinite(length) or length <= 0:
            raise ValueError("Nonfinite or degenerate native path geometry")
        native_edges.append({"edge_id": int(edge_id), "endpoints_mm": [samples[0], samples[-1]],
                             "samples_mm": samples[1:-1], "length_mm": length})
    _match(records, native_edges)
    live = {"name": name, "closed": closed,
            "points": [{axis: f"{v:.17g}mm" for axis, v in zip("xyz", p)} for p in points],
            "segments": segments}
    return live, native_edges


def path_position_expressions(plan, polyline, variables):
    """Retain line interpolation or fixed-angle rotation of source expressions."""
    if all(segment["SegmentType"] == "Line" for segment in polyline["segments"]):
        return line_position_expressions(plan, polyline, variables)
    records, _, _, _ = _records(polyline, variables)
    _match(records, json.loads(plan.source_json).get("native_edges", []))
    positions = []
    for point in plan.path.points:
        expressions = None
        for record in records:
            index, segment = record["index"], record["segment"]
            a, b = record["at"](0), record["at"](1)
            source = polyline["points"]
            if record["kind"] == "Line":
                delta = tuple(y - x for x, y in zip(a, b))
                t = sum((p - x) * d for p, x, d in zip(point, a, delta)) / sum(d * d for d in delta)
                if not -1e-9 <= t <= 1 + 1e-9 or math.dist(point, record["at"](t)) > TOLERANCE_MM:
                    continue
                t = max(0.0, min(1.0, t))
                expressions = tuple(f"({source[index][axis]})+({t:.17g})*(({source[index+1][axis]})-({source[index][axis]}))"
                                    for axis in "xy")
            else:
                alpha, beta = PLANES[segment["ArcPlane"]]
                center = tuple(float(segment[f"ArcCenter{axis}"].removesuffix("mm")) for axis in "XYZ")
                da, db = a[alpha] - center[alpha], a[beta] - center[beta]
                pa, pb = point[alpha] - center[alpha], point[beta] - center[beta]
                theta = math.atan2(da * pb - db * pa, da * pa + db * pb)
                angle = math.radians(_angle_degrees(segment["ArcAngle"]))
                if angle > 0 and theta < -1e-12:
                    theta += 2 * math.pi
                if angle < 0 and theta > 1e-12:
                    theta -= 2 * math.pi
                t = theta / angle
                if not -1e-9 <= t <= 1 + 1e-9 or math.dist(point, record["at"](t)) > TOLERANCE_MM:
                    continue
                raw = record["raw"]
                axes = "xyz"
                ca, cb = raw[f"ArcCenter{axes[alpha].upper()}"], raw[f"ArcCenter{axes[beta].upper()}"]
                sa, sb = source[index][axes[alpha]], source[index][axes[beta]]
                c, s = math.cos(theta), math.sin(theta)
                rotated = dict(source[index])
                rotated[axes[alpha]] = f"({ca})+(({sa})-({ca}))*({c:.17g})-(({sb})-({cb}))*({s:.17g})"
                rotated[axes[beta]] = f"({cb})+(({sa})-({ca}))*({s:.17g})+(({sb})-({cb}))*({c:.17g})"
                expressions = tuple(rotated[axis] for axis in "xy")
            break
        if expressions is None:
            raise ValueError("Via point does not match a verified source edge")
        positions.append(expressions)
    return tuple(positions)
