import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimizer import cli


class HiddenWindowLaunchTest(unittest.TestCase):
    def test_hidden_window_kwargs_enabled_on_windows(self):
        class FakeStartupInfo:
            def __init__(self):
                self.dwFlags = 0

        with patch.object(cli.os, "name", "nt"), patch.object(
            cli.subprocess,
            "STARTUPINFO",
            FakeStartupInfo,
        ), patch.object(cli.subprocess, "STARTF_USESHOWWINDOW", 1), patch.object(
            cli.subprocess,
            "CREATE_NO_WINDOW",
            0x08000000,
        ):
            kwargs = cli._hidden_window_popen_kwargs(True)

        self.assertIn("startupinfo", kwargs)
        self.assertIn("creationflags", kwargs)
        self.assertEqual(kwargs["creationflags"], 0x08000000)
        self.assertEqual(kwargs["startupinfo"].dwFlags, 1)

    def test_hidden_window_kwargs_disabled(self):
        kwargs = cli._hidden_window_popen_kwargs(False)
        self.assertEqual(kwargs, {})


class TeeWriterTest(unittest.TestCase):
    def test_tee_writer_ignores_console_stream_failures(self):
        class FailingStream:
            def write(self, data):
                raise OSError(22, "Invalid argument")

            def flush(self):
                raise OSError(22, "Invalid argument")

        class RecordingStream:
            def __init__(self):
                self.writes = []
                self.flushed = False

            def write(self, data):
                self.writes.append(data)

            def flush(self):
                self.flushed = True

        file_stream = RecordingStream()
        tee = cli._TeeWriter(FailingStream(), file_stream)

        bytes_written = tee.write("hello")
        tee.flush()

        self.assertEqual(bytes_written, 5)
        self.assertEqual(file_stream.writes, ["hello"])
        self.assertTrue(file_stream.flushed)


