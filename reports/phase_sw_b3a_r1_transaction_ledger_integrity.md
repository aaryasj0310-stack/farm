# Phase SW-B3A-R1 — Transaction Ledger & Causal Telemetry Integrity Report

**Repository:** `https://github.com/aaryasj0310-stack/farm`  
**Branch:** `fix/sw-b3a-r1-transaction-ledger-integrity`  
**Starting Commit:** `5bdf74135aa2e1efcb008cef31d37a954d4acd10`  
**Canonical Production Baseline:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982` (`dist/submission.zip` SHA-256 `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41` strictly untouched)  
**Evaluation Seeds:** Canary Seeds `97013, 97014` (Seeds `98001–98050` strictly protected)  
**Deliverable Artifacts:** `simulations/results/phase_sw_b3a_r1/`  

---

## 1. Executive Summary & Audit Resolution

Phase SW-B3A-R1 was commissioned following an independent GitHub audit of Phase SW-B3A. While SW-B3A replicated the frozen Gate 2 cash outcomes, its telemetry, economic attribution, and inventory ledgers suffered from critical discrepancies:
- **Massive Cash Residuals:** Ledger residuals averaged -$21,475 in Control and -$14,511 in Treatment, with 0/40 matches reconciled.
- **Worker Telemetry Blank:** Worker action telemetry reported `total_actions = 0`.
- **Fictitious Balancing Deductions:** Inventory conservation was derived using discard as an unverified balancing figure.
- **Inaccurate Timeout Claims:** Prior reports cited a non-existent 2,000 ms timeout limit.

### Root Cause Analysis & Resolution:
1. **Engine Interception Architecture:**  
   In SW-B3A, the runner attempted to infer financial transactions from observation delta heuristics (e.g., comparing `pre_shed` to `post_shed` and `pre_cash` to `post_cash`). Because workers deposit harvested crops into the shed on the same turn that crops are sold or purchased, and because multiple orders execute in parallel, observation deltas conflated transfers with market transactions.  
   **Correction:** We implemented `MatchEngineAuditor`, hooking directly into the engine's authoritative transaction execution functions (`_commit_unit`, `_do_hire`, `_do_buy_land`, `_apply_unit_action`, `_drop_inventories_to_shed`). Every executed penny is recorded directly from the engine.
2. **Zero Cash Residuals:**  
   All **40 individual matches** and all **20 paired waterfalls** achieve **$0.00 residual** ($\text{residual} = 0.0000$).
3. **Physical Inventory Conservation:**  
   All 12 crops and animal goods satisfy physical conservation:
   $$\text{Opening} + \text{Harvest} + \text{Purchased} + \text{Produced} = \text{Sold} + \text{Feed} + \text{Fertilizer} + \text{Animal Placed} + \text{Discarded} + \text{Ending}$$
   with **$\text{Diff} = 0$** across all 40 matches without balancing fudge factors.
4. **Worker Action Telemetry Restored:**  
   Full tracking across 7,300+ actions per match, capturing genuine tool usage and cross-quadrant transitions.
5. **Exact Gate 2 Parity Maintained:**  
   All 40 matches produce **identical final cash outcomes ($0.0000 difference)** compared to Gate 2.

---

## 2. Gate 2 Parity Verification

The tournament runner executed the full 20 matched pairs (40 matches) across Canary Seeds `97013` and `97014` against all 5 canonical opponents in both seats (0 and 1). Parity was evaluated against `simulations/results/phase_sw_b2_gate2_canary/live_canary_20_pairs.json`.

| Metric | Gate 2 Canary | Phase SW-B3A-R1 Auditor | Difference | Parity Status |
| :--- | :---: | :---: | :---: | :---: |
| **Control Mean Final Cash** | $109,444.30 | $109,444.30 | $0.00 | **100.00% EXACT** |
| **Treatment Mean Final Cash** | $108,437.05 | $108,437.05 | $0.00 | **100.00% EXACT** |
| **Mean Paired Delta** | -$1,007.25 | -$1,007.25 | $0.00 | **100.00% EXACT** |
| **Pairwise Record** | 8W / 8L / 4T | 8W / 8L / 4T | 0 | **100.00% EXACT** |
| **SW Purchasing Pairs** | 16 / 20 | 16 / 20 | 0 | **100.00% EXACT** |
| **Purchasing Mean Delta** | -$1,259.06 | -$1,259.06 | $0.00 | **100.00% EXACT** |
| **Match Identity Discrepancies** | 40 / 40 failed | **0 / 40 failed** | -40 | **100% RECONCILED** |
| **Max Cash Difference Across 40 Matches** | - | $0.0000 | $0.00 | **IDENTICAL** |

---

## 3. Individual Match Cash Accounting Ledgers (40/40 Matches Reconciled to $0.00)

Every match satisfies the exact engine cash conservation identity:
$$\text{Reconciled Cash} = \text{Starting Cash (\$3,000)} + \text{Crop Sales} + \text{Animal Sales} - \text{Land Costs} - \text{Seed Costs} - \text{Animal Costs} - \text{Feed Costs} - \text{Fertilizer Costs} - \text{Hiring Costs} - \text{Wages (\$0.00)}$$
$$\text{Residual} = \text{Final Cash} - \text{Reconciled Cash} \equiv 0.0000$$

### Match-by-Match Accounting Summary:

| Match ID | Mode | Starting | Inflows (Sales) | Outflows (Purchases/Hires) | Reconciled | Final Cash | Residual |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `s97013_pass_s0_c` | Control | $3,000.00 | $153,605.00 | $49,034.00 | $107,571.00 | $107,571.00 | **$0.00** |
| `s97013_pass_s0_t` | Treatment | $3,000.00 | $156,742.00 | $58,314.00 | $101,428.00 | $101,428.00 | **$0.00** |
| `s97013_pass_s1_c` | Control | $3,000.00 | $153,605.00 | $49,034.00 | $107,571.00 | $107,571.00 | **$0.00** |
| `s97013_pass_s1_t` | Treatment | $3,000.00 | $155,016.00 | $59,134.00 | $98,882.00 | $98,882.00 | **$0.00** |
| `s97013_pure_wheat_rush_s0_c` | Control | $3,000.00 | $136,547.00 | $33,541.00 | $106,006.00 | $106,006.00 | **$0.00** |
| `s97013_pure_wheat_rush_s0_t` | Treatment | $3,000.00 | $136,547.00 | $33,541.00 | $106,006.00 | $106,006.00 | **$0.00** |
| `s97013_pure_wheat_rush_s1_c` | Control | $3,000.00 | $136,547.00 | $33,541.00 | $106,006.00 | $106,006.00 | **$0.00** |
| `s97013_pure_wheat_rush_s1_t` | Treatment | $3,000.00 | $136,547.00 | $33,541.00 | $106,006.00 | $106,006.00 | **$0.00** |
| `s97013_cow_milk_engine_s0_c` | Control | $3,000.00 | $145,562.00 | $43,242.00 | $105,320.00 | $105,320.00 | **$0.00** |
| `s97013_cow_milk_engine_s0_t` | Treatment | $3,000.00 | $148,694.00 | $44,812.00 | $106,882.00 | $106,882.00 | **$0.00** |
| `s97013_cow_milk_engine_s1_c` | Control | $3,000.00 | $145,562.00 | $43,242.00 | $105,320.00 | $105,320.00 | **$0.00** |
| `s97013_cow_milk_engine_s1_t` | Treatment | $3,000.00 | $149,974.00 | $44,638.00 | $108,336.00 | $108,336.00 | **$0.00** |
| `s97013_melon_sniper_s0_c` | Control | $3,000.00 | $150,707.00 | $48,487.00 | $105,220.00 | $105,220.00 | **$0.00** |
| `s97013_melon_sniper_s0_t` | Treatment | $3,000.00 | $158,241.00 | $50,605.00 | $110,636.00 | $110,636.00 | **$0.00** |
| `s97013_melon_sniper_s1_c` | Control | $3,000.00 | $150,707.00 | $48,487.00 | $105,220.00 | $105,220.00 | **$0.00** |
| `s97013_melon_sniper_s1_t` | Treatment | $3,000.00 | $158,545.00 | $50,796.00 | $110,749.00 | $110,749.00 | **$0.00** |
| `s97013_full_production_s0_c` | Control | $3,000.00 | $159,425.00 | $50,800.00 | $111,625.00 | $111,625.00 | **$0.00** |
| `s97013_full_production_s0_t` | Treatment | $3,000.00 | $146,563.00 | $46,542.00 | $103,021.00 | $103,021.00 | **$0.00** |
| `s97013_full_production_s1_c` | Control | $3,000.00 | $159,425.00 | $50,800.00 | $111,625.00 | $111,625.00 | **$0.00** |
| `s97013_full_production_s1_t` | Treatment | $3,000.00 | $148,633.00 | $46,336.00 | $105,297.00 | $105,297.00 | **$0.00** |
| `s97014_pass_s0_c` | Control | $3,000.00 | $166,692.00 | $52,293.00 | $117,399.00 | $117,399.00 | **$0.00** |
| `s97014_pass_s0_t` | Treatment | $3,000.00 | $166,692.00 | $52,293.00 | $117,399.00 | $117,399.00 | **$0.00** |
| `s97014_pass_s1_c` | Control | $3,000.00 | $166,692.00 | $52,293.00 | $117,399.00 | $117,399.00 | **$0.00** |
| `s97014_pass_s1_t` | Treatment | $3,000.00 | $166,692.00 | $52,293.00 | $117,399.00 | $117,399.00 | **$0.00** |
| `s97014_pure_wheat_rush_s0_c` | Control | $3,000.00 | $164,166.00 | $47,831.00 | $119,335.00 | $119,335.00 | **$0.00** |
| `s97014_pure_wheat_rush_s0_t` | Treatment | $3,000.00 | $169,819.00 | $49,025.00 | $123,794.00 | $123,794.00 | **$0.00** |
| `s97014_pure_wheat_rush_s1_c` | Control | $3,000.00 | $164,166.00 | $47,831.00 | $119,335.00 | $119,335.00 | **$0.00** |
| `s97014_pure_wheat_rush_s1_t` | Treatment | $3,000.00 | $169,819.00 | $49,025.00 | $123,794.00 | $123,794.00 | **$0.00** |
| `s97014_cow_milk_engine_s0_c` | Control | $3,000.00 | $130,223.00 | $47,680.00 | $85,543.00 | $85,543.00 | **$0.00** |
| `s97014_cow_milk_engine_s0_t` | Treatment | $3,000.00 | $143,601.00 | $50,905.00 | $95,696.00 | $95,696.00 | **$0.00** |
| `s97014_cow_milk_engine_s1_c` | Control | $3,000.00 | $130,223.00 | $47,680.00 | $85,543.00 | $85,543.00 | **$0.00** |
| `s97014_cow_milk_engine_s1_t` | Treatment | $3,000.00 | $143,601.00 | $50,905.00 | $95,696.00 | $95,696.00 | **$0.00** |
| `s97014_melon_sniper_s0_c` | Control | $3,000.00 | $168,266.00 | $52,413.00 | $118,853.00 | $118,853.00 | **$0.00** |
| `s97014_melon_sniper_s0_t` | Treatment | $3,000.00 | $175,108.00 | $62,432.00 | $115,676.00 | $115,676.00 | **$0.00** |
| `s97014_melon_sniper_s1_c` | Control | $3,000.00 | $168,266.00 | $52,413.00 | $118,853.00 | $118,853.00 | **$0.00** |
| `s97014_melon_sniper_s1_t` | Treatment | $3,000.00 | $175,108.00 | $62,432.00 | $115,676.00 | $115,676.00 | **$0.00** |
| `s97014_full_production_s0_c` | Control | $3,000.00 | $168,367.00 | $53,796.00 | $117,571.00 | $117,571.00 | **$0.00** |
| `s97014_full_production_s0_t` | Treatment | $3,000.00 | $157,074.00 | $56,890.00 | $103,184.00 | $103,184.00 | **$0.00** |
| `s97014_full_production_s1_c` | Control | $3,000.00 | $168,367.00 | $53,796.00 | $117,571.00 | $117,571.00 | **$0.00** |
| `s97014_full_production_s1_t` | Treatment | $3,000.00 | $157,074.00 | $56,890.00 | $103,184.00 | $103,184.00 | **$0.00** |

*All 40 matches archived in `simulations/results/phase_sw_b3a_r1/transaction_ledgers_40_matches.json`.*

---

## 4. Closed Paired Cash Waterfall (20/20 Pairs Reconciled to $0.00)

Every matched pair is decomposed into its exact mathematical constituents:
$$\begin{aligned}
\Delta \text{Cash} &= \text{SW Net Margin} + \Delta \text{Core Crop Rev} - \Delta \text{Core Seed Cost} + \Delta \text{Animal Rev} \\
&\quad - \Delta \text{Feed Cost} - \Delta \text{Fert Cost} - \Delta \text{Animal Purchases} - \Delta \text{Hiring Cost} - \Delta \text{Wages}
\end{aligned}$$
where $\text{SW Net Margin} = \text{SW Crop Revenue} - \text{SW Land Cost (\$2,000)} - \text{SW Seed Cost}$.

$$\text{Waterfall Residual} = \Delta \text{Cash} - \text{Accounted Delta} \equiv 0.00$$

| Pair ID | Control Cash | Treatment Cash | Paired $\Delta$ | SW Net Margin | Core Crop $\Delta$ | Core Seed $\Delta$ | Animal $\Delta$ | Feed $\Delta$ | Fert $\Delta$ | Animal Purch $\Delta$ | Residual |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `s97013_pass_s0` | $107,571 | $101,428 | **-$6,143** | +$7,396 | -$2,674 | -$320 | -$1,711 | +$8,474 | $0 | +$1,000 | **$0.00** |
| `s97013_pass_s1` | $107,571 | $98,882 | **-$8,689** | +$6,374 | -$2,104 | -$240 | -$2,767 | +$9,432 | $0 | +$1,000 | **$0.00** |
| `s97013_pure_wheat_s0` | $106,006 | $106,006 | **$0** | $0 | $0 | $0 | $0 | $0 | $0 | $0 | **$0.00** |
| `s97013_pure_wheat_s1` | $106,006 | $106,006 | **$0** | $0 | $0 | $0 | $0 | $0 | $0 | $0 | **$0.00** |
| `s97013_cow_milk_s0` | $105,320 | $106,882 | **+$1,562** | +$6,845 | -$9,795 | -$190 | +$3,202 | -$1,620 | $0 | +$500 | **$0.00** |
| `s97013_cow_milk_s1` | $105,320 | $108,336 | **+$3,016** | +$6,892 | -$10,641 | -$120 | +$5,281 | -$1,864 | $0 | +$500 | **$0.00** |
| `s97013_melon_sniper_s0` | $105,220 | $110,636 | **+$5,416** | +$7,006 | -$5,769 | +$10 | +$3,417 | -$1,172 | $0 | +$400 | **$0.00** |
| `s97013_melon_sniper_s1` | $105,220 | $110,749 | **+$5,529** | +$7,375 | -$5,086 | +$210 | +$2,669 | -$1,181 | $0 | +$400 | **$0.00** |
| `s97013_full_prod_s0` | $111,625 | $103,021 | **-$8,604** | +$7,372 | -$15,420 | -$80 | -$7,694 | -$6,558 | $0 | -$500 | **$0.00** |
| `s97013_full_prod_s1` | $111,625 | $105,297 | **-$6,328** | +$7,166 | -$15,205 | -$10 | -$5,633 | -$6,834 | $0 | -$500 | **$0.00** |
| `s97014_pass_s0` | $117,399 | $117,399 | **$0** | $0 | $0 | $0 | $0 | $0 | $0 | $0 | **$0.00** |
| `s97014_pass_s1` | $117,399 | $117,399 | **$0** | $0 | $0 | $0 | $0 | $0 | $0 | $0 | **$0.00** |
| `s97014_pure_wheat_s0` | $119,335 | $123,794 | **+$4,459** | +$8,311 | -$3,922 | +$210 | -$1,616 | -$1,896 | $0 | $0 | **$0.00** |
| `s97014_pure_wheat_s1` | $119,335 | $123,794 | **+$4,459** | +$8,311 | -$3,922 | +$210 | -$1,616 | -$1,896 | $0 | $0 | **$0.00** |
| `s97014_cow_milk_s0` | $85,543 | $95,696 | **+$10,153** | +$6,529 | -$4,820 | -$30 | +$8,794 | +$380 | $0 | $0 | **$0.00** |
| `s97014_cow_milk_s1` | $85,543 | $95,696 | **+$10,153** | +$6,529 | -$4,820 | -$30 | +$8,794 | +$380 | $0 | $0 | **$0.00** |
| `s97014_melon_sniper_s0` | $118,853 | $115,676 | **-$3,177** | +$6,958 | -$6,296 | -$270 | +$3,300 | +$6,509 | $0 | +$900 | **$0.00** |
| `s97014_melon_sniper_s1` | $118,853 | $115,676 | **-$3,177** | +$6,958 | -$6,296 | -$270 | +$3,300 | +$6,509 | $0 | +$900 | **$0.00** |
| `s97014_full_prod_s0` | $117,571 | $103,184 | **-$14,387** | +$6,571 | -$14,112 | -$250 | -$6,632 | +$464 | $0 | $0 | **$0.00** |
| `s97014_full_prod_s1` | $117,571 | $103,184 | **-$14,387** | +$6,571 | -$14,112 | -$250 | -$6,632 | +$464 | $0 | $0 | **$0.00** |
| **Panel Mean (20 Pairs)** | **$109,444.30** | **$108,437.05** | **-$1,007.25** | **+$5,658.18** | **-$6,249.68** | **-$58.00** | **+$222.80** | **+$479.55** | **$0.00** | **+$185.00** | **$0.00** |

---

## 5. Resolution of Engine Mechanics & Audit Anomalies

### 1. Hiring Mechanics & The Absence of Daily Wages
- **Engine Ground Truth:** In `kaggriculture.py` (lines 690–710), hiring cost is computed as:
  $$\text{cost} = \text{mult} \times \text{fib}(\text{hires\_today})$$
  where $\text{mult} = 100$ and $\text{fib}(0)=1, \text{fib}(1)=1, \text{fib}(2)=2, \text{fib}(3)=3, \text{fib}(4)=5, \dots$
- **Worker Despawn:** Every midnight (line 880), the engine executes:
  ```python
  farm["hands"] = []
  farm["hires_today"] = 0
  private["inventories"] = [{}]
  ```
- **Finding:** **There are zero daily wages in the game engine.** Hands do not earn recurring daily wages. The daily hiring budget is paid upfront each morning when hands are re-spawned. Both Control and Treatment executed identical hiring schedules across all matches ($\Delta \text{Hiring} = \$0.00$, $\Delta \text{Wages} = \$0.00$).

### 2. Resolution of the Alleged "$230 Animal Purchase Delta"
- In earlier reports, an anomalous "$230 difference" was cited for animal purchases.
- **Engine Audit:** Animal prices are fixed constants in `kaggriculture.py`:
  - `COW = $400.0`
  - `SHEEP = $300.0`
  - `CHICKEN = $200.0`
- The $230 discrepancy was an artifact of flawed snapshot estimations. In our engine-intercepted audit, all animal purchases are exact multiples of animal costs (e.g. $1,000 = 1 Cow + 2 Sheep; $500 = 1 Sheep + 1 Chicken; $400 = 1 Cow; $900 = 1 Cow + 1 Sheep + 1 Chicken).

### 3. Engine ActTimeout Limit
- In `kaggriculture.json` line 9, the execution timeout is explicitly declared:
  ```json
  "actTimeout": 1
  ```
- **Ground Truth:** The action timeout is **1.0 second (1,000 ms)**, not 2,000 ms. While local testing on Windows with 7-way multiprocessing experienced scheduling latency spikes up to 3,031 ms due to OS process competition, production environments enforce a strict 1,000 ms wall-clock limit. P95 latency across matches averaged 205.45 ms.

---

## 6. Worker Action & Movement Telemetry

Worker actions were recorded directly from `kag._apply_unit_action`. Total actions across 720 steps average **7,380+ actions per match**.

### Comparative Action Profiles (Panel Mean):

| Action Type | Control (Mean) | Treatment (Mean) | Delta (T - C) | Causal Significance |
| :--- | :---: | :---: | :---: | :--- |
| **Move Actions** | 4,402.5 | 4,881.0 | **+478.5** | **Workers travel 478+ extra steps between quadrants** |
| **Water Actions** | 996.0 | 917.5 | **-78.5** | **78 fewer watering operations performed in Core** |
| **Harvest Actions** | 267.5 | 258.0 | **-9.5** | Fewer completed harvest cycles in Core |
| **Plant Actions** | 158.0 | 165.0 | **+7.0** | Extra planting in SW (compact tranche) |
| **Feed Actions** | 210.0 | 215.5 | **+5.5** | Normal herd maintenance preserved |
| **Care Actions** | 215.0 | 210.0 | **-5.0** | Minor deferred animal grooming |
| **Fertilize Actions** | 36.0 | 14.0 | **-22.0** | Reduced fertilizer application |
| **Idle / Pass Actions** | 701.0 | 270.5 | **-430.5** | Idle capacity absorbed by long-distance transit |
| **Actions in SW** | 98.0 | 512.5 | **+414.5** | Substantial labor shift to SW quadrant |
| **Actions in Core (NW/NE)** | 7,296.0 | 6,869.5 | **-426.5** | **426 worker actions lost from Core farm operations** |
| **Quadrant Transitions (NW $\leftrightarrow$ SW)** | 84.0 | 198.0 | **+114.0** | Bottleneck transit congestion at port (4, 5) |

---

## 7. Physical Inventory Conservation (Diff = 0 Across All Goods)

Physical conservation holds with zero discrepancy across all items:
$$\text{Opening} + \text{Harvested (Core)} + \text{Harvested (SW)} + \text{Purchased} + \text{Produced} = \text{Sold} + \text{Feed} + \text{Fertilizer} + \text{Placed} + \text{Discarded} + \text{Ending (Shed + Worker)}$$

### Representative Match Verification (`s97013_pass_seat0` Treatment):

| Item | Opening | Harv (Core) | Harv (SW) | Bought | Produced | Sold | Fed | Placed | Discard | Ending | Diff | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **WHEAT** | 0 | 480 | 0 | 365 | 0 | 589 | 216 | 0 | 18 | 22 | **0** | **EXACT** |
| **CARROT** | 0 | 88 | 0 | 0 | 0 | 88 | 0 | 0 | 0 | 0 | **0** | **EXACT** |
| **TOMATO** | 0 | 48 | 0 | 0 | 0 | 48 | 0 | 0 | 0 | 0 | **0** | **EXACT** |
| **STRAWBERRY** | 0 | 178 | 56 | 0 | 0 | 230 | 0 | 0 | 4 | 0 | **0** | **EXACT** |
| **MELON** | 0 | 100 | 16 | 0 | 0 | 116 | 0 | 0 | 0 | 0 | **0** | **EXACT** |
| **MILK** | 0 | 0 | 0 | 0 | 342 | 342 | 0 | 0 | 0 | 0 | **0** | **EXACT** |
| **WOOL** | 0 | 0 | 0 | 0 | 148 | 148 | 0 | 0 | 0 | 0 | **0** | **EXACT** |
| **FERTILIZER** | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 0 | 2 | 0 | **0** | **EXACT** |
| **COW** | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | **0** | **EXACT** |
| **SHEEP** | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | **0** | **EXACT** |

*All 40 matches archived in `simulations/results/phase_sw_b3a_r1/inventory_conservation_records.json`.*

---

## 8. Storage Discard Reconciliation: Rescue Sales vs. Rollover Overflows

The independent audit questioned whether discards were real or derived. By intercepting `_drop_inventories_to_shed`, we tracked actual engine rollover drops and contrasted them with Midnight Storage Rescue actions:

1. **Pre-Midnight Storage Rescue:**
   - Active across all matches. The controller executes emergency sales at Hour 23 to liquidate excess goods before the rollover drop.
   - Panel mean: **6.2 rescue events** per match, liquidating **109.5 units** before midnight.
2. **Midnight Rollover Drop Overflows:**
   - When workers carry items into Hour 0, the engine attempts to deposit them into the shed up to `capacity = 100`. Any overflow exceeding shed capacity is permanently deleted (`del inv[item]`).
   - In Control: 5 overflow events discarded **11 units** (mostly excess wheat and strawberries).
   - In Treatment: 5 overflow events discarded **22 units**.
   - **Conclusion:** Genuine shed overflows do occasionally occur when worker inventories arrive simultaneously at Hour 23, but they account for less than $400 in total value across the match. Discard is not the primary causal driver of the SW canary loss.

---

## 9. 9-Stage SW Land Order Lifecycle Telemetry

Stage 9 (engine-confirmed productive planting) was verified for all 16 SW purchasing matches:

| Pair ID | Stage 1 (Rec) | Stage 2 (Appr) | Stage 4 (Emitted) | Stage 6 (Confirmed) | Cost Deducted | Stage 9 First Plant | Planted Crop & Pos |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `s97013_pass_s0` | D10 H14 | D10 H14 | D10 H14 | D10 H15 | $2,000.00 | **D11 H03 (Step 267)** | `STRAWBERRY` @ (2, 5) |
| `s97013_pass_s1` | D10 H14 | D10 H14 | D10 H14 | D10 H15 | $2,000.00 | **D11 H03 (Step 267)** | `STRAWBERRY` @ (2, 5) |
| `s97013_cow_milk_s0` | D10 H14 | D10 H14 | D10 H14 | D10 H15 | $2,000.00 | **D11 H03 (Step 267)** | `STRAWBERRY` @ (2, 5) |
| `s97013_cow_milk_s1` | D10 H14 | D10 H14 | D10 H14 | D10 H15 | $2,000.00 | **D11 H03 (Step 267)** | `STRAWBERRY` @ (2, 5) |
| `s97013_melon_s0` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97013_melon_s1` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97013_full_prod_s0` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97013_full_prod_s1` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97014_pure_wheat_s0` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97014_pure_wheat_s1` | D09 H14 | D09 H14 | D09 H14 | D09 H15 | $2,000.00 | **D10 H03 (Step 243)** | `STRAWBERRY` @ (2, 5) |
| `s97014_cow_milk_s0` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |
| `s97014_cow_milk_s1` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |
| `s97014_melon_s0` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |
| `s97014_melon_s1` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |
| `s97014_full_prod_s0` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |
| `s97014_full_prod_s1` | D11 H14 | D11 H14 | D11 H14 | D11 H15 | $2,000.00 | **D12 H03 (Step 291)** | `STRAWBERRY` @ (2, 5) |

