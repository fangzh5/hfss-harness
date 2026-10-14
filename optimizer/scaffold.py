"""Copy bundled templates, workflow skills and the example into a new workspace."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

PUBLIC_SKILLS = ("hh-sim", "hh-via", "hh-export-pcb", "hh-rebuild-pcb", "hh-iter")
CONFIGS = ("template_opt.json", "template_sweep.json", "template_val.json", "template_bo.json",
           "template_cmaes.json", "example_patch_opt.json")
DOCS = ("agent-reference.md", "via-planning.md", "via-creation.md", "pcb-stackup.md", "migration-0.2.0.md")


def scaffold(destination, *, _resource_root=None):
    bundled = Path(__file__).parent / "_resources"
    source = Path(_resource_root) if _resource_root is not None else (
        bundled if bundled.is_dir() else Path(__file__).resolve().parents[1])
    destination = Path(destination).resolve()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Destination must be a directory")
    names = [Path("AGENT.md"), Path("hfss/patch.aedt")]
    names += [Path("scripts/create_vias_safely.py")]
    names += [Path("configs") / name for name in CONFIGS]
    names += [Path("docs") / name for name in DOCS]
    for skill in PUBLIC_SKILLS:
        folder = source / ".agents/skills" / skill
        if not folder.is_dir():
            raise ValueError("Bundled workflow resource is missing: " + skill)
        names += [p.relative_to(source) for p in sorted(folder.rglob("*")) if p.is_file()]
    if any(not (source / name).is_file() for name in names):
        raise ValueError("Bundled template, document or example is missing")
    collisions = [name.as_posix() for name in names if (destination / name).exists()]
    if collisions:
        raise ValueError("Refusing to overwrite workspace files: " + ", ".join(collisions))
    # Check all input resources and collisions before creating any output.
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            with (source / name).open("rb") as resource:
                shutil.copyfileobj(resource, stream)
    return len(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    args = parser.parse_args(argv)
    try:
        count = scaffold(args.destination)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Created {count} workspace files in {Path(args.destination).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
