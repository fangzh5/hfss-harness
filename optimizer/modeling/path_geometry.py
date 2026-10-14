from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Point = tuple[float, float, float]
MAX_PATH_POINTS = 10000
POINT_TOLERANCE_MM = 1e-9


def _evaluate_expression(expr, variables, factors, seen=None, units_used=None):
    seen = set() if seen is None else set(seen)
    if len(seen) > 64:
        raise ValueError("Expression dependency depth exceeds 64")
    normalized = str(expr).strip()
    if not normalized:
        raise ValueError("Empty expression")
    unit_pattern = "|".join(sorted((re.escape(unit) for unit in factors), key=len, reverse=True))
    pattern = rf"(?<![\w.$])((?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\s*({unit_pattern})\b"

    def replace_unit(match):
        if units_used is not None:
            units_used.append(True)
        return repr(float(match.group(1)) * factors[match.group(2).lower()])

    normalized = re.sub(pattern, replace_unit, normalized, flags=re.I)
    aliases = {}

    def replace_project_variable(match):
        alias = f"__hh_project_{len(aliases)}"
        while alias in variables or re.search(rf"\b{alias}\b", normalized):
            alias += "_"
        aliases[alias] = match.group()
        return alias

    normalized = re.sub(r"\$[A-Za-z_]\w*", replace_project_variable, normalized)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Unsupported expression or units: {expr!r}") from exc
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise ValueError("Expression exceeds 512 syntax nodes")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.Name):
            name = aliases.get(node.id, node.id)
            if name not in variables:
                raise ValueError(f"Unknown variable {name!r} in {expr!r}")
            if name in seen:
                raise ValueError(f"Recursive variable reference involving {name!r}")
            return _evaluate_expression(variables[name], variables, factors, seen | {name}, units_used)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError(f"Unsupported expression: {expr!r}")

    try:
        value = visit(tree)
    except (ArithmeticError, OverflowError) as exc:
        raise ValueError(f"Invalid expression arithmetic: {expr!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite expression: {expr!r}")
    return value


def eval_length_mm(expr, variables, _seen=None):
    """Restricted numeric AEDT arithmetic; unsuffixed lengths are millimetres."""
    return _evaluate_expression(expr, variables, {"mm": 1.0, "um": 0.001, "µm": 0.001,
                                                "nm": 1e-6, "cm": 10.0, "m": 1000.0,
                                                "mil": 0.0254, "in": 25.4}, _seen)


def _angle_degrees(value, variables=None):
    units_used = []
    result = _evaluate_expression(value, variables or {}, {"deg": math.pi / 180.0, "rad": 1.0}, units_used=units_used)
    return math.degrees(result) if units_used else result


def _parse_plain_mm(value):
    return eval_length_mm(value, {})


def _finite_point(point):
    if len(point) != 3 or any(isinstance(item, bool) for item in point):
        raise ValueError("Path points must have three finite numeric coordinates")
    result = tuple(float(item) for item in point)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("Nonfinite path coordinate")
    return result


def _dist(a, b):
    return math.dist(a, b)


def _lerp(a, b, t):
    return tuple(a[index] + (b[index] - a[index]) * t for index in range(3))


def _same_point(a, b, tol=POINT_TOLERANCE_MM):
    return _dist(a, b) <= tol


def _validate_spacing(spacing, spacing_rule):
    if isinstance(spacing, bool) or not math.isfinite(float(spacing)) or float(spacing) <= 0:
        raise ValueError("Spacing must be positive and finite")
    if spacing_rule not in {"max", "min"}:
        raise ValueError(f"Unsupported spacing_rule {spacing_rule!r}")


def _interval_count(length, spacing, spacing_rule):
    _validate_spacing(spacing, spacing_rule)
    if not math.isfinite(length) or length < 0:
        raise ValueError("Invalid segment length")
    if spacing_rule == "min" and length + POINT_TOLERANCE_MM < spacing:
        raise ValueError("Segment endpoints cannot satisfy the requested minimum spacing")
    quotient = length / spacing
    if not math.isfinite(quotient) or quotient >= MAX_PATH_POINTS:
        raise ValueError("Path sampling exceeds point limit")
    return max(1, int(math.ceil(quotient) if spacing_rule == "max" else math.floor(quotient)))


