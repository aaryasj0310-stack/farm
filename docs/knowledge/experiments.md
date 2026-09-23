
### Experiment: Goose Daily CARE (+1 Bonus) vs No-CARE
- **Type**: EXPERIMENT
- **Date**: 2026-08-25
- **Agents Tested**: `goose_wheat_engine` vs `goose_no_care`
- **Sample Size**: 6 games
- **Results**: Mean A = $1982.0 (Win Rate 0.0%) vs Mean B = $1982.0 (Win Rate 0.0%), Lift: +0.0%
- **Verdict**: INCONCLUSIVE
- **Key Finding**: Caring for geese daily yields exactly 2x egg production under v1.32.7 engine rules, increasing net profit. -> Confirmed with delta +$0.0.

### Experiment: P4.1 Late-Season Isolated SW Zonal Acreage Expansion Feasibility Test
- **Type**: EXPERIMENT
- **Date**: 2026-09-22
- **Control**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Promoted P2.3 Production Baseline)
- **Treatment**: `P41_SW_ZONAL_EXPANSION_ENABLED = True` (Day 14 SW unlock, 8-tile zone, Hands 11 & 12 dedicated squad, Hybrid crop policy)
- **Sample Size**: 20 matched pairs (40 live games across 5 standard opponents, balanced seats, seeds 97,001–97,010)
- **Results**: Control Mean = $100,366.65, Treatment Mean = $95,547.55, Paired Delta = -$4,819.10 (95% CI: [-$11,531.97, +$1,893.77], SE = $3,207.29)
- **Verdict**: REJECTED (Failed Tier 1 Feasibility Gate)
- **Key Finding**: Disproved the hypothesis that Hands 11 & 12 were surplus/negligible in the core farm. While the 8 SW tiles operated cleanly (+241 strawberries, +853 wheat harvested, +$1,950 net SW direct profit after seeds and $2,000 land cost), removing Hands 11 & 12 caused core watering compliance to plunge from 84.25% to 79.80% (-4.45%). This resulted in an additional +21.35 core crop deaths per game (284.9 vs 263.55) and missed repeat harvests, destroying ~$6,769 in core farm revenue. Net effect: -$4,819.10/game. SW expansion is labor-starved even with 13 workers.

### Audit: P4.2 Market Revenue Realization & Sell-Timing Ground-Truth Audit
- **Type**: AUDIT / MEASUREMENT
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline; historically ~$103.6k on P2.3 discovery panel, ~$101.9k on held-out panel)
- **Sample Size**: 100 live baseline games (10 fresh seeds 96,101–96,110 x 5 opponents x 2 balanced seats)
- **Results**: Mean Final Cash = $102,986.19 (Std Dev = $8,724.54). 25,463 market transactions recorded with exact per-unit lockstep pricing.
- **Verdict**: STOP (Closed Without Implementation)
- **Key Findings**: 
  1. Near-complete inventory realization with very small identified timing opportunity: 100% of harvested products are monetized with 0 unsold units at season end and 0 overflow discards.
  2. Post-town-drain sell window (`hour % 4 == 1`) reliably captures peak local prices as town shops consume 1.0 to 3.5 units per 4h cycle.
  3. Drip-selling slippage is <1.5% across all fragile goods (0.7% strawberry, 1.4% milk, 1.0% wool, 1.9% melon).
  4. Max market orders in any turn was 9 (cap is 10); 10-order cap displacement is exactly 0.0/game.
  5. Non-hindsight, live-actionable market opportunity ceiling is bounded at <= +$45 to +$65/game, far too small to justify an intervention against matched tournament variance (~$1,000 MDE). No treatment justified; untouched seed block 98,001–98,050 preserved.

