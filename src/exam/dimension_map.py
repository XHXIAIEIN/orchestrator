"""Dimension → Department/Division routing table for Clawvard exam."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _find_repo_root() -> Optional[Path]:
    """Walk up from this file until we find a directory containing both
    'departments/' and 'src/' subdirectories."""
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        if (candidate / "departments").is_dir() and (candidate / "src").is_dir():
            return candidate
    return None


@dataclass(frozen=True)
class DimensionRoute:
    dimension: str
    department: str
    division: str


def load_dimension_map(path: Path | str) -> dict[str, DimensionRoute]:
    """Load dimension routing table from YAML file.

    Returns:
        dict mapping dimension name → DimensionRoute
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    dimensions: dict[str, dict] = data.get("dimensions", {})
    result: dict[str, DimensionRoute] = {}
    for dim_name, routing in dimensions.items():
        result[dim_name] = DimensionRoute(
            dimension=dim_name,
            department=routing["department"],
            division=routing["division"],
        )
    return result


# --- Module-level singleton ---

_repo_root = _find_repo_root()
_DEFAULT_YAML = (
    _repo_root / "departments" / "shared" / "exam" / "dimension_map.yaml"
    if _repo_root is not None
    else None
)

DIMENSION_MAP: dict[str, DimensionRoute] = {}

if _DEFAULT_YAML is not None and _DEFAULT_YAML.exists():
    try:
        DIMENSION_MAP = load_dimension_map(_DEFAULT_YAML)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load dimension_map.yaml: %s", exc)
else:
    logger.warning(
        "dimension_map.yaml not found (repo_root=%s); DIMENSION_MAP will be empty",
        _repo_root,
    )


def get_route(dimension: str) -> Optional[DimensionRoute]:
    """Return the DimensionRoute for *dimension*, or None if unknown."""
    return DIMENSION_MAP.get(dimension)


def get_all_dimensions() -> list[str]:
    """Return all known dimension names."""
    return list(DIMENSION_MAP.keys())
