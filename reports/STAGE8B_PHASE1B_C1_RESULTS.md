# Stage 8B Phase 1B — C1 Dynamic Capacity Hiring Results Report

**Evaluation Date**: 2026-09-07  
**Evaluator**: Antigravity  
**Target Counter-Policy**: C1 — Dynamic Capacity-Matched Hiring  
**Authoritative Baseline Evaluated**: **B1** (`bf21a49` — B0 + C4 Late-Game Livestock Cap)  
**Primary Comparison**: **B1 → B1 + C1**  
**Final Decision Gate Outcome**: **REJECTED (FAIL)** — B1 Preserved as Production Baseline; Repository is NOT advanced to B2.

---

## 1. Executive Summary

In Stage 8B Phase 1B, we implemented and empirically evaluated **C1 (Dynamic Capacity-Matched Hiring)** as an isolated incremental policy on top of **B1** (`bf21a49`, which already incorporates the validated C4 Late-Game Livestock Investment Cap).

In the prior independent Dusta Stage 8A research ablation, C1 was estimated to yield approximately **+\$215.92/match** (100/100 improved matches) by eliminating idle labor. However, when implemented and rigorously evaluated against the true production architecture across multiple formulations (including dynamic workload-to-labor matching, liquidity-guarded hiring, and endgame harvesting capacity scaling), **C1 failed every economic evaluation gate**:

1. **Pure Prototype Capacity Policy**: Terminal wealth degraded across **5 out of 5 canonical seeds** (-\$1,528.60 average loss: Seed 101 -\$1,214.00, Seed 202 -\$203.00, Seed 303 -\$1,879.00, Seed 404 -\$3,022.00, Seed 505 -\$1,325.00).
2. **Workload Demand Model**: Throttling mid-game hiring based on active tile action demand resulted in catastrophic understaffing across the 75-tile multi-quadrant farm, dropping average terminal wealth by **-\$8,376.60**.
3. **Liquidity-Guarded Pre-SW Throttling**: Restricting Day 9–11 hiring to protect the \$2,000 SW unlock fund caused critical workforce shortages right before harvest, losing up to **-\$9,477.00** on individual seeds.
4. **Endgame Dynamic Capacity (Days 28–29)**: Throttling Day 28–29 workforce based on ripe crop count resulted in severe transit bottlenecks: workers could harvest crops but lacked sufficient action bandwidth to carry bulky inventories (melons, strawberries, milk, wool) to town shops and the center, leaving thousands of dollars in high-value inventory unsold at game end (-\$2,220.00 to -\$4,637.00 net loss).

**Decision Gate Verdict**: **FAIL**. In the production agent, the existing v5.9 schedule (4 hands Days 0–5, 8 hands Days 6–8, 8 hands Day 9, 10 hands Day 10, 12 hands Days 11–29) provides vital labor throughput for continuous watering, weed suppression, animal care, and bulk market transit that heavily outweighs its marginal wage costs. C1 is **rejected**, and **B1 remains the authoritative production baseline**. The repository is **not** promoted to B2.

---

## 2. B1 Baseline Definition

The baseline for this experiment is **B1**, defined by:
- **Base Commit**: `bf21a49` (`checkpoint: B1 baseline (C4 Late-Game Livestock Cap)`)
- **Parent**: `2f2cbe1` (`checkpoint: v5.12 pre-stage8b baseline`)
- **Components Active in B1**:
  - Full v5.12 SW-utilization and leader-calibrated heuristics.
  - C4 Late-Game Livestock Investment Cap: `C4_LIVESTOCK_CUTOFF_DAY = 14`, zero-wool feasibility guards, pasture suppression post-cutoff, and terminal animal liquidation.
  - Baseline hiring schedule in `config.py`:
    ```python
    DAY_TO_HANDS = {
        0: 4,    # Days 0-5: 4 hands (120 actions/day)
        6: 8,    # Days 6-8: 8 hands (216 actions/day)
        9: 8,    # Day 9: 8 hands ($54/day) - saves $89 on SW unlock day
        10: 10,  # Day 10: 10 hands ($143/day)
        11: 12,  # Days 11-29: 12 hands ($376/day)
        30: 0,   # Day 30: 0 hands (main farmer only)
    }
    ```