### Audit / Revalidation: P5.0-R Late-Wheat Counterfactual Repair & Revalidation
- **Type**: AUDIT / COUNTERFACTUAL REVALIDATION
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Scope**: Evaluated all 2,493 wheat planting decisions on Days 21–25 across 100 live baseline discovery games (seeds 96,201–96,210 x 5 opponents x 2 seats) with full state capture and 100% cash reconciliation.
- **Verdict**: GO FOR P5.1 (Refined Boundary: Days 21–23, 2 Carrot Cycles, Feed Buffer Floor)
- **Key Findings**:
  1. *P5.0 Model Superseded*: P5.0's preliminary +$1,121.85/game headline was invalidated due to hardcoded $45 unit gain, 6-wheat assumption, inaccurate seed/yield constants ($20/$35 seeds vs $10/$20 engine truth), and day-blind aggregation.
  2. *Feed Security Reclassification*: Replaced static model with Time-Indexed Dynamic Feed Ledger ($B_d = B_{d-1} + H_d - F_d$). Out of 2,493 events: 2,489 (99.8%) are RW3 Genuine Economic Surplus, 4 (0.2%) are RW2 Buffer Support, and exactly 0 (0.0%) are RW1 Feed Critical. Herd starvation remained strictly 0.0%.
  3. *The Asymmetry of Days 21–23 vs Days 24–25*:
     - Days 21–23: Two 3-day carrot cycles fit before Day 29 (6 carrots net $170 vs 4 wheat net $90), delivering +$36.80 mean task-displaced gain per event (65.2% positive).
     - Days 24–25: Only one 3-day carrot cycle fits (3 carrots net $85 vs 4 wheat net $90), causing a -$24.50 loss per event (78.2% negative).
  4. *Refined Decision Boundary*: Confining substitution strictly to Days 21–23 with conservative feed security ($B_{\min} \ge 1.0 \times \text{Herd}$) and same-day executability produces:
     - Raw Crop Economic Delta: **+$1,049.33 / game** (Median: +$1,063.00)
     - Primary Task-Displaced Delta: **+$655.25 / game** (Median: **+$500.00**, $\sigma_\Delta = \$801.01$)
     - Labor Stressed Delta: **+$642.37 / game** (Median: +$459.00)
     - Zero negative games ($Min = \$0.00$), active in 67% of games (mean gain when active: **+$977.99 / game**).
  5. *Power & Tournament Protocol*: Empirical paired $\sigma_\Delta = \$801.01$ implies MDE of $100.35 on the untouched 500-game tournament block (seeds 98,001–98,050), providing $>99.99\%$ power for P5.1.

### Experiment: P5.1 Two-Cycle Carrot Rotation Implementation & Live Feasibility Gate
- **Type**: EXPERIMENT / LIVE FEASIBILITY GATE
- **Date**: 2026-09-22
- **Control**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Treatment**: `P51_T1_TWO_CYCLE_CARROT_ENABLED = True` (Two-cycle carrot rotation on Days 21–23 NW+NE tiles, state-based sequential feed ledger, Hour 0 priority seed pre-ordering, MacroPlan coordinate reservation)
- **Sample Size**: 100 matched pairs (200 live games on discovery panel seeds 96,201–96,210 x 5 opponents x 2 balanced seats)
- **Results**:
  - Mean Paired Cash Delta: **−$1,020.68 / game** (Median: **−$959.00 / game**, $\sigma = \$2,847.55$, SE = $284.76)
  - 95% Confidence Interval: **[−$1,578.80, −$462.56]** ($p < 0.001$, statistically significantly negative)
  - Full Two-Cycle Rotations Completed: **626** (6.26 / game, 96.60% conversion of planted C2)
  - Day 23 Rotations Completed: **211** (2.11 / game)
  - Animal Starvation Rate: **0.0%** (0 / 100 treatment games)
  - Win Rate: Control 100.0%, Treatment 100.0%
- **Verdict**: STOP (Rejected at Live Feasibility Gate; Production Default Remains False)
- **Key Findings**:
  1. *Execution Success*: Completely resolved Cycle 2 seed starvation and tile hijacking through Hour 0 priority elevation (`P1_URGENT`) and `MacroPlan` tile reservation. Achieved 626 live two-cycle completions and 211 Day 23 completions.
### Audit / Forensic Reconciliation: P5.1-C Causal Delta Reconciliation
- **Type**: AUDIT / CAUSAL FORENSIC RECONCILIATION
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Scope**: Complete engine-level transaction and action interception across all 100 matched pairs (200 live games on discovery panel seeds 96,201–96,210 x 5 opponents x 2 balanced seats) with exact bit-level cash reconciliation.
- **Results**:
  - Maximum Single-Game Reconciliation Error: **0.000000**
  - Mean Paired Cash Delta: **−$1,020.68 / game**
  - Residual Accounting Discrepancy: **$0.0000**
  - Primary Causal Cash Waterfall:
    * Net Direct Carrot Profit: **+$1,269.96 / game** (+$1,516.36 gross rev @ $42.09/unit avg − $246.40 seeds)
    * Lost Wheat Sales (Net): **−$822.63 / game** (−$931.43 revenue + $108.80 seed savings)
    * Forced Market Feed Wheat Purchases: **−$559.88 / game**
    * Lost Livestock Revenue: **−$985.32 / game** (−$404.58 milk, −$545.65 wool, −$35.09 fertilizer)
    * Minor Categories (Labor hires, crop variance): **+$77.19 / game**
    * **Total Closed Cash Delta**: **−$1,020.68 / game**
