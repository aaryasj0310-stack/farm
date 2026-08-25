"""Unit action emission."""
from .pathfinding import bfs_first_step


def step_toward(unit_pos, target_pos, board=10):
    return bfs_first_step(tuple(unit_pos), tuple(target_pos), board)


def emit_action(task, ctx):
    op = task["op"]
    target = task.get("target")
    args = task.get("args", [])
    pos = tuple(task["unit_pos"])
    board = 10

    if target is not None and pos != tuple(target):
        move = step_toward(pos, target, board)
        if move is not None:
            return [move]

    if op in ("NORTH", "SOUTH", "EAST", "WEST", "PASS"):
        return [op]
    if op == "PICKUP":
        return ["PICKUP", *args]
    if op == "PLACE":
        return ["PLACE", *args]
    return [op] if not args else [op, *args]


def reroute_to_shed_access(unit_pos):
    best = None
    best_d = 10 ** 9
    for tile in [(4, 4), (5, 4), (4, 5), (5, 5)]:
        d = abs(tile[0] - unit_pos[0]) + abs(tile[1] - unit_pos[1])
        if d < best_d:
            best_d = d
            best = tile
    return best