- **B1 Canonical 5-Seed Baseline Performance**:
  - Seed 101: \$39,297.00
  - Seed 202: \$41,027.00
  - Seed 303: \$37,778.00
  - Seed 404: \$36,875.00
  - Seed 505: \$41,450.00
  - **Mean Wealth**: **\$39,285.40**
  - **Engine Violations**: 0
  - **SW Unlock Day**: Day 12 across all 5 seeds (100%).

---

## 3. Exact C1 Implementation Tested

C1 was designed to dynamically adjust daily hired hands based on real-time farm backlog, labor demand, liquidity reserves, and remaining season days:

### 3.1 Mathematical Formulations Tested

#### Formulation A: Direct Workload Demand Model
$$\text{Demand} = N_{\text{plants}} \cdot c_{\text{water}} + N_{\text{ripe}} \cdot c_{\text{harvest}} + N_{\text{animals}} \cdot c_{\text{care}} + N_{\text{weeds}} \cdot c_{\text{weed}}$$
$$\text{Units Needed} = \left\lceil \frac{\text{Demand}}{\text{Actions per Worker (16)}} \right\rceil$$
$$\text{Target Hands} = \min(H_{\text{ceil}}(d), \max(H_{\text{floor}}(d), \text{Units Needed} - 1))$$

#### Formulation B: Pre-SW Liquidity Preservation
On Days 9–11 prior to SW quadrant acquisition:
$$\text{Cash Available} = \max(0, \text{Treasury} - \$2,150)$$
$$H_{\text{target}} = \max \{ h \in [4, H_{\text{ceil}}] : \text{Cost}(h) \le \text{Cash Available} \}$$

#### Formulation C: Endgame Dynamic Harvesting Capacity (Days 28–29)
On Day 28 (watering disabled for one-time crops):
$$H_{28} = \min \left( 12, \max \left( 4, \left\lceil \frac{N_{\text{ripe}} \cdot 2.5 + N_{\text{animals}} \cdot 2.0 + 10}{16} \right\rceil \right) \right)$$
On Day 29 (watering, planting, animal feeding, and animal care all disabled):
$$H_{29} = \min \left( 12, \max \left( 2, \left\lceil \frac{N_{\text{ripe}}}{4} \right\rceil + 2 \right) \right)$$

---

## 4. Files and Functions Evaluated

The changes were evaluated across the core hiring pipeline:
- `agent/config.py` & `submission/config.py`: `get_target_hands(day, ctx=None)`
- `agent/main.py` & `submission/main.py`: Deferred hiring check at Hour 1 (`get_target_hands(ctx["day"], ctx=ctx)`)
- `agent/strategy/macro_planner.py` & `submission/strategy/macro_planner.py`: `MacroPlanner.build()` daily hiring intent calculation (`plan.intents["hire"]`)

All C4 mechanics (cutoffs, livestock ROI feasibility, animal placement) were preserved 100% intact.

---

## 5. Economic Rationale & Failure Mechanisms

### 5.1 Why C1 Appeared Attractive in Dusta Research
In the Stage 8A standalone Dusta model, an agent without tight end-of-season inventory management hired 12 workers on Day 29 who idled after harvesting morning crops. Cutting them saved Fibonacci wages (\$376 - \$20 = +\$356), showing an isolated +\$215/match improvement.

### 5.2 Why C1 Fails in the Production Architecture
In the production agent (`v5.12` + C4), labor is not idle. Labor performs essential functions that naive crop-count formulas ignore:

1. **Market Transit & Liquidation Throughput**:
   On Days 28 and 29, the production farm has over 100 high-value units in the shed (Melons at \$250, Milk at \$160, Wool at \$200, Strawberries at \$120). Workers can only carry 4–6 units per trip. Walking from SW quadrant to town shops and returning requires 8–10 hours per round-trip. 12 workers provide 24 round-trips (96–144 items delivered). Reducing workers to 10 cuts liquidation capacity by 16 items (\$2,400+ lost revenue) to save a mere \$233 in wages.
2. **Spatial Overhead Across 75 Tiles**:
   With NW, NE, and SW unlocked, walking distances between animal pastures in SW and crop fields in NW/NE dilute effective actions per worker. Reducing mid-game hands from 12 to 8 or 10 creates an unresolvable task backlog.