def _sample_line(start, end, spacing, spacing_rule="max"):
    _validate_spacing(spacing, spacing_rule)
    start, end = _finite_point(start), _finite_point(end)
    length = _dist(start, end)
    if length <= POINT_TOLERANCE_MM:
        raise ValueError("Zero-length path segment")
    intervals = _interval_count(length, spacing, spacing_rule)
    return [_lerp(start, end, index / intervals) for index in range(intervals + 1)]


def _segment_indices(segment, points):
    try:
        raw = segment["StartIndex"]
        index = int(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid segment StartIndex") from exc
    if isinstance(raw, bool) or str(raw) != str(index) or index < 0:
        raise ValueError("Segment StartIndex must be a nonnegative integer")
    count = 2 if segment.get("SegmentType") == "Line" else 3
    if segment.get("NoOfPoints") not in (count, str(count)) or index + count > len(points):
        raise ValueError("Segment point count/index does not match its geometry")
    return index, count


def _arc_geometry(points, segment):
    index, _ = _segment_indices(segment, points)
    start, middle, end = [points[index + offset] for offset in range(3)]
    center = tuple(_parse_plain_mm(str(segment.get(f"ArcCenter{axis}", "0mm"))) for axis in "XYZ")
    angle = math.radians(_angle_degrees(str(segment["ArcAngle"])))
    if not math.isfinite(angle) or abs(angle) <= 1e-12 or abs(angle) > 2 * math.pi + 1e-12:
        raise ValueError("AngularArc angle must be nonzero and at most one revolution")
    planes = {"YZ": (1, 2), "ZX": (2, 0), "XY": (0, 1)}
    plane = segment.get("ArcPlane")
    if plane is None or plane == "":
        matching = [name for name, axes in planes.items()
                    if all(abs(point[3 - sum(axes)] - center[3 - sum(axes)]) <= POINT_TOLERANCE_MM
                           for point in (start, middle, end))]
        if len(matching) != 1:
            raise ValueError("Arc plane is ambiguous; provide XY, YZ or ZX")
        plane = matching[0]
    if plane not in planes:
        raise ValueError("Only XY, YZ and ZX angular arc planes are supported")
    alpha, beta = planes[plane]
    constant = 3 - alpha - beta
    if any(abs(point[constant] - center[constant]) > POINT_TOLERANCE_MM for point in (start, middle, end)):
        raise ValueError("AngularArc points and center are not coplanar")
    delta_a, delta_b = start[alpha] - center[alpha], start[beta] - center[beta]
    radius = math.hypot(delta_a, delta_b)
    if not math.isfinite(radius) or radius <= POINT_TOLERANCE_MM:
        raise ValueError("Invalid arc radius")

    def at(fraction):
        theta = angle * fraction
        result = list(start)
        result[alpha] = center[alpha] + delta_a * math.cos(theta) - delta_b * math.sin(theta)
        result[beta] = center[beta] + delta_a * math.sin(theta) + delta_b * math.cos(theta)
        return tuple(result)

    tolerance = max(POINT_TOLERANCE_MM, radius * 1e-8)
    if _dist(at(0.5), middle) > tolerance or _dist(at(1.0), end) > tolerance:
        raise ValueError("AngularArc stored points disagree with its plane/center/angle")
    return radius * abs(angle), at, start, end


def _sample_angular_arc(points, segment, spacing, spacing_rule="max"):
    points = [_finite_point(point) for point in points]
    length, at, start, end = _arc_geometry(points, segment)
    intervals = _interval_count(length, spacing, spacing_rule)
    sampled = [at(index / intervals) for index in range(intervals + 1)]
    sampled[0], sampled[-1] = start, end
    return sampled


@dataclass(frozen=True)
class PathSample:
    points: tuple[Point, ...]
    previous_arclength_steps_mm: tuple[float, ...]
    segment_lengths_mm: tuple[float, ...]
    total_length_mm: float
    closed: bool


def _order_segments(records, closed):
    nodes, graph, endpoints = [], {}, []

    def node_id(point):
        for index, node in enumerate(nodes):
            if _same_point(node, point):
                return index
        nodes.append(point)
        graph[len(nodes) - 1] = []
        return len(nodes) - 1

    for index, (samples, _length) in enumerate(records):
        start, end = node_id(samples[0]), node_id(samples[-1])
        endpoints.append((start, end))
        graph[start].append(index)
        graph[end].append(index)
    ends = [node for node, edges in graph.items() if len(edges) == 1]
    if any(len(edges) > 2 for edges in graph.values()) or (closed and ends) or (not closed and len(ends) != 2):
        raise ValueError("Path must be an unbranched connected chain with matching closed flag")
    current = endpoints[0][0]
    if not closed and current not in ends:
        current = min(ends, key=lambda node: nodes[node])
    used, ordered = set(), []
    while len(used) < len(records):
        choices = [edge for edge in graph[current] if edge not in used]
        if not choices:
            raise ValueError("Disconnected path components")
        edge = min(choices)
        start, end = endpoints[edge]
        samples, length = records[edge]
        ordered.append((samples if start == current else list(reversed(samples)), length))
        current = end if start == current else start
        used.add(edge)
    return ordered


def sample_path(polylines, spacing, closed=False, spacing_rule="max"):
    """Sample and measure a connected line/principal-plane angular-arc path in mm."""
    _validate_spacing(spacing, spacing_rule)
    if type(closed) is not bool:
        raise ValueError("closed must be a boolean")
    records = []
    estimated_count = 0
    for raw_points, segments, _polyline_closed in polylines:
        points = [_finite_point(point) for point in raw_points]
        for segment in segments:
            kind = segment.get("SegmentType")
            if kind == "Line":
                index, _ = _segment_indices(segment, points)
                samples = _sample_line(points[index], points[index + 1], spacing, spacing_rule)
                length = _dist(points[index], points[index + 1])
            elif kind == "AngularArc":
                samples = _sample_angular_arc(points, segment, spacing, spacing_rule)
                length = _arc_geometry(points, segment)[0]
            else:
                raise ValueError(f"Unsupported path segment {kind!r}")
            estimated_count += len(samples) - 1
            if estimated_count >= MAX_PATH_POINTS:
                raise ValueError("Path sampling exceeds point limit")
            records.append((samples, length))
    if not records:
        raise ValueError("Empty path")
    ordered = _order_segments(records, closed)
    sampled, steps = [], []
    for samples, length in ordered:
        step = length / (len(samples) - 1)
        if not sampled:
            sampled.append(samples[0])
            steps.append(0.0)
        sampled.extend(samples[1:])
        steps.extend([step] * (len(samples) - 1))
    if closed:
        if not _same_point(sampled[-1], sampled[0]):
            raise ValueError("Closed path does not return to its start")
        sampled.pop()
        steps[0] = steps.pop()
    lengths = tuple(length for _samples, length in ordered)
    return PathSample(tuple(sampled), tuple(steps), lengths, math.fsum(lengths), closed)


def sample_polyline_points(points, segments, spacing, closed, spacing_rule="max"):
    return list(sample_path([(points, segments, closed)], spacing, closed, spacing_rule).points)


def sample_combined_polyline_points(polylines, spacing, closed, spacing_rule="max"):
    return list(sample_path(polylines, spacing, closed, spacing_rule).points)


def prepare_polylines(polylines, variables):
    prepared = []
    for polyline in polylines:
        points = [tuple(eval_length_mm(point[axis], variables) for axis in "xyz") for point in polyline["points"]]
        segments = []
        for segment in polyline["segments"]:
            converted = dict(segment)
            for key in ("ArcCenterX", "ArcCenterY", "ArcCenterZ"):
                if key in converted:
                    converted[key] = f"{eval_length_mm(converted[key], variables):.17g}mm"
            if "ArcAngle" in converted:
                converted["ArcAngle"] = f"{_angle_degrees(converted['ArcAngle'], variables):.17g}deg"
            segments.append(converted)
        prepared.append((points, segments, bool(polyline["closed"])))
    return prepared


def build_points_from_polyline(polyline, variables, spacing_mm):
    return sample_combined_polyline_points(prepare_polylines([polyline], variables), spacing_mm, bool(polyline["closed"]))


def build_points_from_polylines(polylines, variables, spacing_mm, closed, spacing_rule="max"):
    return sample_combined_polyline_points(prepare_polylines(polylines, variables), spacing_mm, closed, spacing_rule)


def _fmt_mm(value):
    if not math.isfinite(value):
        raise ValueError("Nonfinite model coordinate")
    if abs(value) < 5e-10:
        value = 0.0
    return f"{value:.9f}".rstrip("0").rstrip(".") + "mm"

def _extract_balanced_block(text: str, begin_marker: str, start: int = 0) -> tuple[str, int, int]:
    begin = text.find(begin_marker, start)
    if begin < 0:
        raise ValueError(f"missing block: {begin_marker}")
    depth = 0
    pos = begin
    line_start = text.rfind("\n", 0, begin) + 1
    while pos < len(text):
        next_begin = text.find("$begin", pos)
        next_end = text.find("$end", pos)
        if next_begin == -1 and next_end == -1:
            break
        if next_begin != -1 and (next_end == -1 or next_begin < next_end):
            depth += 1
            pos = next_begin + len("$begin")
        else:
            depth -= 1
            pos = next_end + len("$end")
            if depth == 0:
                end_line = text.find("\n", pos)
                if end_line == -1:
                    end_line = len(text)
                return text[line_start:end_line], line_start, end_line
    raise ValueError(f"unterminated block: {begin_marker}")


def _extract_design_block(text: str, design_name: str) -> str:
    pos = 0
    marker = "$begin 'HFSSModel'"
    while True:
        block, _start, end = _extract_balanced_block(text, marker, pos)
        if re.search(rf"^\s*Name='{re.escape(design_name)}'\s*$", block, re.M):
            return block
        pos = end


def _text_value(block: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}='([^']*)'", block)
    return match.group(1) if match else None


