import pytest
pytest.importorskip("gerbonara", reason="optional CAM extra")
from optimizer.fabrication.profile_io import write_profile, read_profile


def test_concave_dielectric_outline_roundtrips_as_closed_profile_not_bbox(tmp_path):
    ring = [[-2, -2], [2, -2], [2, 2], [0, 2], [0, 0], [-2, 0]]
    path = tmp_path / "BOARD_OUTLINE.gko"
    write_profile(path, [ring])
    result = read_profile(path)
    assert len(result["contours"]) == 1
    assert set(map(tuple, result["contours"][0])) == set(map(tuple, ring))
    assert result["line_width_mm"] == .05 and tuple(result["file_function"]) == ("Profile", "NP")
    assert "G36" not in path.read_text()
    with pytest.raises(FileExistsError): write_profile(path, [ring])


def test_open_or_branched_profile_is_refused(tmp_path):
    path = tmp_path / "open.gko"
    path.write_text("%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.05*%\nD10*\nX0Y0D02*\nX1000000Y0D01*\nX1000000Y1000000D01*\nM02*\n")
    with pytest.raises(ValueError, match="open"): read_profile(path)


def test_filled_copper_region_is_not_accepted_as_board_profile(tmp_path):
    from optimizer.fabrication.cam_io import write_copper
    path = tmp_path / "filled.gko"
    write_copper(path, [{"kind": "polygon", "polarity": "dark", "points": [[0,0],[1,0],[1,1],[0,1]]}])
    with pytest.raises(ValueError, match="straight lines"): read_profile(path)


def test_invalid_profile_does_not_create_output(tmp_path):
    path = tmp_path / "crossed.gko"
    with pytest.raises(ValueError): write_profile(path, [[[0,0],[1,1],[1,0],[0,1]]])
    assert not path.exists()
