from __future__ import annotations

from pathlib import Path

from .model import DrillTool, Via


def format_metric_33(value: float) -> str:
    return f"{int(round(float(value) * 1000)):06d}"


def write_excellon(output_path: str | Path, vias: list[Via], tools: list[DrillTool]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["M48", "METRIC,TZ", ";FILE_FORMAT=3:3"]
    for tool in tools:
        lines.append(f"{tool.code}C{tool.diameter:.3f}")
    lines.extend(["%", "M71", "G90", "G05"])
    for tool in tools:
        hits = [via for via in vias if abs(via.drill - tool.diameter) <= 1e-6]
        if not hits:
            continue
        lines.append(tool.code)
        for via in hits:
            lines.append(f"X{format_metric_33(via.x)}Y{format_metric_33(via.y)}")
    lines.append("M30")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
