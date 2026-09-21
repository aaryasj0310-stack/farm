# Kaggriculture: P2.0 Dynamic Second Melon Tranche Report

- Control Baseline SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e` (True Production Baseline, QUADRANT_HARD_BLOCK={4})
- Treatment Fingerprint: `5eae3825664866383dc1b43fbc8d0692563c3528b8a30ff84d3ede656f5e54c3`
- Engine Version: 1.32.7
- Total Matched Cases: 100 (balanced across 5 opponents and 2 seats)
- Fresh Seed Block: 85,001+
- P20 Treatment Activated: 82/100 (82.0%)

## 1. Overall Economic Performance (Full 100 Matched Cases)

| Metric | Control (True Baseline) | Treatment (P2.0 Second Melon) | Paired Delta / Impact |
|---|---:|---:|---:|
| **Mean Final Score** | **$103,588.21** | **$103,546.03** | **$-42.18** (95% CI: [$-1,042.05, $+957.69]) |
| Median Final Score | $103,107.50 | $102,395.00 | $+0.00 |
| Win / Tie / Loss | — | — | **41W / 18T / 41L** (p=0.9341) |
| Realized Melon Revenue | $2,162,133.00 | $2,214,207.00 | $+52,074.00 |
| Seed Purchase Spend | $464,820.00 | $487,650.00 | $+22,830.00 |
| Wheat Purchase Spend | $2,204,825.00 | $2,205,200.00 | $+375.00 |
| Animal Purchase Spend | $373,500.00 | $371,200.00 | $-2,300.00 |

## 2. Activation-Only Subgroup Analysis

In 82 of 100 cases, the evaluator authorized a second melon tranche ($k^* > 0$).

| Metric | Control in Subgroup | Treatment in Subgroup | Subgroup Delta |
|---|---:|---:|---:|
| **Mean Final Score** | **$102,546.59** | **$102,495.15** | **$-51.44** (95% CI: [$-1,272.13, $+1,169.26]) |
| Subgroup Record | — | — | **41W / 0T / 41L** (p=0.9342) |
| Mean Tranche Size | — | 6.4 tiles | — |
| Melon Revenue Delta | — | — | $+52,074.00 |
| Core Harvests Delta | — | — | +0.0 harvests |

## 3. Breakdown Across Opponent Archetypes

| Opponent Archetype | Cases | Control Mean | Treatment Mean | Paired Delta | 95% CI | Win Rate |
|---|---:|---:|---:|---:|:---:|:---:|
| `pass` | 20 | $99,791.60 | $98,606.90 | $-1,184.70 | [$-3,362.18, $+992.78] | 6/20 (30.0%) |
| `pure_wheat_rush` | 20 | $105,520.65 | $106,173.00 | $+652.35 | [$-2,023.67, $+3,328.37] | 8/20 (40.0%) |
| `cow_milk_engine` | 20 | $105,717.80 | $105,390.40 | $-327.40 | [$-2,531.84, $+1,877.04] | 4/20 (20.0%) |
| `melon_sniper` | 20 | $103,600.25 | $104,405.55 | $+805.30 | [$-1,504.36, $+3,114.96] | 12/20 (60.0%) |
| `full_production_agent` | 20 | $103,310.75 | $103,154.30 | $-156.45 | [$-2,006.68, $+1,693.78] | 11/20 (55.0%) |

## 4. Operational Safety & Core Farm Integrity

- Negative Cash Steps: Control=0, Treatment=0
- NW+NE Productive Operations: Control=202,417, Treatment=202,509 (Delta: +92)
- NW+NE Harvests Realized: Control=0, Treatment=0 (Delta: +0)
- NW+NE Unwatered EOD: Control=14,286, Treatment=14,255 (Delta: -31)
- Starvation Animal-Days: Control=1622, Treatment=1475
- Total Second Melon Admission Checks: 60000
- Second Wave Melon Plantings: 58 tiles

## 5. Promotion Decision

> **PROMOTION REJECTED**: P2.0 did not improve final score over True Production Control. Discard treatment and advance to the next portfolio hypothesis.