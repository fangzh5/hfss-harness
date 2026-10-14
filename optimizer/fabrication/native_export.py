"""Explicit native PCB intake and actual CAM export from a read-only temp copy.

Supported: mm, Z-aligned constant-section solids, straight contour rings and
whole circles. Object roles and drill layer pairs are inputs, never name guesses.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid

from .cam_io import final_region, validate_operations, write_copper, write_drill
from .cam_import import import_cam_package
from .metallization import resolve_via_metallization
from .profile_io import write_profile
from .stackup import (DrillSpec, LayerSpec, LayerStack, MaterialSpec,
                      MissingInputsError, strict_fields, write_stackup_bundle)

TOL = 1e-8
MAP_SCHEMA = "hfss-native-pcb-map-1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mapping_check(data, inventory=None):
    """Require exhaustive, exclusive classification, including explicit exclusions."""
    strict_fields(data, {"schema_version", "coordinate_datum", "layers", "drill_operations",
                         "profile_layer", "excluded_objects"}, context="native mapping")
    if data.get("schema_version") != MAP_SCHEMA:
        raise ValueError("Unsupported native mapping schema")
    missing, assigned = [], []
    if not isinstance(data.get("coordinate_datum"), str) or not data["coordinate_datum"].strip():
        missing.append("coordinate_datum")
    layers = data.get("layers", [])
    drills = data.get("drill_operations", [])
    exclusions = data.get("excluded_objects", {})
    if not isinstance(layers, list) or not isinstance(drills, list) or not isinstance(exclusions, dict):
        raise ValueError("Mapping layers/drill_operations must be lists; exclusions must be an object")
    if not layers:
        missing.append("layers")
    names, drill_ids = set(), set()
    for entry, allowed, context in [(e, {"name", "kind", "objects", "thickness_basis", "fabrication_material"}, "layer") for e in layers] + [
            (e, {"id", "start_layer", "end_layer", "objects", "metallized"}, "drill") for e in drills]:
        strict_fields(entry, allowed, context=context)
        key = entry.get("name" if context == "layer" else "id")
        seen = names if context == "layer" else drill_ids
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError("Empty or duplicate mapping " + context + " identifier")
        seen.add(key)
        objects = entry.get("objects")
        if not isinstance(objects, list) or not objects or any(not isinstance(n, str) or not n for n in objects):
            raise ValueError("Every mapped layer/drill needs a nonempty object list")
        assigned.extend(objects)
        if context == "layer":
            if entry.get("kind") not in ("copper", "dielectric"):
                raise ValueError("Layer kind must be copper or dielectric")
            if entry["kind"] == "copper" and entry.get("thickness_basis") != "modeled":
                missing.append(f"layers.{key}.thickness_basis=modeled (native solid thickness)")
            if "fabrication_material" in entry and (entry["kind"] != "copper" or entry["fabrication_material"] not in ("copper", "pec")):
                raise ValueError("Explicit fabrication material mapping supports copper/pec only")
        else:
            copper = {l.get("name") for l in layers if l.get("kind") == "copper"}
            if entry.get("start_layer") not in copper or entry.get("end_layer") not in copper or entry.get("start_layer") == entry.get("end_layer"):
                raise ValueError("Drill needs two distinct mapped copper layers")
            if "metallized" in entry and type(entry["metallized"]) is not bool:
                raise ValueError("Explicit metallized annotation must be a boolean")
    for name, reason in exclusions.items():
        if not isinstance(name, str) or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Each exclusion needs an object name and a reason")
        assigned.append(name)
    if len(assigned) != len(set(assigned)):
        raise ValueError("Object assigned more than once")
    if inventory is not None and set(assigned) - set(inventory):
        raise ValueError("Mapping refers to absent objects: " + ", ".join(sorted(set(assigned) - set(inventory))))
    if inventory is not None:
        missing += ["object_role:" + name for name in sorted(set(inventory) - set(assigned))]
    if data.get("profile_layer") not in {l["name"] for l in layers if l["kind"] == "dielectric"}:
        missing.append("profile_layer (mapped dielectric layer)")
    if missing:
        raise MissingInputsError(missing)


def straight_loops(segments):
    """Every supplied edge must belong to exactly one unbranched closed ring."""
    adjacent, edges = {}, set()
    for a, b in segments:
        a, b = (tuple(round(float(v), 9) for v in pt[:2]) for pt in (a, b))
        edge = frozenset((a, b))
        if a == b or edge in edges:
            raise ValueError("Degenerate/duplicate native contour segment")
        edges.add(edge)
        adjacent.setdefault(a, []).append(b)
        adjacent.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in adjacent.values()):
        raise ValueError("Open or branched native contour")
    remaining, rings = set(adjacent), []
    while remaining:
        start = min(remaining)
        ring, previous, current = [start], None, start
        while True:
            following = next(pt for pt in adjacent[current] if pt != previous)
            if following == start:
                break
            if following not in remaining or following in ring:
                raise ValueError("Invalid native contour cycle")
            ring.append(following)
            previous, current = current, following
        remaining.difference_update(ring)
        rings.append({"kind": "polygon", "points": [list(p) for p in ring], "polarity": "dark"})
    return rings


def edge_feature(points, length):
    """Require line samples or a closed circle with matching native circumference."""
    if len(points) != 17 or not math.isfinite(length) or length <= 0 or any(len(p) != 3 or any(not math.isfinite(v) for v in p) for p in points):
        raise ValueError("Invalid native edge samples")
    a, b = points[0], points[-1]
    if abs(length - math.dist(a, b)) < TOL and all(math.dist(p, [x+(y-x)*i/16 for x,y in zip(a,b)]) < TOL for i,p in enumerate(points)):
        return (a, b)
    if math.dist(a, b) > TOL:
        raise ValueError("Native arc/spline is unsupported; no chord approximation")
    (ax, ay), (bx, by), (cx, cy) = [points[i][:2] for i in (0, 4, 8)]
    det = 2*(ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
    if abs(det) < 1e-14:
        raise ValueError("Degenerate native circle")
    a2, b2, c2 = ax*ax+ay*ay, bx*bx+by*by, cx*cx+cy*cy
    x = (a2*(by-cy)+b2*(cy-ay)+c2*(ay-by))/det
    y = (a2*(cx-bx)+b2*(ax-cx)+c2*(bx-ax))/det
    r = math.dist((x,y), a[:2])
    if abs(length - 2*math.pi*r) > TOL or any(abs(math.dist((x,y), p[:2])-r) > TOL for p in points):
        raise ValueError("Native edge samples/length do not prove a whole circle")
    return {"kind": "circle", "x": x, "y": y, "diameter": 2*r, "polarity": "dark"}


def nested_operations(features):
    """Topology, rather than edge order/winding, determines islands and voids."""
    validate_operations(features)
    ordered = sorted(((final_region([f]), f) for f in features), key=lambda pair: pair[0].area, reverse=True)
    result = []
    for i, (region, feature) in enumerate(ordered):
        containers = []
        for other, _ in ordered[:i]:
            if other.overlaps(region):
                raise ValueError("Intersecting native contour rings")
            if other.boundary.distance(region.boundary) < TOL:
                raise ValueError("Touching/coincident native contour rings unsupported")
            if other.contains(region):
                containers.append(other)
            elif other.intersects(region):
                raise ValueError("Intersecting native contour rings")
        result.append({**feature, "polarity": "clear" if len(containers) % 2 else "dark"})
    return result


def read_prism(editor, name):
    """Check both end sections, analytical volume and total extrusion surface area."""
    bbox = [float(v) for v in editor.GetObjectBoundingBox(name)]
    if len(bbox) != 6 or any(not math.isfinite(v) for v in bbox) or bbox[5]-bbox[2] <= TOL:
        raise ValueError("Expected a positive-height Z solid: " + name)
    faces = list(editor.GetFaceIDs(name))
    if not 1 <= len(faces) <= 10000:
        raise ValueError("Native solid face limit exceeded")
    ends, end_areas, total_area, edge_count = [[], []], [0., 0.], 0., 0
    for face in faces:
        area = float(editor.GetFaceArea(face))
        if not math.isfinite(area) or area <= 0:
            raise ValueError("Invalid native face area")
        total_area += area
        edges = list(editor.GetEdgeIDsFromFace(face))
        edge_count += len(edges)
        if not edges or edge_count > 20000:
            raise ValueError("Native face edge limit exceeded")
        sampled = [([[float(v) for v in editor.GetEdgePositionAtNormalizedParameter(edge, i/16)] for i in range(17)], float(editor.GetEdgeLength(edge))) for edge in edges]
        for end, z in enumerate((bbox[2], bbox[5])):
            if all(abs(p[2]-z) < TOL for pts, _ in sampled for p in pts):
                features, lines = [], []
                for pts, length in sampled:
                    feature = edge_feature(pts, length)
                    (features if isinstance(feature, dict) else lines).append(feature)
                operations = nested_operations(straight_loops(lines) + features)
                region = final_region(operations)
                if not math.isclose(region.area, area, rel_tol=4e-7, abs_tol=1e-8):
                    raise ValueError("Native face area differs from extracted topology: " + name)
                ends[end].extend(operations)
                end_areas[end] += area
    if not ends[0] or not ends[1]:
        raise ValueError("Solid has no supported horizontal end faces: " + name)
    bottom, top = final_region(ends[0]), final_region(ends[1])
    if bottom.symmetric_difference(top).area > 1e-8 or not math.isclose(end_areas[0], end_areas[1], rel_tol=1e-10, abs_tol=TOL):
        raise ValueError("Tapered/stepped native solid unsupported: " + name)
    # Exact perimeter counts circular features analytically, not via polygonization.
    perimeter = sum(math.pi*op["diameter"] if op["kind"] == "circle" else final_region([{**op,"polarity":"dark"}]).length for op in ends[1])
    height, volume = bbox[5]-bbox[2], float(editor.GetObjectVolume(name))
    if not math.isclose(volume, end_areas[1]*height, rel_tol=1e-8, abs_tol=TOL) or not math.isclose(total_area, 2*end_areas[1]+perimeter*height, rel_tol=1e-8, abs_tol=TOL):
        raise ValueError("Native solid is not a verified constant-section extrusion: " + name)
    return {"bbox_mm": bbox, "volume_mm3": volume, "native_end_area_mm2": end_areas[1], "operations": ends[1]}


def scalar_material(data, key):
    """Unknown, tensor, expression and dispersive values stay unknown."""
    if any(isinstance(v, (list, tuple)) and v and str(v[0]) == "NAME:ModifierData" for v in data):
        return None
    try:
        value = data[data.index(key+":=")+1]
        if isinstance(value, bool):
            return None
        number = float(value)
    except (ValueError, TypeError, IndexError):
        return None
    return number if math.isfinite(number) and number >= 0 and (key == "dielectric_loss_tangent" or number > 0) else None


def inspect_inventory(editor, inventory):
    """Read enough for role intake; retain unreadable boundary-managed entries."""
    details = {}
    for name, group in sorted(inventory.items()):
        entry = {"group":group}
        try:
            entry["bbox_mm"] = [float(v) for v in editor.GetObjectBoundingBox(name)]
        except Exception as exc:
            entry["geometry_read_error"] = repr(exc)
        if group == "Solids":
            try:
                available = set(editor.GetProperties("Geometry3DAttributeTab",name))
                for prop in ("Model","Material"):
                    if prop in available:
                        entry[prop] = str(editor.GetPropertyValue("Geometry3DAttributeTab",name,prop))
            except Exception as exc:
                entry["attribute_read_error"] = repr(exc)
        details[name] = entry
    return details


def extract_design(project, design, mapping, inventory):
    mapping_check(mapping, inventory)
    editor = design.SetActiveEditor("3D Modeler")
    if editor.GetModelUnits() != "mm":
        raise ValueError("Native PCB extraction currently requires explicit mm model units")
    used = {n for e in mapping["layers"] + mapping.get("drill_operations", []) for n in e["objects"]}
    geometry, native_materials, raw_materials = {}, {}, {}
    for name in sorted(used):
        if inventory[name] != "Solids" or str(editor.GetPropertyValue("Geometry3DAttributeTab", name, "Model")).lower() != "true":
            raise ValueError("Assigned PCB feature must be a model solid: " + name)
        native_materials[name] = str(editor.GetPropertyValue("Geometry3DAttributeTab", name, "Material")).strip('"')
        if not native_materials[name]:
            raise MissingInputsError(["material:" + name])
        geometry[name] = read_prism(editor, name)
    layers, materials, copper, dielectric = [], [], {}, {}
    for i, entry in enumerate(mapping["layers"]):
        names = entry["objects"]
        bodies = [geometry[n] for n in names]
        lo, hi = bodies[0]["bbox_mm"][2], bodies[0]["bbox_mm"][5]
        if any(abs(b["bbox_mm"][2]-lo) > TOL or abs(b["bbox_mm"][5]-hi) > TOL for b in bodies):
            raise ValueError("Objects in one layer have different Z intervals")
        actual = {native_materials[n] for n in names}
        if len(actual) != 1 and "fabrication_material" not in entry:
            raise MissingInputsError(["layers."+entry["name"]+".fabrication_material (mixed native materials)"])
        name = entry.get("fabrication_material", sorted(actual)[0])
        material_id = f"material_{i:03d}"
        source = "native material(s): " + ", ".join(sorted(actual))
        if "fabrication_material" in entry:
            source += "; explicit fabrication mapping to " + name
        if entry["kind"] == "dielectric":
            if name.lower() in ("copper", "pec"):
                raise ValueError("A metal material cannot define a dielectric layer")
            if len(names) != 1:
                raise ValueError("Native dielectric extraction currently requires one board solid per layer")
            raw = list(project.GetDefinitionManager().GetManager("Material").GetData(name))
            raw_materials[name] = raw
            materials.append(MaterialSpec(material_id, "dielectric", name, scalar_material(raw,"permittivity"), scalar_material(raw,"dielectric_loss_tangent"),
                conductivity_s_per_m=scalar_material(raw,"conductivity"), source=source))
            dielectric[entry["name"]] = bodies[0]["operations"]
        else:
            conductivity = None
            if "fabrication_material" not in entry and name.lower() not in ("copper", "pec"):
                raw = list(project.GetDefinitionManager().GetManager("Material").GetData(name))
                raw_materials[name] = raw
                conductivity = scalar_material(raw, "conductivity")
                if conductivity is None:
                    raise MissingInputsError(["layers."+entry["name"]+".metal_material_or_conductivity"])
            materials.append(MaterialSpec(material_id, "metal", name, conductivity_s_per_m=conductivity, source=source))
            regions = [final_region(b["operations"]) for b in bodies]
            if any(a.intersection(b).area > 1e-10 for j,a in enumerate(regions) for b in regions[j+1:]):
                raise ValueError("Overlapping native copper solids unsupported")
            # Sort all contours by size so a later object's clearance cannot erase
            # an earlier island. Verify the result equals the union of native bodies.
            ops = sorted([op for b in bodies for op in b["operations"]], key=lambda op: final_region([{**op,"polarity":"dark"}]).area, reverse=True)
            from shapely.ops import unary_union
            if final_region(ops).symmetric_difference(unary_union(regions)).area > 1e-10:
                raise ValueError("Native copper object composition unsupported")
            copper[entry["name"]] = ops
        layers.append(LayerSpec(entry["name"], entry["kind"], material_id, lo, hi,
            f"gerber/layer_{i:03d}.gbr" if entry["kind"] == "copper" else None,
            entry.get("thickness_basis"), "native objects: " + ", ".join(names)))
    layers.sort(key=lambda l: l.z_top_mm, reverse=True)
    layers = [replace(layer,copper_file=f"gerber/layer_{i:03d}.gbr") if layer.kind == "copper" else layer for i,layer in enumerate(layers)]
    profile_ops = dielectric[mapping["profile_layer"]]
    if any(op["kind"] != "polygon" for op in profile_ops):
        raise ValueError("Circular dielectric/profile cutouts need an explicit drill/profile adapter")
    if sum(op["polarity"] == "dark" for op in profile_ops) != 1:
        raise ValueError("Multiple/nested board bodies unsupported")
    board = final_region(profile_ops)
    if any(final_region(ops).symmetric_difference(board).area > 1e-8 for ops in dielectric.values()):
        raise ValueError("Dielectric layers have different physical board profiles")
    if any(not board.buffer(TOL).covers(final_region(ops)) for ops in copper.values()):
        raise ValueError("Native copper extends outside the physical board profile")
    drill_specs, drill_hits, drill_spans = [], {}, {}
    by_name = {l.name:l for l in layers}
    for i, entry in enumerate(mapping.get("drill_operations", [])):
        flags, hits = set(), []
        lo = min(by_name[entry["start_layer"]].z_bottom_mm, by_name[entry["end_layer"]].z_bottom_mm)
        hi = max(by_name[entry["start_layer"]].z_top_mm, by_name[entry["end_layer"]].z_top_mm)
        for name in entry["objects"]:
            body = geometry[name]
            ops, bbox = body["operations"], body["bbox_mm"]
            if len(ops) != 1 or ops[0]["kind"] != "circle" or ops[0]["polarity"] != "dark":
                raise ValueError("Drill source is not a verified solid circular pin: " + name)
            if min(hi, bbox[5])-max(lo, bbox[2]) <= TOL:
                raise ValueError("Drill source does not overlap its explicitly mapped span")
            try:
                flag = resolve_via_metallization(native_materials[name], explicit=entry.get("metallized"))
            except ValueError as exc:
                raise MissingInputsError(["drill_operations."+entry["id"]+".metallized"]) from exc
            flags.add(flag)
            hits.append({k:ops[0][k] for k in ("x","y","diameter")})
            drill_spans[name] = {"native_z_mm": [bbox[2],bbox[5]], "explicit_fabrication_z_mm": [lo,hi]}
        if len(flags) != 1:
            raise ValueError("Mixed metallization needs separate drill operations")
        flag = flags.pop()
        layer_order = {l.name:j for j,l in enumerate(layers)}
        pair = f"layer_{layer_order[entry['start_layer']]:03d}-layer_{layer_order[entry['end_layer']]:03d}"
        drill_specs.append(DrillSpec(entry["id"],entry["start_layer"],entry["end_layer"],
            f"drill/{pair}_operation_{i:03d}_{'PTH' if flag else 'NPTH'}.drl", flag, "explicit layer pair; measured native pin diameter"))
        drill_hits[entry["id"]] = hits
    from shapely.geometry import Point
    for operation,hits in drill_hits.items():
        seen = set()
        for hit in hits:
            point = Point(hit["x"],hit["y"])
            if not board.covers(point) or board.boundary.distance(point) < hit["diameter"]/2:
                raise ValueError("Drill extends outside board or into a physical cutout: " + operation)
            xy = hit["x"],hit["y"]
            if xy in seen:
                raise ValueError("Duplicate drill center in one operation")
            seen.add(xy)
    stack = LayerStack(tuple(layers), tuple(materials), tuple(drill_specs), "gerber/BOARD_OUTLINE.gko", mapping["coordinate_datum"],
        notes=("Native pin diameter defines drill diameter; no pad or plating thickness inferred.",
               "Drill fabrication span follows explicit layer pair, not the simulation pin's outside-board extent."))
    stack.check(require_cam_files=True).require_ready()
    return stack, copper, [op["points"] for op in profile_ops], drill_hits, {
        "geometry":geometry, "native_materials":native_materials, "raw_materials":raw_materials,
        "drill_spans":drill_spans, "mapping":mapping, "exclusions":mapping.get("excluded_objects",{})}


def write_verified_package(path, stack, copper, contours, hits):
    """Reuse actual CAM and stackup writers; validate independent parsed geometry."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    write_stackup_bundle(path, stack)
    (path/"docs/fab_notes.md").write_text(
        "# PCB加工说明\n\n铜形以Gerber为准，孔径/孔位以Excellon Drill为准，层对/材料/Z/厚度以stackup.json及stackup.md为准。\n"
        "BOARD_OUTLINE.gko为物理板框闭合中心线；显示线宽不是铣刀补偿。\n"
        "金属化标记不代表指定镀层厚度；未添加额外焊盘。此包未包含电磁端口、边界或求解设置。\n",
        encoding="utf-8")
    for layer in stack.layers:
        if layer.kind == "copper":
            write_copper(path/layer.copper_file, copper[layer.name])
    write_profile(path/stack.profile_file, contours)
    for op in stack.drill_operations:
        write_drill(path/op.file, hits[op.id], plated=op.metallized)
    plan = import_cam_package(path, stack, mode="fabrication")
    differences = {}
    for name, ops in copper.items():
        expected, actual = final_region(ops), final_region(plan["copper"][name])
        delta = expected.symmetric_difference(actual).area
        if delta > max(1e-6, expected.length*1e-6):
            raise RuntimeError("Written CAM copper readback differs")
        differences[name] = delta
    expected = unary_union([Polygon(ring).boundary for ring in contours])
    actual = unary_union([Polygon(ring).boundary for ring in plan["profile_contours"]])
    if expected.hausdorff_distance(actual) > 1e-6:
        raise RuntimeError("Written GKO profile differs")
    max_offset = 0.
    for op in plan["drill_operations"]:
        unmatched = list(op["hits"])
        if len(unmatched) != len(hits[op["id"]]):
            raise RuntimeError("Written drill count differs")
        for hit in hits[op["id"]]:
            index = min(range(len(unmatched)),key=lambda i:math.dist((hit["x"],hit["y"]),(unmatched[i]["x"],unmatched[i]["y"])))
            other = unmatched.pop(index)
            offset = math.dist((hit["x"],hit["y"]),(other["x"],other["y"]))
            if offset > 1e-6 or abs(hit["diameter"]-other["diameter"]) > 1e-6:
                raise RuntimeError("Written drill center/diameter differs")
            max_offset = max(max_offset,offset)
    return plan, {"copper_symmetric_difference_mm2":differences, "maximum_drill_center_offset_mm":max_offset,
                  "coordinate_tolerance_mm":1e-6, "native_tolerance_mm":TOL, "circle_reference_sides":4096}


