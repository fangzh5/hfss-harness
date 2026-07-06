import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "optimizer" / "dashboard" / "index.html"
STYLESHEET = ROOT / "optimizer" / "dashboard" / "styles.css"
JAVASCRIPT = ROOT / "optimizer" / "dashboard" / "dashboard.js"


class DashboardCurveGridLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX_HTML.read_text(encoding="utf-8")
        cls.css = STYLESHEET.read_text(encoding="utf-8")
        cls.js = JAVASCRIPT.read_text(encoding="utf-8")

    def test_curve_grid_uses_two_fixed_columns_on_desktop(self):
        self.assertRegex(
            self.css,
            re.compile(
                r"\.curve-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
                re.DOTALL,
            ),
        )
        self.assertNotIn("repeat(auto-fit, minmax(240px, 1fr))", self.css)

    def test_curve_grid_collapses_to_one_column_on_mobile_only(self):
        self.assertRegex(
            self.css,
            re.compile(
                r"@media\s*\(max-width:\s*760px\)\s*\{[\s\S]*?\.curve-grid\s*\{[^}]*grid-template-columns:\s*1fr;",
                re.DOTALL,
            ),
        )

    def test_theme_toggle_is_present_and_corner_anchored(self):
        self.assertIn('data-theme-toggle="1"', self.html)
        self.assertIn('id="theme-toggle-state"', self.html)
        self.assertRegex(
            self.css,
            re.compile(
                r"\.theme-toggle\s*\{[^}]*position:\s*fixed;[^}]*right:\s*16px;[^}]*bottom:\s*16px;",
                re.DOTALL,
            ),
        )

    def test_dashboard_javascript_defines_theme_persistence(self):
        self.assertIn("optimizer-dashboard-theme-preference", self.js)
        self.assertIn('prefers-color-scheme: dark', self.js)
        self.assertIn("setupThemeToggle", self.js)

    def test_dashboard_javascript_renders_algorithm_and_bo_summary_metrics(self):
        self.assertIn('label: "Algorithm"', self.js)
        self.assertIn('label: "BO Phase"', self.js)
        self.assertIn('label: "History Loaded"', self.js)
        self.assertIn('label: "BO MAE %"', self.js)


if __name__ == "__main__":
    unittest.main()
