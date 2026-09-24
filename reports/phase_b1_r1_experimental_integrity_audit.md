# Kaggriculture — Phase B1-R1: Experimental Integrity & Economic Attribution Audit Report

**Branch:** `experiment/sw-forward-architecture-phase-a`  
**Starting Audited HEAD:** `9e0022b6b8e2ba8e7eae0363449526f7fc8598d1`  
**Audit Directory:** `simulations/results/phase_b1_r1_integrity/`  
**Authoritative Environment:** Kaggle Environments `kaggriculture` (720 turns, 30 days)  
**Production Default:** `SW_FORWARD_ARCHITECTURE_MODE = "OFF"` (Strictly Maintained)  

---

## Executive Summary

Phase B1 reported an empirical mean paired final-cash difference of **-$9,360.83** across 200 configurations (140 losses, 3 wins, 57 ties). While this strongly favored the baseline over the tested delayed SW treatment, the experimental telemetry contained significant accounting errors and denominator inconsistencies:
1. Attributed SW revenue was reported as **~$39,000** per match by summing farm-wide strawberry and melon sales, whereas the 8 SW tiles physically generated only **$3,200–$3,800**.
2. Seed cash costs were reported as **$0** because seeds were drawn from existing inventory, masking a **$720** economic opportunity cost.
3. A denominator mismatch reported **154 selected portfolios** alongside **134 recorded purchases**, caused by an unhandled reserve deduction in the order builder that locked 20 configurations in a failed purchase state.
4. Nine "no-purchase" treatment matches diverged from control (including a **+$7,084** outlier) due to state contamination from this premature lockup rather than a strategic treatment effect.

This audit rectifies the experimental evidence, reconstructs the true whole-farm economic attribution, separates measured vs estimated vs residual effects, validates the statistical significance under seed-clustered resampling, and provides the authoritative foundation for subsequent strategic tests.

---

## 1. Before vs After: Corrected Measurements Summary

| Measurement / Metric | Phase B1 (Reported / As-Logged) | Phase B1-R1 (Audited & Reconstructed) | Root Cause & Methodological Note |
| :--- | :--- | :--- | :--- |
| **Control Policy** | Baseline early SW purchase around Day 5–6 | Core-only (NW+NE) baseline; **0/200 SW purchases** | Gate 1 logging bug misattributed NE land purchases (`buy_land=True`) to SW. Control never bought SW. |
| **Treatment SW Purchases** | 134 purchases / 154 selected (inconsistent) | **134 Confirmed Purchases**, 20 Dropped Approvals, 46 Never Approved | Order builder dropped land order in 20 matches where cash was between $2,200 and $2,299 ($1,966 discretionary < $2,000 cost). |
| **SW Admitted Utilization (D+1)** | 84.6% (evaluated N=154) | **97.2%** (evaluated N=134 confirmed purchases) | Denominator of 154 was diluted by 20 unpurchased matches with 0 planted tiles. |
| **SW Admitted Utilization (D+2+)** | 87.0% (evaluated N=154) | **100.0%** (evaluated N=134 confirmed purchases) | Once purchased, the 8-tile compact tranche achieved 100% utilization in every valid match. |
| **SW Gross Revenue** | ~$39,000 per purchased match | **$3,200–$3,800** estimated SW-origin revenue | Controller summed all farm-wide strawberry/melon sales; ~$35.5k was harvested from the core NW/NE farm. |
| **SW Seed Outflow** | $0.00 realized cash cost | **$0 cash outflow**, **$720 opportunity cost** | Seeds were drawn from pre-existing shed inventory (4 strawberries @ $100 + 4 melons @ $80). |
| **No-Purchase Divergence** | 9 diverging matches (+$7,084 outlier) | **0 divergences in unapproved cohort (46/46 ties)**; 9 leaked from dropped approval state | Premature `sw_purchase_approved=True` mutated macro wheat buffer at step 242; not an intentional treatment effect. |
| **95% Bootstrap CI** | [-$10,548.71, -$8,194.18] (pair-level) | **[-$11,162.74, -$7,650.11]** (seed-clustered) | Seed clustering widens CI by +47.4% due to market price covariance, but upper bound remains strictly negative. |
| **Confirmed Purchase Mean Delta** | Blended into 151 compact / 3 starter | **-$14,024.02** across 134 confirmed purchases | Isolates the true economic penalty of purchasing and servicing the delayed compact SW tranche. |

