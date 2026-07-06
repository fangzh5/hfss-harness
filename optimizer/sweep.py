"""Single-parameter HFSS sweep execution helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

try:
    from .core import build_step_sweep_values, summarize_sparameter_band
    from .dashboard.state_bridge import TaskDashboardStateWriter
    from .metrics import collect_optional_metrics
    from .output_names import task_data_file_name
    from .path_utils import resolve_run_stamp, resolve_task_output_dir
    from .result_records import build_far_field_meta_record, build_simulation_record
    from .task_config import validate_task_config
except ImportError:  # pragma: no cover
    from core import build_step_sweep_values, summarize_sparameter_band
    from dashboard.state_bridge import TaskDashboardStateWriter
    from metrics import collect_optional_metrics
    from output_names import task_data_file_name
    from path_utils import resolve_run_stamp, resolve_task_output_dir
    from result_records import build_far_field_meta_record, build_simulation_record
    from task_config import validate_task_config


def _resolve_task_output_dir(config: dict[str, Any]) -> Path:
    opt_config = config.get("optimization", {})
    run_stamp = resolve_run_stamp(opt_config.get("run_stamp"))
    task_output_dir = opt_config.get("task_output_dir") or resolve_task_output_dir(
        config,
        run_stamp=run_stamp,
    )
    return Path(task_output_dir)


def _capture_baseline(adapter) -> dict[str, Any]:
    if not hasattr(adapter, "capture_current_parameter_state"):
        raise RuntimeError("Adapter does not support parameter-state capture.")

    baseline = adapter.capture_current_parameter_state()
    if not isinstance(baseline, dict) or not baseline:
        raise RuntimeError("Failed to capture a baseline parameter state.")
    return baseline


def _restore_baseline(adapter, baseline: dict[str, Any]) -> None:
    if not hasattr(adapter, "restore_parameter_state"):
        raise RuntimeError("Adapter does not support parameter-state restore.")
    if not adapter.restore_parameter_state(baseline):
        raise RuntimeError("Failed to restore the baseline parameter state.")


def _set_named_parameter(adapter, name: str, value: float) -> None:
    if hasattr(adapter, "set_parameter"):
        if adapter.set_parameter(name, value):
            return
        raise RuntimeError(f"Failed to set parameter '{name}' to {value}.")

    if hasattr(adapter, "set_parameter_value"):
        if adapter.set_parameter_value(name, value):
            return
        raise RuntimeError(f"Failed to set parameter '{name}' to {value}.")

    raise RuntimeError("Adapter does not support setting named parameters.")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_sweep_summary(rows: list[dict[str, Any]], variables: list[str]) -> dict[str, Any]:
    if not rows:
        return {"records": 0, "variables": variables}

    best_s11 = min(rows, key=lambda item: float(item["s11_worst_db"]))
    summary: dict[str, Any] = {
        "records": len(rows),
        "variables": variables,
        "best_s11_worst": {
            "variable": best_s11["variable"],
            "value": best_s11["value"],
            "s11_worst_db": best_s11["s11_worst_db"],
            "s12_worst_db": best_s11.get("s12_worst_db"),
        },
    }
    s12_candidates = [row for row in rows if row.get("s12_worst_db") is not None]
    if s12_candidates:
        best_s12 = min(s12_candidates, key=lambda item: float(item["s12_worst_db"]))
        summary["best_s12_worst"] = {
            "variable": best_s12["variable"],
            "value": best_s12["value"],
            "s11_worst_db": best_s12["s11_worst_db"],
            "s12_worst_db": best_s12["s12_worst_db"],
        }
    return summary


def _write_summary_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    fig, axes = plt.subplots(2, 1, figsize=(8.5, 6.0), sharex=False)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["variable"]), []).append(row)

    for variable, items in grouped.items():
        items = sorted(items, key=lambda item: float(item["value"]))
        x = [float(item["value"]) for item in items]
        s11 = [float(item["s11_worst_db"]) for item in items]
        axes[0].plot(x, s11, marker="o", linewidth=1.8, label=variable)

        s12_values = [item.get("s12_worst_db") for item in items]
        if any(value is not None for value in s12_values):
            x2 = [x[idx] for idx, value in enumerate(s12_values) if value is not None]
            s12 = [float(value) for value in s12_values if value is not None]
            axes[1].plot(x2, s12, marker="o", linewidth=1.8, label=variable)

    axes[0].set_ylabel("Worst S11 (dB)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best", frameon=False)
    axes[1].set_xlabel("Sweep value")
    axes[1].set_ylabel("Worst S12 (dB)")
    axes[1].grid(True, alpha=0.3)
    if axes[1].lines:
        axes[1].legend(loc="best", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run_hfss_sweep(config: dict[str, Any], adapter) -> dict[str, Any]:
    """Run an HFSS sweep task where each variable is scanned independently."""
    task_type = validate_task_config(config)
    if task_type != "sweep":
        raise ValueError("run_hfss_sweep only accepts sweep configs.")

    study = config.get("study", {})
    variables = study.get("variables", [])
    freq_band = tuple(study.get("freq_band", [0.0, 0.0]))
    s11_threshold = float(study.get("s11_threshold", -10.0))
    s12_threshold = study.get("s12_threshold")
    s12_threshold = None if s12_threshold is None else float(s12_threshold)
    analysis_config = {
        "target": {
            "freq_band": study.get("freq_band"),
            "s11_threshold": study.get("s11_threshold"),
            "s12_threshold": study.get("s12_threshold"),
            "s21_threshold": study.get("s21_threshold"),
            "far_field": study.get("far_field"),
            "boresight": study.get("boresight"),
            "multi_objective": study.get("multi_objective"),
        }
    }

    task_output_dir = _resolve_task_output_dir(config)
    task_output_dir.mkdir(parents=True, exist_ok=True)

    total_points = 0
    for variable in variables:
        try:
            values = build_step_sweep_values(float(variable["start"]), float(variable["stop"]), float(variable["step"]))
            total_points += len(values)
        except Exception:
            continue

    baseline = _capture_baseline(adapter)
    summary_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    completed_points = 0
    far_field_meta_written = False
    dashboard_writer = None
    try:
        dashboard_writer = TaskDashboardStateWriter(task_output_dir, config, max_simulations=total_points)
    except Exception as exc:
        print(f"Dashboard snapshot writer disabled: {exc}")

    try:
        for variable_index, variable in enumerate(variables, start=1):
            name = str(variable["name"])
            start = float(variable["start"])
            stop = float(variable["stop"])
            step = float(variable["step"])
            values = build_step_sweep_values(start, stop, step)

            _restore_baseline(adapter, baseline)

            for point_index, value in enumerate(values, start=1):
                next_sim_id = completed_points + 1
                if dashboard_writer is not None:
                    try:
                        dashboard_writer.begin_simulation(
                            sim_id=next_sim_id,
                            detail={
                                "sweep_variable": name,
                                "value": float(value),
                                "point_index": point_index,
                                "point_count": len(values),
                            },
                            detail_text=f"Sweeping {name} @ {float(value):.4f}",
                        )
                    except Exception as exc:
                        print(f"Dashboard snapshot update failed: {exc}")
                        dashboard_writer = None
                print(
                    f"[progress] task=sweep phase=running sim_id={next_sim_id} total={total_points} "
                    f"variable={name} point_index={point_index} point_count={len(values)} value={float(value):.6f}",
                    flush=True,
                )
                _set_named_parameter(adapter, name, value)
                freqs, s11, s12 = adapter.simulate()
                if freqs is None or s11 is None:
                    print(
                        f"[progress] task=sweep phase=failed sim_id={next_sim_id} total={total_points} "
                        f"variable={name} point_index={point_index} point_count={len(values)} value={float(value):.6f}",
                        flush=True,
                    )
                    continue

                extra_metrics = {}
                try:
                    extra_metrics = collect_optional_metrics(analysis_config, adapter)
                except Exception:
                    extra_metrics = {}

                summary = summarize_sparameter_band(
                    freqs=freqs,
                    s11=s11,
                    s12=s12 if s12_threshold is not None else None,
                    freq_band=freq_band,
                    s11_threshold=s11_threshold,
                    s12_threshold=s12_threshold,
                )

                current_params = {}
                if hasattr(adapter, "capture_current_parameter_state"):
                    try:
                        current_params = adapter.capture_current_parameter_state()
                    except Exception:
                        current_params = {}

                if not far_field_meta_written:
                    far_field = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else None
                    if isinstance(far_field, dict):
                        meta_record = build_far_field_meta_record(far_field)
                        if meta_record is not None:
                            raw_rows.append(meta_record)
                            far_field_meta_written = True

                completed_points += 1
                raw_rows.append(
                    build_simulation_record(
                        sim_id=completed_points,
                        iter_num=completed_points,
                        params=current_params,
                        freqs=freqs,
                        s11=s11,
                        s12=s12,
                        extra_metrics=extra_metrics,
                        extra_fields={
                            "task_type": "sweep",
                            "variable": name,
                            "sweep_variable": name,
                            "variable_index": variable_index,
                            "point_index": point_index,
                            "point_count": len(values),
                            "value": float(value),
                            "sweep_summary": summary,
                        },
                    )
                )
                if dashboard_writer is not None:
                    try:
                        dashboard_writer.record_result(
                            sim_id=completed_points,
                            current={
                                "sweep_variable": name,
                                "value": float(value),
                                "point_index": point_index,
                                "point_count": len(values),
                                "params": current_params,
                                "summary": summary,
                            },
                            freqs=freqs,
                            s11=s11,
                            s12=s12,
                            metric_value=float(summary["s11_worst_db"]),
                            event_message=f"Best sweep point updated at sim_id {completed_points}",
                        )
                    except Exception as exc:
                        print(f"Dashboard snapshot update failed: {exc}")
                        dashboard_writer = None
                print(
                    f"[progress] task=sweep phase=done sim_id={completed_points} total={total_points} "
                    f"variable={name} point_index={point_index} point_count={len(values)} value={float(value):.6f}",
                    flush=True,
                )
                summary_rows.append(
                    {
                        "variable": name,
                        "variable_index": variable_index,
                        "point_index": point_index,
                        "point_count": len(values),
                        "value": float(value),
                        "freq_start_ghz": summary["freq_start_ghz"],
                        "freq_end_ghz": summary["freq_end_ghz"],
                        "band_point_count": summary["point_count"],
                        "s11_worst_db": summary["s11_worst_db"],
                        "s11_best_db": summary["s11_best_db"],
                        "s11_avg_db": summary["s11_avg_db"],
                        "s11_pass_count": summary["s11_pass_count"],
                        "s11_pass_ratio": summary["s11_pass_ratio"],
                        "s12_worst_db": summary.get("s12_worst_db"),
                        "s12_best_db": summary.get("s12_best_db"),
                        "s12_avg_db": summary.get("s12_avg_db"),
                        "s12_pass_count": summary.get("s12_pass_count"),
                        "s12_pass_ratio": summary.get("s12_pass_ratio"),
                    }
                )
    finally:
        _restore_baseline(adapter, baseline)

    raw_path = task_output_dir / task_data_file_name(task_type, "jsonl")
    summary_path = task_output_dir / "sweep_summary.csv"
    summary_json_path = task_output_dir / "summary.json"
    plot_path = task_output_dir / "sweep_summary.png"
    _write_jsonl(raw_path, raw_rows)
    _write_csv(summary_path, summary_rows)
    summary_payload = _build_sweep_summary(summary_rows, [str(item["name"]) for item in variables])
    summary_json_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_summary_plot(plot_path, summary_rows)
    if dashboard_writer is not None:
        try:
            dashboard_writer.finalize("Completed", f"Sweep finished with {completed_points} points")
        except Exception as exc:
            print(f"Dashboard snapshot finalize failed: {exc}")

    return {
        "task_output_dir": str(task_output_dir),
        "raw_path": str(raw_path),
        "summary_path": str(summary_path),
        "summary_json_path": str(summary_json_path),
        "plot_path": str(plot_path),
        "variables": [str(item["name"]) for item in variables],
        "total_points": total_points,
    }
