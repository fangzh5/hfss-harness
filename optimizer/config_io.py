"""Config loading and snapshot helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .path_utils import resolve_config_path
except ImportError:  # pragma: no cover
    from path_utils import resolve_config_path


def load_config(config_path: str | Path, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Load a JSON config file."""
    resolved = resolve_config_path(str(config_path), base_dir)
    with open(resolved, "r", encoding="utf-8") as fp:
        return json.load(fp)


def save_config_snapshot(output_dir: str | Path, config: dict[str, Any]) -> Path:
    """Write a config snapshot into the task output directory."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path
