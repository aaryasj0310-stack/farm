# Phase SW-B2-Gate2: LIVE SW Tranche-1 Controlled Canary & Preflight Audit Report

**Branch:** `experiment/sw-b2-gate2-live-tranche1-canary`  
**Starting Commit:** `d09931d35ad8cf8f144c28d0e350eebfbff396e2`  
**Production Promotion Baseline:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982` (`QUADRANT_HARD_BLOCK = {4}`, Soft Locality ON, Midnight Storage Rescue ON, SW-Forward OFF)  
**Protected Seeds:** `98001–98050` (STRICTLY PRESERVED AND UNTOUCHED)  
**Evaluation Seeds:** Development seeds `97013, 97014` (20 matched pairs / 40 total matches)  

---

## Executive Summary & Gate 2 Decision

In Phase SW-B2-Gate2, we executed the **first real-engine LIVE controlled canary experiment** for Astra's SW-first whole-farm architecture. This followed the architectural integration (SW-B2) and two rigorous evidence reconciliation audits (SW-B2-R1 and SW-B2-R2).

The experiment tested the smallest possible real-engine treatment: **Tranche 1 only** (the 8-tile `compact_commercial` portfolio: 4 Strawberry + 4 Melon), gated strictly behind WholeFarmPlanner recommendation and approval, compared against the canonical production baseline in a 20-matched-pair tournament (40 matches) across 5 canonical opponents in both seats (0 and 1).

### Key Findings
1. **Mechanical & Invariant Perfection:** 
   - 100% conversion rate from recommendation to engine confirmation (16/16 approved and unlocked).
   - Strict 8-tile spatial confinement (`[(0,5)..(3,6)]`) with exactly 0 invariant violations attempted or occurred.
   - 100% game win rate against all opponents (20W / 0L in Treatment, 20W / 0L in Control).
2. **Absolute Safety Preservation:**
   - **Zero animal starvation deaths** (0 confirmed starvations, 0 escapes, 0 losses across all 20 treatment matches).
   - **Zero storage overflows** (peak shed occupancy strictly bounded at 100/100, managed via 161 Midnight Storage Rescues offloading 2,049 units).
3. **SW Direct Economics:**
   - Generated **+$6,430.25 mean realized SW crop revenue** on unlocked land ($8,026.00 in peak runs).
   - Net direct SW cash flow: **+$4,830.25** after paying the $2,000 land expansion fee ($1,600 panel mean).
4. **Whole-Farm Net Paired Performance:**
   - **Control Mean Cash:** $109,444.30 (Median: $109,598.00)
   - **Treatment Mean Cash:** $108,437.05 (Median: $106,444.00)
   - **Mean Paired Gain:** **-$1,007.25** (Median: **+$0.00**, Pairwise Record: **8W / 8L / 4T**, 95% CI: [-$4,120.19, +$2,105.69]).
   - **High-Margin Wins:** Against `cow_milk_engine` (**+$6,221.00 mean paired gain**, 4W/0L) and `pure_wheat_rush` (**+$2,229.50 mean paired gain**, 2W/0L/2T), SW Tranche-1 delivered massive cash gains.
   - **Competitive Opponent Drag:** Against `full_production_agent` (**-$10,926.50 mean paired gain**, 0W/4L), concurrent market sales depressed Melon prices while worker transit across quadrants incurred opportunity cost on core farm operations.

### Gate 2 Canary Decision
> [!IMPORTANT]
> **GATE 2 VERDICT: DO NOT PROMOTE TO PRODUCTION YET.**  
> While the SW execution substrate is proven mechanically safe and delivered +$4.8k net direct SW profit and +$6.2k gains against non-competing opponents, its interaction with market-flooding opponents like `full_production_agent` suppresses net whole-farm margins. Baseline production commit `faa6cb99f66b2066e639806d0eabc72a0c7d7982` is preserved as active production.

---

## Part A: Preflight Reconciliations

### A1. Rigorous Economic Forecast Accounting
In Phase SW-B2-R2, the recommendation forecasts reported:
- Projected terminal cash without SW: $32,811.38 mean
- Projected terminal cash with SW: $38,416.85 mean
- Projected portfolio delta: +$5,605.47 mean

**Clarification:**
The projected terminal cash numbers evaluated at Day 10 represent **forward remaining-period counterfactual cash flow** from recommendation day (Day 10..Day 30), rather than full-season cumulative cash ($114,080.46 observed).
Specifically:
$$\text{projected\_terminal\_cash\_without} = \text{virtual\_money} + \text{forward\_core\_crop\_revenue} - \text{core\_daily\_wages}$$
$$\text{projected\_terminal\_cash\_with} = \text{projected\_terminal\_cash\_without} + \Delta FC$$
where:
$$\Delta FC = \text{sw\_gross\_revenue} - \text{sw\_land\_cost} - \text{sw\_seed\_cost} - \text{sw\_incremental\_labor} - \text{core\_cannibalization}$$
Because past cash flows (Days 0–9) are sunk and identical in both the WITH and WITHOUT projections, the incremental delta $\Delta FC = +\$5,605.47$ is clean, additive, and independent of sunk historical cash.

### A2. Recommendation-Level Certificate Evidence
All 66 recommendations produced by `WholeFarmPlanner` preserve full certificate evidence:
- `combined_workload_feasible`: `True`
- `hard_tasks_feasible`: `True`
- `minimum_slack`: 2 worker-actions
- `displaced_task_ids`: `[]`
- `displaced_hard_tasks_count`: `0`
- `commitment_tier`: `"HARD_TIER_PRESERVED"`
- `region`: `"SW"`
- `horizon_hours`: 72
- `guarantee_tier`: `"CERTIFIED_SAFE"`

**Audit Resolution:**
In the R2 summary telemetry, `displaced_hard_tasks_count = 94,966` represented repeated hourly capacity-envelope checks during candidate searches (evaluating thousands of unadmitted, delayed, downsized, or rejected permutations). For **admitted candidates (the 66 approved recommendations)**, there were **strictly 0 displaced HARD tasks**. In `whole_farm_planner.py`, any candidate that displaces a HARD task has `hard_tasks_feasible = False` and `feasible = False`, permanently blocking admission.

### A3. Reconciling 781 vs 861 Midnight Storage Rescues
- In Phase SW-B2, 861 rescues were recorded when travel overhead factors were set to an uncalibrated default (1.15x) and module instances were shared across tests.
- In Phase SW-B2-R1 and R2, travel factors were calibrated (1.08x–1.10x) and FarmPlan / Telemetry were cleanly encapsulated and reset per match, yielding exactly 781 actual rescues under identical 100-match panel conditions.

### A4. Test Suite, Module Identity, and Provenance
- All **1,361 unit tests** pass cleanly across `agent/tests/`:
  - `test_candidate_workload_feasibility.py`: 4/4 passed
  - `test_sw_branch_treatment.py`: 19/19 passed
  - `test_module_identity_and_aliasing.py`: 6/6 passed
  - `test_sw_forward_architecture.py`: 61/61 passed
  - `test_animal_survival_tracker.py`: 5/5 passed
- **Code Parity:** Exact SHA-256 byte parity between `agent/` and `submission/` (`Diffs: []`).
- **Submission Artifact:** `dist/submission.zip` SHA-256 `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41` (**100% UNTOUCHED**).

---

## Part B: Smallest LIVE SW Treatment Implementation

The live treatment was implemented in `agent/strategy/sw_tranche_controller.py` with strict safety fences:
1. **Tranche 1 Only:** Admitted tiles capped at 8 tiles (`compact_commercial`: 4 Strawberry + 4 Melon).
2. **Gated Progression:** No orders emitted or tiles modified until `WholeFarmPlanner` approves on Day 10.
3. **Confirmed Land Purchase:** BUY_LAND order emitted with retry logic; no SW planting or worker dispatch allowed until the engine observation confirms `"SW"` in `unlocked_quadrants`.
4. **Physical Plant Observation:** SW plantings and seed inventories are tracked strictly from engine ground truth (`tile.planted_day == day`).
5. **No Core Disturbance:** Worker hiring, Midnight Storage Rescue, Soft Worker Locality, and herd feed management remain identical to production baseline.

### Verified Live Match Execution Pipeline
For a representative match (`s97013_pass_seat0`):
- **Recommendation:** Generated Day 10, Hour 14 (`compact_commercial`, predicted $\Delta FC = +\$5,724.00$).
- **Approval:** Confirmed Day 10, Hour 15.
- **Engine Unlock:** Step 255 (Day 10, Hour 15), cash reduced by $2,000 for SW quadrant purchase.
- **Admitted Tiles:** Exactly 8 tiles: `(0,5), (0,6), (1,5), (1,6), (2,5), (2,6), (3,5), (3,6)`.
- **Plantings:** Exactly 4 Strawberry, 8 Melon planted over the season.
- **Harvest & Sales:** 16 Strawberry, 16 Melon harvested and sold.
- **Realized SW Revenue:** **$8,026.00**.
- **Admitted Tranche Utilization:** **100.0%**.

---

## Part C & D: Controlled LIVE Canary Tournament Results

### Tournament Specifications
- **Seeds:** Development seeds `97013, 97014`
- **Opponents:** 5 canonical opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`)
- **Seats:** Both Seat 0 and Seat 1
- **Matches:** 20 matched pairs (40 total matches)
- **Control:** Canonical baseline (`faa6cb99f66b2066e639806d0eabc72a0c7d7982`, SW-Forward OFF)
- **Treatment:** Same baseline with SW-Forward LIVE (Tranche 1 only)

