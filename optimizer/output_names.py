"""Task-specific output file naming helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .task_config import normalize_task_type
except ImportError:  # pragma: no cover
    from task_config import normalize_task_type


def normalize_output_task_type(task_or_config: Any) -> str:
    if isinstance(task_or_config, dict):
        return normalize_task_type(task_or_config)
    return normalize_task_type({"task_type": task_or_config})


def task_file_name(task_or_config: Any, stem: str, suffix: str) -> str:
    task_type = normalize_output_task_type(task_or_config)
    return f"{task_type}_{stem}.{suffix}"


def task_data_file_name(task_or_config: Any, storage_format: str) -> str:
    return task_file_name(task_or_config, "data", storage_format)


def task_history_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "history", "csv")


def task_dashboard_state_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "dashboard_state", "json")


def task_dashboard_control_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "dashboard_control", "json")


def task_fitness_trend_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "fitness_trend", "png")


def task_pareto_front_file_name(task_or_config: Any, suffix: str) -> str:
    return task_file_name(task_or_config, "pareto_front", suffix)


def task_summary_file_name(task_or_config: Any, stem: str = "summary") -> str:
    return task_file_name(task_or_config, stem, "csv")


def task_report_file_name(task_or_config: Any, stem: str = "report") -> str:
    return task_file_name(task_or_config, stem, "md")


def task_overview_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "overview", "png")


def task_results_file_name(task_or_config: Any) -> str:
    return task_file_name(task_or_config, "results", "csv")


def task_output_path(task_output_dir: str | Path, task_or_config: Any, stem: str, suffix: str) -> Path:
    return Path(task_output_dir) / task_file_name(task_or_config, stem, suffix)
