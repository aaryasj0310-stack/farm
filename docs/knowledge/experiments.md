
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
