from optimizer.fabrication.layer_build import (
    classify_material,
    cluster_z_levels,
    copper_layer_name,
)


def test_classify_material_detects_manufacturing_roles():
    assert classify_material("copper") == "copper"
    assert classify_material("pec") == "copper"
    assert classify_material("Rogers RT/duroid 5880") == "dielectric"
    assert classify_material("mmwave g") == "dielectric"
    assert classify_material("vacuum") == "exclude"
    assert classify_material("air") == "exclude"
    assert classify_material("mystery") == "unknown"


def test_cluster_z_levels_groups_close_values():
    clusters = cluster_z_levels([0.0, 0.002, 0.127, 0.128, 0.254], tolerance=0.005)

    assert clusters == [0.001, 0.1275, 0.254]


def test_copper_layer_name_uses_order_and_side_labels():
    assert copper_layer_name(0, 3) == "L1_TOP"
    assert copper_layer_name(1, 3) == "L2_INNER"
    assert copper_layer_name(2, 3) == "L3_BOTTOM"