class CliEntrypointTest(unittest.TestCase):
    def test_cmaes_runtime_requires_only_cma_module(self):
        config = {
            "task_type": "opt",
            "algorithm": {"method": "cmaes"},
        }

        self.assertEqual(cli._required_algorithm_modules(config), ("cma",))

    def test_non_optional_algorithm_does_not_require_runtime_modules(self):
        config = {
            "task_type": "opt",
            "algorithm": {"method": "de"},
        }

        self.assertEqual(cli._required_algorithm_modules(config), ())

    def test_current_python_module_probe_checks_every_required_module(self):
        with patch.object(
            cli.importlib.util,
            "find_spec",
            side_effect=lambda name: object() if name in {"first", "second"} else None,
        ):
            self.assertTrue(cli._current_python_has_modules(("first", "second")))
            self.assertFalse(cli._current_python_has_modules(("first", "missing")))

    def test_project_python_module_probe_handles_present_and_missing_modules(self):
        self.assertTrue(cli._python_has_modules(Path(sys.executable), ("json",)))
        self.assertFalse(
            cli._python_has_modules(
                Path(sys.executable),
                ("module_that_does_not_exist'; raise RuntimeError('unsafe')",),
            )
        )

    def test_cli_reexecs_cmaes_runs_into_project_venv_when_current_python_lacks_deps(self):
        temp_dir = ROOT / "temp" / self._testMethodName
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "name": "demo_cmaes_reexec",
                    "task_type": "opt",
                    "launch": {
                        "dashboard": False,
                        "dashboard_browser": False,
                        "silent": False,
                        "dashboard_port": 8765,
                    },
                    "optimization": {},
                    "parameters": [],
                    "target": {},
                    "algorithm": {"method": "cmaes"},
                }
            ),
            encoding="utf-8",
        )

        fake_venv_python = temp_dir / "venv" / "Scripts" / "python.exe"
        fake_venv_python.parent.mkdir(parents=True, exist_ok=True)
        fake_venv_python.write_text("", encoding="utf-8")
        sentinel = RuntimeError("reexec")

        with patch.object(cli, "_current_python_has_modules", return_value=False) as current_has, patch.object(
            cli,
            "_python_has_modules",
            return_value=True,
        ) as venv_has, patch.object(
            cli,
            "_project_venv_python",
            return_value=fake_venv_python,
        ), patch.object(
            cli.os,
            "chdir",
        ) as chdir, patch.object(
            cli.os,
            "execv",
            side_effect=sentinel,
        ) as execv, patch.object(cli.task_runner, "run_task") as run_task:
            with self.assertRaisesRegex(RuntimeError, "reexec"):
                cli.main([str(config_path)])

        current_has.assert_called_once_with(("cma",))
        venv_has.assert_called_once_with(fake_venv_python, ("cma",))
        chdir.assert_called_once_with(ROOT)
        execv.assert_called_once_with(
            str(fake_venv_python),
            [str(fake_venv_python), "-m", "optimizer.cli", str(config_path)],
        )
        self.assertFalse(run_task.called)

    def test_cli_reexecs_bo_runs_into_project_venv_when_current_python_lacks_deps(self):
        temp_dir = ROOT / "temp" / self._testMethodName
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "name": "demo_bo_reexec",
                    "task_type": "opt",
                    "launch": {
                        "dashboard": False,
                        "dashboard_browser": False,
                        "silent": False,
                        "dashboard_port": 8765,
                    },
                    "optimization": {},
                    "parameters": [],
                    "target": {},
                    "algorithm": {"method": "bo"},
                }
            ),
            encoding="utf-8",
        )

        fake_venv_python = temp_dir / "venv" / "Scripts" / "python.exe"
        fake_venv_python.parent.mkdir(parents=True, exist_ok=True)
        fake_venv_python.write_text("", encoding="utf-8")
        sentinel = RuntimeError("reexec")

        with patch.object(cli, "_current_python_has_modules", return_value=False) as current_has, patch.object(
            cli,
            "_python_has_modules",
            return_value=True,
        ) as venv_has, patch.object(
            cli,
            "_project_venv_python",
            return_value=fake_venv_python,
        ), patch.object(
            cli.os,
            "chdir",
        ) as chdir, patch.object(
            cli.os,
            "execv",
            side_effect=sentinel,
        ) as execv, patch.object(cli.task_runner, "run_task") as run_task:
            with self.assertRaisesRegex(RuntimeError, "reexec"):
                cli.main([str(config_path)])

        current_has.assert_called_once_with(("torch", "botorch"))
        venv_has.assert_called_once_with(fake_venv_python, ("torch", "botorch"))
        chdir.assert_called_once_with(ROOT)
        execv.assert_called_once_with(
            str(fake_venv_python),
            [str(fake_venv_python), "-m", "optimizer.cli", str(config_path)],
        )
        self.assertFalse(run_task.called)

    def test_cli_launches_dashboard_and_task_runner(self):
        temp_dir = ROOT / "temp" / self._testMethodName
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "name": "demo_opt",
                    "task_type": "opt",
                    "launch": {
                        "dashboard": True,
                        "dashboard_browser": True,
                        "silent": False,
                        "dashboard_port": 8765,
                    },
                    "optimization": {},
                    "parameters": [],
                    "target": {},
                    "algorithm": {},
                }
            ),
            encoding="utf-8",
        )

        fake_proc = Mock()
        fake_log_fp = Mock()

        with patch.object(cli, "_start_dashboard_server", return_value=(fake_proc, fake_log_fp)), patch.object(
            cli,
            "_wait_for_port",
            return_value=True,
        ), patch.object(cli.webbrowser, "open_new_tab") as open_tab, patch.object(
            cli.task_runner,
            "run_task",
            return_value=0,
        ) as run_task:
            exit_code = cli.main([str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertTrue(run_task.called)
        self.assertTrue(open_tab.called)
        fake_proc.terminate.assert_called_once()
        fake_log_fp.close.assert_called_once()

    def test_cli_launches_dashboard_for_sweep_runs(self):
        temp_dir = ROOT / "temp" / self._testMethodName
        temp_dir.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "name": "demo_sweep",
                    "task_type": "sweep",
                    "launch": {
                        "dashboard": True,
                        "dashboard_browser": True,
                        "silent": False,
                        "dashboard_port": 8765,
                    },
                    "optimization": {},
                    "study": {
                        "variables": [
                            {"name": "probe_p", "start": 0.4, "stop": 0.6, "step": 0.1}
                        ]
                    },
                    "simulator": {"hfss": {"project_path": "../hfss/demo.aedt"}},
                }
            ),
            encoding="utf-8",
        )

        fake_proc = Mock()
        fake_log_fp = Mock()

        with patch.object(cli, "_start_dashboard_server", return_value=(fake_proc, fake_log_fp)), patch.object(
            cli,
            "_wait_for_port",
            return_value=True,
        ), patch.object(cli.webbrowser, "open_new_tab") as open_tab, patch.object(
            cli.task_runner,
            "run_task",
            return_value=0,
        ) as run_task:
            exit_code = cli.main([str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertTrue(run_task.called)
        self.assertTrue(open_tab.called)
        fake_proc.terminate.assert_called_once()
        fake_log_fp.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
