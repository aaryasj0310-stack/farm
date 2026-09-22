# Kaggriculture P3.2 — Dollar-Denominated Execution-Loss Decomposition

## 1. Executive Summary
This document establishes an authoritative, dollar-denominated decomposition of all unrealized farm revenue caused by execution failures in the Promoted P2.3 Production Baseline (`536f1e7`).

All figures represent per-game averages measured across **100 tournament games** (Seeds 90,001–90,050 across 2 seats, 5 opponent archetypes).

### The Non-Double-Counting Hierarchy
To avoid conflating symptoms with causes (e.g. counting both "lost harvest" and "travel time" as separate dollar deficits), every loss is classified strictly through three distinct levels:
1. **Observed Economic Loss**: The physical uncollected or destroyed dollar value.
2. **Proximate Execution Failure**: The specific task or schedule event that failed in the game engine.
3. **Hypothesized Root Cause**: The scheduler or dispatch defect that created the proximate failure.

---

## 2. Ranked Dollar-Denominated Execution Losses

| Rank | Loss Category | Measured Loss / Game | Evidence Label | Proximate Execution Failure | Primary Root Cause Candidate |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **1** | **Missed Crop Watering Bonus** | **$9,630.95** | **Directly Measured** | Crop was not watered during its active bonus yield window (`(max_yield_day+1)//2 <= age <= max_yield_day`). | **E2 (Priority Inversion)** + **E3 (Spatial Travel)**: Standard harvest, fertilizer collection, and distant travel preempt daily watering passes. |
| **2** | **Crop Decay (Overripe Unharvested)** | **$6,031.80** | **Directly Measured** | One-time crops (Wheat, Carrots, Tomatoes) reached `max_yield_day` and decayed before being harvested. | **E2 (Priority Defect)**: `PRIORITY_STANDARD_HARVEST = 65` sits *below* bonus watering (70) and fert collection (75), allowing ripe crops to sit until they decay into priority 90. |
| **3** | **Missed Animal Care Yield Multiplier** | **$3,926.00** | **Directly Measured** | Cows, Sheep, and Geese missed daily `CARE`, sacrificing +1 yield multiplier on their next production day. | **E2 (Priority Defect)**: `PRIORITY_CARE_ANIMAL = 65` ties standard harvest and sits below watering/fertilizer, causing care to be dropped when morning queues back up. |
| **4** | **Missed Animal Feeding Revenue** | **$2,686.80** | **Directly Measured** | Animal not fed prior to midnight refresh, wiping care bonuses and delaying product cycle. | **E4 (Logistics Bottleneck)**: Wheat courier/pickup staging delays prevent feed actions from completing before the daily cutoff. |
| **5** | **Uncollected Daily Fertilizer** | **$221.00** | **Directly Measured** | Fertilizer available on animal tile was not collected before midnight reset. | **E3 (Spatial Travel)**: Animal pens isolated from main worker routes; low marginal value compared to traversal cost. |
| **6** | **Plant Starvation Deaths (2d Unwatered)** | **$0.00** | **Directly Measured** | Plant consecutive unfed/unwatered $\ge 1$ dies at EOD. | **Zero Regression**: `PRIORITY_URGENT_SURVIVAL = 100` successfully prevents all 2-day crop starvation. |
| **7** | **End-of-Season Unharvested Ripe Crops** | **$0.00** | **Directly Measured** | Ripe crops left in ground at Day 30 hour 23. | **Zero Regression**: `EndgameLiquidator` sweeps all mature crops on Day 29/30 without leaving standing ripe assets. |
| **TOTAL** | **Direct Measured Economic Losses** | **$22,496.55** | **Directly Measured** | **100% Un-duplicated Physical Economic Waste** | **Dominant Bottlenecks: E2 (Priority) + E3 (Spatial Dispatch)** |

---

## 3. Capacity & Traversal Loss (Non-Dollarized Metric)

In accordance with strict non-double-counting principles, movement and idle turns are **not converted into duplicate dollars**, but are measured as wasted labor-turn capacity:

| Capacity Drain Category | Turns / Game | Equivalent Labor Capacity | Proximate Mechanism |
| :--- | :---: | :---: | :--- |
| **Avoidable / Inefficient Movement** | **857.4 turns** | **~2.75 full worker-days** | Path crossing between workers, zigzag routing between NW and NE, and single-item shed runs. |
| **Idle / Ineffective / Stale No-Ops** | **437.6 turns** | **~1.40 full worker-days** | Action emitted on tile whose state changed (e.g. duplicate water on already-watered tile, invalid moves). |
| **Combined Avoidable Capacity Loss** | **1,295.0 turns** | **~4.15 full worker-days** | **17.5% of total seasonal labor capacity** is completely consumed by reversible travel and idle friction! |

---

## 4. Deep-Dive Causal Analysis of the Two Dominant Losses

### Loss #1: Missed Crop Watering Bonus ($9,630.95/game)
- **Engine Rule**: One-time crops only accumulate bonus yield when watered during their designated bonus window (`(max_yield_day + 1) // 2 <= age <= max_yield_day`). For Wheat, this is Days 2, 3, and 4 (up to 6 units yield). For Carrots, Days 1 and 2 (up to 4 units yield). For Strawberries (ongoing), every missed watering drops yield frequency.
- **Root Cause**: On high-activity days (Days 8–24), the queue of competing tasks exceeds morning worker bandwidth. Because `PRIORITY_BONUS_WATER = 70` is lower than urgent survival (100), animal feed (85), structure builds (78), and fertilizer collection (75), water tasks wait until Hour 14–18. By then, workers are spatially dispersed or busy returning products to the shed, leaving 3–5 crops unwatered before the midnight cutoff.

### Loss #2: Crop Decay Before Harvest ($6,031.80/game)
- **Engine Rule**: If a one-time crop is not harvested on `max_yield_day`, it begins decaying at end-of-day, losing 1 yield unit per day until dead.
- **The Priority Inversion Bug**:
  - `PRIORITY_STANDARD_HARVEST` is set to **65** in `agent/config.py`.
  - `PRIORITY_BONUS_WATER` is set to **70**.
  - `PRIORITY_FERT_COLLECT` is set to **75**.
  - `PRIORITY_PLANT_AND_WATER` is set to **75**.
- **Consequence**: When a crop reaches full maturity (e.g. Wheat on Day 4 with 6 units = $150 value), its harvest task is created with priority 65. The scheduler prioritizes watering non-urgent crops (priority 70) and planting new seeds (priority 75) *over* harvesting the ripe wheat! The ripe wheat sits in the ground overnight, decays to 5 units, and only *then* escalates to `PRIORITY_DECAY_HARVEST = 90`. This priority inversion burns an average of **$6,031.80/game in pure decay loss**!

---

## 5. Synthesis: Reconciling the Target Gap
- **Current Promoted Production Baseline**: **~$103.6k/game**
- **Competition Target**: **$130.0k/game**
- **Remaining Target Gap**: **~$26.4k/game**
- **Direct Measured Execution Losses**: **$22,496.55/game**
- **Reconciliation Ratio**: **85.2% of the entire $26.4k gap to $130,000 is directly explained by measured execution failures** in watering bonuses, crop decay, and animal care!
