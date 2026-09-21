# Kaggriculture: Fresh Held-Out Production Validation Report

- Control SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e` (True Baseline, QUADRANT_HARD_BLOCK={4})
- Candidate Snapshot Fingerprint: `3403bf70d872202edc4493c734e0f30c9c979240a08d7e44e20a639baa316604`
- Engine Version: 1.32.7
- Total Matched Cases: 200 (balanced across 5 opponents and 2 seats)
- Fresh Seed Block: 81,001+
- Errors: 0

## 1. Overall Economic Comparison

| Metric | Control (True Baseline) | Candidate (P1.3-C) | Paired Delta / Impact |
|---|---:|---:|---:|
| **Mean Final Score** | **$103,237.65** | **$99,431.74** | **$-3,805.92** (95% CI: [$-4,971.56, $-2,640.28]) |
| Median Final Score | $103,174.00 | $98,720.00 | $-3,403.00 |
| Win / Tie / Loss | — | — | **62W / 0T / 138L** (p=0.0000) |
| Confirmed SW Acquisitions | 0 / 200 | 94 / 200 | +94 cases |
| Realized Crop Revenue | $0.00 | $0.00 | $+0.00 |
| Realized Animal Revenue | $0.00 | $0.00 | $+0.00 |
| Purchased Wheat Spend | $4,295,600.00 | $4,361,100.00 | $+65,500.00 |
| Animal Purchase Spend | $967,000.00 | $977,300.00 | $+10,300.00 |
| Land Expansion Spend | $200,000.00 | $388,000.00 | $+188,000.00 |
| Seed Purchase Spend | $934,490.00 | $999,000.00 | $+64,510.00 |

## 2. Animal Safety & Workload Realization

| Safety / Operational Metric | Control | Candidate (P1.3-C) | Difference |
|---|---:|---:|---:|
| Starvation Animal-Days (Hour 0) | 2585 | 3970 | +1385 |
| Starvation Animal-Hours (All Steps) | 62037 | 95251 | +33214 |
| Negative Cash Steps | 0 | 0 | +0 |
| NW+NE Productive Operations | 403705 | 393942 | -9763 |
| NW+NE Harvests Executed | 51940 | 50393 | -1547 |
| NW+NE Unwatered EOD | 28450 | 29322 | +872 |
| Scheduler Travel Distance | 882245 | 870708 | -11537 |
| SW Worker Turns | 19207 | 78619 | +59412 |

## 3. Performance Across Opponent Archetypes

| Opponent Archetype | Cases | Control Mean | Candidate Mean | Paired Delta | 95% CI | Win Rate |
|---|---:|---:|---:|---:|:---:|:---:|
| `pass` | 40 | $104,572.25 | $101,959.07 | $-2,613.18 | [$-4,498.33, $-728.02] | 13/40 (32.5%) |
| `pure_wheat_rush` | 40 | $101,511.38 | $97,535.55 | $-3,975.82 | [$-6,843.33, $-1,108.32] | 13/40 (32.5%) |
| `cow_milk_engine` | 40 | $102,691.38 | $99,147.23 | $-3,544.15 | [$-6,418.98, $-669.32] | 15/40 (37.5%) |
| `melon_sniper` | 40 | $104,254.15 | $98,224.55 | $-6,029.60 | [$-8,364.75, $-3,694.45] | 6/40 (15.0%) |
| `full_production_agent` | 40 | $103,159.12 | $100,292.27 | $-2,866.85 | [$-5,773.24, $+39.54] | 15/40 (37.5%) |

## 4. Livestock Serviceability Cap Diagnostics

- Total candidate purchase evaluations: 9896
- Total speculative animal candidates rejected: 19623
- Breakdown of rejection reasons:
  - `recent_animal_starvation`: 12287 rejections
  - `core_crop_survival_debt`: 6060 rejections
  - `feeding_deadline_infeasible`: 1276 rejections