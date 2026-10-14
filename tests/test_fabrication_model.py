from optimizer.fabrication.model import (
    BoardOutline,
    DrillTool,
    FabModel,
    Layer,
    Polygon,
    Via,
)
from dataclasses import replace
import pytest


def valid_model():
    return FabModel(source_project="p.aedt", source_design="base",
        layers=[Layer("TOP", "copper", 0.31, 0.02), Layer("D1", "dielectric", 0.15, 0.3),
                Layer("BOT", "copper", -0.01, 0.02)],
        polygons=[Polygon("TOP", [[0, 0], [1, 0], [1, 1], [0, 1]])],
        vias=[Via(0.5, 0.5, 0.2, "TOP", "BOT", "v")], drill_tools=[DrillTool("T01", 0.2)],
        board_outline=BoardOutline([[0, 0], [2, 0], [2, 2], [0, 2]]))


def test_valid_fabrication_structure_passes_including_explicitly_closed_ring():
    model = valid_model()
    model.board_outline.points.append([0, 0])
    assert model.validate() == []


@pytest.mark.parametrize("change", ["dielectric_via_end", "unknown_polygon_layer", "invalid_polarity", "duplicate_layer",
    "nan_coordinate", "zero_thickness", "missing_tool", "bad_diameter", "boolean_coordinate", "string_plated",
    "same_layer", "duplicate_tool", "self_crossing_outline", "repeated_vertex"])
def test_manufacturing_defects_are_rejected_before_writing_files(change):
    m = valid_model()
    if change == "dielectric_via_end": m.vias[0] = replace(m.vias[0], end_layer="D1")
    elif change == "unknown_polygon_layer": m.polygons[0] = replace(m.polygons[0], layer="missing")
    elif change == "invalid_polarity": m.polygons[0] = replace(m.polygons[0], polarity="erase")
    elif change == "duplicate_layer": m.layers.append(m.layers[0])
    elif change == "nan_coordinate": m.polygons[0].points[0][0] = float("nan")
    elif change == "zero_thickness": m.layers[0] = replace(m.layers[0], thickness=0)
    elif change == "missing_tool": m.drill_tools = []
    elif change == "bad_diameter": m.vias[0] = replace(m.vias[0], drill=-0.2)
    elif change == "boolean_coordinate": m.vias[0] = replace(m.vias[0], x=True)
    elif change == "string_plated": m.vias[0] = replace(m.vias[0], plated="false")
    elif change == "same_layer": m.vias[0] = replace(m.vias[0], end_layer="TOP")
    elif change == "duplicate_tool": m.drill_tools.append(DrillTool("T01", 0.3))
    elif change == "self_crossing_outline": m.board_outline.points[:] = [[0, 0], [2, 2], [0, 2], [2, 0]]
    elif change == "repeated_vertex": m.polygons[0].points.insert(1, [0, 0])
    assert m.validate()


def test_fab_model_serializes_core_fields():
    model = FabModel(
        source_project="hfss/board_fixture.aedt",
        source_design="final",
        unit="mm",
        layers=[Layer(name="L1_TOP", kind="copper", z=0.127, thickness=0.018)],
        polygons=[
            Polygon(
                layer="L1_TOP",
                points=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                source_objects=["patch"],
            )
        ],
        vias=[Via(x=0.5, y=0.5, drill=0.2, start_layer="L1_TOP", end_layer="L2_BOTTOM", source_object="via_1")],
        drill_tools=[DrillTool(code="T01", diameter=0.2)],
        board_outline=BoardOutline(points=[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]]),
    )

    payload = model.to_dict()

    assert payload["schema_version"] == "hfss-fab-1"
    assert payload["source_design"] == "final"
    assert payload["layers"][0]["name"] == "L1_TOP"
    assert payload["polygons"][0]["source_objects"] == ["patch"]
    assert payload["vias"][0]["drill"] == 0.2
    assert payload["board_outline"]["points"][2] == [2.0, 2.0]


def test_fab_model_validates_required_outputs():
    model = FabModel(source_project="p.aedt", source_design="final")

    errors = model.validate()

    assert "no copper layers" in errors
    assert "no board outline" in errors
