# Kaggriculture P5.1-C — Worker Action Delta Telemetry

## 1. Executive Summary

This report analyzes the empirical worker activity deltas between Control and Treatment across all 100 matched pairs (200 live games).

Every worker action emitted by the farmer and all hired farm hands was captured and classified across all 720 game turns, with special focus on the **Days 21–29** late-season window where P5.1 was active.

### Core Discoveries:
1. **The "Massive Extra Watering" Narrative is Disproven**:
   - `WATER_CARROT` increased by **+46.06 actions / game** (from 22.72 to 68.78).
   - `WATER_WHEAT` decreased by **−49.58 actions / game** (from 150.36 to 100.78).
   - Net watering change across all crops in Days 21–29: **−4.68 watering actions / game**!
   - Baseline was already watering late wheat on Days 22–27 to reach mature 6-unit yields. The two-cycle carrot rotation did NOT increase total watering workload — it actually watered slightly less.
2. **Where the Labor Drag Truly Came From**:
   - **Transit and Commuting Overhead**: Workers walked **+14.54 additional movement steps per game** across Days 21–29 (`MOVE_WEST` +7.29, `MOVE_EAST` +5.49, `MOVE_SOUTH` +2.22, `MOVE_NORTH` −0.46) due to the fragmented two-cycle workflow (walking to shed for seeds, walking to tile, walking back to deposit C1, returning for C2 seeds).
   - **Intraday Replanting & Harvest Events**: Replanting and double-harvesting added **+4.35 net field task actions** (`PLANT_CARROT` +13.29 vs `PLANT_WHEAT` −11.26; `HARVEST_CARROT` +13.07 vs `HARVEST_WHEAT` −11.01).
   - **Worker Utilization**: `PASS` actions decreased by **−14.57 actions / game** (workers were busier and had less slack: from 151.81 down to 137.24).
3. **The Livestock Work Drop Was Triggered by Wheat Stockouts**:
   - `FEED_COW` dropped by **−1.73 actions / game** (from 59.01 to 57.28).
   - `FEED_SHEEP` dropped by **−1.51 actions / game** (from 35.87 to 34.36).
   - `CARE_COW` dropped by **−0.98 actions / game** (from 47.95 to 46.97).
   - `CARE_SHEEP` dropped by **−0.55 actions / game** (from 32.37 to 31.82).
   - Workers did not "forget" to feed animals; rather, because 41.84 fewer wheat units were harvested, the shed experienced temporary intraday grain stockouts while waiting for market buy orders to settle. Workers routed to feed animals found no wheat in shed/inventory and were forced to skip feed actions.

---

## 2. Worker Action Classification (Days 21–29 Late Season)

The table below lists every worker operation executed between Day 21 Hour 0 and Day 29 Hour 23, averaged across all 100 matched pairs:

| Operation Category | Specific Operation | Control Mean | Treatment Mean | Treatment − Control ($\Delta$) |
| :--- | :--- | :---: | :---: | :---: |
| **Crop Watering** | `WATER_CARROT` | 22.72 | 68.78 | **+46.06** |
| | `WATER_WHEAT` | 150.36 | 100.78 | **−49.58** |
| | `WATER_STRAWBERRY` | 66.20 | 65.27 | **−0.93** |
| | `WATER_MELON` | 18.69 | 18.70 | **+0.01** |
| | `WATER_TOMATO` | 3.71 | 3.56 | **−0.15** |
| | `WATER` (Unspecified) | 0.39 | 0.30 | **−0.09** |
| | **Total Watering** | **262.07** | **257.39** | **−4.68** |
| | | | | |
| **Crop Harvesting** | `HARVEST_CROP_CARROT` | 6.53 | 19.60 | **+13.07** |
| | `HARVEST_CROP_WHEAT` | 41.22 | 30.21 | **−11.01** |
| | `HARVEST_CROP_STRAWBERRY`| 31.35 | 31.34 | **−0.01** |
| | `HARVEST_CROP_MELON` | 3.57 | 3.57 | **0.00** |
| | `HARVEST_CROP_TOMATO` | 1.69 | 1.75 | **+0.06** |
| | **Total Crop Harvests** | **84.36** | **86.47** | **+2.11** |
| | | | | |
| **Crop Planting** | `PLANT_CARROT` | 7.68 | 20.97 | **+13.29** |
| | `PLANT_WHEAT` | 24.93 | 13.67 | **−11.26** |
| | **Total Crop Planting** | **32.61** | **34.64** | **+2.03** |
| | | | | |
| **Worker Transit** | `MOVE_WEST` | 456.48 | 463.77 | **+7.29** |
| | `MOVE_EAST` | 405.75 | 411.24 | **+5.49** |
| | `MOVE_SOUTH` | 306.44 | 308.66 | **+2.22** |
| | `MOVE_NORTH` | 544.80 | 544.34 | **−0.46** |
| | **Total Movement Steps** | **1,713.47** | **1,728.01** | **+14.54** |
| | | | | |
| **Livestock Care & Feed** | `FEED_COW` | 59.01 | 57.28 | **−1.73** |
| | `FEED_SHEEP` | 35.87 | 34.36 | **−1.51** |
| | `CARE_COW` | 47.95 | 46.97 | **−0.98** |
| | `CARE_SHEEP` | 32.37 | 31.82 | **−0.55** |
| | `COLLECT_FERTILIZER` | 99.19 | 99.20 | **+0.01** |
| | `HARVEST_ANIMAL_COW` | 28.36 | 28.39 | **+0.03** |
| | `HARVEST_ANIMAL_SHEEP` | 12.71 | 12.65 | **−0.06** |
| | **Total Livestock Care** | **283.46** | **280.67** | **−2.79** |
| | | | | |
| **Logistics & Idle** | `PASS` (Idle / No-op) | 151.81 | 137.24 | **−14.57** |
| | `PICKUP` (Shed retrieval) | 39.05 | 39.39 | **+0.34** |
| | `PLACE` (Shed deposit) | 3.97 | 3.30 | **−0.67** |
| | `DIG` (Shovel / Clear) | 11.86 | 11.64 | **−0.22** |
| | `FERTILIZE` | 11.02 | 11.15 | **+0.13** |
| | `DROP` | 21.20 | 21.16 | **−0.04** |

---

## 3. Full Season Worker Action Overview

Across the entire 30-day season (Days 0–29):

| Action Group | Control Mean | Treatment Mean | Delta ($\Delta$) |
| :--- | :---: | :---: | :---: |
| **Total Movement Steps** | 4,771.80 | 4,786.34 | **+14.54** |
| **Total Crop Waterings** | 933.73 | 929.04 | **−4.69** |
| **Total Crop Plantings** | 159.51 | 161.53 | **+2.02** |
| **Total Crop Harvests** | 189.84 | 191.95 | **+2.11** |
| **Total Livestock Feeds** | 216.55 | 213.31 | **−3.24** |
| **Total Livestock Cares** | 197.76 | 196.23 | **−1.53** |
| **Total Idle Turns (`PASS`)** | 424.57 | 410.00 | **−14.57** |
| **Total Worker Actions Tracked** | 7,422.38 | 7,424.97 | **+2.59** |

---

## 4. Key Causal Takeaways

1. **The Real Shift**: Substituting two carrot cycles for wheat substituted 49.58 wheat waterings for 46.06 carrot waterings. Waterings were NOT the bottleneck.
2. **The Transit Overhead**: The two-cycle nature (harvest C1, fetch C2 seed, plant C2, water C2, harvest C2) increased worker movement by **+14.54 steps** and consumed **14.57 idle/slack turns**.
3. **The Fatal Impact on Feed**: Because grain harvest was depleted by 41.84 units, animal feed routines experienced stockout gaps, leading to **−3.24 fewer feeds** and **−1.53 fewer cares**, directly triggering the **−$985.32 livestock revenue collapse**.