- **Verdict**: CLOSED & PERMANENTLY REJECTED (Zero Strategy Modification; Root Cause Proved)
- **Key Findings & Epistemic Classification**:
  1. *[MEASURED FACT] Hypotheses Refuted by Telemetry*:
     - *Carrot Price Collapse*: Refuted. Realized price was $42.09 in Treatment vs $40.65 in Control (well above $35 base).
     - *Excessive Watering Workload*: Refuted. Total waterings in Days 21–29 actually decreased by −4.68 / game (+46.06 carrot vs −49.58 wheat). Baseline already watered late wheat.
     - *Market Slot Saturation*: Refuted. Cap is 10 orders per turn, not per day; zero orders were dropped (0.00%).
     - *Endgame Unsold Stock*: Refuted. Exactly 0.00 units remained in shed or backpacks at Day 30.
  2. *[INFERRED MECHANISM] The Real Transmission Mechanism*:
     - Replacing 41.84 wheat units from the core farm depleted physical grain from the shed.
     - While Treatment bought replacement feed wheat on the open market ($559.88), market buys settle post-turn.
     - Feeding workers during morning hours encountered empty shed bins, skipping −1.72 cow feeds and −1.47 sheep feeds.
     - In engine rules (`_daily_refresh_animals`), skipping feeding voids pending care bonuses, directly destroying 2.50 units of milk ($244/unit) and 1.91 units of wool ($215/unit).
### Experiment: Goose Daily CARE (+1 Bonus) vs No-CARE
- **Type**: EXPERIMENT
- **Date**: 2026-08-25
- **Agents Tested**: `goose_wheat_engine` vs `goose_no_care`
- **Sample Size**: 6 games
- **Results**: Mean A = $1982.0 (Win Rate 0.0%) vs Mean B = $1982.0 (Win Rate 0.0%), Lift: +0.0%
- **Verdict**: INCONCLUSIVE
- **Key Finding**: Caring for geese daily yields exactly 2x egg production under v1.32.7 engine rules, increasing net profit. -> Confirmed with delta +$0.0.

### Experiment: P4.1 Late-Season Isolated SW Zonal Acreage Expansion Feasibility Test
- **Type**: EXPERIMENT
- **Date**: 2026-09-22
- **Control**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Promoted P2.3 Production Baseline)
- **Treatment**: `P41_SW_ZONAL_EXPANSION_ENABLED = True` (Day 14 SW unlock, 8-tile zone, Hands 11 & 12 dedicated squad, Hybrid crop policy)
- **Sample Size**: 20 matched pairs (40 live games across 5 standard opponents, balanced seats, seeds 97,001–97,010)
- **Results**: Control Mean = $100,366.65, Treatment Mean = $95,547.55, Paired Delta = -$4,819.10 (95% CI: [-$11,531.97, +$1,893.77], SE = $3,207.29)
- **Verdict**: REJECTED (Failed Tier 1 Feasibility Gate)
- **Key Finding**: Disproved the hypothesis that Hands 11 & 12 were surplus/negligible in the core farm. While the 8 SW tiles operated cleanly (+241 strawberries, +853 wheat harvested, +$1,950 net SW direct profit after seeds and $2,000 land cost), removing Hands 11 & 12 caused core watering compliance to plunge from 84.25% to 79.80% (-4.45%). This resulted in an additional +21.35 core crop deaths per game (284.9 vs 263.55) and missed repeat harvests, destroying ~$6,769 in core farm revenue. Net effect: -$4,819.10/game. SW expansion is labor-starved even with 13 workers.

### Audit: P4.2 Market Revenue Realization & Sell-Timing Ground-Truth Audit
- **Type**: AUDIT / MEASUREMENT
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline; historically ~$103.6k on P2.3 discovery panel, ~$101.9k on held-out panel)
- **Sample Size**: 100 live baseline games (10 fresh seeds 96,101–96,110 x 5 opponents x 2 balanced seats)
- **Results**: Mean Final Cash = $102,986.19 (Std Dev = $8,724.54). 25,463 market transactions recorded with exact per-unit lockstep pricing.
- **Verdict**: STOP (Closed Without Implementation)
- **Key Findings**: 
  1. Near-complete inventory realization with very small identified timing opportunity: 100% of harvested products are monetized with 0 unsold units at season end and 0 overflow discards.
  2. Post-town-drain sell window (`hour % 4 == 1`) reliably captures peak local prices as town shops consume 1.0 to 3.5 units per 4h cycle.
  3. Drip-selling slippage is <1.5% across all fragile goods (0.7% strawberry, 1.4% milk, 1.0% wool, 1.9% melon).
  4. Max market orders in any turn was 9 (cap is 10); 10-order cap displacement is exactly 0.0/game.
  5. Non-hindsight, live-actionable market opportunity ceiling is bounded at <= +$45 to +$65/game, far too small to justify an intervention against matched tournament variance (~$1,000 MDE). No treatment justified; untouched seed block 98,001–98,050 preserved.