def _bool_value(block: str, key: str) -> bool | None:
    match = re.search(rf"\b{re.escape(key)}=(true|false)", block)
    return match.group(1) == "true" if match else None


def _parse_polyline_part(part_block: str) -> dict[str, Any]:
    attributes = re.search(r"\$begin 'Attributes'(?P<body>.*?)\$end 'Attributes'", part_block, re.S)
    attr_block = attributes.group("body") if attributes else ""
    name = _text_value(attr_block, "Name") or "<unnamed>"
    closed = _bool_value(part_block, "IsPolylineClosed")
    points = []
    points_match = re.search(r"\$begin 'PolylinePoints'(?P<body>.*?)\$end 'PolylinePoints'", part_block, re.S)
    if points_match:
        for point_match in re.finditer(r"\$begin 'PLPoint'(?P<body>.*?)\$end 'PLPoint'", points_match.group("body"), re.S):
            body = point_match.group("body")
            point = {}
            for axis in ("X", "Y", "Z"):
                value = _text_value(body, axis)
                if value is not None:
                    point[axis.lower()] = value
            points.append(point)
    segments = []
    segments_match = re.search(r"\$begin 'PolylineSegments'(?P<body>.*?)\$end 'PolylineSegments'", part_block, re.S)
    if segments_match:
        for segment_match in re.finditer(
            r"\$begin 'PLSegment'(?P<body>.*?)\$end 'PLSegment'",
            segments_match.group("body"),
            re.S,
        ):
            body = segment_match.group("body")
            segment: dict[str, Any] = {}
            for key in ("SegmentType", "StartIndex", "NoOfPoints", "ArcAngle", "ArcCenterX", "ArcCenterY", "ArcCenterZ", "ArcPlane"):
                value = re.search(rf"\b{key}=('?)([^'\r\n]+)\1", body)
                if value:
                    raw = value.group(2).strip()
                    segment[key] = int(raw) if raw.isdigit() else raw
            segments.append(segment)
    return {
        "name": name,
        "material": _text_value(attr_block, "MaterialValue"),
        "solve_inside": _bool_value(attr_block, "SolveInside"),
        "closed": closed,
        "points": points,
        "segments": segments,
        "xsection_type": _text_value(part_block, "XSectionType"),
        "xsection_width": _text_value(part_block, "XSectionWidth"),
        "xsection_height": _text_value(part_block, "XSectionHeight"),
    }


