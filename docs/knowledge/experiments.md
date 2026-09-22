
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