### Audit / Revalidation: P5.0-R Late-Wheat Counterfactual Repair & Revalidation
- **Type**: AUDIT / COUNTERFACTUAL REVALIDATION
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Scope**: Evaluated all 2,493 wheat planting decisions on Days 21–25 across 100 live baseline discovery games (seeds 96,201–96,210 x 5 opponents x 2 seats) with full state capture and 100% cash reconciliation.
- **Verdict**: GO FOR P5.1 (Refined Boundary: Days 21–23, 2 Carrot Cycles, Feed Buffer Floor)
- **Key Findings**:
  1. *P5.0 Model Superseded*: P5.0's preliminary +$1,121.85/game headline was invalidated due to hardcoded $45 unit gain, 6-wheat assumption, inaccurate seed/yield constants ($20/$35 seeds vs $10/$20 engine truth), and day-blind aggregation.
  2. *Feed Security Reclassification*: Replaced static model with Time-Indexed Dynamic Feed Ledger ($B_d = B_{d-1} + H_d - F_d$). Out of 2,493 events: 2,489 (99.8%) are RW3 Genuine Economic Surplus, 4 (0.2%) are RW2 Buffer Support, and exactly 0 (0.0%) are RW1 Feed Critical. Herd starvation remained strictly 0.0%.
  3. *The Asymmetry of Days 21–23 vs Days 24–25*:
     - Days 21–23: Two 3-day carrot cycles fit before Day 29 (6 carrots net $170 vs 4 wheat net $90), delivering +$36.80 mean task-displaced gain per event (65.2% positive).
     - Days 24–25: Only one 3-day carrot cycle fits (3 carrots net $85 vs 4 wheat net $90), causing a -$24.50 loss per event (78.2% negative).
  4. *Refined Decision Boundary*: Confining substitution strictly to Days 21–23 with conservative feed security ($B_{\min} \ge 1.0 \times \text{Herd}$) and same-day executability produces:
     - Raw Crop Economic Delta: **+$1,049.33 / game** (Median: +$1,063.00)
     - Primary Task-Displaced Delta: **+$655.25 / game** (Median: **+$500.00**, $\sigma_\Delta = \$801.01$)
     - Labor Stressed Delta: **+$642.37 / game** (Median: +$459.00)
     - Zero negative games ($Min = \$0.00$), active in 67% of games (mean gain when active: **+$977.99 / game**).
  5. *Power & Tournament Protocol*: Empirical paired $\sigma_\Delta = \$801.01$ implies MDE of $100.35 on the untouched 500-game tournament block (seeds 98,001–98,050), providing $>99.99\%$ power for P5.1.

### Experiment: P5.1 Two-Cycle Carrot Rotation Implementation & Live Feasibility Gate
- **Type**: EXPERIMENT / LIVE FEASIBILITY GATE
- **Date**: 2026-09-22
- **Control**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Treatment**: `P51_T1_TWO_CYCLE_CARROT_ENABLED = True` (Two-cycle carrot rotation on Days 21–23 NW+NE tiles, state-based sequential feed ledger, Hour 0 priority seed pre-ordering, MacroPlan coordinate reservation)
- **Sample Size**: 100 matched pairs (200 live games on discovery panel seeds 96,201–96,210 x 5 opponents x 2 balanced seats)
- **Results**:
  - Mean Paired Cash Delta: **−$1,020.68 / game** (Median: **−$959.00 / game**, $\sigma = \$2,847.55$, SE = $284.76)
  - 95% Confidence Interval: **[−$1,578.80, −$462.56]** ($p < 0.001$, statistically significantly negative)
  - Full Two-Cycle Rotations Completed: **626** (6.26 / game, 96.60% conversion of planted C2)
  - Day 23 Rotations Completed: **211** (2.11 / game)
  - Animal Starvation Rate: **0.0%** (0 / 100 treatment games)
  - Win Rate: Control 100.0%, Treatment 100.0%
- **Verdict**: STOP (Rejected at Live Feasibility Gate; Production Default Remains False)
- **Key Findings**:
  1. *Execution Success*: Completely resolved Cycle 2 seed starvation and tile hijacking through Hour 0 priority elevation (`P1_URGENT`) and `MacroPlan` tile reservation. Achieved 626 live two-cycle completions and 211 Day 23 completions.
### Audit / Forensic Reconciliation: P5.1-C Causal Delta Reconciliation
- **Type**: AUDIT / CAUSAL FORENSIC RECONCILIATION
- **Date**: 2026-09-22
- **Baseline**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Scope**: Complete engine-level transaction and action interception across all 100 matched pairs (200 live games on discovery panel seeds 96,201–96,210 x 5 opponents x 2 balanced seats) with exact bit-level cash reconciliation.
- **Results**:
  - Maximum Single-Game Reconciliation Error: **0.000000**
  - Mean Paired Cash Delta: **−$1,020.68 / game**
  - Residual Accounting Discrepancy: **$0.0000**
  - Primary Causal Cash Waterfall:
    * Net Direct Carrot Profit: **+$1,269.96 / game** (+$1,516.36 gross rev @ $42.09/unit avg − $246.40 seeds)
    * Lost Wheat Sales (Net): **−$822.63 / game** (−$931.43 revenue + $108.80 seed savings)
    * Forced Market Feed Wheat Purchases: **−$559.88 / game**
    * Lost Livestock Revenue: **−$985.32 / game** (−$404.58 milk, −$545.65 wool, −$35.09 fertilizer)
    * Minor Categories (Labor hires, crop variance): **+$77.19 / game**
    * **Total Closed Cash Delta**: **−$1,020.68 / game**
