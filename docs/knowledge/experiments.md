
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
  1. The production selling layer is near-optimal: 100% of harvested products are monetized with 0 unsold units at season end and 0 overflow discards.
  2. Post-town-drain sell window (`hour % 4 == 1`) reliably captures peak local prices as town shops consume 1.0 to 3.5 units per 4h cycle.
  3. Drip-selling slippage is <1.5% across all fragile goods (0.7% strawberry, 1.4% milk, 1.0% wool, 1.9% melon).
  4. Max market orders in any turn was 9 (cap is 10); 10-order cap displacement is exactly 0.0/game.
  5. Non-hindsight, live-actionable market opportunity ceiling is bounded at <= +$45 to +$65/game, which is <0.75% of the $8,724.54 standard deviation. No treatment justified; untouched seed block 98,001–98,050 preserved.


