"""Shared path helpers for optimizer inputs, runs, and temp artifacts."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

try:
    from .task_config import normalize_task_type
except ImportError:  # pragma: no cover
    from task_config import normalize_task_type


def repo_root(script_dir: Path | None = None) -> Path:
    script_dir = script_dir or Path(__file__).resolve().parent
    return script_dir.parent


def resolve_config_path(raw_path: str, script_dir: Path | None = None) -> Path:
    """Resolve config paths from the repo root or the legacy optimizer/configs folder."""
    script_dir = script_dir or Path(__file__).resolve().parent
    repo = repo_root(script_dir)
    path = Path(raw_path)

    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                path,
                (Path.cwd() / path),
                (script_dir / path),
                (repo / path),
            ]
        )

        if path.parts[:2] == ("optimizer", "configs") and len(path.parts) > 2:
            candidates.append(repo / "configs" / Path(*path.parts[2:]))
        elif path.parts and path.parts[0] == "configs" and len(path.parts) > 1:
            candidates.append(repo / "configs" / Path(*path.parts[1:]))

        candidates.extend(
            [
                repo / "configs" / path.name,
                script_dir / "configs" / path.name,
                script_dir / path.name,
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            return resolved

    if candidates:
        try:
            return candidates[-1].resolve()
        except Exception:
            return candidates[-1]

    return path


def resolve_original_project_dir(config: dict, script_dir: Path | None = None) -> Path:
    script_dir = script_dir or Path(__file__).resolve().parent
    repo = repo_root(script_dir)
    hfss_config = config.get("simulator", {}).get("hfss", {})
    project_path = Path(hfss_config.get("project_path", ""))

    if project_path.is_absolute():
        return project_path.parent.resolve()

    candidate = (script_dir / project_path).resolve()
    if candidate.exists():
        return candidate.parent

    return candidate.parent


def resolve_run_stamp(raw_stamp: str | None = None) -> str:
    if raw_stamp:
        return raw_stamp

    env_stamp = os.environ.get("PY_AEDT_RUN_STAMP")
    if env_stamp:
        return env_stamp

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _normalize_token(text: str) -> str:
    token = re.sub(r"\s+", "-", text.strip().lower())
    token = re.sub(r"[^a-z0-9_-]+", "-", token)
    token = re.sub(r"-{2,}", "-", token)
    token = re.sub(r"_{2,}", "_", token)
    token = token.strip("-_")
    return token or "task"


def _format_band_value(value: object) -> str:
    try:
        number = float(value)
    except Exception:
        return _normalize_token(str(value))

    if number.is_integer():
        return str(int(number))

    return ("%g" % number).rstrip("0").rstrip(".")


def format_band_label(freq_band: object) -> str | None:
    if not isinstance(freq_band, (list, tuple)) or len(freq_band) < 2:
        return None

    start = _format_band_value(freq_band[0])
    end = _format_band_value(freq_band[1])
    return f"{start}-{end}g"


def resolve_task_name(config: dict, config_path: str | Path | None = None) -> str:
    explicit = config.get("name")
    if explicit:
        return _normalize_token(str(explicit))

    hfss_config = config.get("simulator", {}).get("hfss", {})
    project_path = hfss_config.get("project_path", "")
    project_name = _normalize_token(Path(project_path).stem) if project_path else None

    target = config.get("target", {})
    band = format_band_label(target.get("freq_band"))
    task_type = normalize_task_type(config)

    if task_type == "opt":
        algo = config.get("algorithm", {}).get("method")
        task_suffix = _normalize_token(str(algo)) if algo else "opt"
    else:
        task_suffix = _normalize_token(task_type)

    parts = [part for part in (project_name, band, task_suffix) if part]
    if parts:
        return "_".join(parts)

    if config_path is not None:
        return _normalize_token(Path(config_path).stem)

    return "task"


def _resolve_root(config: dict, script_dir: Path | None, key_path: tuple[str, ...], default_name: str) -> Path:
    script_dir = script_dir or Path(__file__).resolve().parent
    repo = repo_root(script_dir)
    original_project_dir = resolve_original_project_dir(config, script_dir)

    cursor = config
    for key in key_path:
        if not isinstance(cursor, dict):
            cursor = {}
            break
        cursor = cursor.get(key, {})

    configured = cursor if isinstance(cursor, str) else None
    if configured:
        path = Path(configured)
        if path.is_absolute():
            return path.resolve()
        return (original_project_dir / path).resolve()

    return (repo / default_name).resolve()


def resolve_runs_root(config: dict, script_dir: Path | None = None) -> Path:
    return _resolve_root(config, script_dir, ("output", "output_dir"), "runs")


def resolve_temp_root(config: dict, script_dir: Path | None = None) -> Path:
    return _resolve_root(config, script_dir, ("optimization", "work_dir"), "temp")


def resolve_task_output_dir(
    config: dict,
    script_dir: Path | None = None,
    run_stamp: str | None = None,
    task_name: str | None = None,
) -> Path:
    task_name = task_name or resolve_task_name(config)
    return resolve_runs_root(config, script_dir) / task_name / resolve_run_stamp(run_stamp)


def resolve_task_work_dir(
    config: dict,
    script_dir: Path | None = None,
    run_stamp: str | None = None,
    task_name: str | None = None,
) -> Path:
    task_name = task_name or resolve_task_name(config)
    return resolve_temp_root(config, script_dir) / task_name / resolve_run_stamp(run_stamp)


def resolve_task_log_dir(
    config: dict,
    script_dir: Path | None = None,
    run_stamp: str | None = None,
    task_name: str | None = None,
) -> Path:
    return resolve_task_output_dir(config, script_dir, run_stamp, task_name=task_name) / "logs"
