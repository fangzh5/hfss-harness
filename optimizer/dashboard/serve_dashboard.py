"""Serve the dashboard UI and expose a minimal state API."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

try:
    from .state_bridge import rebuild_dashboard_snapshot
    from ..output_names import task_dashboard_state_file_name
    from ..task_config import normalize_task_type
except ImportError:
    from state_bridge import rebuild_dashboard_snapshot
    from output_names import task_dashboard_state_file_name
    from task_config import normalize_task_type


def _existing_task_file(task_dir: Path, suffix: str) -> Path | None:
    for task_type in ("opt", "sweep", "val"):
        candidate = task_dir / f"{task_type}_{suffix}"
        if candidate.exists():
            return candidate
    return None


def _resolve_state_path(task_dir: Path) -> Path:
    config_path = task_dir / "config.json"
    task_type = "opt"
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as fp:
                config = json.load(fp)
            if isinstance(config, dict):
                task_type = normalize_task_type(config)
        except Exception:
            task_type = "opt"

    preferred = task_dir / task_dashboard_state_file_name(task_type)
    if preferred.exists():
        return preferred

    existing = _existing_task_file(task_dir, "dashboard_state.json")
    if existing is not None:
        return existing

    legacy = task_dir / "dashboard_state.json"
    if legacy.exists():
        return legacy

    return preferred


def _resolve_control_path(task_dir: Path) -> Path:
    config_path = task_dir / "config.json"
    task_type = "opt"
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as fp:
                config = json.load(fp)
            if isinstance(config, dict):
                task_type = normalize_task_type(config)
        except Exception:
            task_type = "opt"

    preferred = task_dir / f"{task_type}_dashboard_control.json"
    if preferred.exists():
        return preferred

    existing = _existing_task_file(task_dir, "dashboard_control.json")
    if existing is not None:
        return existing

    legacy = task_dir / "dashboard_control.json"
    if legacy.exists():
        return legacy

    return preferred


def _load_state_payload(state_path: Path, task_dir: Path) -> str:
    with state_path.open("r", encoding="utf-8") as fp:
        payload = fp.read()

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload

    if (
        isinstance(parsed, dict)
        and parsed.get("optimization_mode") in ("single_objective", "multi_objective")
        and isinstance(parsed.get("runtime"), dict)
    ):
        return json.dumps(_sanitize_json_value(parsed), ensure_ascii=False, indent=2, allow_nan=False)

    rebuilt = rebuild_dashboard_snapshot(task_dir)
    if rebuilt is not None:
        return json.dumps(_sanitize_json_value(rebuilt), ensure_ascii=False, indent=2, allow_nan=False)
    return json.dumps(_sanitize_json_value(parsed), ensure_ascii=False, indent=2, allow_nan=False)


def _sanitize_json_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    return value


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, dashboard_dir: str, task_dir: str | None, **kwargs):
        self.dashboard_dir = Path(dashboard_dir).resolve()
        self.task_dir = Path(task_dir).resolve() if task_dir else None
        super().__init__(*args, directory=str(self.dashboard_dir), **kwargs)

    def log_message(self, format: str, *args):  # noqa: A003
        print(format % args)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._handle_state_api(parsed)
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/control/stop":
            self._handle_stop_request(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unsupported endpoint")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _handle_state_api(self, parsed):
        query = parse_qs(parsed.query)
        requested_state_file = query.get("state_file", [None])[0]
        requested = query.get("task_dir", [None])[0]
        state_path = None
        task_dir = None

        if requested_state_file:
            state_path = Path(requested_state_file).resolve()
            task_dir = state_path.parent
        else:
            task_dir = Path(requested).resolve() if requested else self.task_dir
            if task_dir is not None:
                state_path = _resolve_state_path(task_dir)

        if state_path is None or task_dir is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "state_file or task_dir is required")
            return

        if not state_path.exists():
            rebuilt = rebuild_dashboard_snapshot(task_dir)
            if rebuilt is not None:
                task_dir.mkdir(parents=True, exist_ok=True)
                with state_path.open("w", encoding="utf-8") as fp:
                    json.dump(rebuilt, fp, ensure_ascii=False, indent=2)

        if not state_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, f"{state_path.name} not found")
            return

        payload = _load_state_payload(state_path, task_dir)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f"{path.stem}_", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    def _handle_stop_request(self, parsed):
        query = parse_qs(parsed.query)
        requested = query.get("task_dir", [None])[0]
        task_dir = Path(requested).resolve() if requested else self.task_dir
        if task_dir is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "task_dir is required")
            return

        control_path = _resolve_control_path(task_dir)
        state_path = _resolve_state_path(task_dir)
        control = {
            "stop_requested": True,
            "reason": "user_request",
            "requested_at": time.time(),
            "requested_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        self._write_json_atomic(control_path, control)

        snapshot = None
        if state_path.exists():
            try:
                with state_path.open("r", encoding="utf-8") as fp:
                    snapshot = json.load(fp)
            except Exception:
                snapshot = None
        if not isinstance(snapshot, dict):
            snapshot = rebuild_dashboard_snapshot(task_dir) or {}
        snapshot["control"] = control
        status = snapshot.get("status") if isinstance(snapshot.get("status"), dict) else {}
        snapshot["status"] = {
            **status,
            "label": "Stopping",
            "tone": "paused",
            "detail": "Stop requested; waiting for current simulation to finish",
        }
        self._write_json_atomic(state_path, snapshot)

        payload = json.dumps({"ok": True, "control": control}, ensure_ascii=False)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the optimizer dashboard.")
    parser.add_argument(
        "--task-dir",
        default=None,
        help="Optimization output directory that contains config.json/opt_history.csv/opt_data.jsonl/opt_dashboard_state.json.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port.")
    args = parser.parse_args()

    dashboard_dir = Path(__file__).resolve().parent
    handler = partial(DashboardHandler, dashboard_dir=str(dashboard_dir), task_dir=args.task_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Serving dashboard at http://{args.host}:{args.port}/")
    if args.task_dir:
        print(f"Task dir: {Path(args.task_dir).resolve()}")
        print(f"State API: http://{args.host}:{args.port}/api/state?task_dir={Path(args.task_dir).resolve()}")
    print("Use ?task_dir=<abs-path-to-output-dir> for live polling.")
    print("Use ?state_file=<abs-path-to-*opt_dashboard_state.json> for static JSON viewing.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
