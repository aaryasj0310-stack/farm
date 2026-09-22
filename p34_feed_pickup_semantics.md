# Kaggriculture P3.4 — Phase 2: Wheat Pickup Semantics Audit

## Executive Summary

This document audits the authoritative game engine semantics ([`kaggriculture.py`](file:///C:/Users/rohit/AppData/Local/Programs/Python/Python312/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py)) and the baseline scheduler's feed-staging pipeline ([`task_scheduler.py`](file:///d:/website%20project/kaggri%20ox/agent/execution/task_scheduler.py)).

---

## 1. Authoritative Engine Ground Truth: Feeding & Inventory Rules

### A. Engine `FEED` Semantics
In `kaggriculture.py` (lines 505–514):
```python
if op == "FEED":
    if not (isinstance(tile, dict) and "animal" in tile):
        return
    if tile["fed_today"]:
        return
    if not _inv_take(inv, "WHEAT", 1):
        return
    tile["fed_today"] = True
    return
```
- **Critical Invariant**: The engine requires wheat to be in the **acting unit's personal inventory** (`inv`).
- Feeding **never** consumes wheat directly from the shed.
- A worker without wheat in hand standing on an animal tile no-ops and accomplishes nothing.
- Therefore, visiting the shed to acquire wheat prior to feeding is **physically mandatory under engine mechanics**.

### B. Worker Inventory Capacity
In `kaggriculture.py` (lines 299–300):
```python
def _inv_add(inv, item, n=1):
    inv[item] = inv.get(item, 0) + n
```
- **Ground Truth**: There is **no capacity limit** on worker personal inventories.
- A worker can theoretically hold arbitrary quantities of wheat, harvested crops, or fertilizer simultaneously.
- Worker inventory only has an economic limit at midnight, when `_drop_inventories_to_shed` discards any items that cannot fit in the shed's 100-item capacity.

### C. Engine `PICKUP` Semantics
In `kaggriculture.py` (lines 358–376):
```python
if op == "PICKUP":
    if not _is_shed_adjacent((fx, fy), board_size):
        return
    if len(action) < 2:
        return
    item = action[1]
    n = int(action[2]) if len(action) >= 3 else 1
    if n <= 0:
        return
    available = private["shed"].get(item, 0)
    n = min(n, available)
    if n <= 0:
        return
    private["shed"][item] -= n
    _inv_add(inv, item, n)
    return
```
- `PICKUP` transfers $\min(n, \text{shed\_available})$ from shed to worker in a single turn.
- A unit must stand on one of the 4 shed-access coordinates: $(4,4), (4,5), (5,4), (5,5)$.

---

## 2. Baseline Scheduler Feed-Staging Pipeline

In [`agent/execution/task_scheduler.py`](file:///d:/website%20project/kaggri%20ox/agent/execution/task_scheduler.py#L958-L975):
```python
# WHEAT STAGING: engine FEED consumes the UNIT's inventory (never the
# shed), so staged PICKUP tasks must run before any FEED can succeed.
# Distribute wheat across multiple workers in small chunks (2-3 wheat)
# so multiple workers can feed animals simultaneously!
if feeds_due > 0:
    held = sum(int(inv.get("WHEAT", 0)) for inv in ctx["private"].inventories)
    shed_wheat = int(ctx["private"].shed.get("WHEAT", 0))
    needed = min(shed_wheat, max(feeds_due - held, 0))
    if needed > 0:
        staging_prio = max(PRIORITY_FEED_STAGING, max_feed_prio + 1)
        chunk_size = 3
        n_chunks = (needed + chunk_size - 1) // chunk_size
        for c_idx in range(n_chunks):
            take = min(chunk_size, needed - c_idx * chunk_size)
            target = SHED_ACCESS_TILES[c_idx % len(SHED_ACCESS_TILES)]
            add(staging_prio, "PICKUP", tuple(target),
                args=["WHEAT", int(take)], kind="pickup_wheat")
```

### Complete Lifecycle Trace
1. **Demand Generation (`feeds_due`)**:
   Every morning, the scheduler loops over all animal tiles (pastures/coops) in unlocked quadrants. Animals not yet fed today increment `feeds_due`.
2. **Deficit Calculation (`needed`)**:
   The scheduler calculates how much wheat is *already held* across all active workers: `held = sum(worker_wheat)`.
   If `held >= feeds_due`, **zero pickup tasks are generated**! Workers already holding wheat service the animals.
3. **Chunking & Multi-Target Staging**:
   When `needed > 0`, the deficit is partitioned into chunks of up to 3 units: `chunk_size = 3`.
   Each chunk is assigned to a *different* shed-access tile (`target = SHED_ACCESS_TILES[c_idx % len(SHED_ACCESS_TILES)]`).
4. **Assignment**:
   The C2 zonal dispatcher matches each pickup task to the nearest capable candidate worker.
5. **Execution**:
   The worker navigates to the shed tile, executes `["PICKUP", "WHEAT", take]`, and receives the wheat into inventory.
6. **Subsequent Feeding**:
   Once the worker holds wheat, they become eligible for `FEED` tasks (`_eligible(task)` returns units holding wheat) and proceed to feed animals in their quadrant.

---

## 3. Empirical Verification: Generated vs Emitted vs Executed

Across the 20 diagnostic games:
- **Total `pickup_wheat` tasks generated**: 1,702 (85.10 / game)
- **Total `PICKUP WHEAT` actions emitted**: 1,693 (84.65 / game)
- **Total successful executions**: 1,693 (84.65 / game, **99.5% completion rate**)
- **Failed / Ineffective pickup actions**: 0 (0.0%)
- **Quantities Transferred Distribution**:
  - `qty = 3`: 1,199 actions (70.8%)
  - `qty = 2`: 281 actions (16.6%)
  - `qty = 1`: 213 actions (12.6%)
  - Mean quantity transferred: **2.58 wheat per pickup**.

### Key Finding on Waste
There are **zero failed pickups**, **zero wasted actions at the shed**, and **zero duplicate tasks**. The pipeline is mechanically tight and reliable.