def _parse_box_part(part_block: str) -> dict[str, Any]:
    attributes = re.search(r"\$begin 'Attributes'(?P<body>.*?)\$end 'Attributes'", part_block, re.S)
    attr_block = attributes.group("body") if attributes else ""
    name = _text_value(attr_block, "Name") or "<unnamed>"
    box_match = re.search(r"\$begin 'BoxParameters'(?P<body>.*?)\$end 'BoxParameters'", part_block, re.S)
    if not box_match:
        raise ValueError(f"GeometryPart {name!r} does not contain BoxParameters")
    box_block = box_match.group("body")
    return {
        "name": name,
        "material": _text_value(attr_block, "MaterialValue"),
        "solve_inside": _bool_value(attr_block, "SolveInside"),
        "x_position": _text_value(box_block, "XPosition"),
        "y_position": _text_value(box_block, "YPosition"),
        "z_position": _text_value(box_block, "ZPosition"),
        "x_size": _text_value(box_block, "XSize"),
        "y_size": _text_value(box_block, "YSize"),
        "z_size": _text_value(box_block, "ZSize"),
    }


def parse_design_polyline(project: Path, design: str, path_name: str) -> dict[str, Any]:
    text = project.read_text(encoding="utf-8-sig", errors="replace")
    block = _extract_design_block(text, design)
    pos = 0
    while True:
        try:
            part, _start, end = _extract_balanced_block(block, "$begin 'GeometryPart'", pos)
        except ValueError:
            break
        polyline = _parse_polyline_part(part)
        if polyline["name"] == path_name:
            return polyline
        pos = end
    raise ValueError(f"missing polyline GeometryPart {path_name!r} in design {design!r}")


