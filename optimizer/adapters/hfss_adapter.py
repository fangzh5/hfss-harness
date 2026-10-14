"""
HFSS仿真器适配器
通过PyAEDT连接HFSS进行仿真
支持文件复制保护、最优结果保存等功能
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import math
import re
import shutil
import time
import uuid
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, Iterable, Any
try:
    from .base import SimulatorAdapter
    from ..task_config import normalize_task_type, resolve_evaluation_mode
    from ..results import TraceData, ResultBundle, frequency_to_ghz
    from ..provenance import file_sha256
except ImportError:  # pragma: no cover
    from adapters.base import SimulatorAdapter
    from task_config import normalize_task_type, resolve_evaluation_mode
    from results import TraceData, ResultBundle, frequency_to_ghz
    from provenance import file_sha256


class HFSSAdapter(SimulatorAdapter):
    """
    HFSS适配器

    运行模式：
    - 前台运行: non_graphical=false, new_desktop=false (显示AEDT窗口)
    - 后台运行: non_graphical=true, new_desktop=true (不显示窗口)

    文件保护机制：
    - 原始文件复制到临时工作目录，所有操作在工作副本上进行
    - 优化结束后保存最优结果，并清理临时副本
    """

    def __init__(self, config: dict, optimization_config: dict = None, task_name: str = None):
        super().__init__(config)
        self.optimization_config = optimization_config or {}
        self.task_type = normalize_task_type(self.optimization_config)
        self.evaluation_mode = resolve_evaluation_mode({
            "optimization": self.optimization_config, "simulator": {"hfss": config}})
        if self.task_type in {"opt", "sweep"} and self.evaluation_mode != "solve":
            raise ValueError("Optimization and sweep tasks must solve a protected work copy")
        self.config = dict(config)
        self.config["skip_simulation"] = self.evaluation_mode == "existing_results"
        self.task_name = task_name or "task"
        self.app = None
        self.work_project_path = None
        self.task_output_dir = self.optimization_config.get("task_output_dir")
        self.use_original_project = bool(self.optimization_config.get("use_original_project", False))
        self.original_project_path = config.get('project_path', '')
        if not os.path.isabs(self.original_project_path):
            self.original_project_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                self.original_project_path
            )
        self.original_project_dir = os.path.dirname(self.original_project_path)
        self.best_params = None
        self.best_fitness = float('inf')
        self.current_params = None
        self._parameter_units: dict[str, str] = {}
        self._parameter_baseline: dict[str, Any] = {}
        self._parameter_state_valid = True
        self._failed_parameter_snapshot = {}
        self.last_parameter_error = None
        self.last_result_bundle = None
        self._last_trace_source = {}
        self._result_context = {}
        self.source_project_sha256 = None
        self.execution_fingerprint = None

    def _get_results_dir(self) -> str:
        """获取结果保存目录（原始项目目录下的results文件夹）"""
        if self.task_output_dir:
            return str(self.task_output_dir)

        repo_root = os.path.dirname(self.original_project_dir)
        return os.path.join(repo_root, 'runs', self.task_name)

    def _get_temp_dir(self) -> str:
        """获取优化临时目录。"""
        work_dir = self.optimization_config.get('work_dir')
        if work_dir:
            if not os.path.isabs(work_dir):
                work_dir = os.path.abspath(os.path.join(self.original_project_dir, work_dir))
            return work_dir
        repo_root = os.path.dirname(self.original_project_dir)
        return os.path.join(repo_root, 'temp', self.task_name)

    def _get_setup_sweep_name(self) -> str:
        """生成HFSS的 setup/sweep 名称。"""
        setup_name = self.config.get('setup_name', 'Setup1')
        sweep_name = self.config.get('sweep_name', 'Sweep')
        return f"{setup_name} : {sweep_name}"

    def _get_solve_targets(self) -> list[str]:
        """Return AEDT analysis targets in priority order."""
        setup_name = self.config.get('setup_name', 'Setup1')
        sweep_name = self.config.get('sweep_name')
        analyze_sweep_target = bool(self.config.get('analyze_setup_sweep_target', False))

        targets: list[str] = []
        if analyze_sweep_target and setup_name and sweep_name:
            targets.append(f"{setup_name} : {sweep_name}")
        targets.append(setup_name)

        seen: set[str] = set()
        ordered: list[str] = []
        for target in targets:
            if not target or target in seen:
                continue
            seen.add(target)
            ordered.append(target)
        return ordered or [setup_name]

    def _ensure_configured_sweep(self) -> bool:
        """Create the configured band sweep in the working copy when requested."""
        if not self.config.get('create_band_sweep', False):
            return True
        if not self.app:
            return False

        setup_name = self.config.get('setup_name', 'Setup1')
        sweep_name = self.config.get('sweep_name', 'CodexBand')
        expected_band = self.config.get('expected_freq_band')
        step = self.config.get('sweep_step_ghz')
        if not expected_band or step is None:
            print("Configured band sweep requires expected_freq_band and sweep_step_ghz")
            return False

        try:
            existing = list(self.app.get_sweeps(setup_name) or [])
        except Exception as exc:
            print(f"Failed to list sweeps for {setup_name}: {exc}")
            existing = []

        if sweep_name in existing:
            return True

        try:
            sweep = self.app.create_linear_step_sweep(
                setup=setup_name,
                unit="GHz",
                start_frequency=float(expected_band[0]),
                stop_frequency=float(expected_band[1]),
                step_size=float(step),
                name=sweep_name,
                save_fields=bool(self.config.get('save_sweep_fields', False)),
                save_rad_fields=bool(self.config.get('save_sweep_rad_fields', False)),
                sweep_type=self.config.get('sweep_type', 'Discrete'),
            )
            if not sweep:
                print(f"Failed to create sweep {setup_name} : {sweep_name}")
                return False
            print(
                f"Created sweep {setup_name} : {sweep_name} "
                f"({expected_band[0]}-{expected_band[1]} GHz, step {step} GHz)"
            )
            return True
        except Exception as exc:
            print(f"Failed to create sweep {setup_name} : {sweep_name}: {exc}")
            return False

    def _solution_frequency_coverage_ok(self, freqs: np.ndarray, label: str) -> bool:
        """Reject accidental adaptive-only single-point data for band targets."""
        if freqs is None:
            return False

        expected_band = self.config.get('expected_freq_band')
        if not expected_band:
            return True

        try:
            start, stop = float(expected_band[0]), float(expected_band[1])
        except Exception:
            return False

        values = np.asarray(freqs, dtype=float)
        if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
            return False

        in_band = values[(values >= start - 1e-9) & (values <= stop + 1e-9)]
        min_points = int(self.config.get('min_band_points', 2))
        if start == stop:
            min_points = 1
        if values[0] > start + 1e-8 or values[-1] < stop - 1e-8:
            print(f"Rejected solution data ({label}): missing frequency band boundaries")
            return False
        if in_band.size < min_points:
            print(
                f"Rejected solution data ({label}): "
                f"{in_band.size} points in expected band {start:g}-{stop:g} GHz"
            )
            return False
        return True

    def _is_sweep_task(self) -> bool:
        return self.task_type == "sweep"

    @staticmethod
    def _to_plain_string(value: Any) -> str:
        if isinstance(value, str):
            return value
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:
                pass
        return str(value)

    @staticmethod
    def _split_numeric_unit(value: Any) -> tuple[float | None, str]:
        if isinstance(value, (int, float, np.integer, np.floating)):
            return float(value), ""
        text = HFSSAdapter._to_plain_string(value).strip()
        match = re.match(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z_][A-Za-z0-9_/-]*)?\s*$", text)
        if not match:
            return None, ""
        numeric = float(match.group(1))
        unit = match.group(2) or ""
        return numeric, unit

    def _format_parameter_assignment(
        self,
        name: str,
        value: Any,
        unit: str | None = None,
        resolution: float | None = None,
    ) -> str:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError(f"{name}: assignment must not be empty")
            numeric_value, _ = self._split_numeric_unit(value)
            if numeric_value is not None and not math.isfinite(numeric_value):
                raise ValueError(f"{name}: value must be finite")
            return value

        raw_unit = unit or self._parameter_units.get(name, "")
        if not raw_unit and name in self._parameter_baseline:
            _, raw_unit = self._split_numeric_unit(self._parameter_baseline[name])

        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name}: value must be finite")
        if resolution:
            try:
                resolution_value = float(resolution)
            except Exception:
                resolution_value = 0.0
            if resolution_value > 0.0:
                numeric = round(numeric / resolution_value) * resolution_value
        return f"{numeric:.17g}{raw_unit}"

    def _read_parameter_expression(self, name: str) -> str:
        manager = getattr(self.app, "variable_manager", None)
        if manager is not None:
            if name not in manager.variable_names:
                raise ValueError(f"Unknown AEDT parameter {name!r}")
            value = manager.get_expression(name)
        else:
            value = self.app[name]
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Could not read AEDT parameter {name!r}")
        return value

    def _assignment_matches(self, name: str, expected: str) -> bool:
        actual = self._read_parameter_expression(name)
        number, unit = self._split_numeric_unit(expected)
        actual_number, actual_unit = self._split_numeric_unit(actual)
        if number is not None:
            if actual_number is None or unit != actual_unit:
                if not hasattr(self.app, "get_evaluated_value"):
                    return False
                if actual_number is not None and unit != actual_unit:
                    from ansys.aedt.core.generic.constants import unit_system
                    expected_system, actual_system = unit_system(unit), unit_system(actual_unit)
                    if not expected_system or expected_system != actual_system:
                        return False
                actual_number = self.app.get_evaluated_value(name, units=unit or None)
            if type(actual_number) is bool:
                return False
            return math.isfinite(float(actual_number)) and math.isclose(
                float(actual_number), number, rel_tol=1e-10, abs_tol=1e-15)
        if "".join(actual.split()) != "".join(expected.split()):
            return False
        if hasattr(self.app, "get_evaluated_value"):
            evaluated = self.app.get_evaluated_value(name)
            return type(evaluated) is not bool and math.isfinite(float(evaluated))
        return True

    def apply_parameter_values(self, values: dict[str, Any], *, units=None, resolutions=None) -> bool:
        """Apply existing variables atomically and verify fresh AEDT readback."""
        if not self.app:
            return False
        units, resolutions = units or {}, resolutions or {}
        snapshot = {}
        write_attempted = False
        try:
            # Read everything before any write, including units for named val/sweep updates.
            snapshot = {name: self._read_parameter_expression(name) for name in values}
            for name, expression in snapshot.items():
                _, inferred_unit = self._split_numeric_unit(expression)
                if inferred_unit:
                    self._parameter_units[name] = inferred_unit
            assignments = {name: self._format_parameter_assignment(
                name, value, unit=units.get(name), resolution=resolutions.get(name))
                for name, value in values.items()}
            if self.evaluation_mode == "existing_results":
                if not all(self._assignment_matches(name, value) for name, value in assignments.items()):
                    raise ValueError("Existing results cannot be evaluated with changed model parameters")
                return True
            for name, assignment in assignments.items():
                write_attempted = True
                self.app[name] = assignment
            for name, assignment in assignments.items():
                if not self._assignment_matches(name, assignment):
                    raise RuntimeError(f"AEDT readback mismatch for {name!r}")
            self.last_parameter_error = None
            return True
        except Exception as exc:
            rollback_errors = []
            if write_attempted:
                for name, expression in snapshot.items():
                    try:
                        self.app[name] = expression
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{name}: {rollback_exc}")
                for name, expression in snapshot.items():
                    try:
                        if not self._assignment_matches(name, expression):
                            raise RuntimeError("rollback readback mismatch")
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{name}: {rollback_exc}")
            if rollback_errors:
                self._parameter_state_valid = False
                self._failed_parameter_snapshot = snapshot.copy()
            self.last_parameter_error = str(exc)
            if rollback_errors:
                self.last_parameter_error += "; rollback failed: " + "; ".join(rollback_errors)
            print(f"Parameter transaction failed: {self.last_parameter_error}")
            return False

    def capture_current_parameter_state(self, param_names: Iterable[str] | None = None) -> dict[str, Any]:
        """Capture the current design variable state from AEDT."""
        if not self.app:
            raise RuntimeError("HFSS is not connected.")

        variations = getattr(self.app, "available_variations", None)
        nominal_values = getattr(variations, "nominal_values", {}) if variations is not None else {}
        baseline: dict[str, Any] = {}

        if isinstance(nominal_values, dict):
            for name, value in nominal_values.items():
                baseline[str(name)] = self._to_plain_string(value)
                _, unit = self._split_numeric_unit(value)
                if unit:
                    self._parameter_units[str(name)] = unit

        manager = getattr(self.app, "variable_manager", None)
        names = list(param_names) if param_names is not None else (
            list(manager.variable_names) if manager is not None else list(baseline))
        for name in names:
            baseline[str(name)] = self._read_parameter_expression(str(name))

        self._parameter_baseline = baseline.copy()
        return baseline

    def restore_parameter_state(self, state: dict[str, Any]) -> bool:
        """Restore a previously captured parameter state."""
        if not self.app:
            return False

        if self.apply_parameter_values(state):
            if set(self._failed_parameter_snapshot).issubset(state):
                self._parameter_state_valid = True
                self._failed_parameter_snapshot = {}
            self._parameter_baseline = dict(state)
            return True
        return False

    def _iter_candidate_setup_sweeps(self) -> list[str]:
        """Return setup/sweep names in priority order.

        The configured setup/sweep is tried first, then any sweeps discovered from the
        active AEDT design. This keeps the code resilient across projects whose nominal
        sweep name is not exactly what the config declares.
        """
        candidates: list[str] = []

        setup_name = self.config.get('setup_name')
        sweep_name = self.config.get('sweep_name')
        if setup_name and sweep_name:
            return [f"{setup_name} : {sweep_name}"]
        if setup_name:
            return [f"{setup_name} : LastAdaptive"]

        if self.app:
            nominal_sweep = getattr(self.app, 'nominal_sweep', None)
            if nominal_sweep:
                candidates.append(nominal_sweep)

            nominal_adaptive = getattr(self.app, 'nominal_adaptive', None)
            if nominal_adaptive:
                candidates.append(nominal_adaptive)

            existing = getattr(self.app, 'existing_analysis_sweeps', None) or []
            if setup_name:
                prefix = f"{setup_name} : "
                for item in existing:
                    if item.startswith(prefix):
                        candidates.append(item)
                if setup_name in existing:
                    candidates.append(setup_name)
            else:
                candidates.extend(existing)

        seen: set[str] = set()
        ordered: list[str] = []
        for item in candidates:
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def _clean_lock_files(self, project_path: str):
        """清理项目目录下的锁文件"""
        project_dir = os.path.dirname(project_path)
        if not os.path.exists(project_dir):
            return

        project_name = Path(project_path).stem
        for filename in os.listdir(project_dir):
            if filename.startswith(project_name) and filename.endswith('.aedt.lock'):
                lock_path = os.path.join(project_dir, filename)
                try:
                    os.remove(lock_path)
                    print(f"Cleaned lock file: {lock_path}")
                except Exception as e:
                    print(f"Failed to clean lock file: {lock_path}, {e}")

    def connect(self) -> bool:
        """连接到HFSS项目"""
        if self._is_connected:
            return True

        skip_simulation = self.config.get('skip_simulation', False)
        if skip_simulation or self.use_original_project:
            self.work_project_path = self.original_project_path
            try:
                self.source_project_sha256 = file_sha256(self.original_project_path)
            except OSError as exc:
                print(f"Cannot fingerprint existing-results source: {exc}")
                return False
            mode_label = "Read-only mode" if skip_simulation else "Direct-project mode"
            print(f"{mode_label}: use the original file")
        else:
            try:
                self.work_project_path = self._copy_project_to_work_dir()
            except (OSError, ValueError) as exc:
                print(f"Failed to prepare protected work copy: {exc}")
                self.work_project_path = None
                self._is_connected = False
                return False
            self._clean_lock_files(self.work_project_path)

        if not os.path.exists(self.work_project_path):
            print(f"Error: project file not found: {self.work_project_path}")
            self._is_connected = False
            return False

        try:
            from ansys.aedt.core import Hfss

            use_grpc_api = self.config.get('use_grpc_api')
            if use_grpc_api is not None:
                from ansys.aedt.core import settings
                settings.use_grpc_api = bool(use_grpc_api)

            print(f"Connecting to HFSS...")
            print(f"  Project: {self.work_project_path}")
            print(f"  Mode: non_graphical={self.config.get('non_graphical', True)}")
            if use_grpc_api is not None:
                api_mode = "gRPC" if bool(use_grpc_api) else "COM"
                print(f"  PyAEDT API: {api_mode}")
            self.app = Hfss(
                project=self.work_project_path,
                design=self.config.get('design_name', ''),
                version=self.config.get('aedt_version', '2023.2'),
                non_graphical=self.config.get('non_graphical', True),
                new_desktop=self.config.get('new_desktop', True),
                remove_lock=self.config.get('remove_lock', False),
                close_on_exit=False
            )
            if getattr(self.app, "valid_design", True) is not True:
                raise RuntimeError(
                    "PyAEDT returned an invalid HFSS design handle "
                    f"for project={self.work_project_path!r}, "
                    f"design={self.config.get('design_name', '')!r}"
                )
            self._is_connected = True
            print(f"Connected to HFSS project")
            return True

        except Exception as e:
            print(f"Failed to connect to HFSS: {e}")
            self._is_connected = False
            return False

    def _copy_project_to_work_dir(self) -> str:
        """复制原始AEDT文件到工作目录"""
        if not self.original_project_path:
            raise ValueError("An AEDT source project is required")

        if not os.path.exists(self.original_project_path):
            raise FileNotFoundError(f"AEDT source project not found: {self.original_project_path}")

        work_dir = self._get_temp_dir()

        suffix = self.optimization_config.get('project_suffix', '')

        os.makedirs(work_dir, exist_ok=True)

        original_name = Path(self.original_project_path).stem
        original_ext = Path(self.original_project_path).suffix

        new_name = f"{original_name}{suffix}_{self.task_name}{original_ext}"
        work_path = os.path.join(work_dir, new_name)

        if Path(work_path).resolve() == Path(self.original_project_path).resolve() or (
            os.path.exists(work_path) and os.path.samefile(work_path, self.original_project_path)
        ):
            raise ValueError("AEDT work copy must be separate from the source project")

        if os.path.exists(work_path):
            raise FileExistsError(
                f"Work copy already exists; use a fresh task directory: {work_path}")

        try:
            source_hash = file_sha256(self.original_project_path)
            if os.path.isdir(self.original_project_path):
                shutil.copytree(self.original_project_path, work_path)
            else:
                shutil.copy2(self.original_project_path, work_path)
            if file_sha256(work_path) != source_hash or file_sha256(self.original_project_path) != source_hash:
                raise OSError("AEDT source changed during copying or the copy is incomplete")
            self.source_project_sha256 = source_hash
            print(f"Copied original file to: {work_path}")
        except OSError as e:
            raise OSError(f"Cannot create AEDT work copy at {work_path}: {e}") from e

        return work_path

    def _remove_path(self, path: Path):
        """Remove a file or directory if it exists."""
        if not path.exists():
            return

        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _is_transient_cleanup_error(self, error: Exception) -> bool:
        """Return True when a cleanup failure likely comes from a temporary lock."""
        winerror = getattr(error, "winerror", None)
        if winerror == 32:
            return True

        message = str(error).lower()
        return (
            "winerror 32" in message
            or "being used by another process" in message
            or "in use" in message
            or "access is denied" in message
            or "semaphore" in message
        )

    def _remove_path_with_retry(
        self,
        target: Path,
        attempts: int = 6,
        initial_wait: float = 0.5,
        backoff: float = 1.5,
    ) -> bool:
        """Remove a target with retries for transient AEDT file locks."""
        last_error = None
        wait = max(0.0, initial_wait)

        for attempt in range(1, max(1, attempts) + 1):
            try:
                self._remove_path(target)
                return True
            except Exception as e:
                last_error = e
                if not self._is_transient_cleanup_error(e) or attempt == attempts:
                    break
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass
                time.sleep(wait)
                wait *= max(1.0, backoff)

        if last_error is not None:
            print(f"Failed to remove temporary artifact: {target}, {last_error}")
        return False

    def _cleanup_temp_copy(self):
        """Delete the temporary HFSS working copy and related solver artifacts."""
        if not self.work_project_path or self.work_project_path == self.original_project_path:
            return

        work_path = Path(self.work_project_path)
        cleanup_targets = [
            work_path,
            Path(str(work_path) + "results"),
            work_path.with_suffix(".pyaedt"),
            Path(str(work_path) + ".lock"),
        ]

        for target in cleanup_targets:
            removed = self._remove_path_with_retry(target)
            if not removed and target.exists():
                print(f"Temporary artifact still present after cleanup: {target}")
            elif removed:
                print(f"Removed temporary artifact: {target}")

        for parent in list(dict.fromkeys([work_path.parent, Path(self._get_temp_dir())])):
            try:
                if parent.exists():
                    parent.rmdir()
                    print(f"Removed empty temporary dir: {parent}")
            except OSError:
                pass
            except Exception as e:
                print(f"Failed to remove temporary dir: {parent}, {e}")

    def disconnect(self):
        """断开HFSS连接"""
        skip_simulation = self.config.get('skip_simulation', False)
        close_projects = bool(self.config.get('close_projects', 0))
        close_desktop = bool(self.config.get('close_desktop', 0))
        sweep_task = self._is_sweep_task()
        closure_confirmed = False

        if self.app:
            optimization_finished = getattr(self, "_optimization_finished", False)
            if not optimization_finished:
                try:
                    self.app.modeler.fit_all()
                except Exception:
                    pass

            if not skip_simulation and not sweep_task and not optimization_finished:
                try:
                    self.app.save_project()
                    print("Project saved")
                except Exception as e:
                    print(f"Failed to save project: {e}")

            time.sleep(0.5)

            try:
                if close_desktop:
                    if hasattr(self.app, 'close_desktop'):
                        released = self.app.close_desktop()
                    else:
                        released = self.app.release_desktop(close_projects=True, close_desktop=True)
                    closure_confirmed = released is True
                    if released is False:
                        raise RuntimeError("AEDT did not confirm desktop closure")
                    print("Desktop closed")
                else:
                    # Design.release_desktop defaults close_desktop=True in PyAEDT 0.18.1.
                    released = self.app.release_desktop(close_projects=close_projects, close_desktop=False)
                    closure_confirmed = released is True and close_projects
                    if released is False:
                        raise RuntimeError("AEDT did not confirm desktop release")
                    print("Desktop released")
            except Exception as e:
                print(f"Failed to release Desktop: {e}")
                try:
                    import gc
                    del self.app
                    gc.collect()
                    print("Released resources by garbage collection")
                except Exception:
                    pass
            finally:
                self.app = None

            if closure_confirmed:
                if self.work_project_path and self.work_project_path != self.original_project_path:
                    self._clean_lock_files(self.work_project_path)

        try:
            import gc
            gc.collect()
        except Exception:
            pass
        time.sleep(1.0)
        if closure_confirmed and not self.optimization_config.get("keep_working_copy", False):
            self._cleanup_temp_copy()
        elif closure_confirmed and self.work_project_path:
            print(f"Working copy retained by keep_working_copy: {self.work_project_path}")
        elif self.work_project_path:
            print(f"Working copy retained; project closure was not confirmed: {self.work_project_path}")

        self._is_connected = False
        print("Disconnected from HFSS")

    def set_parameter(
        self,
        name: str,
        value: Any,
        unit: str | None = None,
        resolution: float | None = None,
    ) -> bool:
        """Set a single named design variable."""
        if not self.app:
            return False

        return self.apply_parameter_values({name: value}, units={name: unit},
                                           resolutions={name: resolution})

    def _apply_fixed_parameters(self) -> bool:
        """Apply non-optimized design variables fixed by the task config."""
        fixed_parameters = self.config.get('fixed_parameters') or {}
        if not fixed_parameters:
            return True
        if not isinstance(fixed_parameters, dict):
            print("fixed_parameters must be a mapping")
            return False

        try:
            for name, value in fixed_parameters.items():
                if not self.set_parameter(str(name), value):
                    return False
            return True
        except Exception as e:
            print(f"Failed to apply fixed parameters: {e}")
            return False

    def set_parameters(self, params: np.ndarray) -> bool:
        """设置仿真参数"""
        if not self.app:
            return False

        param_names = self.config.get('param_names', [])
        param_units = self.config.get('param_units', ['mm'] * len(param_names))
        param_resolutions = self.config.get('param_resolutions', [None] * len(param_names))

        try:
            values = np.asarray(params, dtype=float)
            if values.shape != (len(param_names),) or not np.all(np.isfinite(values)):
                raise ValueError("Parameter vector must contain one finite value per configured name")
            if len(param_units) != len(param_names) or len(param_resolutions) != len(param_names):
                raise ValueError("Parameter names, units and resolutions must have the same length")
            if len(set(param_names)) != len(param_names):
                raise ValueError("Parameter names must be unique")
            assignments = dict(self.config.get("fixed_parameters") or {})
            if set(assignments).intersection(param_names):
                raise ValueError("Fixed and optimized parameter names must not overlap")
            assignments.update(zip(param_names, values))
            if not self.apply_parameter_values(assignments, units=dict(zip(param_names, param_units)),
                                               resolutions=dict(zip(param_names, param_resolutions))):
                return False
            self.current_params = values.copy()
            return True
        except Exception as e:
            print(f"Failed to set parameters: {e}")
            return False

    def get_parameters(self) -> np.ndarray:
        """获取当前仿真参数"""
        return self.current_params

    def simulate(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """执行仿真并返回结果"""
        self.last_result_bundle = None
        if not self.app or not self._parameter_state_valid:
            return None, None, None

        setup_name = self.config.get('setup_name', 'Setup1')
        skip_simulation = self.config.get('skip_simulation', False)

        try:
            if skip_simulation and (not self.source_project_sha256 or
                    file_sha256(self.original_project_path) != self.source_project_sha256):
                raise RuntimeError("Existing-results source changed since connection")
            parameters = self.capture_current_parameter_state()
            self._result_context = {
                "acquisition_id": uuid.uuid4().hex, "started_at_unix": time.time(),
                "project": self.work_project_path, "design": self.config.get("design_name"),
                "setup": setup_name, "sweep": self.config.get("sweep_name"),
                "parameters": parameters, "evaluation_mode": self.evaluation_mode,
                "solved_this_call": False,
                "execution_fingerprint": self.execution_fingerprint,
                "source_sha256": self.source_project_sha256,
            }
            if skip_simulation:
                print(f"Skipping simulation and reading results directly (Setup: {setup_name})...")
            else:
                if not self._ensure_configured_sweep():
                    return None, None, None
                solve_targets = self._get_solve_targets()
                success = False
                for solve_target in solve_targets:
                    print(f"Running simulation (Setup: {solve_target})...", end=' ')
                    start_time = time.time()
                    success = self.app.analyze(solve_target)
                    sim_time = time.time() - start_time
                    if success:
                        print(f"done (elapsed: {sim_time:.1f}s)")
                        break
                    print("failed")

                if not success:
                    return None, None, None
                self._result_context["solved_this_call"] = True
                self._result_context["solve_target"] = solve_target

            if self.capture_current_parameter_state() != parameters:
                raise RuntimeError("AEDT parameters changed during result acquisition")

            results = self._get_solution_data()
            if skip_simulation and file_sha256(self.original_project_path) != self.source_project_sha256:
                raise RuntimeError("Existing-results source changed while reading")
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            return results

        except Exception as e:
            self.last_result_bundle = None
            print(f"Simulation error: {e}")
            return None, None, None

    def _get_solution_data(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """获取S参数数据。"""
        self.last_result_bundle = None
        try:
            results = self.config.get('results', {})
            s11_expr = results.get('s11', 'dB(S(1,1))')
            s12_expr = results.get('s12', results.get('s21', 'dB(S(1,2))'))

            freqs, s11_data = self._get_solution_data_direct(s11_expr)
            if freqs is None:
                freqs, s11_data = self._get_trace_data_via_report(s11_expr)
            if freqs is None:
                return None, None, None
            traces = {"s11": TraceData(s11_expr, freqs, s11_data,
                                       source=dict(self._last_trace_source))}

            s12_data = None
            if results.get('s12') or results.get('s21'):
                s12_freqs, s12_raw = self._get_solution_data_direct(s12_expr)
                if s12_raw is None:
                    s12_freqs, s12_raw = self._get_trace_data_via_report(s12_expr)
                if s12_raw is None or s12_freqs is None:
                    raise ValueError("Configured isolation trace is missing")
                s12_data = s12_raw
                traces["s12"] = TraceData(s12_expr, s12_freqs, s12_raw,
                                          source=dict(self._last_trace_source))

            if self._result_context.get("parameters") is not None:
                if self.capture_current_parameter_state() != self._result_context["parameters"]:
                    raise RuntimeError("AEDT parameters changed while traces were being read")
            self.last_result_bundle = ResultBundle(traces, dict(self._result_context))

            return freqs, s11_data, s12_data

        except Exception as e:
            print(f"Failed to get result data: {e}")
            return None, None, None

    def _extract_solution_series(self, solution) -> Tuple[np.ndarray, np.ndarray]:
        """从 PyAEDT SolutionData 中提取频率和曲线数据。"""
        if solution is None or isinstance(solution, bool):
            return None, None

        if getattr(solution, "primary_sweep", "Freq") != "Freq":
            return None, None
        if len(getattr(solution, "variations", [{}])) != 1:
            return None, None
        freqs = np.asarray(getattr(solution, 'primary_sweep_values', []))
        if freqs.size == 0:
            return None, None

        values = None
        for accessor in ('data_real', 'data_magnitude', 'data'):
            candidate = getattr(solution, accessor, None)
            if candidate is None:
                continue
            try:
                raw = candidate() if callable(candidate) else candidate
                values = np.array(raw)
                if values.size > 0:
                    break
            except Exception:
                continue

        if values is None or values.size == 0:
            return None, None

        try:
            unit = (getattr(solution, "units_sweeps", {}) or {}).get("Freq") or self.config.get("frequency_unit")
            freqs = frequency_to_ghz(freqs, unit)
            trace = TraceData("solution", freqs, values)
            self._last_trace_source["frequency_unit_original"] = unit
            return trace.frequencies_ghz, trace.values
        except (ValueError, TypeError) as exc:
            print(f"Rejected solution series: {exc}")
            return None, None

    @staticmethod
    def _to_scalar(value: Any):
        """Convert a NumPy scalar-like object to a plain Python scalar."""
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass
        return value

    @staticmethod
    def _format_ghz(value_ghz: float) -> str:
        """Format a floating-point GHz value into AEDT's discrete sweep string."""
        text = f"{value_ghz:.6f}".rstrip("0").rstrip(".")
        return f"{text}GHz"

    def build_frequency_list(
        self,
        freq: str | None = None,
        freq_start: float | None = None,
        freq_end: float | None = None,
        freq_step: float | None = None,
    ) -> list[str]:
        """Build a discrete frequency list for far-field queries."""
        if freq:
            return [freq]

        if freq_start is None or freq_end is None or freq_step is None:
            raise ValueError("Either freq or the full freq_start/freq_end/freq_step triplet is required.")
        if freq_step <= 0:
            raise ValueError("freq_step must be positive.")

        values: list[str] = []
        current = freq_start
        while current <= freq_end + 1e-9:
            values.append(self._format_ghz(current))
            current += freq_step
        return values

    def _normalize_far_field_rows(
        self,
        coords: np.ndarray,
        values: np.ndarray,
    ) -> list[tuple[float, float, float]]:
        """Convert SolutionData far-field arrays into (theta, phi, gain_db) rows."""
        coord_array = np.asarray(coords)
        value_array = np.asarray(values, dtype=float)

        if coord_array.size == 0 or value_array.size == 0:
            raise RuntimeError("SolutionData returned an empty far-field dataset.")
        if coord_array.ndim == 1:
            raise RuntimeError(
                "SolutionData returned a 1D coordinate axis, not a Theta/Phi grid."
            )

        rows: list[tuple[float, float, float]] = []
        for coord, gain_db in zip(coord_array, value_array):
            if len(coord) < 2:
                continue
            theta = float(self._to_scalar(coord[0]))
            phi = float(self._to_scalar(coord[1]))
            rows.append((theta, phi, float(self._to_scalar(gain_db))))

        if not rows:
            raise RuntimeError("No numeric Theta/Phi/gain samples were parsed from SolutionData.")
        return rows

    def _extract_far_field_rows_from_solution_data(
        self,
        solution_data,
        expression: str,
        formula: str,
    ) -> list[tuple[float, float, float]]:
        """Read a full 3D far-field grid from SolutionData."""
        if hasattr(solution_data, "get_expression_data"):
            coords, values = solution_data.get_expression_data(
                expression,
                formula=formula,
                sweeps=["Theta", "Phi"],
            )
            return self._normalize_far_field_rows(coords, values)

        try:
            theta_values = [float(self._to_scalar(value)) for value in solution_data.variation_values("Theta")]
            phi_values = [float(self._to_scalar(value)) for value in solution_data.variation_values("Phi")]
        except Exception as exc:
            raise RuntimeError(f"SolutionData does not expose Theta/Phi variation values: {exc}") from exc

        try:
            if formula == "db10" and hasattr(solution_data, "data_db10"):
                values = solution_data.data_db10(expression)
            elif hasattr(solution_data, "data_real"):
                values = solution_data.data_real(expression)
            elif hasattr(solution_data, "data_magnitude"):
                values = solution_data.data_magnitude(expression)
            else:
                raise AttributeError("no supported data accessor")
        except Exception as exc:
            raise RuntimeError(f"SolutionData does not expose far-field values for {expression}: {exc}") from exc

        value_array = np.asarray(values, dtype=float).ravel()
        if value_array.size == 0:
            raise RuntimeError("SolutionData returned an empty far-field value array.")

        rows: list[tuple[float, float, float]] = []
        expected_grid = len(theta_values) * len(phi_values)
        if expected_grid == value_array.size:
            index = 0
            for theta in theta_values:
                for phi in phi_values:
                    rows.append((float(theta), float(phi), float(value_array[index])))
                    index += 1
        elif len(theta_values) == 1 and value_array.size == len(phi_values):
            rows = [(float(theta_values[0]), float(phi), float(value)) for phi, value in zip(phi_values, value_array)]
        elif len(phi_values) == 1 and value_array.size == len(theta_values):
            rows = [(float(theta), float(phi_values[0]), float(value)) for theta, value in zip(theta_values, value_array)]
        elif value_array.size == 1 and theta_values and phi_values:
            rows = [(float(theta_values[0]), float(phi_values[0]), float(value_array[0]))]
        else:
            raise RuntimeError(
                "SolutionData far-field dimensions are unsupported: "
                f"theta={len(theta_values)}, phi={len(phi_values)}, values={value_array.size}."
            )

        if not rows:
            raise RuntimeError("No numeric Theta/Phi/gain samples were parsed from SolutionData.")
        return rows

    def _compute_peak_loss_metrics(
        self,
        rows: list[tuple[float, float, float]],
        boresight_theta: float,
        boresight_phi: float,
        plane_phi_deg: float | None = None,
        plane_tolerance_deg: float = 1e-6,
        plane_include_opposite: bool = True,
    ) -> dict:
        """Compute peak, boresight, peak-loss, and pointing-error metrics.

        When ``plane_phi_deg`` is set, the default is to evaluate the full
        principal-plane cut by including both phi and its opposite half-plane.
        For E-plane phi=0, that means phi=0 and phi=180/-180.
        """
        all_rows = list(rows)
        if not all_rows:
            raise RuntimeError("Far-field rows are empty.")
        if not np.all(np.isfinite(np.asarray(all_rows, dtype=float))):
            raise RuntimeError("Far-field samples contain NaN/Inf")

        def _angular_delta_deg(angle_a: float, angle_b: float) -> float:
            return abs((float(angle_a) - float(angle_b) + 180.0) % 360.0 - 180.0)

        global_peak_theta, global_peak_phi, global_peak_gain_db = max(all_rows, key=lambda item: item[2])

        if plane_phi_deg is not None:
            plane_targets = [float(plane_phi_deg)]
            if plane_include_opposite:
                plane_targets.append(float(plane_phi_deg) + 180.0)
            filtered_rows = [
                item for item in rows
                if any(_angular_delta_deg(item[1], target) <= float(plane_tolerance_deg) for target in plane_targets)
            ]
            if filtered_rows:
                rows = filtered_rows

        peak_theta, peak_phi, peak_gain_db = max(rows, key=lambda item: item[2])
        bore_theta, bore_phi, bore_gain_db = min(
            rows,
            key=lambda item: abs(item[0] - boresight_theta) + abs(item[1] - boresight_phi),
        )

        def _direction_vector(theta_deg: float, phi_deg: float) -> np.ndarray:
            theta = math.radians(float(theta_deg))
            phi = math.radians(float(phi_deg))
            return np.asarray(
                [
                    math.sin(theta) * math.cos(phi),
                    math.sin(theta) * math.sin(phi),
                    math.cos(theta),
                ],
                dtype=float,
            )

        def _angular_distance_deg(theta_a: float, phi_a: float, theta_b: float, phi_b: float) -> float:
            vec_a = _direction_vector(theta_a, phi_a)
            vec_b = _direction_vector(theta_b, phi_b)
            cosang = float(np.clip(np.dot(vec_a, vec_b), -1.0, 1.0))
            return math.degrees(math.acos(cosang))

        pointing_error_deg = _angular_distance_deg(peak_theta, peak_phi, boresight_theta, boresight_phi)

        return {
            "sample_count": len(rows),
            "boresight_request": {
                "theta_deg": boresight_theta,
                "phi_deg": boresight_phi,
                "plane_phi_deg": plane_phi_deg,
                "plane_tolerance_deg": plane_tolerance_deg,
                "plane_include_opposite": plane_include_opposite,
            },
            "boresight_grid_point": {
                "theta_deg": bore_theta,
                "phi_deg": bore_phi,
                "gain_db": bore_gain_db,
            },
            "peak_direction": {
                "theta_deg": peak_theta,
                "phi_deg": peak_phi,
                "gain_db": peak_gain_db,
            },
            "global_peak_direction": {
                "theta_deg": global_peak_theta,
                "phi_deg": global_peak_phi,
                "gain_db": global_peak_gain_db,
            },
            "peak_loss_db": peak_gain_db - bore_gain_db,
            "pointing_error_deg": pointing_error_deg,
        }

    @staticmethod
    def _normalize_angle_delta(angle_a: float, angle_b: float) -> float:
        return abs((float(angle_a) - float(angle_b) + 180.0) % 360.0 - 180.0)

    def _extract_plane_cut(
        self,
        rows: list[tuple[float, float, float]],
        plane_phi_deg: float,
        plane_tolerance_deg: float = 1e-6,
        plane_include_opposite: bool = True,
    ) -> dict[str, Any] | None:
        """Convert one principal-plane cut into a signed angle / gain series."""
        cut_samples: list[tuple[float, float]] = []
        primary_phi = float(plane_phi_deg)
        opposite_phi = float(plane_phi_deg) + 180.0
        tolerance = float(plane_tolerance_deg)

        for theta_deg, phi_deg, gain_db in rows:
            theta_value = float(theta_deg)
            phi_value = float(phi_deg)
            if self._normalize_angle_delta(phi_value, primary_phi) <= tolerance:
                cut_angle = theta_value
            elif plane_include_opposite and self._normalize_angle_delta(phi_value, opposite_phi) <= tolerance:
                cut_angle = -theta_value
            else:
                continue

            if abs(cut_angle) < 1e-9:
                cut_angle = 0.0
            cut_samples.append((cut_angle, float(gain_db)))

        if not cut_samples:
            return None

        grouped: dict[float, list[float]] = {}
        for cut_angle, gain_db in cut_samples:
            rounded_angle = round(float(cut_angle), 6)
            grouped.setdefault(rounded_angle, []).append(float(gain_db))

        cut_angles = sorted(grouped.keys())
        gains = [max(grouped[angle]) for angle in cut_angles]
        return {
            "plane_phi_deg": primary_phi,
            "plane_include_opposite": bool(plane_include_opposite),
            "cut_angle_deg": cut_angles,
            "gain_db": gains,
        }

    def _far_field_variables(self):
        manager = getattr(self.app, "variable_manager", None)
        return ({name: self._read_parameter_expression(name) for name in manager.independent_variables}
                if manager is not None else {})

    def _verify_far_field_context(self, solution, requested, freq):
        returned = self._read_solution_variation(solution) if requested else {}
        for name, expression in requested.items():
            if (name not in returned or not self._assignment_matches(name, returned[name])
                    or self._read_parameter_expression(name) != expression):
                raise RuntimeError("Far-field variation mismatch: " + name)
        actual_freqs = solution.variation_values("Freq")
        unit = (getattr(solution, "units_sweeps", {}) or {}).get("Freq")
        actual = frequency_to_ghz(actual_freqs, unit)
        number, expected_unit = self._split_numeric_unit(freq)
        expected = frequency_to_ghz([number], expected_unit)
        if len(actual) != 1 or not np.allclose(actual, expected, rtol=1e-10, atol=1e-12):
            raise RuntimeError("Far-field frequency mismatch")
        return {"requested_variation": requested.copy(), "returned_variation": returned,
                "variation_verified": bool(requested), "frequency_ghz": float(actual[0]),
                "frequency_unit_original": unit}

    @staticmethod
    def _full_sphere_rows(rows):
        theta = sorted({r[0] for r in rows})
        phi = sorted({r[1] % 360 for r in rows})
        if len(theta) < 3 or len(phi) < 8 or abs(theta[0]) > 1e-6 or abs(theta[-1]-180) > 1e-6:
            return False
        gaps = [b-a for a,b in zip(phi,phi[1:])] + [phi[0]+360-phi[-1]]
        return max(gaps) <= 90+1e-6 and len({(r[0],r[1] % 360) for r in rows}) == len(theta)*len(phi)

    def _attempt_far_field_direct_query(
        self,
        setup_sweep_name: str,
        sphere_name: str,
        freq: str,
        expression: str,
    ) -> tuple[list[tuple[float, float, float]], dict]:
        """Try the low-level direct SolutionData path for far-field data."""
        attempts = [
            {
                "label": "direct_raw_expr_db10",
                "query_expression": expression,
                "result_expression": expression,
                "formula": "db10",
            },
            {
                "label": "direct_wrapped_expr_real",
                "query_expression": f"dB({expression})",
                "result_expression": f"dB({expression})",
                "formula": "real",
            },
        ]

        errors: list[str] = []
        requested = self._far_field_variables()
        for attempt in attempts:
            solution_data = self.app.post.get_solution_data_per_variation(
                "Far Fields",
                setup_sweep_name=setup_sweep_name,
                context=["Context:=", sphere_name],
                sweeps={**{n:[v] for n,v in requested.items()}, "Theta": "All", "Phi": "All", "Freq": freq},
                expressions=attempt["query_expression"],
            )
            if not solution_data:
                errors.append(f"{attempt['label']}: no solution data")
                continue

            try:
                rows = self._extract_far_field_rows_from_solution_data(
                    solution_data,
                    attempt["result_expression"],
                    attempt["formula"],
                )
                provenance = self._verify_far_field_context(solution_data, requested, freq)
                if not self._full_sphere_rows(rows):
                    raise RuntimeError("Direct far-field data does not cover a full sampled sphere")
                return rows, {
                    **provenance,
                    "method": attempt["label"],
                    "setup": setup_sweep_name,
                    "context": ["Context:=", sphere_name],
                    "expression": attempt["query_expression"],
                    "formula": attempt["formula"],
                    "angular_scope": "sampled_sphere",
                }
            except Exception as exc:
                errors.append(f"{attempt['label']}: {exc}")

        raise RuntimeError(" ; ".join(errors))

    def _attempt_far_field_cut_queries(
        self,
        setup_sweep_name: str,
        sphere_name: str,
        freq: str,
        expression: str,
    ) -> tuple[list[tuple[float, float, float]], dict]:
        """Query four fixed-phi cuts to avoid the AEDT 2023.2 2D-grid bug."""
        attempts = [
            {
                "label": "fixed_phi_raw_expr_db10",
                "query_expression": expression,
                "result_expression": expression,
                "formula": "db10",
            },
            {
                "label": "fixed_phi_wrapped_expr_real",
                "query_expression": f"dB({expression})",
                "result_expression": f"dB({expression})",
                "formula": "real",
            },
        ]
        errors: list[str] = []
        requested_phis = (0.0, 180.0, 90.0, 270.0)
        requested = self._far_field_variables()
        for attempt in attempts:
            combined_rows: list[tuple[float, float, float]] = []
            attempt_errors: list[str] = []
            for phi_deg in requested_phis:
                solution_data = self.app.post.get_solution_data_per_variation(
                    "Far Fields",
                    setup_sweep_name=setup_sweep_name,
                    context=["Context:=", sphere_name],
                    sweeps={**{n:[v] for n,v in requested.items()}, "Theta": "All", "Phi": f"{phi_deg:g}deg", "Freq": freq},
                    expressions=attempt["query_expression"],
                )
                if not solution_data:
                    attempt_errors.append(f"phi={phi_deg:g}: no solution data")
                    continue
                try:
                    provenance = self._verify_far_field_context(solution_data, requested, freq)
                    cut_rows = self._extract_far_field_rows_from_solution_data(
                        solution_data,
                        attempt["result_expression"],
                        attempt["formula"],
                    )
                    cut_rows = [(theta, phi_deg, gain_db) for theta, _phi, gain_db in cut_rows]
                    if len(cut_rows) < 10:
                        raise RuntimeError(f"only {len(cut_rows)} theta samples")
                    combined_rows.extend(cut_rows)
                except Exception as exc:
                    attempt_errors.append(f"phi={phi_deg:g}: {exc}")
            if not attempt_errors and len(combined_rows) >= 40:
                return combined_rows, {
                    **provenance,
                    "method": attempt["label"],
                    "setup": setup_sweep_name,
                    "context": ["Context:=", sphere_name],
                    "expression": attempt["query_expression"],
                    "formula": attempt["formula"],
                    "fixed_phi_deg": list(requested_phis),
                    "angular_scope": "principal_cuts",
                }
            errors.append(f"{attempt['label']}: " + " ; ".join(attempt_errors))
        raise RuntimeError(" ; ".join(errors))

    def _attempt_far_field_report_query(
        self,
        setup_sweep_name: str,
        sphere_name: str,
        freq: str,
        expression: str,
        phi_samples_deg=None,
    ) -> tuple[list[tuple[float, float, float]], dict]:
        """Export four fixed-Phi rectangular reports through AEDT ReportSetup.

        AEDT 2023.2 can collapse Theta when far-field SolutionData is queried
        directly.  The low-level report CSV path preserves all Theta samples.
        """
        requested_phis = tuple(phi_samples_deg) if phi_samples_deg is not None else (0.0, 180.0, 90.0, 270.0)
        if (any(not math.isfinite(float(p)) or not 0 <= float(p) < 360 for p in requested_phis)
                or len(set(requested_phis)) != len(requested_phis)
                or (phi_samples_deg is not None and len(requested_phis) < 8)):
            raise ValueError("Sphere sampling requires at least eight unique finite Phi angles in [0,360)")
        query_expression = expression if str(expression).startswith("dB(") else f"dB({expression})"
        report_prefix = f"FFCut_{int(time.time() * 1000)}"
        export_dir = Path(self._get_temp_dir()) / "far_field_report_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        combined_rows: list[tuple[float, float, float]] = []
        errors: list[str] = []

        variation_names: list[str] = []
        requested = self._far_field_variables()
        try:
            template = self.app.post.reports_by_category.far_field(
                expressions=query_expression,
                setup=setup_sweep_name,
                sphere_name=sphere_name,
            )
            variation_names = [
                str(name)
                for name in template.variations
                if str(name) not in {"Theta", "Phi", "Freq"}
            ]
        except Exception:
            variation_names = []

        for index, phi_deg in enumerate(requested_phis):
            report_name = f"{report_prefix}_{index}"
            csv_path = export_dir / f"{report_name}.csv"
            families: list[Any] = [
                "Theta:=", ["All"],
                "Phi:=", [f"{phi_deg:g}deg"],
                "Freq:=", [freq],
            ]
            for variable_name in variation_names:
                families.extend([f"{variable_name}:=", [requested.get(variable_name, "Nominal")]])
            try:
                self.app.oreportsetup.CreateReport(
                    report_name,
                    "Far Fields",
                    "Rectangular Plot",
                    setup_sweep_name,
                    ["Context:=", sphere_name],
                    families,
                    ["X Component:=", "Theta", "Y Component:=", [query_expression]],
                )
                self.app.oreportsetup.ExportToFile(report_name, str(csv_path), False)
                with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames:
                        raise RuntimeError("exported CSV has no header")
                    theta_key = next((key for key in reader.fieldnames if "theta" in key.lower()), None)
                    phi_key = next((key for key in reader.fieldnames if "phi" in key.lower()), None)
                    freq_key = next((key for key in reader.fieldnames if "freq" in key.lower()), None)
                    if not freq_key:
                        raise RuntimeError("Far-field CSV has no frequency column")
                    freq_unit = re.search(r"\[([^\]]+)\]", freq_key)
                    if freq_unit is None:
                        raise RuntimeError("Far-field CSV frequency unit is missing")
                    expected_number, expected_unit = self._split_numeric_unit(freq)
                    expected_ghz = frequency_to_ghz([expected_number], expected_unit)[0]
                    value_key = next(
                        (key for key in reversed(reader.fieldnames) if key not in {theta_key, phi_key} and "freq" not in key.lower()),
                        None,
                    )
                    if not theta_key or not value_key:
                        raise RuntimeError(f"unsupported CSV columns: {reader.fieldnames}")
                    cut_rows = []
                    for row in reader:
                        actual_ghz = frequency_to_ghz([float(row[freq_key])], freq_unit.group(1))[0]
                        if not math.isclose(actual_ghz, expected_ghz, rel_tol=1e-10, abs_tol=1e-12):
                            raise RuntimeError("Far-field CSV frequency mismatch")
                        theta_value = float(row[theta_key])
                        phi_value = float(row[phi_key]) if phi_key else float(phi_deg)
                        gain_db = float(row[value_key])
                        cut_rows.append((theta_value, phi_value, gain_db))
                if len(cut_rows) < 10:
                    raise RuntimeError(f"only {len(cut_rows)} theta samples")
                combined_rows.extend(cut_rows)
            except Exception as exc:
                errors.append(f"phi={phi_deg:g}: {exc}")
            finally:
                try:
                    self.app.oreportsetup.DeleteReports([report_name])
                except Exception:
                    pass
                try:
                    csv_path.unlink()
                except Exception:
                    pass

        if errors or len(combined_rows) < 40:
            raise RuntimeError(" ; ".join(errors) or f"only {len(combined_rows)} samples")
        if any(self._read_parameter_expression(n) != v for n,v in requested.items()):
            raise RuntimeError("Live parameters changed during far-field report acquisition")
        full_sphere = phi_samples_deg is not None and self._full_sphere_rows(combined_rows)
        if phi_samples_deg is not None and not full_sphere:
            raise RuntimeError("Requested sphere sampling has incomplete Theta/Phi coverage")
        return combined_rows, {
            "requested_variation": requested, "variation_verified": bool(requested),
            "variation_read_method": "explicit_report_families_and_live_state",
            "method": "report_csv_fixed_phi",
            "setup": setup_sweep_name,
            "context": ["Context:=", sphere_name],
            "expression": query_expression,
            "fixed_phi_deg": list(requested_phis),
            "angular_scope": "sampled_sphere" if full_sphere else "principal_cuts",
        }
    def get_far_field_peak_loss(
        self,
        freq: str,
        boresight_theta: float = 0.0,
        boresight_phi: float = 0.0,
        sphere_name: str = "3D",
        expression: str = "RealizedGainTotal",
        setup_sweep_name: str | None = None,
        plane_phi_deg: float | None = None,
        plane_tolerance_deg: float = 1e-6,
        plane_include_opposite: bool = True,
        phi_samples_deg=None,
    ) -> dict:
        """Extract peak-loss and pointing-error metrics for one frequency point.

        Returns a dictionary containing the acquisition path, peak direction,
        boresight gain, and `peak_loss_db`.
        """
        if not self.app:
            raise RuntimeError("HFSS is not connected.")

        setup_candidates = [setup_sweep_name] if setup_sweep_name else self._iter_candidate_setup_sweeps()
        setup_candidates = [item for item in setup_candidates if item]
        if not setup_candidates:
            raise RuntimeError("No valid setup/sweep candidates available for far-field query.")

        errors: list[str] = []
        for candidate_setup in setup_candidates:
            for attempt in (
                self._attempt_far_field_direct_query,
                self._attempt_far_field_cut_queries,
                self._attempt_far_field_report_query,
            ):
                if phi_samples_deg is not None and attempt == self._attempt_far_field_cut_queries:
                    continue
                try:
                    rows, acquisition = attempt(
                        candidate_setup,
                        sphere_name,
                        freq,
                        expression,
                        **({"phi_samples_deg": phi_samples_deg} if attempt == self._attempt_far_field_report_query else {}),
                    )
                    result = {
                        "frequency": freq,
                        "acquisition": acquisition,
                    }
                    result.update(
                        self._compute_peak_loss_metrics(
                            rows,
                            boresight_theta=boresight_theta,
                            boresight_phi=boresight_phi,
                            plane_phi_deg=plane_phi_deg,
                            plane_tolerance_deg=plane_tolerance_deg,
                            plane_include_opposite=plane_include_opposite,
                        )
                    )
                    scope = acquisition.get("angular_scope", "unverified")
                    result["peak_scope"] = "principal_cut" if plane_phi_deg is not None else scope
                    if scope != "sampled_sphere":
                        result["sampled_peak_direction"] = result.pop("global_peak_direction")
                    if plane_phi_deg is not None:
                        plane_cuts: dict[str, Any] = {}
                        primary_cut = self._extract_plane_cut(
                            rows,
                            plane_phi_deg=float(plane_phi_deg),
                            plane_tolerance_deg=plane_tolerance_deg,
                            plane_include_opposite=plane_include_opposite,
                        )
                        if primary_cut is not None:
                            plane_cuts["primary_plane"] = primary_cut
                        orthogonal_cut = self._extract_plane_cut(
                            rows,
                            plane_phi_deg=float(plane_phi_deg) + 90.0,
                            plane_tolerance_deg=plane_tolerance_deg,
                            plane_include_opposite=plane_include_opposite,
                        )
                        if orthogonal_cut is not None:
                            plane_cuts["orthogonal_plane"] = orthogonal_cut
                        required_planes = ("primary_plane", "orthogonal_plane")
                        incomplete = [
                            plane_id
                            for plane_id in required_planes
                            if plane_id not in plane_cuts
                            or len(plane_cuts[plane_id].get("cut_angle_deg", [])) < 10
                        ]
                        if incomplete:
                            raise RuntimeError(
                                "Incomplete principal-plane cuts: " + ", ".join(incomplete)
                            )
                        result["plane_cuts"] = plane_cuts
                    return result
                except Exception as exc:
                    errors.append(f"{candidate_setup}/{attempt.__name__}: {exc}")

        raise RuntimeError("All far-field peak-loss attempts failed. " + " | ".join(errors))

    def get_far_field_peak_loss_band(
        self,
        freqs: Iterable[str] | None = None,
        *,
        freq_start: float | None = None,
        freq_end: float | None = None,
        freq_step: float | None = None,
        boresight_theta: float = 0.0,
        boresight_phi: float = 0.0,
        sphere_name: str = "3D",
        expression: str = "RealizedGainTotal",
        setup_sweep_name: str | None = None,
        plane_phi_deg: float | None = None,
        plane_tolerance_deg: float = 1e-6,
        plane_include_opposite: bool = True,
        phi_samples_deg=None,
    ) -> dict:
        """Extract peak-loss and pointing-error metrics across a discrete frequency band."""
        freq_list = list(freqs) if freqs is not None else self.build_frequency_list(
            freq=None,
            freq_start=freq_start,
            freq_end=freq_end,
            freq_step=freq_step,
        )

        band_results = [
            self.get_far_field_peak_loss(
                freq=freq,
                boresight_theta=boresight_theta,
                boresight_phi=boresight_phi,
                sphere_name=sphere_name,
                expression=expression,
                setup_sweep_name=setup_sweep_name,
                plane_phi_deg=plane_phi_deg,
                plane_tolerance_deg=plane_tolerance_deg,
                plane_include_opposite=plane_include_opposite,
                phi_samples_deg=phi_samples_deg,
            )
            for freq in freq_list
        ]

        worst_peak_loss = max(band_results, key=lambda item: item["peak_loss_db"])
        best_peak_loss = min(band_results, key=lambda item: item["peak_loss_db"])
        avg_peak_loss = float(np.mean([item["peak_loss_db"] for item in band_results]))
        worst_pointing_error = max(band_results, key=lambda item: item.get("pointing_error_deg", 0.0))
        best_pointing_error = min(band_results, key=lambda item: item.get("pointing_error_deg", 0.0))
        avg_pointing_error = float(np.mean([item.get("pointing_error_deg", 0.0) for item in band_results]))

        return {
            "frequencies": freq_list,
            "summary": {
                "point_count": len(band_results),
                "worst_peak_loss_db": worst_peak_loss["peak_loss_db"],
                "worst_peak_loss_frequency": worst_peak_loss["frequency"],
                "best_peak_loss_db": best_peak_loss["peak_loss_db"],
                "best_peak_loss_frequency": best_peak_loss["frequency"],
                "average_peak_loss_db": avg_peak_loss,
                "worst_pointing_error_deg": worst_pointing_error.get("pointing_error_deg", 0.0),
                "worst_pointing_error_frequency": worst_pointing_error["frequency"],
                "best_pointing_error_deg": best_pointing_error.get("pointing_error_deg", 0.0),
                "best_pointing_error_frequency": best_pointing_error["frequency"],
                "average_pointing_error_deg": avg_pointing_error,
            },
            "per_frequency": band_results,
        }

    def capture_geometry_snapshot(self, object_names: list[str]) -> dict:
        """Read selected live CAD extents without bulk-cache parsing or CAD edits."""
        if not self.app:
            raise RuntimeError("Geometry snapshot requires a connected model")
        if (not isinstance(object_names, list) or not object_names or
                any(not isinstance(name, str) or not name.strip() for name in object_names) or
                len(set(object_names)) != len(object_names)):
            raise ValueError("Geometry snapshot requires unique nonempty object names")
        modeler = self.app.modeler
        available = set(modeler.object_names)
        missing = set(object_names) - available
        if missing:
            raise ValueError(f"Geometry snapshot objects not found: {sorted(missing)}")
        unit = modeler.model_units
        if not isinstance(unit, str) or not unit:
            raise RuntimeError("Geometry snapshot requires explicit model units")
        objects = {}
        for name in object_names:
            obj = modeler.objects[name]
            if obj.object_type == "Unclassified":
                raise RuntimeError(f"Cannot verify unclassified geometry {name!r}")
            bbox = np.asarray(obj.bounding_box, dtype=float)
            if (bbox.shape != (6,) or not np.all(np.isfinite(bbox)) or
                    np.any(bbox[3:] < bbox[:3])):
                raise RuntimeError(f"Invalid live bounding box for {name!r}")
            objects[name] = {"bounding_box": bbox.tolist(),
                             "dimensions": (bbox[3:] - bbox[:3]).tolist()}
        return {"model_unit": unit, "objects": objects,
                "parameters": self.capture_current_parameter_state()}

    def _read_solution_variation(self, solution) -> dict[str, str]:
        """Read explicit native-unit values, avoiding ambiguous PyAEDT Quantity units."""
        wrapped = {name: str(value) for name, value in
                   (getattr(solution, "active_variation", {}) or {}).items()}
        self._last_trace_source["pyaedt_returned_variation"] = wrapped
        native = getattr(solution, "nominal_variation", None)
        if native is None or not hasattr(native, "GetDesignVariableValue"):
            self._last_trace_source["variation_read_method"] = "active_variation"
            return wrapped
        returned = {}
        for name in native.GetDesignVariableNames():
            # AEDT's default may be SI while GetDesignVariableUnits reports native units.
            value = native.GetDesignVariableValue(name, False)
            unit = native.GetDesignVariableUnits(name)
            if isinstance(value, (bool, str)) or not math.isfinite(float(value)):
                raise RuntimeError(f"Invalid native result variation value for {name!r}")
            if not isinstance(unit, str):
                raise RuntimeError(f"Missing native result variation unit for {name!r}")
            returned[name] = f"{float(value):.17g}{unit}"
        self._last_trace_source["variation_read_method"] = "native_value_explicit_non_si"
        return returned

    def _get_solution_data_direct(self, trace_expr: str) -> Tuple[np.ndarray, np.ndarray]:
        """Read only the configured setup/sweep and the current nominal variation."""
        if not self.app:
            return None, None
        if not self.config.get("setup_name"):
            raise ValueError("An explicit setup_name is required for result acquisition")
        manager = getattr(self.app, "variable_manager", None)
        variations = ({name: [self._read_parameter_expression(name)]
                       for name in manager.independent_variables} if manager is not None else None)
        for setup_sweep_name in self._iter_candidate_setup_sweeps():
            try:
                self._last_trace_source = {
                    "setup_sweep": setup_sweep_name, "expression": trace_expr,
                    "requested_variation": dict(variations or {}),
                    "method": "post_solution_data",
                }
                query = dict(expressions=trace_expr, setup_sweep_name=setup_sweep_name,
                             report_category="Standard", primary_sweep_variable="Freq")
                if variations is not None:
                    # PyAEDT augments this dict with intrinsic sweeps (e.g. Freq=All).
                    # Keep the requested design-variable contract independent of that mutation.
                    query["variations"] = {name: list(values) for name, values in variations.items()}
                solution = self.app.post.get_solution_data(**query)
                freqs, values = self._extract_solution_series(solution)
                if freqs is not None and self._solution_frequency_coverage_ok(freqs, setup_sweep_name):
                    returned = self._read_solution_variation(solution)
                    if variations is not None:
                        for name in variations:
                            if name not in returned or not self._assignment_matches(name, str(returned[name])):
                                raise RuntimeError(
                                    f"Result variation mismatch for {name!r}: "
                                    f"requested={variations[name]!r}, returned={returned.get(name)!r}, "
                                    f"model={self._read_parameter_expression(name)!r}")
                    self._last_trace_source["returned_variation"] = returned
                    self._last_trace_source["variation_verified"] = variations is not None
                    return freqs, values
            except Exception as exc:
                print(f"Result acquisition failed ({setup_sweep_name}): {exc}")
        return None, None

    def _get_trace_data_via_report(self, trace_expr: str) -> Tuple[np.ndarray, np.ndarray]:
        """Compatibility alias; never fall back to a different solution context."""
        return self._get_solution_data_direct(trace_expr)

    def get_trace_data(self, trace_expr: str) -> Tuple[np.ndarray, np.ndarray]:
        """Load an arbitrary scalar report trace from the solved HFSS result."""
        freqs, values = self._get_solution_data_direct(trace_expr)
        if freqs is None:
            freqs, values = self._get_trace_data_via_report(trace_expr)
        return freqs, values
    def save_results_to_csv(self, output_dir: str = None, sim_id: int = 0) -> bool:
        """保存仿真结果到CSV文件"""
        if not self.app:
            return False

        try:
            if output_dir is None:
                output_dir = self._get_results_dir()

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"sim_{sim_id:04d}.csv")

            results = self.config.get('results', {})
            s11_expr = results.get('s11', 'dB(S(1,1))')

            freqs, s11_data = self._get_trace_data_via_report(s11_expr)
            if freqs is None or len(freqs) == 0:
                return False

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Freq', 'S11'])
                for f_val, s_val in zip(freqs, s11_data):
                    writer.writerow([f_val, s_val])

            print(f"Result saved to: {output_path}")
            return True

        except Exception as e:
            print(f"Failed to save CSV: {e}")
            return False

    def save_best_result(self, output_dir: str = None, sim_id: int = None, output_path: str = None) -> bool:
        """Save the best project snapshot into the task results directory."""
        if not self.work_project_path:
            return False

        if output_path is None:
            original_name = Path(self.original_project_path).stem
            if output_dir is None:
                output_dir = self._get_results_dir()
            os.makedirs(output_dir, exist_ok=True)

            sim_tag = str(sim_id) if sim_id is not None else "best"
            output_path = os.path.join(output_dir, f"{original_name}_{sim_tag}_best.aedt")

        try:
            if not self.app or self.best_params is None or self.last_result_bundle is None:
                raise RuntimeError("Best export requires a verified solved result bundle")
            if self.current_params is None or not np.array_equal(self.current_params, self.best_params):
                raise RuntimeError("Current parameters do not match the verified export point")
            provenance = self.last_result_bundle.provenance
            if not provenance.get("solved_this_call") or not self._parameter_state_valid:
                raise RuntimeError("Best export requires results solved for the current model")
            if self.capture_current_parameter_state() != provenance.get("parameters"):
                raise RuntimeError("Model changed after export verification")
            destination = Path(output_path).resolve()
            if destination == Path(self.original_project_path).resolve() or destination.exists():
                raise ValueError("Best export must use a new path separate from the source")
            work_path = Path(self.work_project_path).resolve()
            if work_path == Path(self.original_project_path).resolve() or destination == work_path:
                raise ValueError("Best export requires a separate protected work project")
            # SaveAs changes the active project. A later baseline restore followed by
            # disconnect/save would overwrite that exported file with baseline values.
            # Persist the verified work model, then copy only the AEDT model snapshot.
            # Solver caches stay with the work project; the snapshot needs a fresh solve.
            if self.app.save_project() is not True:
                raise RuntimeError("AEDT save_project reported failure")
            if self.capture_current_parameter_state() != provenance.get("parameters"):
                raise RuntimeError("Model changed while saving the verified work project")
            if not work_path.is_file() or work_path.stat().st_size == 0:
                raise RuntimeError("AEDT did not persist the verified work project")
            saved_hash = file_sha256(work_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with destination.open("xb") as target:
                    created = True
                    with work_path.open("rb") as source:
                        shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                if file_sha256(destination) != saved_hash or file_sha256(work_path) != saved_hash:
                    raise RuntimeError("Saved model changed during export or snapshot is incomplete")
            except Exception:
                if created:
                    destination.unlink(missing_ok=True)
                raise
            if not destination.is_file() or destination.stat().st_size == 0:
                raise RuntimeError("AEDT did not create the saved project file")
            print(f"Best result saved to: {output_path}")
            return True
        except Exception as e:
            print(f"Failed to save best result: {e}")
            return False

    def save_checkpoint(self, checkpoint_path: str, iteration: int, best_params: np.ndarray, best_cost: float):
        """保存检查点"""
        import json

        try:
            checkpoint_data = {
                'iteration': iteration,
                'best_params': best_params.tolist() if best_params is not None else [],
                'best_cost': best_cost,
                'timestamp': time.time()
            }

            if checkpoint_path is None:
                checkpoint_path = os.path.join(self._get_results_dir(), f"checkpoint_{iteration}.json")

            os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)

            print(f"Checkpoint saved: {checkpoint_path}")
            return True
        except Exception as e:
            print(f"Failed to save checkpoint: {e}")
            return False

    def update_best(self, params: np.ndarray, cost: float) -> bool:
        """更新最优解"""
        if cost < self.best_fitness:
            self.best_fitness = cost
            self.best_params = params.copy()
            return True
        return False

    @property
    def project_path(self) -> str:
        """获取当前项目路径"""
        return self.work_project_path or self.original_project_path
