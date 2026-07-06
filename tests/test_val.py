from pathlib import Path
import json
import sys
import types

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.output_names import task_dashboard_state_file_name
from optimizer.task_config import validate_task_config
from optimizer.validation import run_val_cases


class FakeValAdapter:
    def __init__(self):
        self.baseline = {"strip_l": "1.00mm", "strip_w": "0.10mm"}
        self.current = self.baseline.copy()
        self.calls = []
        self.config = {
            "setup_name": "Setup1",
            "sweep_name": "Sweep",
            "results": {"s11": "dB(S(1,1))", "s12": "dB(S(1,2))"},
        }

    def capture_current_parameter_state(self):
        return self.current.copy()

    def restore_parameter_state(self, baseline):
        self.calls.append(("restore", baseline.copy()))
        self.current = baseline.copy()
        return True

    def set_parameter(self, name, value):
        self.calls.append(("set", name, float(value)))
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
                "worst_pointing_error_deg": 0.7,
                "best_pointing_error_deg": 0.7,
                "average_pointing_error_deg": 0.7,
            },
            "per_frequency": [
                {
                    "frequency": "56GHz",
                    "peak_loss_db": 0.12,
                    "pointing_error_deg": 0.7,
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


def test_val_task_config_requires_cases_and_target():
    config = {
        "task_type": "val",
        "cases": [{"name": "case_001", "params": {"strip_l": 1.0}}],
        "target": {"freq_band": [56, 66]},
    }

    assert validate_task_config(config) == "val"


def test_run_val_cases_writes_prefixed_outputs(tmp_path):
    adapter = FakeValAdapter()
    config = {
        "name": "patch_val",
        "task_type": "val",
        "optimization": {
            "task_output_dir": str(tmp_path),
        },
        "simulator": {
            "hfss": {
                "project_path": "hfss/patch.aedt",
                "design_name": "element",
                "setup_name": "Setup1",
                "sweep_name": "Sweep",
            }
        },
        "target": {
            "freq_band": [56.0, 58.0],
            "s11_threshold": -10.0,
            "boresight": {
                "enabled": True,
                "freqs": ["56GHz"],
                "theta_deg": 0.0,
                "phi_deg": 0.0,
                "sphere": "3D",
                "expression": "RealizedGainTotal",
            },
        },
        "cases": [
            {"name": "case_a", "params": {"strip_l": 0.8, "strip_w": 0.1}},
            {"name": "case_b", "params": {"strip_l": 0.9, "strip_w": 0.12}},
        ],
    }

    result = run_val_cases(config, adapter)

    data_path = tmp_path / "val_data.jsonl"
    summary_path = tmp_path / "val_results.csv"
    report_path = tmp_path / "val_report.md"
    dashboard_state_path = tmp_path / task_dashboard_state_file_name("val")

    assert data_path.exists()
    assert summary_path.exists()
    assert report_path.exists()
    assert dashboard_state_path.exists()
    assert result["total_cases"] == 2
    assert result["data_path"] == str(data_path)
    assert result["summary_path"] == str(summary_path)

    raw_rows = [json.loads(line) for line in data_path.read_text(encoding="utf-8").splitlines()]
    dashboard_state = json.loads(dashboard_state_path.read_text(encoding="utf-8"))
    assert raw_rows[0]["case_name"] == "case_a"
    assert raw_rows[1]["case_name"] == "case_b"
    assert raw_rows[0]["task_type"] == "val"
    assert raw_rows[0]["far_field"]["summary"]["worst_pointing_error_deg"] == 0.7
    assert dashboard_state["task_type"] == "val"
    assert dashboard_state["status"]["label"] == "Completed"
    assert dashboard_state["runtime"]["completed_simulations"] == 2
    assert dashboard_state["runtime"]["max_simulations"] == 2
    assert dashboard_state["current"]["case_name"] == "case_b"
    assert dashboard_state["metrics"]["fitness"]["value"] == 22.0
    assert dashboard_state["events"]

    summary_text = report_path.read_text(encoding="utf-8")
    assert "val" in summary_text
    assert "case_a" in summary_text