def parse_design_box(project: Path, design: str, object_name: str) -> dict[str, Any]:
    text = project.read_text(encoding="utf-8-sig", errors="replace")
    block = _extract_design_block(text, design)
    pos = 0
    while True:
        try:
            part, _start, end = _extract_balanced_block(block, "$begin 'GeometryPart'", pos)
        except ValueError:
            break
        attributes = re.search(r"\$begin 'Attributes'(?P<body>.*?)\$end 'Attributes'", part, re.S)
        attr_block = attributes.group("body") if attributes else ""
        if _text_value(attr_block, "Name") == object_name and _text_value(part, "OperationType") == "Box":
            return _parse_box_part(part)
        pos = end
    raise ValueError(f"missing box GeometryPart {object_name!r} in design {design!r}")


def parse_design_variables(project: Path, design: str) -> dict[str, str]:
    text = project.read_text(encoding="utf-8-sig", errors="replace")
    block = _extract_design_block(text, design)
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"VariableProp\('([^']+)',\s*'UD',\s*'',\s*'([^']*)'", block)
    }


def box_centerline_y(box: dict[str, Any], variables: dict[str, str]) -> list[Point]:
    required = ("x_position", "y_position", "z_position", "x_size", "y_size")
    missing = [key for key in required if box.get(key) is None]
    if missing:
        raise ValueError(f"box {box.get('name', '<unnamed>')!r} is missing {', '.join(missing)}")
    x0 = eval_length_mm(str(box["x_position"]), variables)
    y0 = eval_length_mm(str(box["y_position"]), variables)
    z0 = eval_length_mm(str(box["z_position"]), variables)
    x_size = eval_length_mm(str(box["x_size"]), variables)
    y_size = eval_length_mm(str(box["y_size"]), variables)
    x_center = x0 + x_size / 2.0
    return [(x_center, y0, z0), (x_center, y0 + y_size, z0)]