def render_preview(path, plan):
    """Render only parsed CAM; optional plotting failure must not certify a package."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Circle
    fig, axes = plt.subplots(1,len(plan["copper"]),figsize=(5*len(plan["copper"]),5),squeeze=False)
    for ax,(name,ops) in zip(axes[0],plan["copper"].items()):
        region = final_region(ops)
        for body in (list(region.geoms) if region.geom_type == "MultiPolygon" else [region]):
            ax.add_patch(Polygon(list(body.exterior.coords),color="#d97706"))
            for hole in body.interiors:
                ax.add_patch(Polygon(list(hole.coords),color="white"))
        for ring in plan["profile_contours"]:
            closed = ring+[ring[0]]
            ax.plot([p[0] for p in closed],[p[1] for p in closed],color="#16a34a")
        for operation in plan["drill_operations"]:
            if name not in (operation["start_layer"],operation["end_layer"]):
                layer = next(l for l in plan["stackup"]["layers"] if l["name"] == name)
                if layer["z_bottom_mm"] < operation["z_bottom_mm"]-TOL or layer["z_top_mm"] > operation["z_top_mm"]+TOL:
                    continue
            for hit in operation["hits"]:
                ax.add_patch(Circle((hit["x"],hit["y"]),hit["diameter"]/2,fill=False,color="#2563eb" if operation["metallized"] else "#a855f7"))
        ax.autoscale_view()
        ax.set(aspect="equal",title=name,xlabel="x / mm",ylabel="y / mm")
        ax.grid(alpha=.15)
    fig.tight_layout()
    fig.savefig(path,dpi=160)
    plt.close(fig)


def export_native(source, design_name, *, mapping_path=None, temp_root, runs_root, aedt_version, non_graphical=True):
    source, temp_root, runs_root = map(lambda p:Path(p).resolve(), (source,temp_root,runs_root))
    if not source.is_file() or source.suffix.lower() != ".aedt" or not design_name.strip():
        raise ValueError("Explicit existing AEDT source and design required")
    if temp_root.is_relative_to(runs_root) or runs_root.is_relative_to(temp_root) or temp_root == source.parent or runs_root == source.parent:
        raise ValueError("Use distinct temp and runs roots, separate from source directory")
    source_sha = sha(source)
    mapping_path = Path(mapping_path).resolve(strict=True) if mapping_path else None
    mapping_sha = sha(mapping_path) if mapping_path else None
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path else None
    if mapping is not None:
        mapping_check(mapping)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8]
    name = "native_export_"+stamp
    work, out = temp_root/name, runs_root/name
    work.mkdir(parents=True,exist_ok=False)
    out.mkdir(parents=True,exist_ok=False)
    target = work/(name+".aedt")
    shutil.copy2(source,target)
    if sha(target) != source_sha:
        raise RuntimeError("Protected source copy differs")
    manifest = {"status":"started", "source":str(source), "source_sha256":source_sha, "working":str(target),
        "design":design_name, "mapping_sha256":mapping_sha, "solver_called":False, "cad_modified":False, "owned_desktop":True,
        "non_graphical_requested":non_graphical}
    def persist():
        (out/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    def check_files():
        if sha(source) != source_sha or sha(target) != source_sha or (mapping_path and sha(mapping_path) != mapping_sha):
            raise RuntimeError("Source, protected copy or mapping changed during export")
    desktop, transport_changed = None, False
    persist()
    try:
        from ansys.aedt.core import Desktop, __version__ as pyaedt_version
        from ansys.aedt.core.generic.settings import settings
        from optimizer.modeling.via_creation import NativeViaBackend, snapshot_differences
        previous_transport = settings.use_grpc_api
        settings.use_grpc_api = False
        transport_changed = True
        desktop = Desktop(version=aedt_version,new_desktop=True,non_graphical=non_graphical,close_on_exit=False)
        manifest.update(aedt_pid=desktop.aedt_process_id,pyaedt_version=pyaedt_version,aedt_version=str(desktop.odesktop.GetVersion()))
        manifest["non_graphical_actual"] = bool(desktop.odesktop.GetIsNonGraphical())
        if manifest["non_graphical_actual"] != non_graphical:
            raise RuntimeError("AEDT graphical mode differs from requested mode")
        persist()
        desktop.odesktop.OpenProject(str(target))
        project = desktop.odesktop.SetActiveProject(target.stem)
        designs = [str(d).split(";")[-1] for d in project.GetTopDesignList()]
        manifest["available_designs"] = designs
        if design_name not in designs:
            raise ValueError("Requested design absent; no fallback or design creation")
        design = project.SetActiveDesign(design_name)
        if str(design.GetDesignType()) != "HFSS":
            raise ValueError("Native PCB intake requires an HFSS design")
        guard = NativeViaBackend(project,design,source=source,working=target,temp_root=temp_root)
        guard.assert_isolated_workspace()
        editor = guard.editor
        inventory = {str(n):g for g in ("Solids","Sheets","Lines","Unclassified") for n in editor.GetObjectsInGroup(g)}
        if len(inventory) > 10000:
            raise ValueError("Native inventory exceeds 10000 objects")
        manifest.update(inventory=inventory,inventory_details=inspect_inventory(editor,inventory),variables=guard.variables())
        if mapping is None:
            raise MissingInputsError(["explicit object/layer/drill mapping; see inventory"])
        mapping_check(mapping, inventory)
        assigned = {n for e in mapping["layers"]+mapping.get("drill_operations",[]) for n in e["objects"]}
        before = guard.snapshot(assigned)
        stack,copper,contours,hits,evidence = extract_design(project,design,mapping,inventory)
        manifest.update(extraction=evidence,stackup=stack.to_dict(),rebuild_missing=list(stack.check("rebuild",require_cam_files=True).missing))
        after = guard.snapshot(assigned)
        if snapshot_differences(before,after) or guard.variables() != manifest["variables"] or guard.names() != set(inventory):
            raise RuntimeError("Native source changed during read-only extraction")
        if snapshot_differences(manifest["inventory_details"],inspect_inventory(editor,inventory)):
            raise RuntimeError("Native inventory changed during read-only extraction")
        check_files()
        plan,comparison = write_verified_package(out/"package",stack,copper,contours,hits)
        render_preview(out/"cam_readback.png",plan)
        from importlib.metadata import version
        manifest.update(status="verified_cam_export",package=str(out/"package"),preview=str(out/"cam_readback.png"),
            comparison=comparison,file_hashes=plan["file_hashes"],gerbonara_version=version("gerbonara"),
            copper_layer_count=len(copper),drill_count=sum(len(h) for h in hits.values()),read_only_snapshot_unchanged=True)
    except MissingInputsError as exc:
        manifest.update(status="needs_input",missing=list(exc.fields))
    except Exception as exc:
        manifest.update(status="failed",reason=repr(exc))
    finally:
        if desktop is not None:
            try:
                if target.stem in desktop.project_list():
                    desktop.odesktop.CloseProject(target.stem)
                if desktop.release_desktop(close_projects=True,close_on_exit=True) is False:
                    raise RuntimeError("Owned desktop failed to close")
                manifest["owned_desktop_closed"] = True
            except Exception as exc:
                manifest.update(status="failed",cleanup_error=repr(exc),owned_desktop_closed=False)
        if transport_changed:
            settings.use_grpc_api = previous_transport
        try:
            check_files()
            manifest.update(source_unchanged=True,protected_copy_unchanged=True)
        except Exception as exc:
            manifest.update(status="failed",input_error=repr(exc))
        persist()
    return out,manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read native PCB geometry in an owned temp copy; write verified actual CAM, no solve.")
    parser.add_argument("source",type=Path)
    parser.add_argument("--design",required=True)
    parser.add_argument("--mapping",type=Path,help="Explicit roles; omitted mapping produces inventory/needs_input only.")
    parser.add_argument("--temp-root",type=Path,required=True)
    parser.add_argument("--runs-root",type=Path,required=True)
    parser.add_argument("--aedt-version",required=True)
    parser.add_argument("--gui",action="store_true",help="Open a visible owned AEDT session for requested visual review; default is non-GUI.")
    args = parser.parse_args(argv)
    try:
        out,result = export_native(args.source,args.design,mapping_path=args.mapping,temp_root=args.temp_root,runs_root=args.runs_root,aedt_version=args.aedt_version,non_graphical=not args.gui)
    except MissingInputsError as exc:
        print(json.dumps({"status":"needs_input","missing":list(exc.fields),"cad_modified":False,"solver_called":False},ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"status":"failed","reason":str(exc)},ensure_ascii=False))
        return 1
    print(json.dumps({k:result[k] for k in ("status","package","preview","copper_layer_count","drill_count","missing","rebuild_missing") if k in result} | {"report":str(out/"manifest.json")},ensure_ascii=False))
    return 0 if result["status"] == "verified_cam_export" else (2 if result["status"] == "needs_input" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
