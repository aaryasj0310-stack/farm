# Phase SW-B3B: Core-First SW Task Admission Experiment Report

**Tournament Execution Date:** September 27, 2026  
**Git Branch:** `experiment/sw-b3b-core-first-admission`  
**Starting HEAD:** `7ee0b4a4a042736e26cc964b76eae6ebf8055826`  
**Canonical Production Baseline:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982`  
`dist/submission.zip` SHA-256: `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41` (100% verified intact)

---

## 1. Executive Summary

Phase SW-B3B conducted a rigorous, real-engine 3-arm matched comparison to evaluate whether a **Core-First Task Admission Controller** (`SW_CORE_FIRST_TASK_ADMISSION`) can eliminate the whole-farm performance degradation observed in the first LIVE SW canary (Gate 2 / Phase SW-B3A).

The three arms evaluated across 40 matched pair cells (120 audited engine matches) are:
- **Arm A (Canonical Production Baseline):** `SW_FORWARD_ARCHITECTURE_MODE = "CONTROL"`, Core-First Admission OFF.
- **Arm B (Frozen Gate 2 LIVE SW Control):** `SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"`, Core-First Admission OFF.
- **Arm C (Phase SW-B3B Treatment):** `SW_FORWARD_ARCHITECTURE_MODE = "TREATMENT"`, Core-First Admission ON (`SW_CORE_FIRST_TASK_ADMISSION = True`).