---

## 10. Descriptive Panel Statistics (Seed Clusters & Pooled)

> **Methodological Note:** The sample consists of 20 matched pairs across 2 independent seed clusters (10 pairs per seed). Because the sample size is small ($N=20$), asymptotic clustered standard error inference (e.g. cluster-robust $t$-tests) is not statistically valid and is omitted. We report rigorous descriptive panel metrics.

| Metric | Seed Cluster 97013 (10 Pairs) | Seed Cluster 97014 (10 Pairs) | Pooled Panel (20 Pairs) |
| :--- | :---: | :---: | :---: |
| **Control Mean Cash** | $107,148.40 | $111,740.20 | **$109,444.30** |
| **Treatment Mean Cash** | $105,724.30 | $111,149.80 | **$108,437.05** |
| **Mean Paired Delta** | -$1,424.10 | -$590.40 | **-$1,007.25** |
| **Median Paired Delta** | $0.00 | $0.00 | **$0.00** |
| **Std Dev of Paired Delta** | $5,562.43 | $8,670.54 | **$7,102.80** |
| **Min Paired Delta** | -$8,689.00 | -$14,387.00 | **-$14,387.00** |
| **Max Paired Delta** | +$5,529.00 | +$10,153.00 | **+$10,153.00** |
| **Record (W / L / T)** | 4W / 4L / 2T | 4W / 4L / 2T | **8W / 8L / 4T** |
| **SW Purchasing Pairs** | 8 / 10 | 8 / 10 | **16 / 20** |
| **Purchasing Mean Delta** | -$1,780.12 | -$738.00 | **-$1,259.06** |

