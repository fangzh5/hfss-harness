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
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, Iterable, Any
try:
    from .base import SimulatorAdapter
    from ..task_config import normalize_task_type
except ImportError:  # pragma: no cover
    from adapters.base import SimulatorAdapter
    from task_config import normalize_task_type


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
            return True

        values = np.asarray(freqs, dtype=float)
        if values.size == 0:
            return False

        in_band = values[(values >= start - 1e-9) & (values <= stop + 1e-9)]
        min_points = int(self.config.get('min_band_points', 2))
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
        match = re.match(r"^\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([A-Za-z_][A-Za-z0-9_/-]*)?\s*$", text)
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
            return value

        raw_unit = unit or self._parameter_units.get(name, "")
        if not raw_unit and name in self._parameter_baseline:
            _, raw_unit = self._split_numeric_unit(self._parameter_baseline[name])

        numeric = float(value)
        if resolution:
            try:
                resolution_value = float(resolution)
            except Exception:
                resolution_value = 0.0
            if resolution_value > 0.0:
                numeric = round(numeric / resolution_value) * resolution_value
        numeric = round(numeric, 4)
        return f"{numeric}{raw_unit}" if raw_unit else f"{numeric}"

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

        if param_names is not None:
            for name in param_names:
                key = str(name)
                if key not in baseline and hasattr(self.app, key):
                    baseline[key] = self._to_plain_string(getattr(self.app, key))

        self._parameter_baseline = baseline.copy()
        return baseline

    def restore_parameter_state(self, state: dict[str, Any]) -> bool:
        """Restore a previously captured parameter state."""
        if not self.app:
            return False

        try:
            for name, value in state.items():
                self.app[name] = self._to_plain_string(value)
            self._parameter_baseline = dict(state)
            return True
        except Exception as exc:
            print(f"Failed to restore parameter state: {exc}")
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
            candidates.append(f"{setup_name} : {sweep_name}")

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
            mode_label = "Read-only mode" if skip_simulation else "Direct-project mode"
            print(f"{mode_label}: use the original file")
        elif self.optimization_config:
            self._clean_lock_files(self.original_project_path)
            self.work_project_path = self._copy_project_to_work_dir()
            self._clean_lock_files(self.work_project_path)
        else:
            self._clean_lock_files(self.original_project_path)
            self.work_project_path = self._copy_project_to_work_dir()
            self._clean_lock_files(self.work_project_path)

        if not os.path.exists(self.work_project_path):
            print(f"Error: project file not found: {self.work_project_path}")
            self._is_connected = False
            return False

        try:
            from ansys.aedt.core import Hfss

            print(f"Connecting to HFSS...")
            print(f"  Project: {self.work_project_path}")
            print(f"  Mode: non_graphical={self.config.get('non_graphical', True)}")
            self.app = Hfss(
                project=self.work_project_path,
                design=self.config.get('design_name', ''),
                version=self.config.get('aedt_version', '2023.2'),
                non_graphical=self.config.get('non_graphical', True),
                new_desktop=self.config.get('new_desktop', True),
                remove_lock=self.config.get('remove_lock', False),
                close_on_exit=False
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
            return self.original_project_path

        if not os.path.exists(self.original_project_path):
            print(f"Warning: original file not found: {self.original_project_path}")
            return self.original_project_path

        work_dir = self._get_temp_dir()

        suffix = self.optimization_config.get('project_suffix', '')

        os.makedirs(work_dir, exist_ok=True)

        original_name = Path(self.original_project_path).stem
        original_ext = Path(self.original_project_path).suffix

        new_name = f"{original_name}{suffix}_{self.task_name}{original_ext}"
        work_path = os.path.join(work_dir, new_name)

        if os.path.exists(work_path):
            print(f"Work copy already exists, using: {work_path}")
            return work_path

        try:
            if os.path.isdir(self.original_project_path):
                shutil.copytree(self.original_project_path, work_path)
            else:
                shutil.copy2(self.original_project_path, work_path)
            print(f"Copied original file to: {work_path}")
        except Exception as e:
            print(f"Failed to copy file: {e}")
            return self.original_project_path

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

        if self.app:
            try:
                self.app.modeler.fit_all()
            except Exception:
                pass

            if not skip_simulation and not sweep_task:
                try:
                    self.app.save_project()
                    print("Project saved")
                except Exception as e:
                    print(f"Failed to save project: {e}")

            time.sleep(0.5)

            try:
                if sweep_task:
                    self.app.release_desktop(close_projects=False)
                    print("Desktop released (sweep working copy)")
                elif close_desktop:
                    if hasattr(self.app, 'close_desktop'):
                        self.app.close_desktop()
                    else:
                        self.app.release_desktop(close_projects=close_projects)
                    print("Desktop closed")
                else:
                    self.app.release_desktop(close_projects=close_projects)
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

            if skip_simulation or close_projects or close_desktop:
                self._clean_lock_files(self.original_project_path)
                if self.work_project_path and self.work_project_path != self.original_project_path:
                    self._clean_lock_files(self.work_project_path)

        try:
            import gc
            gc.collect()
        except Exception:
            pass
        time.sleep(1.0)
        self._cleanup_temp_copy()

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

        try:
            assignment = self._format_parameter_assignment(name, value, unit=unit, resolution=resolution)
            self.app[name] = assignment
            if unit:
                self._parameter_units[name] = unit
            return True
        except Exception as e:
            print(f"Failed to set parameter {name}: {e}")
            return False

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

        self.current_params = params.copy()
        param_names = self.config.get('param_names', [])
        param_units = self.config.get('param_units', ['mm'] * len(param_names))
        param_resolutions = self.config.get('param_resolutions', [None] * len(param_names))

        try:
            if not self._apply_fixed_parameters():
                return False
            for i, (name, unit) in enumerate(zip(param_names, param_units)):
                if i < len(params):
                    resolution = param_resolutions[i] if i < len(param_resolutions) else None
                    if not self.set_parameter(name, params[i], unit=unit, resolution=resolution):
                        return False
            return True
        except Exception as e:
            print(f"Failed to set parameters: {e}")
            return False

    def get_parameters(self) -> np.ndarray:
        """获取当前仿真参数"""
        return self.current_params

    def simulate(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """执行仿真并返回结果"""
        if not self.app:
            return None, None, None

        setup_name = self.config.get('setup_name', 'Setup1')
        skip_simulation = self.config.get('skip_simulation', False)

        try:
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

            results = self._get_solution_data()
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            return results

        except Exception as e:
            print(f"Simulation error: {e}")
            return None, None, None

    def _get_solution_data(self) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """获取S参数数据。"""
        try:
            results = self.config.get('results', {})
            s11_expr = results.get('s11', 'dB(S(1,1))')
            s12_expr = results.get('s12', results.get('s21', 'dB(S(1,2))'))

            freqs, s11_data = self._get_solution_data_direct(s11_expr)
            if freqs is None:
                freqs, s11_data = self._get_trace_data_via_report(s11_expr)
            if freqs is None:
                return None, None, None

            s12_data = None
            if results.get('s12') or results.get('s21'):
                _, s12_raw = self._get_solution_data_direct(s12_expr)
                if s12_raw is None:
                    _, s12_raw = self._get_trace_data_via_report(s12_expr)
                s12_data = s12_raw

            return freqs, s11_data, s12_data

        except Exception as e:
            print(f"Failed to get result data: {e}")
            return None, None, None

    def _extract_solution_series(self, solution) -> Tuple[np.ndarray, np.ndarray]:
        """从 PyAEDT SolutionData 中提取频率和曲线数据。"""
        if solution is None or isinstance(solution, bool):
            return None, None

        freqs = np.array(getattr(solution, 'primary_sweep_values', []))
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

        if values.ndim > 1:
            values = values.flatten()

        if len(values) != len(freqs):
            min_len = min(len(values), len(freqs))
            freqs = freqs[:min_len]
            values = values[:min_len]

        return freqs, values

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
        coords, values = solution_data.get_expression_data(
            expression,
            formula=formula,
            sweeps=["Theta", "Phi"],
        )
        return self._normalize_far_field_rows(coords, values)

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
        for attempt in attempts:
            solution_data = self.app.post.get_solution_data_per_variation(
                "Far Fields",
                setup_sweep_name=setup_sweep_name,
                context=["Context:=", sphere_name],
                sweeps={"Theta": "All", "Phi": "All", "Freq": freq},
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
                return rows, {
                    "method": attempt["label"],
                    "setup": setup_sweep_name,
                    "context": ["Context:=", sphere_name],
                    "expression": attempt["query_expression"],
                    "formula": attempt["formula"],
                }
            except Exception as exc:
                errors.append(f"{attempt['label']}: {exc}")

        raise RuntimeError(" ; ".join(errors))

    def _attempt_far_field_report_query(
        self,
        setup_sweep_name: str,
        sphere_name: str,
        freq: str,
        expression: str,
    ) -> tuple[list[tuple[float, float, float]], dict]:
        """Fallback to the official far-field report-object path."""
        attempts = [
            {
                "label": "report_obj_raw_expr_db10",
                "query_expression": expression,
                "result_expression": expression,
                "formula": "db10",
            },
            {
                "label": "report_obj_wrapped_expr_real",
                "query_expression": f"dB({expression})",
                "result_expression": f"dB({expression})",
                "formula": "real",
            },
        ]

        errors: list[str] = []
        for attempt in attempts:
            report = self.app.post.reports_by_category.far_field(
                expressions=attempt["query_expression"],
                setup=setup_sweep_name,
                sphere_name=sphere_name,
                Freq=[freq],
                Theta=["All"],
                Phi=["All"],
            )
            report.report_type = "3D Polar Plot"
            report.primary_sweep = "Phi"
            report.secondary_sweep = "Theta"

            try:
                plot_name = f"PointingErrorProbe_{int(time.time() * 1000)}"
                report.create(plot_name)
            except Exception:
                pass

            try:
                solution_data = report.get_solution_data()
                if not solution_data:
                    errors.append(f"{attempt['label']}: no solution data")
                    continue

                rows = self._extract_far_field_rows_from_solution_data(
                    solution_data,
                    attempt["result_expression"],
                    attempt["formula"],
                )
                return rows, {
                    "method": attempt["label"],
                    "setup": setup_sweep_name,
                    "sphere": sphere_name,
                    "expression": attempt["query_expression"],
                    "formula": attempt["formula"],
                    "report_type": report.report_type,
                }
            except Exception as exc:
                errors.append(f"{attempt['label']}: {exc}")
            finally:
                try:
                    report.delete()
                except Exception:
                    pass

        raise RuntimeError(" ; ".join(errors))

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
                self._attempt_far_field_report_query,
            ):
                try:
                    rows, acquisition = attempt(
                        candidate_setup,
                        sphere_name,
                        freq,
                        expression,
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
                        if plane_cuts:
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

    def _get_solution_data_direct(self, trace_expr: str) -> Tuple[np.ndarray, np.ndarray]:
        """Directly load solution data without binding to a case-specific setup string."""
        if not self.app:
            return None, None

        # First try the setup objects exposed by the active design. This is the most
        # stable path across AEDT/PyAEDT versions because it lets the library resolve
        # the correct nominal sweep itself.
        setup_objects = []
        for setup in getattr(self.app, 'setups', []) or []:
            if setup is None:
                continue
            setup_name = getattr(setup, 'name', None)
            if self.config.get('setup_name') and setup_name and setup_name != self.config.get('setup_name'):
                continue
            setup_objects.append(setup)

        for setup in setup_objects:
            try:
                solution = setup.get_solution_data(expressions=trace_expr)
                freqs, values = self._extract_solution_series(solution)
                if freqs is not None and self._solution_frequency_coverage_ok(
                    freqs,
                    f"setup object {getattr(setup, 'name', 'unknown')}",
                ):
                    print(f"Direct solution data loaded: {len(freqs)} points")
                    return freqs, values
            except Exception as e:
                print(f"Direct setup data failed ({getattr(setup, 'name', 'unknown')}): {e}")

        # Fall back to the post processor with progressively more explicit sweep names.
        for setup_sweep_name in self._iter_candidate_setup_sweeps():
            try:
                solution = self.app.post.get_solution_data(
                    expressions=trace_expr,
                    setup_sweep_name=setup_sweep_name,
                    report_category="Standard",
                )
                freqs, values = self._extract_solution_series(solution)
                if freqs is not None and self._solution_frequency_coverage_ok(freqs, setup_sweep_name):
                    print(f"Direct solution data loaded: {len(freqs)} points")
                    return freqs, values
            except Exception as e:
                print(f"Direct solution data failed ({setup_sweep_name}): {e}")

        # Last attempt: let PyAEDT choose the nominal sweep on its own.
        try:
            solution = self.app.post.get_solution_data(
                expressions=trace_expr,
                report_category="Standard",
            )
            freqs, values = self._extract_solution_series(solution)
            if freqs is not None and self._solution_frequency_coverage_ok(freqs, "default sweep"):
                print(f"Direct solution data loaded: {len(freqs)} points")
                return freqs, values
        except Exception as e:
            print(f"Direct solution data failed (default sweep): {e}")

        return None, None

    def _get_trace_data_via_report(self, trace_expr: str) -> Tuple[np.ndarray, np.ndarray]:
        """通过兼容的结果接口获取 trace 数据。

        这里不再依赖 create_report 的返回值，因为当前 PyAEDT 版本返回的是
        bool，而不是可继续读取的 report 对象。
        """
        if not self.app:
            return None, None

        try:
            for setup_sweep_name in self._iter_candidate_setup_sweeps():
                try:
                    solution = self.app.post.get_solution_data(
                        expressions=trace_expr,
                        setup_sweep_name=setup_sweep_name,
                        report_category="Standard",
                    )
                    freqs, values = self._extract_solution_series(solution)
                    if freqs is not None and self._solution_frequency_coverage_ok(freqs, setup_sweep_name):
                        print(f"Trace data loaded: {len(freqs)} points ({setup_sweep_name})")
                        return freqs, values
                except Exception as e:
                    print(f"Trace data failed ({setup_sweep_name}): {e}")

            solution = self.app.post.get_solution_data(
                expressions=trace_expr,
                report_category="Standard",
            )
            freqs, values = self._extract_solution_series(solution)
            if freqs is None or not self._solution_frequency_coverage_ok(freqs, "default report"):
                print(f"Trace data empty ({trace_expr})")
                return None, None

            return freqs, values

        except Exception as e:
            print(f"Trace data failed ({trace_expr}): {e}")
            return None, None

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
            if self.best_params is not None:
                best_params = np.asarray(self.best_params, dtype=float)
                if not self.set_parameters(best_params):
                    print("Failed to restore best parameters before saving")
                    return False
                print(f"Restored best parameters before save: {best_params.tolist()}")

                # Re-solve once at the restored best point so the saved project opens
                # with result data already matching the visible geometry/variables.
                freqs, s11, _ = self.simulate()
                if freqs is None or s11 is None:
                    print("Failed to re-simulate best parameters before saving")
                    return False
                print("Best-parameter re-simulation completed before save")

            if self.app:
                self.app.save_project(output_path)
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


