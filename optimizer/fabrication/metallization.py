"""Resolve explicit via annotations before the copper/PEC fabrication default."""


def resolve_via_metallization(material: str, *, explicit: bool | None = None) -> bool:
    """Use only for objects already classified as vias, not arbitrary metal.

    The model diameter is the drill diameter. A True result describes the
    metallized drill operation; it does not imply a plating thickness or pad.
    Unknown materials require an explicit annotation rather than being lost.
    """
    if explicit is not None:
        if type(explicit) is not bool:
            raise ValueError("Via metallization annotation must be a boolean")
        return explicit
    if isinstance(material, str) and material.strip().strip('"').lower() in ("copper", "pec"):
        return True
    raise ValueError("Via material needs an explicit metallization annotation")
