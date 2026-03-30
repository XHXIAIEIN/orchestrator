"""Tests for src/exam/dimension_map.py"""

import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.exam.dimension_map import DimensionRoute, load_dimension_map


# ---------------------------------------------------------------------------
# test_load_returns_correct_routes
# ---------------------------------------------------------------------------

_SMALL_YAML = textwrap.dedent("""\
    dimensions:
      execution:
        department: engineering
        division: implement
      reflection:
        department: quality
        division: review
""")


def test_load_returns_correct_routes(tmp_path: Path) -> None:
    yaml_file = tmp_path / "dimension_map.yaml"
    yaml_file.write_text(_SMALL_YAML, encoding="utf-8")

    routes = load_dimension_map(yaml_file)

    assert set(routes.keys()) == {"execution", "reflection"}

    exec_route = routes["execution"]
    assert exec_route.dimension == "execution"
    assert exec_route.department == "engineering"
    assert exec_route.division == "implement"

    refl_route = routes["reflection"]
    assert refl_route.dimension == "reflection"
    assert refl_route.department == "quality"
    assert refl_route.division == "review"


# ---------------------------------------------------------------------------
# test_route_is_frozen
# ---------------------------------------------------------------------------


def test_route_is_frozen() -> None:
    route = DimensionRoute(dimension="eq", department="protocol", division="communicate")
    with pytest.raises(FrozenInstanceError):
        route.department = "something_else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# test_all_8_dimensions_in_real_file  (integration)
# ---------------------------------------------------------------------------

_EXPECTED_DIMENSIONS = {
    "execution",
    "tooling",
    "retrieval",
    "reflection",
    "understanding",
    "eq",
    "reasoning",
    "memory",
}


def test_all_8_dimensions_in_real_file() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    real_yaml = repo_root / "departments" / "shared" / "exam" / "dimension_map.yaml"

    assert real_yaml.exists(), f"dimension_map.yaml not found at {real_yaml}"

    routes = load_dimension_map(real_yaml)
    assert set(routes.keys()) == _EXPECTED_DIMENSIONS, (
        f"Missing dimensions: {_EXPECTED_DIMENSIONS - set(routes.keys())}"
    )

    # Spot-check a few routes
    assert routes["execution"].department == "engineering"
    assert routes["memory"].division == "recall"
    assert routes["eq"].department == "protocol"
