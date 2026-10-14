import json
import math

import pytest

from optimizer.modeling.path_geometry import eval_length_mm
from optimizer.modeling.via_paths import capture_live_path, path_position_expressions
from optimizer.modeling.vias import build_via_plan


def arc_fixture(angle="90deg", plane="XY"):
    k = math.sqrt(0.5)
    points = [{"x": x, "y": y, "z": "0mm"} for x, y in
              (("cx+r", "cy"), (f"cx+r*{k}", f"cy+r*{k}"), ("cx", "cy+r"), ("cx-r", "cy+r"))]
    return {"closed": False, "points": points, "segments": [
        {"SegmentType": "AngularArc", "StartIndex": 0, "NoOfPoints": 3, "ArcAngle": angle,
         "ArcCenterX": "cx", "ArcCenterY": "cy", "ArcCenterZ": "0mm", "ArcPlane": plane},
        {"SegmentType": "Line", "StartIndex": 2, "NoOfPoints": 2}]}


class Editor:
    def GetModelUnits(self): return "mm"
    def GetEdgeIDsFromObject(self, name): return [2, 1]  # shuffled, reversed line
    def GetVertexIDsFromEdge(self, edge): return [edge * 2, edge * 2 + 1]
    def GetEdgeLength(self, edge): return math.pi if edge == 1 else 2.0
    def GetEdgePositionAtNormalizedParameter(self, edge, t):
        if edge == 1: return [2 * math.cos(math.pi * t / 2), 2 * math.sin(math.pi * t / 2), 0]
        return [-2 + 2 * t, 2, 0]


def test_native_composite_arc_preserves_curvature_and_parameterized_centers():
    history = arc_fixture()
    variables = {"r": "2mm", "cx": "0mm", "cy": "0mm"}
    live, edges = capture_live_path(Editor(), "arc", history, variables)
    plan = build_via_plan([live], variables, prefix="v", spacing_mm=0.6, radius="0.1mm",
                          z_start="0mm", height="0.3mm", geometry_source={"mode": "live_snapshot", "native_edges": edges})
    assert plan.path.total_length_mm == pytest.approx(math.pi + 2)
    assert len(plan.names) == 11
    positions = path_position_expressions(plan, history, variables)
    for xy, center in zip(positions, plan.centers_mm):
        assert tuple(eval_length_mm(e, variables) for e in xy) == pytest.approx(center[:2], abs=1e-10)
    changed = dict(variables, r="2.2mm", cx="0.3mm")
    actual = [tuple(eval_length_mm(e, changed) for e in xy) for xy in positions]
    assert actual[0] == pytest.approx((2.5, 0))
    for x, y in actual[:7]:
        assert math.hypot(x - 0.3, y) == pytest.approx(2.2)


@pytest.mark.parametrize("mode", ["curve_sample", "length", "missing_edge", "nonfinite", "single_vertex"])
def test_live_arc_rejects_stale_history_or_invalid_native_geometry(mode):
    class BadEditor(Editor):
        def GetEdgeIDsFromObject(self, name): return [1] if mode == "missing_edge" else super().GetEdgeIDsFromObject(name)
        def GetEdgeLength(self, edge): return 2.828 if mode == "length" and edge == 1 else super().GetEdgeLength(edge)
        def GetVertexIDsFromEdge(self, edge): return [1] if mode == "single_vertex" else super().GetVertexIDsFromEdge(edge)
        def GetEdgePositionAtNormalizedParameter(self, edge, t):
            p = super().GetEdgePositionAtNormalizedParameter(edge, t)
            if mode == "curve_sample" and edge == 1 and t == 0.25: p[0] += 0.01
            if mode == "nonfinite" and edge == 1: p[0] = float("nan")
            return p
    with pytest.raises(ValueError):
        capture_live_path(BadEditor(), "arc", arc_fixture(), {"r": "2mm", "cx": "0mm", "cy": "0mm"})


def test_variable_angle_refused_before_native_reads():
    with pytest.raises(ValueError, match="constant arc angle"):
        capture_live_path(None, "arc", arc_fixture("ang"), {"r": "2mm", "cx": "0mm", "cy": "0mm", "ang": "90deg"})


