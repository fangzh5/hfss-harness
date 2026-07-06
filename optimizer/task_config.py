"""Task config validation and routing helpers."""

from __future__ import annotations

from typing import Any


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

        if stop < start:
            raise TaskConfigError(f"study.variables[{index - 1}] stop must be greater than or equal to start.")
        if step <= 0:
            raise TaskConfigError(f"study.variables[{index - 1}] step must be positive.")


def _reject_readonly_flags(config: dict[str, Any], task_type: str) -> None:
    """Reject read-only flags for tasks that must always simulate."""
    if task_type not in {"opt", "sweep"}:
        return

    offending: list[str] = []
    sections = (("top-level", config), ("optimization", config.get("optimization", {})))
    for section_name, section in sections:
        if not isinstance(section, dict):
            continue
        for key in ("skip_simulation", "use_original_project"):
            if key in section:
                offending.append(f"{section_name}.{key}")

    if offending:
        joined = ", ".join(offending)
        raise TaskConfigError(f"{task_type} config must not include read-only flags: {joined}")


def validate_task_config(config: dict[str, Any]) -> str:
    """Validate the config against the declared task type and return that type."""
    task_type = normalize_task_type(config)

    if task_type == "opt":
        _require_fields(config, ["parameters", "target", "algorithm"], task_type)
        _reject_readonly_flags(config, task_type)
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
        _validate_sweep_variables(study)
        _reject_readonly_flags(config, task_type)
        return task_type

    if task_type == "val":
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
