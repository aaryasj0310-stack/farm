# Kaggriculture P3.4 — Phase 4: Feeding Parallelism & Batch Size Audit

## Executive Summary

This document evaluates the trade-off between wheat pickup chunk size and animal feeding parallelism, comparing the baseline policy (`chunk_size = 3`) against counterfactual batch sizes of 4, 5, and 6 across 20 baseline games ([`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox)).

---

## 1. Feeding Parallelism in the Baseline

Under `chunk_size = 3`, the scheduler deliberately distributes wheat demand across multiple shed-access coordinates:

| Metric | Baseline Value (`chunk_size = 3`) | Interpretation |
| :--- | :--- | :--- |
| **Feed-Capable Workers per Day** | **3.74 workers / day** | High parallelism across workforce |
| **Animals Fed per Day** | **7.18 animals / day** | ~1.9 animals fed per active feeder |
| **Mean Turns from Day Start to All Animals Fed** | **4.2 hours (turn 4 of 24)** | Morning feeding completed rapidly |
| **Urgent Feed Tasks Completed before Deadlines** | **99.2%** | Almost zero missed critical feeds |
| **Unfed Animals at EOD across Season** | **14.10 animal-days / game** | Concentrated on Day 29 (feed cutoff) |
| **Animal Escapes across Season** | **0.00 escapes / game** | 100% escape prevention |

### Why Parallelism Matters:
In the 2-quadrant layout:
- Cows and sheep are distributed across pasture tiles in **both Quadrant 1 (NW) and Quadrant 2 (NE)**.
- Having 3 to 4 workers pick up 2–3 wheat each allows **simultaneous feeding** in NW and NE during the morning hours (Hours 0–4).
- Workers quickly feed their local animals and immediately transition into localized crop watering sweeps.

---

## 2. Counterfactual Batch Sizing Analysis

What happens if we increase `chunk_size` from 3 to 4, 5, or 6?

Across all 20 diagnostic games, we evaluated every instance where the same worker made a repeat pickup on the same day ($N=279$ occurrences across 20 games):

| Batch Size Policy | Repeat Journeys Eliminated / Game | Gross Trips Saved / Season | Parallelism Impact |
| :--- | :--- | :--- | :--- |
| **Baseline (`chunk = 3`)** | — (Baseline) | — | Optimal (3.74 feeders/day) |
| **Counterfactual (`chunk = 4`)** | **2.40 journeys / game** | 48 trips in 20 games | Minor reduction |
| **Counterfactual (`chunk = 5`)** | **3.05 journeys / game** | 61 trips in 20 games | Moderate reduction |
| **Counterfactual (`chunk = 6`)** | **12.45 journeys / game** | 249 trips in 20 games | **Severe concentration risk** |

---

## 3. The Structural Bottlenecks of Larger Batch Sizes

### 1. Shed Wheat Inventory Scarcity
- In the early-to-mid game (Days 4–15), `shed["WHEAT"]` fluctuates between **3 and 6 units** because wheat is continually consumed for feeding and cash generation.
- If `chunk_size = 6`, the first worker to reach the shed claims **all 6 available wheat units**.
- The second and third workers in other quadrants find `shed["WHEAT"] == 0`, forcing their feed tasks to stall.
- The single carrier must now walk across both Quadrants 1 and 2 sequentially to service all animals, creating severe transit ping-pong and delaying feeding until late in the day.

### 2. Disruption of Morning Crop Sweeps
- Under baseline (`chunk = 3`), 3 workers spend ~3 turns feeding local animals and immediately join the critical morning crop watering sweep (`PRIORITY_BONUS_WATER = 70`).
- Under `chunk = 6`, a single worker is burdened with full-farm livestock rounds, while other workers in the livestock quadrant sit idle waiting for feed or have to cross the farm later.

### 3. Asymmetric Payoff
- Increasing batch size to 4 or 5 saves only **2.4 to 3.0 journeys per game across the entire 30-day season** (less than 0.1 journeys per day).
- Saving 3 journeys per game represents an average of only **~4 to 8 movement turns per game** ($< 0.15\%$ of total movement turns).
- Yet the downside risk (delayed feeding, missed milk/wool production windows, animal escape risk) carries a potential penalty of thousands of dollars per game (as demonstrated in P3.2 where minor schedule disruption cost -$3,455/game).
