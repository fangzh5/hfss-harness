"""One checked case execution path, with durable records and baseline isolation."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
from typing import Any
import numpy as np

try:
    from .metrics import collect_optional_metrics, collect_geometry_snapshot
    from .result_records import build_simulation_record
except ImportError:  # pragma: no cover
    from metrics import collect_optional_metrics, collect_geometry_snapshot
    from result_records import build_simulation_record


class CaseJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Resume requires a validated manifest; never silently overwrite an earlier run.
        self.stream = self.path.open("x", encoding="utf-8")

    def append(self, record):
        self.stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        self.stream.close()


@dataclass
class CaseOutcome:
    case_id: int
    status: str
    params: dict[str, Any] = field(default_factory=dict)
    freqs: Any = None
    s11: Any = None
    s12: Any = None
    extra_metrics: dict = field(default_factory=dict)
    fitness: Any = None
    failure_reason: str | None = None
    duration_seconds: float = 0.0
    failure_phase: str | None = None
    simulation_attempted: bool = False
    result_acquired: bool = False
    restored_geometry: dict | None = None


class CaseExecutor:
    def __init__(self, adapter, calculator, config, baseline, journal, *, metrics_collector=None):
        self.adapter, self.calculator, self.config = adapter, calculator, config
        self.baseline = dict(baseline)
        self.journal = journal
        self.metrics_collector = metrics_collector or collect_optional_metrics
        self.geometry_baseline = collect_geometry_snapshot(config, adapter)
        if self.geometry_baseline is not None:
            self.journal.append({"record_type": "geometry_baseline", "snapshot": self.geometry_baseline})

    def restore(self):
        if not self.adapter.restore_parameter_state(self.baseline):
            raise RuntimeError("Case baseline restore failed; cannot safely continue")
        if self.geometry_baseline is None:
            return None
        snapshot = collect_geometry_snapshot(self.config, self.adapter)
        tolerance = float(self.config["output"]["geometry_snapshot"].get("absolute_tolerance", 1e-8))
        if snapshot["model_unit"] != self.geometry_baseline["model_unit"]:
            raise RuntimeError("Case baseline restore failed: geometry units changed")
        for name, obj in self.geometry_baseline["objects"].items():
            current = snapshot["objects"][name]["bounding_box"]
            if not np.allclose(current, obj["bounding_box"], atol=tolerance, rtol=0):
                raise RuntimeError(f"Case baseline restore failed: geometry mismatch for {name!r}")
        return snapshot

    def execute(self, case_id, values, *, fields=None, before_solve=None, restore_geometry=None,
                parameter_vector=None, enrich_metrics=None, already_started=False,
                retain_success_state=False):
        fields = dict(fields or {})
        started = time.time()
        if not already_started:
            self.journal.append({"record_type": "case_started", "case_id": case_id,
                                 "requested_params": values, "started_at_unix": started, **fields})
        outcome = CaseOutcome(case_id, "failed")
        phase = "restore"
        try:
            self.restore()
            phase = "apply"
            effective = dict(getattr(self.adapter, "config", {}).get("fixed_parameters") or {})
            if set(effective).intersection(values):
                raise ValueError("Fixed and case parameter names must not overlap")
            effective.update(values)
            unknown = set(effective) - self.baseline.keys()
            if unknown:
                raise ValueError(f"Unknown case parameters: {sorted(unknown)}")
            if parameter_vector is not None:
                names = list(self.adapter.config["param_names"])
                vector = np.asarray(parameter_vector, dtype=float)
                if vector.shape != (len(names),) or not np.all(np.isfinite(vector)) or set(values) != set(names):
                    raise ValueError("Vector and named case parameters must match the adapter contract")
                if not self.adapter.set_parameters(vector):
                    raise RuntimeError(getattr(self.adapter, "last_parameter_error", None)
                                       or "Parameter transaction failed")
            elif hasattr(self.adapter, "apply_parameter_values"):
                if not self.adapter.apply_parameter_values(effective):
                    raise RuntimeError(getattr(self.adapter, "last_parameter_error", None)
                                       or "Parameter transaction failed")
            else:
                for name, value in effective.items():
                    setter = getattr(self.adapter, "set_parameter", None) or getattr(
                        self.adapter, "set_parameter_value", None)
                    if setter is None or not setter(name, value):
                        raise RuntimeError(f"Failed to set parameter {name!r}")
            if before_solve is not None:
                before_solve()
            phase = "solve"
            outcome.simulation_attempted = True
            outcome.freqs, outcome.s11, outcome.s12 = self.adapter.simulate()
            if outcome.freqs is None or outcome.s11 is None:
                raise RuntimeError("Solve or result acquisition failed")
            outcome.result_acquired = True
            phase = "metrics"
            outcome.extra_metrics = self.metrics_collector(self.config, self.adapter)
            if enrich_metrics is not None:
                enrich_metrics(outcome.extra_metrics)
            json.dumps(outcome.extra_metrics, allow_nan=False)
            phase = "evaluate"
            outcome.fitness = self.calculator.calculate(
                outcome.freqs, outcome.s11, outcome.s12, extra_metrics=outcome.extra_metrics)
            if not getattr(outcome.fitness, "valid", True) or not np.isfinite(outcome.fitness.cost):
                raise RuntimeError(getattr(outcome.fitness, "failure_reason", None) or "Invalid result data")
            phase = "read_parameters"
            outcome.params = self.adapter.capture_current_parameter_state()
            bundle = getattr(self.adapter, "last_result_bundle", None)
            if bundle is not None and bundle.provenance.get("parameters") != outcome.params:
                raise RuntimeError("Parameters changed between result acquisition and evaluation")
            outcome.status = "completed"
        except Exception as exc:
            outcome.failure_reason = str(exc)
            outcome.failure_phase = phase
        except BaseException as exc:
            self.journal.append({"record_type": "case_finished", "case_id": case_id,
                                 "status": "cancelled", "failure_reason": type(exc).__name__, **fields})
            raise
        finally:
            try:
                if restore_geometry is not None:
                    restore_geometry()
            finally:
                try:
                    if not retain_success_state or outcome.status != "completed":
                        outcome.restored_geometry = self.restore()
                except Exception as exc:
                    event = {"record_type": "case_restore_failed", "case_id": case_id,
                             "status": "failed", "failure_reason": str(exc), **fields}
                    if outcome.fitness is not None and getattr(outcome.fitness, "valid", True):
                        event["result"] = build_simulation_record(
                            case_id, case_id, outcome.params, outcome.freqs, outcome.s11, outcome.s12,
                            extra_metrics=outcome.extra_metrics, extra_fields=fields)
                    self.journal.append(event)
                    raise
        outcome.duration_seconds = time.time() - started
        event = {"record_type": "case_finished", "case_id": case_id, "status": outcome.status,
                 "failure_reason": outcome.failure_reason, "duration_seconds": outcome.duration_seconds,
                 "failure_phase": outcome.failure_phase,
                 "requested_params": values, **fields}
        if outcome.restored_geometry is not None:
            event["restored_geometry"] = outcome.restored_geometry
        if outcome.status == "completed":
            event["result"] = build_simulation_record(
                case_id, case_id, outcome.params, outcome.freqs, outcome.s11, outcome.s12,
                extra_metrics=outcome.extra_metrics, extra_fields=fields)
            event["evaluation"] = {"valid": True, "target_met": bool(outcome.fitness.target_met),
                                   "cost": float(outcome.fitness.cost)}
            event["result_bundle"] = outcome.extra_metrics.get("result_bundle")
            event["extra_metrics"] = outcome.extra_metrics
        self.journal.append(event)
        return outcome


def finish_journal(journal, *, status, reason=None, writer=None):
    journal.append({"record_type": "task_finished", "status": status,
                    "reason": reason, "finished_at_unix": time.time()})
    if writer is not None:
        try:
            writer.finalize(status, reason or "Task finished")
        except Exception as exc:
            print(f"Dashboard finalization failed: {exc}")
