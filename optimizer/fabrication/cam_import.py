"""Read actual CAM files using an explicit v2 stack; never infer layers from names."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .cam_io import read_copper, read_drill
from .profile_io import read_profile
from .stackup import load_stackup, package_path


def import_cam_package(directory, stack, *, mode="rebuild"):
    stack.check(mode, require_cam_files=True).require_ready()
    directory = Path(directory).resolve(strict=True)
    hashes = {}

    def checked_path(relative):
        if not package_path(relative):
            raise ValueError("CAM file must be a relative package path")
        path = (directory / relative).resolve(strict=True)
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError("CAM file escapes the selected package")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("CAM input exceeds 64 MiB")
        return path

    def parse(relative, reader):
        path = checked_path(relative)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        value = reader(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError("CAM file changed during parsing")
        hashes[relative] = before
        return value

    copper = {layer.name: parse(layer.copper_file, read_copper) for layer in stack.layers if layer.kind == "copper"}
    profile = parse(stack.profile_file, read_profile)
    contours = profile["contours"]
    drill_hits = {}
    for operation in stack.drill_operations:
        hits = parse(operation.file, read_drill)
        if not hits:
            raise ValueError(f"Drill operation {operation.id} has no hits")
        seen = set()
        for hit in hits:
            if hit["plated"] is not None and hit["plated"] != operation.metallized:
                raise ValueError(f"Drill metallization conflicts with stackup operation {operation.id}")
            xy = hit["x"], hit["y"]
            if xy in seen:
                raise ValueError(f"Duplicate drill position in operation {operation.id}")
            seen.add(xy)
        drill_hits[operation.id] = [{key: hit[key] for key in ("x", "y", "diameter")} for hit in hits]
    # Verify supported contour topology and hole placement using the declared CAM extra.
    from shapely.geometry import Polygon, Point
    rings = [Polygon(ring) for ring in contours]
    # This first import subset supports one board body; cutouts may be separate closed rings.
    outer = max(rings, key=lambda r: r.area)
    cuts = [ring for ring in rings if ring is not outer]
    if any(not outer.contains(cut) for cut in cuts) or any(a.intersects(b) for i, a in enumerate(cuts) for b in cuts[i+1:]):
        raise ValueError("Multiple board bodies or overlapping/nested profile cutouts unsupported")
    board = Polygon(outer.exterior.coords, [cut.exterior.coords for cut in cuts])
    if not board.is_valid:
        raise ValueError("Invalid board profile topology")
    for operation in stack.drill_operations:
        for hit in drill_hits[operation.id]:
            center = Point(hit["x"], hit["y"])
            if not board.covers(center) or board.boundary.distance(center) < hit["diameter"] / 2:
                raise ValueError(f"Drill in {operation.id} extends outside board or into a profile cutout")
    for relative, expected in hashes.items():
        if hashlib.sha256(checked_path(relative).read_bytes()).hexdigest() != expected:
            raise ValueError("CAM package changed while assembling plan")
    layers = {layer.name: layer for layer in stack.layers}
    return {"schema_version": "hfss-rebuild-plan-2", "unit": "mm", "coordinate_datum": stack.coordinate_datum,
            "stackup": stack.to_dict(), "copper": copper, "profile_contours": contours,
            "drill_operations": [{"id": op.id, "start_layer": op.start_layer, "end_layer": op.end_layer,
                "z_bottom_mm": min(layers[op.start_layer].z_bottom_mm, layers[op.end_layer].z_bottom_mm),
                "z_top_mm": max(layers[op.start_layer].z_top_mm, layers[op.end_layer].z_top_mm),
                "metallized": op.metallized, "hits": drill_hits[op.id]} for op in stack.drill_operations],
            "file_hashes": hashes, "source": "actual-cam-files", "profile_line_width_mm": profile["line_width_mm"],
            "purpose": "geometry/material reconstruction plan; EM recipe absent",
            "solver_called": False, "cad_modified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read mapped Gerber/GKO/Drill into a geometry/material plan; no CAD or solve.")
    parser.add_argument("package", type=Path)
    parser.add_argument("--stackup", type=Path, help="Defaults to package/stackup.json; requires hfss-stackup-2.")
    parser.add_argument("--output", type=Path, required=True, help="New plan or missing-input report; never overwritten.")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output already exists; choose a new report path")
    try:
        stackup_path = args.stackup or args.package / "stackup.json"
        stackup_sha = hashlib.sha256(stackup_path.read_bytes()).hexdigest()
        stack = load_stackup(stackup_path)
        check = stack.check("rebuild", require_cam_files=True)
        if check.errors:
            raise ValueError("; ".join(check.errors))
        if check.missing:
            result = {"status": "needs_input", "missing": list(check.missing), "cad_modified": False, "solver_called": False}
            code = 2
        else:
            result = {"status": "planned", "plan": import_cam_package(args.package, stack)}
            code = 0
        if hashlib.sha256(stackup_path.read_bytes()).hexdigest() != stackup_sha:
            raise ValueError("Stackup input changed while assembling plan")
        result["stackup_sha256"] = stackup_sha
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc), "cad_modified": False}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "report": str(args.output.resolve()), "missing": result.get("missing", [])}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