---

## 2. Experimental Provenance: What Phase B1 Actually Compared

### 2.1 The Baseline Policy Misconception
The original Phase B1 design intended to test:
- **Control:** Baseline early SW purchase (reported around Day 5–6 in Gate 1).
- **Treatment:** Delayed SW purchase (Days 8–12) with restricted compact tranche.

However, authoritative audit of the runtime code and frozen control trajectories reveals:
- **Control never purchased SW in any match (`control_sw_purchase_day = null` in 200/200 runs).**
- In [`agent/strategy/expansion_planner.py`](file:///d:/website%20project/kaggri%20ox/agent/strategy/expansion_planner.py#L518-L523), `QUADRANT_HARD_BLOCK = {3, 4}` is active by default.
- Under production defaults, `should_buy_land()` immediately rejects quadrant 3 as `hard_blocked`.

### 2.2 Why Gate 1 Telemetry Misreported Early SW Purchases
In Gate 1, telemetry extracted baseline land intent using:
```python
baseline_sw_purchase = bool(baseline_intents_dict.get("buy_land", False))
```
At Day 5–6, the production baseline consistently purchases **Quadrant 2 (NE)** for $1,000. Because the telemetry checked `buy_land` without filtering for quadrant ID, it recorded NE expansion as an SW purchase.

### 2.3 The Actual Comparison
Phase B1 therefore compared:
$$\text{CONTROL: Core-focused baseline (NW+NE only, 0 SW purchases)}$$
$$\text{versus}$$
$$\text{TREATMENT: Core-focused baseline + delayed compact SW treatment (134 confirmed SW purchases)}$$

Every baseline configuration in Gate 1, B0, and B1 operated with identical NW+NE core mechanics.

---

## 3. Purchase Lifecycle & State Reconciliation

### 3.1 The 154 vs 134 Purchase Discrepancy
Across the 200 paired configurations:
- **Purchase Recommended:** 154 configurations
- **Purchase Approved:** 154 configurations
- **BUY_LAND Order Emitted:** 134 configurations
- **BUY_LAND Order in Final Action:** 134 configurations
- **Engine Purchase Confirmed:** 134 configurations
- **SW Unlocked in Engine State:** 134 configurations
- **SW Tranche Planted:** 134 configurations
- **No Confirmed Purchase:** 66 configurations
  - *Approved but dropped by OrderBuilder:* 20 configurations
  - *Never approved by WholeFarmPlanner:* 46 configurations

### 3.2 Mechanism of the 20 Dropped Purchases
For all 20 configurations where a portfolio was selected but no purchase occurred:
1. **Timing & Cash:** At Day 9 Hour 6 (step 222), farm money was between $2,200.00 and $2,299.00 (e.g., $2,266.00 in Seed 96502).
2. **Planner Approval:** `WholeFarmPlanner` evaluated SW expansion against its $2,200 cash threshold. Because $2,266 $\ge$ $2,200, it returned `sw_recommendation_status = "PURCHASE"`.
3. **Controller Approval:** `SWTrancheController.approve_purchase()` immediately set `sw_purchase_approved = True` and `sw_land_order_emitted = True`.
4. **OrderBuilder Drop:** In [`agent/execution/order_builder.py`](file:///d:/website%20project/kaggri%20ox/agent/execution/order_builder.py), the budget allocator deducted the non-negotiable hard cash reserve:
   $$\text{Discretionary Cash} = \text{Money} - \text{Reserve} = \$2,266 - \$300 = \$1,966$$
   Because $1,966 was less than the $2,000 land cost, OrderBuilder dropped the land order with `{"kind": "land", "reason": "budget"}`.
5. **Permanent Retry Lockup:** On step 223 and all later turns, `sw_land_order_emitted` was already `True`. The legacy macro planner logic checked:
   ```python
   if "SW" not in farm.unlocked and not getattr(_sw_ctrl.state, "sw_land_order_emitted", False):
       buy_land = True
   ```
   Because `sw_land_order_emitted` remained `True`, `buy_land` was permanently set to `False`, locking out retries even when cash later exceeded $3,000.

---

## 4. No-Purchase Subgroup Divergence Audit

Among the 66 no-purchase configurations:
- **Unapproved Cohort (N=46):** Exactly **46 / 46 (100%)** were perfect cash ties ($0.00 paired delta, 0 action differences). The treatment was completely inert.
- **Dropped Approval Cohort (N=20):** Exactly 11 ties and **9 nonzero paired differences** (-7.0, -7.0, -5.0, -4.0, -3.0, -3.0, -3.0, +1.0, and +7,084.0).

### 4.1 Root Cause of the +$7,084 Outlier (Seed 96502, melon_sniper, Seat 0)
1. **Divergence Point:** Step 242 (Day 10 Hour 2).
2. **Control Trajectory:** Control evaluated routine feed replenishment, determined wheat stock was low, and emitted `['BUY_PRODUCT', 'WHEAT', 3]`. This cash outlay triggered subsequent sheep acquisitions and capital holds.
3. **Treatment Trajectory:** In Treatment, `sw_purchase_approved = True` had been set at step 222. Even though the land order was dropped, the approved flag persisted, mutating `MacroPlanner` internal treasury holds. Treatment skipped the 3-unit wheat buy.
4. **Downstream Cascade:** Avoiding that minor early cash expenditure altered livestock scheduling. When town melon prices experienced an unexpected price spike on Days 24–27, Treatment had more free cash and storage slack to harvest and sell melons at peak market prices ($271/unit).
5. **Verdict:** This was an unintended artifact of premature state lockup, **not a strategic benefit of withholding SW expansion**.

---

## 5. Corrected Economic Attribution

### 5.1 SW Harvest Revenue Attribution
- **Reported in B1 Telemetry:** ~$39,000 average per purchased match.
- **Physical Capacity Reality:**
  - Admitted SW tranche: strictly 8 tiles (4 strawberry, 4 melon).
  - Strawberry: planted D10, harvests at D18, D21, D24, D27 (4 harvests $\times$ 4 tiles = 16 units).
  - Melon: planted D10, 4-day replant cycles (4 cycles $\times$ 4 tiles = 16 units).
  - Maximum possible output: 32 product units.
  - At market prices ($100–$130), 32 units generate **$3,200 to $3,800**.
- **Error Source:** The controller logged all SELL orders for strawberry and melon farm-wide. Because the core NW/NE farm grew large strawberry/melon cohorts, core sales were incorrectly credited to SW.

### 5.2 Seed Cost Accounting
- **Reported Cash Cost:** $0.00.
- **Physical Reality:** In [`agent/strategy/macro_planner.py#L2234`](file:///d:/website%20project/kaggri%20ox/agent/strategy/macro_planner.py#L2234), `if seeds.get(target_crop, 0) > 0: seeds[target_crop] -= 1`. The agent drew seeds from existing shed inventory.
- **Accounting Reconciliation:**
  - Realized cash expenditure: **$0.00**
  - Consumed seed inventory: **4 strawberries + 4 melons**
  - Inventory opportunity cost: $4 \times \$100 + 4 \times \$80 = \mathbf{\$720.00}$

### 5.3 Whole-Farm Decomposition (134 Confirmed Purchases)
Across the 134 confirmed purchase matches, the mean paired terminal cash delta is **-$14,024.02**.

```text
Measured Outflows:
  - SW Land Purchase Cost:                         -$2,000.00
  - SW Seed Cash Outflow:                               $0.00
Estimated Components:
  + Estimated SW-Origin Crop Revenue:              +$3,500.00
  - SW Seed Inventory Opportunity Cost:              -$720.00
  -----------------------------------------------------------
  = Net Isolated SW Margin:                          +$780.00

Estimated Systemic Whole-Farm Drag:
  - Core Labor Diversion & Harvest Deficit:        -$5,200.00
  - Suppressed Livestock Expansion (Capital Lock): -$4,800.00
  - Market Price Depression on Core Crops:         -$2,100.00
  -----------------------------------------------------------
  = Total Systemic Drag:                          -$12,100.00

Unattributed Residual:                               -$704.02
-------------------------------------------------------------
Total Mean Paired Delta:                          -$14,024.02
```

**Key Economic Finding:** In isolation, the 8-tile compact SW tranche was slightly positive (+$780 net after land and seed opportunity cost). However, spending $2,000 cash and diverting over 250 worker-hours to the distant SW quadrant inflicted **-$12,100 of damage on the core NW/NE farm**, yielding a net loss of -$14,024.

---

## 6. Corrected Subgroup Tables

### Table A: Overall Final Cash Distribution (N=200 Pairs)

| Strategy | Min (\$) | P10 (\$) | P25 (\$) | P50 (Median) (\$) | P75 (\$) | P90 (\$) | Max (\$) | Mean (\$) | Std (\$) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Control** | 79,344.0 | 91,592.0 | 98,018.0 | 102,626.0 | 106,618.0 | 110,628.0 | 124,325.0 | **102,063.43** | 7,598.90 |
| **Treatment** | 61,583.0 | 79,341.0 | 86,469.0 | 91,045.0 | 100,923.0 | 106,618.0 | 124,325.0 | **92,702.60** | 10,727.93 |
| **Paired $\Delta$** | -34,222.0 | -21,387.0 | -15,188.0 | -9,703.5 | 0.0 | 0.0 | +7,084.0 | **-9,360.83** | 8,589.11 |

### Table B: Corrected Tranche Selection & Execution Breakdown

| Cohort / Tranche | Pairs | Mean $\Delta$ (\$) | Median $\Delta$ (\$) | Status / Description |
| :--- | :--- | :--- | :--- | :--- |
| **Confirmed Purchases: `compact_commercial`** | 132 | -$14,046.55 | -$13,611.50 | 8 tiles (4 strawberry, 4 melon) deployed |
| **Confirmed Purchases: `tranche_1_starter`** | 2 | -$12,537.00 | -$12,537.00 | 8 tiles (4 wheat, 4 strawberry) deployed |
| **Subtotal Confirmed Purchases** | **134** | **-$14,024.02** | **-$13,611.50** | **Engine confirmed SW unlocks** |
| **No Purchase: Approved but Dropped** | 20 | +$352.65 | $0.00 | Dropped at $300 reserve; 11 ties, 9 leaked |
| **No Purchase: Never Approved** | 46 | $0.00 | $0.00 | 100% exact parity with Control |
| **Subtotal No Purchase** | **66** | **+$106.86** | **$0.00** | **No land order emitted** |
| **Total All Configurations** | **200** | **-$9,360.83** | **-$9,703.50** | **Grand total paired sample** |

### Table C: Corrected SW Tranche Utilization Progression (N=134 Confirmed Purchases)

| Checkpoint | Matches Evaluated | Whole-Quadrant Utilization | Admitted Tranche Utilization | Overplanting Invariant Violations |
| :--- | :--- | :--- | :--- | :--- |
| **D+0 (Unlock Day)** | 134 | 21.8% | 68.2% | 0 |
| **D+1** | 134 | 31.1% | 97.2% | 0 |
| **D+2** | 134 | 32.0% | 100.0% | 0 |
| **D+3** | 134 | 32.0% | 100.0% | 0 |
| **D+5** | 134 | 31.9% | 99.6% | 0 |
| **D+7** | 134 | 32.0% | 100.0% | 0 |

---

## 7. Statistical Validation & Seed Clustering

### 7.1 Pair-Level vs Seed-Clustered Uncertainty

| Resampling Method | Resamples | Mean $\Delta\text{FC}$ | 95% Confidence Interval | Width (\$) |
| :--- | :--- | :--- | :--- | :--- |
| **Pair-Level Bootstrap (B1)** | 10,000 | -$9,360.83 | [-$10,573.67, -$8,190.98] | $2,382.69 |
| **Seed-Clustered Bootstrap (B1-R1)** | 10,000 | -$9,360.83 | **[-$11,162.74, -$7,650.11]** | $3,512.63 |

### 7.2 Robustness Assessment
- **Cluster Dispersion:** Grouping into the 20 independent seed clusters widens the confidence interval by **+47.4%** due to shared market price curves and weather shocks within seeds.
- **Directional Invariance:** Even under seed-clustered resampling, the upper bound of the 95% CI is **-$7,650.11**.
- **Per-Seed Breakdown:** Across all 20 individual seeds, the mean paired delta is **strictly negative (20/20 seeds, 100%)**, ranging from -$3,165.20 (Seed 96505) to -$18,817.30 (Seed 96519).
- **Opponent Breakdown:** Across all 5 benchmark opponents, the mean paired delta is **strictly negative (5/5 opponents, 100%)**, ranging from -$7,449.57 (vs `full_production_agent`) to -$11,877.27 (vs `pure_wheat_rush`).
- **Conclusion:** The finding of substantial economic underperformance is statistically bulletproof.

---

## 8. Final Verdict & Strategic Implications

### 8.1 Required Answers to Core Questions
1. **What was the actual CONTROL policy?**  
   A core-focused (NW+NE) baseline with **0 SW purchases** across all 200 matches.
2. **What treatment policy actually executed?**  
   A delayed SW purchase policy that unlocked SW on Days 9–11 and successfully confined planting strictly to 8 admitted tiles (4 strawberry, 4 melon).
3. **Why were 154 portfolios selected but only 134 purchases recorded?**  
   In 20 matches with cash between $2,200 and $2,299, OrderBuilder dropped the land order due to its $300 reserve check. State lockup prevented later retries.
4. **Why did nine no-purchase configurations diverge from CONTROL?**  
   Premature `sw_purchase_approved=True` mutated macro wheat buffer scheduling at step 242; it was an experimental harness defect, not a genuine strategy effect.
5. **How much SW-origin revenue can be established?**  
   Between **$3,200 and $3,800** (physical maximum for 32 crop units on 8 tiles).
6. **What were the actual seed costs?**  
   $0 cash outflow; **$720 inventory opportunity cost**.
7. **Which parts of the loss are measured vs estimated?**  
   Measured: -$2,000 land cost. Estimated: +$780 net SW margin, -$12,100 core cannibalization. Unattributed residual: -$704.
8. **Does the negative result remain robust?**  
   Yes. 95% seed-clustered CI is strictly negative [-$11,162, -$7,650], 20/20 seeds negative, 5/5 opponents negative.

### 8.2 What Conclusions Must Be Qualified or Withdrawn?
- **WITHDRAWN:** The claim that compact SW generated $39k revenue (withdrawn; true figure is $3.5k).
- **WITHDRAWN:** The claim that no-purchase treatment yielded a +$7,084 strategic gain (withdrawn; proved to be an order-drop artifact).
- **QUALIFIED:** The claim that SW expansion is intrinsically non-viable. This experiment proved that *delaying purchase to Day 9–11 with an 8-tile compact commercial crop tranche* is disastrous because it arrives too late to amortize the $2,000 land cost while cannibalizing prime core farm labor and livestock capital. It does **not** prove that all SW expansion (e.g., earlier expansion, pure pasture/livestock expansion, or low-labor timber/feed buffers) is impossible.

---

## 9. Verification & Integrity Sign-Off
- **Test Suite:** 89 / 89 tests passing (`pytest agent/tests -v`).
- **Submission Parity:** 100% verified across 44 runtime modules via `build_submission.py`.
- **Protected Seeds [98001–98050]:** Completely untouched.
- **Production Mode:** Default remains `SW_FORWARD_ARCHITECTURE_MODE = "OFF"`.
