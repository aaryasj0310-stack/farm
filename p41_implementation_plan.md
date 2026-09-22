# Kaggriculture P4.1 Implementation Plan — Late-Season Isolated SW Zonal Acreage Expansion (Revised)

## 1. Executive Summary & Problem Formulation

In Phase P4.0, the authoritative economic audit established that:
1. The Promoted P2.3 Production Baseline (`536f1e7`) achieves a mean final score of **$101,836.36** across 100 games, leaving a remaining gap of **-$28,163.64** against the $130,000 project target.
2. The 2-quadrant core (NW+NE, 46 usable tiles) is **90–96% saturated** from Day 14 to Day 26 (only 1.8 to 4.7 empty tiles).
3. The farm amasses **$17,721 in cash by Day 13** and **$50,849 by Day 22**, with 13 active workers (1 farmer + 12 hands).
4. Micro-execution within the 46 tiles is exhausted (P3.1, P3.2, P3.3-A, P3.3-B, P3.4 rejected).
5. **The Sole Structural Frontier is Physical Acreage Expansion**: Reaching $130k physically requires more cultivating tiles.

This document presents the revised, rigorous implementation plan for **P4.1: Late-Season Isolated SW Zonal Acreage Expansion**, addressing all five user-required corrections:
1. **Incremental Labor Economics**: Rigorous proof that Hands 11 & 12 generate more net value in SW than in the crowded core.
2. **Explicit SW Crop Policy**: A feasible, deadline-aware planting and harvesting schedule for the 8 SW tiles.
3. **Actual Two-Worker Isolation**: Overriding the legacy 5-worker SW squad without breaking critical shed/feed logistics.
4. **Purchase and Activation Integrity**: Verifying the full order-execution path before authorized planting.
5. **Control Equivalence**: 100% bit-for-bit equivalence with `536f1e7` when disabled.
6. **Corrected Experimental Protocol**: A small 20-game instrumented feasibility test on fresh seeds `97,001–97,010` before any full tournament.

---

## 2. Incremental Labor Economics: Land Saturation vs. Labor Saturation

A central question is whether taking two workers (Hands 11 & 12) away from the core farm sacrifices valuable production in NW+NE.

### A. Realized Productivity of Hands 11 & 12 in the Core Farm
From the 100-game P3 workforce audit (`p3_hiring_roi_audit.md`):
- **Excess Walking Due to Congestion**: In the 46-tile core farm, 13 active workers create severe spatial congestion. Hands 11 and 12 spend **69.9% of their turns in transit**, executing only **5.28 productive actions per worker-day**.
- **Marginal Revenue Generated**: At ~$24 average net revenue per productive action, 5.28 actions produce ~$126.70 in daily revenue.
- **Daily Hiring Cost**: Hand 11 ($\text{fib}(10) = \$89$) and Hand 12 ($\text{fib}(11) = \$144$) cost $233/day combined ($116.50/worker-day).
- **Net Daily Profit in Core Farm**: $\$126.70 - \$116.50 = \mathbf{+\$10.20/\text{worker-day}}$.
- **Total Net Contribution over Days 14–29 (16 days)**:
  $$2 \text{ workers} \times 16 \text{ days} \times \$10.20/\text{day} = \mathbf{+\$326.40}.$$
  Hands 11 and 12 are operating at the bare edge of economic profitability in the core farm.

### B. Core Farm Labor Adequacy Without Hands 11 & 12
Can the remaining 11 workers (Farmer + Hands 1–10) maintain 100% of the core farm without Hands 11 & 12?
- **Core Farm Daily Workload (Days 14–29)**:
  - 11 livestock: 11 feed + 11 collect fertilizer + 11 care = 33 turns.
  - 15 strawberry tiles: 15 water + 7.5 harvest = 22.5 turns.
  - 17 wheat tiles: 17 water + 4.2 harvest = 21.2 turns.
  - Total daily core farm tasks = **~77 productive actions per day**.
- **Available Turns of Farmer + Hands 1–10**:
  - 11 workers $\times$ 24 turns = **264 worker-turns per day**.
  - Required productive action ratio: $77 / 264 = \mathbf{29.2\%}$.
  - This matches the natural physical efficiency of Hands 1–4 (29.5%) and Hands 5–8 (26.4%).
- **Conclusion**: **Farmer + Hands 1–10 provide 100% labor coverage for NW+NE.** Displacing Hands 11 & 12 to SW sacrifices at most **$\le \$400$** in net core value.

### C. Projected Labor Economics in the 8-Tile SW Zone
In the dedicated 8-tile SW zone directly adjacent to the shed:
- Hands 11 & 12 have a transit distance of only 1–3 tiles from the shed.
- Daily SW work:
  - 8 tiles watering = 8 turns/day.
  - Tilling/planting/harvesting = 4–8 turns/day.
  - Total daily SW tasks = **12–16 turns/day**.
