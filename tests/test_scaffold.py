from pathlib import Path

import pytest

from optimizer.scaffold import CONFIGS, DOCS, PUBLIC_SKILLS, scaffold


def resources(root):
    files = ["AGENT.md", "hfss/patch.aedt", "scripts/create_vias_safely.py"]
    files += ["configs/"+n for n in CONFIGS] + ["docs/"+n for n in DOCS]
    files += [".agents/skills/"+n+"/SKILL.md" for n in PUBLIC_SKILLS]
    for name in files:
        p = root/name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(b"resource bytes")
    return files


def test_scaffold_copies_only_public_workflow_assets(tmp_path):
    source, destination = tmp_path/"resources", tmp_path/"workspace"
    files = resources(source)
    private = source/".agents/skills/hh-git/SKILL.md"
    private.parent.mkdir(parents=True)
    private.write_text("private")
    assert scaffold(destination,_resource_root=source) == len(files)
    assert all((destination/name).read_bytes()==b"resource bytes" for name in files)
    assert not (destination/".agents/skills/hh-git").exists()


def test_existing_file_rejected_before_any_partial_output(tmp_path):
    source, destination = tmp_path/"resources", tmp_path/"workspace"
    resources(source)
    existing = destination/"configs/template_val.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("user config")
    with pytest.raises(ValueError,match="overwrite"):
        scaffold(destination,_resource_root=source)
    assert existing.read_text()=="user config" and not (destination/"AGENT.md").exists()


def test_missing_bundle_rejected_before_creating_workspace(tmp_path):
    source, destination = tmp_path/"resources", tmp_path/"workspace"
    resources(source)
    (source/"hfss/patch.aedt").unlink()
    with pytest.raises(ValueError,match="missing"):
        scaffold(destination,_resource_root=source)
    assert not destination.exists()