The test panel includes:
- **Discovery Sample:** Seeds `97013`, `97014` (20 cells / 60 audited matches) across 5 canonical opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`) and both seats (0, 1).
- **Independent Confirmation Sample:** Seeds `97015`, `97016` (20 cells / 60 audited matches) across the same 5 opponents and seats.

### Headline Experimental Results

| Metric | Discovery Sample (Seeds 97013, 97014) | Confirmation Sample (Seeds 97015, 97016) | Combined 40-Pair Panel (Seeds 97013–97016) |
| :--- | :---: | :---: | :---: |
| **Total Matched Pairs** | 20 | 20 | 40 |
| **SW Purchasing Pairs** | 16 / 20 (80.0%) | 12 / 20 (60.0%) | 28 / 40 (70.0%) |
| **Primary Metric (Arm C vs Arm B Mean Delta)** | **-$3,925.35** | **+$874.30** | **-$1,525.53** |
| **Primary Metric Median Delta** | -$2,946.50 | $0.00 | $0.00 |
| **Primary Pairwise Record (C vs B)** | 5W / 11L / 4T | **8W / 4L / 8T** | 13W / 15L / 12T |
| **Secondary Metric (Arm C vs Arm A Mean Delta)** | -$4,932.60 | -$3,874.15 | -$4,403.38 |
| **Secondary Pairwise Record (C vs A)** | 2W / 14L / 4T | 0W / 12L / 8T | 2W / 26L / 12T |
| **Baseline Check (Arm B vs Arm A Mean Delta)** | -$1,007.25 (Exact Gate 2 Parity) | -$4,748.45 | -$2,877.85 |
| **Cash Ledger Reconciliation Residual** | **$0.0000 (100% of 60 matches)** | **$0.0000 (100% of 60 matches)** | **$0.0000 (100% of 120 matches)** |
| **Paired Waterfall Residual** | **$0.0000 (100% of 20 pairs)** | **$0.0000 (100% of 20 pairs)** | **$0.0000 (100% of 40 pairs)** |
| **Starvation Animal Deaths** | **0** | **0** | **0** |
| **Turn Latency Mean / p95** | 76.5 ms / 198.4 ms | 74.2 ms / 195.1 ms | 75.3 ms / 196.7 ms |

### Key Findings & Empirical Diagnosis

1. **Gate 2 Reproduction Parity is 100% Exact:**
   On the Discovery panel (Seeds 97013, 97014), Arm B vs Arm A reproduced the exact -$1,007.25 mean paired delta and identical match cash values to the penny, confirming flawless baseline stability.
2. **Core Recovery Succeeded Mechanically:**
   The Core-First Admission Controller successfully protected the core farm:
   - Worker transit waste dropped by **-112.43 movement actions** per match.
   - Core agricultural actions rose by **+263.52 actions** per match.
   - Core crop revenue recovered by **+$2,166.62** across the combined panel (+$2,691.13 in Discovery, +$1,642.11 in Confirmation).
   - Animal revenue recovered by **+$1,706.17** across the combined panel (+$3,620.45 in Confirmation).
3. **Confirmation Sample Outperformance (C vs B):**
   In the independent Confirmation sample (Seeds 97015, 97016), Arm C achieved a positive delta over Arm B of **+$874.30** with an **8W / 4L / 8T** record. In seeds where Arm B suffered severe livestock/core collapse, admission successfully defended the farm.
4. **The Over-Throttling Capital Efficiency Dilemma:**
   Despite mechanical core protection, Arm C lost on net against Arm B overall (-$1,525.53) and against Arm A (-$4,403.38).
   The diagnostic telemetry reveals why:
   - The Macro Planner still committed the **$2,000.00 capital expenditure** to purchase SW land.
   - However, the task admission controller admitted only **10.4 SW tasks per match** (out of 6,620.75 proposed, a **0.16% admission rate**), because `UNASSIGNED_CORE_STANDARD_TASK` (mature harvests, daily watering, routine animal care) continuously blocked SW workers.
   - As a result, the agent paid for SW land and planted seeds, but then starved the SW crops of follow-up watering and harvesting labor. SW crops withered or went unharvested, driving **SW Net Margin down by -$6,717.32**.

---

## 2. Comprehensive 3-Arm Matched Match Outcomes

The table below presents the audited final cash outcomes for each cell across Arm A, Arm B, and Arm C, together with paired deltas and SW purchasing verification.

### Discovery Sample (Seeds 97013, 97014)

| Cell ID | Arm A (Prod) | Arm B (Gate 2) | Arm C (B3B) | C vs B Delta | C vs A Delta | B vs A Delta | SW Purchased (B/C) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `s97013_cow_milk_engine_seat0` | $105,320.00 | $106,882.00 | $103,248.00 | -$3,634.00 | -$2,072.00 | +$1,562.00 | Yes / Yes |
| `s97013_cow_milk_engine_seat1` | $105,320.00 | $108,336.00 | $103,066.00 | -$5,270.00 | -$2,254.00 | +$3,016.00 | Yes / Yes |
| `s97013_full_production_agent_seat0` | $111,625.00 | $103,021.00 | $103,445.00 | +$424.00 | -$8,180.00 | -$8,604.00 | Yes / Yes |
| `s97013_full_production_agent_seat1` | $111,625.00 | $105,297.00 | $102,747.00 | -$2,550.00 | -$8,878.00 | -$6,328.00 | Yes / Yes |
| `s97013_melon_sniper_seat0` | $105,220.00 | $110,636.00 | $107,293.00 | -$3,343.00 | +$2,073.00 | +$5,416.00 | Yes / Yes |
| `s97013_melon_sniper_seat1` | $105,220.00 | $110,749.00 | $107,293.00 | -$3,456.00 | +$2,073.00 | +$5,529.00 | Yes / Yes |
| `s97013_pass_seat0` | $107,571.00 | $101,428.00 | $102,253.00 | +$825.00 | -$5,318.00 | -$6,143.00 | Yes / Yes |
| `s97013_pass_seat1` | $107,571.00 | $98,882.00 | $102,449.00 | +$3,567.00 | -$5,122.00 | -$8,689.00 | Yes / Yes |
| `s97013_pure_wheat_rush_seat0` | $106,006.00 | $106,006.00 | $106,006.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97013_pure_wheat_rush_seat1` | $106,006.00 | $106,006.00 | $106,006.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97014_cow_milk_engine_seat0` | $85,543.00 | $95,696.00 | $75,750.00 | -$19,946.00 | -$9,793.00 | +$10,153.00 | Yes / Yes |
| `s97014_cow_milk_engine_seat1` | $85,543.00 | $95,696.00 | $75,750.00 | -$19,946.00 | -$9,793.00 | +$10,153.00 | Yes / Yes |
| `s97014_full_production_agent_seat0` | $117,571.00 | $103,184.00 | $104,199.00 | +$1,015.00 | -$13,372.00 | -$14,387.00 | Yes / Yes |
| `s97014_full_production_agent_seat1` | $117,571.00 | $103,184.00 | $104,199.00 | +$1,015.00 | -$13,372.00 | -$14,387.00 | Yes / Yes |
| `s97014_melon_sniper_seat0` | $118,853.00 | $115,676.00 | $110,147.00 | -$5,529.00 | -$8,706.00 | -$3,177.00 | Yes / Yes |
| `s97014_melon_sniper_seat1` | $118,853.00 | $115,676.00 | $110,147.00 | -$5,529.00 | -$8,706.00 | -$3,177.00 | Yes / Yes |
| `s97014_pass_seat0` | $117,399.00 | $117,399.00 | $117,399.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97014_pass_seat1` | $117,399.00 | $117,399.00 | $117,399.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97014_pure_wheat_rush_seat0` | $119,335.00 | $123,794.00 | $115,719.00 | -$8,075.00 | -$3,616.00 | +$4,459.00 | Yes / Yes |
| `s97014_pure_wheat_rush_seat1` | $119,335.00 | $123,794.00 | $115,719.00 | -$8,075.00 | -$3,616.00 | +$4,459.00 | Yes / Yes |
| **Discovery Mean** | **$109,444.30** | **$108,437.05** | **$104,511.70** | **-$3,925.35** | **-$4,932.60** | **-$1,007.25** | **16 / 20** |

### Confirmation Sample (Seeds 97015, 97016)

| Cell ID | Arm A (Prod) | Arm B (Gate 2) | Arm C (B3B) | C vs B Delta | C vs A Delta | B vs A Delta | SW Purchased (B/C) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `s97015_cow_milk_engine_seat0` | $110,573.00 | $99,592.00 | $102,979.00 | +$3,387.00 | -$7,594.00 | -$10,981.00 | Yes / Yes |
| `s97015_cow_milk_engine_seat1` | $109,006.00 | $105,092.00 | $100,854.00 | -$4,238.00 | -$8,152.00 | -$3,914.00 | Yes / Yes |
| `s97015_full_production_agent_seat0` | $117,824.00 | $117,824.00 | $117,824.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97015_full_production_agent_seat1` | $120,209.00 | $120,209.00 | $120,209.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97015_melon_sniper_seat0` | $117,028.00 | $111,692.00 | $115,384.00 | +$3,692.00 | -$1,644.00 | -$5,336.00 | Yes / Yes |
| `s97015_melon_sniper_seat1` | $115,347.00 | $118,506.00 | $113,930.00 | -$4,576.00 | -$1,417.00 | +$3,159.00 | Yes / Yes |
| `s97015_pass_seat0` | $119,351.00 | $119,351.00 | $119,351.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97015_pass_seat1` | $122,108.00 | $122,108.00 | $122,108.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97015_pure_wheat_rush_seat0` | $107,403.00 | $107,403.00 | $107,403.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97015_pure_wheat_rush_seat1` | $107,403.00 | $107,403.00 | $107,403.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97016_cow_milk_engine_seat0` | $110,582.00 | $106,176.00 | $108,763.00 | +$2,587.00 | -$1,819.00 | -$4,406.00 | Yes / Yes |
| `s97016_cow_milk_engine_seat1` | $111,258.00 | $105,420.00 | $104,831.00 | -$589.00 | -$6,427.00 | -$5,838.00 | Yes / Yes |
| `s97016_full_production_agent_seat0` | $121,221.00 | $121,221.00 | $121,221.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97016_full_production_agent_seat1` | $121,185.00 | $121,185.00 | $121,185.00 | $0.00 | $0.00 | $0.00 | No / No |
| `s97016_melon_sniper_seat0` | $115,924.00 | $101,538.00 | $100,637.00 | -$901.00 | -$15,287.00 | -$14,386.00 | Yes / Yes |
| `s97016_melon_sniper_seat1` | $118,109.00 | $102,721.00 | $105,112.00 | +$2,391.00 | -$12,997.00 | -$15,388.00 | Yes / Yes |
| `s97016_pass_seat0` | $116,032.00 | $103,178.00 | $108,622.00 | +$5,444.00 | -$7,410.00 | -$12,854.00 | Yes / Yes |
| `s97016_pass_seat1` | $116,032.00 | $106,206.00 | $106,616.00 | +$410.00 | -$9,416.00 | -$9,826.00 | Yes / Yes |
| `s97016_pure_wheat_rush_seat0` | $117,409.00 | $112,065.00 | $114,749.00 | +$2,684.00 | -$2,660.00 | -$5,344.00 | Yes / Yes |
| `s97016_pure_wheat_rush_seat1` | $117,409.00 | $107,554.00 | $114,749.00 | +$7,195.00 | -$2,660.00 | -$9,855.00 | Yes / Yes |
| **Confirmation Mean** | **$115,313.95** | **$110,565.50** | **$111,439.80** | **+$874.30** | **-$3,874.15** | **-$4,748.45** | **12 / 20** |

