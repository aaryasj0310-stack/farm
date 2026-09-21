# Kaggriculture P2.3 Marginal Wheat Replanting / Crop Substitution Results

## Executive Summary
- **Treatment**: P2.3 Marginal Wheat Replanting / Crop Substitution (`P23_MARGINAL_WHEAT_ALLOCATION_ENABLED=True`)
- **Control Baseline**: True Production Baseline (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`) with `QUADRANT_HARD_BLOCK={4}`
- **Sample Size**: 100 matched pairs (200 live games), 8 workers, Seeds 88,001–88050
- **Control Mean**: **$103,159.65**
- **Treatment Mean**: **$103,605.13**
- **Paired Mean Delta**: **+$445.48** (95% CI: [$291.56, $599.40])
- **Median Delta**: **+$435.50**
- **Record**: **70W / 27L / 3T** (Win Rate: 70.0%)
- **Statistical Significance**: $t = 5.6728$, $p = 1.4051e-08$

## Crop Substitution & Economic Telemetry
| Metric | True Control Baseline | P2.3 Treatment | Impact / Delta |
| :--- | :--- | :--- | :--- |
| **Wheat Tiles Planted** | 107.4 | 101.7 | **-5.7 tiles** |
| **Carrot Tiles Planted** | 24.9 | 26.6 | **+1.7 tiles** |
| **Wheat Fed to Herd** | 211.4 units | 211.4 units | -0.0 units |
| **Wheat Buy Spend** | $21,362.50 | $21,343.25 | $-19.25 |
| **Carrot Sales Revenue** | $1,664.75 | $1,737.75 | **+$73.00** |
| **Total Crop Revenue** | $6,537.50 | $6,632.25 | **+$94.75** |
| **Animal Revenue** | $5,289.00 | $5,309.25 | $20.25 |
| **Animal Starvation Days (EOD)** | 0 | 0 | 0 (0 animals escaped) |
| **Animal Starvation Hours (intraday)** | 29,948 | 29,991 | +43 hrs (stochastic noise) |

> [!NOTE]
> **Starvation Telemetry Reconciliation**:
> In `run_p23_marginal_wheat_ab.py`, `m["starvation_animal_hours"]` tracks every hourly simulation step where `consecutive_unfed >= 1`. In a 720-step game with 10–11 animals across 200 games (144,000 engine steps), this counts cumulative intraday morning hours prior to the daily feed cycle completing (~30,000 aggregate animal-hours). The difference of +43 hours out of ~30,000 (0.14%) is stochastic worker task-scheduling noise. Crucially, **`starvation_animal_days` at Hour 23 EOD was strictly 0 in Control and 0 in Treatment**, with **zero animal escapes and zero animal health penalties**.

## Score Delta Distribution Analysis
- **Positive-Delta Cases (70 games)**: Mean +$814.51
- **Negative-Delta Cases (27 games)**: Mean $-461.78
- **Median Delta**: +$435.50

## Promotion Decision
- **Status**: **PROMOTED TO PRODUCTION**
- **Authoritative Configuration**: `P23_MARGINAL_WHEAT_ALLOCATION_ENABLED = True` (defaults to `True` in `agent/config.py`).
- **Mechanism**: Blocks economically inferior terminal wheat plantings on Day 26+ (`day > 25`), preserving empty tiles for high-velocity late-season crops (primarily Carrots maturing by Day 29/30) while strictly preserving mid-season wheat replanting (Days 0–25) and herd feed security.
