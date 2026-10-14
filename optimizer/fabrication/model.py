from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .validation import contour_errors, finite_number


SCHEMA_VERSION = "hfss-fab-1"


@dataclass(frozen=True)
class Layer:
    name: str
    kind: str
    z: float
    thickness: float | None = None
    material: str | None = None


@dataclass(frozen=True)
class Polygon:
    layer: str
    points: list[list[float]]
    source_objects: list[str] = field(default_factory=list)
    polarity: str = "dark"


@dataclass(frozen=True)
class Via:
    x: float
    y: float
    drill: float
    start_layer: str
    end_layer: str
    source_object: str
    plated: bool = True


@dataclass(frozen=True)
class DrillTool:
    code: str
    diameter: float


@dataclass(frozen=True)
class BoardOutline:
    points: list[list[float]]
    source_object: str | None = None


@dataclass
class FabModel:
    source_project: str
    source_design: str
    unit: str = "mm"
    schema_version: str = SCHEMA_VERSION
    layers: list[Layer] = field(default_factory=list)
    polygons: list[Polygon] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    drill_tools: list[DrillTool] = field(default_factory=list)
    board_outline: BoardOutline | None = None
    excluded_objects: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not any(layer.kind == "copper" for layer in self.layers):
            errors.append("no copper layers")
        if self.board_outline is None:
            errors.append("no board outline")
        if self.unit != "mm":
            errors.append(f"unsupported unit: {self.unit}")
        if self.schema_version != SCHEMA_VERSION:
            errors.append(f"unsupported schema: {self.schema_version}")
        layers = {}
        for layer in self.layers:
            if not isinstance(layer.name, str) or not layer.name.strip() or layer.name in layers:
                errors.append(f"empty or duplicate layer name: {layer.name}")
            layers[layer.name] = layer
            if layer.kind not in ("copper", "dielectric"):
                errors.append(f"unknown layer kind: {layer.name}: {layer.kind}")
            if not finite_number(layer.z) or not finite_number(layer.thickness, positive=True):
                errors.append(f"invalid layer z/thickness: {layer.name}")
            elif not all(finite_number(v) for v in (layer.z - layer.thickness / 2, layer.z + layer.thickness / 2)):
                errors.append(f"nonfinite layer extent: {layer.name}")
        if self.board_outline is not None:
            errors.extend("board outline: " + issue for issue in contour_errors(self.board_outline.points))
        for index, polygon in enumerate(self.polygons):
            layer = layers.get(polygon.layer)
            if layer is None or layer.kind != "copper":
                errors.append(f"polygon {index} references an unknown or non-copper layer: {polygon.layer}")
            if polygon.polarity not in ("dark", "clear"):
                errors.append(f"polygon {index} has invalid polarity: {polygon.polarity}")
            errors.extend(f"polygon {index}: " + issue for issue in contour_errors(polygon.points))
        tools = {}
        for tool in self.drill_tools:
            if tool.code in tools or not isinstance(tool.code, str) or not tool.code.startswith("T") or not tool.code[1:].isdigit():
                errors.append(f"invalid or duplicate drill tool code: {tool.code}")
            tools[tool.code] = tool
            if not finite_number(tool.diameter, positive=True):
                errors.append(f"invalid drill tool diameter: {tool.code}")
        for index, via in enumerate(self.vias):
            if not all(finite_number(v) for v in (via.x, via.y)) or not finite_number(via.drill, positive=True):
                errors.append(f"via {index} has invalid coordinates/diameter")
            if type(via.plated) is not bool:
                errors.append(f"via {index} plated must be a boolean")
            pair = [layers.get(name) for name in (via.start_layer, via.end_layer)]
            if any(layer is None or layer.kind != "copper" for layer in pair) or via.start_layer == via.end_layer:
                errors.append(f"via {index} needs two distinct known copper layers: {via.start_layer}->{via.end_layer}")
            elif finite_number(pair[0].z) and finite_number(pair[1].z) and pair[0].z == pair[1].z:
                errors.append(f"via {index} copper layers have zero vertical span")
            if finite_number(via.drill, positive=True) and not any(finite_number(tool.diameter, positive=True)
                    and abs(via.drill - tool.diameter) <= 1e-6 for tool in self.drill_tools):
                errors.append(f"via {index} has no matching drill tool")
        return errors