- Hands 11 & 12 supply **48 turns/day** (2 $\times$ 24). They operate at a comfortable 25–33% workload, with zero task contention and minimal travel.
- **Net Economic Equation**:
  $$\text{Net Delta} = \text{Gross SW Revenue} - \text{SW Seed Cost} - \text{SW Land Cost (\$2,000)} - \text{Displaced Core Value (\$400)}.$$

---

## 3. Explicit SW Crop Portfolio & Planting Schedule

In the baseline configuration, `STRAWBERRY_PLANT_DEADLINE = 13` prohibits new strawberry planting after Day 13.
To guarantee feasible, deadline-aware production, P4.1 introduces an explicit **P4.1 SW Planting Controller** for the 8 tiles:

### Option 1: Dedicated SW Wheat Engine (Lowest Risk, Guaranteed Turnover)
- **Schedule**: 4 full 4-day wheat cycles across Days 14–29:
  - Cycle 1: Plant Day 14 -> Harvest Day 18.
  - Cycle 2: Plant Day 18 -> Harvest Day 22.
  - Cycle 3: Plant Day 22 -> Harvest Day 26.
  - Cycle 4: Plant Day 26 -> Harvest Day 29.
- **Physical Output**: 8 tiles $\times$ 4 cycles = 32 plantings $\times$ 6 yield = **192 units of wheat**.
- **Realized Economics**:
  - Gross Revenue: 192 units $\times$ $36.60 = **+$7,027.20**.
  - Seed Cost: 32 seeds $\times$ $10 = -$320.00.
  - Gross SW Profit: **+$6,707.20**.
  - Net Delta: $\$6,707.20 - \$2,000 \text{ (land)} - \$400 \text{ (core drag)} = \mathbf{+\$4,307.20}$.

### Option 2: P4.1 SW Post-Day 13 Strawberry Wave (Maximum Revenue Frontier)
- **Mechanics**: In the engine, strawberries have no hard deadline; they mature in 4 days and yield 2 units every 2 days indefinitely.
- **Schedule**: Planted Day 14. First harvest Day 18 (16 units), then Days 20, 22, 24, 26, 28 (5 harvests $\times$ 16 = 80 units). Total: 6 harvests = **96 units of strawberries**.
- **Realized Economics**:
  - Gross Revenue: 96 units $\times$ $245.58 = **+$23,575.68**.
  - Seed Cost: 8 seeds $\times$ $100 = -$800.00.
  - Gross SW Profit: **+$22,775.68**.
  - Net Delta: $\$22,775.68 - \$2,000 \text{ (land)} - \$400 \text{ (core drag)} = \mathbf{+\$20,375.68}$.

### Option 3: Balanced Hybrid Portfolio (Recommended for Initial Feasibility)
- **Allocation**: 4 tiles Strawberry + 4 tiles Wheat.
- **Physical Output**: 48 strawberries + 96 wheat.
- **Gross Revenue**: $(48 \times \$245.58) + (96 \times \$36.60) = \$11,787.84 + \$3,513.60 = **\$15,301.44**.
- **Seed Cost**: $(4 \times \$100) + (16 \times \$10) = -$560.00.
- **Gross SW Profit**: **+$14,741.44**.
- **Net Delta**: $\$14,741.44 - \$2,000 - \$400 = \mathbf{+\$12,341.44}$.

---

## 4. Actual Two-Worker Isolation: Overriding Legacy Squads & Logistics Invariants

### A. Overriding the Legacy 5-Worker Squad in `get_home_quadrant`
In `536f1e7` (`agent/execution/task_scheduler.py` line 1119), the baseline logic automatically assigns 5 workers (units 8, 9, 10, 11, 12) to SW when SW unlocks and roster $\ge 13$.

Under P4.1, this is **explicitly overridden**:
```python
def get_home_quadrant(u_idx, n_units, unlocked):
    if get_p41_sw_zonal_expansion_enabled() and "SW" in unlocked:
        # P4.1 Strict 2-Worker Zonal Allocation:
        # Only units 11 and 12 belong to the SW squad.
        if u_idx in (11, 12):
            return "SW"
        # Units 0 to 10 remain strictly partitioned between NW and NE:
        non_sw = 11  # units 0..10
        half = max(1, non_sw // 2)
        return "NW" if u_idx < half else "NE"

    # Baseline 536f1e7 fallback (exact preservation):
    if "SW" in unlocked and n_units >= 5:
        sw_squad_size = 5 if n_units >= 13 else 4
        sw_start = n_units - sw_squad_size
        if u_idx >= sw_start:
            return "SW"
        non_sw = sw_start
        half = max(1, non_sw // 2)
        return "NW" if u_idx < half else "NE"
    ...
```
**Effect**: Units 8, 9, and 10 remain permanently in NW and NE. Exactly 2 workers (11 and 12) are assigned to SW.