def test_arc_positions_recheck_native_provenance():
    from dataclasses import replace
    variables = {"r": "2mm", "cx": "0mm", "cy": "0mm"}
    history = arc_fixture()
    live, edges = capture_live_path(Editor(), "arc", history, variables)
    plan = build_via_plan([live], variables, prefix="v", spacing_mm=0.6, radius="0.1mm",
                          z_start="0mm", height="0.3mm", geometry_source={"mode": "live_snapshot", "native_edges": edges})
    data = json.loads(plan.source_json)
    data["native_edges"][0]["length_mm"] += 0.1
    with pytest.raises(ValueError, match="does not uniquely match"):
        path_position_expressions(replace(plan, source_json=json.dumps(data)), history, variables)


@pytest.mark.parametrize("plane", ["XY", "YZ", "ZX"])
def test_principal_plane_quarter_arc_expressions_follow_radius_and_center(plane):
    from optimizer.modeling.via_paths import PLANES
    alpha, beta = PLANES[plane]
    points = []
    for ca, cb in (("origin+rad", "offset"), ("origin+rad*0.7071067811865476", "offset+rad*0.7071067811865476"),
                   ("origin", "offset+rad")):
        p = ["0mm"] * 3
        p[alpha], p[beta] = ca, cb
        points.append(dict(zip("xyz", p)))
    center = ["0mm"] * 3
    center[alpha], center[beta] = "origin", "offset"
    history = {"closed": False, "points": points, "segments": [{"SegmentType": "AngularArc", "StartIndex": 0,
        "NoOfPoints": 3, "ArcAngle": "90deg", "ArcPlane": plane, **dict(zip(("ArcCenterX", "ArcCenterY", "ArcCenterZ"), center))}]}
    variables = {"rad": "2mm", "origin": "0mm", "offset": "0mm"}
    class PlaneEditor(Editor):
        def GetEdgeIDsFromObject(self, name): return [1]
        def GetEdgePositionAtNormalizedParameter(self, edge, t):
            p = [0.0] * 3
            p[alpha], p[beta] = 2 * math.cos(t * math.pi / 2), 2 * math.sin(t * math.pi / 2)
            return p
    live, edges = capture_live_path(PlaneEditor(), "arc", history, variables)
    plan = build_via_plan([live], variables, prefix="v", spacing_mm=0.6, radius="0.02mm", z_start="0mm", height="0.3mm",
                          geometry_source={"mode": "live_snapshot", "native_edges": edges})
    positions = path_position_expressions(plan, history, variables)
    for xy, center in zip(positions, plan.centers_mm):
        assert tuple(eval_length_mm(e, variables) for e in xy) == pytest.approx(center[:2], abs=1e-10)
    changed = dict(variables, rad="2.2mm", origin="0.3mm", offset="0.1mm")
    for xy, point in zip(positions, plan.path.points):
        expected = list(point)
        expected[alpha], expected[beta] = point[alpha] * 1.1 + 0.3, point[beta] * 1.1 + 0.1
        assert tuple(eval_length_mm(e, changed) for e in xy) == pytest.approx(expected[:2], abs=1e-10)


def test_negative_major_arc_positions_do_not_follow_shorter_arc():
    history = arc_fixture("-270deg")
    history["points"][1] = {"x": "-r*0.7071067811865476", "y": "-r*0.7071067811865476", "z": "0mm"}
    history["points"] = history["points"][:3]
    history["segments"] = history["segments"][:1]
    variables = {"r": "2mm", "cx": "0mm", "cy": "0mm"}
    class MajorEditor(Editor):
        def GetEdgeIDsFromObject(self, name): return [1]
        def GetEdgeLength(self, edge): return 3 * math.pi
        def GetEdgePositionAtNormalizedParameter(self, edge, t):
            return [2 * math.cos(-1.5 * math.pi * t), 2 * math.sin(-1.5 * math.pi * t), 0]
    live, edges = capture_live_path(MajorEditor(), "major", history, variables)
    plan = build_via_plan([live], variables, prefix="v", spacing_mm=0.6, radius="0.1mm", z_start="0mm", height="0.3mm",
                          geometry_source={"mode": "live_snapshot", "native_edges": edges})
    assert plan.path.total_length_mm == pytest.approx(3 * math.pi)
    positions = path_position_expressions(plan, history, variables)
    for xy, point in zip(positions, plan.path.points):
        assert tuple(eval_length_mm(e, variables) for e in xy) == pytest.approx(point[:2], abs=1e-10)
    assert any(eval_length_mm(x, variables) < -1.9 for x, _ in positions)
