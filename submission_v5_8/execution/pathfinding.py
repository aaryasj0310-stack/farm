"""BFS pathfinding on the 10x10 farm grid.

LOCKED tiles are fully PASSABLE traversal nodes (mechanic: movement onto
locked tiles is allowed; only tile OPERATIONS no-op there). The shed is
reachable from all four center tiles regardless of lock status.
"""
from collections import deque

MOVES = [("NORTH", (0, -1)), ("SOUTH", (0, 1)),
         ("EAST", (1, 0)), ("WEST", (-1, 0))]


def neighbors(pos, board=10):
    x, y = pos
    for name, (dx, dy) in MOVES:
        nx, ny = x + dx, y + dy
        if 0 <= nx < board and 0 <= ny < board:
            yield name, (nx, ny)


def bfs_first_step(start, goal, board=10):
    """First move direction on a shortest path start->goal.

    Grid topology is uniform (all tiles passable), so BFS is overkill but
    kept per architecture; returns None when already at goal.
    """
    if tuple(start) == tuple(goal):
        return None
    prev = {tuple(start): None}
    q = deque([tuple(start)])
    while q:
        cur = q.popleft()
        if cur == tuple(goal):
            break
        for name, nxt in neighbors(cur, board):
            if nxt not in prev:
                prev[nxt] = (cur, name)
                q.append(nxt)
    if tuple(goal) not in prev:
        return None
    # walk back to the edge right after start
    cur = tuple(goal)
    while prev[cur][0] != tuple(start):
        cur = prev[cur][0]
    return prev[cur][1]


def path_length(start, goal, board=10):
    sx, sy = start
    gx, gy = goal
    return abs(sx - gx) + abs(sy - gy)


def nearest_pos(units_positions, targets):
    """Greedy assignment helper: for each target, the closest unit index."""
    out = {}
    remaining = list(range(len(units_positions)))
    for target in sorted(targets, key=lambda t: min(
            path_length(units_positions[i], t) for i in remaining)):
        i = min(remaining, key=lambda i: path_length(units_positions[i], target))
        out[target] = i
        remaining.remove(i)
    return out