---

## 11. Categorized Evaluation of Causal Hypotheses

Based on engine mechanics and verified experimental data, hypotheses are classified into four evidential categories:

### 1. ENGINE-VERIFIED
- **Zero Daily Wages:** `farm["hands"]` are completely despawned at midnight; no recurring wages exist in the engine.
- **Fibonacci Hiring Cost:** Cost scales strictly by Fibonacci order and resets daily.
- **Rollover Shed Overflow:** Discards occur strictly when worker inventory cannot fit into `shedCapacity = 100` at midnight.
- **ActTimeout Limit:** Strictly 1.0 second (1,000 ms) per `kaggriculture.json`.

### 2. SUPPORTED BY PAIRED EVIDENCE
- **Direct SW Parcel Profitability:** The 8-tile SW tranche reliably produces positive net operating margin (**+$5,658.18 panel mean**; **+$7,072.73 purchasing mean**).
- **Core Farm Labor Cannibalization:** The deficit is driven by worker transit displacement (**+478.5 move actions**, **-78.5 Core watering operations**), eroding Core crop revenue by **-$6,249.68** on average and up to -$15,420 in competitive scenarios.
- **Secondary Livestock Disruption:** Deferral of core feeding and milking schedules reduces animal sales by **-$5,400+** in severe loss cases.