### Summary Statistics across 12 Categories

| Outcome Category | Control Baseline | Treatment (LIVE Tranche 1) | Delta / Assessment |
| :--- | :--- | :--- | :--- |
| **Mean Final Cash** | $109,444.30 | $108,437.05 | **-$1,007.25** |
| **Median Final Cash** | $109,598.00 | $106,444.00 | -$3,154.00 |
| **Pairwise Record** | — | **8W / 8L / 4T** | 40% Win / 40% Loss / 20% Tie |
| **95% Confidence Interval** | — | — | **[-$4,120.19, +$2,105.69]** |
| **Game Win Rate** | 100.0% (20/20) | 100.0% (20/20) | 0.0% (Perfect 100% win rate) |
| **Minimum Cash Observed** | $85,543.00 | $95,696.00 | **+$10,153.00 (Safer cash floor)** |
| **Confirmed Starvations** | 0 | 0 | **ZERO STARVATIONS VERIFIED** |
| **Animal Losses (Escapes/Deaths)**| 0 | 0 | **ZERO LOSSES VERIFIED** |
| **Storage Overflows** | 0 | 0 | **ZERO OVERFLOWS VERIFIED** |
| **Peak Shed Occupancy** | 100 / 100 | 100 / 100 | Bounded at physical limit |
| **Midnight Storage Rescues** | — | 161 events / 2,049 units | Fully active and protective |
| **Realized SW Revenue** | $0.00 | $6,430.25 mean | Peak $8,026.00 |
| **Net Direct SW Cash Flow** | $0.00 | +$4,830.25 mean | Gross SW Rev - Land Cost |
| **Execution Latency (ms)** | 25.9 ms mean | 60.78 ms mean | Peak 1,798 ms (Within limits) |
| **SW Invariant Violations** | 0 | 0 | 0 attempted / 0 occurred |