### B. Precision Task Eligibility Invariants & Safety Exceptions
We define the worker boundary by **task assignment**, not literal physical geometry:
1. **Discretionary SW Agricultural Tasks**:
   - Clearing weeds, tilling, planting, watering, and fertilizing on SW tiles ($y \ge 5, x < 5$) are strictly restricted: `_eligible(worker, task)` returns `True` **ONLY if `u_idx in (11, 12)`**. Core workers (Farmer + Hands 1–10) are permanently forbidden from taking SW crop tasks.
2. **Discretionary Core Agricultural Tasks**:
   - Hands 11 and 12 are barred from regular NW/NE crop tasks while SW tasks exist.
3. **Explicit Safety Exceptions (Permitted for ALL Workers)**:
   - **Central Shed Access**: Shed tiles `(4,4), (4,5), (5,4), (5,5)` may be accessed by any worker for product drop or feed pickup.
   - **Pathfinding / Transit**: Workers may step through boundary tiles when routing to the shed.
   - **Emergency Animal Rescue**: If an animal in the core is unfed at Hour $\ge 18$, any worker with wheat in hand may feed it.
4. **Telemetry Separation**: Physical tile crossings are logged separately from task assignments to distinguish incidental transit from task diversion.

---

## 5. Purchase & Activation Integrity: The Full Execution Pipeline

To ensure the land purchase executes reliably and does not desynchronize the agent:

```mermaid
sequenceDiagram
    participant M as Expansion Planner (should_buy_land)
    participant P as Macro Planner
    participant O as Order Builder
    participant A as Agent Main / Arbitration
    participant E as Game Engine
    participant S as Task Scheduler

    Note over M: Day >= 14, Cash >= $15,000, Core >= 90%
    M->>P: return True, "p41_sw_zonal_authorized"
    P->>P: plan.intents["buy_land"] = True
    P->>O: build market orders
    O->>A: orders.append(["BUY_LAND"])
    A->>E: submit action {"market": [["BUY_LAND"], ...]}
    E->>E: _do_buy_land() -> farm.money -= 2000, unlocked.append("SW")
    Note over S: Next turn: Check "SW" in farm.unlocked_quadrants
    alt SW is confirmed unlocked
        S->>S: Assign Hands 11 & 12 to SW; Activate SW Crop Controller
    else SW purchase failed / pending
        S->>S: Hands 11 & 12 continue core NW+NE baseline duties
    end
```

### Complete Pipeline Verification:
1. **Gate Authority**: In `agent/strategy/expansion_planner.py`, `should_buy_land()` contains an authoritative P4.1 branch:
   - Evaluates: `P41_SW_ZONAL_EXPANSION_ENABLED = True`, `next_quadrant == 3`, `current_day >= 14`, `money >= 15000.0`, `core_occupancy >= 0.90`, `worker_count >= 13`.
   - Returns `True, "p41_sw_zonal_authorized", diag`.
2. **Order Emit**: `macro_planner.py` sets `plan.intents["buy_land"] = True`. `order_builder.py` appends `["BUY_LAND"]`.
3. **Arbitration Passthrough**: In `main.py`, `QUADRANT_HARD_BLOCK = {4}` blocks SE (quadrant 4). SW (quadrant 3) is allowed to pass through into `reconciled_orders`.
4. **Post-Purchase Activation Barrier**: SW planting and dedicated SW squad allocation activate **ONLY IF `"SW" in farm.unlocked_quadrants`**. If the order fails or is delayed, Hands 11 & 12 remain 100% in their baseline core roles.

---

## 6. Control Equivalence: Zero-Regression Guarantee

When `P41_SW_ZONAL_EXPANSION_ENABLED = False`:
- `get_home_quadrant()` executes the exact legacy code.
- `should_buy_land()` rejects SW via baseline logic.
- SW planting controller is dormant.
- The agent reproduces `536f1e7` 100% bit-for-bit.

---

## 7. Corrected Experimental Design & Seed Protocol

### Seed History Audit & Fresh Block Reservation
- **Historical Seed Usages**:
  - P3.1 Evaluation: `90,001–90,050`
  - P3.2 Evaluation: `92,001–92,050`
  - P3.3-A Smoke: `92,991–92,995`
  - P3.3-A Evaluation: `93,001–93,050`
  - P3.4 / Early Diagnostic Block: `94,001–94,050`
  - P3.4 Feed Logistics: `95,001–95,010`
  - P4.0 Economic Audit: `96,001–96,050`
