# P6 Worker Execution and Transit Audit

## 1. Executive Summary & Epistemic Verdict

- **Total Worker Actions / Game**: 7,375.73 actions
- **Movement Actions (`MOVE_*`)**: 4,783.10 moves (**64.85%** of all actions)
- **Direct Work Actions**: 2,183.80 work actions (**29.61%** of all actions)
- **Idle Pass Actions (`PASS`)**: 408.83 passes (**5.54%** of all actions)

```
[Total Worker Capacity: 7,375.73 actions]
┌───────────────────────────────────────┬──────────────────────┬────────┐
│             MOVE (64.85%)             │     WORK (29.61%)    │PASS (5)│
│              4,783.10                 │       2,183.80       │ 408.83 │
└───────────────────────────────────────┴──────────────────────┴────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> Across 100 baseline games, the production workforce spends **2.19 hours traveling for every 1.0 hour of productive field work**. Worker transit is the largest single time sink in the system, consuming nearly two-thirds of all available labor-hours.

---

## 2. Complete Worker Action Breakdown

| Category | Action Type | Actions / Game | % of Total Actions |
| :--- | :--- | :---: | :---: |
| **Movement** | `MOVE_NORTH` | 1,512.55 | 20.51% |
| | `MOVE_WEST` | 1,349.37 | 18.29% |
| | `MOVE_EAST` | 1,112.73 | 15.09% |
| | `MOVE_SOUTH` | 808.45 | 10.96% |
| **Crop Maintenance** | `WATER_WHEAT` | 453.69 | 6.15% |
| | `WATER_STRAWBERRY` | 177.56 | 2.41% |
| | `WATER_MELON` | 163.53 | 2.22% |
| | `WATER_CARROT` | 94.13 | 1.28% |
| | `WATER_TOMATO` | 41.09 | 0.56% |
| | `FERTILIZE` | 23.67 | 0.32% |
| **Livestock Care** | `FEED_COW` | 139.18 | 1.89% |
| | `CARE_COW` | 125.05 | 1.70% |
| | `FEED_SHEEP` | 74.79 | 1.01% |
| | `CARE_SHEEP` | 71.49 | 0.97% |
| | `COLLECT_FERTILIZER` | 218.13 | 2.96% |
| **Harvest Operations**| `HARVEST_CROP_WHEAT` | 98.76 | 1.34% |
| | `HARVEST_ANIMAL_COW` | 47.36 | 0.64% |
| | `HARVEST_CROP_STRAWBERRY` | 40.13 | 0.54% |
| | `HARVEST_CROP_CARROT` | 25.61 | 0.35% |
| | `HARVEST_ANIMAL_SHEEP` | 19.84 | 0.27% |
| | `HARVEST_CROP_MELON` | 15.67 | 0.21% |
| | `HARVEST_CROP_TOMATO` | 10.92 | 0.15% |
| **Planting & Infra** | `PLANT_WHEAT` | 99.87 | 1.35% |
| | `PLANT_CARROT` | 26.83 | 0.36% |
| | `PLANT_MELON` | 15.67 | 0.21% |
| | `PLANT_STRAWBERRY` | 13.48 | 0.18% |
| | `PLANT_TOMATO` | 4.45 | 0.06% |
| | `BUILD_PASTURE` | 11.18 | 0.15% |
| | `DIG` | 15.91 | 0.22% |
| **Logistics & Shed** | `PICKUP` | 116.50 | 1.58% |
| | `DROP` | 20.50 | 0.28% |
| | `PLACE` | 17.59 | 0.24% |
| **Idle** | `PASS` | 408.83 | 5.54% |

---

## 3. Spatial Transit & Quadrant Congestion

### Movement by Quadrant
- **NW Quadrant (Home / Starter)**: 2,404.86 moves (**50.28%**)
- **NE Quadrant (Primary Expansion)**: 2,224.19 moves (**46.50%**)
- **SW Quadrant (Fringe / Unlocked)**: 80.59 moves (**1.68%**)
- **SE Quadrant (Locked)**: 73.46 moves (**1.54%**)

```
        NW Quadrant               NE Quadrant
  ┌──────────────────────┬──────────────────────┐
  │  2,404.86 moves      │  2,224.19 moves      │
  │  (50.28% of transit) │  (46.50% of transit) │
  │  [Primary Livestock, │  [High-Value Cash    │
  │   Wheat, Shed Access]│   Crops: Melons,     │
  │                      │   Strawberries]      │
  ├──────────────────────┼──────────────────────┤
  │    80.59 moves       │    73.46 moves       │
  │   (1.68% of transit) │   (1.54% of transit) │
  │  [Fringe Patrol]     │  [Border Navigation] │
  └──────────────────────┴──────────────────────┘
        SW Quadrant               SE Quadrant
