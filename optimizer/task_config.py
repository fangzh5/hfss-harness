"""Task config validation and routing helpers."""

from __future__ import annotations

from typing import Any
import math
try:
    from .core.study import build_study_cases
except ImportError:  # pragma: no cover
    from core.study import build_study_cases


class TaskConfigError(ValueError):
    """Raised when a config does not match the selected task type."""


def normalize_task_type(config: dict[str, Any]) -> str:
    """Return the normalized task type."""
    task_type = str(config.get("task_type", "opt")).strip().lower()
    if task_type in {"hfss", "opt"}:
        return "opt"
    if task_type in {"hfss_sweep", "sweep"}:
        return "sweep"
    if task_type == "csv":
        return "csv"
    return task_type or "opt"


def _require_fields(config: dict[str, Any], field_names: list[str], task_type: str) -> None:
    missing = [name for name in field_names if name not in config]
    if missing:
        raise TaskConfigError(f"{task_type} config is missing required fields: {', '.join(missing)}")


def _validate_sweep_variables(study: dict[str, Any]) -> None:
    variables = study.get("variables")
    if not isinstance(variables, list) or not variables:
        raise TaskConfigError("sweep config requires study.variables with at least one variable.")

    for index, variable in enumerate(variables, start=1):
        if not isinstance(variable, dict):
            raise TaskConfigError(f"study.variables[{index - 1}] must be an object.")
        _require_fields(variable, ["name", "start", "stop", "step"], "study.variables item")

        try:
            start = float(variable["start"])
            stop = float(variable["stop"])
            step = float(variable["step"])
        except Exception as exc:
            raise TaskConfigError(
                f"study.variables[{index - 1}] must provide numeric start/stop/step values."
            ) from exc

        if not all(math.isfinite(value) for value in (start, stop, step)):
            raise TaskConfigError(f"study.variables[{index - 1}] values must be finite.")
        if stop < start:
            raise TaskConfigError(f"study.variables[{index - 1}] stop must be greater than or equal to start.")
        if step <= 0:
            raise TaskConfigError(f"study.variables[{index - 1}] step must be positive.")


def _reject_readonly_flags(config: dict[str, Any], task_type: str) -> None:
    """Reject read-only flags for tasks that must always simulate."""
    if task_type not in {"opt", "sweep"}:
        return

    offending: list[str] = []
    sections = _mode_sections(config)
    for section_name, section in sections:
        if not isinstance(section, dict):
            continue
        for key in ("skip_simulation", "use_original_project"):
            if key in section:
                offending.append(f"{section_name}.{key}")
        if section.get("evaluation_mode", "solve") != "solve":
            offending.append(f"{section_name}.evaluation_mode")

    if offending:
        joined = ", ".join(offending)
        raise TaskConfigError(f"{task_type} config must not include read-only flags: {joined}")


def _mode_sections(config):
    simulator = config.get("simulator", {})
    hfss = simulator.get("hfss", {}) if isinstance(simulator, dict) else {}
    return (("top-level", config), ("optimization", config.get("optimization", {})),
            ("simulator", simulator), ("simulator.hfss", hfss))


def resolve_evaluation_mode(config: dict[str, Any]) -> str:
    """Resolve legacy flags without allowing contradictions or source writes."""
    modes = []
    flags = {"skip_simulation": [], "use_original_project": []}
    for section_name, section in _mode_sections(config):
        if not isinstance(section, dict):
            continue
        if "evaluation_mode" in section:
            mode = section["evaluation_mode"]
            if mode not in {"solve", "existing_results"}:
                raise TaskConfigError(f"{section_name}.evaluation_mode must be solve or existing_results")
            modes.append(mode)
        for key in flags:
            if key in section:
                if type(section[key]) is not bool:
                    raise TaskConfigError(f"{section_name}.{key} must be boolean")
                flags[key].append(section[key])
    if any(len(set(values)) > 1 for values in flags.values()) or len(set(modes)) > 1:
        raise TaskConfigError("Conflicting evaluation mode flags")
    skip = flags["skip_simulation"]
    mode = modes[0] if modes else ("existing_results" if any(skip) else "solve")
    if skip and skip[0] != (mode == "existing_results"):
        raise TaskConfigError("skip_simulation conflicts with evaluation_mode")
    if any(flags["use_original_project"]) and mode != "existing_results":
        raise TaskConfigError("use_original_project requires existing_results; source writes are forbidden")
    return mode


def validate_task_config(config: dict[str, Any]) -> str:
    """Validate the config against the declared task type and return that type."""
    task_type = normalize_task_type(config)
    opt_options = config.get("optimization", {})
    if isinstance(opt_options, dict) and "keep_working_copy" in opt_options:
        if type(opt_options["keep_working_copy"]) is not bool:
            raise TaskConfigError("optimization.keep_working_copy must be a boolean")

    if task_type == "opt":
        _require_fields(config, ["parameters", "target", "algorithm"], task_type)
        _reject_readonly_flags(config, task_type)
        opt = config.get("optimization", {})
        if not isinstance(opt, dict):
            raise TaskConfigError("optimization must be an object")
        interval = opt.get("save_interval", 10)
        if type(interval) is not int or interval < 0:
            raise TaskConfigError("optimization.save_interval must be a nonnegative integer")
        return task_type

    if task_type == "sweep":
        _require_fields(config, ["study"], task_type)
        for forbidden in ("parameters", "target", "algorithm"):
            if forbidden in config:
                raise TaskConfigError(
                    f"sweep config must not include '{forbidden}'. Use study.* fields instead."
                )
        study = config.get("study", {})
        if not isinstance(study, dict):
            raise TaskConfigError("sweep config requires study to be an object.")
        if study.get("mode", "oat") != "explicit":
            _validate_sweep_variables(study)
        try:
            build_study_cases(study)
        except (ValueError, KeyError, TypeError) as exc:
            raise TaskConfigError(str(exc)) from exc
        _reject_readonly_flags(config, task_type)
        return task_type

    if task_type == "val":
        resolve_evaluation_mode(config)
        _require_fields(config, ["cases", "target"], task_type)
        cases = config.get("cases")
        if not isinstance(cases, list) or not cases:
            raise TaskConfigError("val config requires cases with at least one case.")
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                raise TaskConfigError(f"cases[{index}] must be an object.")
            params = case.get("params", case)
            if not isinstance(params, dict) or not params:
                raise TaskConfigError(f"cases[{index}] must provide parameter values.")
        target = config.get("target")
        if not isinstance(target, dict):
            raise TaskConfigError("val config requires target to be an object.")
        return task_type

    if task_type == "csv":
        return task_type

    raise TaskConfigError(f"Unsupported task_type: {task_type}")
