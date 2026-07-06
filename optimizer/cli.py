"""Launch the optimizer with unified console logs."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

try:
    from .config_io import load_config
    from .path_utils import (
        resolve_config_path,
        resolve_run_stamp,
        resolve_task_name,
        resolve_task_output_dir,
    )
    from . import task_runner
    from .task_config import normalize_task_type
except ImportError:  # pragma: no cover
    from config_io import load_config
    from path_utils import (
        resolve_config_path,
        resolve_run_stamp,
        resolve_task_name,
        resolve_task_output_dir,
    )
    import task_runner
    from task_config import normalize_task_type


def _resolve_launch_bool(cli_value, launch_config: dict, key: str, default: bool) -> bool:
    """Resolve a launch boolean from CLI override, config, or default."""
    if cli_value is not None:
        return bool(cli_value)
    if key not in launch_config:
        return default
    value = launch_config.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return bool(value)


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class _TeeWriter:
    """Write console output to multiple streams."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            try:
                stream.write(data)
            except (OSError, ValueError):
                # Console streams can fail independently of the log file. Keep the
                # file-backed stream alive so the optimizer can finish and persist.
                continue
        return len(data)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except (OSError, ValueError):
                # Do not let a bad console handle abort the optimization run.
                continue


def _hidden_window_popen_kwargs(enabled: bool) -> dict:
    """Return Windows-only subprocess flags that suppress console windows."""
    if not enabled or os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _start_dashboard_server(
    task_output_dir: Path,
    script_dir: Path,
    stamp: str,
    log_dir: Path,
    port: int,
    hide_console: bool = False,
):
    dashboard_script = script_dir / "dashboard" / "serve_dashboard.py"
    if not dashboard_script.exists():
        print(f"Dashboard server not started: missing {dashboard_script}")
        return None, None

    dashboard_log = log_dir / f"dashboard_{stamp}.log"
    log_fp = dashboard_log.open("w", encoding="utf-8")
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "optimizer.dashboard.serve_dashboard",
        "--task-dir",
        str(task_output_dir),
        "--port",
        str(port),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(script_dir.parent),
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            **_hidden_window_popen_kwargs(hide_console),
        )
    except Exception as exc:
        log_fp.close()
        print(f"Dashboard server start failed: {exc}")
        return None, None

    time.sleep(0.5)
    if proc.poll() is not None:
        log_fp.close()
        print(f"Dashboard server exited immediately; see {dashboard_log}")
        return None, None

    print(f"Dashboard: http://127.0.0.1:{port}/?task_dir={quote(task_output_dir.as_posix(), safe='')}")
    print(f"Dashboard log: {dashboard_log}")
    return proc, log_fp


OPTIONAL_ALGORITHM_MODULES = {
    "bo": ("torch", "botorch"),
    "cmaes": ("cma",),
}


def _required_algorithm_modules(config: dict) -> tuple[str, ...]:
    if normalize_task_type(config) != "opt":
        return ()
    method = str((config.get("algorithm") or {}).get("method", "")).strip().lower()
    return OPTIONAL_ALGORITHM_MODULES.get(method, ())


def _current_python_has_modules(modules: tuple[str, ...]) -> bool:
    return all(importlib.util.find_spec(module) is not None for module in modules)


