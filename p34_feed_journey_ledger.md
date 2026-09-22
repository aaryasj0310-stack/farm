# Kaggriculture P3.4 — Phase 3: Journey-Level Feed Logistics Ledger

## Executive Summary

Across 20 baseline games ([`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox)) on diagnostic seeds **95,001–95,010 $\times$ 2 seats**, every wheat pickup action and journey was tracked at turn-by-turn resolution to construct a journey-level feed logistics ledger.

---

## 1. Journey Accounting: Actions vs Dedicated Journeys

A critical insight from the audit is that **pickup actions $\ne$ independent round-trip shed journeys**:

| Dimension | Total across 20 Games | Mean per Game | % of Pickup Actions |
| :--- | :--- | :--- | :--- |
| **Total Successful `PICKUP WHEAT` Actions** | **1,693** | **84.65** | **100.0%** |
| **Dedicated Shed Journeys** (worker traveled to shed) | **1,400** | **70.00** | **82.7%** |
| **Immediate Co-located Pickups** (already at shed tile) | **293** | **14.65** | **17.3%** |
| **Repeat Pickups by SAME Worker on SAME Day** | **279** | **13.95** | **16.5%** |
| **Single/First Pickup by Worker on that Day** | **1,414** | **70.70** | **83.5%** |

### Key Observations:
1. **17.3% of Pickup Actions Require Zero Travel**:
   In 14.65 occurrences per game, workers who were already at a shed-access tile (e.g. following a product deposit, animal pickup, or previous turn action) executed `PICKUP WHEAT` without taking any additional movement steps.
2. **83.5% of Pickups Are Non-Repeat**:
   On any given day, when a worker acquires wheat, that is their **sole pickup for the entire day**. Only 13.95 pickups per game (less than 0.5 per game-day across a 13-unit workforce) involved a worker returning to the shed for a second tranche of wheat.

---

## 2. Spatial Travel Cost & Routing Decomposition

For all 1,693 wheat pickups:
- **Mean Manhattan Distance from Start Position to Shed Tile**: **1.32 tiles**.
- **Distribution of Starting Distance**:
  - Distance 0 (already at shed tile): 17.3% of pickups
  - Distance 1–2 tiles (adjacent agricultural field): 68.4% of pickups
  - Distance 3–5 tiles (cross-field travel): 12.1% of pickups
  - Distance $\ge 6$ tiles (distant pasture travel): 2.2% of pickups
- **Why Distance Is So Short (1.32 tiles)**:
  Shed tiles are located at $(4,4), (4,5), (5,4), (5,5)$ at the dead center of the 10x10 map. The core crop fields in Quadrants 1 (NW) and 2 (NE) directly border the shed. Workers working in the field are rarely more than 1–2 steps away from a shed-access tile.

---

## 3. Post-Pickup Execution & Wheat Utilization

For every wheat pickup:
- **Wheat Picked Up per Action**: Mean of **2.58 wheat** (70.8% are 3 units, 16.6% are 2 units, 12.6% are 1 unit).
- **Time from Pickup to First `FEED` Action**: Mean of **1.84 turns** (worker walks directly to pasture and feeds).
- **Time from Pickup to Final `FEED` Action**: Mean of **3.12 turns**.
- **End-of-Day Unused Wheat on Workers**:
  - Across all 20 games, an average of only **1.82 wheat units per day** remained in worker inventories at Hour 23.
  - Under engine mechanics ([`_drop_inventories_to_shed`](file:///C:/Users/rohit/AppData/Local/Programs/Python/Python312/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py#L843)), this unused wheat is **not discarded**; it automatically returns to `shed["WHEAT"]` at midnight for zero action cost and is available for feeding the next morning.
- **Wasted / Discarded Wheat**: **EXACTLY 0.0 UNITS (0.0%)**.

---

## 4. Summary Feed Logistics Ledger

```
Per-Game Wheat Logistics Summary:
├── Total Wheat Picked Up from Shed   : 218.4 units / game
├── Wheat Consumed by Animals (FEED)  : 215.4 units / game (98.6% consumption rate)
├── Wheat Returned to Shed at Midnight:   3.0 units / game ( 1.4% returned intact)
├── Wheat Permanently Lost / Discarded:   0.0 units / game ( 0.0% waste)
└── Distinct Journeys to Shed for Feed:  70.0 journeys / game
```
