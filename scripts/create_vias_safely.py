"""Create first-time vias in temp and retain verified models/evidence in runs.

This entry point never modifies/saves the source project or launches a solve.
Native final edges must match line or fixed-angle principal-plane arc history.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimizer.modeling.path_geometry import eval_length_mm, parse_design_polyline
from optimizer.modeling.vias import build_via_plan, write_via_plan_csv
from optimizer.modeling.via_creation import (NativeViaBackend, create_checked_vias,
                                           snapshot_differences, verify_cylinder)
from optimizer.modeling.via_paths import capture_live_path, path_position_expressions


def set_variable(design, name, value):
    if not name.isidentifier() or name.startswith("$"):
        raise ValueError("Only local identifier variables are supported")
    existing = {str(v) for v in design.GetVariables()}
    prop = ["NAME:" + name, "Value:=", value] if name in existing else [
        "NAME:" + name, "PropType:=", "VariableProp", "UserDef:=", True, "Value:=", value]
    design.ChangeProperty(["NAME:AllTabs", ["NAME:LocalVariableTab", ["NAME:PropServers", "LocalVariables"],
                                         ["NAME:ChangedProps" if name in existing else "NAME:NewProps", prop]]])
    if str(design.GetVariableValue(name)) != value:
        raise RuntimeError(f"Variable assignment did not stick: {name}")


def assignments(values):
    result = {}
    for value in values:
        name, sep, expression = value.partition("=")
        if not sep or not name.isidentifier() or not expression.strip() or name in result:
            raise ValueError(f"Invalid/duplicate variable assignment: {value}")
        result[name] = expression
    return result


def run(args):
    from ansys.aedt.core import Desktop
    source = args.project.resolve(strict=True)
    temp_root = args.temp_root.resolve()
    runs_root = args.runs_root.resolve()
    if source.is_relative_to(temp_root) or runs_root == temp_root or runs_root.is_relative_to(temp_root):
        raise ValueError("Source, temp, and retained runs must have separate locations")
    if args.project.suffix.lower() != ".aedt":
        raise ValueError("Source must be an AEDT project")
    variables_to_set, checks = assignments(args.variable), assignments(args.check_variable)
    owned_existing = None
    if args.ownership_manifest:
        record = json.loads(args.ownership_manifest.read_text(encoding="utf-8"))
        owned_existing = record.get("result", {}).get("observations")
        if record.get("status") not in ("passed_geometry", "passed_geometry_saved", "passed") or not isinstance(owned_existing, dict) or not owned_existing:
            raise ValueError("Ownership manifest must contain a successful verified array result")
    if args.aedt_process_id is not None and args.aedt_process_id <= 0:
        raise ValueError("AEDT process ID must be positive")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    label = re.sub(r"[^A-Za-z0-9_-]", "_", source.stem + "_" + args.path_name)
    out = runs_root / (label + "_" + stamp)
    work_dir = temp_root / ("via_" + stamp)
    out.mkdir(parents=True, exist_ok=False)
    work_dir.mkdir(parents=True, exist_ok=False)
    data = source.read_bytes()
    source_sha = hashlib.sha256(data).hexdigest()
    working = work_dir / (label + "_" + stamp + ".aedt")
    for path in (working, out / "source.aedt"):
        with path.open("xb") as stream:
            stream.write(data)
    manifest = {"source": str(source), "source_sha256": source_sha, "working": str(working),
                "run_dir": str(out), "design": args.design, "path_name": args.path_name,
                "input": vars(args).copy(), "status": "started", "solver_called": False}
    manifest["input"] = {k: str(v) if isinstance(v, Path) else v for k, v in manifest["input"].items()}
    manifest_path = out / "manifest.json"

    def persist():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    def emit(event, **values):
        with (out / "journal.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **values}, ensure_ascii=False, allow_nan=False) + "\n")

    persist()
    print("RUN_DIR=" + str(out), flush=True)
    desktop = None
    project = None
    projects_before = set()
    try:
        desktop = Desktop(version=args.aedt_version, non_graphical=False,
                          new_desktop=args.aedt_process_id is None, close_on_exit=False,
                          aedt_process_id=args.aedt_process_id)
        if args.aedt_process_id is not None and desktop.aedt_process_id != args.aedt_process_id:
            raise RuntimeError("Attached AEDT process differs from explicit requested PID")
        manifest.update(process_id=desktop.aedt_process_id, borrowed_session=args.aedt_process_id is not None)
        projects_before = set(desktop.project_list())
        if working.stem in projects_before:
            raise RuntimeError("Unique working project already open")
        persist()
        project = desktop.odesktop.OpenProject(str(working))
        if not project or project.GetName() != working.stem or args.design not in list(desktop.design_list(project.GetName())):
            raise RuntimeError("Working project/design identity could not be verified")
        design = desktop.active_design(project, name=args.design)
        backend = NativeViaBackend(project, design, source=source, working=working, temp_root=temp_root)
        backend.assert_isolated_workspace()
        manifest["variables_before"] = backend.variables()
        for name, value in variables_to_set.items():
            set_variable(design, name, value)
        variables = backend.variables()
        history = parse_design_polyline(working, args.design, args.path_name)
        live, edges = capture_live_path(backend.editor, args.path_name, history, variables)
        plan = build_via_plan([live], variables, prefix=args.prefix, spacing_mm=args.spacing_mm,
                              spacing_rule=args.spacing_rule, radius=args.radius, z_start=args.z_start, height=args.height,
                              geometry_source={"mode": "live_snapshot", "native_edges": edges, "variables": variables,
                                               "source_sha256": source_sha, "design": args.design, "path": args.path_name})
        positions = path_position_expressions(plan, history, variables)
        (out / "plan.json").write_text(json.dumps({**plan.to_dict(), "position_expressions": positions}, indent=2), encoding="utf-8")
        write_via_plan_csv(plan, out / "via_positions.csv")
        result = create_checked_vias(backend, plan, positions=positions, color=tuple(args.color), emit=emit,
                                     owned_existing=owned_existing)
        # Exercise parameter regeneration on this owned work model, then restore.
        # This checks actual native dimensions, not a PyAEDT property cache.
        parameter_checks = []
        for name, value in checks.items():
            if name not in variables:
                raise ValueError(f"Check variable missing from model: {name}")
            try:
                set_variable(design, name, value)
                changed_variables = backend.variables()
                changed_centers = tuple((eval_length_mm(xy[0], changed_variables), eval_length_mm(xy[1], changed_variables),
                                         eval_length_mm(plan.z_start_expression, changed_variables)) for xy in positions)
                changed_plan = replace(plan, radius_mm=eval_length_mm(plan.radius_expression, changed_variables),
                                       z_start_mm=eval_length_mm(plan.z_start_expression, changed_variables),
                                       height_mm=eval_length_mm(plan.height_expression, changed_variables), centers_mm=changed_centers)
                changed = {n: backend.inspect(n) for n in plan.names}
                for n, center, xy in zip(plan.names, changed_centers, positions):
                    verify_cylinder(changed[n], changed_plan, center, xy, tuple(args.color))
                if changed == result["observations"]:
                    raise RuntimeError(f"Parameter check did not change any via geometry: {name}")
                parameter_checks.append({"variable": name, "from": variables[name], "to": value, "observations": changed})
            finally:
                set_variable(design, name, variables[name])
        restored = {n: backend.inspect(n) for n in plan.names}
        for n, center, xy in zip(plan.names, plan.centers_mm, positions):
            verify_cylinder(restored[n], plan, center, xy, tuple(args.color))
        if backend.variables() != variables or snapshot_differences(result["protected_before"], backend.snapshot(result["protected_before"])):
            raise RuntimeError("Parameter checks did not restore full work-model baseline")
        if backend.save() is False:
            raise RuntimeError("Final work-model save failed")
        # Reopen the saved WORK project; the original borrowed GUI is independent.
        desktop.odesktop.CloseProject(project.GetName())
        project = desktop.odesktop.OpenProject(str(working))
        design = desktop.active_design(project, name=args.design)
        backend = NativeViaBackend(project, design, source=source, working=working, temp_root=temp_root)
        backend.assert_isolated_workspace()
        if backend.variables() != variables or snapshot_differences(result["protected_before"], backend.snapshot(result["protected_before"])):
            raise RuntimeError("Saved model reopened with changed baseline")
        reopened = {n: backend.inspect(n) for n in plan.names}
        for n, center, xy in zip(plan.names, plan.centers_mm, positions):
            verify_cylinder(reopened[n], plan, center, xy, tuple(args.color))
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha:
            raise RuntimeError("Source changed while via creation was running")
        snapshot = out / (source.stem + "_vias.aedt")
        final_data = working.read_bytes()
        with snapshot.open("xb") as stream:
            stream.write(final_data)
        saved_sha = hashlib.sha256(final_data).hexdigest()
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != saved_sha:
            raise RuntimeError("Exported model bytes differ from verified work model")
        manifest.update(status="passed_geometry", result=result, parameter_checks=parameter_checks,
                        reopened_observations=reopened, variables_after=backend.variables(),
                        snapshot=str(snapshot), snapshot_sha256=saved_sha, source_unchanged=True,
                        session_left_open=True, working_project_left_open=not args.close_project)
        emit("saved_model_reopen_passed", snapshot=str(snapshot), sha256=saved_sha)
        persist()
        desktop.odesktop.RestoreWindow()
        print(json.dumps({"status": manifest["status"], "count": len(plan.names), "working": str(working),
                          "snapshot": str(snapshot), "csv": str(out / "via_positions.csv"),
                          "process_id": desktop.aedt_process_id, "source_unchanged": True}, indent=2), flush=True)
        return manifest
    except Exception as exc:
        manifest.update(status="failed", error=str(exc), source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest() == source_sha)
        emit("via_run_failed", reason=str(exc))
        persist()
        raise
    finally:
        if desktop is not None:
            if args.close_project and working.stem in desktop.project_list():
                desktop.odesktop.CloseProject(working.stem)
                manifest["working_project_closed_without_additional_save"] = working.stem not in desktop.project_list()
                manifest["other_project_names_unchanged"] = set(desktop.project_list()) == projects_before
                persist()
            desktop.release_desktop(close_projects=False, close_on_exit=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    repo = Path(__file__).resolve().parents[1]
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--design", required=True)
    parser.add_argument("--path-name", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--spacing-mm", type=float, required=True)
    parser.add_argument("--spacing-rule", choices=("max", "min"), default="max")
    parser.add_argument("--radius", required=True)
    parser.add_argument("--z-start", required=True)
    parser.add_argument("--height", required=True)
    parser.add_argument("--color", type=int, nargs=3, default=(0, 0, 255))
    parser.add_argument("--variable", action="append", default=[])
    parser.add_argument("--check-variable", action="append", default=[])
    parser.add_argument("--temp-root", type=Path, default=repo / "temp")
    parser.add_argument("--runs-root", type=Path, default=repo / "runs" / "autovia")
    parser.add_argument("--aedt-version", default="2023.2")
    parser.add_argument("--aedt-process-id", type=int, help="Explicit existing AEDT PID; only the isolated copy is changed")
    parser.add_argument("--ownership-manifest", type=Path, help="Verified successful result required to replace an existing array")
    parser.add_argument("--close-project", action="store_true", help="Close only the working project without an additional save")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
