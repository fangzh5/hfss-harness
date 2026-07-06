from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from optimizer.core.study import (
    build_step_sweep_values,
    summarize_longest_matched_band,
    summarize_sparameter_band,
)


def test_build_step_sweep_values_includes_upper_bound():
    assert build_step_sweep_values(0.1, 1.2, 0.1) == [
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
        0.7,
        0.8,
        0.9,
        1.0,
        1.1,
        1.2,
    ]


def test_summarize_sparameter_band_uses_inclusive_thresholds():
    freqs = [55.0, 56.0, 60.0, 66.0, 67.0]
    s11 = [-9.0, -12.0, -11.0, -8.0, -20.0]
    s12 = [-18.0, -21.0, -20.0, -19.0, -30.0]

    summary = summarize_sparameter_band(
        freqs=freqs,
        s11=s11,
        s12=s12,
        freq_band=(56.0, 66.0),
        s11_threshold=-10.0,
        s12_threshold=-20.0,
    )

    assert summary["point_count"] == 3
    assert summary["s11_worst_db"] == -8.0
    assert summary["s12_worst_db"] == -19.0
    assert summary["s11_pass_count"] == 2
    assert summary["s12_pass_count"] == 2
    assert summary["s11_pass_ratio"] == 2.0 / 3.0
    assert summary["s12_pass_ratio"] == 2.0 / 3.0


def test_summarize_longest_matched_band_tracks_worst_s12_inside_matched_segment():
    freqs = [56.0, 57.0, 58.0, 59.0, 60.0, 61.0, 62.0]
    s11 = [-8.0, -10.5, -11.0, -10.2, -9.5, -10.8, -11.2]
    s12 = [-14.0, -16.0, -18.0, -17.0, -13.0, -19.0, -21.0]

    summary = summarize_longest_matched_band(
        freqs=freqs,
        s11=s11,
        s12=s12,
        s11_threshold=-10.0,
    )

    assert summary["matched_point_count"] == 3
    assert summary["matched_bandwidth_ghz"] == 2.0
    assert summary["matched_start_ghz"] == 57.0
    assert summary["matched_end_ghz"] == 59.0
    assert summary["matched_s11_worst_db"] == -10.2
    assert summary["matched_s12_worst_db"] == -16.0