---

## 3. Causal Cash Waterfall Decomposition (Arm C vs Arm B)

Every dollar of cash difference between Arm C and Arm B is reconciled with **$0.0000 residual** via the engine transaction ledgers:

$$\Delta\text{Cash}_{C - B} = \Delta\text{SW Net Margin} + \Delta\text{Core Crop Rev} - \Delta\text{Core Seed Cost} - \Delta\text{Core Land Cost} + \Delta\text{Animal Rev} - \Delta\text{Animal Purchases} - \Delta\text{Feed Cost} - \Delta\text{Fert Cost} - \Delta\text{Labor Hires} - \Delta\text{Wages}$$

### Average Waterfall Components (Per Match)

| Waterfall Component | Discovery (Seeds 97013, 97014) | Confirmation (Seeds 97015, 97016) | Combined 40-Pair Panel |
| :--- | :---: | :---: | :---: |
| **Observed Mean Delta ($\Delta\text{Cash}$)** | **-$3,925.35** | **+$874.30** | **-$1,525.53** |
| **1. SW Net Margin Delta ($\Delta\text{SW Net}$)** | **-$7,652.18** | **-$5,782.46** | **-$6,717.32** |
| — SW Crop Sales Revenue Delta | -$7,652.18 | -$5,782.46 | -$6,717.32 |
| — SW Land Purchase Cost Delta | $0.00 | $0.00 | $0.00 |
| — SW Seed Purchase Cost Delta | $0.00 | $0.00 | $0.00 |
| **2. Core Agricultural Revenue & Cost Deltas** | | | |
| — Core Crop Sales Revenue Delta | **+$2,691.13** | **+$1,642.11** | **+$2,166.62** |
| — Core Seed Purchases Cost Delta | +$49.50 | +$45.50 | +$47.50 |
| — Core Land Purchases Cost Delta | $0.00 | $0.00 | $0.00 |
| **3. Livestock Operation Deltas** | | | |
| — Animal Sales Revenue Delta | -$208.10 | **+$3,620.45** | **+$1,706.17** |
| — Animal Purchase Cost Delta | -$140.00 | -$35.00 | -$87.50 |
| — Feed Purchases Cost Delta | -$1,153.30 | -$1,404.70 | -$1,279.00 |
| — Fertilizer Purchases Cost Delta | $0.00 | $0.00 | $0.00 |
| **4. Labor Cost Deltas** | | | |
| — Hiring Cost Delta | $0.00 | $0.00 | $0.00 |
| — Wages Paid Delta | $0.00 | $0.00 | $0.00 |
| **Accounted Delta Sum** | **-$3,925.35** | **+$874.30** | **-$1,525.53** |
| **Reconciliation Residual** | **$0.0000** | **$0.0000** | **$0.0000** |

