import csv
import math

import pytest

from optimizer.modeling.path_geometry import build_points_from_polyline, eval_length_mm, sample_path, sample_polyline_points
from optimizer.modeling.vias import CircularKeepout, ViaIntent, build_via_plan, write_via_plan_csv


def line(points=((0, 0, 0), (1, 0, 0)), segments=None, closed=False):
    return {"closed": closed, "points": [dict(zip("xyz", (f"{value}mm" for value in point))) for point in points],
            "segments": segments if segments is not None else [{"SegmentType": "Line", "StartIndex": 0, "NoOfPoints": 2}]}


def plan(polyline=None, **options):
    return build_via_plan([polyline or line()], {}, **{
        "prefix": "fixture_via", "spacing_mm": 0.3, "radius": "0.05mm", "z_start": "-0.1mm", "height": "0.5mm", **options})


@pytest.mark.parametrize("expr,expected", [(".5mm", 0.5), ("1e-3cm", 0.01), ("100um", 0.1),
                                        ("0.001m", 1), ("2mil", 0.0508), (".01in", 0.254),
                                        ("5e2nm", 0.0005), (".2mm + 50um", 0.25)])
def test_length_units_and_numeric_syntax(expr, expected):
    assert eval_length_mm(expr, {}) == pytest.approx(expected)


def test_variable_dependencies_and_project_variables_preserve_values():
    assert eval_length_mm("$board + offset", {"$board": ".2mm", "offset": "scale*50um", "scale": "2"}) == pytest.approx(0.3)


@pytest.mark.parametrize("expr,variables", [("missing", {}), ("x", {"x": "y", "y": "x"}),
                                         ("1/0", {}), ("1e309mm", {}), ("True", {}),
                                         ("__import__('os')", {}), ("1GHz", {})])
def test_invalid_expressions_are_rejected(expr, variables):
    with pytest.raises(ValueError):
        eval_length_mm(expr, variables)


@pytest.mark.parametrize("spacing", [0, -0.1, float("nan"), float("inf"), True])
def test_bad_spacing_is_rejected_before_sampling(spacing):
    with pytest.raises(ValueError, match="Spacing"):
        plan(spacing_mm=spacing)


def test_short_segment_cannot_satisfy_minimum_spacing_with_forced_endpoints():
    with pytest.raises(ValueError, match="minimum spacing"):
        plan(line(((0, 0, 0), (0.2, 0, 0))), spacing_rule="min", spacing_mm=0.3)


def test_unordered_segments_are_joined_by_geometry_without_losing_corners():
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)]
    segments = [{"SegmentType": "Line", "StartIndex": index, "NoOfPoints": 2} for index in (1, 2, 0)]
    result = sample_polyline_points(points, segments, 1, False)
    assert result == points


@pytest.mark.parametrize("points,segments,closed", [
    ([(0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0)], [0, 2], False),
    ([(0, 0, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0), (0, 0, 0), (0, -1, 0)], [0, 2, 4], False),
    ([(0, 0, 0), (1, 0, 0)], [0], True),
])
def test_disconnected_branched_or_unclosed_paths_are_rejected(points, segments, closed):
    descriptor = [{"SegmentType": "Line", "StartIndex": index, "NoOfPoints": 2} for index in segments]
    with pytest.raises(ValueError):
        sample_polyline_points(points, descriptor, 0.3, closed)


@pytest.mark.parametrize("plane,axes", [("XY", (0, 1)), ("YZ", (1, 2)), ("ZX", (2, 0))])
def test_principal_plane_arcs_follow_aedt_axes_and_keep_true_arc_length(plane, axes):
    points = []
    for angle in (0, math.pi / 4, math.pi / 2):
        point = [0.0, 0.0, 0.0]
        point[axes[0]], point[axes[1]] = math.cos(angle), math.sin(angle)
        points.append(tuple(point))
    segment = {"SegmentType": "AngularArc", "StartIndex": 0, "NoOfPoints": 3, "ArcPlane": plane,
               "ArcAngle": "90deg", "ArcCenterX": "0mm", "ArcCenterY": "0mm", "ArcCenterZ": "0mm"}
    sampled = sample_path([(points, [segment], False)], spacing=0.4)
    assert sampled.total_length_mm == pytest.approx(math.pi / 2)
    assert all(math.dist(point, (0, 0, 0)) == pytest.approx(1) for point in sampled.points)
    assert sampled.previous_arclength_steps_mm[1:] == pytest.approx([math.pi / 8] * 4)


def test_single_path_evaluates_arc_centers_and_angles_from_variables():
    polyline = {"closed": False, "points": [
        {"x": "cx+r", "y": "cy", "z": "0mm"},
        {"x": "cx", "y": "cy+r", "z": "0mm"},
        {"x": "cx-r", "y": "cy", "z": "0mm"}],
        "segments": [{"SegmentType": "AngularArc", "StartIndex": 0, "NoOfPoints": 3,
                      "ArcAngle": "theta", "ArcCenterX": "cx", "ArcCenterY": "cy", "ArcCenterZ": "0mm", "ArcPlane": "XY"}]}
    points = build_points_from_polyline(polyline, {"cx": ".2mm", "cy": ".3mm", "r": "1mm", "theta": "180deg"}, 0.6)
    assert all(math.dist(point[:2], (0.2, 0.3)) == pytest.approx(1) for point in points)


