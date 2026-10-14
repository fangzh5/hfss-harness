"""Closed straight board profiles, kept separate from filled copper regions."""
from pathlib import Path

from .cam_io import _dependencies, validate_operations
from .validation import finite_number, contour_errors


def write_profile(path, contours, *, line_width_mm=0.05):
    """Write GKO profile centerlines; line width is not cutter compensation."""
    if not finite_number(line_width_mm, positive=True):
        raise ValueError("Profile display line width must be finite and positive")
    validate_operations([{"kind": "polygon", "polarity": "dark", "points": ring} for ring in contours])
    GerberFile, _, go, ap, FileSettings, MM = _dependencies()
    aperture = ap.CircleAperture(line_width_mm, unit=MM)
    objects = []
    for ring in contours:
        ring = list(map(tuple, ring))
        if ring[0] == ring[-1]: ring.pop()
        for a, b in zip(ring, ring[1:] + ring[:1]):
            objects.append(go.Line(*a, *b, aperture, unit=MM))
    if len(objects) > 10000:
        raise ValueError("Profile exceeds 10000 segments")
    data = GerberFile(objects=objects, file_attrs={".FileFunction": ["Profile", "NP"]}).write_to_bytes(
        FileSettings(unit=MM, number_format=(4, 6), zeros="leading"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream: stream.write(data)


def read_profile(path):
    """Read unbranched closed line contours, including reordered segments."""
    GerberFile, _, go, ap, _, MM = _dependencies()
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Profile input exceeds 64 MiB")
    file = GerberFile.open(path)
    if not 1 <= len(file.objects) <= 10000:
        raise ValueError("Profile needs 1..10000 segments")
    adjacency, edges, widths = {}, set(), set()
    for obj in file.objects:
        if not isinstance(obj, go.Line) or not obj.polarity_dark or not isinstance(obj.aperture, ap.CircleAperture) or obj.aperture.hole_dia:
            raise ValueError("Profile supports only dark straight lines with circular aperture")
        a, b = [tuple(obj.unit.convert_to(MM, v) for v in pt) for pt in ((obj.x1, obj.y1), (obj.x2, obj.y2))]
        if a == b or any(not finite_number(v) or abs(v) >= 9999 for pt in (a, b) for v in pt):
            raise ValueError("Invalid profile coordinates")
        edge = frozenset((a, b))
        if edge in edges: raise ValueError("Duplicate profile segment")
        edges.add(edge)
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
        width = obj.aperture.unit.convert_to(MM, obj.aperture.diameter)
        if not finite_number(width, positive=True): raise ValueError("Invalid profile line width")
        widths.add(width)
    if len(widths) != 1 or any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ValueError("Profile is open, branched, or has mixed line widths")
    remaining, contours = set(adjacency), []
    while remaining:
        start = min(remaining)
        ring, prev, current = [start], None, start
        while True:
            following = next(pt for pt in adjacency[current] if pt != prev)
            if following == start: break
            if following not in remaining or following in ring:
                raise ValueError("Profile has an invalid loop")
            ring.append(following)
            prev, current = current, following
        if len(ring) > 4096 or contour_errors(ring): raise ValueError("Invalid profile contour")
        remaining.difference_update(ring)
        contours.append([list(pt) for pt in ring])
    return {"contours": contours, "line_width_mm": next(iter(widths)), "file_function": file.file_attrs.get(".FileFunction")}
