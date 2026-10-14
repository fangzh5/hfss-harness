from pathlib import Path
import pytest

pytest.importorskip("gerbonara", reason="optional CAM extra")
pytest.importorskip("shapely", reason="optional CAM extra")
from optimizer.fabrication.cam_io import read_copper, write_copper, final_region, read_drill, write_drill


def test_actual_cam_roundtrip_keeps_clear_hole_and_dark_island_order(tmp_path):
    outer = {"kind": "polygon", "polarity": "dark", "points": [[0, 0], [4, 0], [4, 4], [0, 4]]}
    window = {"kind": "circle", "polarity": "clear", "x": 2., "y": 2., "diameter": 2.}
    island = {"kind": "polygon", "polarity": "dark", "points": [[1.8, 1.8], [2.2, 1.8], [2.2, 2.2], [1.8, 2.2]]}
    operations = [outer, window, island]
    path = tmp_path / "layer.gbr"
    write_copper(path, operations)
    actual = read_copper(path)
    assert [op["polarity"] for op in actual] == ["dark", "clear", "dark"]
    assert final_region(actual).symmetric_difference(final_region(operations)).area < 1e-10
    with pytest.raises(FileExistsError): write_copper(path, operations)


def test_drill_output_retains_negative_positions_diameter_and_plated_metadata(tmp_path):
    path = tmp_path / "L1-L2-plated.drl"
    hits = [{"x": -1.5, "y": -1.361111, "diameter": 0.2}, {"x": 0., "y": 1.75, "diameter": 0.2}]
    write_drill(path, hits, plated=True)
    assert read_drill(path) == [dict(hit, plated=True) for hit in hits]


def test_external_inch_circle_is_converted_to_mm(tmp_path):
    path = tmp_path / "external.gbr"
    path.write_text("%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.010*%\n%LPD*%\nD10*\nX010000Y-020000D03*\nM02*\n")
    op = read_copper(path)[0]
    assert op["x"] == pytest.approx(25.4) and op["y"] == pytest.approx(-50.8)
    assert op["diameter"] == pytest.approx(0.254)


def test_unsupported_rectangular_flash_is_refused(tmp_path):
    path = tmp_path / "rectangle.gbr"
    path.write_text("%FSLAX46Y46*%\n%MOMM*%\n%ADD10R,1X2*%\n%LPD*%\nD10*\nX0Y0D03*\nM02*\n")
    with pytest.raises(ValueError, match="Unsupported CAM feature"): read_copper(path)


def test_explicit_nonmetallized_drill_annotation_survives_file_roundtrip(tmp_path):
    path = tmp_path / "NPTH.drl"
    hits = [{"x": 1., "y": 2., "diameter": .2}]
    write_drill(path, hits, plated=False)
    assert read_drill(path) == [dict(hits[0], plated=False)]


def test_excessive_drill_count_is_rejected_before_output(tmp_path):
    path = tmp_path / "too_many.drl"
    with pytest.raises(ValueError, match="10000"):
        write_drill(path, [{"x": 0., "y": 0., "diameter": .2}] * 10001, plated=True)
    assert not path.exists()