---

## 4. Operational & Behavioral Telemetry

### Worker Activity Comparison (Arm B vs Arm C)

| Action Metric (Mean per match) | Arm B (Gate 2) | Arm C (SW-B3B) | Delta (C - B) |
| :--- | :---: | :---: | :---: |
| **Movement Actions (`move`)** | 2,752.68 | 2,640.25 | **-112.43** (-4.1%) |
| **Actions Executed in Core (NW/NE)** | 2,897.40 | 3,160.92 | **+263.52** (+9.1%) |
| **Actions Executed in SW** | 305.18 | 39.03 | **-266.15** (-87.2%) |
| **Watering Actions** | 821.15 | 831.23 | **+10.08** (+1.2%) |

The worker telemetry demonstrates that the admission controller accomplished its design mandate: workers ceased commuting aimlessly to SW, devoting 263.5 more worker-hours to core farm tasks.

### Task Admission Diagnostics (Arm C)

Across all 40 matches in Arm C, the `SWTaskAdmissionController` evaluated every agricultural task proposed on SW land:

| Admission Metric | Discovery | Confirmation | Combined Panel |
| :--- | :---: | :---: | :---: |
| **Proposed SW Tasks (Mean / Match)** | 7,623.30 | 5,618.20 | 6,620.75 |
| **Admitted SW Tasks (Mean / Match)** | **10.00** | **10.80** | **10.40** |
| **Deferred SW Tasks (Mean / Match)** | 7,613.30 | 5,607.40 | 6,610.35 |
| **Effective Admission Rate** | **0.13%** | **0.19%** | **0.16%** |

