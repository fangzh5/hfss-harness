"""Case-by-case validation runner."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

try:
    from .core import FitnessCalculator
    from .dashboard.state_bridge import TaskDashboardStateWriter
    from .metrics import collect_optional_metrics
    from .output_names import (
        task_data_file_name,
        task_overview_file_name,
        task_report_file_name,
        task_results_file_name,
    )
    from .path_utils import resolve_run_stamp, resolve_task_output_dir
    from .result_records import build_simulation_record
    from .task_config import validate_task_config
except ImportError:  # pragma: no cover
    from core import FitnessCalculator
    from dashboard.state_bridge import TaskDashboardStateWriter
    from metrics import collect_optional_metrics
    from output_names import (
        task_data_file_name,
        task_overview_file_name,
        task_report_file_name,
        task_results_file_name,
    )
    from path_utils import resolve_run_stamp, resolve_task_output_dir
    from result_records import build_simulation_record
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


def _serialize_csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _serialize_csv_value(value) for key, value in row.items()})


def _case_name(case: dict[str, Any], index: int) -> str:
    name = case.get("name")
    if name:
        return str(name)
    return f"case_{index:03d}"


def _case_params(case: dict[str, Any]) -> dict[str, Any]:
    params = case.get("params")
    if isinstance(params, dict) and params:
        return dict(params)
    return {
        str(key): value
        for key, value in case.items()
        if key not in {"name", "params"}
    }


def _summarize_far_field(extra_metrics: dict[str, Any]) -> dict[str, Any]:
    far_field = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else None
    if not isinstance(far_field, dict):
        return {}
    summary = far_field.get("summary")
    return summary if isinstance(summary, dict) else {}


def _build_report_md(config: dict[str, Any], summary_rows: list[dict[str, Any]], report_path: Path) -> str:
    lines = [
        "# Validation Report",
        "",
        f"- `task_type`: `{config.get('task_type', 'val')}`",
        f"- `task_output_dir`: `{report_path.parent}`",
        f"- `case_count`: `{len(summary_rows)}`",
        "",
    ]

    if not summary_rows:
        lines.append("No validation cases were evaluated.")
        return "\n".join(lines) + "\n"

    ranked = sorted(summary_rows, key=lambda row: (row.get("cost") is None, row.get("cost", float("inf"))))
    lines.extend(
        [
            "## Case Summary",
            "",
            "| Case | Cost | S11 max (dB) | S12 max (dB) | Pointing error (deg) | Target met |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in ranked:
        lines.append(
            "| {case} | {cost} | {s11} | {s12} | {pe} | {met} |".format(
                case=row.get("case_name", ""),
                cost=f"{float(row['cost']):.4f}" if row.get("cost") is not None else "N/A",
                s11=f"{float(row['s11_max']):.2f}" if row.get("s11_max") is not None else "N/A",
                s12=f"{float(row['s12_max']):.2f}" if row.get("s12_max") is not None else "N/A",
                pe=(
                    f"{float(row['pointing_error_worst_deg']):.3f}"
                    if row.get("pointing_error_worst_deg") is not None
                    else "N/A"
                ),
                met=str(bool(row.get("target_met", False))),
            )
        )

    return "\n".join(lines) + "\n"


def _plot_overview(output_path: Path, summary_rows: list[dict[str, Any]]) -> None:
    if not summary_rows:
        return

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax_s11, ax_metric = axes
    colors = plt.cm.tab20(np.linspace(0, 1, max(len(summary_rows), 1)))

    for idx, row in enumerate(summary_rows):
        freqs = row.get("freqs", [])
        s11 = row.get("s11", [])
        if freqs and s11:
            ax_s11.plot(freqs, s11, marker="o", linewidth=1.2, color=colors[idx], label=row.get("case_name", f"case_{idx+1}"))

    ax_s11.axhline(float(summary_rows[0].get("s11_threshold", -10.0)), color="#999999", linestyle="--", linewidth=1)
    ax_s11.set_title("S11 Curves")
    ax_s11.set_xlabel("Frequency (GHz)")
    ax_s11.set_ylabel("S11 (dB)")
    ax_s11.grid(True, alpha=0.3)
    if len(summary_rows) <= 8:
        ax_s11.legend(fontsize=8)

    case_names = [row.get("case_name", f"case_{idx+1}") for idx, row in enumerate(summary_rows)]
    costs = [float(row.get("cost", 0.0)) if row.get("cost") is not None else 0.0 for row in summary_rows]
    pe_values = [
        float(row.get("pointing_error_worst_deg", 0.0)) if row.get("pointing_error_worst_deg") is not None else 0.0
        for row in summary_rows
    ]
    x = np.arange(len(case_names))
    width = 0.38
    ax_metric.bar(x - width / 2, costs, width, label="Cost", color="#3b82f6")
    ax_metric.bar(x + width / 2, pe_values, width, label="Pointing error", color="#f97316")
    ax_metric.set_title("Case Ranking")
    ax_metric.set_xticks(x)
    ax_metric.set_xticklabels(case_names, rotation=30, ha="right")
    ax_metric.grid(True, axis="y", alpha=0.3)
    ax_metric.legend()

    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def run_val_cases(config: dict[str, Any], adapter) -> dict[str, Any]:
    """Run a batch validation task for explicit parameter cases."""
    task_type = validate_task_config(config)
    if task_type != "val":
        raise ValueError("run_val_cases only accepts val configs.")

    target = config.get("target", {})
    cases = config.get("cases", [])
    output_config = config.get("output", {})
    task_output_dir = _resolve_task_output_dir(config)
    task_output_dir.mkdir(parents=True, exist_ok=True)

    raw_format = str(output_config.get("raw_data_format", "jsonl")).lower()
    raw_path = task_output_dir / task_data_file_name(task_type, raw_format)
    summary_path = task_output_dir / task_results_file_name(task_type)
    report_path = task_output_dir / task_report_file_name(task_type)
    overview_path = task_output_dir / task_overview_file_name(task_type)

    baseline = _capture_baseline(adapter)
    summary_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    case_details: list[dict[str, Any]] = []
    total_cases = 0
    case_count = len(cases)
    far_field_meta_written = False
    dashboard_writer = None

    fitness_calc = FitnessCalculator(
        freq_band=tuple(target.get("freq_band", [0, 0])),
        s11_target=target.get("s11_threshold", -10),
        s12_target=target.get("s12_threshold", target.get("s21_threshold")),
        bandwidth_target=target.get("bandwidth_target"),
        gain_target=target.get("gain_min"),
        stages=target.get("stages"),
        objective_mode=target.get("objective_mode", "legacy"),
        fitness_config=target.get("fitness"),
        multi_objective_config=target.get("multi_objective"),
        s11_profile=target.get("s11_profile"),
    )
    try:
        dashboard_writer = TaskDashboardStateWriter(task_output_dir, config, max_simulations=case_count)
    except Exception as exc:
        print(f"Dashboard snapshot writer disabled: {exc}")

    try:
        for index, case in enumerate(cases, start=1):
            case_name = _case_name(case, index)
            params = _case_params(case)

            _restore_baseline(adapter, baseline)
            for name, value in params.items():
                _set_named_parameter(adapter, str(name), float(value))

            next_sim_id = total_cases + 1
            if dashboard_writer is not None:
                try:
                    dashboard_writer.begin_simulation(
                        sim_id=next_sim_id,
                        detail={
                            "case_name": case_name,
                            "case_index": index,
                            "case_count": len(cases),
                        },
                        detail_text=f"Validating {case_name}",
                    )
                except Exception as exc:
                    print(f"Dashboard snapshot update failed: {exc}")
                    dashboard_writer = None
            print(
                f"[progress] task=val phase=running sim_id={next_sim_id} total={case_count} "
                f"case={case_name} case_index={index}",
                flush=True,
            )
            freqs, s11, s12 = adapter.simulate()
            if freqs is None or s11 is None:
                print(
                    f"[progress] task=val phase=failed sim_id={next_sim_id} total={case_count} "
                    f"case={case_name} case_index={index}",
                    flush=True,
                )
                continue

            extra_metrics = {}
            try:
                extra_metrics = collect_optional_metrics(config, adapter)
            except Exception as exc:
                print(f"Optional far-field metric collection failed for {case_name}: {exc}")
                extra_metrics = {}

            far_field_summary = _summarize_far_field(extra_metrics)
            if not far_field_meta_written:
                far_field = extra_metrics.get("far_field") if isinstance(extra_metrics, dict) else None
                if isinstance(far_field, dict):
                    meta = far_field.get("summary")
                    if isinstance(meta, dict):
                        far_field_meta_written = True

            fitness = fitness_calc.calculate(freqs, s11, s12, extra_metrics=extra_metrics)
            total_cases += 1

            current_params = {}
            if hasattr(adapter, "capture_current_parameter_state"):
                try:
                    current_params = adapter.capture_current_parameter_state()
                except Exception:
                    current_params = {}

            raw_rows.append(
                build_simulation_record(
                    sim_id=next_sim_id,
                    iter_num=next_sim_id,
                    params=current_params,
                    freqs=freqs,
                    s11=s11,
                    s12=s12,
                    extra_metrics=extra_metrics,
                    extra_fields={
                        "task_type": "val",
                        "case_name": case_name,
                        "case_index": index,
                        "case_count": len(cases),
                    },
                )
            )

            summary_row = {
                "case_name": case_name,
                "case_index": index,
                "case_count": len(cases),
                "sim_id": total_cases,
                "cost": float(fitness.cost),
                "s11_max": fitness.s11_max,
                "bandwidth": fitness.bandwidth,
                "s12_max": fitness.s12_max,
                "target_met": fitness.target_met,
                "freqs": [float(value) for value in np.asarray(freqs, dtype=float).tolist()],
                "s11": [float(value) for value in np.asarray(s11, dtype=float).tolist()],
                "s11_threshold": float(target.get("s11_threshold", -10.0)),
                "pointing_error_worst_deg": far_field_summary.get("worst_pointing_error_deg"),
                "pointing_error_best_deg": far_field_summary.get("best_pointing_error_deg"),
                "pointing_error_avg_deg": far_field_summary.get("average_pointing_error_deg"),
                "peak_loss_worst_db": far_field_summary.get("worst_peak_loss_db"),
                "peak_loss_best_db": far_field_summary.get("best_peak_loss_db"),
                "peak_loss_avg_db": far_field_summary.get("average_peak_loss_db"),
            }
            summary_rows.append(summary_row)
            case_details.append(summary_row)
            if dashboard_writer is not None:
                try:
                    dashboard_writer.record_result(
                        sim_id=next_sim_id,
                        current={
                            "case_name": case_name,
                            "case_index": index,
                            "case_count": len(cases),
                            "params": current_params,
                            "target_met": bool(fitness.target_met),
                        },
                        freqs=freqs,
                        s11=s11,
                        s12=s12,
                        metric_value=float(fitness.cost),
                        event_message=f"Best validation case updated at sim_id {next_sim_id}",
                    )
                except Exception as exc:
                    print(f"Dashboard snapshot update failed: {exc}")
                    dashboard_writer = None
            print(
                f"[progress] task=val phase=done sim_id={next_sim_id} total={case_count} "
                f"case={case_name} case_index={index} cost={float(fitness.cost):.4f}",
                flush=True,
            )
    finally:
        _restore_baseline(adapter, baseline)

    if raw_format == "csv":
        _write_csv(raw_path, raw_rows)
    else:
        _write_jsonl(raw_path, raw_rows)
    _write_csv(summary_path, summary_rows)
    report_md = _build_report_md(config, summary_rows, report_path)
    report_path.write_text(report_md, encoding="utf-8")
    _plot_overview(overview_path, summary_rows)
    if dashboard_writer is not None:
        try:
            dashboard_writer.finalize("Completed", f"Validation finished with {total_cases} cases")
        except Exception as exc:
            print(f"Dashboard snapshot finalize failed: {exc}")

    return {
        "task_output_dir": str(task_output_dir),
        "data_path": str(raw_path),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
        "overview_path": str(overview_path),
        "total_cases": total_cases,
        "cases": case_details,
    }