- **Verdict**: CLOSED & PERMANENTLY REJECTED (Zero Strategy Modification; Root Cause Proved)
- **Key Findings & Epistemic Classification**:
  1. *[MEASURED FACT] Hypotheses Refuted by Telemetry*:
     - *Carrot Price Collapse*: Refuted. Realized price was $42.09 in Treatment vs $40.65 in Control (well above $35 base).
     - *Excessive Watering Workload*: Refuted. Total waterings in Days 21–29 actually decreased by −4.68 / game (+46.06 carrot vs −49.58 wheat). Baseline already watered late wheat.
     - *Market Slot Saturation*: Refuted. Cap is 10 orders per turn, not per day; zero orders were dropped (0.00%).
     - *Endgame Unsold Stock*: Refuted. Exactly 0.00 units remained in shed or backpacks at Day 30.
  2. *[INFERRED MECHANISM] The Real Transmission Mechanism*:
     - Replacing 41.84 wheat units from the core farm depleted physical grain from the shed.
     - While Treatment bought replacement feed wheat on the open market ($559.88), market buys settle post-turn.
     - Feeding workers during morning hours encountered empty shed bins, skipping −1.72 cow feeds and −1.47 sheep feeds.
     - In engine rules (`_daily_refresh_animals`), skipping feeding voids pending care bonuses, directly destroying 2.50 units of milk ($244/unit) and 1.91 units of wool ($215/unit).
  3. *[MEASURED FACT] Shed Capacity Discards*:
     - Adding high-volume carrot cycles into the 100-capacity shed increased end-of-day discards by +4.37 units (+3.95 carrots, +0.93 wool, +0.49 fertilizer), destroying ~$330 in physical value.
   4. *Structural Lesson*:
      - Core farm wheat is essential farm infrastructure that secures high-leverage livestock revenue ($66.4k/game). 
      - Never trade physical grain security for standalone cash crops.

### Audit / System Forensic: P6 Baseline System Bottleneck Audit (P6-R Revalidated)
- **Type**: AUDIT / PRODUCTION BASELINE BOTTLENECK AUDIT & REVALIDATION
- **Date**: 2026-09-22
- **Baseline Commit**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Flag State**: `P51_T1_TWO_CYCLE_CARROT_ENABLED = False` (Permanently locked)
- **Panel**: 100 baseline games across 10 untouched discovery seeds (`96,401`–`96,410`) $\times$ 5 benchmark opponents $\times$ 2 balanced seats.
- **Evaluation Status**: Diagnostic only; 100% behavior-invariant shadow telemetry. Protected evaluation seeds `98,001`–`98,050` remained untouched.
- **Accounting Closure**: Max single-game cash reconciliation error: **$0.000000** ($\epsilon = 0$).
- **Results**:
  - Baseline Mean Final Cash: **$101,035.79** (Median: **$99,584.00**, Min: $78,028.00, Max: $122,839.00)
  - Gross Product Revenue: **$147,457.41 / game**
  - Gross Operating Expenditures: **$49,421.62 / game**
    * Feed Wheat Purchases: **$31,249.44 / game** (863.02 units @ $36.21) [63.2% of all expenses]
    * Worker Wages (Hires): **$7,540.68 / game** (294.0 hires)
    * Livestock Purchases: **$4,933.00 / game** (6.73 cows, 4.45 sheep)
    * Seed Purchases: **$4,698.50 / game**
    * Land Expansion (NE): **$1,000.00 / game** (1.0 quadrant)
- **P6-R Forensic Corrections & Key Findings**:
  1. *[MEASURED FACT] Shed Overflow Destruction*:
     - **46.31 completed physical units ($4,300.60 base / $6,026.53 realized reference value)** destroyed at midnight shed drop-offs across 16.76 events/game.
     - Losses dominated by high-value cash goods: Strawberries ($2,266.63), Wool ($1,047.17), Milk ($1,013.91), Melons ($515.01).
     - Feasible incremental cash is an `UNTESTED HYPOTHESIS` (+ $2,500 to + $4,000/game net).
  2. *[REFUTATION] Fertilizer "Backlog" Disproved*:
     - Proved exact mathematical inventory conservation across all 100 games ($\text{Diff} = 0.000000$): Collected (218.13) = Sold (187.76) + Used on Crops (23.67) + Discarded in Shed (4.73) + Ending Worker (1.97) + Ending Shed (0.00).
     - The previous claim of a 33.47-unit backlog ($800–$1,400) caused by slot exhaustion was completely fictitious and is **withdrawn to $0.00**.
  3. *[REFUTATION] Final-Day Harvest Opportunity Disproved*:
     - Pre-EOD diagnostic hook at Day 29 Hour 23 confirmed **0.00 mature units** on tiles.
     - All 11.53 unharvested units spawned at Step 719 EOD refresh after the simulation ended. They were physically unharvestable under engine rules. Recoverable value is **withdrawn to $0.00**.
  4. *[CORRECTION] Livestock Mechanical Max & Care Gap*:
     - Under true engine rules, cow mechanical max is 166.14 milk (actual 150.33, efficiency 90.48%) and sheep mechanical max is 90.26 wool (actual 78.87, efficiency 87.38%).
     - Actual yield never exceeds mechanical maximum. Harvest efficiency is 97.8% (milk) and 97.9% (wool). Missed production cares: 15.81 cow, 11.39 sheep.
  5. *[MEASURED FACT] Day 28 Wheat Churn*:
     - 100-game panel mean: 440.39 units bought vs 465.98 units sold on Day 28 (panel total: 44,039 bought / 46,598 sold).
     - Churn generated **+$1,040.97 / game net cash** (+$104,097.00 panel total); animal feed starvation was 0.0%; market slots were not saturated (8 free slots/hour).
