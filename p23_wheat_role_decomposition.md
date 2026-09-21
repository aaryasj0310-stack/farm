# Kaggriculture P2.3 — Wheat Role & Economic Decomposition

## Four-Bucket Economic Classification

Based on the 20-game telemetry audit, each wheat unit and planting cohort is classified into its functional and economic role:

| Bucket | Category | Units / Game | Equivalent Tiles | Economic Purpose & Realized Value |
| :---: | :--- | :---: | :---: | :--- |
| **A** | **Mandatory Feed Wheat** | **211.7 units** | **62.3 tiles** | Keeps ~10–11 animal herd alive through Day 28. Net value is the livestock enterprise contribution: **+$30,597/game** (~$144.50/unit of feed). |
| **B** | **Strategic Feed Buffer** | **44.0 units** | **12.9 tiles** | 4-day survival buffer (`animals * 4 = 44`) held to prevent starvation across harvest delays and weather variance. Preserves livestock safety. |
| **C** | **Viable Commercial Wheat** | **78.0 units** | **22.9 tiles** | Mid-season wheat harvests that are sold for market revenue at ~$25/unit ($1,950 gross revenue, ~$75 net revenue per tile over 5 days = $15/tile/day). |
| **D** | **Excess / Displacing Wheat** | **35.6 units** | **10.6 tiles** | Late/terminal wheat plantings (especially Days 25–27) that either produce zero yield (mature post-season) or produce low-margin commercial wheat that directly displaces high-margin CARROT ($22.50/tile/day). |

---

## Detailed Bucket Analysis

### Bucket A: Mandatory Feed Wheat (211.7 units / game)
- **Role**: Essential fuel for the livestock engine.
- **Consumption Profile**:
  - Days 0–9: 2 cows consume 2 units/day (20 units total).
  - Days 10–13: Herd ramps from 4 to 10 animals, consuming 3.7 to 9.8 units/day (~26 units total).
  - Days 14–28: Full 11-animal herd consumes 11 units/day $\times$ 15 days = 165 units.
- **Total Physical Consumption**: 211.7 units.
- **Economic Value**: Without this wheat, animals escape and lose $30,597 in milk, wool, and care bonuses. Feed wheat is overwhelmingly the highest-value crop per unit on the farm ($144.50 net contribution per unit).

### Bucket B: Strategic Feed Reserve (44.0 units / game)
- **Role**: Risk mitigation against logistical and growth delays.
- **Buffer Target**: The engine maintains an operational buffer of `animals * FEED_WHEAT_BUFFER_DAYS` (4 days $\times$ 11 animals = 44 units).
- **Economic Justification**: Prevents sudden starvation when field workers are occupied with urgent strawberry watering or melon harvesting.

### Bucket C: Viable Commercial Wheat (78.0 units / game)
- **Role**: Surplus wheat produced from early/mid-season tranches (Days 0–19).
- **Market Dynamics**: Sold across Days 5–24 during normal sell windows at $25/unit.
- **Economic Reality**:
  - Gross revenue: 3.40 units $\times$ $25 = $85.00/tile.
  - Seed cost: -$10.00.
  - Realized gross margin: $75.00/tile over 5 calendar days ($15.00/tile/day).
  - While profitable in isolation, its return per tile-day is significantly lower than CARROT.

### Bucket D: Excess / Low-Value Wheat (35.6 units / game, ~10.6 tiles)
- **Role**: Unnecessary late-season replantings.
- **Component 1: Terminal Waste (6.10 tiles on Days 26–27)**:
  - Planted on Days 26 and 27 because the continuous replanting engine blindly refills to 20 tiles whenever a tile empties.
  - Wheat takes 4 full days to mature (`planted_day + 4`).
  - Day 26 planting matures on Day 30 (after season ends).
  - Day 27 planting matures on Day 31 (after season ends).
  - **Yield: 0 units. Revenue: $0.00. Seed capital wasted: $61.00. Labor wasted: 6 planting actions.**
- **Component 2: Late Commercial Substitution (4.5 tiles on Days 24–25)**:
  - Matures on Days 28–29 when all livestock feed obligations are already satisfied.
  - Sold at $25/unit, earning $85/tile ($15/tile/day).
  - Displaces CARROT planted on the same tile:
    - CARROT seed: $20. Cycle: 3 days. Max yield: 4 units at $35 = $140 gross. Net: $120/tile over 4 days = **$30.00/tile/day**.
    - Opportunity cost of planting commercial wheat instead of carrot: **-$15.00 per tile-day!**

---

## The Root Cause in Production Code

In [`agent/strategy/macro_planner.py`](file:///d:/website%20project/kaggri%20ox/agent/strategy/macro_planner.py#L2343-L2386):
```python
# Continuous wheat replanting engine (Leader-Calibrated: 8/20/30 active wheat tiles)
n_quads = len(farm.unlocked)
quadrant_wheat_target = (
    8 if (n_quads == 1 or day <= 9)
    else (20 if (n_quads == 2 or day <= 13) else 30)
)
wheat_cap = min(len(empty_tiles) + existing_wheat, quadrant_wheat_target)
wheat_needed = max(0, wheat_cap - existing_wheat)
wheat_to_plant = min(wheat_needed, len(empty_tiles))
```

### Three Structural Flaws Identified:
1. **No Planting Deadline Guard**: The block has zero check for whether wheat planted today can mature by Day 29 (`_crop_allowed_today("WHEAT", day)` is never called). This causes the 6.1 terminal wasted tiles on Days 26–27.
2. **Static Unconditional Target**: The target of 20 tiles is rigid from Day 10 to Day 27. It does not look at actual herd feed requirements or current shed inventory.
3. **Preempts Economic Crop Scoring**: Because this block runs *before* Phase 2b (the general crop loop), empty tiles are forcibly claimed for WHEAT before CARROT or any other crop can even be evaluated.