- **Completely Fresh, Untouched Seed Allocations for P4.1**:
  - **Phase 1: Instrumented Feasibility Test**: **Seeds 97,001–97,010** (10 pairs $\times$ 2 seats = 20 matched games across 5 opponents).
  - **Phase 2: Formal Held-Out A/B Tournament** (executed ONLY if Phase 1 passes): **Seeds 98,001–98,050** (50 pairs $\times$ 2 seats = 100 matched cases = 200 live games).

---

## 8. Two-Tiered Promotion & Rejection Criteria

### Tier 1: Feasibility Test Gate (20 Games, Seeds 97,001–97,010)
- **Objective**: Verify mechanism telemetry and safety before running the 200-game tournament.
- **Passing Criteria**:
  1. `BUY_LAND` executes cleanly on Day 14; SW unlocks.
  2. Exactly 2 workers (Hands 11 & 12) perform SW agricultural tasks; core workers perform 0 SW crop tasks.
  3. 8 SW tiles are successfully tilled, planted, watered, and harvested.
  4. Core farm watering compliance remains $\ge 98.0\%$ (zero watering regression).
  5. Zero negative cash steps; zero animal starvation.
  6. Score delta is non-negative ($\Delta \ge +\$0.00$).

### Tier 2: Formal Tournament Criteria (200 Games, Seeds 98,001–98,050)
- **Statistical Significance**: Paired delta $t$-test achieves $p < 0.05$ with 95% CI lower bound $> +\$500.00$.
- **Business Target**: Mean paired delta $\Delta \ge +\$3,500.00$ per game.
- **Safety Invariants**: 0 negative cash steps, 0 starvation days, core gross revenue within $\pm \$500$ of Control.
- **Rejection Trigger**: $p \ge 0.05$ with CI crossing zero, or core farm revenue destruction $> \$1,500$, or any solvency failure.

---

## 9. Empirical Feasibility Test Results & Final Verdict

The Tier 1 Instrumented Feasibility Test was executed across 20 matched pairs (40 live games across 5 opponents, balanced seats) on fresh seed block `97,001–97,010`:

### Key Metrics Summary:
- **Control Baseline Mean**: **$100,366.65**
- **Treatment Mean**: **$95,547.55**
- **Paired Score Delta**: **-$4,819.10** (95% CI: [-$11,531.97, +$1,893.77], $SE = \$3,207.29$)
- **Core Watering Compliance**: Dropped from **84.25%** (Control) to **79.80%** (Treatment), a **-4.45%** absolute drop.
- **Core Plant Deaths**: Increased from **263.55** (Control) to **284.90** (Treatment) per game (+21.35 crop deaths/game).
- **SW Execution Telemetry**:
  - SW purchase executed cleanly on Day 14 in 20/20 games.
  - Hands 11 & 12 executed 2,598 SW agricultural actions; core workers executed only 1 action (perfect isolation).
  - Physical harvests: 241 strawberries + 853 wheat harvested across 20 games (avg 12.05 strawberries + 42.65 wheat/game).
  - Direct gross SW revenue: ~+$4,520/game.
  - Seed cost: -$560/game; Land purchase cost: -$2,000/game.
  - Net SW gross profit: **+$1,960/game**.
- **The Failure Mechanism (Labor Saturation Proved)**:
  - Displacing Hands 11 & 12 out of the core farm deprived the 46-tile core farm of critical watering slack during peak Day 16–28 strawberry cycles.
  - The resulting 21.35 extra plant deaths and missed repeat yields destroyed **-$6,779/game** in core revenue.
  - **Net Realized Delta**: $+\$1,960 - \$6,779 = \mathbf{-\$4,819.10/\text{game}}$.

### Tier 1 Feasibility Gate Evaluation:
| Criterion | Target | Realized | Status |
| :--- | :--- | :--- | :--- |
| Clean Day 14 Unlock | 100% (20/20) | 100% (20/20) | **PASSED** |
| 2-Worker Isolation | Hands 11 & 12 only | 2,598 vs 1 action | **PASSED** |
| Solvency & Herd Safety | 0 negative cash, 0 starvation | 0 negative cash, 0 starvation | **PASSED** |
| Core Watering Compliance | $\ge 98\%$ retention ($\ge 82.5\%$) | 79.80% (-4.45%) | **FAILED** |
| Score Delta | $\ge +\$0.00$ | **-$4,819.10** | **FAILED** |

### Final Verdict: REJECTED
P4.1 fails the Tier 1 Feasibility Gate.
- **DO NOT proceed to the 200-game tournament on `98,001–98,050`** (preserving this fresh seed block for future treatments).
- `P41_SW_ZONAL_EXPANSION_ENABLED` remains locked to `False` (100% bit-for-bit control equivalence).

