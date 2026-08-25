"""Observation and grid tile accessors."""
from typing import Any, Dict


def tile_at(farm: Dict[str, Any], position: Any) -> Any:
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return "OUT_OF_BOUNDS"
    x, y = map(int, position)
    tiles = farm.get("tiles", []) or []
    if not (0 <= y < len(tiles) and 0 <= x < len(tiles[y])):
        return "OUT_OF_BOUNDS"
    return tiles[y][x]