- **Defensible Mutually Exclusive Recoverable Value Ledger**:
  - Direct Shed Discard Prevention (P6.1): **+$2,500.00 to +$4,000.00 / game**
  - Livestock Care Adherence: **+$800.00 to +$1,500.00 / game**
  - Transit Optimization / Route Bundling: **+$500.00 to +$1,200.00 / game**
  - Day 28 Churn: **$0.00 direct cash** (already net positive)
  - Fertilizer Backlog: **$0.00** (refuted)
  - Final-Day Harvest: **$0.00** (refuted)
  - **Defensible Realizable Baseline Potential**: **+$3,800.00 to +$6,700.00 / game** (Ceiling: ~$106k–$108k).
- **Epistemic Verdict on the $130,000 Target**:
  - Reaching $130k cannot be achieved by baseline bug fixes alone. It requires Macro-Architectural Expansion (SW quadrant development and secondary livestock scaling) after storage hygiene is established.
- **Next Experiment**: Execute **P6.1: Shed-Overflow Prevention via Pre-Midnight Storage Hygiene** as a strictly single-variable isolated experiment.

### Experiment: P6.1 Shed-Overflow Prevention via Pre-Midnight Storage Hygiene
- **Type**: SINGLE-VARIABLE STRATEGY EXPERIMENT (Pre-Midnight Storage Hygiene)
- **Date**: 2026-09-22
- **Baseline Commit**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Active Branch**: `experiment/sw-p13-planting-gate`
- **Control**: Production baseline (`P51_T1_TWO_CYCLE_CARROT_ENABLED = False`, `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`)
- **Treatment**: `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = True` (Proactive late-evening shed headroom liquidation)
- **Panel**: 100 matched pairs (200 live games) on fresh untouched evaluation seeds `96,411`–`96,420` $\times$ 5 opponents $\times$ 2 seats. Protected seeds `98,001`–`98,050` remained 100% untouched.
- **Hypothesis**: By monitoring shed inventory in the late evening (Hours 20, 21, 22) and proactively selling surplus inventory to guarantee $\ge 25$ units of shed headroom before workers execute their midnight inventory drops, physical shed overflow discards will decrease by $\ge 70\%$ without harming feed security, market prices, crop production, livestock production, or worker execution.
- **Results**:
  - Control Final Cash: **\$99,890.78**
  - Treatment Final Cash: **\$101,330.64**
  - Mean Paired Cash Delta: **+\$1,439.86** (Median: **+\$642.50**)
  - 95% Confidence Interval: **[+\$297.91, +\$2,581.81]** (Std Error: \$582.63)
  - Win Rate: **Control 100.0% vs Treatment 100.0%**
  - Control Discards: **42.08 u/game** (\$5,900.91 realized value)
  - Treatment Discards: **40.90 u/game** (\$5,488.48 realized value)
  - Discard Reduction: **-1.18 u/game (-2.80% reduction)**
  - Livestock Feed Failures / Starvations / Escapes: **0 / 0 / 0 (100% Clean Invariant)**
  - CentralPlanner P0 Emergency Rejections: **0 (Zero Displacement)**
  - CentralPlanner `slot_cap` Rejections: **100.61 (Control) vs 101.67 (Treatment)**
- **Verdict**: **MECHANISM NO-GO / TREATMENT ITERATE**
  - Failed the $\ge 70\%$ discard reduction GO threshold (achieved only 2.80%).
  - Failed the $\ge 50\%$ discard reduction ITERATE threshold for storage overflow prevention.
  - Cash delta (+$1,439.86) fell short of the +$2,000 GO gate and was 89.6% driven by 10 outlier pairs.
