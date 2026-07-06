#!/usr/bin/env python3
"""Read basic HFSS/AEDT metadata from a project and print JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from ansys.aedt.core import Hfss


REPO_MARKERS = ("AGENT.md", "configs", "optimizer")


def _looks_like_repo_root(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "AGENT.md").exists()
        and (path / "configs").is_dir()
        and (path / "optimizer").is_dir()
    )


def _find_repo_root(project_path: Path) -> Path:
    search_roots: list[Path] = []

    cwd = Path.cwd().resolve()
    search_roots.append(cwd)
    search_roots.extend(cwd.parents)

    project_parent = project_path.parent.resolve()
    search_roots.append(project_parent)
    search_roots.extend(project_parent.parents)

    seen: set[Path] = set()
    for candidate in search_roots:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _looks_like_repo_root(candidate):
            return candidate

    raise RuntimeError(
        "Could not locate the hfss-harness repo root. Run this script from the repository or point at a project inside it."
    )


def _split_numeric_unit(value):
    text = str(value).strip()
    match = re.match(r"^\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([A-Za-z_][A-Za-z0-9_/-]*)?\s*$", text)
    if not match:
        return None, ""
    return float(match.group(1)), match.group(2) or ""


def _copy_project(project_path: Path, repo_root: Path) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temp_root = repo_root / "temp" / "readonly" / project_path.stem / f"{stamp}_{os.getpid()}"
    temp_root.mkdir(parents=True, exist_ok=False)
    if project_path.is_dir():
        target = temp_root / project_path.name
        shutil.copytree(project_path, target)
    else:
        target = temp_root / project_path.name
        shutil.copy2(project_path, target)
    return temp_root, target


def _setup_names(app) -> list[str]:
    names = list(getattr(app, "setup_names", []) or [])
    if names:
        return names
    collected = []
    for setup in getattr(app, "setups", []) or []:
        name = getattr(setup, "name", None)
        if name:
            collected.append(str(name))
    return collected


def _analysis_sweeps(app) -> list[str]:
    sweeps = list(getattr(app, "existing_analysis_sweeps", []) or [])
    if sweeps:
        return sweeps
    setup_names = _setup_names(app)
    return setup_names


def _parameter_rows(app) -> list[dict]:
    variations = getattr(app, "available_variations", None)
    nominal_values = getattr(variations, "nominal_values", {}) if variations is not None else {}
    rows = []
    if isinstance(nominal_values, dict):
        for name, value in nominal_values.items():
            numeric_value, unit = _split_numeric_unit(value)
            rows.append(
                {
                    "name": str(name),
                    "raw_value": str(value),
                    "numeric_value": numeric_value,
                    "unit": unit,
                }
            )
    rows.sort(key=lambda item: item["name"])
    return rows


def _release(app) -> None:
    if app is None:
        return
    try:
        app.release_desktop(close_projects=True, close_desktop=True)
        return
    except TypeError:
        pass
    except Exception:
        pass

    try:
        app.release_desktop(close_projects=True)
        return
    except Exception:
        pass

    try:
        if hasattr(app, "close_desktop"):
            app.close_desktop()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Read AEDT metadata for sim-intake.")
    parser.add_argument("--project", required=True, help="Path to the .aedt project")
    parser.add_argument("--design", default="", help="Optional design name")
    parser.add_argument("--version", default="2023.2", help="AEDT version")
    parser.add_argument("--graphical", action="store_true", help="Open a visible AEDT session")
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    if not project_path.exists():
        print(json.dumps({"error": f"Project not found: {project_path}"}, ensure_ascii=False))
        return 1

    repo_root = _find_repo_root(project_path)
    temp_root = None
    work_project = None
    app = None
    try:
        temp_root, work_project = _copy_project(project_path, repo_root)
        app = Hfss(
            project=str(work_project),
            design=args.design or "",
            version=args.version,
            non_graphical=not args.graphical,
            new_desktop=True,
            close_on_exit=False,
        )

        if args.design and args.design in getattr(app, "design_list", []):
            try:
                app.set_active_design(args.design)
            except Exception:
                pass

        payload = {
            "repo_root": str(repo_root),
            "source_project": str(project_path),
            "work_project": str(work_project),
            "designs": list(getattr(app, "design_list", []) or []),
            "active_design": getattr(app, "design_name", ""),
            "setup_names": _setup_names(app),
            "analysis_sweeps": _analysis_sweeps(app),
            "parameters": _parameter_rows(app),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        _release(app)
        if temp_root and temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())


