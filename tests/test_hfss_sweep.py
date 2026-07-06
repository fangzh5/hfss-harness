from pathlib import Path
import json
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.output_names import task_dashboard_state_file_name
from optimizer.sweep import run_hfss_sweep


class FakeSweepAdapter:
    def __init__(self):
        self.calls = []
        self.baseline = {"strip_l": "1.00mm", "patch_x": "0.94mm"}
        self.current = self.baseline.copy()
        self.config = {
            "setup_name": "Setup1",
            "sweep_name": "Sweep",
            "results": {"s11": "dB(S(1,1))", "s12": "dB(S(1,2))"},
        }

    def capture_current_parameter_state(self):
        self.calls.append(("capture", self.current.copy()))
        return self.current.copy()

    def set_parameter(self, name, value):
        self.calls.append(("set", name, float(value)))
        if name == "strip_l":
            self.current[name] = f"{float(value):.2f}mm"
        else:
            self.current[name] = f"{float(value):.2f}mm"
        return True

    def simulate(self):
        self.calls.append(("simulate", self.current.copy()))
        freqs = np.array([56.0, 57.0, 58.0], dtype=float)
        s11 = np.array([-9.0, -12.0, -11.0], dtype=float)
        s12 = np.array([-18.0, -19.0, -20.0], dtype=float)
        return freqs, s11, s12

    def get_far_field_peak_loss_band(self, **kwargs):
        self.calls.append(("far_field", kwargs))
        return {
            "frequencies": ["56GHz"],
            "summary": {
                "point_count": 1,
                "worst_peak_loss_db": 0.12,
                "best_peak_loss_db": 0.12,
                "average_peak_loss_db": 0.12,
                "worst_pointing_error_deg": 0.0,
                "best_pointing_error_deg": 0.0,
                "average_pointing_error_deg": 0.0,
            },
            "per_frequency": [
                {
                    "frequency": "56GHz",
                    "peak_loss_db": 0.12,
                    "pointing_error_deg": 0.0,
                    "global_peak_direction": {
                        "theta_deg": 0.0,
                        "phi_deg": 0.0,
                        "gain_db": 8.5,
                    },
                    "plane_cuts": {
                        "primary_plane": {
                            "plane_phi_deg": 0.0,
                            "plane_include_opposite": True,
                            "cut_angle_deg": [0.0, 90.0, 180.0],
                            "gain_db": [6.0, 7.0, 6.5],
                        }
                    },
                }
            ],
        }

    def restore_parameter_state(self, baseline):
        self.calls.append(("restore", baseline.copy()))
        self.current = baseline.copy()
        return True


def test_run_hfss_sweep_scans_one_variable_at_a_time(tmp_path):
    adapter = FakeSweepAdapter()
    config = {
        "name": "strip_l_study",
        "task_type": "sweep",
        "optimization": {
            "task_output_dir": str(tmp_path),
        },
        "simulator": {
            "hfss": {
                "project_path": "hfss/patch.aedt",
                "design_name": "design1",
                "setup_name": "Setup1",
                "sweep_name": "Sweep",
            }
        },
        "study": {
            "variables": [
                {"name": "strip_l", "start": 0.8, "stop": 1.0, "step": 0.1},
                {"name": "patch_x", "start": 0.9, "stop": 1.0, "step": 0.1},
            ],
            "freq_band": [56.0, 58.0],
            "s11_threshold": -10.0,
            "s12_threshold": -18.5,
        },
    }

    result = run_hfss_sweep(config, adapter)

    summary_path = tmp_path / "sweep_summary.csv"
    raw_path = tmp_path / "sweep_data.jsonl"
    summary_json_path = tmp_path / "summary.json"
    plot_path = tmp_path / "sweep_summary.png"
    dashboard_state_path = tmp_path / task_dashboard_state_file_name("sweep")

    assert summary_path.exists()
    assert raw_path.exists()
    assert summary_json_path.exists()
    assert plot_path.exists()
    assert dashboard_state_path.exists()
    assert result["total_points"] == 5
    assert result["variables"] == ["strip_l", "patch_x"]

    raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    summary = json.loads(summary_json_path.read_text(encoding="utf-8"))
    dashboard_state = json.loads(dashboard_state_path.read_text(encoding="utf-8"))
    assert summary["records"] == 5
    assert summary["variables"] == ["strip_l", "patch_x"]
    assert dashboard_state["task_type"] == "sweep"
    assert dashboard_state["status"]["label"] == "Completed"
    assert dashboard_state["runtime"]["completed_simulations"] == 5
    assert dashboard_state["runtime"]["max_simulations"] == 5
    assert dashboard_state["current"]["params"]["patch_x"] == 1.0
    assert dashboard_state["current"]["sweep_variable"] == "patch_x"
    assert dashboard_state["s11Curves"]["last"]
    assert dashboard_state["events"]
    assert [row["variable"] for row in raw_rows] == ["strip_l", "strip_l", "strip_l", "patch_x", "patch_x"]
    assert adapter.calls[0][0] == "capture"
    assert adapter.calls[-1][0] == "restore"
    assert adapter.current == adapter.baseline

    set_calls = [call for call in adapter.calls if call[0] == "set"]
    assert [call[1] for call in set_calls] == ["strip_l", "strip_l", "strip_l", "patch_x", "patch_x"]
    assert [round(call[2], 1) for call in set_calls] == [0.8, 0.9, 1.0, 0.9, 1.0]


def test_run_hfss_sweep_includes_far_field_records_when_enabled(tmp_path):
    adapter = FakeSweepAdapter()
    config = {
        "name": "strip_l_study",
        "task_type": "sweep",
        "optimization": {
            "task_output_dir": str(tmp_path),
        },
        "simulator": {
            "hfss": {
                "project_path": "hfss/patch.aedt",
                "design_name": "design1",
                "setup_name": "Setup1",
                "sweep_name": "Sweep",
            }
        },
        "study": {
            "variables": [
                {"name": "strip_l", "start": 0.8, "stop": 0.8, "step": 0.1},
            ],
            "freq_band": [56.0, 58.0],
            "s11_threshold": -10.0,
            "s12_threshold": -18.5,
            "far_field": {
                "enabled": True,
                "freqs": ["56GHz"],
                "theta_deg": 0.0,
                "phi_deg": 0.0,
                "sphere": "3D",
                "expression": "RealizedGainTotal",
            },
        },
    }

    run_hfss_sweep(config, adapter)

    raw_path = tmp_path / "sweep_data.jsonl"
    raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]

    assert raw_rows[0]["record_type"] == "far_field_meta"
    assert raw_rows[1]["s11"] == [-9.0, -12.0, -11.0]
    assert raw_rows[1]["s12"] == [-18.0, -19.0, -20.0]
    assert raw_rows[1]["far_field"]["global_peak"]["gain_db"] == [8.5]
    assert raw_rows[1]["task_type"] == "sweep"
    assert raw_rows[1]["sweep_variable"] == "strip_l"