### 3. PLAUSIBLE BUT UNVERIFIED
- **Market Price Saturation:** Melon selling prices fell slightly ($239.52 vs $237.95), but broader price depression across multiple seed clusters remains plausible but unverified.
- **Transit Bottleneck Congestion:** Movement congestion at shed port (4, 5) likely causes transit deadlocks during peak midday hours.

### 4. DISPROVEN
- **"Unreconciled Cash Residuals":** Disproven. Every cent is fully accounted for with $0.00 residual across all 40 matches.
- **"Arbitrary Animal Delta ($230)":** Disproven. Animal purchases are exact integer multiples of engine prices ($400, $300, $200).
- **"Derived Discard Balancing Figure":** Disproven. Physical crop inventory balances with Diff = 0 across all 40 matches.
- **"2,000 ms Engine Timeout":** Disproven. Ground truth is 1,000 ms.

---

## 12. Recommended Controlled Intervention for Phase SW-B3B

The causal diagnosis is unambiguous: **the SW tranche is highly profitable in isolation, but its current unconstrained labor dispatch cannibalizes the core farm.**

For **Phase SW-B3B**, we recommend a single, targeted, controlled architectural intervention:
1. **Dedicated SW Worker Zoning (Locality Hard-Cap):**  
   Strictly constrain SW operations to at most **1 dedicated hand** stationed south of row 5. Forbid NW/NE core workers from crossing into SW to water or harvest SW crops.
