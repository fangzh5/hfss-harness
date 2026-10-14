from __future__ import annotations

from pathlib import Path

from .model import Layer


def write_stackup(output_path: str | Path, layers: list[Layer], total_thickness: float | None = None) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PCB 叠层说明",
        "",
        "| 层名 | 类型 | 材料 | Z(mm) | 厚度(mm) |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for layer in layers:
        material = layer.material or ""
        thickness = "" if layer.thickness is None else f"{layer.thickness:g}"
        lines.append(f"| {layer.name} | {layer.kind} | {material} | {layer.z:g} | {thickness} |")
    lines.append("")
    if total_thickness is not None:
        lines.append(f"总厚度：{total_thickness:g} mm")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
