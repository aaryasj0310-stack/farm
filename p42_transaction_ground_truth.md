# Kaggriculture P4.2 Phase 2 Audit: Transaction Ground-Truth Telemetry

## 1. Experimental Setup & Protocol Compliance

The P4.2 ground-truth transaction audit was conducted across a balanced panel:
- **Baseline Lineage**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Authoritative Production Baseline; historically ~$103.6k on P2.3 discovery panel, ~$101.9k on independent held-out panel).
- **Sample Arithmetic**: 10 fresh seeds (`96,101–96,110`) $\times$ 5 standard opponents $\times$ 2 balanced seats = **100 live baseline games**.
- **Opponents**: `pass` (20), `pure_wheat_rush` (20), `cow_milk_engine` (20), `melon_sniper` (20), `full_production_agent` (20).
- **Engine Instrumentation**: Kaggle Environments v1.32.7 with per-unit lockstep transaction interception (`kagg._commit_unit` and `kagg._town_consume`). Every individual unit sold was logged with its exact integer price and post-trade inventory.
- **Seat Balance**: Exactly 50 games in Seat 0 and 50 games in Seat 1.
- **Completion**: 100 / 100 games completed successfully (0 failures, 0 desyncs).

---

## 2. Global Performance & Distribution

Across all 100 games:
- **Mean Final Cash**: **$102,986.19**
- **Median Final Cash**: **$103,717.50**
- **Standard Deviation**: **$8,724.54**
- **Min Final Cash**: $76,731.00 (Seed 96106 vs pass, Seat 0)
- **Max Final Cash**: $120,812.00 (Seed 96103 vs cow_milk_engine, Seat 1)

### Opponent Breakdown:
| Opponent | Games | Mean Final Cash | Median Final Cash | Std Dev |
| :--- | :--- | :--- | :--- | :--- |
| `pass` | 20 | $101,586.45 | $103,731.50 | $10,123.82 |
| `cow_milk_engine` | 20 | $101,013.20 | $105,133.50 | $10,814.73 |
| `pure_wheat_rush` | 20 | $105,805.90 | $104,890.00 | $6,979.61 |
| `melon_sniper` | 20 | $103,044.50 | $103,249.00 | $6,373.16 |
| `full_production_agent` | 20 | $103,480.90 | $106,301.00 | $8,294.27 |
| **All Opponents** | **100** | **$102,986.19** | **$103,717.50** | **$8,724.54** |

---

## 3. Transaction Volume & Execution Telemetry

- **Total Market Transactions**: **25,463** market orders executed across 100 games.
- **Mean Transactions per Game**: **254.63 orders/game**.
- **Total Physical Product Units Sold**: **165,550 units** across 100 games (**1,655.5 units/game**).
- **Total Gross Revenue Realized**: **$14,767,760.00** across 100 games (**$147,677.60/game**).
- **Net Operating Margin**:
  - Gross Product Revenue: **$147,677.60/game**
  - Operating Expenditures (Seeds, Hires, Animal Purchases, Land): **-$44,691.41/game**
  - Realized Final Cash: **$102,986.19/game** (69.7% cash conversion efficiency).

---

## 4. Integrity Verification

1. **Exact Per-Unit Settlement**:
   Every transaction verified that the sum of per-unit committed prices matched the cash credited to `farm["money"]`. No discrepancy between quoted prices and settled cash was observed.
2. **End-of-Season Liquidation**:
   Across all 100 games, **zero units** remained unsold in the shed at Day 30 Hour 0 (`unsold_shed_per_game = 0.00`).
3. **Storage Discard Rate**:
   Across all 100 games, **zero units** were discarded due to shed overflow. The two-tier shed relief mechanism (`SHED_SOFT_CAP = 65`, `SHED_RESUME_CAP = 55`, midnight guard at 88) successfully prevented overflow discards.