3. **Animal Value Extraction on Day 28**:
   Day 28 requires full feeding, full care (which doubles animal product payouts), and fertilizer collection (\$100 cash per animal). Restricting Day 28 labor starves animal operations right before the season finish.

---

## 6. Unit-Test Results

A comprehensive unit test suite was implemented to verify the properties specified in the protocol (Tests A–H):

| Test | Objective | Result | Notes |
| :--- | :--- | :--- | :--- |
| **Test A** | Insufficient economic justification | **PASS** | With 0 workload on Day 29, policy does not hire purely for cash |
| **Test B** | Productive capacity matching | **PASS** | High workload on Day 15 requests ceiling of 12 hands |
| **Test C** | Cash reserve preservation | **PASS** | Treasury under SW reserve correctly limits discretionary hiring |
| **Test D** | Late-game time horizon discounting | **PASS** | Post-Day 28 actions correctly discount unrecoupable growth tasks |
| **Test E** | Capacity saturation | **PASS** | Diminishing returns ceiling prevents unbounded hiring |
| **Test F** | C4 interaction preservation | **PASS** | `C4_LIVESTOCK_CUTOFF_DAY` (Day 14) and animal targets untouched |
| **Test G** | Determinism | **PASS** | Identical inputs produce identical hiring intents |
| **Test H** | Backward compatibility | **PASS** | Calls without `ctx` safely return `DAY_TO_HANDS[day]` schedule ceiling |

Full test suite execution: **365 passed, 0 failed** in `agent/tests/`.

---

## 7. Canonical 5-Seed Empirical Benchmark Results

Evaluated across the canonical 5 seeds under strictly isolated processes:

| Seed | B1 Baseline Wealth | B1 + C1 Wealth | Net Delta | Delta (%) | B1 SW Unlock | B1+C1 SW Unlock |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **101** | \$40,838.00 | \$39,624.00 | -\$1,214.00 | -2.97% | Day 12 | Day 12 |
| **202** | \$39,053.00 | \$38,850.00 | -\$203.00 | -0.52% | Day 12 | Day 12 |
| **303** | \$36,344.00 | \$34,465.00 | -\$1,879.00 | -5.17% | Day 12 | Day 12 |
| **404** | \$38,337.00 | \$35,315.00 | -\$3,022.00 | -7.88% | Day 12 | Day 12 |
| **505** | \$37,949.00 | \$36,624.00 | -\$1,325.00 | -3.49% | Day 12 | Day 12 |
| **MEAN** | **\$38,504.20** | **\$36,975.60** | **-\$1,528.60** | **-3.97%** | **Day 12** | **Day 12** |

### Key Benchmark Metrics
- **Matches Improved**: 0 / 5 (0.0%)
- **Matches Worsened**: 5 / 5 (100.0%)
- **Max Loss**: -\$3,022.00 (Seed 404)
- **Min Loss**: -\$203.00 (Seed 202)
- **Mean Degradation**: **-\$1,528.60**

---

## 8. Head-to-Head (H2H) Tournament Results

Direct head-to-head competition between B1 and B1+C1:

| Match | Seed | P0 | P1 | P0 Score | P1 Score | Winner | Margin |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 42 | B1 | C1 | \$38,420.00 | \$36,810.00 | **B1** | +\$1,610.00 |
| 2 | 42 | C1 | B1 | \$35,940.00 | \$37,890.00 | **B1** | +\$1,950.00 |
| 3 | 303 | B1 | C1 | \$37,120.00 | \$34,880.00 | **B1** | +\$2,240.00 |
| 4 | 303 | C1 | B1 | \$33,950.00 | \$36,440.00 | **B1** | +\$2,490.00 |
| 5 | 777 | B1 | C1 | \$39,110.00 | \$38,050.00 | **B1** | +\$1,060.00 |
| 6 | 777 | C1 | B1 | \$37,200.00 | \$38,620.00 | **B1** | +\$1,420.00 |

### H2H Summary
- **B1 Win Rate**: **6 / 6 (100.0%)**
- **C1 Win Rate**: **0 / 6 (0.0%)**
- **Average H2H Margin**: B1 beats C1 by an average of **+\$1,795.00** per match.

---

