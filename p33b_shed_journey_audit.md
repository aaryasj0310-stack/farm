# Kaggriculture P3.3-B — Shed Journey Diagnostic Audit & Feasibility Assessment

## Executive Summary

- **Objective**: Determine whether workers make unnecessary trips to the shed for single-item product deposits that can be batched or eliminated without delaying sales, overflowing the shed, or disrupting feed/animal logistics.
- **Audit Design**: 20 deep-trace baseline games on commit [`536f1e7`](file:///d:/website%20project/kaggri%20ox) (Promoted P2.3, seeds 90,001–90,010 $\times$ 2 seats) with per-turn unit coordinate tracking, action classification, shed load monitoring, and intent auditing.
- **Core Empirical Finding**:
  - **Daytime Routine Product Deposits (S6)**: **0.00 visits/game** (0.0% of shed actions).
  - **Mandatory Feed Pickups (S1)**: **84.90 visits/game** (61.2% of explicit shed actions).
  - **Fertilizer Pickups (S2)**: **16.00 visits/game** (11.5% of explicit shed actions).
  - **Overflow-Protection Deposits (S5)**: **5.00 visits/game** (at hours 22–23 when pending inventory threatens midnight discard).
  - **Incidental Central Tile Crossings (S7)**: **633.45 visits/game** (workers walking through $(4,4)-(5,5)$ while traveling between NW and NE).
- **Verdict**: **CLOSE HYPOTHESIS P3.3-B via Pre-Registered Stop Condition**.
  - The production baseline (`536f1e7`) **already avoids routine daytime shed deposits entirely**, relying on the engine's zero-cost midnight auto-deposit.
  - Genuinely avoidable deposit journeys do not exist in the codebase.
  - Per the experimental protocol: *"If the audit finds that almost all explicit shed trips are mandatory feed, overflow-protection or endgame-realization journeys, do not implement a batching treatment merely to complete P3.3-B. Close the hypothesis and re-profile the remaining execution bottleneck."*

---

## Complete Empirical Distribution of Shed Visits (20 Baseline Games)

| Category | Description | Mean Visits/Game | Share of Explicit Actions | Share of Total Tile Touches |
| :--- | :--- | :--- | :--- | :--- |
| **S1: Feed Pickup** | `PICKUP WHEAT` for hungry livestock | **84.90** | **61.2%** | 11.0% |
| **S2: Fertilizer Pickup** | `PICKUP FERTILIZER` for crop boost | **16.00** | **11.5%** | 2.1% |
| **S3: Livestock Delivery** | `PLACE <ANIMAL>` from shop/shed to pasture | **0.00** | **0.0%** | 0.0% |
| **S4: Day-29 Endgame Liquidation** | Final day pre-sale deposit | **0.00** | **0.0%** | 0.0% |
| **S5: Overflow-Risk Deposit** | Hours 22–23 deposit when inventory > 50 | **5.00** | **3.6%** | 0.6% |
| **S6: Routine Daytime Deposit** | Discretionary mid-day product delivery | **0.00** | **0.0%** | **0.0%** |
| **S8: Other Explicit Actions** | Initial setup / misc shed interactions | **32.80** | **23.6%** | 4.2% |
| **Total Explicit Shed Actions** | Units executing `PICKUP`/`DROP`/`PLACE` at shed | **138.70** | **100.0%** | **18.0%** |
| **S7: Incidental Tile Crossings** | Units moving `N`/`S`/`E`/`W` through $(4,4)-(5,5)$ | **633.45** | — | **82.0%** |
| **Grand Total (All Touches)** | All turn-unit occurrences on shed access tiles | **772.15** | — | **100.0%** |

---

## Causal Audit & Detailed Mechanics

### 1. The Code Already Implements Deposit Batching
In `agent/execution/task_scheduler.py` (lines 1014–1025):
```python
# Normal-day worker inventory is intentionally allowed to ride until
# the engine's free end-of-day auto-drop. Explicit shed travel costs
# scarce field actions and previously caused watering/feed regressions.
# Intervene only when value is at risk of EOD overflow, or on Day 29
# when EOD auto-drop occurs after the final market opportunity.
overflow_risk = pending_total > SHED_CAPACITY
should_deliver = (
    day == 29
    or (hour >= 22 and overflow_risk)
)
if not should_deliver:
    continue
```
On Days 0 through 28, before Hour 22, the scheduler **never creates deposit tasks**. Harvested crops and animal goods sit in worker inventories and automatically deposit into the shed at midnight for zero action cost.

### 2. S5 (Overflow-Risk Deposits) Are Genuinely Protective
Across all 20 games:
- An average of only **5.0 deposits/game** occurred under S5.
- S5 triggered strictly at Hours 22 and 23.
- Deposited items were high-volume accumulated yields: 217 wheat, 56 wool, 44 milk, 36 melons, 12 strawberries, 12 carrots, 10 tomatoes.
- If these items were not deposited at Hour 22–23, midnight auto-drop would have exceeded the engine's 50-item shed capacity, causing permanent discards and revenue loss.

### 3. S1 (Feed Pickup) Is Strictly Mandatory
- Feed pickups (84.9 visits/game) account for over 60% of all explicit shed actions.
- Under engine rules, `FEED` consumes wheat from the *acting unit's personal inventory*, not the shed.
- Because cows and sheep require daily feeding to produce milk/wool and avoid escape, workers must visit the shed to pick up wheat before walking to the pastures.

### 4. S7 (Incidental Tile Crossings) Account for 82% of Shed Coordinate Touches
- 633.45 turns/game involve a worker stepping on $(4,4), (4,5), (5,4), (5,5)$.
- In all 633.45 instances, the worker executed a movement command (`NORTH`, `SOUTH`, `EAST`, `WEST`) en route between agricultural tiles in NW and NE.
- The shed coordinates sit at the geographic center of the 10x10 map between Quadrants 1 and 2; pathfinding naturally routes through these central tiles.

---

## Conclusion & Next Steps

1. **Hypothesis P3.3-B Closed**: There is no avoidable product deposit travel in the production baseline. Attempting to delay or suppress the 5.0 overflow-prevention trips would risk midnight discards for zero meaningful transit savings.
2. **Re-Profiling the Remaining Execution Bottleneck**:
   With P3.1 (harvest priority), P3.2 (care urgency), P3.3-A (physical locality), and P3.3-B (shed batching) resolved:
   - What truly causes the remaining transit overhead?
   - The 84.9 feed pickups/game: workers walking back and forth between shed and pastures.
   - The 633.45 incidental transit crossings between NW and NE.
   - The task distribution across the day (morning watering sweep vs midday vs evening).