#### Deferral Reasons Breakdown across All 40 Matches

```
Total Deferral Events: 1,114,946

[78.35%] UNASSIGNED_CORE_STANDARD_TASK: 873,630 events
         (Active core watering, mature crop harvesting, routine animal feeding)
[19.92%] UNASSIGNED_CORE_HARD_TASK:     222,101 events
         (Emergency crop survival watering, feed rescue, decaying crop harvest)
 [1.81%] CORE_WORKER_DEFICIT:            20,216 events
         (Assigned core workers < required core capacity)
 [1.45%] UNAUTHORIZED_SW_TILE:           16,115 events
         (Tasks outside the approved 8-tile tranche)
 [0.25%] NEAR_TERM_CORE_CAPACITY_DEFICIT: 2,736 events
         (Capacity deficit over remaining hours)
 [0.02%] LATE_DAY_TRANSIT_OVERHEAD:         278 events
         (Hour >= 18 cross-map commuting block)
```

---

## 5. Architectural Root-Cause Analysis

### Why Confirmation Succeeded (+ $874.30, 8W / 4L / 8T)
In the Confirmation panel (Seeds 97015, 97016), Arm B suffered severe livestock and farm neglect due to SW workers getting stranded. Arm B lost -$4,748.45 compared to Arm A.
In these seeds, the admission controller successfully prevented workers from abandoning the barns:
- Animal revenue was higher by **+$3,620.45** in Arm C compared to Arm B.
- Core crop revenue was higher by **+$1,642.11**.
- Even with SW production curtailed, the protection of core livestock assets more than compensated for the SW deficit, allowing Arm C to beat Arm B in 8 out of 12 SW matches (+$874.30 average delta).

### Why the Overall Strategy Lost (- $1,525.53 vs B, - $4,403.38 vs A)
The tournament surfaced a fundamental architectural tension between the **Macro Planner** and the **Micro Task Admission Controller**:
1. **Unilateral Capital Allocation:**
   The Macro Planner (`macro_planner.py` / `sw_tranche_controller.py`) evaluated land purchase readiness at Day 10 and committed **$2,000.00** to buy the SW quadrant and seed it with high-value Melons and Strawberries.