@pytest.mark.parametrize("change", [{"ArcPlane": "tilted"}, {"ArcAngle": "0deg"}, {"ArcAngle": "720deg"},
                                   {"ArcCenterZ": "1mm"}, {"ArcAngle": "-90deg"}])
def test_invalid_arc_metadata_does_not_silently_produce_xy_geometry(change):
    segment = {"SegmentType": "AngularArc", "StartIndex": 0, "NoOfPoints": 3, "ArcAngle": "180deg",
               "ArcCenterX": "0mm", "ArcCenterY": "0mm", "ArcCenterZ": "0mm", "ArcPlane": "XY", **change}
    with pytest.raises(ValueError):
        sample_polyline_points([(0, 1, 0), (-1, 0, 0), (0, -1, 0)], [segment], 0.5, False)


def test_closed_path_length_and_csv_include_closing_edge_and_actual_bottom_z(tmp_path):
    points = [(0, 0, 3), (1, 0, 3), (1, 1, 3), (0, 1, 3), (0, 0, 3)]
    segments = [{"SegmentType": "Line", "StartIndex": index, "NoOfPoints": 2} for index in range(4)]
    result = plan(line(points, segments, True), spacing_mm=0.5)
    assert result.path.total_length_mm == 4 and len(result.centers_mm) == 8
    assert result.path.previous_arclength_steps_mm[0] == 0.5
    assert all(point[2] == -0.1 for point in result.centers_mm)
    assert all(point[2] == 3 for point in result.path.points)
    output = tmp_path / "preview.csv"
    write_via_plan_csv(result, output)
    rows = list(csv.reader(output.open(encoding="utf-8")))
    assert ["path_length_mm", "4"] in rows
    header = next(index for index, row in enumerate(rows) if row and row[0] == "name")
    assert rows[header + 1][3:6] == ["-0.1", "3", "0.5"]
    with pytest.raises(FileExistsError):
        write_via_plan_csv(result, output)


def test_nearby_nonadjacent_vias_violate_physical_clearance():
    points = [(0, 0, 0), (1, 0, 0), (1, 0.05, 0), (0, 0.05, 0)]
    segments = [{"SegmentType": "Line", "StartIndex": index, "NoOfPoints": 2} for index in range(3)]
    with pytest.raises(ValueError, match="minimum clearance"):
        plan(line(points, segments), spacing_mm=0.5)


@pytest.mark.parametrize("options", [{"radius": "0mm"}, {"radius": "-1mm"}, {"height": "0mm"},
                                   {"height": "-1mm"}, {"prefix": "via,other"}, {"minimum_edge_clearance_mm": -1}])
def test_invalid_dimensions_or_names_are_rejected(options):
    with pytest.raises(ValueError):
        plan(**options)


def test_pins_do_not_become_drills_and_plated_barrels_require_layer_and_hole_intent():
    result = plan()
    assert result.intent.kind == "solid_pin" and result.intent.finished_hole_diameter_mm is None
    with pytest.raises(ValueError, match="fabrication drill"):
        ViaIntent(kind="solid_pin", finished_hole_diameter_mm=0.1)
    with pytest.raises(ValueError):
        ViaIntent(kind="plated_barrel")
    intent = ViaIntent(kind="plated_barrel", start_layer="top", end_layer="bottom",
                       finished_hole_diameter_mm=0.08, plating_thickness_mm=0.01)
    assert plan(intent=intent).intent == intent
    with pytest.raises(ValueError, match="Barrel outer radius"):
        plan(intent=intent, radius="0.1mm")


def test_planning_hash_is_deterministic_and_changes_with_geometry_or_expressions():
    first, second = plan(), plan()
    assert first.to_dict()["plan_sha256"] == second.to_dict()["plan_sha256"]
    assert first.to_dict()["plan_sha256"] != plan(z_start="0mm").to_dict()["plan_sha256"]
    assert first.to_dict()["geometry_source"]["mode"] == "provided_geometry"


def test_path_point_limit_prevents_extreme_spacing_allocation():
    with pytest.raises(ValueError, match="point limit"):
        plan(spacing_mm=1e-12)


def test_distinct_path_z_points_cannot_create_coincident_z_directed_vias():
    with pytest.raises(ValueError, match="minimum clearance"):
        plan(line(((0, 0, 0), (0, 0, 1))), radius="1e-10mm")


def test_vertical_extent_overflow_or_loss_of_height_is_rejected():
    with pytest.raises(ValueError, match="vertical extent"):
        plan(z_start="1e308mm", height="1mm")
