"""Dependency-free structural checks shared by fabrication and rebuild intake."""
from __future__ import annotations

import math
from numbers import Real


def finite_number(value, *, positive=False):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and (not positive or value > 0)


def contour_errors(points):
    """Accept a simple finite ring, with optional repeated closing point."""
    if not isinstance(points, (list, tuple)) or any(not isinstance(p, (list, tuple)) or len(p) != 2
            or not all(finite_number(v) for v in p) for p in points):
        return ["coordinates must be finite XY pairs"]
    ring = list(points)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        return ["contour needs at least three vertices"]
    if len({tuple(p) for p in ring}) != len(ring):
        return ["contour repeats a vertex"]
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    def on_segment(a, b, p):
        return orient(a, b, p) == 0 and all(min(x, y) <= z <= max(x, y) for x, y, z in zip(a, b, p))
    def intersects(a, b, c, d):
        o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
        return ((o1 < 0 < o2 or o2 < 0 < o1) and (o3 < 0 < o4 or o4 < 0 < o3)
                or on_segment(a, b, c) or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b))
    # Translate before area calculation to avoid cancellation far from origin.
    origin = ring[0]
    translated = [(p[0] - origin[0], p[1] - origin[1]) for p in ring]
    area2 = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(translated, translated[1:] + translated[:1]))
    if not math.isfinite(area2) or area2 == 0:
        return ["contour has zero or nonfinite area"]
    edges = list(zip(ring, ring[1:] + ring[:1]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if intersects(a, b, *edges[j]):
                return ["contour self-intersects or self-touches"]
    return []