2. **Micro Labor Starvation:**
   Once the land was purchased, the `SWTaskAdmissionController` evaluated whether workers should be allowed to travel to SW. Because the core farm has continuous standard tasks (core crops need water every day, cows need feeding and milking every day), the admission controller saw `UNASSIGNED_CORE_STANDARD_TASK > 0` on almost 99.8% of turns.
3. **The Unfinished Harvest Trap:**
   The admission controller deferred 99.84% of SW tasks. As a consequence, workers planted SW seeds but were virtually forbidden from returning to water or harvest them.
   - The agent incurred the full **$2,000.00 land cost** and seed costs.
   - The crops sat unwatered or decayed.
   - SW crop sales revenue plummeted by **-$6,717.32**.

**Core Takeaway:** You cannot have a Macro Planner that assumes full agricultural utilization of SW land operating alongside a Micro Admission Controller that gives strict priority to routine core tasks. Either:
1. The Macro Planner must NOT purchase SW land unless there is surplus labor beyond routine core maintenance, OR
2. The Admission Controller must distinguish between *urgent/hard* core obligations (animal death, crop decay) and *routine/postponable* standard tasks (optional watering, early harvest), creating bounded service windows for SW crops.

---

## 6. Execution Safety & Latency Audit

1. **Animal Survival:**
   Across all 120 audited matches, there were **0 confirmed starvation deaths**, **0 escapes**, and **0 animal disappearances**. Peak herd sizes were preserved.
2. **Deterministic Parity:**
   On Discovery Seeds 97013 & 97014, Arm B cash outcomes matched the frozen Gate 2 baseline with 100% exact numerical identity ($0.00 deviation across all 20 cells).
3. **Turn Latency:**
   - Mean Turn Latency: 75.3 ms
   - p95 Turn Latency: 196.7 ms
   - p99 Turn Latency: 228.4 ms
   - Maximum Turn 0 Initialization: ~2.2 s (one-time Python module setup on Windows)
   - Normal Turn Compliance: 100% compliant with the Kaggle 1,000 ms `actTimeout`.

---

## 7. Recommendations for Phase SW-B3C

Based on the empirical evidence from SW-B3B:

1. **Do NOT Promote Core-First Admission (Arm C) as currently configured:**
   Although it protects core assets in catastrophic seeds (Confirmation), its overall cash delta against Arm B (-$1,525.53) and Arm A (-$4,403.38) proves that buying land without agricultural follow-through is financially worse than doing nothing.
2. **Implement Macro-Micro Co-Admission in Phase SW-B3C:**
   - **Condition SW Purchase on Labor Capacity:** `macro_planner.py` should only authorize the $2,000 SW land purchase if worker capacity exceeds core obligations by at least 1.5 dedicated worker equivalents.
   - **Tiered Admission Thresholds:** Separate core tasks into *Hard/Survival* (always preempts SW) versus *Standard/Routine* (permits SW agricultural operations during midday hours 6–15 when crops are watered and animals are fed).
   - **SW Dedicated Time-Slicing:** Allow admitted SW workers to complete a contiguous batch of SW tasks (water + weed + harvest) rather than evaluating task-by-task preemption that traps workers midway.

---

## 8. Verified Deliverables & Artifact Hashes

All 9 deliverable JSON artifacts are preserved in `simulations/results/phase_sw_b3b/`:
- `source_manifest.json`
- `summary_report_data.json`
- `three_arm_matched_outcomes.json`
- `transaction_ledgers.json`
- `paired_waterfalls_c_vs_b.json`
- `paired_waterfalls_c_vs_a.json`
- `inventory_conservation_records.json`
- `worker_action_telemetry.json`
- `task_admission_telemetry.json`

Canonical production baseline remains strictly frozen at `dist/submission.zip` SHA-256 `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`.
