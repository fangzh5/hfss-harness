from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .model import FabModel


def package_manifest(model: FabModel) -> dict:
    return {
        "schema_version": model.schema_version,
        "source_project": model.source_project,
        "source_design": model.source_design,
        "unit": model.unit,
        "layer_count": len(model.layers),
        "polygon_count": len(model.polygons),
        "via_count": len(model.vias),
        "warning_count": len(model.warnings),
    }


def write_preview(output_path: str | Path, model: FabModel) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    labelled_layers: set[str] = set()
    for polygon in model.polygons:
        if len(polygon.points) < 3:
            continue
        xs = [point[0] for point in polygon.points] + [polygon.points[0][0]]
        ys = [point[1] for point in polygon.points] + [polygon.points[0][1]]
        label = polygon.layer if polygon.layer not in labelled_layers else None
        ax.plot(xs, ys, linewidth=1.2, linestyle="--" if polygon.polarity == "clear" else "-", label=label)
        labelled_layers.add(polygon.layer)
    for via in model.vias:
        ax.scatter([via.x], [via.y], s=16, color="black")
    if model.board_outline:
        pts = model.board_outline.points
        xs = [point[0] for point in pts] + [pts[0][0]]
        ys = [point[1] for point in pts] + [pts[0][1]]
        ax.plot(xs, ys, color="red", linewidth=1.5)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.25)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
