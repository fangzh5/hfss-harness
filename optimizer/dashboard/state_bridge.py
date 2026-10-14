"""Build and persist dashboard state snapshots from optimization runs."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

try:
    from ..output_names import (
        task_dashboard_control_file_name,
        task_dashboard_state_file_name,
        task_data_file_name,
        task_history_file_name,
        task_pareto_front_file_name,
        task_results_file_name,
    )
    from ..task_config import normalize_task_type
    from ..result_records import pareto_front_for_json
except ImportError:  # pragma: no cover
    from output_names import (
        task_dashboard_control_file_name,
        task_dashboard_state_file_name,
        task_data_file_name,
        task_history_file_name,
        task_pareto_front_file_name,
        task_results_file_name,
    )
    from task_config import normalize_task_type
    from result_records import pareto_front_for_json


def _format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _iso_from_epoch(value: Optional[float]) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value)).isoformat()
    except Exception:
        return None


def _safe_duration_seconds(started_at: Optional[float], finished_at: Optional[float] = None) -> Optional[float]:
    if started_at in (None, ""):
        return None
    try:
        start = float(started_at)
    except Exception:
        return None
    end = float(finished_at) if finished_at not in (None, "") else time.time()
    return max(end - start, 0.0)


def _normalize_freqs(freqs: Iterable[float]) -> list[float]:
    arr = np.asarray(freqs, dtype=float)
    if arr.size == 0:
        return []
    if np.nanmean(arr) > 1000:
        arr = arr / 1e9
    return [float(v) for v in arr.tolist()]


def _normalize_current_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    normalized: dict[str, Any] = {}
    for name, value in params.items():
        if value is None:
            normalized[str(name)] = None
            continue
        if isinstance(value, (int, float, np.integer, np.floating)):
            normalized[str(name)] = float(value)
            continue
        text = str(value).strip()
        for suffix in ("mm", "cm", "m", "GHz", "Hz", "deg"):
            if text.lower().endswith(suffix.lower()):
                text = text[: -len(suffix)].strip()
                break
        try:
            normalized[str(name)] = float(text)
        except Exception:
            normalized[str(name)] = str(value)
    return normalized


def _curve_points_from_arrays(
    freqs: Iterable[float],
    values: Iterable[float],
    value_key: str = "s11",
) -> dict[str, list[dict[str, float]]]:
    normalized_freqs = _normalize_freqs(freqs)
    series = np.asarray(values, dtype=float).tolist()
    points = [
        {"freq": float(freq), value_key: float(val)}
        for freq, val in zip(normalized_freqs, series)
    ]
    return {"points": points}


def _curve_points_from_far_field(
    far_field_metrics: Optional[dict[str, Any]],
    metric_key: str,
    value_key: str = "value",
) -> dict[str, list[dict[str, float]]]:
    per_frequency = (far_field_metrics or {}).get("per_frequency", [])
    if not isinstance(per_frequency, list):
        return {"points": []}

    points: list[dict[str, float]] = []
    for item in per_frequency:
        if not isinstance(item, dict):
            continue
        freq = item.get("frequency")
        value = item.get(metric_key)
        try:
            if freq is None or value is None:
                continue
            freq_value = float(str(freq).replace("GHz", "").strip())
            points.append({"freq": freq_value, value_key: float(value)})
        except Exception:
            continue
    return {"points": points}


def _band_worst(
    curve: Optional[dict[str, Any]],
    band: Optional[Iterable[float]],
    value_key: str = "s11",
) -> dict[str, Any]:
    points = (curve or {}).get("points", [])
    if not points:
        return {"value": "N/A", "note": f"target-band max {value_key.upper()}"}

    candidates = points
    if band is not None:
        band = list(band)
        if len(band) >= 2:
            in_band = [pt for pt in points if band[0] <= pt["freq"] <= band[1]]
            candidates = in_band or points

    worst = max(candidates, key=lambda item: item.get(value_key, item.get("s11", float("-inf"))))
    return {
        "value": f"{worst.get(value_key, worst.get('s11')):.2f} dB",
        "note": f"band max @ {worst['freq']:.2f} GHz",
    }


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _parse_log_float(row: dict[str, Any], key: str) -> Optional[float]:
    raw = row.get(key)
    if raw in (None, "", "N/A"):
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _build_parameter_rows(param_configs: list[dict[str, Any]], current_values: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for cfg in param_configs:
        name = cfg.get("name")
        rows.append(
            {
                "name": name,
                "value": current_values.get(name),
                "min": cfg.get("min"),
                "max": cfg.get("max"),
                "unit": cfg.get("unit", "mm"),
                "mode": cfg.get("mode", "step"),
                "step": cfg.get("step"),
                "count": cfg.get("count"),
                "resolution": cfg.get("resolution", 0.01),
                "constraint": cfg.get("constraint"),
                "state": cfg.get("state", "active"),
            }
        )
    return rows


def _is_multi_objective_config(target: dict[str, Any]) -> bool:
    return bool((target.get("multi_objective") or {}).get("enabled"))


def _extract_objectives(row: dict[str, Any], limit: int = 3) -> list[float]:
    objectives: list[float] = []
    for index in range(1, limit + 1):
        value = _parse_log_float(row, f"objective_{index}")
        if value is None:
            continue
        objectives.append(value)
    return objectives


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None


def _first_existing_path(task_dir: Path, candidates: list[str]) -> Path:
    for name in candidates:
        candidate = task_dir / name
        if candidate.exists():
            return candidate
    return task_dir / candidates[0]


def _write_json_atomic(path: Path, payload: dict[str, Any], retries: int = 8, retry_delay: float = 0.15) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Optional[BaseException] = None

    for attempt in range(max(1, int(retries))):
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f"{path.stem}_", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, path)
            return True
        except OSError as exc:
            last_error = exc
            try:
                os.remove(tmp_name)
            except OSError:
                pass
            time.sleep(retry_delay * (attempt + 1))

    # Windows can temporarily deny atomic replace when a browser/server/AV scanner
    # has the JSON open. Fall back to in-place overwrite so the dashboard writer
    # keeps running instead of disabling live updates for the rest of the job.
    try:
        with path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        return True
    except OSError as exc:
        last_error = exc

    print(f"Dashboard snapshot write skipped after transient file error: {last_error}")
    return False


def _dashboard_extra_metrics(extra_metrics: dict[str, Any]) -> dict[str, Any]:
    """Keep dashboard snapshots compact by omitting raw far-field grids."""
    if not isinstance(extra_metrics, dict):
        return {}

    compact: dict[str, Any] = {}
    for key in ("constraint_details", "objective_metrics", "bo_diagnostics"):
        if key in extra_metrics:
            compact[key] = extra_metrics[key]

    far_field = extra_metrics.get("far_field")
    if isinstance(far_field, dict):
        compact["far_field"] = {
            "frequencies": far_field.get("frequencies", []),
            "summary": far_field.get("summary", {}),
        }
    return compact


def _build_params_from_log_row(row: dict[str, Any], param_configs: list[dict[str, Any]]) -> dict[str, float]:
    params: dict[str, float] = {}
    for cfg in param_configs:
        name = cfg.get("name")
        if not name:
            continue
        value = _parse_log_float(row, name)
        if value is None:
            continue
        params[name] = value
    return params


def build_dashboard_snapshot(
    *,
    config: dict[str, Any],
    current: Optional[dict[str, Any]] = None,
    best_curve: Optional[dict[str, Any]] = None,
    last_curve: Optional[dict[str, Any]] = None,
    best_s12_curve: Optional[dict[str, Any]] = None,
    last_s12_curve: Optional[dict[str, Any]] = None,
    current_fitness: Optional[float] = None,
    best_cost: Optional[float] = None,
    fitness_history: Optional[list[dict[str, Any]]] = None,
    events: Optional[list[dict[str, Any]]] = None,
    status: Optional[dict[str, Any]] = None,
    started_at: Optional[float] = None,
    pareto_front: Optional[list[dict[str, Any]]] = None,
    current_sim_started_at: Optional[float] = None,
    last_sim_duration: Optional[float] = None,
    finished_at: Optional[float] = None,
    control: Optional[dict[str, Any]] = None,
    best_pointing_curve: Optional[dict[str, Any]] = None,
    last_pointing_curve: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    target = config.get("target", {})
    param_configs = config.get("parameters", [])
    algorithm = config.get("algorithm", {})
    simulator = config.get("simulator", {})
    hfss = simulator.get("hfss", {})
    current = current or {}
    status = status or {"label": "Running", "tone": "running", "detail": "Optimization in progress"}
    fitness_history = fitness_history or []
    events = events or []
    control = control or {}
    optimization_mode = "multi_objective" if _is_multi_objective_config(target) else "single_objective"
    pareto_front = pareto_front_for_json(pareto_front) if optimization_mode == "multi_objective" else []

    project_path = hfss.get("project_path")
    source_name = Path(project_path).stem if project_path else "N/A"
    task_name = config.get("name", "task")

    target_band = target.get("freq_band")
    best_metric = _band_worst(best_curve, target_band)
    last_metric = _band_worst(last_curve, target_band)
    s12_threshold = target.get("s12_threshold", target.get("s21_threshold"))
    best_s12_metric = _band_worst(best_s12_curve, target_band, "s12") if best_s12_curve else {"value": "N/A", "note": "target-band max S12"}
    last_s12_metric = _band_worst(last_s12_curve, target_band, "s12") if last_s12_curve else {"value": "N/A", "note": "target-band max S12"}
    total_runtime_seconds = _safe_duration_seconds(started_at, finished_at)
    current_sim_runtime_seconds = _safe_duration_seconds(current_sim_started_at, finished_at) if current_sim_started_at else None
    last_sim_runtime_seconds = float(last_sim_duration) if last_sim_duration is not None else None
    elapsed = _format_duration(total_runtime_seconds) if total_runtime_seconds is not None else current.get("elapsed", "00:00:00")

    best_points = (best_curve or {}).get("points", [])
    last_points = (last_curve or {}).get("points", [])
    best_s12_points = (best_s12_curve or {}).get("points", [])
    last_s12_points = (last_s12_curve or {}).get("points", [])
    current_values = current.get("params", {})
    param_rows = _build_parameter_rows(param_configs, current_values)

    current_objectives = list(current.get("objectives", []) or []) if optimization_mode == "multi_objective" else []
    current_constraint_violation = current.get("constraint_violation") if optimization_mode == "multi_objective" else None
    completed_simulations = current.get("sim_id")
    try:
        completed_simulations = int(completed_simulations) if completed_simulations not in (None, "") else 0
    except Exception:
        completed_simulations = 0
    max_simulations = algorithm.get("max_simulations")
    try:
        max_simulations = int(max_simulations) if max_simulations not in (None, "") else None
    except Exception:
        max_simulations = None
    progress_fraction = None
    if isinstance(max_simulations, int) and max_simulations > 0:
        progress_fraction = min(max(completed_simulations / max_simulations, 0.0), 1.0)

    return {
        "title": f"{config.get('name', 'task')} Optimization Dashboard",
        "subtitle": "Live snapshot from optimization logs",
        "meta": {
            "source_name": source_name,
            "task_name": task_name,
        },
        "mode": "Runtime",
        "optimization_mode": optimization_mode,
        "status": status,
        "control": control,
        "current": {
            **current,
            "sim_id": current.get("sim_id"),
            "iter_id": current.get("iter_id"),
            "stage": current.get("stage"),
            "checkpoint": bool(current.get("checkpoint", False)),
            "elapsed": elapsed,
            "component_costs": current.get("component_costs", {}),
            "raw_metrics": current.get("raw_metrics", {}),
            "adaptive_scales": current.get("adaptive_scales", {}),
            "extra_metrics": current.get("extra_metrics", {}),
            "objectives": current_objectives,
            "constraint_violation": current_constraint_violation,
        },
        "runtime": {
            "run_started_at": _iso_from_epoch(started_at),
            "finished_at": _iso_from_epoch(finished_at),
            "active_sim_started_at": _iso_from_epoch(current_sim_started_at),
            "active_sim_id": current.get("active_sim_id"),
            "active_iter_id": current.get("active_iter_id"),
            "completed_simulations": completed_simulations,
            "max_simulations": max_simulations,
            "progress_fraction": progress_fraction,
            "progress_percent": None if progress_fraction is None else progress_fraction * 100.0,
            "total_runtime_seconds": total_runtime_seconds,
            "total_runtime_display": _format_duration(total_runtime_seconds) if total_runtime_seconds is not None else "N/A",
            "current_sim_runtime_seconds": current_sim_runtime_seconds,
            "current_sim_runtime_display": _format_duration(current_sim_runtime_seconds) if current_sim_runtime_seconds is not None else "N/A",
            "last_sim_runtime_seconds": last_sim_runtime_seconds,
            "last_sim_runtime_display": _format_duration(last_sim_runtime_seconds) if last_sim_runtime_seconds is not None else "N/A",
        },
        "algorithm": {
            "method": algorithm.get("method"),
            "population_size": algorithm.get("population_size"),
            "max_iterations": algorithm.get("max_iterations"),
            "max_simulations": max_simulations,
            "history_loaded": algorithm.get("history_loaded", 0),
        },
        "metrics": {
            "best_s11": {
                "value": best_metric["value"],
                "unit": "dB",
                "note": best_metric["note"],
            },
            "last_s11": {
                "value": last_metric["value"],
                "unit": "dB",
                "note": last_metric["note"],
            },
            "best_s12": {
                "value": best_s12_metric["value"],
                "unit": "dB",
                "note": best_s12_metric["note"],
            },
            "last_s12": {
                "value": last_s12_metric["value"],
                "unit": "dB",
                "note": last_s12_metric["note"],
            },
            "fitness": {
                "value": current_fitness if current_fitness is not None else best_cost,
                "unit": "cost",
                "note": "current fitness" if current_fitness is not None else ("current best fitness" if best_cost is not None else ""),
            },
        },
        "s11Curves": {
            "threshold": target.get("s11_threshold"),
            "best": best_points,
            "last": last_points,
        },
        "s12Curves": {
            "threshold": s12_threshold,
            "best": best_s12_points,
            "last": last_s12_points,
        },
        "pointingErrorCurves": {
            "threshold": (target.get("multi_objective") or {}).get("pointing_error_threshold"),
            "best": (best_pointing_curve or {}).get("points", []),
            "last": (last_pointing_curve or {}).get("points", []),
        },
        "target": {
            "freq_band": target.get("freq_band"),
            "s11_threshold": target.get("s11_threshold"),
            "s11_profile": target.get("s11_profile"),
            "s12_threshold": s12_threshold,
            "s21_threshold": target.get("s21_threshold", s12_threshold),
            "bandwidth_target": target.get("bandwidth_target"),
            "gain_min": target.get("gain_min"),
            "multi_objective": target.get("multi_objective"),
            "stages": [
                {
                    **stage,
                    "s12_threshold": stage.get("s12_threshold", stage.get("s21_threshold")),
                    "s21_threshold": stage.get("s21_threshold", stage.get("s12_threshold")),
                }
                for stage in (target.get("stages") or [])
            ],
        },
        "parameters": param_rows,
        "fitnessHistory": fitness_history,
        "paretoFront": pareto_front,
        "events": events,
    }


def _derive_dashboard_target(config: dict[str, Any], task_type: str) -> dict[str, Any]:
    if task_type == "sweep":
        study = config.get("study", {})
        return {
            "freq_band": study.get("freq_band"),
            "s11_threshold": study.get("s11_threshold"),
            "s12_threshold": study.get("s12_threshold", study.get("s21_threshold")),
            "s21_threshold": study.get("s21_threshold", study.get("s12_threshold")),
            "multi_objective": study.get("multi_objective"),
        }
    return config.get("target", {})


def _derive_dashboard_parameters(config: dict[str, Any], task_type: str, current_params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    if task_type == "sweep":
        rows: list[dict[str, Any]] = []
        for item in config.get("study", {}).get("variables", []):
            rows.append(
                {
                    "name": item.get("name"),
                    "min": item.get("start"),
                    "max": item.get("stop"),
                    "step": item.get("step"),
                    "mode": "step",
                    "resolution": item.get("resolution", item.get("step")),
                    "unit": item.get("unit", "mm"),
                }
            )
        return rows

    if task_type == "val":
        cases = config.get("cases", [])
        ranges: dict[str, list[float]] = {}
        for case in cases:
            params = case.get("params")
            if not isinstance(params, dict):
                continue
            for name, value in params.items():
                try:
                    ranges.setdefault(str(name), []).append(float(value))
                except Exception:
                    continue
        rows = []
        for name, values in sorted(ranges.items()):
            rows.append(
                {
                    "name": name,
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                    "unit": "mm",
                    "resolution": None,
                }
            )
        if rows:
            return rows

        current = current_params or {}
        return [{"name": name, "min": value, "max": value, "unit": "mm", "resolution": None} for name, value in current.items()]

    return config.get("parameters", [])


def _task_dashboard_title(config: dict[str, Any], task_type: str) -> str:
    label = {
        "opt": "Optimization",
        "sweep": "Sweep",
        "val": "Validation",
    }.get(task_type, task_type.capitalize())
    return f"{config.get('name', 'task')} {label} Dashboard"


def _build_task_dashboard_snapshot(
    *,
    config: dict[str, Any],
    task_type: str,
    current: Optional[dict[str, Any]],
    best_curve: Optional[dict[str, Any]],
    last_curve: Optional[dict[str, Any]],
    best_s12_curve: Optional[dict[str, Any]],
    last_s12_curve: Optional[dict[str, Any]],
    current_metric: Optional[float],
    best_metric: Optional[float],
    fitness_history: Optional[list[dict[str, Any]]],
    events: Optional[list[dict[str, Any]]],
    status: Optional[dict[str, Any]],
    started_at: Optional[float],
    max_simulations: Optional[int],
    current_sim_started_at: Optional[float] = None,
    last_sim_duration: Optional[float] = None,
    finished_at: Optional[float] = None,
    control: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    current = current or {}
    current_params = current.get("params", {}) if isinstance(current.get("params"), dict) else {}
    dashboard_config = {
        "name": config.get("name", "task"),
        "task_type": task_type,
        "simulator": config.get("simulator", {}),
        "target": _derive_dashboard_target(config, task_type),
        "parameters": _derive_dashboard_parameters(config, task_type, current_params=current_params),
        "algorithm": {
            "method": task_type,
            "max_simulations": max_simulations,
        },
    }
    snapshot = build_dashboard_snapshot(
        config=dashboard_config,
        current=current,
        best_curve=best_curve,
        last_curve=last_curve,
        best_s12_curve=best_s12_curve,
        last_s12_curve=last_s12_curve,
        current_fitness=current_metric,
        best_cost=best_metric,
        fitness_history=fitness_history,
        events=events,
        status=status,
        started_at=started_at,
        pareto_front=[],
        current_sim_started_at=current_sim_started_at,
        last_sim_duration=last_sim_duration,
        finished_at=finished_at,
        control=control,
        best_pointing_curve={"points": []},
        last_pointing_curve={"points": []},
    )
    snapshot["task_type"] = task_type
    snapshot["title"] = _task_dashboard_title(config, task_type)
    snapshot["subtitle"] = "Live snapshot from task progress"
    snapshot.setdefault("metrics", {})
    snapshot["metrics"]["current_fitness"] = {
        "value": current_metric,
        "unit": "cost",
        "note": "latest task metric",
    }
    snapshot["metrics"]["best_fitness"] = {
        "value": best_metric,
        "unit": "cost",
        "note": "best task metric",
    }
    return snapshot


class TaskDashboardStateWriter:
    """Write live dashboard snapshots for sweep/val tasks."""

    def __init__(self, task_output_dir: str | Path, config: dict[str, Any], *, max_simulations: int):
        self.task_output_dir = Path(task_output_dir)
        self.config = config
        self.task_type = normalize_task_type(config)
        if self.task_type not in {"sweep", "val"}:
            raise ValueError("TaskDashboardStateWriter only supports sweep/val tasks.")
        self.state_path = self.task_output_dir / task_dashboard_state_file_name(self.task_type)
        self.control_path = self.task_output_dir / task_dashboard_control_file_name(self.task_type)
        self.started_at = time.time()
        self.max_simulations = int(max_simulations) if max_simulations else 0
        self.best_metric: Optional[float] = None
        self.current_metric: Optional[float] = None
        self.best_curve: dict[str, Any] = {"points": []}
        self.last_curve: dict[str, Any] = {"points": []}
        self.best_s12_curve: dict[str, Any] = {"points": []}
        self.last_s12_curve: dict[str, Any] = {"points": []}
        self.current: dict[str, Any] = {}
        self.status: dict[str, Any] = {"label": "Running", "tone": "running", "detail": "Waiting for first simulation"}
        self.fitness_history: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.current_sim_started_at: Optional[float] = None
        self.last_sim_duration: Optional[float] = None
        self.finished_at: Optional[float] = None
        self._write_snapshot()

    def _load_control(self) -> dict[str, Any]:
        control = _load_json(self.control_path)
        return control if isinstance(control, dict) else {}

    def is_stop_requested(self) -> bool:
        return bool(self._load_control().get("stop_requested", False))

    def append_event(self, message: str, severity: str = "info") -> None:
        self.events.append(
            {
                "time": _format_duration(time.time() - self.started_at),
                "message": message,
                "severity": severity,
            }
        )
        self.events = self.events[-8:]

    def update_status(self, label: str, tone: str = "running", detail: str = "") -> None:
        self.status = {"label": label, "tone": tone, "detail": detail}
        self._write_snapshot()

    def begin_simulation(self, *, sim_id: int, detail: Optional[dict[str, Any]] = None, detail_text: str = "") -> None:
        self.current_sim_started_at = time.time()
        self.finished_at = None
        self.current.update(detail or {})
        self.current["active_sim_id"] = sim_id
        self.current["active_iter_id"] = sim_id
        self.status = {"label": "Running", "tone": "running", "detail": detail_text or "Simulation in progress"}
        self._write_snapshot()

    def record_result(
        self,
        *,
        sim_id: int,
        current: dict[str, Any],
        freqs: Iterable[float],
        s11: Iterable[float],
        s12: Optional[Iterable[float]],
        metric_value: Optional[float],
        event_message: Optional[str] = None,
        better_when_lower: bool = True,
    ) -> None:
        completed_sim_duration = _safe_duration_seconds(self.current_sim_started_at)
        self.last_sim_duration = completed_sim_duration
        self.current_sim_started_at = None
        self.current = {
            **self.current,
            **current,
            "sim_id": sim_id,
            "iter_id": sim_id,
            "active_sim_id": sim_id,
            "active_iter_id": sim_id,
            "checkpoint": False,
        }
        if isinstance(self.current.get("params"), dict):
            self.current["params"] = _normalize_current_params(self.current["params"])
        self.current_metric = metric_value
        self.last_curve = _curve_points_from_arrays(freqs, s11, "s11")
        self.last_s12_curve = _curve_points_from_arrays(freqs, s12 if s12 is not None else [], "s12")
        if metric_value is not None:
            self.fitness_history.append({"sim_id": sim_id, "iter_id": sim_id, "fitness": float(metric_value)})
            if self.best_metric is None or ((metric_value < self.best_metric) if better_when_lower else (metric_value > self.best_metric)):
                self.best_metric = float(metric_value)
                self.best_curve = self.last_curve
                self.best_s12_curve = self.last_s12_curve
                self.append_event(event_message or f"New best at sim_id {sim_id}", "success")
        self.status = {"label": "Running", "tone": "running", "detail": "Latest simulation recorded"}
        self._write_snapshot()

    def finalize(self, status: str = "Completed", detail: str = "") -> None:
        tone = "success" if status.lower() == "completed" else "paused"
        self.status = {"label": status, "tone": tone, "detail": detail}
        self.finished_at = time.time()
        self.current_sim_started_at = None
        self._write_snapshot()

    def _write_snapshot(self) -> None:
        snapshot = _build_task_dashboard_snapshot(
            config=self.config,
            task_type=self.task_type,
            current=self.current,
            best_curve=self.best_curve,
            last_curve=self.last_curve,
            best_s12_curve=self.best_s12_curve,
            last_s12_curve=self.last_s12_curve,
            current_metric=self.current_metric,
            best_metric=self.best_metric,
            fitness_history=self.fitness_history,
            events=self.events,
            status=self.status,
            started_at=self.started_at,
            max_simulations=self.max_simulations,
            current_sim_started_at=self.current_sim_started_at,
            last_sim_duration=self.last_sim_duration,
            finished_at=self.finished_at,
            control=self._load_control(),
        )
        self.task_output_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.state_path, snapshot)


class DashboardStateWriter:
    """Incrementally write dashboard state snapshots for live monitoring."""

    def __init__(self, task_output_dir: str | Path, config: dict[str, Any]):
        self.task_output_dir = Path(task_output_dir)
        self.config = config
        self.task_type = normalize_task_type(config)
        self.state_path = self.task_output_dir / task_dashboard_state_file_name(self.task_type)
        self.control_path = self.task_output_dir / task_dashboard_control_file_name(self.task_type)
        self.started_at = time.time()
        self.best_cost = float("inf")
        self.current_fitness: Optional[float] = None
        self.best_curve: dict[str, Any] = {"points": []}
        self.last_curve: dict[str, Any] = {"points": []}
        self.best_s12_curve: dict[str, Any] = {"points": []}
        self.last_s12_curve: dict[str, Any] = {"points": []}
        self.best_pointing_curve: dict[str, Any] = {"points": []}
        self.last_pointing_curve: dict[str, Any] = {"points": []}
        self.current: dict[str, Any] = {}
        self.status: dict[str, Any] = {"label": "Running", "tone": "running", "detail": "Optimization in progress"}
        self.fitness_history: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.pareto_front: list[dict[str, Any]] = []
        self.current_sim_started_at: Optional[float] = None
        self.last_sim_duration: Optional[float] = None
        self.finished_at: Optional[float] = None

    def _load_control(self) -> dict[str, Any]:
        control = _load_json(self.control_path)
        return control if isinstance(control, dict) else {}

    def is_stop_requested(self) -> bool:
        return bool(self._load_control().get("stop_requested", False))

    def request_stop(self, reason: str = "user_request") -> dict[str, Any]:
        control = {
            "stop_requested": True,
            "reason": reason,
            "requested_at": time.time(),
            "requested_at_iso": datetime.fromtimestamp(time.time()).isoformat(),
        }
        _write_json_atomic(self.control_path, control)
        self.append_event("Stop requested from dashboard", "warning")
        self._write_snapshot()
        return control

    def append_event(self, message: str, severity: str = "info") -> None:
        self.events.append(
            {
                "time": _format_duration(time.time() - self.started_at),
                "message": message,
                "severity": severity,
            }
        )
        self.events = self.events[-8:]

    def update_status(self, label: str, tone: str = "running", detail: str = "") -> None:
        self.status = {"label": label, "tone": tone, "detail": detail}

    def begin_simulation(self, *, sim_id: int, iter_id: int) -> None:
        self.current_sim_started_at = time.time()
        self.finished_at = None
        self.current["active_sim_id"] = sim_id
        self.current["active_iter_id"] = iter_id
        self._write_snapshot()

    def record_simulation(
        self,
        *,
        sim_id: int,
        iter_id: int,
        params: np.ndarray,
        param_names: list[str],
        freqs: np.ndarray,
        s11: np.ndarray,
        s12: Optional[np.ndarray],
        fitness: Any,
        checkpoint: bool = False,
        stage_name: str = "",
    ) -> None:
        params_map = (
            {name: float(value) for name, value in zip(param_names, np.asarray(params, dtype=float))}
            if params is not None
            else {}
        )
        extra_metrics = getattr(fitness, "extra_metrics", {}) or {}
        dashboard_extra_metrics = _dashboard_extra_metrics(extra_metrics)
        far_field_metrics = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else {}
        curve = _curve_points_from_arrays(freqs if freqs is not None else [], s11 if s11 is not None else [], "s11")
        curve_s12 = _curve_points_from_arrays(freqs if freqs is not None else [], s12 if s12 is not None else [], "s12")
        pointing_curve = _curve_points_from_far_field(far_field_metrics, "pointing_error_deg", "value")
        cost = float(getattr(fitness, "cost", float("inf")))
        completed_sim_duration = _safe_duration_seconds(self.current_sim_started_at)
        self.last_sim_duration = completed_sim_duration
        self.current_sim_started_at = None

        self.current = {
            "sim_id": sim_id,
            "iter_id": iter_id,
            "stage": stage_name or getattr(fitness, "stage_name", ""),
            "checkpoint": bool(checkpoint),
            "params": params_map,
            "fitness": cost,
            "component_costs": getattr(fitness, "component_costs", {}),
            "raw_metrics": getattr(fitness, "raw_metrics", {}),
            "adaptive_scales": getattr(fitness, "adaptive_scales", {}),
            "extra_metrics": dashboard_extra_metrics,
            "objectives": list(getattr(fitness, "objectives", []) or []),
            "constraint_violation": getattr(fitness, "constraint_violation", None),
            "active_sim_id": sim_id,
            "active_iter_id": iter_id,
        }
        self.current_fitness = cost
        self.last_curve = curve
        self.last_s12_curve = curve_s12
        self.last_pointing_curve = pointing_curve
        self.fitness_history.append(
            {
                "sim_id": sim_id,
                "iter_id": iter_id,
                "fitness": cost,
                "component_costs": getattr(fitness, "component_costs", {}),
                "raw_metrics": getattr(fitness, "raw_metrics", {}),
                "extra_metrics": dashboard_extra_metrics,
                "objectives": list(getattr(fitness, "objectives", []) or []),
                "constraint_violation": getattr(fitness, "constraint_violation", None),
            }
        )

        if cost < self.best_cost:
            self.best_cost = cost
            self.best_curve = curve
            self.best_s12_curve = curve_s12
            self.best_pointing_curve = pointing_curve
            self.append_event(f"New best at sim_id {sim_id}", "success")

        self._write_snapshot()

    def finalize(self, status: str = "Completed", detail: str = "") -> None:
        tone = "success" if status.lower() == "completed" else "paused"
        self.update_status(status, tone=tone, detail=detail)
        self.finished_at = time.time()
        self.current_sim_started_at = None
        self._write_snapshot()

    def update_pareto_front(self, pareto_front: Optional[list[dict[str, Any]]]) -> None:
        self.pareto_front = list(pareto_front or [])
        self._write_snapshot()

    def _write_snapshot(self) -> None:
        control = self._load_control()
        snapshot = build_dashboard_snapshot(
            config=self.config,
            current=self.current,
            best_curve=self.best_curve,
            last_curve=self.last_curve,
            best_s12_curve=self.best_s12_curve,
            last_s12_curve=self.last_s12_curve,
            best_pointing_curve=self.best_pointing_curve,
            last_pointing_curve=self.last_pointing_curve,
            current_fitness=self.current_fitness,
            best_cost=self.best_cost if self.best_cost != float("inf") else None,
            fitness_history=self.fitness_history,
            events=self.events,
            status=self.status,
            started_at=self.started_at,
            pareto_front=self.pareto_front,
            current_sim_started_at=self.current_sim_started_at,
            last_sim_duration=self.last_sim_duration,
            finished_at=self.finished_at,
            control=control,
        )

        self.task_output_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.state_path, snapshot)


def _simulation_rows(data_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in data_rows if row.get("record_type") != "far_field_meta" and row.get("sim_id") not in (None, "")]


def _rebuild_sweep_snapshot(
    *,
    task_dir: Path,
    config: dict[str, Any],
    control: dict[str, Any],
    run_started_at: Optional[float],
    finished_at: Optional[float],
) -> dict[str, Any]:
    data_rows = _simulation_rows(_load_jsonl_records(task_dir / task_data_file_name("sweep", "jsonl")))
    total_points = len(data_rows)
    best_row = None
    best_metric = None
    history: list[dict[str, Any]] = []
    for row in data_rows:
        summary = row.get("sweep_summary", {}) if isinstance(row.get("sweep_summary"), dict) else {}
        metric = summary.get("s11_worst_db")
        try:
            metric_value = float(metric)
        except Exception:
            continue
        history.append({"sim_id": int(row["sim_id"]), "iter_id": int(row["sim_id"]), "fitness": metric_value})
        if best_metric is None or metric_value < best_metric:
            best_metric = metric_value
            best_row = row

    last_row = data_rows[-1] if data_rows else None
    current = {}
    current_metric = None
    if last_row is not None:
        summary = last_row.get("sweep_summary", {}) if isinstance(last_row.get("sweep_summary"), dict) else {}
        current_metric = summary.get("s11_worst_db")
        current = {
            "sim_id": int(last_row["sim_id"]),
            "iter_id": int(last_row["sim_id"]),
            "sweep_variable": last_row.get("sweep_variable", last_row.get("variable")),
            "value": last_row.get("value"),
            "point_index": last_row.get("point_index"),
            "point_count": last_row.get("point_count"),
            "params": _normalize_current_params(last_row.get("params", {})),
        }

    return _build_task_dashboard_snapshot(
        config=config,
        task_type="sweep",
        current=current,
        best_curve=_curve_points_from_arrays(best_row.get("s_freqs", []), best_row.get("s11", []), "s11") if best_row else {"points": []},
        last_curve=_curve_points_from_arrays(last_row.get("s_freqs", []), last_row.get("s11", []), "s11") if last_row else {"points": []},
        best_s12_curve=_curve_points_from_arrays(best_row.get("s_freqs", []), best_row.get("s12", []), "s12") if best_row else {"points": []},
        last_s12_curve=_curve_points_from_arrays(last_row.get("s_freqs", []), last_row.get("s12", []), "s12") if last_row else {"points": []},
        current_metric=float(current_metric) if current_metric is not None else None,
        best_metric=best_metric,
        fitness_history=history,
        events=[],
        status={"label": "Completed", "tone": "success", "detail": "Snapshot rebuilt from sweep outputs"},
        started_at=run_started_at,
        max_simulations=total_points,
        finished_at=finished_at,
        control=control,
    )


def _rebuild_val_snapshot(
    *,
    task_dir: Path,
    config: dict[str, Any],
    control: dict[str, Any],
    run_started_at: Optional[float],
    finished_at: Optional[float],
) -> dict[str, Any]:
    data_rows = _simulation_rows(_load_jsonl_records(task_dir / task_data_file_name("val", "jsonl")))
    summary_rows = _load_csv_rows(task_dir / task_results_file_name("val"))
    raw_by_case = {row.get("case_name"): row for row in data_rows}
    best_case_name = None
    best_metric = None
    history: list[dict[str, Any]] = []
    for row in summary_rows:
        case_name = row.get("case_name")
        cost = _parse_log_float(row, "cost")
        sim_id = _parse_log_float(row, "sim_id")
        if case_name in (None, "") or cost is None or sim_id is None:
            continue
        history.append({"sim_id": int(sim_id), "iter_id": int(sim_id), "fitness": cost})
        if best_metric is None or cost < best_metric:
            best_metric = cost
            best_case_name = case_name

    last_row = data_rows[-1] if data_rows else None
    last_summary = summary_rows[-1] if summary_rows else {}
    best_row = raw_by_case.get(best_case_name) if best_case_name else None
    current = {}
    current_metric = _parse_log_float(last_summary, "cost")
    if last_row is not None:
        current = {
            "sim_id": int(last_row["sim_id"]),
            "iter_id": int(last_row["sim_id"]),
            "case_name": last_row.get("case_name"),
            "case_index": last_row.get("case_index"),
            "case_count": last_row.get("case_count"),
            "params": _normalize_current_params(last_row.get("params", {})),
            "target_met": str(last_summary.get("target_met", "")).strip().lower() == "true",
        }

    return _build_task_dashboard_snapshot(
        config=config,
        task_type="val",
        current=current,
        best_curve=_curve_points_from_arrays(best_row.get("s_freqs", []), best_row.get("s11", []), "s11") if best_row else {"points": []},
        last_curve=_curve_points_from_arrays(last_row.get("s_freqs", []), last_row.get("s11", []), "s11") if last_row else {"points": []},
        best_s12_curve=_curve_points_from_arrays(best_row.get("s_freqs", []), best_row.get("s12", []), "s12") if best_row else {"points": []},
        last_s12_curve=_curve_points_from_arrays(last_row.get("s_freqs", []), last_row.get("s12", []), "s12") if last_row else {"points": []},
        current_metric=current_metric,
        best_metric=best_metric,
        fitness_history=history,
        events=[],
        status={"label": "Completed", "tone": "success", "detail": "Snapshot rebuilt from validation outputs"},
        started_at=run_started_at,
        max_simulations=len(data_rows),
        finished_at=finished_at,
        control=control,
    )


def rebuild_dashboard_snapshot(task_output_dir: str | Path) -> Optional[dict[str, Any]]:
    """Rebuild a dashboard snapshot from existing output files."""
    task_dir = Path(task_output_dir)
    config_path = task_dir / "config.json"
    config = None
    task_type = "opt"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fp:
            config = json.load(fp)
        if isinstance(config, dict):
            task_type = normalize_task_type(config)
    log_path = _first_existing_path(
        task_dir,
        [task_history_file_name(task_type), "history.csv", "log.csv"],
    )
    data_path = _first_existing_path(
        task_dir,
        [task_data_file_name(task_type, "jsonl"), task_data_file_name(task_type, "csv"), "data.jsonl", "data.csv"],
    )
    pareto_front_path = _first_existing_path(
        task_dir,
        [task_pareto_front_file_name(task_type, "json"), "pareto_front.json"],
    )
    summary_path = task_dir / "summary.json"
    control_path = _first_existing_path(
        task_dir,
        [task_dashboard_control_file_name(task_type), "dashboard_control.json"],
    )

    if config is None:
        return None

    summary_data = _load_json(summary_path)
    control_data = _load_json(control_path)
    control = control_data if isinstance(control_data, dict) else {}

    existing_files = [path for path in (config_path, log_path, data_path, pareto_front_path, summary_path) if path.exists()]
    run_started_at = min((path.stat().st_mtime for path in existing_files), default=None)
    finished_at = max((path.stat().st_mtime for path in existing_files), default=None)

    if isinstance(summary_data, dict):
        try:
            if summary_data.get("start_time"):
                run_started_at = datetime.fromisoformat(summary_data["start_time"]).timestamp()
        except Exception:
            pass
        try:
            if summary_data.get("end_time"):
                finished_at = datetime.fromisoformat(summary_data["end_time"]).timestamp()
        except Exception:
            pass

    if task_type == "sweep":
        return _rebuild_sweep_snapshot(
            task_dir=task_dir,
            config=config,
            control=control,
            run_started_at=run_started_at,
            finished_at=finished_at,
        )

    if task_type == "val":
        return _rebuild_val_snapshot(
            task_dir=task_dir,
            config=config,
            control=control,
            run_started_at=run_started_at,
            finished_at=finished_at,
        )

    target = config.get("target", {})
    param_configs = config.get("parameters", [])
    is_multi_objective = _is_multi_objective_config(target)
    log_rows = _load_csv_rows(log_path)
    data_rows = _load_jsonl_records(data_path)
    pareto_front = _load_json(pareto_front_path) if is_multi_objective else []
    if not isinstance(pareto_front, list):
        pareto_front = []

    if not log_rows and not data_rows:
        return build_dashboard_snapshot(
            config=config,
            current={},
            best_curve={"points": []},
            last_curve={"points": []},
            best_s12_curve={"points": []},
            last_s12_curve={"points": []},
            current_fitness=None,
            best_cost=None,
            fitness_history=[],
            events=[],
            status={"label": "Running", "tone": "running", "detail": "Waiting for first simulation"},
            started_at=run_started_at,
            pareto_front=pareto_front,
            finished_at=finished_at,
            control=control,
            best_pointing_curve={"points": []},
            last_pointing_curve={"points": []},
        )

    data_by_sim_id = {
        int(row.get("sim_id")): row
        for row in data_rows
        if row.get("sim_id") not in (None, "")
    }

    best_row = None
    representative_row = None
    current_log_row = log_rows[-1] if log_rows else None

    if is_multi_objective:
        valid_rows = [row for row in log_rows if _extract_objectives(row) or _parse_log_float(row, "constraint_violation") is not None]
        if valid_rows:
            representative_row = valid_rows[-1]
            best_row = representative_row
            current_log_row = representative_row
    elif log_rows:
        scored_rows = []
        for row in log_rows:
            cost = _parse_log_float(row, "cost")
            sim_id = row.get("sim_id")
            if cost is None or sim_id in (None, ""):
                continue
            scored_rows.append((cost, int(sim_id), row))
        if scored_rows:
            _, _, best_row = min(scored_rows, key=lambda item: item[0])

    current_row = None
    if current_log_row and current_log_row.get("sim_id") not in (None, ""):
        current_row = data_by_sim_id.get(int(current_log_row["sim_id"]))

    def _extract_curve(row: Optional[dict[str, Any]], value_key: str = "s11") -> dict[str, Any]:
        if not row:
            return {"points": []}
        sim_id_raw = row.get("sim_id")
        if sim_id_raw in (None, ""):
            return {"points": []}
        sim_id = int(sim_id_raw)
        record = data_by_sim_id.get(sim_id)
        if not record:
            return {"points": []}
        values = record.get(value_key, [])
        if not values and value_key == "s12":
            values = record.get("s21", [])
        return _curve_points_from_arrays(record.get("s_freqs", []), values, value_key)

    fitness_history = []
    for row in log_rows:
        sim_id = row.get("sim_id")
        iter_id = row.get("iter")
        cost = _parse_log_float(row, "cost")
        if sim_id in (None, "") or iter_id in (None, "") or cost is None:
            continue
        item = {
            "sim_id": int(sim_id),
            "iter_id": int(iter_id),
            "fitness": cost,
        }
        if is_multi_objective:
            item["constraint_violation"] = _parse_log_float(row, "constraint_violation")
            item["objectives"] = _extract_objectives(row)
        fitness_history.append(item)

    current = {}
    current_fitness = None
    last_sim_duration = None
    if current_log_row:
        current_sim_id = int(current_log_row.get("sim_id")) if current_log_row.get("sim_id") not in (None, "") else None
        params = {}
        if current_row and isinstance(current_row.get("params"), dict):
            params = current_row.get("params", {})
        elif isinstance(current_log_row, dict):
            params = _build_params_from_log_row(current_log_row, param_configs)
        current = {
            "sim_id": current_sim_id,
            "iter_id": int(current_log_row.get("iter")) if current_log_row.get("iter") not in (None, "") else None,
            "stage": "final",
            "checkpoint": str(current_log_row.get("checkpoint", "")).strip().lower() == "true",
            "params": params,
        }
        if is_multi_objective:
            current["objectives"] = _extract_objectives(current_log_row)
            current["constraint_violation"] = _parse_log_float(current_log_row, "constraint_violation")
        current_fitness = _parse_log_float(current_log_row, "cost")
        last_sim_duration = _parse_log_float(current_log_row, "sim_time")

    return build_dashboard_snapshot(
        config=config,
        current=current,
        best_curve=_extract_curve(best_row, "s11"),
        last_curve=_extract_curve(current_row, "s11"),
        best_s12_curve=_extract_curve(best_row, "s12"),
        last_s12_curve=_extract_curve(current_row, "s12"),
        current_fitness=current_fitness,
        best_cost=_parse_log_float(best_row, "cost") if best_row else None,
        fitness_history=fitness_history,
        events=[],
        status={"label": "Completed", "tone": "success", "detail": "Snapshot rebuilt from run outputs"},
        started_at=run_started_at,
        pareto_front=pareto_front,
        last_sim_duration=last_sim_duration,
        finished_at=finished_at,
        control=control,
        best_pointing_curve={"points": []},
        last_pointing_curve={"points": []},
    )