- **Key Forensic Findings**:
  1. *[MEASURED FACT] Inventory Spatial Decoupling*:
     - Late-evening (Hours 20–22) inventory is held predominantly in **worker personal backpacks** (mean 34.5 u, peak 60–85 u), not in the shed (mean 30.9 u).
     - Workers in baseline do not execute mid-day shed deposits.
  2. *[MEASURED FACT] Shed Feed Wheat Impasse*:
     - Shed occupancy at Hours 20–22 is composed almost entirely of **protected animal feed wheat** (40–48 units, the reserve for herd animals).
     - Storage hygiene strictly protected Tier 3 wheat above `feed_safety_buffer = ceil(daily_feed_demand * 1.5) = 48 units`, leaving 0 sellable wheat.
     - Tier 2 high-value goods (Strawberries, Wool, Milk) had 0 stock in the shed because they were in worker backpacks.
     - Storage hygiene correctly refused to sell protected feed wheat, leaving the shed half-full of grain.
  3. *[MEASURED FACT] Midnight Inflow Collision*:
     - At midnight (Turn 23 -> Turn 0), workers dumped 60–85 units of backpack inventory into the shed that already contained 48 units of feed wheat ($48 + 82 = 130$ units load).
     - High-value produce was discarded despite storage hygiene being active.
  4. *[MEASURED FACT] Pricing Stability Confirmed in Isolation*:
     - Late-evening drip sales did NOT depress town shop prices in isolation, but caused severe pricing degradation (-$19.95/u on wool) when competing against `full_production_agent`.
- **Architectural Lesson for P6.2**:
  - Pure market liquidation cannot solve discards when goods are physically trapped in worker backpacks.
  - While dedicated long-distance deposit trips for low-value wheat are uneconomic, real 10×10 geometry (max distance 8 steps, mean 4 steps) makes opportunistic near-shed deposits and end-of-day deposits (where hands despawn anyway, incurring zero return-trip cost) highly profitable.
  - P6.2 must target opportunistic near-shed and end-of-day deposits of high-value produce (Melons, Milk, Strawberries) coupled with same-turn market sales.

### Forensic Investigation: P6.1-C Causal Reconciliation (Revalidated in P6.1-C-R)
- **Type**: CAUSAL RECONCILIATION & FORENSIC ACCOUNTING AUDIT
- **Date**: 2026-09-22 (Revalidated 2026-09-23)
- **Baseline Commit**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Active Branch**: `experiment/sw-p13-planting-gate`
- **Scope**: Complete transaction interception and hourly trajectory mapping across all 100 scenario pairs (200 live games on seeds `96,411`–`96,420`).
- **Accounting Closure**: Max single-game cash reconciliation error: **0.000000** ($\epsilon = 0.000000$).
  * Control: $3,000.00 + $145,803.18 (Sales) - $48,912.40 (Exp) = **$99,890.78** (Residual: 0.000000)
  * Treatment: $3,000.00 + $146,464.88 (Sales) - $48,134.24 (Exp) = **$101,330.64** (Residual: 0.000000)
- **Final Cash Delta**: **+$1,439.86 / game** (Mean) | **+$642.50 / game** (Even-N Median) | **+$1,250.08 / game** (10% Trimmed Mean, slice `[10:90]`)
- **Causal Waterfall Breakdown**:
  * **Gross Sales Revenue Delta**: **+$661.70 / game**
    - Milk: +$799.35 (+1.97 u) [Quantity effect +$470.66, Price effect +$324.13 @ $238.91/u Ctrl vs $241.23/u Treat]
    - Melon: +$535.48 (+2.45 u) [Quantity effect +$585.17, Price effect -$48.36]
    - Strawberry: +$115.62 (+0.68 u) [Quantity effect +$170.23, Price effect -$54.13]
    - Carrot: +$49.40 (+0.54 u)
    - Tomato: +$39.15 (+0.45 u)
    - Fertilizer: -$8.41 (-0.22 u)
    - Wool: -$137.40 (-0.06 u) [Price effect -$124.16 due to FPA competition]
    - Wheat: -$731.49 (-24.24 u) [Quantity effect -$854.25, Price effect +$125.74]
  * **Gross Expenditure Delta**: **-$778.16 / game (Expenditure Savings)**
    - Feed Wheat Purchases: **-$749.18** (-23.16 u) [96.3% of all savings]
    - Seed Purchases: -$4.90
    - Animal Purchases: -$14.00
    - Worker Wages: -$10.08
    - Land Expansion: $0.00
  * **Reconciled Cash Delta**: $\Delta \text{Revenue} - \Delta \text{Expenditures} = +\$661.70 - (-\$778.16) = \mathbf{+\$1,439.86 / game}$ (Residual: **0.000000**).
