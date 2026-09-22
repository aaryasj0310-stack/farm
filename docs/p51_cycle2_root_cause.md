# Kaggriculture P5.1 — Cycle 2 Failure Root Cause Forensics

## Executive Summary
In P5.0-R, a naive live replay attempting wheat-to-carrot replacement yielded an empirical loss of **-$2,333.49/game** with **0.0% Cycle 2 completions**.
Initial hypotheses suspected missing Hour 0 pre-ordering and next-day tile hijacking. 
Detailed diagnostic instrumentation of the live execution trace on seed 96,201 (`diagnostic_c2_trace.txt`) reveals the **actual, multi-stage root cause mechanism**:

1. **Same-Day Wheat Queue Competition**: At the exact hour Cycle 1 is harvested intraday (Hours 7–16), baseline `MacroPlanner.build()` observes an empty tile (`is_empty=True`) and immediately queues `WHEAT` on that coordinate. The naive replay checked `if is_empty and pos_tuple not in queued_positions`, which evaluated to `False` because the coordinate was *already* queued with wheat. Thus, Cycle 2 CARROT was never queued, and workers planted wheat.
2. **Market Order Slot Saturation (The 10-Order Limit)**: At Hour 0 on Days 21, 24, and 25, the agent routinely generates 6–8 priority SELL orders and 3–4 HIRE orders. The Kaggle engine enforces `MAX_MARKET_ORDERS = 10`. Any unprioritized `BUY_SEED CARROT` intent is pushed out of the 10-slot limit by `central_planner.py`.
3. **Hourly Intent Repetition Artifact**: The provisional replay incremented conversion counters on every hourly invocation of `MacroPlanner.build()` (up to 10–15 times per physical planting), masking the fact that very few physical rotations actually started cleanly.
4. **Planting-Day Watering Vulnerability**: Intraday replanting occurring after midday faces worker contention with afternoon harvesting and feeding tasks, risking the omission of mandatory planting-day watering.

---

## Step-by-Step Empirical Forensic Trace (Seed 96201)

### Stage 1: Market Order Slot Saturation at Day 21 Hour 0
On Day 21 Hour 0, the agent identified 5 surplus wheat tiles and requested 5 CARROT seeds in `plan.intents["buy_seed"]`:
```
[D21 H00] BUY_SEED INTENTS ADJUSTED: {'CARROT': 5}
[D21 H00] AGENT ACTIONS: market=[['SELL', 'WHEAT', 10], ['SELL', 'WHEAT', 6], ['SELL', 'MILK', 10], ['SELL', 'MILK', 7], ['SELL', 'WOOL', 4], ['SELL', 'STRAWBERRY', 4], ['SELL', 'FERTILIZER', 9], ['HIRE'], ['HIRE'], ['HIRE']], seeds={'WHEAT': 5, 'CARROT': 0}
```
**Observation**: Sells (7 orders) + Hires (3 orders) = 10 orders. The 10-order cap was reached. `BUY_SEED CARROT` was completely dropped.
Because CARROT seeds were 0 while WHEAT seeds were 5, workers began planting WHEAT on some of the designated tiles:
```
[D21 H10] T1 Tile (2, 0) (planted D21): kind=PLANT, crop=WHEAT, age=-1
```

### Stage 2: Intraday Cycle 1 Harvest and Same-Day Wheat Competition
On Day 24, Cycle 1 carrots matured and were harvested intraday (Hours 7–16).
At Hour 7, Tile (4, 2) was harvested and became empty.
Immediately on that exact same step, baseline `MacroPlanner.build()` observed `(4, 2)` was empty and added `((4, 2), "WHEAT")` to `plan.plant_queue`.
When the provisional replay logic ran:
```python
queued_positions = {tuple(pos) for pos, _ in plan.plant_queue}
if is_empty and pos_tuple not in queued_positions:
    tiles_to_replant.append(pos_tuple)
```
Because `(4, 2)` was already in `queued_positions` (queued for wheat by baseline), the check `pos_tuple not in queued_positions` was **False**!
The trace records this exact failure across all tiles:
```
[D24 H07] T1 Replant check on (4, 2): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H08] T1 Replant check on (6, 2): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H09] T1 Replant check on (7, 2): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H10] T1 Replant check on (6, 1): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H11] T1 Replant check on (7, 1): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H12] T1 Replant check on (8, 2): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
[D24 H16] T1 Replant check on (8, 0): is_empty=True, in_queue=True, baseline_queued=['WHEAT']
```
**Consequence**: `tiles_to_replant` was empty. Cycle 2 carrot was NEVER appended. Instead, workers planted wheat on every single harvested Cycle 1 tile!

### Stage 3: Day 25/26 Hour 0 Market Drop for Cycle 2
On Day 25 Hour 0, for tiles that were maturing:
```
[D25 H00] H0 Maturing check: maturing_today=7
[D25 H00] AGENT ACTIONS: market=[['SELL', 'WHEAT', 9], ['SELL', 'CARROT', 9], ['SELL', 'MILK', 10], ['SELL', 'MILK', 6], ['SELL', 'STRAWBERRY', 3], ['SELL', 'MELON', 6], ['SELL', 'FERTILIZER', 7], ['HIRE'], ['HIRE'], ['HIRE']]
```
Again, 7 SELL orders + 3 HIRE orders = 10 orders. `BUY_SEED` was squeezed out.

---

## The Four Requirements for P5.1 Architecture

To achieve 100% reliable Cycle 2 execution, the production agent must solve all four forensic failure points:

1. **Active Tile Reservation in Queue Construction**:
   The `MacroPlanner` must be aware of reserved T1 tiles *before* constructing its default plant queue. It must NOT place generic wheat on any coordinate currently managed by an active two-cycle rotation.
2. **Explicit Seed Order Slot Reservation**:
   In `central_planner.py` and `order_builder.py`, `BUY_SEED` for active two-cycle carrot rotations must be treated as **P1 mandatory operational dependencies** (on par with HIRE and survival wheat), ensuring they are never crowded out by non-critical sell orders.
3. **Confirmed Observation-Driven State Machine**:
   States must transition only upon confirmed engine observations (e.g., verifying `kind == "PLANT"` and `crop == "CARROT"` and watering status), rather than optimistic intent scheduling.
4. **Planting-Day Watering Guarantee**:
   When Cycle 2 is planted intraday on Day $D+3$, a high-priority `WATER` task must immediately be dispatched on that coordinate during the remaining hours of Day $D+3$.
