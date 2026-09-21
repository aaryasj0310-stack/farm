# Kaggriculture: P2.1 Dynamic Strawberry Portfolio Optimization Report

- Control Baseline SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e` (True Production Baseline, QUADRANT_HARD_BLOCK={4})
- Treatment Fingerprint: `f03ae79e5592e013dbe610772ada04d6e74176777fb0e08d21c879db62e41cd5`
- Engine Version: 1.32.7
- Total Matched Cases: 100 (balanced across 5 opponents and 2 seats)
- Fresh Seed Block: 86,001+

## 1. Overall Economic Performance (Full 100 Matched Cases)

| Metric | Control (True Baseline) | Treatment (P2.1 Dynamic Strawberry) | Paired Delta / Impact |
|---|---:|---:|---:|
| **Mean Final Score** | **$102,955.63** | **$103,065.56** | **$+109.93** (95% CI: [$-67.84, $+287.70]) |
| Median Final Score | $102,295.50 | $102,295.50 | $+0.00 |
| Win / Tie / Loss | — | — | **4W / 95T / 1L** (p=0.2255) |
| Strawberry Tiles Planted | 1,472 | 1,469 | -3 tiles |
| Realized Strawberry Revenue | $2,000,627.00 | $1,997,566.00 | $-3,061.00 |
| Seed Purchase Spend | $467,550.00 | $467,430.00 | $-120.00 |
| Wheat Purchase Spend | $2,148,925.00 | $2,148,450.00 | $-475.00 |
| Animal Purchase Spend | $378,300.00 | $378,300.00 | $+0.00 |

## 2. Breakdown Across Opponent Archetypes

| Opponent Archetype | Cases | Control Mean | Treatment Mean | Paired Delta | 95% CI | Win Rate |
|---|---:|---:|---:|---:|:---:|:---:|
| `pass` | 20 | $100,702.85 | $100,702.85 | $+0.00 | [$+0.00, $+0.00] | 0/20 (0.0%) |
| `pure_wheat_rush` | 20 | $103,784.60 | $103,784.60 | $+0.00 | [$+0.00, $+0.00] | 0/20 (0.0%) |
| `cow_milk_engine` | 20 | $103,178.15 | $103,376.50 | $+198.35 | [$-561.97, $+958.67] | 2/20 (10.0%) |
| `melon_sniper` | 20 | $108,875.20 | $109,226.50 | $+351.30 | [$-122.59, $+825.19] | 2/20 (10.0%) |
| `full_production_agent` | 20 | $98,237.35 | $98,237.35 | $+0.00 | [$+0.00, $+0.00] | 0/20 (0.0%) |

## 3. Operational Safety & Core Farm Integrity

- Negative Cash Steps: Control=0, Treatment=0
- NW+NE Productive Operations: Control=201,905, Treatment=201,876 (Delta: -29)
- NW+NE Harvests Realized: Control=26,056, Treatment=26,054 (Delta: -2)
- NW+NE Unwatered EOD: Control=14,706, Treatment=14,717 (Delta: +11)
- Starvation Animal-Days: Control=1487, Treatment=1484
- Total P2.1 Dynamic Cap Checks: 67200

## 4. Promotion Decision

> **TENTATIVE / INCONCLUSIVE**: P2.1 showed a positive mean delta but did not achieve full statistical significance at the 95% level. Do not promote without further validation.