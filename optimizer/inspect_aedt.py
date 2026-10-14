"""Read-only HFSS intake on a fresh, owned, non-graphical project copy."""
from __future__ import annotations

import argparse
from datetime import datetime
from importlib.metadata import version
import json
import math
from pathlib import Path
import shutil
import uuid

from .provenance import file_sha256


def read_design(project, design, setup=None, sweep=None):
    """Native metadata only: no solve, variable assignment, report creation or save."""
    editor = design.SetActiveEditor("3D Modeler")
    variables = {str(name): str(owner.GetVariableValue(name))
                 for owner in (project, design) for name in owner.GetVariables()}
    objects = {}
    for group in ("Solids", "Sheets", "Lines", "Unclassified"):
        for name in editor.GetObjectsInGroup(group):
            name = str(name)
            box = [float(x) for x in editor.GetObjectBoundingBox(name)]
            if len(box) != 6 or not all(math.isfinite(x) for x in box):
                raise ValueError("Invalid object bounding box: " + name)
            objects[name] = {"group": group, "bounding_box": box}
    analysis = design.GetModule("AnalysisSetup")
    setups = {str(name): [str(s) for s in analysis.GetSweeps(name)] for name in analysis.GetSetups()}
    boundary = design.GetModule("BoundarySetup")
    report = design.GetModule("ReportSetup")
    categories = [str(x) for x in report.GetAvailableReportTypes()]
    reports = [str(x) for x in report.GetAllReportNames()]
    solutions, quantities, diagnostics = {}, {}, []
    for category in categories:
        try:
            solutions[category] = [str(x) for x in report.GetAvailableSolutions(category)]
        except Exception as exc:
            diagnostics.append({"query": "solutions", "category": category, "reason": repr(exc)})
    solution = f"{setup} : {sweep}" if setup and sweep else None
    if solution and setup in setups and sweep in setups[setup] + ["LastAdaptive"]:
        for category in categories:
            if solution not in solutions.get(category, []):
                continue
            try:
                groups = report.GetAllCategories(category, "Rectangular Plot", solution, "")
                quantities[category] = {str(group): [str(q) for q in report.GetAllQuantities(
                    category, "Rectangular Plot", solution, "", group)] for group in groups}
            except Exception as exc:
                diagnostics.append({"query": "quantities", "category": category, "reason": repr(exc)})
    missing = []
    if not setup:
        missing.append("setup")
    elif setup not in setups:
        raise ValueError("Requested setup absent; no fallback")
    if not sweep:
        missing.append("sweep")
    elif setup and setup in setups and sweep not in setups[setup] + ["LastAdaptive"]:
        raise ValueError("Requested sweep absent; no fallback")
    return {"variables": variables, "model_unit": str(editor.GetModelUnits()), "objects": objects,
            "setups": setups, "excitations": list(boundary.GetExcitations()),
            "boundaries": list(boundary.GetBoundaries()), "report_categories": categories,
            "available_solutions": solutions, "existing_reports": reports,
            "available_quantities": quantities, "query_diagnostics": diagnostics,
            "selected_setup": setup, "selected_sweep": sweep, "missing": missing}


def inspect_project(source, *, design_name=None, setup=None, sweep=None, temp_root,
                    runs_root, aedt_version="2023.2", _desktop_factory=None):
    source, temp_root, runs_root = (Path(x).resolve() for x in (source, temp_root, runs_root))
    if not source.is_file() or source.suffix.lower() != ".aedt":
        raise ValueError("An existing .aedt source is required")
    if (temp_root.is_relative_to(runs_root) or runs_root.is_relative_to(temp_root)
            or source.is_relative_to(temp_root) or source.is_relative_to(runs_root)):
        raise ValueError("Source, temp and runs must be separate")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    work, out = temp_root / ("inspect_" + stamp), runs_root / ("inspect_" + stamp)
    work.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=False)
    target = work / ("inspection_" + stamp + ".aedt")
    expected = file_sha256(source)
    result = {"schema_version": 1, "status": "started", "source": str(source),
              "source_sha256": expected, "working_copy": str(target), "output": str(out),
              "non_graphical": True, "solver_called": False, "save_called": False}
    desktop, settings, previous = None, None, None

    def check_files():
        if file_sha256(source) != expected or file_sha256(target) != expected:
            raise RuntimeError("Source or protected copy changed during read-only inspection")

    try:
        shutil.copy2(source, target)
        check_files()
        if _desktop_factory is None:
            from ansys.aedt.core import Desktop
            from ansys.aedt.core.generic.settings import settings
            previous = settings.use_grpc_api
            settings.use_grpc_api = False
            _desktop_factory = Desktop
            result["pyaedt_version"] = version("pyaedt")
        desktop = _desktop_factory(version=aedt_version, new_desktop=True,
                                   non_graphical=True, close_on_exit=False)
        result.update(owned_pid=desktop.aedt_process_id, aedt_version=str(desktop.odesktop.GetVersion()))
        if not desktop.odesktop.GetIsNonGraphical():
            raise RuntimeError("Inspection requires a non-graphical owned session")
        desktop.odesktop.OpenProject(str(target))
        project = desktop.odesktop.SetActiveProject(target.stem)
        if (Path(project.GetPath()) / (str(project.GetName()) + ".aedt")).resolve() != target:
            raise RuntimeError("Connected project differs from protected copy")
        designs = [str(d).split(";")[-1] for d in project.GetTopDesignList()]
        result["designs"] = designs
        if design_name is None:
            result.update(status="needs_input", missing=["design"])
        else:
            if design_name not in designs:
                raise ValueError("Requested design absent; no fallback or creation")
            design = project.SetActiveDesign(design_name)
            if str(design.GetDesignType()) != "HFSS":
                raise ValueError("Inspection supports HFSS 3D designs")
            before = read_design(project, design, setup, sweep)
            after = read_design(project, design, setup, sweep)
            if before != after:
                raise RuntimeError("Live model metadata changed during inspection")
            result.update(before, design=design_name, read_only_snapshot_unchanged=True,
                          status="needs_input" if before["missing"] else "inspected")
        check_files()
    except Exception as exc:
        result.update(status="failed", reason=repr(exc))
    finally:
        if desktop is not None:
            try:
                if target.stem in desktop.project_list():
                    desktop.odesktop.CloseProject(target.stem)
                if desktop.release_desktop(close_projects=True, close_on_exit=True) is not True:
                    raise RuntimeError("Owned AEDT session closure was not confirmed")
                result["owned_desktop_closed"] = True
            except Exception as exc:
                result.update(status="failed", close_error=repr(exc), owned_desktop_closed=False)
        if settings is not None:
            settings.use_grpc_api = previous
        try:
            check_files()
            result["source_and_copy_unchanged"] = True
        except Exception as exc:
            result.update(status="failed", integrity_error=repr(exc))
        (out / "inspection.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--design")
    parser.add_argument("--setup")
    parser.add_argument("--sweep")
    parser.add_argument("--temp-root", default="temp")
    parser.add_argument("--runs-root", default="runs/inspection")
    parser.add_argument("--aedt-version", default="2023.2")
    args = parser.parse_args(argv)
    try:
        result = inspect_project(args.source, design_name=args.design, setup=args.setup, sweep=args.sweep,
                                 temp_root=args.temp_root, runs_root=args.runs_root, aedt_version=args.aedt_version)
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": repr(exc)}))
        return 1
    print(json.dumps({key: result[key] for key in ("status", "output", "source_sha256")}, ensure_ascii=False))
    return {"inspected": 0, "needs_input": 2}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