```

### Analysis of the Hub-and-Spoke Bottleneck
The shed access points are situated exclusively at the inner quad intersection:
$$(4,4), (5,4), (4,5), (5,5)$$
Because NE crops (Melons, Strawberries) are planted far from the shed (average Manhattan distance $d = 6 \text{ to } 8$ steps), every seed planting, watering refill, and crop harvest requires a minimum round-trip transit of **12 to 16 steps per cycle**.

This structural layout imposes a heavy transit tax:
- A worker traveling from $(0,0)$ or $(9,0)$ to the shed consumes **8 hours** simply walking.
- Over 96% of all movement is concentrated in NW and NE, shuttling back and forth across the border meridian $x=4 \leftrightarrow x=5$.

---

## 4. Workforce Idle Capacity & Labor Allocation

Across workers (Unit 0 = Farmer, Units 1–12 = Hired Hands):

| Worker Index | Moves / Game | Idle Passes / Game | Total Work Actions / Game | Transit Share |
| :---: | :---: | :---: | :---: | :---: |
| **0 (Farmer)** | 441.23 | 43.19 | 235.58 | 61.3% |
| **1 (Hand 1)** | 421.32 | 50.26 | 248.42 | 58.5% |
| **2 (Hand 2)** | 433.67 | 46.22 | 240.11 | 60.2% |
| **3 (Hand 3)** | 419.10 | 51.77 | 249.13 | 58.2% |
| **4 (Hand 4)** | 405.90 | 51.38 | 262.72 | 56.4% |
| **5 (Hand 5)** | 340.90 | 27.33 | 211.77 | 58.8% |
| **6 (Hand 6)** | 372.54 | 22.88 | 184.58 | 64.2% |
| **7 (Hand 7)** | 371.07 | 24.81 | 184.12 | 64.0% |
| **8 (Hand 8)** | 369.70 | 24.75 | 185.55 | 63.7% |
| **9 (Hand 9)** | 314.82 | 16.98 | 148.20 | 65.6% |
| **10 (Hand 10)** | 311.10 | 16.40 | 152.50 | 64.8% |
| **11 (Hand 11)** | 294.18 | 16.57 | 169.25 | 61.3% |
| **12 (Hand 12)** | 287.57 | 16.29 | 176.14 | 60.0% |

### Idle Passes: 408.83 Passes / Game
- Workers execute an average of **408.83 PASS actions** per season (equivalent to 17 full worker-days of zero activity).
- Early workers (Farmer and Hands 1–4) account for 242.8 passes (59.4% of all idle turns).
- Root cause: On Days 0–5 and off-peak mid-day hours, tasks are exhausted or blocked awaiting market quotes or plant growth, resulting in unutilized labor.

---

## 5. Recoverable Value & Operational Verdict

1. **Theoretical Upper Bound**:
   - If transit overhead were cut by 50% (from 64.9% to 32.5%), **~2,390 worker actions** would be liberated.
   - 2,390 actions could perform ~400 additional crop cycles (seed + water $\times 4$ + harvest) or provide 100% livestock care and prompt harvests.
   - At ~$15 net profit per crop cycle, theoretical upper bound = **+$6,000/game**.

2. **Inferred Recoverable Value: `+$1,500 – $2,500 / game`**:
   - Realistic route bundling (e.g. batching waterings along contiguous rows, carrying seeds for multiple plantings, avoiding empty-handed return trips to shed) can physically save 400–600 moves per game.
   - Converting 400 moves into timely livestock harvests and elimination of missed cares captures **+$1,200 to +$2,200/game** directly.