def _python_has_modules(python_executable: Path, modules: tuple[str, ...]) -> bool:
    modules_literal = repr(tuple(modules))
    try:
        completed = subprocess.run(
            [
                str(python_executable),
                "-c",
                (
                    "import importlib.util, sys; "
                    f"modules={modules_literal}; "
                    "sys.exit(0 if all(importlib.util.find_spec(module) is not None for module in modules) else 1)"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _project_venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def _exec_into_python(python_executable: Path, repo_root: Path, argv: list[str]) -> None:
    os.chdir(repo_root)
    os.execv(str(python_executable), [str(python_executable), "-m", "optimizer.cli", *argv])


def _maybe_reexec_algorithm_into_project_venv(config: dict, repo_root: Path, argv: list[str]) -> int | None:
    required_modules = _required_algorithm_modules(config)
    if not required_modules:
        return None
    if _current_python_has_modules(required_modules):
        return None

    venv_python = _project_venv_python(repo_root)
    if not venv_python.exists() or not _python_has_modules(venv_python, required_modules):
        method = str((config.get("algorithm") or {}).get("method", "")).strip().lower()
        module_text = ", ".join(required_modules)
        raise RuntimeError(
            f"{method.upper()} task requires {module_text}, but the current Python environment "
            "does not provide them and the project .venv is not usable."
        )

    method = str((config.get("algorithm") or {}).get("method", "")).strip().upper()
    print(
        f"{method} dependencies missing in current interpreter; "
        f"re-launching with project environment: {venv_python}",
        flush=True,
    )
    _exec_into_python(venv_python, repo_root, argv)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch optimizer with centralized run logs.")
    parser.add_argument("config", nargs="?", default="configs/template.json", help="Path to the optimizer config.")
    parser.add_argument("--log-dir", default=None, help="Override the log directory root.")
    parser.add_argument(
        "--dashboard",
        dest="dashboard",
        action="store_true",
        default=None,
        help="Start the dashboard server for optimization runs.",
    )
    parser.add_argument(
        "--no-dashboard",
        dest="dashboard",
        action="store_false",
        help="Disable the dashboard server for optimization runs.",
    )
    parser.add_argument(
        "--dashboard-browser",
        action="store_true",
        default=None,
        help="Open the dashboard in the default browser once the server is ready.",
    )
    parser.add_argument(
        "--no-dashboard-browser",
        dest="dashboard_browser",
        action="store_false",
        help="Do not open the dashboard in the default browser.",
    )
    parser.add_argument(
        "--silent",
        dest="silent",
        action="store_true",
        default=None,
        help="Suppress live console progress and dashboard startup.",
    )
    parser.add_argument(
        "--no-silent",
        dest="silent",
        action="store_false",
        help="Enable live console progress and dashboard startup.",
    )
    parser.add_argument("--dashboard-port", type=int, default=8765, help="Dashboard server port.")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    argv = list(argv or sys.argv[1:])
    config_path = resolve_config_path(args.config, script_dir)
    config = load_config(config_path, script_dir)
    reexec_exit = _maybe_reexec_algorithm_into_project_venv(config, repo_root, argv)
    if reexec_exit is not None:
        return int(reexec_exit)
    launch_config = config.get("launch", {})
    task_type = normalize_task_type(config)
    dashboard_enabled = _resolve_launch_bool(args.dashboard, launch_config, "dashboard", True)
    dashboard_browser_enabled = _resolve_launch_bool(
        args.dashboard_browser,
        launch_config,
        "dashboard_browser",
        True,
    )
    silent_enabled = _resolve_launch_bool(args.silent, launch_config, "silent", False)
    dashboard_port = int(launch_config.get("dashboard_port", args.dashboard_port))
    task_name = resolve_task_name(config, config_path)
    stamp = resolve_run_stamp(config.get("optimization", {}).get("run_stamp"))
    task_output_dir = resolve_task_output_dir(config, script_dir, stamp, task_name=task_name)
    if args.log_dir:
        log_root = Path(args.log_dir)
        if not log_root.is_absolute():
            log_root = (repo_root / log_root).resolve()
        log_dir = log_root / task_name / stamp
    else:
        log_dir = task_output_dir / "logs"
    task_output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    out_log = log_dir / f"{task_name}_{stamp}.out.log"
    err_log = log_dir / f"{task_name}_{stamp}.err.log"

    dashboard_proc = None
    dashboard_log_fp = None
    dashboard_task_dir = quote(task_output_dir.as_posix(), safe="")
    dashboard_url = f"http://127.0.0.1:{dashboard_port}/?task_dir={dashboard_task_dir}"
    if dashboard_enabled and not silent_enabled:
        dashboard_proc, dashboard_log_fp = _start_dashboard_server(
            task_output_dir,
            script_dir,
            stamp,
            log_dir,
            dashboard_port,
            hide_console=True,
        )
        if dashboard_proc is not None and dashboard_browser_enabled:
            if _wait_for_port("127.0.0.1", dashboard_port, timeout=10.0):
                try:
                    webbrowser.open_new_tab(dashboard_url)
                    print(f"Opened dashboard browser: {dashboard_url}")
                except Exception as exc:
                    print(f"Failed to open dashboard browser: {exc}")
            else:
                print(f"Dashboard browser not opened: server not ready at {dashboard_url}")

    print("=" * 58, flush=True)
    print(f"[task={task_name} | config={config_path.name} | stamp={stamp}]", flush=True)
    print(f"Log dir: {log_dir}", flush=True)
    print(f"Task output dir: {task_output_dir}", flush=True)
    if dashboard_enabled:
        print(f"Dashboard URL: {dashboard_url}", flush=True)
    print(f"OUT: {out_log}", flush=True)
    print(f"ERR: {err_log}", flush=True)
    print(f"Run: {task_runner.__name__}.run_task({config_path.name})", flush=True)
    print("=" * 58, flush=True)

    try:
        with out_log.open("w", encoding="utf-8") as out_fp, err_log.open("w", encoding="utf-8") as err_fp:
            tee_out = _TeeWriter(sys.stdout, out_fp)
            tee_err = _TeeWriter(sys.stderr, err_fp)
            with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
                return task_runner.run_task(
                    str(config_path),
                    run_stamp=stamp,
                    task_output_dir=str(task_output_dir),
                )
    finally:
        if dashboard_proc is not None:
            try:
                dashboard_proc.terminate()
                dashboard_proc.wait(timeout=5)
            except Exception:
                try:
                    dashboard_proc.kill()
                except Exception:
                    pass
        if dashboard_log_fp is not None:
            dashboard_log_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