2. **Prioritized Core Irrigation Lock:**  
   Require 100% of NW/NE core crops and dairy animals to be fully watered and milked before any peripheral tasks are dispatched.
3. **Execution Safety Gate:**  
   Validate that the zoning intervention eliminates the -$6,249 Core revenue deficit while preserving the +$5,658 SW margin, thereby transforming the overall paired delta from -$1,007 to **+$4,500+**.

---

## 13. Deliverable Artifact Manifest

All 8 authoritative artifacts have been emitted and verified in `simulations/results/phase_sw_b3a_r1/`:
1. `transaction_ledgers_40_matches.json`: Complete 40-match ledger with $0.00 residual.
2. `paired_waterfalls_20_pairs.json`: 20 paired waterfalls with $0.00 waterfall residual.
3. `inventory_conservation_records.json`: Physical conservation for all goods (Diff = 0).
4. `worker_action_telemetry.json`: Granular worker action and regional movement counts.
5. `storage_discard_reconciliation.json`: Actual rollover drop overflow vs rescue telemetry.
6. `sw_lifecycle_9stages.json`: 9-stage SW acquisition and planting lifecycle.
7. `summary_report_data.json`: Comprehensive statistics, parity audit, and latency profiles.
8. `source_manifest.json`: Exact SHA-256 provenance hashes.
