from pathlib import Path
import pytest

from optimizer.adapters.hfss_adapter import HFSSAdapter


class _Template:
    variations = {"Freq": ["All"], "h_lambda": ["Nominal"]}


class _Reports:
    @staticmethod
    def far_field(**_kwargs):
        return _Template()


class _Post:
    reports_by_category = _Reports()


class _ReportSetup:
    def __init__(self):
        self._phi = {}

    def CreateReport(self, name, _category, _plot_type, _setup, _context, families, _components):
        phi_index = families.index("Phi:=") + 1
        self._phi[name] = float(families[phi_index][0].removesuffix("deg"))

    def ExportToFile(self, name, path, _uniform):
        phi = self._phi[name]
        rows = ['"Freq [GHz]","Phi [deg]","Theta [deg]","dB(DirTotal) []"']
        rows.extend(f"30,{phi:g},{theta},{6.0 - theta / 10.0 + phi / 1000.0}" for theta in range(91))
        Path(path).write_text("\n".join(rows), encoding="utf-8")

    def DeleteReports(self, names):
        for name in names:
            self._phi.pop(name, None)


class _App:
    post = _Post()

    def __init__(self):
        self.oreportsetup = _ReportSetup()


def test_report_csv_fallback_returns_four_complete_theta_cuts(tmp_path):
    adapter = object.__new__(HFSSAdapter)
    adapter.app = _App()
    adapter._get_temp_dir = lambda: str(tmp_path)

    rows, metadata = adapter._attempt_far_field_report_query(
        "Setup_30GHz : LastAdaptive",
        "UpperHemisphere",
        "30GHz",
        "DirTotal",
    )

    assert metadata["method"] == "report_csv_fixed_phi"
    assert len(rows) == 4 * 91
    assert sorted({row[1] for row in rows}) == [0.0, 90.0, 180.0, 270.0]
    assert sorted({row[0] for row in rows}) == list(range(91))


def test_explicit_full_sphere_does_not_accept_a_hemisphere(tmp_path):
    adapter = object.__new__(HFSSAdapter)
    adapter.app = _App()
    adapter._get_temp_dir = lambda: str(tmp_path)
    with pytest.raises(RuntimeError, match="incomplete Theta/Phi"):
        adapter._attempt_far_field_report_query("Analysis : Field", "Sphere", "30GHz", "DirTotal",
                                               phi_samples_deg=list(range(0,360,45)))


def test_explicit_full_sphere_csv_is_labeled_only_after_grid_verification(tmp_path):
    class FullReport(_ReportSetup):
        def ExportToFile(self, name, path, _uniform):
            phi = self._phi[name]
            rows = ['"Freq [GHz]","Phi [deg]","Theta [deg]","dB(DirTotal) []"']
            rows.extend(f"30,{phi:g},{theta},6" for theta in range(0,181,10))
            Path(path).write_text("\n".join(rows))
    adapter = object.__new__(HFSSAdapter)
    adapter.app = _App()
    adapter.app.oreportsetup = FullReport()
    adapter._get_temp_dir = lambda: str(tmp_path)
    rows, metadata = adapter._attempt_far_field_report_query("Analysis : Field", "Sphere", "30GHz", "DirTotal",
                                                             phi_samples_deg=list(range(0,360,45)))
    assert len(rows) == 19*8 and metadata["angular_scope"] == "sampled_sphere"
