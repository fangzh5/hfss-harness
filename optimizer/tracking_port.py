"""Scoped translation of an existing port integration line during a sweep."""

import copy
import math


def _plain(value):
    # PyAEDT property containers carry live CAD owners and cannot be deep-copied.
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class TrackingPort:
    def __init__(self, adapter, config, baseline):
        self.adapter, self.config = adapter, config or {}
        self.boundary = None
        self.original = None
        self.attached_line = None
        self.parameter = str(self.config.get("height_parameter", ""))
        if not self.config:
            return
        app = getattr(adapter, "app", None)
        boundary_name = str(self.config.get("boundary", "Port1"))
        self.boundary = next((b for b in app.boundaries if b.name == boundary_name), None) if app else None
        if self.boundary is None:
            raise ValueError(f"Tracking port {boundary_name!r} was not found")
        if self.parameter not in baseline:
            raise ValueError("Tracking port parameter is not in the model baseline")
        self.baseline_expression = str(baseline[self.parameter])
        self.axis = {"x": 0, "y": 1, "z": 2}.get(self.config.get("axis", "z"))
        if self.axis is None:
            raise ValueError("Tracking port axis must be x, y or z")
        line = self.boundary.props["Modes"]["Mode1"]["IntLine"]
        if "GeometryPosition" in line:
            points = line["GeometryPosition"]
            if (not isinstance(points, list) or len(points) != 2 or any(
                    p.get("PositionType") != "OnEdge" or not p.get("IsAttachedToEntity")
                    or not math.isfinite(float(p.get("UParam", float("nan"))))
                    or not 0 <= float(p["UParam"]) <= 1 for p in points)):
                raise ValueError("Tracking supports two explicit endpoints or two native edge attachments")
            if "gap_mm" in self.config:
                raise ValueError("Explicit gap cannot override native edge attachments")
            self.attached_line = _plain(line)
            self.snapshot()  # Verify actual edge coordinates before any solve.
            return
        self.original = {key: copy.deepcopy(list(line[key])) for key in ("Start", "End")}
        if any(len(point) != 3 for point in self.original.values()):
            raise ValueError("Tracking port requires 3D integration line endpoints")
        if not hasattr(self.boundary, "auto_update"):
            raise ValueError("Tracking port requires the supported BoundaryObject auto_update API")
        self.original_auto_update = self.boundary.auto_update

    def _write(self, endpoints):
        self.boundary.auto_update = False
        try:
            line = self.boundary.props["Modes"]["Mode1"]["IntLine"]
            for key, point in endpoints.items():
                line[key] = copy.deepcopy(point)
            if self.boundary.update() is not True:
                raise RuntimeError("Tracking port boundary update failed")
            if any(list(line[key]) != point for key, point in endpoints.items()):
                raise RuntimeError("Tracking port endpoint readback mismatch")
        finally:
            self.boundary.auto_update = self.original_auto_update

    def apply(self, values):
        if self.boundary is None or self.parameter not in values:
            return
        if self.attached_line is not None:
            # AEDT regenerates these endpoints with their referenced edges.
            # Replacing them with coordinates would discard that attachment.
            self.snapshot()
            return
        # Preserve the model's X/Y and any reference offset. AEDT evaluates the
        # parameter expression; no fixed coordinates, gap or numerical truncation.
        endpoints = copy.deepcopy(self.original)
        gap = self.config.get("gap_mm")
        if gap is not None:
            gap = float(gap)
            if not math.isfinite(gap) or gap <= 0:
                raise ValueError("Tracking port gap_mm must be finite and positive")
            app = self.adapter.app
            delta_si = []
            for index in range(3):
                expression = f"({self.original['End'][index]})-({self.original['Start'][index]})"
                evaluated = app.evaluate_expression(expression)
                if type(evaluated) is bool or not math.isfinite(float(evaluated)):
                    raise RuntimeError("Cannot evaluate tracking port endpoints")
                delta_si.append(float(evaluated))
            length_mm = math.sqrt(sum(value ** 2 for value in delta_si)) * 1000
            if length_mm <= 0:
                raise ValueError("Tracking port integration line has zero length")
            for key, sign in (("Start", -1), ("End", 1)):
                for index in range(3):
                    start, end = self.original["Start"][index], self.original["End"][index]
                    endpoints[key][index] = f"(({start})+({end}))/2 + ({sign * gap / length_mm:.17g})*(({end})-({start}))/2"
        for point in endpoints.values():
            point[self.axis] = f"({point[self.axis]}) + ({self.parameter}) - ({self.baseline_expression})"
        self._write(endpoints)

    def restore(self):
        if self.boundary is not None:
            if self.attached_line is not None:
                if _plain(self.boundary.props["Modes"]["Mode1"]["IntLine"]) != self.attached_line:
                    raise RuntimeError("Native port attachment changed")
            else:
                self._write(self.original)

    def snapshot(self):
        if self.boundary is None:
            return None
        if self.attached_line is None:
            return {"mode": "explicit_endpoints", "boundary": self.boundary.name,
                    "endpoints": _plain(self.boundary.props["Modes"]["Mode1"]["IntLine"])}
        editor = self.adapter.app.modeler.oeditor
        points = [[float(v) for v in editor.GetEdgePositionAtNormalizedParameter(
            int(point["EntityID"]), float(point["UParam"]))]
            for point in self.attached_line["GeometryPosition"]]
        if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
            raise RuntimeError("Invalid native port edge coordinates")
        if math.dist(*points) <= 1e-12:
            raise RuntimeError("Native port integration line has zero length")
        return {"mode": "native_edge_attachment", "boundary": self.boundary.name,
                "model_unit": self.adapter.app.modeler.model_units,
                "start": points[0], "end": points[1], "attachments": copy.deepcopy(self.attached_line)}
