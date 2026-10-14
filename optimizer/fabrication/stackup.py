"""Versioned, dependency-free layer/material intake; unknown values stay unknown."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .validation import finite_number

STACKUP_SCHEMA = "hfss-stackup-2"
Z_TOLERANCE_MM = 1e-8


def strict_fields(data, allowed, *, context):
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be an object")
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {context} fields: {sorted(unknown)}")
    return data


def package_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    parts = value.split("/")
    return not value.startswith("/") and all(p not in ("", ".", "..") for p in parts)


@dataclass(frozen=True)
class MaterialSpec:
    id: str
    kind: str
    name: str | None = None
    permittivity: float | None = None
    loss_tangent: float | None = None
    conductivity_s_per_m: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class LayerSpec:
    name: str
    kind: str
    material_id: str
    z_bottom_mm: float | None = None
    z_top_mm: float | None = None
    copper_file: str | None = None
    thickness_basis: str | None = None
    source: str | None = None

    @property
    def thickness_mm(self):
        if not all(finite_number(v) for v in (self.z_bottom_mm, self.z_top_mm)):
            return None
        return self.z_top_mm - self.z_bottom_mm


@dataclass(frozen=True)
class DrillSpec:
    id: str
    start_layer: str
    end_layer: str
    file: str | None = None
    metallized: bool | None = None
    source: str | None = None


@dataclass(frozen=True)
class InputCheck:
    errors: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def ready(self):
        return not self.errors and not self.missing

    def require_ready(self):
        if self.errors:
            raise ValueError("Invalid fabrication inputs: " + "; ".join(self.errors))
        if self.missing:
            raise MissingInputsError(self.missing)


class MissingInputsError(ValueError):
    def __init__(self, fields):
        self.fields = tuple(fields)
        super().__init__("User input required: " + "; ".join(self.fields))


@dataclass(frozen=True)
class LayerStack:
    layers: tuple[LayerSpec, ...]
    materials: tuple[MaterialSpec, ...]
    drill_operations: tuple[DrillSpec, ...] = ()
    profile_file: str | None = None
    coordinate_datum: str | None = None
    schema_version: str = STACKUP_SCHEMA
    unit: str = "mm"
    notes: tuple[str, ...] = ()

    def check(self, mode="fabrication", *, require_cam_files=False):
        if mode not in ("fabrication", "rebuild"):
            raise ValueError("Mode must be fabrication or rebuild")
        errors, missing = [], []
        if self.schema_version != STACKUP_SCHEMA:
            errors.append("unsupported stackup schema")
        if self.unit != "mm":
            errors.append("stackup coordinates must explicitly use mm")
        if not isinstance(self.coordinate_datum, str) or not self.coordinate_datum.strip():
            missing.append("coordinate_datum")
        materials = {}
        for material in self.materials:
            if not isinstance(material.id, str) or not material.id.strip() or material.id in materials:
                errors.append("empty or duplicate material id")
                continue
            materials[material.id] = material
            if material.kind not in ("metal", "dielectric"):
                errors.append(f"materials.{material.id}.kind")
            for prop, positive in (("permittivity", True), ("loss_tangent", False), ("conductivity_s_per_m", True)):
                value = getattr(material, prop)
                if value is not None and (not finite_number(value, positive=positive) or value < 0):
                    errors.append(f"materials.{material.id}.{prop} must be finite and {'positive' if positive else 'nonnegative'}")
        layers, previous = {}, None
        used_materials = set()
        copper_files = set()
        for layer in self.layers:
            key = f"layers.{layer.name}"
            if not isinstance(layer.name, str) or not layer.name.strip() or layer.name in layers:
                errors.append("empty or duplicate layer name")
                continue
            layers[layer.name] = layer
            if layer.kind not in ("copper", "dielectric"):
                errors.append(key + ".kind")
            material = materials.get(layer.material_id) if isinstance(layer.material_id, str) else None
            if material is None:
                errors.append(key + ".material_id references an unknown material")
            else:
                used_materials.add(material.id)
                expected = "metal" if layer.kind == "copper" else "dielectric"
                if material.kind != expected:
                    errors.append(key + ".material_id has the wrong material kind")
            for prop in ("z_bottom_mm", "z_top_mm"):
                value = getattr(layer, prop)
                if value is None:
                    missing.append(key + "." + prop)
                elif not finite_number(value):
                    errors.append(key + "." + prop + " must be finite")
            thickness = layer.thickness_mm
            if thickness is not None and not finite_number(thickness, positive=True):
                errors.append(key + " has nonpositive or unrepresentable thickness")
            if previous is not None and finite_number(previous.z_bottom_mm) and finite_number(layer.z_top_mm):
                delta = previous.z_bottom_mm - layer.z_top_mm
                if not math.isclose(delta, 0.0, abs_tol=Z_TOLERANCE_MM):
                    errors.append(key + " is out of top-to-bottom order, overlaps or leaves an undeclared gap")
            previous = layer
            if layer.kind == "copper":
                if layer.thickness_basis is None:
                    missing.append(key + ".thickness_basis")
                elif layer.thickness_basis not in ("modeled", "base", "finished"):
                    errors.append(key + ".thickness_basis")
                if require_cam_files and layer.copper_file is None:
                    missing.append(key + ".copper_file")
                if layer.copper_file is not None:
                    if not package_path(layer.copper_file) or layer.copper_file in copper_files:
                        errors.append(key + ".copper_file must be a unique relative package path")
                    if package_path(layer.copper_file):
                        copper_files.add(layer.copper_file)
            elif layer.copper_file is not None:
                errors.append(key + ".copper_file cannot be assigned to a dielectric")
        if not any(layer.kind == "copper" for layer in self.layers):
            errors.append("no copper layers")
        for material_id in sorted(used_materials):
            material = materials[material_id]
            if not isinstance(material.name, str) or not material.name.strip():
                missing.append(f"materials.{material_id}.name")
            if not isinstance(material.source, str) or not material.source.strip():
                missing.append(f"materials.{material_id}.source")
            if mode == "rebuild" and material.kind == "dielectric":
                for prop in ("permittivity", "loss_tangent"):
                    if getattr(material, prop) is None:
                        missing.append(f"materials.{material_id}.{prop}")
        operation_ids, drill_files = set(), set()
        for operation in self.drill_operations:
            key = f"drill_operations.{operation.id}"
            if not isinstance(operation.id, str) or not operation.id.strip() or operation.id in operation_ids:
                errors.append("empty or duplicate drill operation id")
                continue
            operation_ids.add(operation.id)
            pair = [layers.get(name) if isinstance(name, str) else None for name in (operation.start_layer, operation.end_layer)]
            if operation.start_layer == operation.end_layer or any(l is None or l.kind != "copper" for l in pair):
                errors.append(key + " needs two distinct copper layers")
            if operation.metallized is None:
                missing.append(key + ".metallized")
            elif type(operation.metallized) is not bool:
                errors.append(key + ".metallized must be boolean")
            if require_cam_files and operation.file is None:
                missing.append(key + ".file")
            if operation.file is not None:
                if not package_path(operation.file) or operation.file in drill_files or operation.file in copper_files:
                    errors.append(key + ".file must be a unique relative package path")
                if package_path(operation.file):
                    drill_files.add(operation.file)
        if require_cam_files and self.profile_file is None:
            missing.append("profile_file")
        if self.profile_file is not None and (not package_path(self.profile_file) or self.profile_file in copper_files | drill_files):
            errors.append("profile_file must be a distinct relative package path")
        return InputCheck(tuple(errors), tuple(missing))

    def to_dict(self):
        data = asdict(self)
        for key in ("layers", "materials", "drill_operations", "notes"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data):
        strict_fields(data, cls.__dataclass_fields__, context="stackup")
        if data.get("schema_version") != STACKUP_SCHEMA or data.get("unit") != "mm":
            raise ValueError("Explicit hfss-stackup-2 schema and mm units required")
        result = dict(data)
        for key, factory in (("layers", LayerSpec), ("materials", MaterialSpec), ("drill_operations", DrillSpec)):
            entries = result.get(key, [])
            if not isinstance(entries, list):
                raise ValueError(f"{key} must be an array")
            try:
                result[key] = tuple(factory(**strict_fields(item, factory.__dataclass_fields__, context=key)) for item in entries)
            except TypeError as exc:
                raise ValueError(f"Missing or invalid {key} identity fields") from exc
        notes = result.get("notes", [])
        if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
            raise ValueError("notes must be an array of strings")
        result["notes"] = tuple(notes)
        stack = cls(**result)
        check = stack.check()
        if check.errors:
            raise ValueError("Invalid stackup: " + "; ".join(check.errors))
        return stack


def load_stackup(path):
    return LayerStack.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def stackup_markdown(stack):
    check = stack.check()
    if check.errors:
        raise ValueError("Invalid stackup: " + "; ".join(check.errors))
    materials = {m.id: m for m in stack.materials}
    def cell(value):
        text = "待确认" if value is None else str(value)
        return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    lines = ["# PCB叠层", "", f"坐标基准：{cell(stack.coordinate_datum)}；单位：mm。按顶到底排序。", "",
             "| 层 | 类型 | Z底 | Z顶 | 厚度 | 材料 | Dk | Df | 铜厚依据 |",
             "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |"]
    for layer in stack.layers:
        material = materials[layer.material_id]
        values = (layer.name, layer.kind, layer.z_bottom_mm, layer.z_top_mm, layer.thickness_mm, material.name,
                  material.permittivity, material.loss_tangent, layer.thickness_basis if layer.kind == "copper" else "—")
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    if stack.layers and all(l.thickness_mm is not None for l in stack.layers):
        lines += ["", f"总厚度：{sum(l.thickness_mm for l in stack.layers):.12g} mm"]
    lines += ["", "材料来源："] + [f"- {cell(m.id)}：{cell(m.source)}" for m in stack.materials]
    lines += ["", "钻孔作业："] + [f"- {cell(o.id)}：{cell(o.start_layer)}→{cell(o.end_layer)}；金属化={cell(o.metallized)}；文件={cell(o.file)}" for o in stack.drill_operations]
    missing = stack.check("rebuild", require_cam_files=True).missing
    if missing:
        lines += ["", "重建前待补充："] + ["- " + cell(p) for p in missing]
    lines += ["", "说明："] + ["- " + cell(note) for note in stack.notes]
    return "\n".join(lines) + "\n"


def write_stackup_bundle(directory, stack):
    """Create a new output directory; JSON and Markdown share one resolved stack."""
    check = stack.check()
    if check.errors:
        raise ValueError("Invalid stackup: " + "; ".join(check.errors))
    data = json.dumps(stack.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    markdown = stackup_markdown(stack)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / "stackup.json").open("x", encoding="utf-8") as stream:
        stream.write(data)
    (directory / "docs").mkdir()
    with (directory / "docs/stackup.md").open("x", encoding="utf-8") as stream:
        stream.write(markdown)
    loaded = load_stackup(directory / "stackup.json")
    if loaded != stack:
        raise RuntimeError("Written stackup readback differs from resolved inputs")
    return {"fabrication": stack.check(require_cam_files=True), "rebuild": stack.check("rebuild", require_cam_files=True)}
