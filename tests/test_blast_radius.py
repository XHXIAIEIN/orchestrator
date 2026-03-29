import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import pytest


def load_manifest(dept):
    manifest_path = Path(__file__).parent.parent / "departments" / dept / "manifest.yaml"
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("dept", [
    "engineering", "operations", "quality", "personnel", "security", "protocol"
])
def test_manifest_has_blast_radius(dept):
    manifest = load_manifest(dept)
    assert "blast_radius" in manifest, f"{dept} manifest missing blast_radius"
    br = manifest["blast_radius"]
    assert "max_files_per_run" in br
    assert isinstance(br["max_files_per_run"], int)
    assert br["max_files_per_run"] > 0


@pytest.mark.parametrize("dept,expected_max", [
    ("engineering", 15),
    ("operations", 8),
    ("quality", 5),
    ("personnel", 5),
    ("security", 8),
    ("protocol", 5),
])
def test_blast_radius_values(dept, expected_max):
    manifest = load_manifest(dept)
    br = manifest["blast_radius"]
    assert br["max_files_per_run"] == expected_max


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "src" / "governance" / "audit" / "learnings.py").exists(),
    reason="check_blast_radius not yet implemented in learnings.py"
)
def test_blast_radius_check_function():
    from src.governance.audit.learnings import check_blast_radius
    assert check_blast_radius(5, 10) is True
    assert check_blast_radius(10, 10) is True
    assert check_blast_radius(11, 10) is False