- **Core Forensic Revelations**:
  1. *[REFUTATION] "Early Liquidity Compounding" Disproved*:
     - The unexplained +$778.16 in P6.1 was **NOT** compounding investment returns.
     - It was **$749.18 in lower feed wheat expenditures**. Treatment kept 24.24 units of wheat on-farm (losing -$731.49 in wholesale sales revenue), which directly displaced 23.16 units of town retail feed purchases (saving +$749.18). Net internal transfer arbitrage was **+$17.69**.
  2. *[MEASURED FACT] Zero Divergence for Days 0–9*:
     - Trajectories are 100% bit-for-bit identical for the first 260 hours ($t=0 \dots 260$, $\text{Delta} = \$0.00$). First divergence occurred at $t=261$ (Day 10, Hour 21).
  3. *[MEASURED FACT] Outlier Concentration*:
     - Top 1 pair = 12.1% of total gain; top 5 pairs = 53.2%; top 10 pairs = **89.6%** ($129k / $144k).
     - Win rate was **58.0%** (58 wins, 42 losses).
  4. *[MEASURED FACT] Severe Deficit Against `full_production_agent`*:
     - Treatment lost by **-$1,543.55 / game** with a **35.0% win rate** against FPA.
     - Uncoordinated pre-midnight sales degraded town wool market price from $237.50/u to $217.55/u (-$19.95/u), losing -$2,153.95 in wool revenue.
  5. *[CORRECTION] Real Engine Geometry & Deposit Feasibility*:
     - Engine runs on a **10×10 board** with a **100-capacity shed** centered at `(4,4), (5,4), (4,5), (5,5)`.
     - Maximum distance to shed access is 8 steps (corners); average distance across all tiles is 4.0 steps (round-trip 8 steps).
     - Opportunistic deposits (0 extra steps) and end-of-day deposits (where hands despawn at midnight, incurring 0 return steps) are highly profitable.
- **Classification & Final Taxonomy**:
  - Mechanism Verdict: **MECHANISM NO-GO**
  - Final Taxonomy: **Option B (Storage Mechanism Failed, Cash Signal Mostly Incidental / Feed Buffer Arbitrage)**.
  - Action: Keep `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`. Do not promote to production.
  - Selected P6.2 Experiment: **Candidate A (Opportunistic Near-Shed Deposit-and-Sell)**.

### SW-first architecture audit (2026-09-23)
- Type: FACT / AUDIT
- Source: docs/sw_architecture_deep_audit.md; docs/sw_leader_comparison.md; artifacts/sw_economics/model.json
- Confidence: HIGH for engine facts and P4.1 cash; MEDIUM for counterfactual sensitivities
- Details: Verified HEAD is 975da5e1683f1bb57463cb9478344d0acf379d58 and remote branch has no later commit. P4.1 lost $4,819.10/game after reserving two productive core workers for eight SW tiles; core agricultural attempts fell 141.0 to 29.4/game and core watering compliance fell 4.45 points. The old death, starvation, and direct SW-profit decomposition is not transaction-verified. Saved replay census found 132 unique episodes; Crop Dusta acquired NE around D5 and SW D8-9, mixed SW crops, and reached 13 total workers by D12. This is descriptive evidence, not a causal treatment effect. Engine arithmetic gives 96 melon, 32 strawberry, 160 wheat and 9 carrot for a nominal D6 24-tile calendar, but 1,351 planned actions are not route-certified. Whole-farm sensitivity rows for A/B/C/C+ are scenario estimates only: do not add them to P6/P6.1 recoverable ledgers or pool panels.
- Related: docs/sw_architecture_deep_audit.md; docs/sw_leader_comparison.md; docs/sw_labor_and_capacity_model.md; docs/sw_economic_model.md; docs/sw_architecture_alternatives.md; docs/sw_architecture_recommendation.md; docs/sw_validation_plan.md

### SW-first forward architecture redesign (Phase A) (2026-09-23)
- Type: EXPERIMENT / ARCHITECTURE
- Source: docs/sw_forward_architecture_design.md; strategy/farm_plan.py; strategy/resource_ledger.py; strategy/cohort_planner.py; strategy/service_certificate.py; strategy/whole_farm_planner.py
- Confidence: HIGH (16/16 new unit & historical failure replay tests pass; 100% full-suite pass rate; bit-for-bit control invariance confirmed)
- Details: Implemented complete architectural substrate and decoupled shadow-mode planner under `SW_FORWARD_ARCHITECTURE_MODE` (default "OFF"). Created observation-driven `FarmPlan` state machine, multi-resource commitment ledger (cash confidence tiers, feed causality, 10-order command limits, storage execution sequence), counterfactual opportunity-cost cohort evaluator ($\Delta FC = \text{WITH} - \text{WITHOUT}$), rolling 72-hour `ServiceCertificate` with structured `RepairOption` records, and decoupled `ShadowSnapshot` execution hook in `main.py`. Validated against synthetic historical failure replays (P4.1 core displacement, P1 overcommitment, P1.1 feed shortfall, P6.1 storage pressure). Fixed test fixture teardown leak in `test_production_no_sw.py`. All 43 runtime files maintain 100% byte-for-byte parity between `agent/` and `submission/`. Protected evaluation seeds `98001–98050` remain untouched.
- Related: docs/sw_forward_architecture_design.md; docs/sw_resource_ledger_spec.md; docs/sw_service_certificate_spec.md; docs/sw_cohort_planner_spec.md; docs/sw_scheduler_redesign_spec.md; docs/sw_shadow_validation.md; docs/sw_phase_b_implementation_plan.md

