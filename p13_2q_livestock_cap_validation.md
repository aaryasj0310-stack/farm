# Kaggriculture: 2-Quadrant Livestock Serviceability Cap Salvage Report

- Control Baseline SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e` (True Baseline, QUADRANT_HARD_BLOCK={4})
- Worktree Candidate Fingerprint: `fc502660e75334e024d3f4a1b5a6bb1c539a788113d468e6ec32e38c6708a49a`
- Engine Version: 1.32.7
- Total Matched Cases: 100 (balanced across 5 opponents and 2 seats)
- Fresh Seed Block: 83,001+
- SW Acquisitions: Control=0/100, Capped=0/100

## 1. Overall Economic Performance

| Metric | Control (True 2Q Baseline) | Capped (2Q + Livestock Cap) | Paired Delta / Impact |
|---|---:|---:|---:|
| **Mean Final Score** | **$103,570.20** | **$103,252.77** | **$-317.43** (95% CI: [$-1,588.36, $+953.50]) |
| Median Final Score | $104,748.00 | $104,425.00 | $+132.00 |
| Win / Tie / Loss | — | — | **51W / 0T / 49L** (p=0.6245) |
| Purchased Wheat Spend | $2,127,100.00 | $1,850,575.00 | $-276,525.00 |
| Animal Purchase Spend | $472,100.00 | $450,700.00 | $-21,400.00 |
| Seed Purchase Spend | $470,440.00 | $480,610.00 | $+10,170.00 |
| Land Expansion Spend | $100,000.00 | $100,000.00 | $+0.00 |

## 2. Animal Safety & Core Realization

| Metric | Control | Capped | Impact |
|---|---:|---:|---:|
| Starvation Animal-Days (Hour 0) | 1219 | 764 | -455 |
| Starvation Animal-Hours (All Steps) | 29254 | 18333 | -10921 |
| Negative Cash Steps | 0 | 0 | +0 |
| NW+NE Productive Operations | 202040 | 202331 | +291 |
| NW+NE Harvests Realized | 26043 | 26077 | +34 |
| NW+NE Unwatered EOD | 13614 | 13006 | -608 |
| Scheduler Travel Distance | 439484 | 438348 | -1136 |

## 3. Breakdown Across Opponent Archetypes

| Opponent Archetype | Cases | Control Mean | Capped Mean | Paired Delta | 95% CI | Win Rate |
|---|---:|---:|---:|---:|:---:|:---:|
| `pass` | 20 | $102,620.25 | $103,620.70 | $+1,000.45 | [$-2,215.45, $+4,216.35] | 12/20 (60.0%) |
| `pure_wheat_rush` | 20 | $108,569.30 | $110,708.10 | $+2,138.80 | [$+612.44, $+3,665.16] | 15/20 (75.0%) |
| `cow_milk_engine` | 20 | $101,976.70 | $102,431.95 | $+455.25 | [$-3,090.51, $+4,001.01] | 8/20 (40.0%) |
| `melon_sniper` | 20 | $106,272.60 | $103,626.05 | $-2,646.55 | [$-5,449.90, $+156.80] | 10/20 (50.0%) |
| `full_production_agent` | 20 | $98,412.15 | $95,877.05 | $-2,535.10 | [$-4,814.52, $-255.68] | 6/20 (30.0%) |

## 4. Livestock Cap Diagnostics

- Total candidate purchase evaluations: 4645
- Total speculative animal candidates rejected: 9163
- Breakdown of rejection reasons:
  - `core_crop_survival_debt`: 3604 rejections
  - `feeding_deadline_infeasible`: 223 rejections
  - `recent_animal_starvation`: 5336 rejections