"""Explicit CAM subset for validated polygon/circle copper and circular drills.

Uses Gerbonara for file syntax/units; unsupported feature types are refused.
This is not a complete Gerber/XNC or fabrication model implementation.
"""
from __future__ import annotations

from pathlib import Path

from .validation import contour_errors, finite_number


def _dependencies():
    try:
        from gerbonara import GerberFile, ExcellonFile
        from gerbonara import graphic_objects as go, apertures as ap
        from gerbonara.cam import FileSettings
        from gerbonara.utils import MM
        return GerberFile, ExcellonFile, go, ap, FileSettings, MM
    except ImportError as exc:
        raise RuntimeError("CAM support requires hfss-harness[cam]") from exc


def validate_operations(operations):
    if not operations or len(operations) > 10000:
        raise ValueError("Copper operations must contain 1..10000 features")
    for operation in operations:
        if operation.get("polarity") not in ("dark", "clear"):
            raise ValueError("Copper polarity must be dark or clear")
        if operation.get("kind") == "polygon":
            if len(operation["points"]) > 4096:
                raise ValueError("CAM contour exceeds 4096 vertices")
            errors = contour_errors(operation["points"])
            if errors:
                raise ValueError("Invalid CAM contour: " + "; ".join(errors))
            coordinates = [v for point in operation["points"] for v in point]
        elif operation.get("kind") == "circle":
            coordinates = [operation["x"], operation["y"]]
            if not finite_number(operation["diameter"], positive=True):
                raise ValueError("Circle diameter must be finite and positive")
            if any(not finite_number(v) or abs(v) + operation["diameter"]/2 >= 9999 for v in coordinates):
                raise ValueError("Circle extent outside supported mm range")
        else:
            raise ValueError("Only polygon regions and circular flashes are supported")
        if any(not finite_number(v) or abs(v) >= 9999 for v in coordinates):
            raise ValueError("CAM coordinates outside supported finite mm range")


def write_copper(path, operations):
    validate_operations(operations)
    GerberFile, _, go, ap, FileSettings, MM = _dependencies()
    objects = []
    for op in operations:
        if op["kind"] == "polygon":
            points = [tuple(pt) for pt in op["points"]]
            if points[0] != points[-1]:
                points.append(points[0])
            objects.append(go.Region(points, unit=MM, polarity_dark=op["polarity"] == "dark"))
        else:
            objects.append(go.Flash(op["x"], op["y"], ap.CircleAperture(op["diameter"], unit=MM),
                                    unit=MM, polarity_dark=op["polarity"] == "dark"))
    data = GerberFile(objects=objects).write_to_bytes(FileSettings(unit=MM, number_format=(4, 6), zeros="leading"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def read_copper(path):
    GerberFile, _, go, ap, _, MM = _dependencies()
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("CAM input exceeds 64 MiB")
    file = GerberFile.open(path)
    operations = []
    for obj in file.objects:
        base = {"polarity": "dark" if obj.polarity_dark else "clear"}
        if isinstance(obj, go.Region):
            if any(clockwise is not None for _, _, (clockwise, _) in obj.iter_segments()):
                raise ValueError("Arc regions require the later bounded arc adapter")
            operations.append({**base, "kind": "polygon", "points": [[obj.unit.convert_to(MM, v) for v in pt] for pt in obj.outline]})
        elif isinstance(obj, go.Flash) and isinstance(obj.aperture, ap.CircleAperture) and not obj.aperture.hole_dia:
            operations.append({**base, "kind": "circle", "x": obj.unit.convert_to(MM, obj.x), "y": obj.unit.convert_to(MM, obj.y),
                               "diameter": obj.aperture.unit.convert_to(MM, obj.aperture.diameter)})
        else:
            raise ValueError(f"Unsupported CAM feature: {type(obj).__name__}")
    validate_operations(operations)
    return operations


def write_drill(path, hits, *, plated):
    _, ExcellonFile, go, ap, FileSettings, MM = _dependencies()
    if type(plated) is not bool or not 1 <= len(hits) <= 10000:
        raise ValueError("Explicit plating flag and 1..10000 drill hits required")
    objects = []
    for hit in hits:
        validate_operations([{**hit, "kind": "circle", "polarity": "dark"}])
        objects.append(go.Flash(hit["x"], hit["y"], ap.ExcellonTool(hit["diameter"], plated=plated, unit=MM), unit=MM))
    # XNC has no intrinsic plating field; keep the explicit operation in a
    # commonly parsed TYPE comment as well as the caller's layer-pair filename.
    file = ExcellonFile(objects=objects, comments=["TYPE=PLATED" if plated else "TYPE=NON_PLATED"])
    data = file.write_to_bytes(FileSettings(unit=MM, number_format=(4, 6), zeros="leading"), drop_comments=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def read_drill(path):
    _, ExcellonFile, go, _, _, MM = _dependencies()
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("CAM input exceeds 64 MiB")
    file = ExcellonFile.open(path)
    if len(file.objects) > 10000:
        raise ValueError("Drill input exceeds 10000 hits")
    hits = []
    for obj in file.objects:
        if not isinstance(obj, go.Flash):
            raise ValueError("Slots/routed drills require the later XNC adapter")
        converted = obj.converted(MM)
        hits.append({"x": converted.x, "y": converted.y, "diameter": obj.tool.unit.convert_to(MM, obj.tool.diameter),
                     "plated": obj.tool.plated})
    for hit in hits:
        validate_operations([{**hit, "kind": "circle", "polarity": "dark"}])
    return hits


def final_region(operations):
    """Compose actual file order; circular comparison uses bounded approximation."""
    validate_operations(operations)
    try:
        from shapely.geometry import Polygon, Point, GeometryCollection
    except ImportError as exc:
        raise RuntimeError("CAM geometry comparison requires hfss-harness[cam]") from exc
    region = GeometryCollection()
    for op in operations:
        feature = Polygon(op["points"]) if op["kind"] == "polygon" else Point(op["x"], op["y"]).buffer(op["diameter"] / 2, quad_segs=1024)
        if not feature.is_valid or feature.is_empty:
            raise ValueError("Invalid copper feature geometry")
        region = region.union(feature) if op["polarity"] == "dark" else region.difference(feature)
    return region
