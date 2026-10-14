from optimizer.fabrication.model import BoardOutline, FabModel, Layer, Polygon
from optimizer.fabrication.package_check import package_manifest, write_preview


def test_package_manifest_records_counts():
    model = FabModel(
        source_project="p.aedt",
        source_design="final",
        layers=[Layer(name="L1_TOP", kind="copper", z=0.1)],
        polygons=[Polygon(layer="L1_TOP", points=[[0, 0], [1, 0], [1, 1]])],
        board_outline=BoardOutline(points=[[0, 0], [2, 0], [2, 2], [0, 2]]),
    )

    manifest = package_manifest(model)

    assert manifest["source_design"] == "final"
    assert manifest["layer_count"] == 1
    assert manifest["polygon_count"] == 1


def test_write_preview_creates_png(tmp_path):
    model = FabModel(
        source_project="p.aedt",
        source_design="final",
        layers=[Layer(name="L1_TOP", kind="copper", z=0.1)],
        polygons=[Polygon(layer="L1_TOP", points=[[0, 0], [1, 0], [1, 1], [0, 1]])],
        board_outline=BoardOutline(points=[[0, 0], [2, 0], [2, 2], [0, 2]]),
    )
    output = tmp_path / "preview.png"

    write_preview(output, model)

    assert output.exists()
    assert output.stat().st_size > 0