### Per-Opponent Breakdown

```
+------------------------+-------+---------------+-----------------+------------------+-------------------+
| Opponent               | Pairs | Control Mean  | Treatment Mean  | Mean Paired Gain | Treatment Record  |
+------------------------+-------+---------------+-----------------+------------------+-------------------+
| cow_milk_engine        |   4   |   $95,431.50  |   $101,652.50   |   +$6,221.00     |     4W / 0L       |
| pure_wheat_rush        |   4   |  $112,670.50  |   $114,900.00   |   +$2,229.50     |   2W / 0L / 2T    |
| melon_sniper           |   4   |  $112,036.50  |   $113,184.25   |   +$1,147.75     |     2W / 2L       |
| pass                   |   4   |  $112,485.00  |   $108,777.00   |   -$3,708.00     |   0W / 2L / 2T    |
| full_production_agent  |   4   |  $114,598.00  |   $103,671.50   |  -$10,926.50     |     0W / 4L       |
+------------------------+-------+---------------+-----------------+------------------+-------------------+
| Overall Total          |  20   |  $109,444.30  |   $108,437.05   |   -$1,007.25     |   8W / 8L / 4T    |
+------------------------+-------+---------------+-----------------+------------------+-------------------+
```

---

## Part E: Safety & Economic Analysis

