"""Unit action emission: movement queues + tile operations per unit.

Each unit (farmer idx 0, hands idx 1+) gets ONE list-action per turn:
either a move toward the task target or the tile/shed operation itself.
"""
from pathfinding import bfs_first_step


def step_toward(unit_pos, target_pos, board=10):
    return bfs_first_step(tuple(unit_pos), tuple(target_pos), board)


def emit_action(task, ctx):
    """Return the list-action for `task` given the assigned unit's position.

    Task shape: {"op": str, "target": (x,y) | None, "args": list}
    Ops with target=None execute immediately (should be none here).
    """
    op = task["op"]
    target = task.get("target")
    args = task.get("args", [])
    pos = tuple(task["unit_pos"])
    board = 10

    if target is not None and pos != tuple(target):
        move = step_toward(pos, target, board)
        if move is None:
            # unreachable/occupied edge: fall through to op attempt
            pass
        else:
            return [move]

    if op in ("NORTH", "SOUTH", "EAST", "WEST", "PASS"):
        return [op]
    if op == "PICKUP":
        return ["PICKUP", *args]
    if op == "PLACE":
        return ["PLACE", *args]
    return [op] if not args else [op, *args]


def needs_shed_adjacent(op):
    return op in ("PICKUP", "DROP") or (op == "PLACE_SHED")


def reroute_to_shed_access(unit_pos):
    """Closest shed-access tile for PICKUP/DROP staging."""
    best = None
    best_d = 10 ** 9
    for tile in [(4, 4), (5, 4), (4, 5), (5, 5)]:
        d = abs(tile[0] - unit_pos[0]) + abs(tile[1] - unit_pos[1])
        if d < best_d:
            best_d = d
            best = tile
    return best
