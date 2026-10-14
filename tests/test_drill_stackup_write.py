from optimizer.fabrication.drill_write import write_excellon
from optimizer.fabrication.model import DrillTool, Layer, Via
from optimizer.fabrication.stackup_write import write_stackup


def test_write_excellon_outputs_tools_and_hits(tmp_path):
    output = tmp_path / "plated_through.drl"
    vias = [Via(x=1.0, y=2.0, drill=0.2, start_layer="L1_TOP", end_layer="L2_BOTTOM", source_object="via_1")]
    tools = [DrillTool(code="T01", diameter=0.2)]

    write_excellon(output, vias, tools)

    text = output.read_text(encoding="utf-8")
    assert "METRIC,TZ" in text
    assert ";FILE_FORMAT=3:3" in text
    assert "M71" in text
    assert "T01C0.200" in text
    assert "X001000Y002000" in text


def test_write_stackup_outputs_layer_table(tmp_path):
    output = tmp_path / "stackup.md"
    layers = [
        Layer(name="L1_TOP", kind="copper", z=0.127, thickness=0.018, material="copper"),
        Layer(name="D1", kind="dielectric", z=0.0635, thickness=0.127, material="Rogers"),
        Layer(name="L2_BOTTOM", kind="copper", z=0.0, thickness=0.018, material="copper"),
    ]

    write_stackup(output, layers, total_thickness=0.127)

    text = output.read_text(encoding="utf-8")
    assert "# PCB 叠层说明" in text
    assert "| L1_TOP | copper | copper | 0.127 | 0.018 |" in text
    assert "总厚度" in text
