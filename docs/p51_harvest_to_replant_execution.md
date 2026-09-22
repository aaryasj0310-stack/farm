# Kaggriculture P5.1 — Harvest-to-Replant Execution & Queue Protection

## The Same-Day Competition Vulnerability

In Kaggriculture, crop harvesting and planting operate within a continuous hourly loop:
1. When a worker completes a `HARVEST` action on Day $D+3$ at Hour $H$ (typically between Hours 7 and 16), the tile immediately changes to `kind = "EMPTY"`.
2. On step $H+1$, `MacroPlanner.build()` is invoked.
3. In baseline code, `MacroPlanner` queries all empty tiles on the farm (`empty_tiles = [t.pos for t in farm.iter_tiles() if t.kind == "EMPTY"...]`).
4. In late season (Days 21–25), `MacroPlanner` maintains an active wheat replanting target (e.g. 20 or 30 tiles). It pops empty tiles from `empty_tiles` and queues `(pos, "WHEAT")`.
5. In previous provisional replays, external treatment logic ran *after* `MacroPlanner.build()`. Seeing that the coordinate was already in `plan.plant_queue`, it refused to append CARROT. Workers consequently planted wheat on the newly harvested tile within 1–2 hours.

---

## P5.1 Architectural Queue Protection

Under `P51_T1_TWO_CYCLE_CARROT_ENABLED`, the queue generation in `MacroPlanner.build()` is modified to provide guaranteed coordinate isolation:

```python
# 1. Query reserved rotation coordinates
reserved_p51_tiles = rotation_mgr.get_active_rotation_tiles()

# 2. Suppress managed tiles from generic empty_tiles
# Generic wheat, strawberry, or melon logic can NEVER touch these coordinates
empty_tiles = [p for p in empty_tiles if p not in reserved_p51_tiles]

# 3. Dedicated Cycle 2 Replant Injection
replant_c2_tiles = rotation_mgr.get_c2_replant_tiles()
for pos in replant_c2_tiles:
    tx, ty = pos
    tile = farm.tiles[ty][tx]
    is_empty = (getattr(tile, "kind", "") == "EMPTY" or 
                (not getattr(tile, "is_plant", False) and not getattr(tile, "is_animal", False)))
    if is_empty and hour <= 17:
        plant_queue.append((pos, "CARROT"))
```

### Tri-Action Success Sequence on Day $D+3$:
1. **Hour $H_1$**: Worker harvests Cycle 1 carrot. Produce lands on worker; tile becomes empty.
2. **Hour $H_2$ ($H_2 \le 17$)**: `MacroPlanner` adds `(pos, "CARROT")` to `plant_queue`. `task_scheduler` checks seed inventory (guaranteed on hand via Hour 0 pre-order) and dispatches `PLANT(CARROT)`. Worker steps on tile and plants.
3. **Hour $H_3$ ($H_3 < 24$)**: In `task_scheduler.py`, `(t.planted_day == day)` evaluates to True. Tile is assigned `PRIORITY_URGENT_SURVIVAL` (100) for `WATER`. Worker waters the newly planted Cycle 2 carrot before midnight.

This ensures all three required operations—harvest C1, plant C2, and water C2—complete reliably on Day $D+3$.
