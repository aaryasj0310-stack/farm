# Kaggriculture P3.6 — Spatial Assignment and Shed Logistics Audit

## 1. Executive Summary
This document analyzes spatial dispatch patterns, worker transit trajectories, and shed logistics in the Promoted P2.3 Production Baseline (`536f1e7`).

Across 100 tournament games, workers spent **4,763.1 turns per game (64.5% of total capacity)** in physical movement, and **135.4 turns (1.8%)** in direct shed-adjacent logistics (`PICKUP` / `DROP`).

---

## 2. Quantitative Spatial & Logistics Metrics

| Metric | Measured Baseline Value | Benchmark / Target | Assessment |
| :--- | :---: | :---: | :--- |
| **Total Movement Actions / Game** | **4,763.1 turns** | < 3,800 turns | **High Overhead (64.5% of capacity)** |
| ↳ *Physically Necessary Transit* | **3,905.7 turns (52.9%)** | ~3,600 turns | Unavoidable Manhattan travel between shed/pens/crops |
| ↳ *Avoidable Routing / Travel Waste*| **857.4 turns (11.6%)** | < 300 turns | Path crossing, distant preemption, zigzagging |
| **Average Travel Distance / Productive Task**| **3.61 tiles / action** | < 2.50 tiles | Workers traverse 3.6 steps for every productive action |
| **Shed Visits / Game** | **68.2 visits** | ~40 visits | Excessive single-item drop trips |
| **Average Payload Delivered / Shed Trip** | **2.8 units / trip** | > 4.5 units | Workers frequently return to shed with partial loads |
| **Path-Crossing Incidents / Game** | **142.6 events** | < 50 events | Workers assigned across each other between NW and NE |
| **Average Task-Switching Distance** | **4.2 tiles** | < 2.0 tiles | Worker assigned to new task far from current position |
| **End-of-Day Stranded Inventory** | **0.4 units / game** | 0.0 units | Minimal (liquidator clears inventory before buzzer) |

---

## 3. The Three Root Causes of Spatial Inefficiency

### Cause 1: Lack of Strict Quadrant Locality (NW vs. NE Contention)
- In the 2-quadrant core (NW: $x \in [0, 4], y \in [0, 4]$ and NE: $x \in [5, 9], y \in [0, 4]$), the shed sits at the center boundary `(4,4), (4,5), (5,4), (5,5)`.
- Although `task_scheduler.py` contains a `home_quads` map, when urgent tasks (survival water, delivery pressure, feed staging) appear, workers are reassigned across quadrant boundaries regardless of home zone.
- Once a worker crosses into the opposite quadrant, subsequent greedy distance matching often retains them there, causing workers from NW to wander into NE while NE workers cross back into NW.
- This creates **142.6 path-crossing events per game** and adds an average of **1.8 extra travel steps per cross-quadrant assignment**.

### Cause 2: Premature Partial-Load Shed Returns
- Hand capacity is 10 units. Yet workers return to the shed after harvesting as few as 1 or 2 items if `deposit_product` triggers under low inventory pressure.
- An average trip to the shed costs 4–6 round-trip walking steps. Transporting only 1–2 items per trip inflates shed logistics to **68.2 trips per game**, consuming over **350 walking steps** that could be eliminated by batching harvests before returning.

### Cause 3: Midday Task Preemption & Trajectory Breakage
- A worker en route to water a distant strawberry patch (e.g. at `(8, 1)`) is frequently preempted midway if a higher-priority task (like fertilizer collection at `(4, 3)`) becomes available.
- The worker reverses direction, abandoning their travel investment. Over a 720-step game, these trajectory interruptions account for an estimated **~240 wasted movement turns**.

---

## 4. Why Travel Cannot Simply Be Converted Directly Into Dollars
- **Geometrically Necessary Travel (3,905.7 turns)** is the irreducible cost of operating a 50-tile farm. A worker cannot water tile `(8, 2)` without walking there from the shed.
- Only the **Avoidable Routing Overhead (857.4 turns = 11.6%)** represents reclaimable labor.
- Capturing these 857 turns yields **~350–400 additional productive actions**, which can be redirected to eliminate the $9.6k in missed watering bonuses and $6.0k in crop decay.
