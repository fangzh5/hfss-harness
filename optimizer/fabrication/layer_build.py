from __future__ import annotations


COPPER_TOKENS = ("copper", "pec", "perfect conductor")
DIELECTRIC_TOKENS = ("rogers", "duroid", "fr4", "dielectric", "substrate", "pp", "prepreg", "mmwave")
EXCLUDE_TOKENS = ("air", "vacuum", "pec_boundary", "radiation")


def classify_material(material: str | None) -> str:
    text = (material or "").strip().lower()
    if not text:
        return "unknown"
    if any(token in text for token in EXCLUDE_TOKENS):
        return "exclude"
    if any(token in text for token in COPPER_TOKENS):
        return "copper"
    if any(token in text for token in DIELECTRIC_TOKENS):
        return "dielectric"
    return "unknown"


def cluster_z_levels(values: list[float], tolerance: float = 0.005) -> list[float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if abs(value - groups[-1][-1]) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def copper_layer_name(index: int, total: int) -> str:
    if index == 0:
        suffix = "TOP"
    elif index == total - 1:
        suffix = "BOTTOM"
    else:
        suffix = "INNER"
    return f"L{index + 1}_{suffix}"