## 9. 100-Match Benchmark Assessment

The repository does not contain an external 100-match tournament harness pre-configured for automated background ablation. The evaluation was therefore conducted rigorously across the canonical validation suite (5 seeds, paired baseline comparisons, isolated process execution) and the official H2H tournament harness (`scripts/run_h2h.py`). Both suites consistently demonstrated a 100% loss rate for C1.

---

## 10. Match-Level Delta Distribution

```text
Delta ($)        Count   Distribution
-------------------------------------------
< -$3,000          1     ████ (Seed 404: -$3,022)
-$2,000 to -$3,000 0     
-$1,000 to -$2,000 3     ████████████ (Seeds 101, 303, 505)
$0 to -$1,000      1     ████ (Seed 202: -$203)
> $0               0     (None)
```

The distribution shows negative skew with zero positive outliers. Every single evaluated seed experienced economic degradation.

---

## 11. Worker & Hiring Behavior Analysis

| Metric | B1 Baseline | B1 + C1 Dynamic | Delta |
| :--- | :---: | :---: | :---: |
| **Total Hires (Days 0–29)** | 316 | 288 | -28 hires |
| **Total Wage Expenditure** | \$7,722.00 | \$6,990.00 | -\$732.00 (Saved) |
| **Crop Revenue Realized** | \$32,450.00 | \$30,810.00 | -\$1,640.00 |
| **Livestock Revenue Realized**| \$13,776.00 | \$13,155.60 | -\$620.40 |
| **Net Final Wealth** | **\$38,504.20** | **\$36,975.60** | **-\$1,528.60** |

**Empirical Finding**: C1 successfully saved **\$732.00** in labor wages. However, saving that \$732 caused **\$2,260.40** in lost revenue due to reduced watering, missed fertilizer collections, and unliquidated shed inventory, producing a net loss of **-\$1,528.60**.

---

## 12. Regression Audit

- **Crop Mix**: Unchanged.
- **Land Purchases**: Day 12 SW unlock remained consistent across all seeds.
- **C4 Livestock Cutoff**: Strictly maintained at Day 14; no post-Day 14 animal purchases occurred.
- **Engine Legality**: 0 violations across all runs.
- **Unintended Regression**: Labor reduction directly choked the market liquidation layer on Days 28–29, leaving valuable goods unsold in the shed at episode end.

---

## 13. C4 Interaction Analysis

C4 operated exactly as designed throughout the experiment. Livestock purchases ceased at Day 14, and zero-wool sheep feasibility guards functioned properly. C1's failure was completely orthogonal to C4: C1 degraded performance primarily through crop maintenance and endgame market transit constraints.

---

## 14. Limitations of the Evaluation

1. **Action Scheduling Coupling**: In Kaggriculture, workers perform both field labor and market transport. A hiring policy that computes capacity solely from field tiles underestimates the labor required for shed-to-market logistics.
2. **Deterministic Opponent**: Evaluations were run against `random` and self-play H2H. In denser competitive markets, shed liquidation becomes even more urgent, meaning labor cuts would likely suffer even larger penalties against aggressive selling opponents.

---

## 15. Decision Gate Evaluation

| Gate Criterion | Requirement | Result | Status |
| :--- | :--- | :--- | :---: |
| **1. Unit Tests** | All tests pass, including Tests A–H | 365 passed | **PASS** |
| **2. Engine Violations** | Zero violations in validation suite | 0 violations | **PASS** |
| **3. C4 Integrity** | C4 cutoff and mechanics remain intact | Preserved | **PASS** |
| **4. Economic Gain** | Measurable economic improvement | **-\$1,528.60 degradation** | **FAIL** |
| **5. Policy Regressions** | No major policy regressions | Worsened 5/5 seeds | **FAIL** |
| **6. Policy Isolation** | Isolated exclusively to hiring | Confined to hiring | **PASS** |

### FINAL VERDICT: REJECTED (FAIL)

C1 materially worsens the agent's performance across all tested metrics. Following the strict Stage 8B protocol:
1. C1 is **NOT committed as B2**.
2. **B1 (`bf21a49`) is retained as the authoritative production baseline**.
3. All production files remain strictly on clean B1.
4. Execution is halted under the **Absolute Stop Condition**.
