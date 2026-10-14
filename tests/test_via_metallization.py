import pytest
from optimizer.fabrication.metallization import resolve_via_metallization


@pytest.mark.parametrize("material", ["copper", "PEC", ' "Copper" '])
def test_copper_and_pec_vias_default_to_metallized_drill(material):
    assert resolve_via_metallization(material) is True


def test_explicit_annotation_overrides_material_default():
    assert resolve_via_metallization("copper", explicit=False) is False
    assert resolve_via_metallization("brass", explicit=True) is True
    with pytest.raises(ValueError, match="boolean"):
        resolve_via_metallization("PEC", explicit="false")


def test_unrecognized_via_material_is_not_silently_classified():
    with pytest.raises(ValueError, match="explicit"):
        resolve_via_metallization("vacuum")
