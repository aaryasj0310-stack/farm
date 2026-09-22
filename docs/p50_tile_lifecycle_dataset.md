# P5.0 Diagnostic Audit: 100-Game Tile Lifecycle Dataset

## Executive Summary

This document establishes the empirical dataset for **Kaggriculture P5.0 — Within-Core Marginal Tile & Input Value Audit**.
The dataset comprises **100 completed, fully instrumented tournament-format games** evaluated against the authoritative Promoted P2.3 Production Baseline behavior (`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`).

All 100 games satisfied strict methodological invariants:
1. **Action/Runtime Equivalence**: Evaluated on execution branch `experiment/sw-p13-planting-gate` with all experimental flags OFF, producing bit-for-bit action identical traces to baseline commit `536f1e7`.
2. **Fresh Diagnostic Seed Panel**: Evaluated strictly on 10 fresh seeds (`96,201–96,210`). The formal reserved tournament block (`98,001–98,050`) remains untouched.
3. **Balanced Opponent & Seat Matrix**: 10 seeds × 5 standard opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`) × 2 seats (Seat 0 & Seat 1) = 100 live matches.
4. **100% Exact Cash Reconciliation**: Engine cash flow invariant:
   $$\text{Starting Cash }(\$3,000) + \text{Inflows} - \text{Outflows} = \text{Final Cash} = \text{Final Reward}$$
   Maximum discrepancy across all 100 games: **$0.000000** (0.00% error).

---

## Overall Baseline Performance Panel

| Metric | Empirical Value | Notes / Benchmarks |
| :--- | :--- | :--- |
| **Total Completed Games** | **100** | 10 seeds × 5 opponents × 2 seats |
| **Mean Baseline Reward** | **$102,300.11** | Historical expectation: ~$101.9k – $103.6k |
| **Standard Deviation** | **$9,493.20** | Season-to-season yield and pricing volatility |
| **Median Baseline Reward** | **$102,708.00** | Robust central tendency |
| **Reward Range (Min / Max)** | **$75,878.00 / $121,238.00** | Min on Seed 96202 vs melon_sniper; Max on 96206 vs full_prod |
| **Cash Reconciliation Delta** | **$0.000000** | Exact machine precision across all 72,100 steps |

---

## Opponent-Segmented Performance Breakdown

| Opponent Agent | Games ($N$) | Mean Score ($) | Std Dev ($) | Min Score ($) | Max Score ($) | Win Rate vs Opp |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` | 20 | $102,156.55 | $8,256.75 | $81,622.00 | $112,214.00 | 100.0% |
| `pure_wheat_rush` | 20 | $101,313.35 | $9,213.08 | $77,272.00 | $111,822.00 | 100.0% |
| `cow_milk_engine` | 20 | $99,161.85 | $9,384.15 | $77,935.00 | $115,368.00 | 100.0% |
| `melon_sniper` | 20 | $103,280.75 | $10,391.06 | $75,878.00 | $119,472.00 | 100.0% |
| `full_production_agent` | 20 | $105,588.05 | $9,832.64 | $88,325.00 | $121,238.00 | 100.0% |

---

## Seat Balance Verification

| Seat | Games ($N$) | Mean Reward ($) | Std Dev ($) | Delta vs Pooled Mean |
| :---: | :---: | :---: | :---: | :---: |
| **Seat 0 (Player 1)** | 50 | $101,657.86 | $10,272.87 | -$642.25 (-0.63%) |
| **Seat 1 (Player 2)** | 50 | $102,942.36 | $8,701.00 | +$642.25 (+0.63%) |

The seat bias is negligible (<0.65%), confirming that order-of-execution effects at the market boundary are properly balanced.

---

## Telemetry Volume Summary

Across the 100 live baseline games:
- **Physical Tiles Tracked**: 50 physical tiles per game × 100 games = **5,000 tile-seasons** (150,000 tile-days).
- **Wheat Planting Decisions**: **10,146** decisions audited (101.5/game).
- **Fertilizer Applications**: **2,428** applications audited (24.3/game).
- **Replacement Feasibility Probes**: **60,100** hour-specific probes across Days 15–26.
- **Idle Tile-Days Recorded**: **19,814** tile-days audited (198.1/game).
