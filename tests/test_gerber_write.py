from optimizer.fabrication.gerber_write import format_coord, write_copper_gerber, write_outline_gerber
from optimizer.fabrication.model import BoardOutline, Polygon


def test_format_coord_uses_millimeter_46():
    assert format_coord(1.25) == "001250"
    assert format_coord(-0.5) == "-000500"


def test_write_copper_gerber_outputs_region(tmp_path):
    output = tmp_path / "top.gbr"
    polygon = Polygon(layer="L1_TOP", points=[[0, 0], [1, 0], [1, 1], [0, 1]], source_objects=["patch"])

    write_copper_gerber(output, "L1_TOP", [polygon])

    text = output.read_text(encoding="utf-8")
    assert "%FSLAX33Y33*%" in text
    assert "%MOMM*%" in text
    assert "G36*" in text
    assert "G37*" in text
    assert "X000000Y000000D02*" in text


def test_write_copper_gerber_outputs_clear_region(tmp_path):
    output = tmp_path / "top.gbr"
    polygons = [
        Polygon(layer="L1_TOP", points=[[0, 0], [2, 0], [2, 2], [0, 2]], source_objects=["ground"]),
        Polygon(layer="L1_TOP", points=[[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]], source_objects=["ground"], polarity="clear"),
        Polygon(layer="L1_TOP", points=[[0.6, 0.6], [0.9, 0.6], [0.9, 0.9], [0.6, 0.9]], source_objects=["patch"]),
    ]

    write_copper_gerber(output, "L1_TOP", polygons)

    text = output.read_text(encoding="utf-8")
    assert "%LPC*%" in text
    assert text.index("%LPC*%") < text.index("%LPD*%", text.index("%LPC*%"))


def test_write_outline_gerber_outputs_drawn_perimeter(tmp_path):
    output = tmp_path / "outline.gbr"
    outline = BoardOutline(points=[[0, 0], [2, 0], [2, 1], [0, 1]])

    write_outline_gerber(output, outline)

    text = output.read_text(encoding="utf-8")
    assert "%ADD10C,0.0500*%" in text
    assert "X000000Y000000D02*" in text
    assert "X002000Y000000D01*" in text
    assert "M02*" in text