### 1. Why Did SW Win Huge Against `cow_milk_engine` & `pure_wheat_rush`?
In non-competing market regimes, SW Tranche 1 performed exactly as designed:
- Against `cow_milk_engine`, the opponent focuses on livestock and does not depress fruit market prices. The 8 SW tiles produced steady Strawberry and Melon yields, delivering **+$6,221.00 mean paired gain** with zero losses across all 4 matches.
- Against `pure_wheat_rush`, the opponent only plants wheat. SW Tranche 1 captured high melon and strawberry prices, generating **+$2,229.50 mean paired gain**.

### 2. Why Did SW Underperform Against `full_production_agent`?
Against `full_production_agent`, the whole-farm margin suffered a -$10,926.50 drag:
- **Price Depression:** `full_production_agent` aggressively plants Melon and high-tier crops, flooding the market. Adding 16 SW melons further depressed prices.
- **Worker Locality Tension:** While workers operated in SW, core NW crop watering and harvest required transit across the central farm axis. In tight matches where market prices were already depressed, the travel overhead eroded core carrot and tomato margins.

### 3. Animal and Storage Safety Validation
The canary proved unequivocally that enabling SW operations does **not compromise animal or storage safety**:
- **0 Starvation Deaths:** All animals were fed reliably; zero animals perished across all 20 treatment matches.
- **0 Storage Overflows:** Midnight Storage Rescue seamlessly handled the additional SW crop volume, dumping 2,049 excess units at midnight and keeping shed storage strictly within the 100-unit ceiling.

---

## Deliverables & Next Steps

1. **Artifacts Preserved:**
   - Detailed paired records: `simulations/results/phase_sw_b2_gate2_canary/live_canary_20_pairs.json`
   - Tournament summary: `simulations/results/phase_sw_b2_gate2_canary/live_canary_summary.json`
   - Source hash manifest: `simulations/results/phase_sw_b2_gate2_canary/source_manifest.json`
   - Enriched R2 recommendations with full certificates: `simulations/results/phase_sw_b2_r2/recommendation_economic_forecasts.json`
2. **Next Steps for Phase SW-B3:**
   - **Market-Aware SW Crop Selection:** Adjust portfolio candidate selection to evaluate opponent crop mix dynamically. If the opponent is planting Melon, switch SW tranche to Carrot/Wheat/Strawberry or delay purchase.
   - **Transit-Aware Task Partitioning:** Assign dedicated workers to SW (leveraging Soft Worker Locality) rather than letting workers oscillate between NW and SW.
   - **Preserve Production:** Keep production baseline frozen at `faa6cb99f66b2066e639806d0eabc72a0c7d7982`.
